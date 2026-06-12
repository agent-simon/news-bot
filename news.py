# news.py
from dotenv import load_dotenv
load_dotenv()

import html
import json
import feedparser
from anthropic import Anthropic
from dedup import load_seen, normalize
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

MAX_AGE_DAYS = 3

ai = Anthropic()

SOURCES = [
    {"url": "https://news.google.com/rss/search?q=playwright+e2e+testing", "limit": 10, "name": "Google News"},
    {"url": "https://news.google.com/rss/search?q=AI+test+automation", "limit": 10, "name": "Google News"},
    {"url": "https://github.com/microsoft/playwright/releases.atom", "limit": 1, "name": "GitHub"},
    {"url": "https://hnrss.org/newest?q=playwright", "limit": 5, "name": "Hacker News"},
    {"url": "https://hnrss.org/newest?q=Anthropic+OR+OpenAI+OR+Claude+OR+GPT+OR+Gemini+OR+Llama+OR+LLM&points=20", "limit": 2, "name": "Hacker News"},
]

KNOWN_SOURCE_NAMES = {
    "github.com": "GitHub",
    "news.ycombinator.com": "Hacker News",
    "news.google.com": "Google News",
}

def _source_name(link):
    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return KNOWN_SOURCE_NAMES.get(netloc, netloc)

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

    for source in SOURCES:
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

def search_new_items():
    seen = load_seen()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    messages = [{
        "role": "user",
        "content": (
            f"Search the web for news from {cutoff_str} onward about:\n"
            "1. Playwright, end-to-end testing, and AI-driven test automation.\n"
            "2. New model releases and major product announcements from AI labs "
            "such as Anthropic (Claude), OpenAI (GPT/ChatGPT), Google (Gemini), "
            "and Meta (Llama).\n\n"
            "Find up to 5 relevant articles or announcements, then respond with ONLY a "
            "JSON array (no markdown, no commentary) where each element has \"title\", "
            "\"link\" (the source URL) and \"summary\" (1-2 sentences)."
        )
    }]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

    response = ai.messages.create(model="claude-sonnet-4-6", max_tokens=1500, tools=tools, messages=messages)
    while response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = ai.messages.create(model="claude-sonnet-4-6", max_tokens=1500, tools=tools, messages=messages)

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        return []

    try:
        results = _extract_json(text_blocks[-1])
    except json.JSONDecodeError:
        print("search_new_items: could not parse response as JSON")
        return []

    items = []
    for result in results:
        link = result.get("link")
        if not link or normalize(link) in seen:
            continue
        items.append({"title": result.get("title", ""), "link": link, "summary": result.get("summary", ""), "source": _source_name(link)})

    print(f"Web search -> added {len(items)}")
    return items


def collect_new_items():
    """Gather candidates from RSS + web search, deduped across both by
    normalized link. Does not persist; caller marks items seen after delivery."""
    items = []
    picked = set()
    for item in fetch_new_items() + search_new_items():
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
        f"[{idx}] Title: {i['title']}\nRaw: {i['summary'][:300]}"
        for idx, i in enumerate(items)
    )
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": (
                "For each item below, write a 1-2 sentence summary based on the title "
                "(the raw content may be sparse) and pick one emoji that fits its topic. "
                "Include ALL items, even if the raw content is empty — infer from the title.\n\n"
                "Respond with ONLY a JSON array (no markdown, no commentary), where each "
                "element is {\"i\": <the bracketed index>, \"emoji\": ..., \"summary\": ...}.\n\n"
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
        try:
            enrichments[int(r["i"])] = {"emoji": r.get("emoji"), "summary": r.get("summary")}
        except (KeyError, TypeError, ValueError):
            continue

    return _render(items, enrichments)
