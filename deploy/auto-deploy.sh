#!/usr/bin/env bash
# Pull-based auto-deploy: fetch origin/main, and if there are new commits,
# fast-forward, sync dependencies, and restart the service. Run periodically
# by news-bot-deploy.timer. Safe to run with no changes (no-op, exit 0).
#
# This deliberately does NOT install changed systemd unit files into
# /etc/systemd/system. It runs as the unprivileged newsbot account whose only
# sudo right is `restart news-bot.service`; letting it write units as root +
# reload would let a compromised account set User=root and escalate. Installing
# units stays a human action (deploy/install.sh). Instead we just WARN below
# when an update changes a unit so the reinstall isn't silently forgotten.
set -euo pipefail

# Non-interactive sessions (systemd, ssh) don't source ~/.bashrc, so a uv that
# was installed under $HOME may be missing from PATH. /usr/local/bin (where a
# system-wide uv lives) is already on the default PATH; keep this for the
# home-install case too.
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "$0")/.."

SOURCE_FILE="src/newsbot/sources.json"
SOURCE_TEMPLATE="sources.shadow.json"

# `git merge --ff-only` below rewrites this very file, and bash may continue
# executing stale (pre-merge) content for the rest of this process. Re-exec
# after merging so the remaining steps run from the freshly-merged script.
if [ -z "${AUTO_DEPLOY_APPLY:-}" ]; then
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
    # Note (before merging) whether this update changes any installed unit file,
    # so we can warn after — auto-deploy can't reinstall them (see header).
    UNIT_CHANGED=
    if git diff --name-only "$LOCAL" "$REMOTE" | grep -qE '^deploy/.*\.(service|timer)$'; then
        UNIT_CHANGED=1
    fi

    # Preserve a customized tracked sources.json across the migration to the
    # ignored local file. Fresh installs fall back to sources.shadow.json below.
    SOURCE_BACKUP=
    if [ -f "$SOURCE_FILE" ]; then
        SOURCE_BACKUP="$(mktemp)"
        cp "$SOURCE_FILE" "$SOURCE_BACKUP"
    fi

    git merge --ff-only origin/main
    exec env AUTO_DEPLOY_APPLY=1 AUTO_DEPLOY_UNIT_CHANGED="$UNIT_CHANGED" \
        AUTO_DEPLOY_SOURCES_BACKUP="${SOURCE_BACKUP:-}" "$0"
fi

if [ -n "${AUTO_DEPLOY_SOURCES_BACKUP:-}" ]; then
    if [ ! -f "$SOURCE_FILE" ]; then
        cp "$AUTO_DEPLOY_SOURCES_BACKUP" "$SOURCE_FILE"
    fi
    rm -f "$AUTO_DEPLOY_SOURCES_BACKUP"
elif [ ! -f "$SOURCE_FILE" ]; then
    cp "$SOURCE_TEMPLATE" "$SOURCE_FILE"
fi

uv sync
sudo systemctl restart news-bot.service
echo "Deployed $(git rev-parse HEAD) and restarted news-bot.service"

if [ -n "${AUTO_DEPLOY_UNIT_CHANGED:-}" ]; then
    echo "WARNING: this update changed systemd unit file(s) under deploy/. The" >&2
    echo "running service still uses the previously installed unit — re-run" >&2
    echo "deploy/install.sh (as root) to apply the new unit." >&2
fi
