#!/usr/bin/env bash
# Trigger an immediate deploy on the Pi over SSH, instead of waiting for
# news-bot-deploy.timer's next 15-minute tick. Runs deploy/auto-deploy.sh in
# the Pi's checkout: fetches origin/main, fast-forwards if it moved, runs
# `uv sync`, and restarts news-bot.service (no-op if already up to date).
#
# Usage: scripts/pi-deploy.sh
# Override the target with PI_HOST=user@host (default: sam@pizero.local) and
# the checkout path with REPO_DIR (default: /home/sam/work/news-bot).
set -euo pipefail

PI_HOST="${PI_HOST:-sam@pizero.local}"
REPO_DIR="${REPO_DIR:-/home/sam/work/news-bot}"

ssh "$PI_HOST" "$REPO_DIR/deploy/auto-deploy.sh"
