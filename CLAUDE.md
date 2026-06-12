# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that aggregates news from RSS feeds and Claude-driven web search (Playwright/E2E testing/AI test automation topics), summarizes new items with the Anthropic API, and posts the summary to a Telegram chat — either on a daily schedule or on demand via the `/news` command.

## Running

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`; run `uv sync` to create the `.venv`).

```bash
uv run bot.py
```

Requires a `.env` file (loaded via `python-dotenv`) with:
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `ANTHROPIC_API_KEY` — Anthropic API key
- `CHAT_ID` — Telegram chat ID for the daily job

There are no automated tests or linters configured.

## Architecture

- **bot.py** — Telegram bot entrypoint (`python-telegram-bot`). Registers the `/news` command and a daily job (`run_daily`, 08:00 server time). Both call `collect_new_items()` then `summarize()` from `news.py`, and `mark_seen()` from `dedup.py` after the message is sent. `/news` passes `include_themes=True` for the extra random-theme search; the daily job does not.
- **news.py** — Core logic:
  - `SOURCES`: list of RSS/Atom feed URLs + per-feed item limits, parsed with `feedparser`. Add/remove feeds here.
  - `SEARCH_THEMES` / `THEMES_PER_RUN`: topics the on-demand `/news` does a random web search across (`THEMES_PER_RUN` chosen at random per run, for variety). Edit `SEARCH_THEMES` to change coverage.
  - `fetch_new_items()`: pulls entries from each source, skips links already seen (via `dedup.load_seen()`/`normalize()`) and items older than `MAX_AGE_DAYS` (3). Read-only — does not record seen links.
  - `search_new_items()`: asks Claude (`SEARCH_MODEL`, Sonnet, with the `web_search_20250305` server tool, `max_uses: 5`) to search the web for recent items on the fixed Playwright/AI-release topics and return them as JSON; dedups against the seen set. Returns the same `{title, link, summary, source}` shape so results merge directly with RSS items.
  - `search_themes(count=THEMES_PER_RUN)`: web-searches a random sample of `SEARCH_THEMES` for variety; same shape/dedup as `search_new_items()`. Both route through the `_web_search()` + `_results_to_items()` helpers. Only invoked on `/news` (via `include_themes`).
  - `collect_new_items(include_themes=False)`: runs `fetch_new_items() + search_new_items()` (plus `search_themes()` when `include_themes`) and dedups across all by normalized link; the candidate list the bot summarizes and (post-send) marks seen.
  - `summarize()`: sends collected items to the Anthropic API (`claude-sonnet-4-6`) to produce a bullet-point summary with source links.
- **dedup.py** — SQLite-backed store of seen entry links (`seen_links.db`), used to avoid re-summarizing the same article across runs. `normalize()` canonicalizes URLs (lowercase scheme/host, strip `www.`/trailing slash/fragment/tracking params) before comparison; `load_seen()` returns the current normalized set (pruning entries older than `RETENTION_DAYS`); `mark_seen()` records links with a timestamp. Links are committed via `mark_seen()` only *after* the summary is delivered (called from `bot.py`), so a failed send re-surfaces items next run. Migrates a legacy `seen_links.json` on first connect.

## Notes

- `seen_links.json` is runtime state (regenerated on each run); don't treat it as source of truth for code changes.
- `.shadow.env` is a tracked template listing the required env var names (no values) — use it as the reference for what to put in your local `.env`.