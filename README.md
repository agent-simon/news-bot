# news-bot

A Telegram bot that aggregates news on Playwright/E2E testing and AI test automation, summarizes new items with Claude, and posts the summary to a Telegram chat — on demand via `/news` or automatically every day at 08:00.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Install uv, then sync the locked dependencies into a project-local `.venv`:

```bash
uv sync
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
uv run bot.py
```

- Send `/news` to the bot for an on-demand summary of new items.
- A daily summary is automatically sent to `CHAT_ID` at 08:00 server time.

## Running as a systemd service

A unit template lives at [`deploy/news-bot.service`](deploy/news-bot.service). It runs the uv-managed interpreter (`.venv/bin/python`) directly, so the service does no dependency resolution at start — run `uv sync` first to create the `.venv`. Adjust `User=` and the three paths to match your checkout, then install it:

```bash
uv sync                                        # create .venv from uv.lock
sudo cp deploy/news-bot.service /etc/systemd/system/news-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot.service   # start now + on every boot
systemctl status news-bot.service
journalctl -u news-bot.service -f              # tail logs / watch a run
```

After updating the code:

```bash
git pull
uv sync                                        # apply any dependency changes
sudo systemctl restart news-bot.service
```

Notes:
- **`WorkingDirectory` must be the repo checkout** — `.env` and the `seen_links.db` dedup store are resolved relative to it.
- `seen_links.db` (and a legacy `seen_links.json`) are runtime state, written to `WorkingDirectory`; they're gitignored.
- The daily job fires at **08:00 server time** — check the host timezone with `timedatectl`.
- No system packages are required beyond the venv: `sqlite3` is part of the Python standard library.

## Configuration

RSS/Atom sources and search topics live in [`sources.json`](sources.json) (edit feeds and topics there). Each `sources` entry has a feed `url`, a `limit` on how many items to consider per run, and a display `name`. Items older than `MAX_AGE_DAYS` (default 3) or already seen (tracked in `seen_links.db`, a SQLite store) are skipped. Links are committed as seen only after the summary is successfully delivered, so a failed run re-surfaces its items next time.

In addition to the RSS sources, Claude performs its own web search each run (`search_web()`) over the `base_topics` from `sources.json` to find recent items on the same topics, which are merged in before summarizing. On the on-demand `/news` command it also mixes in a random sample of `search_themes` for variety.