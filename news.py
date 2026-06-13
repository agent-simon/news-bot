# news.py
from dotenv import load_dotenv
load_dotenv()

import html
import json
import os
import random
import re
import feedparser
from anthropic import Anthropic
from dedup import load_seen, normalize
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

MAX_AGE_DAYS = 3

# Web search needs relevance judgement + synthesis, so it stays on Sonnet.
# Summarising titles into emoji + a one-liner is simple, so Haiku does it
# (~3x cheaper per token and faster).
SEARCH_MODEL = "claude-sonnet-4-6"
SUMMARY_MODEL = "claude-haiku-4-5"

ai = Anthropic()

# Feed/topic config lives in sources.json (edit feeds and topics there). It's
# read fresh on each run so edits take effect without restarting the bot.
#   "sources"            — RSS/Atom feeds: {url, limit, name}
#   "known_source_names" — display labels for web-search hosts (netloc sans www.)
#   "base_topics"        — fixed topics every web search covers
#   "search_themes"      — extra topics /news mixes in at random
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "sources.json")

# How many search_themes /news samples per run (behaviour knob, not data).
THEMES_PER_RUN = 2

def load_config():
    """Read sources.json fresh (CWD-independent), so config edits apply without
    a restart."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def _source_name(link, known_names):
    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return known_names.get(netloc, netloc)

def _coerce_index(value):
    """Pull an integer item index out of the model's response. Tolerates ints,
    "0", and stray formatting like "[0]" (some models echo the label verbatim)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None

def _extract_json(text):
    raw = text.strip()
    # Strip a surrounding ```json ... ``` (or bare ```) code fence if present.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # The model sometimes wraps the array in prose ("Here are the items: [...]").
    # Fall back to slicing out the outermost JSON array/object.
    starts = [i for i in (raw.find("["), raw.find("{")) if i != -1]
    ends = [i for i in (raw.rfind("]"), raw.rfind("}")) if i != -1]
    if starts and ends:
        return json.loads(raw[min(starts):max(ends) + 1])
    raise json.JSONDecodeError("no JSON found", raw, 0)

def fetch_new_items():
    seen = load_seen()
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for source in load_config()["sources"]:
        feed = feedparser.parse(source["url"])
        added = 0
        for entry in feed.entries[:source["limit"]]:
            if normalize(entry.link) in seen:
                continue
            published = entry.get("published_parsed")
            if published:
                pub_date = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_date < cutoff:
                    continue
            items.append({"title": entry.title, "link": entry.link, "summary": entry.get("summary", ""), "source": source["name"]})
            added += 1
        print(f"{source['url']} -> added {added}")

    print(f"Total new items: {len(items)}")
    return items

def _web_search(instruction):
    """Run a Claude web search with the given instruction and return the parsed
    [{title, link, summary}] list, or [] if nothing usable came back."""
    messages = [{"role": "user", "content": instruction}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

    response = ai.messages.create(model=SEARCH_MODEL, max_tokens=2000, tools=tools, messages=messages)
    while response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = ai.messages.create(model=SEARCH_MODEL, max_tokens=2000, tools=tools, messages=messages)

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        return []
    try:
        return _extract_json(text_blocks[-1])
    except json.JSONDecodeError:
        print("web search: could not parse response as JSON")
        return []


def _results_to_items(results, seen, known_names):
    """Turn raw web-search results into item dicts, skipping already-seen links."""
    items = []
    for result in results:
        link = result.get("link")
        if not link or normalize(link) in seen:
            continue
        items.append({"title": result.get("title", ""), "link": link, "summary": result.get("summary", ""), "source": _source_name(link, known_names)})
    return items

def search_web(include_themes=False):
    """One web search covering the fixed base_topics, plus (on /news) a random
    sample of search_themes. Single call keeps token/search cost down vs one
    request per topic group."""
    config = load_config()
    seen = load_seen()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    themes = config["search_themes"]
    topics = list(config["base_topics"])
    if include_themes and themes:
        topics += random.sample(themes, k=min(THEMES_PER_RUN, len(themes)))
    topic_lines = "\n".join(f"- {t}" for t in topics)

    results = _web_search(
        f"Search the web for recent, noteworthy news from {cutoff_str} onward about:\n"
        f"{topic_lines}\n\n"
        "Find up to 8 relevant articles or announcements across these topics, then "
        "respond with ONLY a JSON array (no markdown, no commentary) where each "
        "element has \"title\", \"link\" (the source URL) and \"summary\" (1-2 sentences)."
    )
    items = _results_to_items(results, seen, config["known_source_names"])
    print(f"Web search ({len(topics)} topics) -> added {len(items)}")
    return items


def collect_new_items(include_themes=False):
    """Gather candidates from RSS + a single web search, deduped by normalized
    link. Does not persist; caller marks items seen after delivery. When
    include_themes is set, the web search also covers random search_themes
    (used by the on-demand /news)."""
    sources = fetch_new_items() + search_web(include_themes)

    items = []
    picked = set()
    for item in sources:
        key = normalize(item["link"])
        if key in picked:
            continue
        picked.add(key)
        items.append(item)
    return items


def _render(items, enrichments):
    """Build the HTML Telegram message. `enrichments` maps an item index to
    {emoji, summary}; missing entries fall back to the item's own data."""
    entries = []
    for idx, item in enumerate(items):
        enr = enrichments.get(idx, {})
        emoji = enr.get("emoji") or "🔹"
        summary = html.escape(enr.get("summary") or item["summary"] or "")
        title = html.escape(item["title"])
        link = item["link"]
        source = html.escape(item.get("source", ""))
        if link:
            header = f'{emoji} <a href="{html.escape(link, quote=True)}"><b>{title}</b></a>'
        else:
            header = f"{emoji} <b>{title}</b>"
        if source:
            header += f" <i>({source})</i>"
        entries.append(f"{header}\n{summary}" if summary else header)

    return f"📰 <b>{len(entries)} new item(s)</b>\n\n" + "\n\n".join(entries)

def summarize(items):
    if not items:
        return "📰 No new relevant items today."

    # Ask only for emoji + summary keyed by index; title/link/source stay local.
    # This keeps output small (avoids token-limit truncation) and removes the
    # risk of the model mangling copied URLs.
    text_blob = "\n\n".join(
        f"Item {idx}:\nTitle: {i['title']}\nRaw: {i['summary'][:300]}"
        for idx, i in enumerate(items)
    )
    msg = ai.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": (
                "For each item below, write a 1-2 sentence summary based on the title "
                "(the raw content may be sparse) and pick one emoji that fits its topic. "
                "Include ALL items, even if the raw content is empty — infer from the title.\n\n"
                "Respond with ONLY a JSON array (no markdown, no commentary), where each "
                "element is {\"i\": <the item number as an integer>, \"emoji\": ..., \"summary\": ...}.\n\n"
                f"{text_blob}"
            )
        }]
    )

    try:
        results = _extract_json(msg.content[0].text)
    except json.JSONDecodeError:
        # Never leak raw model output to Telegram — render from local items.
        print("summarize: could not parse response as JSON; using raw items")
        return _render(items, {})

    enrichments = {}
    for r in results:
        idx = _coerce_index(r.get("i"))
        if idx is not None:
            enrichments[idx] = {"emoji": r.get("emoji"), "summary": r.get("summary")}

    return _render(items, enrichments)
