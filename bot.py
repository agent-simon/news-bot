# bot.py — compatibility shim.
#
# The bot now lives in the `newsbot` package (src/newsbot/); the real entrypoint
# is the `news-bot` console script (or `python -m newsbot`). This shim keeps the
# old `python bot.py` invocation working — notably the Pi's pre-existing
# systemd unit (ExecStart=.../python .../bot.py) until its unit file is
# reinstalled via deploy/install.sh. Safe to delete once that's done.
from newsbot.bot import main

if __name__ == "__main__":
    main()
