#!/usr/bin/env bash
# Trigger an immediate deploy on the Pi over SSH, instead of waiting for
# news-bot-deploy.timer's next 15-minute tick. Runs deploy/auto-deploy.sh in
# the Pi's checkout: fetches origin/main, fast-forwards if it moved, runs
# `uv sync`, and restarts news-bot.service (no-op if already up to date).
#
# Usage: scripts/pi-deploy.sh
# Reads PI_HOST=user@host from the repo's .env (or the environment). Override
# the checkout path with REPO_DIR (default: /home/youruser/work/news-bot).
set -euo pipefail

ENV_FILE="$(dirname "$0")/../.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

if [[ -z "${PI_HOST:-}" ]]; then
    echo "PI_HOST is not set; add it to .env (e.g. PI_HOST=user@host)" >&2
    exit 1
fi

REPO_DIR="${REPO_DIR:-/home/youruser/work/news-bot}"

ssh "$PI_HOST" "$REPO_DIR/deploy/auto-deploy.sh"
