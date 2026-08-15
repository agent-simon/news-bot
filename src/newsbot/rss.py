# rss.py
"""RSS/Atom feed ingestion: pull recent, unseen entries from the configured
feeds. Read-only against the dedup store — callers mark items seen after
delivery."""
import logging
import time
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import feedparser

from .config import MAX_AGE_DAYS, load_config
from .dedup import load_seen, normalize

logger = logging.getLogger(__name__)

RSS_TIMEOUT_SECONDS = 15
RSS_MAX_ATTEMPTS = 3
RSS_RETRY_BACKOFF_SECONDS = 1


def _retryable_http_error(error):
    return error.code in {408, 425, 429, 500, 502, 503, 504}


def _fetch_feed(url):
    """Fetch and parse one feed with bounded network retries."""
    request = Request(url, headers={"User-Agent": "news-bot/1.0"})
    for attempt in range(1, RSS_MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=RSS_TIMEOUT_SECONDS) as response:
                return feedparser.parse(response)
        except HTTPError as error:
            if not _retryable_http_error(error):
                logger.warning("RSS %s returned HTTP %s", url, error.code)
                break
            reason = f"HTTP {error.code}"
        except (URLError, TimeoutError, OSError) as error:
            reason = str(error)

        if attempt < RSS_MAX_ATTEMPTS:
            delay = RSS_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
            logger.warning(
                "RSS %s attempt %d/%d failed (%s); retrying in %ss",
                url,
                attempt,
                RSS_MAX_ATTEMPTS,
                reason,
                delay,
            )
            time.sleep(delay)
        else:
            logger.warning("RSS %s failed after %d attempts (%s)", url, attempt, reason)
    return None


def fetch_new_items():
    """Pull entries from each configured feed, skipping links already seen and
    items older than MAX_AGE_DAYS. Returns {title, link, summary, source} dicts."""
    seen = load_seen()
    items = []
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)

    sources = load_config()["sources"]
    for source in sources:
        feed = _fetch_feed(source["url"])
        if feed is None:
            continue
        added = 0
        for entry in feed.entries[:source["limit"]]:
            if normalize(entry.link) in seen:
                continue
            published = entry.get("published_parsed")
            if published:
                pub_date = datetime(*published[:6], tzinfo=UTC)
                if pub_date < cutoff:
                    continue
            items.append({"title": entry.title, "link": entry.link, "summary": entry.get("summary", ""), "source": source["name"]})
            added += 1
        logger.info("RSS %s -> %d new", source["name"], added)

    logger.info("RSS: %d new item(s) across %d feed(s)", len(items), len(sources))
    return items
