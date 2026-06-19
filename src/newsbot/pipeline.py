# pipeline.py
"""Top-level collection: gather candidates from RSS + the web search and dedup
across both. The bot summarizes this list and (post-send) marks it seen."""
import logging

from .dedup import normalize
from .rss import fetch_new_items
from .websearch import search_web

logger = logging.getLogger(__name__)


def collect_new_items(include_themes=False):
    """Gather candidates from RSS + a single web search, deduped by normalized
    link. Does not persist; caller marks items seen after delivery. When
    include_themes is set, the web search also covers random search_themes
    (used by the on-demand /news)."""
    rss = fetch_new_items()
    web = search_web(include_themes)

    items = []
    picked = set()
    for item in rss + web:
        key = normalize(item["link"])
        if key in picked:
            continue
        picked.add(key)
        items.append(item)

    logger.info(
        "Collected %d new item(s): RSS %d + web %d, %d cross-source duplicate(s) dropped",
        len(items), len(rss), len(web), len(rss) + len(web) - len(items),
    )
    return items
