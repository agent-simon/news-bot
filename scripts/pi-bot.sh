#!/usr/bin/env bash
# Start/stop/restart/check news-bot.service on the Raspberry Pi over SSH.
#
# Telegram allows only one getUpdates poller per bot token, so running the
# bot locally while the Pi's instance is also polling causes Conflict
# errors. Stop the Pi's bot before a local run, then start it again when
# you're done.
#
# Usage: scripts/pi-bot.sh {start|stop|restart|status}
# Override the target with PI_HOST=user@host (default: sam@pizero.local).
set -euo pipefail

PI_HOST="${PI_HOST:-sam@pizero.local}"
SERVICE="news-bot.service"

case "${1:-}" in
    start|stop|restart)
        ssh "$PI_HOST" "sudo systemctl $1 $SERVICE && systemctl status $SERVICE --no-pager"
        ;;
    status)
        ssh "$PI_HOST" "systemctl status $SERVICE --no-pager"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}" >&2
        exit 1
        ;;
esac
