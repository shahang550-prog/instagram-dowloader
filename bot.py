
import os
import re
import asyncio
import tempfile
import shutil
import psycopg2

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import yt_dlp


# ========== CONFIG ==========

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATABASE_URL = os.environ["DATABASE_URL"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")


# ========== DATABASE ==========

def db(sql, params=(), fetch=None):
    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10
    )

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)

            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                result = None

        conn.commit()
        return result

    finally:
        conn.close()


def init_db():

    db("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        joined_at TIMESTAMPTZ DEFAULT NOW(),
        last_seen TIMESTAMPTZ DEFAULT NOW(),
        is_banned BOOLEAN DEFAULT FALSE
    )
    """)

    db("""
    CREATE TABLE IF NOT EXISTS counters (
        id INTEGER PRIMARY KEY,
        downloads BIGINT DEFAULT 0,
        failed BIGINT DEFAULT 0
    )
    """)

    db("""
    INSERT INTO counters (id, downloads, failed)
    VALUES (1, 0, 0)
    ON CONFLICT (id) DO NOTHING
    """)

    db("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)


def get_setting(key, default=""):
    result = db(
        "SELECT value FROM settings WHERE key=%s",
        (key,),
        "one"
    )
    return result[0] if result else default


def set_setting(key, value):
    db("""
    INSERT INTO settings (key, value)
    VALUES (%s, %s)
    ON CONFLICT (key)
    DO UPDATE SET value=EXCLUDED.value
    """, (key, str(value)))


def register_user(user):

    db("""
    INSERT INTO users (user_id, username, first_name)
    VALUES (%s, %s, %s)

    ON CONFLICT (user_id)
    DO UPDATE SET
        username=EXCLUDED.username,
        first_name=EXCLUDED.first_name,
        last_seen=NOW()
    """, (user.id, user.username, user.first_name))

    result = db(
        "SELECT is_banned FROM users WHERE user_id=%s",
        (user.id,),
        "one"
    )

    return result[0]


def get_stats():

    users = db("""
    SELECT
        COUNT(*),
        COUNT(*) FILTER (
            WHERE joined_at::date=CURRENT_DATE
        ),
        COUNT(*) FILTER (
            WHERE last_seen::date=CURRENT_DATE
        )
    FROM users
    """, fetch="one")

    counts = db("""
    SELECT downloads, failed
    FROM counters WHERE id=1
    """, fetch="one")

    return users, counts


def count_download(success=True):

    column = "downloads" if success else "failed"

    db(f"""
    UPDATE counters
    SET {column}={column}+1
    WHERE id=1
    """)


# ========== ADMIN PANEL ==========

def admin_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 آمار کاربران",
                callback_data="stats"
            ),
            InlineKeyboardButton(
                "💾 وضعیت هاست",
                callback_data="hosting"
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 آمار دانلود",
                callback_data="downloads"
            ),
            InlineKeyboardButton(
                "📢 پیام همگانی",
                callback_data="broadcast"
            )
        ],
        [
            InlineKeyboardButton(
                "🔒 تنظیم عضویت اجباری",
                callback_data="membership"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 تغییر شناسه کانال",
                callback_data="set_channel"
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 تغییر لینک عضویت",
                callback_data="set_link"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 بازگشت",
                callback_data="home"
            )
        ]
    ])


def membership_keyboard():

    enabled = get_setting("force_join", "0") == "1"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ فعال کردن" if not enabled else "🟢 فعال است",
                callback_data="join_on"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ خاموش کردن" if enabled else "🔴 غیرفعال است",
                callback_data="join_off"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="home"
            )
        ]
    ])


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.pop("admin_action", None)

    await update.message.reply_text(
        "👑 به پنل مدیریت خوش آمدی",
        reply_markup=admin_keyboard()
    )


async def admin_buttons(update, context):

    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    action = query.data

    context.user_data.pop("admin_action", None)

    if action == "home":

        await query.message.reply_text(
            "👑 پنل مدیریت",
            reply_markup=admin_keyboard()
        )

    elif action == "stats":

        users, counts = await asyncio.to_thread(get_stats)

        await query.message.reply_text(
            f"📊 آمار کاربران\n\n"
            f"👥 کل کاربران: {users[0]}\n"
            f"🆕 کاربران امروز: {users[1]}\n"
            f"🟢 فعالان امروز: {users[2]}"
        )

    elif action == "downloads":

        users, counts = await asyncio.to_thread(get_stats)

        await query.message.reply_text(
            f"🎬 آمار دانلود\n\n"
            f"✅ موفق: {counts[0]}\n"
            f"❌ ناموفق: {counts[1]}"
        )

    elif action == "hosting":

        usage = shutil.disk_usage(tempfile.gettempdir())

        total = usage.total / (1024 ** 3)
        used = usage.used / (1024 ** 3)
        free = usage.free / (1024 ** 3)

        await query.message.reply_text(
            "💾 وضعیت فایل‌سیستم هاست\n\n"
            f"📦 کل فضای فایل‌سیستم: {total:.2f} GB\n"
            f"📂 استفاده شده: {used:.2f} GB\n"
            f"🟢 فضای آزاد: {free:.2f} GB\n\n"
            "⚠️ این عدد فضای آزاد فایل‌سیستم "
            "قابل مشاهده از برنامه است، نه سهمیه "
            "باقی‌مانده پلن Render."
        )

    elif action == "membership":

        enabled = get_setting("force_join", "0") == "1"
        channel = get_setting("channel_id", "تنظیم نشده")

        await query.message.reply_text(
            f"🔒 تنظیم عضویت اجباری\n\n"
            f"وضعیت: {'فعال ✅' if enabled else 'خاموش ❌'}\n"
            f"شناسه کانال: {channel}",
            reply_markup=membership_keyboard()
        )

    elif action == "join_on":

        channel = get_setting("channel_id")

        if not channel:
            await query.message.reply_text(
                "اول شناسه کانال را تنظیم کن."
            )
            return

        set_setting("force_join", "1")

        await query.message.reply_text(
            "✅ عضویت اجباری فعال شد."
        )

    elif action == "join_off":

        set_setting("force_join", "0")

        await query.message.reply_text(
            "🔴 عضویت اجباری خاموش شد."
        )

    elif action == "set_channel":

        context.user_data["admin_action"] = "set_channel"

        await query.message.reply_text(
            "شناسه کانال را بفرست.\n\n"
            "مثال:\n"
            "@MyChannel\n"
            "یا\n"
            "-1001234567890"
        )

    elif action == "set_link":

        context.user_data["admin_action"] = "set_link"

        await query.message.reply_text(
            "لینک عضویت کانال را بفرست.\n"
            "مثال: https://t.me/MyChannel\n\n"
            "برای حذف لینک قبلی بنویس: none"
        )

    elif action == "broadcast":

        context.user_data["admin_action"] = "broadcast"

        await query.message.reply_text(
            "متن پیام همگانی را بفرست."
        )


# ========== MEMBERSHIP ==========

async def is_member(user_id, context):

    if get_setting("force_join", "0") != "1":
        return True

    channel = get_setting("channel_id")

    if not channel:
        return False

    try:

        member = await context.bot.get_chat_member(
            chat_id=channel,
            user_id=user_id
        )

        return (
            member.status in ("creator", "administrator", "member")
            or (
                member.status == "restricted"
                and member.is_member
            )
        )

    except Exception as e:

        print("Membership error:", e)
        return False


async def membership_message(update, context):

    link = get_setting("join_link")

    buttons = []

    if link:
        buttons.append([
            InlineKeyboardButton(
                "📢 عضویت در کانال",
                url=link
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ بررسی عضویت",
            callback_data="check_membership"
        )
    ])

    await update.message.reply_text(
        "🔒 برای استفاده از ربات ابتدا عضو کانال شو.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def check_membership_button(update, context):

    query = update.callback_query
    await query.answer()

    if await is_member(query.from_user.id, context):

        await query.message.reply_text(
            "✅ عضویت شما تأیید شد!\n"
            "حالا لینک ویدیو را ارسال کن."
        )

    else:

        await query.message.reply_text(
            "❌ هنوز عضویت شما تأیید نشده است."
        )


# ========== ADMIN TEXT ACTIONS ==========

async def handle_admin_text(update, context):

    action = context.user_data.get("admin_action")

    if not action:
        return False

    if update.effective_user.id != ADMIN_ID:
        return False

    text = update.message.text.strip()

    context.user_data.pop("admin_action", None)

    if action == "set_channel":

        if not re.match(r"^@[A-Za-z0-9_]{5,32}$|^-100\d+$", text):
            await update.message.reply_text(
                "شناسه کانال معتبر نیست."
            )
            return True

        set_setting("channel_id", text)

        await update.message.reply_text(
            "✅ شناسه کانال ذخیره شد.\n"
            "حالا مطمئن شو ربات در کانال ادمین است."
        )

    elif action == "set_link":

        if text.lower() == "none":
            set_setting("join_link", "")
        elif text.startswith("https://t.me/"):
            set_setting("join_link", text)
        else:
            await update.message.reply_text(
                "لینک باید با https://t.me/ شروع شود."
            )
            return True

        await update.message.reply_text(
            "✅ لینک عضویت ذخیره شد."
        )

    elif action == "broadcast":

        ids = await asyncio.to_thread(
            lambda: db(
                "SELECT user_id FROM users WHERE is_banned=FALSE",
                fetch="all"
            )
        )

        sent = 0

        await update.message.reply_text(
            f"⏳ ارسال به {len(ids)} کاربر شروع شد."
        )

        for row in ids:

            try:

                await context.bot.send_message(
                    chat_id=row[0],
                    text=text
                )

                sent += 1
                await asyncio.sleep(0.05)

            except Exception as e:
                print("Broadcast error:", e)

        await update.message.reply_text(
            f"✅ ارسال تمام شد.\n"
            f"ارسال موفق: {sent}"
        )

    return True


# ========== USER START ==========

async def start(update, context):

    banned = await asyncio.to_thread(
        register_user,
        update.effective_user
    )

    if banned:

        await update.message.reply_text(
            "شما اجازه استفاده از ربات را ندارید."
        )
        return

    if not await is_member(update.effective_user.id, context):

        await membership_message(update, context)
        return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "لینک عمومی ریلز یا پست اینستاگرام را بفرست 🎬"
    )


# ========== DOWNLOAD ==========

async def download_video(update, context):

    user = update.effective_user

    banned = await asyncio.to_thread(register_user, user)

    if banned:
        await update.message.reply_text(
            "دسترسی شما مسدود شده است."
        )
        return

    if not await is_member(user.id, context):

        await membership_message(update, context)
        return

    url = update.message.text.strip()

    if not re.match(
        r"^https?://(www\.)?instagram\.com/(reel|reels|p)/",
        url
    ):

        await update.message.reply_text(
            "❌ لینک معتبر اینستاگرام بفرست."
        )
        return

    msg = await update.message.reply_text(
        "⏳ در حال دانلود..."
    )

    try:

        with tempfile.TemporaryDirectory() as folder:

            options = {
                "outtmpl": os.path.join(folder, "video.%(ext)s"),
                "format": "best[ext=mp4]/best",
                "noplaylist": True,
                "max_filesize": 45 * 1024 * 1024,
                "quiet": True
            }

            def download():
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(download)

            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            ]

            if not files:
                raise Exception("Video not found")

            with open(files[0], "rb") as video:

                await update.message.reply_video(
                    video=video,
                    caption="✅ ویدیوی شما آماده است!"
                )

        await asyncio.to_thread(count_download, True)
        await msg.delete()

    except Exception as e:

        print("Download error:", e)

        await asyncio.to_thread(count_download, False)

        await msg.edit_text(
            "❌ دانلود ناموفق بود."
        )


# ========== TEXT ROUTER ==========

async def handle_text(update, context):

    if update.effective_user.id == ADMIN_ID:

        handled = await handle_admin_text(update, context)

        if handled:
            return

    await download_video(update, context)


# ========== MAIN ==========

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(
        CallbackQueryHandler(
            check_membership_button,
            pattern="^check_membership$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(admin_buttons)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path="telegram",
        webhook_url=f"{BASE_URL}/telegram",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
