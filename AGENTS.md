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
- `pipeline.collect_new_items()` combines RSS and one Claude web-search pass; `render.summarize()` calls Claude for summaries; `bot._send()` delivers Telegram-sized chunks.
- Tests cover pure helpers only and require no network or API credentials; pytest adds `src` to `PYTHONPATH` via `pyproject.toml`.

## Configuration And State

- Copy `.shadow.env` to `.env`; `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and `CHAT_ID` are required to run the bot.
- `DAILY_NEWS` and `WEB_SEARCH` are enabled unless set to `off`, `false`, `0`, `no`, or `disabled`; `SOURCES_PATH` can point to an untracked feed/topic JSON file, which is read fresh on each run.
- Edit `src/newsbot/sources.json` for tracked feeds/topics. Do not edit or commit `seen_links.db`/`seen_links.json`; they are runtime dedup state.
- Items are marked seen only after their Telegram chunk is delivered, so do not move dedup marking earlier without preserving retry behavior.

## Operational Constraints

- Telegram permits one active poller per bot token. Before a local run using the Pi token, stop the Pi with `scripts/pi-bot.sh stop`, or use a separate development bot; restart it afterward.
- `deploy/auto-deploy.sh` refuses dirty checkouts, fast-forwards `origin/main`, runs `uv sync`, and restarts the service. It does not install changed systemd units; rerun `sudo deploy/install.sh` for unit changes.
- `scripts/pi-deploy.sh` is the supported immediate remote deploy trigger; it starts the deploy oneshot so deployment runs as the `newsbot` checkout owner.

See `CLAUDE.md` and `README.md` for the detailed architecture and systemd setup.
