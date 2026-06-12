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

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching news...")
    items = collect_new_items()
    summary = summarize(items)
    await update.message.reply_text(summary, parse_mode="HTML", disable_web_page_preview=True)
    mark_seen([i["link"] for i in items])

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    items = collect_new_items()
    summary = summarize(items)
    await context.bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode="HTML", disable_web_page_preview=True)
    mark_seen([i["link"] for i in items])

def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("news", news_command))

    # Run daily at 08:00 server time
    app.job_queue.run_daily(daily_job, time=time(hour=8, minute=0))

    app.run_polling()

if __name__ == "__main__":
    main()
