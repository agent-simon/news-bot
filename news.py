# news.py
from dotenv import load_dotenv
load_dotenv()

import feedparser
from anthropic import Anthropic
from dedup import load_seen, save_seen

ai = Anthropic()

SOURCES = [
    "https://news.google.com/rss/search?q=playwright+e2e+testing",
    "https://news.google.com/rss/search?q=AI+test+automation",
    "https://github.com/microsoft/playwright/releases.atom",
]

def fetch_new_items():
    seen = load_seen()
    items = []
    for url in SOURCES:
        feed = feedparser.parse(url)
        print(f"{url} -> {len(feed.entries)} entries")  # debug
        for entry in feed.entries[:5]:
            if entry.link not in seen:
                items.append({"title": entry.title, "link": entry.link, "summary": entry.get("summary", "")})
                seen.add(entry.link)
    save_seen(seen)
    print(f"Total new items: {len(items)}")  # debug
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
            "content": f"Summarize each item below in 1-2 sentences, relevant to Playwright/E2E testing/AI tooling. Skip irrelevant ones. Format as:\n- [summary] (source: link)\n\n{text_blob}"
        }]
    )
    return msg.content[0].text
