# bot.py
import asyncio
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from .config import daily_news_enabled, load_config, web_search_enabled
from .dedup import mark_seen
from .pipeline import collect_new_items
from .render import summarize

logger = logging.getLogger(__name__)

load_dotenv()

# Telegram rejects messages longer than 4096 chars; stay safely under it.
TELEGRAM_LIMIT = 4000
_news_run_lock = asyncio.Lock()
NEWS_BUSY_MESSAGE = "A news run is already in progress. Please try again shortly."

def _chunks(entries, limit=TELEGRAM_LIMIT):
    """Group rendered entries ({text, links}) into Telegram-sized pieces on
    entry boundaries so HTML tags are never cut mid-tag. Each chunk is a
    (text, links) pair carrying the item links it contains, so the sender can
    mark them seen only once that chunk is actually delivered."""
    chunks = []
    current = ""
    current_links = []
    for entry in entries:
        block = entry["text"]
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            current_links += entry["links"]
            continue
        if current:
            chunks.append((current, current_links))
        # A single block over the limit is hard-split as a last resort; its
        # links ride the final piece so they're only marked once fully sent.
        while len(block) > limit:
            chunks.append((block[:limit], []))
            block = block[limit:]
        current = block
        current_links = list(entry["links"])
    if current:
        chunks.append((current, current_links))
    return chunks

async def _send(send, entries):
    """Send the rendered entries in Telegram-sized chunks, marking each chunk's
    items seen as soon as it's delivered. On a mid-batch failure the already-sent
    items stay marked (no re-post) while the undelivered ones re-surface next run."""
    chunks = _chunks(entries)
    sent_items = 0
    for text, links in chunks:
        await send(text, parse_mode="HTML", disable_web_page_preview=True)
        if links:
            await asyncio.to_thread(mark_seen, links)
            sent_items += len(links)
    logger.info("Delivered %d item(s) in %d message chunk(s)", sent_items, len(chunks))

FETCH_FAILED_MESSAGE = "⚠️ Failed to fetch the news. Please try again later."


def _authorized_chat(update):
    chat = update.effective_chat
    return chat is not None and str(chat.id) == os.environ.get("CHAT_ID", "").strip()


def _status_text():
    try:
        config = load_config()
        sources = config["sources"]
        if not isinstance(sources, list):
            raise TypeError("sources must be a list")
        feed_status = str(len(sources))
    except (OSError, TypeError, ValueError, KeyError):
        feed_status = "Configuration error"

    daily_enabled = daily_news_enabled()
    web_enabled = web_search_enabled()
    schedule = "08:00 America/New_York" if daily_enabled else "disabled"
    return "\n".join([
        "News bot status",
        f"Daily news: {'enabled' if daily_enabled else 'disabled'}",
        f"Web search: {'enabled' if web_enabled else 'disabled (RSS only)'}",
        f"RSS feeds: {feed_status}",
        f"Schedule: {schedule}",
    ])


async def _fetch_and_summarize(include_themes=False):
    """Run collect_new_items()/summarize() in a worker thread (blocking network +
    multi-second API calls; offloaded so the event loop stays responsive —
    otherwise PTB's own networking times out, bad on a slow Pi). Returns
    (items, entries), or (None, None) if either step raised. `entries` is the
    rendered {text, links} list that _send delivers (and marks seen) per chunk."""
    try:
        items = await asyncio.to_thread(collect_new_items, include_themes=include_themes)
        entries = await asyncio.to_thread(summarize, items)
        return items, entries
    except Exception:
        logger.exception("Failed to fetch/summarize news")
        return None, None


async def _run_news(send, *, include_themes=False, started_text=None):
    """Run one complete news collection, rendering, and delivery cycle.

    The lock is acquired before any collection starts and released only after
    delivery (including post-send deduplication) finishes. The lock check and
    acquire have no intervening await, so competing tasks on this event loop
    cannot both enter the workflow.
    """
    if _news_run_lock.locked():
        return False

    await _news_run_lock.acquire()
    try:
        if started_text:
            await send(started_text)
        items, entries = await _fetch_and_summarize(include_themes=include_themes)
        if items is None:
            await send(FETCH_FAILED_MESSAGE)
            return False
        await _send(send, entries)
        return True
    finally:
        _news_run_lock.release()

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized_chat(update):
        logger.warning("Rejected /news from unauthorized chat")
        return

    if _news_run_lock.locked():
        await update.message.reply_text(NEWS_BUSY_MESSAGE)
        return
    await _run_news(
        update.message.reply_text,
        include_themes=True,
        started_text="Fetching news...",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized_chat(update):
        logger.warning("Rejected /status from unauthorized chat")
        return
    await update.message.reply_text(_status_text())


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = os.environ["CHAT_ID"]

    async def send(text, **kw):
        return await context.bot.send_message(chat_id=chat_id, text=text, **kw)

    if _news_run_lock.locked():
        logger.info("Skipping scheduled news run because another run is in progress")
        return
    await _run_news(send)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Log transient errors (e.g. telegram.error.TimedOut on a flaky link)
    # instead of dumping an unhandled traceback.
    logger.error("Handler error: %s", context.error, exc_info=context.error)

def main():
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
    )
    # httpx (used by python-telegram-bot) logs full request URLs at INFO,
    # including the bot token embedded in the Telegram API path.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    app = (
        ApplicationBuilder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        # Generous HTTP timeouts for a slow/weak-WiFi Pi (defaults are ~5s).
        .connect_timeout(20)
        .read_timeout(20)
        .write_timeout(30)
        .pool_timeout(20)
        .build()
    )
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_error_handler(on_error)

    # Run daily at 08:00 US/Eastern (unless disabled via DAILY_NEWS). The time
    # must carry tzinfo: PTB's JobQueue scheduler defaults to UTC, so a naive
    # time(hour=8) would fire at 08:00 UTC regardless of the host's timezone.
    if daily_news_enabled():
        # daily_job reads CHAT_ID lazily; fail fast at startup if it's missing.
        if "CHAT_ID" not in os.environ:
            raise KeyError("CHAT_ID")
        app.job_queue.run_daily(daily_job, time=time(hour=8, minute=0, tzinfo=ZoneInfo("America/New_York")))
    else:
        logger.info("Daily news disabled via DAILY_NEWS; only /news is active.")

    app.run_polling()

if __name__ == "__main__":
    main()
