import asyncio
from types import SimpleNamespace as NS

import pytest

from newsbot import bot, pipeline, render


def _model_response():
    text = '{"items":[{"i":0,"emoji":"🚀","summary":"Model summary"}]}'
    return NS(
        status="completed",
        output_text=text,
        output=[NS(type="message", phase="final_answer", content=[NS(type="output_text", text=text)])],
    )


def _items():
    return [
        {
            "title": "<Release>",
            "link": "https://example.com/article?utm_source=rss",
            "summary": "RSS summary",
            "source": "RSS",
        }
    ]


def test_workflow_deduplicates_renders_and_persists_seen_links(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    async def run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", run_sync)
    monkeypatch.setattr(pipeline, "fetch_new_items", lambda: _items())
    monkeypatch.setattr(
        pipeline,
        "search_web",
        lambda _include_themes: [{**_items()[0], "link": "https://www.example.com/article/"}],
    )
    monkeypatch.setattr(render, "get_client", lambda: NS(responses=NS(
        create=lambda **_kwargs: _model_response()
    )))

    sent = []

    async def send(text, **kwargs):
        sent.append((text, kwargs))

    async def run():
        items, entries = await bot._fetch_and_summarize(include_themes=True)
        assert len(items) == 1
        assert "&lt;Release&gt;" in entries[1]["text"]
        await bot._send(send, entries)

    asyncio.run(run())

    assert len(sent) == 1
    assert "Model summary" in sent[0][0]
    assert "https://example.com/article?utm_source=rss" in sent[0][0]

    from newsbot.dedup import load_seen

    assert load_seen() == {"https://example.com/article"}


def test_workflow_leaves_failed_delivery_unseen(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    async def run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(bot.asyncio, "to_thread", run_sync)
    monkeypatch.setattr(pipeline, "fetch_new_items", lambda: _items())
    monkeypatch.setattr(pipeline, "search_web", lambda _include_themes: [])
    monkeypatch.setattr(render, "get_client", lambda: NS(responses=NS(
        create=lambda **_kwargs: _model_response()
    )))

    async def send(_text, **_kwargs):
        raise RuntimeError("Telegram unavailable")

    async def run():
        items, entries = await bot._fetch_and_summarize()
        with pytest.raises(RuntimeError, match="Telegram unavailable"):
            await bot._send(send, entries)
        return items

    assert asyncio.run(run())

    from newsbot.dedup import load_seen

    assert load_seen() == set()
