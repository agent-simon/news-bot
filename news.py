# news.py
from dotenv import load_dotenv
load_dotenv()

import html
import json
import feedparser
from anthropic import Anthropic
from dedup import load_seen, save_seen
from datetime import datetime, timedelta, timezone

MAX_AGE_DAYS = 3

ai = Anthropic()

SOURCES = [
    {"url": "https://news.google.com/rss/search?q=playwright+e2e+testing", "limit": 10},
    {"url": "https://news.google.com/rss/search?q=AI+test+automation", "limit": 10},
    {"url": "https://github.com/microsoft/playwright/releases.atom", "limit": 1},
]

def _extract_json(text):
    raw = text.strip().strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return json.loads(raw)

def fetch_new_items():
    seen = load_seen()
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for source in SOURCES:
        feed = feedparser.parse(source["url"])
        added = 0
        for entry in feed.entries[:source["limit"]]:
            if entry.link in seen:
                continue
            published = entry.get("published_parsed")
            if published:
                pub_date = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_date < cutoff:
                    continue
            items.append({"title": entry.title, "link": entry.link, "summary": entry.get("summary", "")})
            seen.add(entry.link)
            added += 1
        print(f"{source['url']} -> added {added}")

    save_seen(seen)
    print(f"Total new items: {len(items)}")
    return items

def search_new_items():
    seen = load_seen()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    messages = [{
        "role": "user",
        "content": (
            f"Search the web for news from {cutoff_str} onward about Playwright, "
            "end-to-end testing, and AI-driven test automation.\n\n"
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
        if not link or link in seen:
            continue
        items.append({"title": result.get("title", ""), "link": link, "summary": result.get("summary", "")})
        seen.add(link)

    save_seen(seen)
    print(f"Web search -> added {len(items)}")
    return items

def summarize(items):
    if not items:
        return "📰 No new relevant items today."

    text_blob = "\n\n".join(f"Title: {i['title']}\nLink: {i['link']}\nRaw: {i['summary'][:300]}" for i in items)
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": (
                "For each item below, write a 1-2 sentence summary based on the title "
                "(the raw content may be sparse) and pick one emoji that fits its topic. "
                "Include ALL items, even if the summary field is empty — use the title to "
                "infer relevance.\n\n"
                "Respond with ONLY a JSON array (no markdown, no commentary), where each "
                "element is {\"emoji\": ..., \"title\": ..., \"summary\": ..., \"link\": ...} "
                "and \"link\" is copied exactly from the item's Link field.\n\n"
                f"{text_blob}"
            )
        }]
    )

    try:
        results = _extract_json(msg.content[0].text)
    except json.JSONDecodeError:
        return msg.content[0].text

    entries = []
    for r in results:
        emoji = r.get("emoji", "🔹")
        title = html.escape(r.get("title", ""))
        summary = html.escape(r.get("summary", ""))
        link = r.get("link", "")
        if link:
            header = f'{emoji} <a href="{html.escape(link, quote=True)}"><b>{title}</b></a>'
        else:
            header = f"{emoji} <b>{title}</b>"
        entries.append(f"{header}\n{summary}")

    return f"📰 <b>{len(entries)} new item(s)</b>\n\n" + "\n\n".join(entries)
