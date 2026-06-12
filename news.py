# news.py
from dotenv import load_dotenv
load_dotenv()

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

def summarize(items):
    if not items:
        return "No new relevant items today."
    text_blob = "\n\n".join(f"Title: {i['title']}\nLink: {i['link']}\nRaw: {i['summary'][:300]}" for i in items)
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"For each item below, write a 1-2 sentence summary based on the title (the raw content may be sparse). Include ALL items, even if the summary field is empty — use the title to infer relevance. Format as:\n- [summary] (source: link)\n\n{text_blob}"
        }]
    )
    return msg.content[0].text
