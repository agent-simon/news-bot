# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Telegram bot that aggregates news from RSS feeds and Claude-driven web search (Playwright/E2E testing/AI test automation topics), summarizes new items with the Anthropic API, and posts the summary to a Telegram chat — either on a daily schedule or on demand via the `/news` command.

## Running

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`; run `uv sync` to create the `.venv`).

```bash
uv run news-bot
```

The code is the `newsbot` package under `src/`; `uv sync` installs it (editable)
along with the `news-bot` console script (`[project.scripts]`). `uv run python -m
newsbot` is equivalent, and a thin root `bot.py` shim keeps the legacy `python
bot.py` invocation working (it routes to `newsbot.bot:main`).

Requires a `.env` file (loaded via `python-dotenv`) with:
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `ANTHROPIC_API_KEY` — Anthropic API key
- `CHAT_ID` — Telegram chat ID for the daily job
- `DAILY_NEWS` — *optional*; set to `off`/`false`/`0`/`no` to disable the daily 08:00 auto-post (the `/news` command still works). Defaults to on when unset/empty.
- `WEB_SEARCH` — *optional*; set to `off`/`false`/`0`/`no` to skip the Claude web-search pass and aggregate RSS feeds only (drops the Sonnet + web-search-tool API cost, which is the bulk of the spend). Both the daily job and `/news` respect it. Defaults to on when unset/empty.
- `SOURCES_PATH` — *optional*; absolute path to a feed/topic config read **instead of** the tracked `sources.json`. Lets you edit feeds/topics in place (e.g. an untracked `sources.local.json` on the Pi) without a commit/PR/deploy — still read fresh each run. The file must live outside version control (it's `.gitignore`d) so editing it doesn't trip `auto-deploy.sh`'s local-changes guard. Falls back to `sources.json` when unset/empty.

Telegram allows only one active poller per bot token, so local runs must either
use a **different bot token** than the Raspberry Pi deployment (separate `.env`,
separate bot via @BotFather), or stop the Pi's instance first with
`scripts/pi-bot.sh stop` (and `start` when done) — see README's "Local
development" section.

Tests and linting use the `dev` dependency group (installed by `uv sync`):

```bash
uv run pytest        # unit tests for the pure helpers (tests/)
uv run ruff check .  # lint; add --fix to autofix
```

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
`scripts/pi-deploy.sh` SSHes into the Pi and starts the `news-bot-deploy`
oneshot (so the deploy runs as `newsbot`, the checkout's owner — running
`auto-deploy.sh` directly as the SSH login user trips git's dubious-ownership
guard), to deploy on demand from a local machine instead of waiting for the
timer.

## Architecture

The code is the `newsbot` package under `src/` (entrypoint `newsbot.bot:main`,
exposed as the `news-bot` console script; a root `bot.py` shim routes the legacy
`python bot.py` to it). The core logic was split out of a former monolithic
`news.py` into the focused modules below. All paths are under `src/newsbot/`.

- **bot.py** — Telegram bot entrypoint (`python-telegram-bot`). Registers the `/news` command and (unless `DAILY_NEWS` is set to a falsey value — `config.daily_news_enabled()`) a daily job (`run_daily`, 08:00 US/Eastern — the `time` carries explicit `tzinfo` because PTB's JobQueue scheduler defaults to UTC). Both call `collect_new_items()` (from `pipeline.py`) then `summarize()` (from `render.py`). `_send()` splits the rendered entries into Telegram-sized chunks and calls `mark_seen()` from `dedup.py` per chunk *as each one is delivered*, so a mid-batch send failure leaves already-sent items marked (no re-post) while undelivered ones re-surface next run. `/news` passes `include_themes=True` for the extra random-theme search; the daily job does not.
- **sources.json** — Feed/topic config. Edit feeds and topics here. Keys: `sources` (RSS/Atom feeds: `{url, limit, name}`), `known_source_names` (host → display label for web-search results), `base_topics` (fixed topics every web search covers), `search_themes` (extra topics `/news` mixes in at random).
- **config.py** — Runtime config, all read **on each call** (not captured into module globals at import) so tests can set env and config edits apply without a restart. `load_config()` reads the feed/topic config fresh; path is `SOURCES_PATH` if set, else the module-relative `sources.json` (CWD-independent). `web_search_enabled()`/`daily_news_enabled()` are the env toggles; `MAX_AGE_DAYS` (3) and `THEMES_PER_RUN` (how many themes `/news` samples) are constants here. Calls `load_dotenv()` once on import.
- **llm.py** — The shared Anthropic client (`get_client()`, built lazily so importing the news modules / running the unit tests needs no API key) plus `SEARCH_MODEL` (Sonnet) and `SUMMARY_MODEL` (Haiku).
- **parsing.py** — Tolerant model-output helpers shared by the search and summary passes: `extract_json()` (handles ```json fences and prose-wrapped JSON) and `coerce_index()`.
- **rss.py** — `fetch_new_items()`: pulls entries from each `load_config()["sources"]` feed, skips links already seen (via `dedup.load_seen()`/`normalize()`) and items older than `MAX_AGE_DAYS`. Read-only — does not record seen links.
- **websearch.py** — `search_web(include_themes=False)`: returns `[]` immediately when `WEB_SEARCH` is off (RSS-only mode). Otherwise a **single** web search (Sonnet, `web_search_20250305` server tool, `max_uses: 5`) covering the config's `base_topics` plus, when `include_themes`, a random sample of `search_themes`. One combined call instead of one-per-topic-group keeps token/search cost down. The prompt asks for dated/time-sensitive items (and to exclude evergreen docs/tutorials/roundups). Routes through `_web_search()` + `_results_to_items()`; dedups against the seen set and returns the same `{title, link, summary, source}` shape as RSS items. `_web_search()` returns `(parsed_items, ages)` where `ages` maps each real `web_search` result URL (normalized) to its parsed publish date or `None` (built from the `web_search_tool_result` blocks' `url` + freeform `page_age`, via `_search_result_ages()`/`_parse_page_age()`). `_results_to_items()` uses it to drop both any model-emitted link **not** in `ages` (a likely hallucinated URL) and any result whose known date is older than the `MAX_AGE_DAYS` cutoff (unknown-date results are kept).
- **pipeline.py** — `collect_new_items(include_themes=False)`: runs `fetch_new_items()` + `search_web(include_themes)` and dedups across all by normalized link; the candidate list the bot summarizes and (post-send) marks seen.
- **render.py** — `summarize()`: sends collected items to the Anthropic API (`SUMMARY_MODEL`/Haiku) for a per-item emoji + 1-2 sentence summary (keyed by index; titles/links/sources stay local), then renders a list of `{text, links}` entries — the title header plus one entry per item carrying its own link. Returns a single linkless notice entry when there are no items. `bot.py`'s `_send()` consumes these entries.
- **tests/** — `pytest` unit tests for the pure helpers (`parsing`, `dedup.normalize`, `websearch` age/result filtering). No network or API key needed; the repo root is on `sys.path` via `[tool.pytest.ini_options]`.
- **dedup.py** — SQLite-backed store of seen entry links (`seen_links.db`), used to avoid re-summarizing the same article across runs. `normalize()` canonicalizes URLs (lowercase scheme/host, strip `www.`/trailing slash/fragment/tracking params) before comparison; `load_seen()` returns the current normalized set (pruning entries older than `RETENTION_DAYS`); `mark_seen()` records links with a timestamp. Links are committed via `mark_seen()` only *after* their chunk is delivered (called per chunk from `bot.py`'s `_send()`), so a failed send re-surfaces the undelivered items next run. Migrates a legacy `seen_links.json` on first connect.

## Notes

- `seen_links.json` is runtime state (regenerated on each run); don't treat it as source of truth for code changes.
- `.shadow.env` is a tracked template listing the required env var names (no values) — use it as the reference for what to put in your local `.env`.