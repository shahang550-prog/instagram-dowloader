
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

TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام خوش اومدی! 👋\n\n"
        "لینک ریلز یا پست عمومی اینستاگرام رو بفرست "
        "تا ویدیوش رو برات دانلود کنم 🎬"
    )


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not re.match(
        r"^https?://(www\.)?instagram\.com/(reel|reels|p)/",
        url
    ):
        await update.message.reply_text(
            "❌ لطفاً لینک معتبر اینستاگرام بفرست."
        )
        return

    msg = await update.message.reply_text(
        "⏳ در حال دانلود ویدیو..."
    )

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

            video = files[0]

            with open(video, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption="✅ ویدیوی شما آماده است!"
                )

        await msg.delete()

    except Exception as e:
        print("Download error:", e)
        await msg.edit_text(
            "❌ دانلود انجام نشد!\n"
            "ممکن است پست خصوصی باشد یا لینک مشکل داشته باشد."
        )


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing!")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            download_video
        )
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
