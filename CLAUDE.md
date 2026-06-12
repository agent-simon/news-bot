# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that aggregates news from RSS feeds (Playwright/E2E testing/AI test automation topics), summarizes new items with the Anthropic API, and posts the summary to a Telegram chat — either on a daily schedule or on demand via the `/news` command.

## Running

```bash
source venv/bin/activate
python bot.py
```

Requires a `.env` file (loaded via `python-dotenv`) with:
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `ANTHROPIC_API_KEY` — Anthropic API key
- `CHAT_ID` — Telegram chat ID for the daily job

There are no automated tests or linters configured.

## Architecture

- **bot.py** — Telegram bot entrypoint (`python-telegram-bot`). Registers the `/news` command and a daily job (`run_daily`, 08:00 server time). Both call `fetch_new_items()` then `summarize()` from `news.py`.
- **news.py** — Core logic:
  - `SOURCES`: list of RSS/Atom feed URLs + per-feed item limits, parsed with `feedparser`. Add/remove feeds here.
  - `fetch_new_items()`: pulls entries from each source, skips links already in `seen_links.json` and items older than `MAX_AGE_DAYS` (3), records new links as seen.
  - `summarize()`: sends collected items to the Anthropic API (`claude-sonnet-4-6`) to produce a bullet-point summary with source links.
- **dedup.py** — Persists the set of seen entry links to `seen_links.json` (`load_seen` / `save_seen`), used to avoid re-summarizing the same article across runs.

## Notes

- `seen_links.json` is runtime state (regenerated on each run); don't treat it as source of truth for code changes.
- `.shadow.env` is a tracked template listing the required env var names (no values) — use it as the reference for what to put in your local `.env`.