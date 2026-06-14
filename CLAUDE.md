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
- `DAILY_NEWS` — *optional*; set to `off`/`false`/`0`/`no` to disable the daily 08:00 auto-post (the `/news` command still works). Defaults to on when unset/empty.

Telegram allows only one active poller per bot token, so local runs must either
use a **different bot token** than the Raspberry Pi deployment (separate `.env`,
separate bot via @BotFather), or stop the Pi's instance first with
`scripts/pi-bot.sh stop` (and `start` when done) — see README's "Local
development" section.

There are no automated tests or linters configured.

## Deployment

The Pi runs `news-bot.service` (see `deploy/news-bot.service`) as a dedicated
unprivileged `newsbot` system account out of `/opt/news-bot`, plus a timer,
`deploy/news-bot-deploy.timer` (+ `news-bot-deploy.service`), that runs
`deploy/auto-deploy.sh` every 15 minutes: fetches `origin/main`, and if it has
moved, fast-forwards, runs `uv sync`, and restarts `news-bot.service`. No-op if
already up to date; refuses to run if the checkout has local changes.
A fresh install is one command: `sudo deploy/install.sh` (idempotent) creates
the account via `deploy/news-bot.sysusers` (`systemd-sysusers`), builds the
venv, installs the units + `deploy/news-bot.tmpfiles` (`systemd-tmpfiles`, keeps
`.env` at 0640) + the two-line sudoers snippet (newsbot gets `restart`; the
human admin — `$SUDO_USER` — gets `start`/`stop`/`restart`), and enables
everything; on first run it seeds `.env` from `.shadow.env` and stops for you to
fill in secrets. README's "Running as a systemd service" / "Auto-deploy"
sections document it and the manual equivalent.
`scripts/pi-deploy.sh` SSHes into the Pi and runs `deploy/auto-deploy.sh`
directly, to deploy on demand from a local machine instead of waiting for the
timer.

## Architecture

- **bot.py** — Telegram bot entrypoint (`python-telegram-bot`). Registers the `/news` command and (unless `DAILY_NEWS` is set to a falsey value) a daily job (`run_daily`, 08:00 US/Eastern — the `time` carries explicit `tzinfo` because PTB's JobQueue scheduler defaults to UTC). Both call `collect_new_items()` then `summarize()` from `news.py`. `_send()` splits the rendered entries into Telegram-sized chunks and calls `mark_seen()` from `dedup.py` per chunk *as each one is delivered*, so a mid-batch send failure leaves already-sent items marked (no re-post) while undelivered ones re-surface next run. `/news` passes `include_themes=True` for the extra random-theme search; the daily job does not.
- **sources.json** — Feed/topic config. Edit feeds and topics here. Keys: `sources` (RSS/Atom feeds: `{url, limit, name}`), `known_source_names` (host → display label for web-search results), `base_topics` (fixed topics every web search covers), `search_themes` (extra topics `/news` mixes in at random).
- **news.py** — Core logic:
  - `load_config()`: reads `sources.json` **fresh on each run** (relative to the module, so it's CWD-independent), so config edits take effect without restarting the bot. `THEMES_PER_RUN` (how many themes `/news` samples per run) stays in `news.py`.
  - `fetch_new_items()`: pulls entries from each `load_config()["sources"]` feed, skips links already seen (via `dedup.load_seen()`/`normalize()`) and items older than `MAX_AGE_DAYS` (3). Read-only — does not record seen links.
  - `search_web(include_themes=False)`: a **single** web search (Claude `SEARCH_MODEL`/Sonnet, `web_search_20250305` server tool, `max_uses: 5`) covering the config's `base_topics` plus, when `include_themes`, a random sample of `search_themes`. One combined call instead of one-per-topic-group keeps token/search cost down. The prompt asks for dated/time-sensitive items (and to exclude evergreen docs/tutorials/roundups). Routes through `_web_search()` + `_results_to_items()`; dedups against the seen set and returns the same `{title, link, summary, source}` shape as RSS items. `_web_search()` returns `(parsed_items, ages)` where `ages` maps each real `web_search` result URL (normalized) to its parsed publish date or `None` (built from the `web_search_tool_result` blocks' `url` + freeform `page_age`, via `_search_result_ages()`/`_parse_page_age()`). `_results_to_items()` uses it to drop both any model-emitted link **not** in `ages` (a likely hallucinated URL) and any result whose known date is older than the `MAX_AGE_DAYS` cutoff (mirroring the RSS age filter; unknown-date results are kept).
  - `collect_new_items(include_themes=False)`: runs `fetch_new_items() + search_web(include_themes)` and dedups across all by normalized link; the candidate list the bot summarizes and (post-send) marks seen.
  - `summarize()`: sends collected items to the Anthropic API (`SUMMARY_MODEL`/Haiku) for a per-item emoji + 1-2 sentence summary (keyed by index; titles/links/sources stay local), then renders a list of `{text, links}` entries — the title header plus one entry per item carrying its own link. Returns a single linkless notice entry when there are no items. `bot.py`'s `_send()` consumes these entries.
- **dedup.py** — SQLite-backed store of seen entry links (`seen_links.db`), used to avoid re-summarizing the same article across runs. `normalize()` canonicalizes URLs (lowercase scheme/host, strip `www.`/trailing slash/fragment/tracking params) before comparison; `load_seen()` returns the current normalized set (pruning entries older than `RETENTION_DAYS`); `mark_seen()` records links with a timestamp. Links are committed via `mark_seen()` only *after* their chunk is delivered (called per chunk from `bot.py`'s `_send()`), so a failed send re-surfaces the undelivered items next run. Migrates a legacy `seen_links.json` on first connect.

## Notes

- `seen_links.json` is runtime state (regenerated on each run); don't treat it as source of truth for code changes.
- `.shadow.env` is a tracked template listing the required env var names (no values) — use it as the reference for what to put in your local `.env`.