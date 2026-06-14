#!/usr/bin/env bash
# Start/stop/restart/check the news bot on the Raspberry Pi over SSH.
#
# Telegram allows only one getUpdates poller per bot token, so running the
# bot locally while the Pi's instance is also polling causes Conflict
# errors. Stop the Pi's bot before a local run, then start it again when
# you're done.
#
# Usage: scripts/pi-bot.sh {start|stop|restart|status|logs}
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

# The bot runs under the dedicated newsbot account, but you SSH in as your own
# login user; the start/stop/restart sudo rights are granted to that login user
# in /etc/sudoers.d/news-bot-deploy (see README's auto-deploy section).
SERVICE="news-bot.service"

case "${1:-}" in
    start|stop|restart)
        ssh "$PI_HOST" "sudo systemctl $1 $SERVICE && systemctl status $SERVICE --no-pager"
        ;;
    status)
        ssh "$PI_HOST" "systemctl status $SERVICE --no-pager"
        ;;
    logs)
        # -t: allocate a TTY so Ctrl-C cleanly stops the remote `journalctl -f`.
        ssh -t "$PI_HOST" "journalctl -u $SERVICE -n 50 -f"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}" >&2
        exit 1
        ;;
esac
