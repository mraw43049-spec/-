"""
ruby_emojis.py — فایل موقت (stub)

این فایل فقط برای این است که ربات دوباره بالا بیاید.
اگر نسخه‌ی اصلی ruby_emojis.py را داری (از زیپ‌های قبلی یا تاریخچه‌ی گیت‌هاب)،
همان را جایگزین این فایل کن.
"""

# ساختار اصلی: {کلید_دسته: (عنوان, قیمت/توضیح, [لیست شکلک‌ها])}
CATEGORIES = {}

_MSG = "🛍 فروشگاه شکلک روبی موقتاً در دسترس نیست. بزودی برمی‌گردد 💎"


async def emoji_command(update, context):
    if update.message:
        await update.message.reply_text(_MSG)


async def emoji_callback(update, context):
    q = update.callback_query
    if q:
        await q.answer(_MSG, show_alert=True)


async def emoji_action(update, context):
    q = update.callback_query
    if q:
        await q.answer(_MSG, show_alert=True)


async def emoji_transfer_text(update, context):
    # False یعنی این پیام مربوط به انتقال شکلک نیست و به بقیه‌ی هندلرها برسد
    return False
