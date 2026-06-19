# websearch.py
"""Claude web-search pass: a single search over the configured topics, with the
returned links validated against the real search results and aged out like RSS.

`_web_search()` returns (parsed_items, ages) where `ages` maps each real
web_search result URL (normalized) to its parsed publish date or None. That map
is the source of truth both for which links are genuine — a model-emitted link
absent from it is a likely hallucination — and for how old each one is.
"""
import json
import logging
import random
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from .config import MAX_AGE_DAYS, THEMES_PER_RUN, load_config, web_search_enabled
from .dedup import load_seen, normalize
from .llm import SEARCH_MODEL, get_client
from .parsing import extract_json

logger = logging.getLogger(__name__)


def _source_name(link, known_names):
    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return known_names.get(netloc, netloc)


def _parse_page_age(page_age):
    """Best-effort parse of a web_search result's freeform `page_age` string into
    a UTC datetime. Handles "N minutes/hours/days/weeks/months/years ago" and a
    few absolute date formats. Returns None when absent or unrecognised — callers
    treat an unknown age as "keep", so we never over-filter on a format we don't
    understand."""
    if not page_age:
        return None
    text = page_age.strip()
    now = datetime.now(UTC)
    m = re.match(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", text, re.I)
    if m:
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
        return now - timedelta(days=int(m.group(1)) * days[m.group(2).lower()])
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _search_result_ages(content):
    """Map each real web_search result URL (normalized) to its parsed publish
    date (or None if unknown). This is the source of truth both for which links
    are genuine — a model-emitted link absent from this map is a likely
    hallucination — and for how old each one is. Skips error result blocks (their
    .content isn't a result list)."""
    ages = {}
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = block.content
        if not isinstance(results, list):
            continue
        for result in results:
            url = getattr(result, "url", None)
            if not url:
                continue
            norm = normalize(url)
            date = _parse_page_age(getattr(result, "page_age", None))
            # If a URL recurs across blocks, keep the first known date over None.
            if norm not in ages or (ages[norm] is None and date is not None):
                ages[norm] = date
    return ages


def _merge_ages(into, new):
    """Merge a URL->date map into another, preferring a known date over None."""
    for url, date in new.items():
        if url not in into or (into[url] is None and date is not None):
            into[url] = date


def _web_search(instruction):
    """Run a Claude web search with the given instruction and return
    (parsed [{title, link, summary}] list, {normalized real result URL -> publish
    date or None}). The URL map is the source of truth for which links are genuine
    and how old they are; the parsed list (model-authored JSON) is validated
    against it by the caller. Either field is empty if nothing usable came back."""
    ai = get_client()
    messages = [{"role": "user", "content": instruction}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

    ages = {}
    response = ai.messages.create(model=SEARCH_MODEL, max_tokens=4000, tools=tools, messages=messages)
    _merge_ages(ages, _search_result_ages(response.content))
    while response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = ai.messages.create(model=SEARCH_MODEL, max_tokens=4000, tools=tools, messages=messages)
        _merge_ages(ages, _search_result_ages(response.content))

    if response.stop_reason == "max_tokens":
        logger.warning("web search: response truncated at max_tokens; results may be incomplete")

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        return [], ages
    try:
        return extract_json(text_blocks[-1]), ages
    except json.JSONDecodeError:
        logger.warning("web search: could not parse response as JSON")
        return [], ages


def _results_to_items(results, seen, known_names, ages, cutoff):
    """Turn raw web-search results into item dicts, skipping: already-seen links;
    any link the model emitted that wasn't among the real search results (`ages`
    keys) — i.e. URLs it invented rather than read; and results whose known
    publish date is older than `cutoff` (results with an unknown date are kept)."""
    items = []
    dropped_invented = 0
    dropped_stale = 0
    for result in results:
        link = result.get("link")
        if not link:
            continue
        norm = normalize(link)
        if norm in seen:
            continue
        if norm not in ages:
            dropped_invented += 1
            continue
        date = ages[norm]
        if date is not None and date < cutoff:
            dropped_stale += 1
            continue
        items.append({"title": result.get("title", ""), "link": link, "summary": result.get("summary", ""), "source": _source_name(link, known_names)})
    if dropped_invented:
        logger.info("web search: dropped %d item(s) with links not in search results", dropped_invented)
    if dropped_stale:
        logger.info("web search: dropped %d item(s) older than cutoff", dropped_stale)
    return items


def search_web(include_themes=False):
    """One web search covering the fixed base_topics, plus (on /news) a random
    sample of search_themes. Single call keeps token/search cost down vs one
    request per topic group. Disabled wholesale via WEB_SEARCH=off (RSS only)."""
    if not web_search_enabled():
        logger.info("Web search disabled via WEB_SEARCH; RSS feeds only.")
        return []

    config = load_config()
    seen = load_seen()
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    themes = config["search_themes"]
    topics = list(config["base_topics"])
    if include_themes and themes:
        topics += random.sample(themes, k=min(THEMES_PER_RUN, len(themes)))
    topic_lines = "\n".join(f"- {t}" for t in topics)

    results, ages = _web_search(
        f"Search the web for news published on or after {cutoff_str} about:\n"
        f"{topic_lines}\n\n"
        "Focus on dated, time-sensitive items — announcements, releases, version "
        "updates, incidents, and reporting from the last few days. Do NOT include "
        "evergreen pages (documentation, tutorials, 'best practices' or 'top N' "
        "roundups, landing pages) or any article you cannot confirm was published "
        "in this window.\n\n"
        "Find up to 8 of the most relevant recent articles, then respond with ONLY "
        "a JSON array (no markdown, no commentary) where each element has \"title\", "
        "\"link\" (the source URL) and \"summary\" (1-2 sentences)."
    )
    items = _results_to_items(results, seen, config["known_source_names"], ages, cutoff)
    logger.info("Web search: %d new item(s) across %d topic(s)", len(items), len(topics))
    return items
