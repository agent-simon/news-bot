import asyncio
from types import SimpleNamespace as NS

import pytest

from newsbot import bot
from newsbot.bot import daily_job, news_command, status_command


def test_news_command_rejects_unauthorized_chat(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    update = NS(
        effective_chat=NS(id=456),
        message=NS(reply_text=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())),
    )
    monkeypatch.setattr(
        "newsbot.bot._fetch_and_summarize",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    asyncio.run(news_command(update, NS()))


def test_news_command_allows_configured_chat(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    replies = []

    async def reply_text(text, **kwargs):
        replies.append((text, kwargs))

    update = NS(effective_chat=NS(id=123), message=NS(reply_text=reply_text))
    async def fetch_and_summarize(**_kwargs):
        return [], [{"text": "No news", "links": []}]

    monkeypatch.setattr("newsbot.bot._fetch_and_summarize", fetch_and_summarize)
    monkeypatch.setattr("newsbot.bot._send", lambda *_args: asyncio.sleep(0))

    asyncio.run(news_command(update, NS()))

    assert replies == [("Fetching news...", {})]


def test_concurrent_news_command_is_rejected(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    replies = []
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def reply_text(text, **kwargs):
        replies.append((text, kwargs))

    async def fetch_and_summarize(**_kwargs):
        calls.append("fetch")
        started.set()
        await release.wait()
        return [], [{"text": "No news", "links": []}]

    monkeypatch.setattr(bot, "_fetch_and_summarize", fetch_and_summarize)
    monkeypatch.setattr(bot, "_send", lambda *_args: asyncio.sleep(0))
    update = NS(effective_chat=NS(id=123), message=NS(reply_text=reply_text))

    async def run():
        first = asyncio.create_task(news_command(update, NS()))
        await started.wait()
        await news_command(update, NS())
        release.set()
        await first

    asyncio.run(run())

    assert calls == ["fetch"]
    assert [text for text, _kwargs in replies] == [
        "Fetching news...",
        bot.NEWS_BUSY_MESSAGE,
    ]


@pytest.mark.parametrize("failure", [False, True])
def test_news_run_lock_is_released_after_completion_or_failure(monkeypatch, failure):
    calls = []

    async def fetch_and_summarize(**_kwargs):
        if failure:
            return None, None
        return [], [{"text": "No news", "links": []}]

    async def send(text, **_kwargs):
        calls.append(text)

    monkeypatch.setattr(bot, "_fetch_and_summarize", fetch_and_summarize)
    monkeypatch.setattr(bot, "_send", lambda *_args: asyncio.sleep(0))

    async def run():
        assert await bot._run_news(send, started_text="Started") is (not failure)
        assert await bot._run_news(send, started_text="Started again") is (not failure)

    asyncio.run(run())

    assert calls.count("Started") == 1
    assert calls.count("Started again") == 1


def test_daily_job_skips_when_news_run_is_active(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    calls = []

    async def send_message(**kwargs):
        calls.append(kwargs)

    async def fetch_and_summarize(**_kwargs):
        raise AssertionError("daily job should not collect while busy")

    monkeypatch.setattr(bot, "_fetch_and_summarize", fetch_and_summarize)

    async def run():
        await bot._news_run_lock.acquire()
        try:
            await daily_job(NS(bot=NS(send_message=send_message)))
        finally:
            bot._news_run_lock.release()

    asyncio.run(run())

    assert calls == []


def test_news_command_rejects_when_chat_id_is_missing(monkeypatch):
    monkeypatch.delenv("CHAT_ID", raising=False)
    update = NS(
        effective_chat=NS(id=123),
        message=NS(reply_text=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())),
    )
    monkeypatch.setattr(
        "newsbot.bot._fetch_and_summarize",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    asyncio.run(news_command(update, NS()))


def test_status_command_reports_runtime_configuration(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("DAILY_NEWS", "off")
    monkeypatch.setenv("WEB_SEARCH", "false")
    replies = []

    async def reply_text(text, **_kwargs):
        replies.append(text)

    update = NS(effective_chat=NS(id=123), message=NS(reply_text=reply_text))
    monkeypatch.setattr("newsbot.bot.load_config", lambda: {"sources": [{}, {}]})

    asyncio.run(status_command(update, NS()))

    assert replies == [
        "News bot status\n"
        "Daily news: disabled\n"
        "Web search: disabled (RSS only)\n"
        "RSS feeds: 2\n"
        "Schedule: disabled"
    ]


def test_status_command_reports_enabled_schedule(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.delenv("DAILY_NEWS", raising=False)
    monkeypatch.delenv("WEB_SEARCH", raising=False)
    monkeypatch.setattr("newsbot.bot.load_config", lambda: {"sources": [{}]})
    replies = []

    async def reply_text(text, **_kwargs):
        replies.append(text)

    update = NS(effective_chat=NS(id=123), message=NS(reply_text=reply_text))
    asyncio.run(status_command(update, NS()))

    assert "Daily news: enabled" in replies[0]
    assert "Web search: enabled" in replies[0]
    assert "RSS feeds: 1" in replies[0]
    assert "Schedule: 08:00 America/New_York" in replies[0]


def test_status_command_reports_source_configuration_error(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setattr("newsbot.bot.load_config", lambda: (_ for _ in ()).throw(ValueError()))
    replies = []

    async def reply_text(text, **_kwargs):
        replies.append(text)

    update = NS(effective_chat=NS(id=123), message=NS(reply_text=reply_text))
    asyncio.run(status_command(update, NS()))

    assert "RSS feeds: Configuration error" in replies[0]


def test_status_command_rejects_unauthorized_chat(monkeypatch):
    monkeypatch.setenv("CHAT_ID", "123")
    update = NS(
        effective_chat=NS(id=456),
        message=NS(reply_text=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())),
    )

    asyncio.run(status_command(update, NS()))
