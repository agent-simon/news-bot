# news-bot

A Telegram bot that aggregates news on Playwright/E2E testing and AI test automation, summarizes new items with OpenAI, and posts the summary to a Telegram chat — on demand via `/news` or automatically every day at 08:00.

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
- `OPENAI_API_KEY` — OpenAI API key
- `CHAT_ID` — Telegram chat ID to receive the daily summary

## Running

```bash
uv run news-bot
```

(The code lives in the `newsbot` package under `src/`; `uv sync` installs the
`news-bot` console script. `uv run python -m newsbot` works too, as does the
legacy `uv run python bot.py` via a thin root shim.)

- Send `/news` to the bot for an on-demand summary of new items.
- A daily summary is automatically sent to `CHAT_ID` at 08:00 server time.

Common tasks are also wrapped in a `Makefile` — run `make` to list targets (`make sync`, `make run`, `make pi-stop`/`pi-start`/`pi-status`/`pi-logs`, `make deploy`).

## Running as a systemd service

The bot runs as [`deploy/news-bot.service`](deploy/news-bot.service) under a dedicated, unprivileged `newsbot` system account, out of `/opt/news-bot` (the conventional home for a self-contained app, kept off your login user's home and privileges). The unit runs the uv-installed `news-bot` console script (`.venv/bin/news-bot`) directly, so the service does no dependency resolution at start.

> **Upgrading an existing Pi to the `src/` layout:** the `ExecStart` changed from `…/python …/bot.py` to `…/.venv/bin/news-bot`. Auto-deploy does **not** reinstall unit files, so after the first pull that includes this change, re-run `sudo /opt/news-bot/deploy/install.sh` to apply the new unit. Until then the service keeps running via the root `bot.py` shim, so there's no downtime.

**Prerequisites:** `git` and [uv](https://docs.astral.sh/uv/). Install uv (the installer puts it in `~/.local/bin`; the install script copies it system-wide for the `newsbot` account):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Install (fresh machine):**

```bash
sudo git clone https://github.com/agent-simon/news-bot.git /opt/news-bot
sudo /opt/news-bot/deploy/install.sh
```

 [`deploy/install.sh`](deploy/install.sh) is idempotent (safe to re-run) and does everything below: creates the `newsbot` account, builds the venv, installs the units + sudoers, and enables the service and auto-deploy timer. It configures the system from the **currently checked-out code** — it does not pull (updating the code is `git pull` / auto-deploy's job), so to apply newer unit files, `git pull` first and then re-run it. On the **first** run it seeds `.env` from `.shadow.env` and stops so you can fill in your tokens — edit `/opt/news-bot/.env` (`TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `CHAT_ID`), then run the script again to finish. Then:

```bash
systemctl status news-bot.service
journalctl -u news-bot.service -f                  # tail logs / watch a run
```

Override defaults with env vars if needed, e.g. `sudo ADMIN_USER=pi REPO_URL=… /opt/news-bot/deploy/install.sh`.

<details>
<summary>What the script does (the manual equivalent)</summary>

```bash
# 1. Dedicated service account — declared in deploy/news-bot.sysusers, applied by:
sudo install -m644 /opt/news-bot/deploy/news-bot.sysusers /etc/sysusers.d/news-bot.conf
sudo systemd-sysusers                                  # no login, home = app dir

# 2. Ownership + config (secrets not world-readable):
sudo chown -R newsbot:newsbot /opt/news-bot
sudo install -m640 -o newsbot -g newsbot /opt/news-bot/.shadow.env /opt/news-bot/.env  # fill in

# 3. uv on a system-wide PATH so newsbot can run it; build the venv as newsbot
#    (HOME set explicitly — nologin means no `sudo -i`):
sudo cp "$(command -v uv)" /usr/local/bin/
sudo -u newsbot env HOME=/opt/news-bot bash -c 'cd /opt/news-bot && uv sync'

# 4. Units + the tmpfiles rule that keeps .env at 0640, then enable:
sudo cp /opt/news-bot/deploy/news-bot.service /etc/systemd/system/
sudo install -m644 /opt/news-bot/deploy/news-bot.tmpfiles /etc/tmpfiles.d/news-bot.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/news-bot.conf
sudo systemctl daemon-reload && sudo systemctl enable --now news-bot.service
```
</details>

Updating the code by hand (auto-deploy, below, does this for you):

```bash
sudo -u newsbot env HOME=/opt/news-bot bash -c 'cd /opt/news-bot && git pull && uv sync'
sudo systemctl restart news-bot.service
```

Notes:
- **`WorkingDirectory=/opt/news-bot` is load-bearing** — `.env` and the `seen_links.db` dedup store are resolved relative to it.
- `seen_links.db` (and a legacy `seen_links.json`) are runtime state, written to `WorkingDirectory`; they're gitignored.
- The daily job fires at **08:00 server time** — check the host timezone with `timedatectl`.
- No system packages are required beyond the venv: `sqlite3` is part of the Python standard library.

## Auto-deploy

`deploy/install.sh` already installs and enables this; the rest of this section explains what it set up (and how to do it by hand).

[`deploy/auto-deploy.sh`](deploy/auto-deploy.sh) pulls `origin/main`, and if there are new commits, runs `uv sync` and restarts `news-bot.service`. It's a no-op (exit 0) when already up to date, and refuses to run if the checkout has local changes. [`deploy/news-bot-deploy.timer`](deploy/news-bot-deploy.timer) runs it every 15 minutes via [`deploy/news-bot-deploy.service`](deploy/news-bot-deploy.service) (oneshot), both also running as `newsbot`.

Auto-deploy updates **code only** — it does not install changed systemd unit files into `/etc/systemd/system` (it runs as the unprivileged `newsbot` account by design, and granting it root unit-installs would be a privilege-escalation path). When an update touches a unit file it logs a `WARNING` to the journal; apply it by re-running `deploy/install.sh` (or `cp`-ing the unit + `daemon-reload`) as root.

The restart needs passwordless `sudo`. Create `/etc/sudoers.d/news-bot-deploy` (via `sudo visudo -f /etc/sudoers.d/news-bot-deploy`, so it's syntax-checked). Two lines, least-privilege: `newsbot` (the deploy account) gets only `restart`; your login user — replace `<you>` — gets `start`/`stop`/`restart` for [`scripts/pi-bot.sh`](scripts/pi-bot.sh) plus `start news-bot-deploy.service` to trigger a deploy on demand via [`scripts/pi-deploy.sh`](scripts/pi-deploy.sh):

```
newsbot ALL=(root) NOPASSWD: /usr/bin/systemctl restart news-bot.service
<you> ALL=(root) NOPASSWD: /usr/bin/systemctl start news-bot.service, /usr/bin/systemctl stop news-bot.service, /usr/bin/systemctl restart news-bot.service, /usr/bin/systemctl start news-bot-deploy.service
```

Then install the timer:

```bash
sudo cp /opt/news-bot/deploy/news-bot-deploy.service /opt/news-bot/deploy/news-bot-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot-deploy.timer
systemctl list-timers news-bot-deploy.timer      # confirm scheduled
journalctl -u news-bot-deploy.service -f         # watch a deploy run
```

To deploy immediately instead of waiting for the timer: `sudo systemctl start news-bot-deploy.service` on the Pi, or from your local machine, [`scripts/pi-deploy.sh`](scripts/pi-deploy.sh) SSHes in and starts that same oneshot unit (so the deploy runs as `newsbot`, the checkout's owner):

```bash
scripts/pi-deploy.sh
```

Same SSH access as [`scripts/pi-bot.sh`](scripts/pi-bot.sh) below, and it relies on the `start news-bot-deploy.service` grant in the sudoers snippet above. Reads `PI_HOST=user@host` from `.env`.

## Local development

Telegram only allows **one active poller per bot token** — running the same bot both on the Pi and locally causes `Conflict: terminated by other getUpdates request` errors and steals updates from whichever instance polls less often.

To develop locally without disrupting the Pi, either:

- **Use a separate dev bot** — create a second bot via [@BotFather](https://t.me/BotFather), and in your local `.env` set `TELEGRAM_BOT_TOKEN` to its token. You can reuse the same `CHAT_ID` (add the dev bot to that chat) or point `CHAT_ID` at a separate test chat. `OPENAI_API_KEY` and `sources.json` can stay the same — only the bot identity differs.
- **Stop the Pi's bot while you work** — [`scripts/pi-bot.sh`](scripts/pi-bot.sh) SSHes into the Pi to stop/start/restart `news-bot.service`:
  ```bash
  scripts/pi-bot.sh stop      # before running locally with the same token
  scripts/pi-bot.sh start     # when done
  scripts/pi-bot.sh status
  ```
  Requires SSH key access to the Pi (`ssh-copy-id user@host` once), `PI_HOST=user@host` in your `.env`, and the sudoers entry for your login user from "Auto-deploy" above. Note: the auto-deploy timer restarts the bot on its own schedule, so if it fires while you're working it'll undo a `stop` — either also stop `news-bot-deploy.timer`, or just re-run `pi-bot.sh stop`.

## Configuration

RSS/Atom sources and search topics live in [`src/newsbot/sources.json`](src/newsbot/sources.json) (edit feeds and topics there). Each `sources` entry has a feed `url`, a `limit` on how many items to consider per run, and a display `name`. Items older than `MAX_AGE_DAYS` (default 3) or already seen (tracked in `seen_links.db`, a SQLite store) are skipped. Links are committed as seen only after the summary is successfully delivered, so a failed run re-surfaces its items next time.

In addition to the RSS sources, OpenAI performs its own web search each run (`search_web()`) over the `base_topics` from `sources.json` to find recent items on the same topics, which are merged in before summarizing. On the on-demand `/news` command it also mixes in a random sample of `search_themes` for variety.
