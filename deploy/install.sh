#!/usr/bin/env bash
#
# Idempotent installer for the news-bot systemd service. Safe to re-run.
#
# Fresh machine:
#   sudo git clone https://github.com/agent-simon/news-bot.git /opt/news-bot
#   sudo /opt/news-bot/deploy/install.sh
#
# Overridable via environment (defaults in parentheses):
#   APP_USER   service account name                         (newsbot)
#   APP_DIR    install location / git checkout              (/opt/news-bot)
#   REPO_URL   git remote, used only to clone if APP_DIR is empty
#                          (https://github.com/agent-simon/news-bot.git)
#   BRANCH     branch to clone (initial clone only)         (main)
#   ADMIN_USER human admin granted start/stop/restart sudo  ($SUDO_USER)
#
# NOTE: the bundled .sysusers / .tmpfiles files assume the APP_USER/APP_DIR
# defaults; override those env vars only if you also adjust those files.
set -euo pipefail

APP_USER="${APP_USER:-newsbot}"
APP_DIR="${APP_DIR:-/opt/news-bot}"
REPO_URL="${REPO_URL:-https://github.com/agent-simon/news-bot.git}"
BRANCH="${BRANCH:-main}"
ADMIN_USER="${ADMIN_USER:-${SUDO_USER:-}}"

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must run as root — use: sudo $0"

# 1. Service account — declared in sysusers.d, created by systemd-sysusers.
log "Ensuring service user '$APP_USER' exists"
install -D -m 0644 "$DEPLOY_DIR/news-bot.sysusers" /etc/sysusers.d/news-bot.conf
systemd-sysusers /etc/sysusers.d/news-bot.conf

# 2. Code at $APP_DIR. Clone on first run; otherwise install whatever is already
#    checked out. The installer deliberately does NOT update the code — that's
#    `git pull` / auto-deploy's job. Not pulling here also means the installer
#    can never rewrite itself mid-run (a stale checkout used to corrupt the
#    running script).
if [[ ! -d "$APP_DIR/.git" ]]; then
    log "Cloning $REPO_URL into $APP_DIR"
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# 3. Config — never clobber an existing .env. On first run, seed it from the
#    template and stop so the operator can fill in secrets, then re-run.
if [[ ! -f "$APP_DIR/.env" ]]; then
    install -m 0640 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.shadow.env" "$APP_DIR/.env"
    die "seeded $APP_DIR/.env — fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, CHAT_ID, then re-run $0"
fi

# 4. uv must be on a system-wide PATH so $APP_USER (not just you) can run it.
#    Probe root's PATH, then the admin user's login PATH (uv often lives in
#    ~/.local/bin, which sudo's sanitised PATH can't see).
if ! sudo -u "$APP_USER" sh -c 'command -v uv' >/dev/null 2>&1; then
    uv_src="$(command -v uv || true)"
    if [[ -z "$uv_src" && -n "$ADMIN_USER" ]]; then
        uv_src="$(sudo -u "$ADMIN_USER" sh -lc 'command -v uv' 2>/dev/null || true)"
    fi
    if [[ -n "$uv_src" ]]; then
        log "Copying uv ($uv_src) to /usr/local/bin for $APP_USER"
        install -m 0755 "$uv_src" /usr/local/bin/uv
    else
        die "uv not found — install it (https://docs.astral.sh/uv/) so it's on PATH, then re-run"
    fi
fi

# 5. Build/refresh the virtualenv as the service user (HOME set for uv's cache).
log "Syncing dependencies (uv sync) as $APP_USER"
sudo -u "$APP_USER" env HOME="$APP_DIR" sh -c 'cd "$1" && uv sync' sh "$APP_DIR"

# 6. systemd units + tmpfiles rule, then reload.
log "Installing systemd units"
install -m 0644 "$DEPLOY_DIR/news-bot.service" \
                "$DEPLOY_DIR/news-bot-deploy.service" \
                "$DEPLOY_DIR/news-bot-deploy.timer" /etc/systemd/system/
install -D -m 0644 "$DEPLOY_DIR/news-bot.tmpfiles" /etc/tmpfiles.d/news-bot.conf
systemd-tmpfiles --create /etc/tmpfiles.d/news-bot.conf
systemctl daemon-reload

# 7. Passwordless sudo for the restart — least privilege, syntax-checked.
log "Installing sudoers snippet"
sudoers_tmp="$(mktemp)"
{
    echo "$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart news-bot.service"
    if [[ -n "$ADMIN_USER" && "$ADMIN_USER" != "root" ]]; then
        echo "$ADMIN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start news-bot.service, /usr/bin/systemctl stop news-bot.service, /usr/bin/systemctl restart news-bot.service"
    fi
} >"$sudoers_tmp"
visudo -cf "$sudoers_tmp"
install -m 0440 "$sudoers_tmp" /etc/sudoers.d/news-bot-deploy
rm -f "$sudoers_tmp"

# 8. Enable + start the bot and the auto-deploy timer.
log "Enabling and starting services"
systemctl enable --now news-bot.service
systemctl enable --now news-bot-deploy.timer

log "Done."
systemctl --no-pager --full status news-bot.service || true
