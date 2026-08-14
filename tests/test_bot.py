import asyncio
from types import SimpleNamespace as NS

from newsbot.bot import news_command


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
