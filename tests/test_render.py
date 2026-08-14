from types import SimpleNamespace as NS

from newsbot.config import EMOJI_PATTERN, SUMMARY_PATTERN
from newsbot.render import _render, summarize


def _response(payload, status="completed"):
    text = payload
    return NS(
        status=status,
        output_text=text,
        output=[NS(type="message", phase="final_answer", content=[NS(type="output_text", text=text)])],
    )


def test_render_keeps_local_title_and_link():
    items = [{"title": "<Title>", "link": "https://example.com/a", "summary": "Raw", "source": "Source"}]
    entries = _render(items, {0: {"emoji": "🚀", "summary": "Model"}})
    assert "&lt;Title&gt;" in entries[1]["text"]
    assert "https://example.com/a" in entries[1]["text"]
    assert "Model" in entries[1]["text"]


def test_render_escapes_model_emoji_html():
    items = [{"title": "Title", "link": "", "summary": "Raw"}]
    entries = _render(items, {0: {"emoji": "<b>injected</b>", "summary": "Model"}})

    assert "&lt;b&gt;injected&lt;/b&gt;" in entries[1]["text"]
    assert "<b>injected</b>" not in entries[1]["text"]


def test_render_bounds_emoji_and_summary_lengths():
    items = [{"title": "Title", "link": "", "summary": "fallback " * 100}]
    entries = _render(items, {0: {"emoji": "😀" * 17, "summary": "model " * 200}})

    assert "🔹 <b>Title</b>" in entries[1]["text"]
    assert "model " * 99 in entries[1]["text"]
    assert "model " * 100 not in entries[1]["text"]
    assert entries[1]["text"].endswith("model…")


def test_render_bounds_raw_fallback_summary():
    items = [{"title": "Title", "link": "", "summary": "raw" * 250}]
    entries = _render(items, {})

    assert entries[1]["text"].endswith("…")
    assert len(entries[1]["text"].split("\n", 1)[1]) == 600


def test_summarize_empty_does_not_call_client(monkeypatch):
    monkeypatch.setattr("newsbot.render.get_client", lambda: (_ for _ in ()).throw(AssertionError()))
    assert summarize([]) == [{"text": "📰 No new relevant items today.", "links": []}]


def test_summarize_uses_responses_and_maps_items(monkeypatch):
    calls = []
    response = _response('{"items":[{"i":0,"emoji":"🚀","summary":"Summary"}]}')

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    monkeypatch.setattr("newsbot.render.get_client", lambda: NS(responses=Responses()))
    entries = summarize([{"title": "Title", "link": "https://example.com", "summary": "Raw"}])
    assert "Summary" in entries[1]["text"]
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["store"] is False
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    properties = calls[0]["text"]["format"]["schema"]["properties"]["items"]["items"]["properties"]
    assert properties["emoji"]["pattern"] == EMOJI_PATTERN
    assert properties["summary"]["pattern"] == SUMMARY_PATTERN


def test_summarize_incomplete_response_falls_back(monkeypatch):
    monkeypatch.setattr("newsbot.render.get_client", lambda: NS(responses=NS(
        create=lambda **kwargs: _response("", status="incomplete")
    )))
    entries = summarize([{"title": "Title", "link": "https://example.com", "summary": "Raw"}])
    assert "Raw" in entries[1]["text"]


def test_summarize_ignores_invalid_indices(monkeypatch):
    response = _response('{"items":[{"i":99,"emoji":"x","summary":"bad"},"bad"]}')
    monkeypatch.setattr("newsbot.render.get_client", lambda: NS(responses=NS(
        create=lambda **kwargs: response
    )))
    entries = summarize([{"title": "Title", "link": "https://example.com", "summary": "Raw"}])
    assert "Raw" in entries[1]["text"]
