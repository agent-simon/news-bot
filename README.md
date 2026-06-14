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

## Auto-deploy

[`deploy/auto-deploy.sh`](deploy/auto-deploy.sh) pulls `origin/main`, and if there are new commits, runs `uv sync` and restarts `news-bot.service`. It's a no-op (exit 0) when already up to date, and refuses to run if the checkout has local changes. [`deploy/news-bot-deploy.timer`](deploy/news-bot-deploy.timer) runs it every 15 minutes via [`deploy/news-bot-deploy.service`](deploy/news-bot-deploy.service) (oneshot).

The restart needs passwordless `sudo`. Create `/etc/sudoers.d/news-bot-deploy` (via `sudo visudo -f /etc/sudoers.d/news-bot-deploy`, so it's syntax-checked) — this also covers the `start`/`stop` used by [`scripts/pi-bot.sh`](scripts/pi-bot.sh) below:

```
youruser ALL=(root) NOPASSWD: /usr/bin/systemctl start news-bot.service, /usr/bin/systemctl stop news-bot.service, /usr/bin/systemctl restart news-bot.service
```

Then install the timer:

```bash
sudo cp deploy/news-bot-deploy.service deploy/news-bot-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot-deploy.timer
systemctl list-timers news-bot-deploy.timer   # confirm scheduled
journalctl -u news-bot-deploy.service -f      # watch a deploy run
```

To deploy immediately instead of waiting for the timer: `sudo systemctl start news-bot-deploy.service` on the Pi, or from your local machine, [`scripts/pi-deploy.sh`](scripts/pi-deploy.sh) SSHes in and runs `deploy/auto-deploy.sh` directly:

```bash
scripts/pi-deploy.sh
```

Same SSH access as [`scripts/pi-bot.sh`](scripts/pi-bot.sh) below — no extra sudoers entry needed, since the restart it performs is already covered by the snippet above. Override the target with `PI_HOST=user@host` (and `REPO_DIR=...` if the checkout path differs).

## Local development

Telegram only allows **one active poller per bot token** — running the same bot both on the Pi and locally causes `Conflict: terminated by other getUpdates request` errors and steals updates from whichever instance polls less often.

To develop locally without disrupting the Pi, either:

- **Use a separate dev bot** — create a second bot via [@BotFather](https://t.me/BotFather), and in your local `.env` set `TELEGRAM_BOT_TOKEN` to its token. You can reuse the same `CHAT_ID` (add the dev bot to that chat) or point `CHAT_ID` at a separate test chat. `ANTHROPIC_API_KEY` and `sources.json` can stay the same — only the bot identity differs.
- **Stop the Pi's bot while you work** — [`scripts/pi-bot.sh`](scripts/pi-bot.sh) SSHes into the Pi to stop/start/restart `news-bot.service`:
  ```bash
  scripts/pi-bot.sh stop      # before running locally with the same token
  scripts/pi-bot.sh start     # when done
  scripts/pi-bot.sh status
  ```
  Requires SSH key access to the Pi (`ssh-copy-id user@host` once) and the sudoers entry from "Auto-deploy" above. Override the target with `PI_HOST=user@host`. Note: the auto-deploy timer restarts `news-bot.service` on its own schedule, so if it fires while you're working it'll undo a `stop` — either also stop `news-bot-deploy.timer`, or just re-run `pi-bot.sh stop`.

## Configuration

RSS/Atom sources and search topics live in [`sources.json`](sources.json) (edit feeds and topics there). Each `sources` entry has a feed `url`, a `limit` on how many items to consider per run, and a display `name`. Items older than `MAX_AGE_DAYS` (default 3) or already seen (tracked in `seen_links.db`, a SQLite store) are skipped. Links are committed as seen only after the summary is successfully delivered, so a failed run re-surfaces its items next time.

In addition to the RSS sources, Claude performs its own web search each run (`search_web()`) over the `base_topics` from `sources.json` to find recent items on the same topics, which are merged in before summarizing. On the on-demand `/news` command it also mixes in a random sample of `search_themes` for variety.