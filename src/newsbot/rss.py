# rss.py
"""RSS/Atom feed ingestion: pull recent, unseen entries from the configured
feeds. Read-only against the dedup store — callers mark items seen after
delivery."""
import logging
from datetime import UTC, datetime, timedelta

import feedparser

from .config import MAX_AGE_DAYS, load_config
from .dedup import load_seen, normalize

logger = logging.getLogger(__name__)


def fetch_new_items():
    """Pull entries from each configured feed, skipping links already seen and
    items older than MAX_AGE_DAYS. Returns {title, link, summary, source} dicts."""
    seen = load_seen()
    items = []
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)

    sources = load_config()["sources"]
    for source in sources:
        feed = feedparser.parse(source["url"])
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
