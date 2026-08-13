from datetime import UTC, datetime
from types import SimpleNamespace as NS

from newsbot.websearch import (
    _parse_published_date,
    _results_to_items,
    _search_source_urls,
    _source_name,
    _web_search,
)


def test_parse_published_date_accepts_iso_values():
    assert _parse_published_date("2026-01-15") == datetime(2026, 1, 15, tzinfo=UTC)
    assert _parse_published_date("2026-01-15T12:30:00Z") == datetime(2026, 1, 15, 12, 30, tzinfo=UTC)


def test_parse_published_date_rejects_unknown_values():
    assert _parse_published_date("") is None
    assert _parse_published_date(None) is None
    assert _parse_published_date("sometime last spring") is None


def test_search_source_urls_reads_sources_and_citations():
    response = NS(output=[
        NS(type="web_search_call", action=NS(
            type="search",
            sources=[NS(url="https://www.example.com/article?utm_source=x")],
        )),
        NS(type="web_search_call", action=NS(type="open_page", url="https://other.org/page")),
        NS(type="message", content=[NS(type="output_text", annotations=[
            NS(type="url_citation", url="https://example.com/article"),
        ])]),
    ])
    assert _search_source_urls(response) == {"https://example.com/article", "https://other.org/page"}


def test_web_search_uses_openai_responses_web_search(monkeypatch):
    calls = []
    text = '{"items":[{"title":"Release","link":"https://example.com/a","summary":"s","published_date":"2026-08-12"}]}'
    response = NS(
        status="completed",
        output_text=text,
        output=[
            NS(type="web_search_call", action=NS(
                type="search", sources=[NS(url="https://example.com/a")]
            )),
            NS(type="message", phase="final_answer", content=[NS(
                type="output_text", text=text, annotations=[]
            )]),
        ],
    )

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    monkeypatch.setattr("newsbot.websearch.get_client", lambda: NS(responses=Responses()))
    results, ages = _web_search("find recent news")
    assert results[0]["title"] == "Release"
    assert ages["https://example.com/a"] == datetime(2026, 8, 12, tzinfo=UTC)
    assert calls[0]["model"] == "gpt-5.5"
    assert calls[0]["tool_choice"] == "required"
    assert calls[0]["tools"] == [{"type": "web_search", "search_context_size": "medium"}]
    assert calls[0]["include"] == ["web_search_call.action.sources"]
    assert calls[0]["text"]["format"]["type"] == "json_schema"


def test_source_name_uses_known_label_else_netloc():
    known = {"example.com": "Example News"}
    assert _source_name("https://www.example.com/a", known) == "Example News"
    assert _source_name("https://other.org/a", known) == "other.org"


def test_results_to_items_drops_invented_and_stale():
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    results = [
        {"title": "Real fresh", "link": "https://a.com/1", "summary": "s"},
        {"title": "Invented", "link": "https://a.com/invented", "summary": "s"},
        {"title": "Stale", "link": "https://a.com/2", "summary": "s"},
        {"title": "Unknown date", "link": "https://a.com/3", "summary": "s"},
    ]
    ages = {
        "https://a.com/1": datetime(2026, 1, 5, tzinfo=UTC),
        "https://a.com/2": datetime(2025, 12, 1, tzinfo=UTC),
        "https://a.com/3": None,
    }
    items = _results_to_items(results, seen=set(), known_names={}, ages=ages, cutoff=cutoff)
    titles = [i["title"] for i in items]
    assert titles == ["Real fresh"]


def test_results_to_items_skips_seen():
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    results = [{"title": "Seen", "link": "https://a.com/1", "summary": "s"}]
    ages = {"https://a.com/1": None}
    items = _results_to_items(
        results, seen={"https://a.com/1"}, known_names={}, ages=ages, cutoff=cutoff
    )
    assert items == []
