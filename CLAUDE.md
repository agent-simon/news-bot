# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that aggregates news from RSS feeds and Claude-driven web search (Playwright/E2E testing/AI test automation topics), summarizes new items with the Anthropic API, and posts the summary to a Telegram chat — either on a daily schedule or on demand via the `/news` command.

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

- **bot.py** — Telegram bot entrypoint (`python-telegram-bot`). Registers the `/news` command and a daily job (`run_daily`, 08:00 server time). Both call `collect_new_items()` then `summarize()` from `news.py`, and `mark_seen()` from `dedup.py` after the message is sent.
- **news.py** — Core logic:
  - `SOURCES`: list of RSS/Atom feed URLs + per-feed item limits, parsed with `feedparser`. Add/remove feeds here.
  - `fetch_new_items()`: pulls entries from each source, skips links already seen (via `dedup.load_seen()`/`normalize()`) and items older than `MAX_AGE_DAYS` (1). Read-only — does not record seen links.
  - `search_new_items()`: asks Claude (`claude-sonnet-4-6` with the `web_search_20250305` server tool, `max_uses: 5`) to search the web for recent items on the same topics and return them as JSON; dedups against the seen set like `fetch_new_items()`. Returns the same `{title, link, summary, source}` shape so results merge directly with RSS items.
  - `collect_new_items()`: runs `fetch_new_items() + search_new_items()` and dedups across both by normalized link; the candidate list the bot summarizes and (post-send) marks seen.
  - `summarize()`: sends collected items to the Anthropic API (`claude-sonnet-4-6`) to produce a bullet-point summary with source links.
- **dedup.py** — SQLite-backed store of seen entry links (`seen_links.db`), used to avoid re-summarizing the same article across runs. `normalize()` canonicalizes URLs (lowercase scheme/host, strip `www.`/trailing slash/fragment/tracking params) before comparison; `load_seen()` returns the current normalized set (pruning entries older than `RETENTION_DAYS`); `mark_seen()` records links with a timestamp. Links are committed via `mark_seen()` only *after* the summary is delivered (called from `bot.py`), so a failed send re-surfaces items next run. Migrates a legacy `seen_links.json` on first connect.

## Notes

- `seen_links.json` is runtime state (regenerated on each run); don't treat it as source of truth for code changes.
- `.shadow.env` is a tracked template listing the required env var names (no values) — use it as the reference for what to put in your local `.env`.