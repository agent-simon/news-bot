# news-bot

A Telegram bot that aggregates news on Playwright/E2E testing and AI test automation, summarizes new items with Claude, and posts the summary to a Telegram chat — on demand via `/news` or automatically every day at 08:00.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy `.shadow.env` to `.env` and fill in the values:

```bash
cp .shadow.env .env
```

- `TELEGRAM_BOT_TOKEN` — token for your Telegram bot (from [@BotFather](https://t.me/BotFather))
- `ANTHROPIC_API_KEY` — Anthropic API key
- `CHAT_ID` — Telegram chat ID to receive the daily summary

## Running

```bash
python bot.py
```

- Send `/news` to the bot for an on-demand summary of new items.
- A daily summary is automatically sent to `CHAT_ID` at 08:00 server time.

## Configuration

RSS/Atom sources are defined in `SOURCES` in `news.py`. Each entry has a feed `url` and a `limit` on how many items to consider per run. Items older than `MAX_AGE_DAYS` (default 1) or already seen (tracked in `seen_links.db`, a SQLite store) are skipped. Links are committed as seen only after the summary is successfully delivered, so a failed run re-surfaces its items next time.

In addition to the RSS sources, Claude performs its own web search each run (`search_new_items()`) to find recent items on the same topics, which are merged in before summarizing.