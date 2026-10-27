# -*- coding: utf-8 -*-
"""ربات مستقل سلف روباهیو — polling، بدون وابستگی به ربات اصلی.

متغیرهای Railway:
  BOT_TOKEN      توکن ربات جدید (از @BotFather)
  ADMIN_IDS      آیدی عددی مدیرها، با کاما (مثلاً 123,456)
  SUPPORT_IDS    (اختیاری) آیدی عددی پشتیبان‌ها با کاما؛ فقط به /support دسترسی دارن
  SELF_API_ID    از my.telegram.org
  SELF_API_HASH  از my.telegram.org
  SELF_KEY       یه رشته‌ی تصادفی بلند برای رمزنگاری سشن‌ها (بعداً عوضش نکن!)
  DATABASE_URL   (اختیاری) Postgres جدا؛ بدون اون SQLite محلی که با دیپلوی پاک می‌شه
"""
import logging
import os

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import selfbot
import commerce
from database import init_db

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("selfapp")

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
# امنیت: فقط مالک تعیین‌شده اجازه‌ی عملیات مدیریتی دارد.
# مقدار ADMIN_IDS در Railway عمداً برای دسترسی مدیریتی نادیده گرفته می‌شود تا
# افزودن تصادفی شناسه‌های دیگر، اختیار مدیریت را گسترش ندهد.
OWNER_ID = 7433300089
ADMIN_IDS = {OWNER_ID}


def _home_kb(uid):
    rows = []
    if uid in ADMIN_IDS:
        rows.append([B("مدیریت سلف", callback_data="selfa:menu", api_kwargs={"style": "primary"})])
    return KB(rows) if rows else None


async def cmd_admin(update, context):
    u = update.effective_user
    if u.id not in ADMIN_IDS:
        return
    await update.effective_message.reply_text("🤖 مدیریت سلف", reply_markup=selfbot.admin_menu_kb())


async def cb_back(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.pop("admin_action", None)
    await q.message.reply_text("🏠 منوی اصلی", reply_markup=_home_kb(q.from_user.id))


async def post_init(app):
    await selfbot.start_all(app)


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده")
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS خالیه؛ هیچ‌کس نمی‌تونه کاربر فعال کنه")
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(cb_back, pattern=r"^admin:back$"))
    selfbot.register(app, ADMIN_IDS)
    for x in os.environ.get("SUPPORT_IDS", "").replace("،", ",").split(","):
        x = x.strip()
        if x.isdigit() and int(x) not in ADMIN_IDS:
            selfbot.SUPPORT_IDS.add(int(x))
    commerce.setup(app)
    logger.info("selfbot standalone started")
    app.run_polling(allowed_updates=["message", "callback_query", "inline_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
