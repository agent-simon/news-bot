#!/usr/bin/env bash
# One-time migration from the old fixed-name systemd units to the templated
# (%i) ones. Run this ON THE PI, as the account the bot runs as, from inside
# the repo checkout:
#
#   scripts/migrate-to-templated-units.sh
#
# It disables/removes the old news-bot.service + news-bot-deploy.{service,timer},
# installs the new news-bot@.service + news-bot-deploy@.{service,timer}, enables
# them for the current user, and refreshes the sudoers snippet. Idempotent —
# safe to re-run.
set -euo pipefail

USER_NAME="$(id -un)"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_DIR=/etc/systemd/system
SUDOERS_FILE=/etc/sudoers.d/news-bot-deploy

echo "Migrating news-bot units to templated form for user '$USER_NAME'"
echo "  repo: $REPO_DIR"

# 1. Tear down the old fixed-name units if present.
for unit in news-bot.service news-bot-deploy.timer news-bot-deploy.service; do
    if systemctl list-unit-files "$unit" --no-legend | grep -q .; then
        echo "Disabling old $unit"
        sudo systemctl disable --now "$unit" 2>/dev/null || true
        sudo rm -f "$SYSTEMD_DIR/$unit"
    fi
done

# 2. Ensure the virtualenv exists — the service execs .venv/bin/python, so a
# missing venv fails the unit with status=203/EXEC.
echo "Syncing dependencies (uv sync)"
if ! command -v uv >/dev/null; then
    echo "uv not found on PATH — install uv (or run 'uv sync' manually) first." >&2
    exit 1
fi
( cd "$REPO_DIR" && uv sync )

# 3. Install the templated unit files.
echo "Installing templated unit files"
sudo cp "$REPO_DIR"/deploy/news-bot@.service \
        "$REPO_DIR"/deploy/news-bot-deploy@.service \
        "$REPO_DIR"/deploy/news-bot-deploy@.timer \
        "$SYSTEMD_DIR/"
sudo systemctl daemon-reload

# 4. Refresh the passwordless-sudo snippet for the restart (new unit name).
echo "Writing $SUDOERS_FILE"
tmp_sudoers="$(mktemp)"
cat >"$tmp_sudoers" <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl start news-bot@$USER_NAME.service, /usr/bin/systemctl stop news-bot@$USER_NAME.service, /usr/bin/systemctl restart news-bot@$USER_NAME.service
EOF
sudo visudo -cf "$tmp_sudoers"            # syntax-check before installing
sudo install -m 0440 "$tmp_sudoers" "$SUDOERS_FILE"
rm -f "$tmp_sudoers"

# 5. Enable the new instances for this user.
echo "Enabling news-bot@$USER_NAME.service and news-bot-deploy@$USER_NAME.timer"
sudo systemctl enable --now "news-bot@$USER_NAME.service"
sudo systemctl enable --now "news-bot-deploy@$USER_NAME.timer"

echo
echo "Done. Status:"
systemctl status "news-bot@$USER_NAME.service" --no-pager || true
systemctl list-timers "news-bot-deploy@$USER_NAME.timer" --no-pager || true
