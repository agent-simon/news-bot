# bot.py
import os
from datetime import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
from news import collect_new_items, summarize
from dedup import mark_seen

load_dotenv()
CHAT_ID = os.environ["CHAT_ID"]

# Telegram rejects messages longer than 4096 chars; stay safely under it.
TELEGRAM_LIMIT = 4000

def _chunks(text, limit=TELEGRAM_LIMIT):
    """Split a summary into Telegram-sized pieces on entry (blank-line)
    boundaries so HTML tags are never cut mid-tag."""
    chunks = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # A single block over the limit is hard-split as a last resort.
        while len(block) > limit:
            chunks.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        chunks.append(current)
    return chunks

async def _send(send, summary):
    for chunk in _chunks(summary):
        await send(chunk, parse_mode="HTML", disable_web_page_preview=True)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching news...")
    items = collect_new_items(include_themes=True)
    summary = summarize(items)
    await _send(update.message.reply_text, summary)
    mark_seen([i["link"] for i in items])

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    items = collect_new_items()
    summary = summarize(items)
    await _send(lambda text, **kw: context.bot.send_message(chat_id=CHAT_ID, text=text, **kw), summary)
    mark_seen([i["link"] for i in items])

def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("news", news_command))

    # Run daily at 08:00 server time
    app.job_queue.run_daily(daily_job, time=time(hour=8, minute=0))

    app.run_polling()

if __name__ == "__main__":
    main()
