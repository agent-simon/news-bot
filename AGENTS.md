# Repository Instructions

## Workflow

- Before making any repository changes, check out a new branch first.

## Commands

- Use `uv sync` to create/update the locked `.venv` and install dev tools.
- Run the bot with `uv run news-bot` (equivalently `uv run python -m newsbot`); `bot.py` is only a legacy shim.
- Run tests with `uv run pytest`; target a focused test with `uv run pytest tests/test_websearch.py` or `uv run pytest tests/test_websearch.py::test_name`.
- Run lint with `uv run ruff check .`; Ruff uses a 100-character line length and rules `E,F,I,UP,B` with `E501` ignored.
- `make` lists convenience targets; `make run` starts the bot, while `make pi-*` and `make deploy` require Pi SSH configuration.

## Structure

- Application code is the `newsbot` package under `src/newsbot/`; the console entrypoint is `newsbot.bot:main`.
- `pipeline.collect_new_items()` combines RSS and one OpenAI web-search pass; `render.summarize()` calls OpenAI for summaries; `bot._send()` delivers Telegram-sized chunks.
- `bot.py` at the repository root is a compatibility shim, not the application implementation.
- Tests cover pure helpers only and require no network or API credentials; pytest adds `src` to `PYTHONPATH` via `pyproject.toml`.

## Configuration And State

- Copy `.shadow.env` to `.env`; `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and `CHAT_ID` are required to run the bot.
- `DAILY_NEWS` and `WEB_SEARCH` are enabled unless set to `off`, `false`, `0`, `no`, or `disabled`; `SOURCES_PATH` can point to an alternate feed/topic JSON file, which is read fresh on each run.
- Edit the ignored `src/newsbot/sources.json` for local feeds/topics; `src/newsbot/sources.shadow.json` is the tracked template. Do not edit or commit `seen_links.db`/`seen_links.json`; they are runtime dedup state.
- Items are marked seen only after their Telegram chunk is delivered, so do not move dedup marking earlier without preserving retry behavior.

## Architecture Details

- `bot.py` registers `/news` and the optional daily 08:00 US/Eastern job, then collects, summarizes, chunks, and sends messages.
- `config.py` reads environment flags and the feed/topic JSON on each call; `SOURCES_PATH` overrides the package-relative local `sources.json`.
- `rss.py` reads configured feeds without persisting dedup state; `websearch.py` performs one OpenAI web-search pass and filters invented or stale links.
- `pipeline.py` deduplicates RSS and web-search candidates; `render.py` keeps titles and links local while OpenAI supplies emoji and summaries.
- `dedup.py` stores normalized seen links in SQLite with 14-day retention and migrates legacy `seen_links.json` on first connection.

## Operational Constraints

- Telegram permits one active poller per bot token. Before a local run using the Pi token, stop the Pi with `scripts/pi-bot.sh stop`, or use a separate development bot; restart it afterward.
- `deploy/auto-deploy.sh` refuses dirty checkouts, fast-forwards `origin/main`, runs `uv sync`, and restarts the service. It does not install changed systemd units; rerun `sudo deploy/install.sh` for unit changes.
- `scripts/pi-deploy.sh` is the supported immediate remote deploy trigger; it starts the deploy oneshot so deployment runs as the `newsbot` checkout owner.

See `README.md` for detailed local development, systemd, and deployment procedures.
