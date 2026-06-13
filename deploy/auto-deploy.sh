#!/usr/bin/env bash
# Pull-based auto-deploy: fetch origin/main, and if there are new commits,
# fast-forward, sync dependencies, and restart the service. Run periodically
# by news-bot-deploy.timer. Safe to run with no changes (no-op, exit 0).
set -euo pipefail

# Non-interactive sessions (systemd, ssh) don't source ~/.bashrc, so uv's
# install location is missing from PATH even though it's on PATH interactively.
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree has local changes — skipping auto-deploy." >&2
    git status --short >&2
    exit 1
fi

git fetch origin main

LOCAL=$(git rev-parse main)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "Already up to date ($LOCAL)."
    exit 0
fi

echo "Updating $LOCAL -> $REMOTE"
git merge --ff-only origin/main
uv sync
sudo systemctl restart news-bot.service
echo "Deployed $REMOTE and restarted news-bot.service"
