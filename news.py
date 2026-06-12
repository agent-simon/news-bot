# news.py
from dotenv import load_dotenv
load_dotenv()

import html
import json
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

# Topics the on-demand /news command does a random web search across, for
# variety run-to-run. Edit this list freely. THEMES_PER_RUN of them are picked
# at random each time (only on /news, not the daily job).
SEARCH_THEMES = [
    "new AI model and product releases from Anthropic, OpenAI, Google, and Meta",
    "AI agents and agentic developer tools",
    "AI coding assistants and developer productivity",
    "open-source LLMs and local model tooling",
    "LLM evaluation, benchmarks, and red-teaming",
    "AI in software testing and QA automation",
    "Playwright and browser automation",
    "retrieval-augmented generation and vector databases",
]
THEMES_PER_RUN = 2

def _source_name(link):
    netloc = urlparse(link).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return KNOWN_SOURCE_NAMES.get(netloc, netloc)

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


def _results_to_items(results, seen):
    """Turn raw web-search results into item dicts, skipping already-seen links."""
    items = []
    for result in results:
        link = result.get("link")
        if not link or normalize(link) in seen:
            continue
        items.append({"title": result.get("title", ""), "link": link, "summary": result.get("summary", ""), "source": _source_name(link)})
    return items

# The fixed topics every web search always covers.
BASE_TOPICS = [
    "Playwright, end-to-end testing, and AI-driven test automation",
    "new model releases and major product announcements from AI labs such as "
    "Anthropic (Claude), OpenAI (GPT/ChatGPT), Google (Gemini), and Meta (Llama)",
]

def search_web(include_themes=False):
    """One web search covering the fixed BASE_TOPICS, plus (on /news) a random
    sample of SEARCH_THEMES. Single call keeps token/search cost down vs one
    request per topic group."""
    seen = load_seen()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    topics = list(BASE_TOPICS)
    if include_themes and SEARCH_THEMES:
        topics += random.sample(SEARCH_THEMES, k=min(THEMES_PER_RUN, len(SEARCH_THEMES)))
    topic_lines = "\n".join(f"- {t}" for t in topics)

    results = _web_search(
        f"Search the web for recent, noteworthy news from {cutoff_str} onward about:\n"
        f"{topic_lines}\n\n"
        "Find up to 8 relevant articles or announcements across these topics, then "
        "respond with ONLY a JSON array (no markdown, no commentary) where each "
        "element has \"title\", \"link\" (the source URL) and \"summary\" (1-2 sentences)."
    )
    items = _results_to_items(results, seen)
    print(f"Web search ({len(topics)} topics) -> added {len(items)}")
    return items


def collect_new_items(include_themes=False):
    """Gather candidates from RSS + a single web search, deduped by normalized
    link. Does not persist; caller marks items seen after delivery. When
    include_themes is set, the web search also covers random SEARCH_THEMES
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
