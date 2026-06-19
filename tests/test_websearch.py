from datetime import UTC, datetime

from newsbot.websearch import _parse_page_age, _results_to_items, _source_name


def test_parse_page_age_relative_days():
    parsed = _parse_page_age("2 days ago")
    assert parsed is not None
    assert (datetime.now(UTC) - parsed).days == 2


def test_parse_page_age_absolute():
    assert _parse_page_age("2026-01-15") == datetime(2026, 1, 15, tzinfo=UTC)
    assert _parse_page_age("January 15, 2026") == datetime(2026, 1, 15, tzinfo=UTC)


def test_parse_page_age_unknown_returns_none():
    assert _parse_page_age("") is None
    assert _parse_page_age(None) is None
    assert _parse_page_age("sometime last spring") is None


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
    assert titles == ["Real fresh", "Unknown date"]


def test_results_to_items_skips_seen():
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    results = [{"title": "Seen", "link": "https://a.com/1", "summary": "s"}]
    ages = {"https://a.com/1": None}
    items = _results_to_items(
        results, seen={"https://a.com/1"}, known_names={}, ages=ages, cutoff=cutoff
    )
    assert items == []
