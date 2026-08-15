from types import SimpleNamespace as NS

from newsbot import rss


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Entry(dict):
    __getattr__ = dict.__getitem__


def test_fetch_feed_uses_timeout_and_retries(monkeypatch):
    calls = []
    attempts = iter([OSError("temporary failure"), OSError("temporary failure"), None])

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        error = next(attempts)
        if error:
            raise error
        return _Response()

    monkeypatch.setattr(rss, "urlopen", fake_urlopen)
    monkeypatch.setattr(rss.feedparser, "parse", lambda response: "feed")
    monkeypatch.setattr(rss.time, "sleep", lambda _delay: None)

    assert rss._fetch_feed("https://example.com/feed") == "feed"
    assert len(calls) == 3
    assert all(timeout == rss.RSS_TIMEOUT_SECONDS for _request, timeout in calls)


def test_fetch_feed_gives_up_after_max_attempts(monkeypatch):
    calls = []

    def fake_urlopen(_request, timeout):
        calls.append(True)
        raise OSError("offline")

    monkeypatch.setattr(rss, "urlopen", fake_urlopen)
    monkeypatch.setattr(rss.time, "sleep", lambda _delay: None)

    assert rss._fetch_feed("https://example.com/feed") is None
    assert len(calls) == rss.RSS_MAX_ATTEMPTS


def test_fetch_new_items_skips_failed_feed(monkeypatch):
    monkeypatch.setattr(rss, "load_seen", lambda: set())
    monkeypatch.setattr(rss, "load_config", lambda: {"sources": [
        {"url": "https://bad.example/feed", "limit": 5, "name": "Bad"},
        {"url": "https://good.example/feed", "limit": 5, "name": "Good"},
    ]})
    monkeypatch.setattr(
        rss,
        "_fetch_feed",
        lambda url: None if "bad" in url else NS(entries=[_Entry(
            link="https://good.example/item",
            title="Good item",
            summary="Summary",
        )]),
    )

    assert rss.fetch_new_items() == [{
        "title": "Good item",
        "link": "https://good.example/item",
        "summary": "Summary",
        "source": "Good",
    }]
