
import os
import re
import asyncio
import tempfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import yt_dlp

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n"
        "لینک عمومی ریلز یا پست اینستاگرام رو بفرست 🎬"
    )


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not re.match(
        r"^https?://(www\.)?instagram\.com/(reel|reels|p)/",
        url
    ):
        await update.message.reply_text("لطفاً لینک معتبر اینستاگرام بفرست.")
        return

    msg = await update.message.reply_text("⏳ در حال دانلود...")

    try:
        with tempfile.TemporaryDirectory() as folder:
            options = {
                "outtmpl": os.path.join(folder, "video.%(ext)s"),
                "format": "best[ext=mp4]/best",
                "noplaylist": True,
                "max_filesize": 45 * 1024 * 1024,
                "quiet": True,
            }

            def download():
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(download)

            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
            ]

            if not files:
                raise Exception("Video not found")

            with open(files[0], "rb") as video:
                await update.message.reply_video(
                    video=video,
                    caption="✅ ویدیوی شما آماده است!"
                )

        await msg.delete()

    except Exception as e:
        print("Download error:", e)
        await msg.edit_text(
            "❌ دانلود انجام نشد. ممکن است لینک خصوصی باشد "
            "یا اینستاگرام دسترسی را محدود کرده باشد."
        )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, download_video)
    )

    port = int(os.environ.get("PORT", 10000))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=f"{BASE_URL}/telegram",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
