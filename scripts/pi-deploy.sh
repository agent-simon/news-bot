#!/usr/bin/env bash
# Trigger an immediate deploy on the Pi over SSH, instead of waiting for
# news-bot-deploy.timer's next 15-minute tick. Starts the news-bot-deploy
# oneshot unit, which runs deploy/auto-deploy.sh as the `newsbot` account
# (fetches origin/main, fast-forwards if it moved, runs `uv sync`, restarts
# news-bot.service — no-op if already up to date), then prints its log.
#
# We start the unit rather than exec auto-deploy.sh directly so it runs as the
# checkout's owner; running it as your SSH login user trips git's dubious-
# ownership guard on the newsbot-owned /opt/news-bot.
#
# Usage: scripts/pi-deploy.sh
# Reads PI_HOST=user@host from the repo's .env (or the environment).
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

# `start` on a Type=oneshot unit blocks until auto-deploy.sh finishes; its
# output goes to the journal, so tail it to see the result.
ssh "$PI_HOST" "sudo systemctl start news-bot-deploy.service && journalctl -u news-bot-deploy.service -n 20 --no-pager"
