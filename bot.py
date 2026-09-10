import logging
import random
import re
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters
)

from config import (
    ADMIN_IDS, BOT_TOKEN, CLAIM_COOLDOWN_SECONDS, CLAIM_KEYWORD,
    CLAIM_POINTS_MAX, CLAIM_POINTS_MIN, REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL
)
from database import Challenge, User, get_session, init_db
from game_logic import (
    GAME_EMOJIS, GAME_NAMES_FA, get_level_for_points,
    get_newly_unlocked_game, get_unlocked_games, points_to_next_level,
    points_needed_for_level
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- عضویت اجباری ----------

async def is_member(bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return m.status in ("member", "administrator", "creator") or bool(getattr(m, "is_member", False))
    except Exception as e:
        logger.warning("Membership check failed: %s", e)
        return False

def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_membership")]
    ])

async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    # Admins always retain access to the management panel, even if they are not
    # subscribed to the required channel themselves.
    if user.id in ADMIN_IDS:
        return True
    if await is_member(context.bot, user.id):
        return True

    text = (
        "🔒 برای استفاده از ربات اول باید عضو کانال بشی.\n\n"
        "بعد از عضویت روی «عضو شدم، بررسی کن» بزن."
    )
    if update.callback_query:
        await update.callback_query.answer("اول باید عضو کانال بشی.", show_alert=True)
        try:
            await update.callback_query.message.edit_text(text, reply_markup=join_keyboard())
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(text, reply_markup=join_keyboard())
    return False

# ---------- کاربران ----------

def get_or_create_user(session, tg_user):
    user = session.get(User, tg_user.id)
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            points=0,
            total_earned=0,
            level=1,
        )
        session.add(user)
        session.commit()
    else:
        changed = False
        if user.username != tg_user.username:
            user.username = tg_user.username; changed = True
        if user.first_name != tg_user.first_name:
            user.first_name = tg_user.first_name; changed = True
        if changed:
            session.commit()
    return user

def format_cooldown(seconds_left):
    m, s = divmod(int(seconds_left), 60)
    return f"{m} دقیقه و {s} ثانیه" if m else f"{s} ثانیه"

def add_points(session, user, amount):
    user.points = max(0, user.points + amount)
    if amount > 0:
        user.total_earned += amount
    old = user.level
    user.level = get_level_for_points(user.points)
    return old, user.level

# ---------- start/profile/games ----------

async def start_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        get_or_create_user(session, update.effective_user)
    finally:
        session.close()
    await update.message.reply_text(
        f"🔥 خوش اومدی!\n\n"
        f"هر {CLAIM_COOLDOWN_SECONDS // 60} دقیقه یک‌بار «{CLAIM_KEYWORD}» رو بفرست و هور پوینت بگیر.\n"
        "با بالا رفتن سطح، بازی‌های جدید باز می‌شن.\n\n"
        "📌 /profile — آمار کامل\n"
        "🎮 /games — بازی‌ها\n"
        "🏆 /challenge — دعوت به بازی\n"
        "🛠 /admin — پنل مدیریت (فقط ادمین)"
    )

async def profile_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        next_level, remaining = points_to_next_level(user.points)
        next_text = f"{remaining} هور پوینت تا لول {next_level}" if next_level else "🏆 بالاترین لول فعلی"
        unlocked = get_unlocked_games(user.level)
        games = "، ".join(GAME_NAMES_FA[g] for g in unlocked) if unlocked else "هنوز بازی‌ای باز نشده"
        await update.message.reply_text(
            f"👤 آمار {user.first_name or 'کاربر'}\n\n"
            f"💰 هور پوینت فعلی: {user.points}\n"
            f"📈 هور پوینت کسب‌شده: {user.total_earned}\n"
            f"⭐ سطح: {user.level}\n"
            f"⏳ {next_text}\n"
            f"🎮 بازی‌های باز: {games}"
        )
    finally:
        session.close()

async def games_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        unlocked = get_unlocked_games(user.level)
    finally:
        session.close()
    await update.message.reply_text(
        "🎮 منوی بازی\n\n" +
        "\n".join(f"• {GAME_NAMES_FA[g]} {GAME_EMOJIS[g]}" for g in unlocked) +
        "\n\n👥 بازی دونفره در گروه:\n"
        "1️⃣ روی پیام حریفت ریپلای کن\n"
        "2️⃣ بنویس: /challenge dice\n"
        "3️⃣ حریفت روی «قبول می‌کنم» بزند\n"
        "4️⃣ هر نفر فقط دکمه خودش را بزند تا نتیجه در گروه اعلام شود."
    )

async def game_command(update, context):
    await games_command(update, context)

# ---------- هور پوینت ----------

async def claim_points(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        now = datetime.now(timezone.utc)
        if user.last_claim_at is not None:
            elapsed = (now - user.last_claim_at).total_seconds()
            if elapsed < CLAIM_COOLDOWN_SECONDS:
                await update.message.reply_text(
                    f"⏳ هنوز زوده! {format_cooldown(CLAIM_COOLDOWN_SECONDS - elapsed)} دیگه."
                )
                return
        earned = random.randint(CLAIM_POINTS_MIN, CLAIM_POINTS_MAX)
        old_level = user.level
        user.points += earned
        user.total_earned += earned
        user.last_claim_at = now
        user.level = get_level_for_points(user.points)
        session.commit()
        text = f"⚡ +{earned} هور پوینت!\n💰 موجودی: {user.points}\n📈 کل کسب‌شده: {user.total_earned}"
        if user.level > old_level:
            text += f"\n\n🎉 لول {user.level} شدی!"
        await update.message.reply_text(text)
    finally:
        session.close()

# ---------- بازی بدون شرط‌بندی ----------

async def challenge_command(update, context):
    if not await require_membership(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام حریف ریپلای کن و بعد /challenge dice بفرست.")
        return
    if not context.args:
        await update.message.reply_text("نوع بازی: dice / darts / bowling / football")
        return
    game_type = context.args[0].lower()
    if game_type not in GAME_EMOJIS:
        await update.message.reply_text("بازی معتبر نیست.")
        return
    challenger = update.effective_user
    opponent = update.message.reply_to_message.from_user
    if opponent.id == challenger.id or opponent.is_bot:
        await update.message.reply_text("این کاربر نمی‌تونه حریف بازی باشه.")
        return

    session = get_session()
    try:
        cuser = get_or_create_user(session, challenger)
        if game_type not in get_unlocked_games(cuser.level):
            await update.message.reply_text("این بازی هنوز برای لولت باز نشده.")
            return
        get_or_create_user(session, opponent)
        challenge = Challenge(
            chat_id=update.effective_chat.id, game_type=game_type,
            player1_id=challenger.id, player2_id=opponent.id, status="pending"
        )
        session.add(challenge); session.commit()
        cid = challenge.id
    finally:
        session.close()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ قبول می‌کنم", callback_data=f"accept:{cid}")]])
    await update.message.reply_text(
        f"🎮 {challenger.first_name} تو را به {GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]} دعوت کرد.\n"
        "این بازی بدون شرط هور پوینت است؛ نتیجه فقط برای امتیاز و سرگرمی ثبت می‌شود.",
        reply_markup=kb
    )

async def accept_challenge(update, context):
    if not await require_membership(update, context):
        return
    q = update.callback_query
    cid = int(q.data.split(":")[1])
    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if ch is None or ch.status != "pending":
            await q.answer("این دعوت منقضی شده.", show_alert=True); return
        if q.from_user.id != ch.player2_id:
            await q.answer("این دعوت برای تو نیست.", show_alert=True); return
        ch.status = "active"; session.commit()
        game_type = ch.game_type
    finally:
        session.close()
    await q.answer("بازی شروع شد!")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎮 بازیکن ۱", callback_data=f"throw:{cid}:1"),
        InlineKeyboardButton("🎮 بازیکن ۲", callback_data=f"throw:{cid}:2")
    ]])
    await q.edit_message_text(
        f"{GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]} شروع شد!\n"
        "هر بازیکن فقط دکمه خودش را بزند.", reply_markup=kb
    )

async def throw_dice(update, context):
    if not await require_membership(update, context):
        return
    q = update.callback_query
    _, cid_s, slot_s = q.data.split(":")
    cid, slot = int(cid_s), int(slot_s)

    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if ch is None or ch.status != "active":
            await q.answer("بازی فعال نیست.", show_alert=True); return
        expected = ch.player1_id if slot == 1 else ch.player2_id
        if q.from_user.id != expected:
            await q.answer("این دکمه برای تو نیست.", show_alert=True); return
        old = ch.player1_score if slot == 1 else ch.player2_score
        if old is not None:
            await q.answer("قبلاً بازی کردی.", show_alert=True); return
        game_type, chat_id = ch.game_type, ch.chat_id
    finally:
        session.close()

    await q.answer()
    msg = await context.bot.send_dice(chat_id=chat_id, emoji=GAME_EMOJIS[game_type])
    value = msg.dice.value

    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if slot == 1: ch.player1_score = value
        else: ch.player2_score = value
        p1, p2 = ch.player1_score, ch.player2_score
        finished = p1 is not None and p2 is not None
        if finished: ch.status = "finished"
        session.commit()
        p1_id, p2_id = ch.player1_id, ch.player2_id
    finally:
        session.close()

    if not finished:
        await context.bot.send_message(chat_id=chat_id, text="✅ نتیجه ثبت شد؛ منتظر بازیکن بعدی...")
        return

    if p1 > p2: winner, loser, text = p1_id, p2_id, f"🏆 بازیکن ۱ برنده شد! {p1} - {p2}"
    elif p2 > p1: winner, loser, text = p2_id, p1_id, f"🏆 بازیکن ۲ برنده شد! {p2} - {p1}"
    else: winner = loser = None; text = f"🤝 مساوی! {p1} - {p2}"

    # پاداش ثابت بازی؛ هیچ شرط‌بندی یا انتقال هور پوینت بین کاربران وجود ندارد.
    session = get_session()
    try:
        if winner:
            wu = session.get(User, winner)
            lu = session.get(User, loser)
            add_points(session, wu, 10)
            add_points(session, lu, 3)
            session.commit()
            text += "\n\n🎁 پاداش بازی: برنده +10 هور پوینت | بازنده +3 هور پوینت"
        else:
            u1 = session.get(User, p1_id); u2 = session.get(User, p2_id)
            add_points(session, u1, 5); add_points(session, u2, 5)
            session.commit()
            text += "\n\n🎁 پاداش مساوی: هر نفر +5 هور پوینت"
    finally:
        session.close()
    await context.bot.send_message(chat_id=chat_id, text=text)

# ---------- پنل ادمین ----------

def admin_only(user_id):
    return user_id in ADMIN_IDS

async def admin_command(update, context):
    if not await require_membership(update, context):
        return
    if not admin_only(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی نداری.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats")],
        [InlineKeyboardButton("👥 تعداد کاربران", callback_data="admin:users")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")],
        [InlineKeyboardButton("➕ دادن هور پوینت", callback_data="admin:addpoints")],
        [InlineKeyboardButton("⭐ تنظیم سطح", callback_data="admin:setlevel")],
    ])
    await update.message.reply_text(
        "🛠 پنل مدیریت\n\n"
        "برای عملیات متنی، بعد از زدن گزینه مربوطه مقدار/پیام را بفرست.",
        reply_markup=kb
    )

async def admin_callback(update, context):
    q = update.callback_query
    if not admin_only(q.from_user.id):
        await q.answer("دسترسی نداری.", show_alert=True); return
    action = q.data.split(":")[1]
    await q.answer()
    if action == "stats":
        session = get_session()
        try:
            users = session.query(User).count()
            points = sum((u.points or 0) for u in session.query(User).all())
            earned = sum((u.total_earned or 0) for u in session.query(User).all())
            games = session.query(Challenge).count()
        finally:
            session.close()
        await q.message.reply_text(
            f"📊 آمار کلی\n\n👥 کاربران: {users}\n💰 هور پوینت موجود کاربران: {points}\n"
            f"📈 مجموع هور پوینت کسب‌شده: {earned}\n🎮 بازی‌های ثبت‌شده: {games}"
        )
    elif action == "users":
        session = get_session()
        try: count = session.query(User).count()
        finally: session.close()
        await q.message.reply_text(f"👥 تعداد کاربران ثبت‌شده: {count}")
    elif action == "broadcast":
        context.user_data["admin_action"] = "broadcast"
        await q.message.reply_text("📣 متن پیام همگانی را همینجا بفرست.")
    elif action == "addpoints":
        context.user_data["admin_action"] = "addpoints"
        await q.message.reply_text("➕ فرمت: آیدی عددی کاربر + مقدار\nمثال: 123456789 50")
    elif action == "setlevel":
        context.user_data["admin_action"] = "setlevel"
        await q.message.reply_text("⭐ فرمت: آیدی عددی کاربر + سطح\nمثال: 123456789 4")

async def admin_text(update, context):
    if not admin_only(update.effective_user.id):
        return
    action = context.user_data.get("admin_action")
    if not action:
        return
    context.user_data.pop("admin_action", None)
    text = update.message.text.strip()

    if action == "broadcast":
        session = get_session()
        try: users = [u.telegram_id for u in session.query(User).all()]
        finally: session.close()
        ok = fail = 0
        for uid in users:
            try:
                await context.bot.send_message(uid, "📢 پیام مدیریت:\n\n" + text)
                ok += 1
            except Exception:
                fail += 1
        await update.message.reply_text(f"✅ ارسال شد: {ok}\n❌ ناموفق: {fail}")
        return

    parts = text.split()
    if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
        await update.message.reply_text("فرمت اشتباه است.")
        return
    uid, value = int(parts[0]), int(parts[1])
    session = get_session()
    try:
        user = session.get(User, uid)
        if not user:
            await update.message.reply_text("کاربر پیدا نشد.")
            return
        if action == "addpoints":
            old = user.level
            user.points = max(0, user.points + value)
            if value > 0: user.total_earned += value
            user.level = get_level_for_points(user.points)
            session.commit()
            await update.message.reply_text(
                f"✅ انجام شد.\nپوینت: {user.points}\nسطح: {user.level}\nکل کسب‌شده: {user.total_earned}"
            )
        elif action == "setlevel":
            if value < 1 or value > 5:
                await update.message.reply_text("سطح باید بین 1 تا 5 باشد.")
                return
            min_points = points_needed_for_level(value)
            user.level = value
            # برای هماهنگی سطح با پوینت، حداقل پوینت لازم را اعمال می‌کنیم.
            user.points = max(user.points, min_points or 0)
            session.commit()
            await update.message.reply_text(f"✅ سطح کاربر شد {user.level} (پوینت: {user.points})")
    finally:
        session.close()

async def membership_callback(update, context):
    q = update.callback_query
    if q.data != "check_membership":
        return
    if await is_member(context.bot, q.from_user.id):
        await q.answer("عضویت تأیید شد! 🎉")
        await q.message.edit_text(
            f"✅ تأیید شد!\n\nحالا «{CLAIM_KEYWORD}» رو بفرست تا هور پوینت جمع کنی."
        )
    else:
        await q.answer("هنوز عضویتت تأیید نشده.", show_alert=True)

def main():
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN is missing. Add BOT_TOKEN in Railway Variables.')
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("game", game_command))
    app.add_handler(CommandHandler("challenge", challenge_command))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(CallbackQueryHandler(membership_callback, pattern=r"^check_membership$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:(stats|users|broadcast|addpoints|setlevel)$"))
    app.add_handler(CallbackQueryHandler(accept_challenge, pattern=r"^accept:\d+$"))
    app.add_handler(CallbackQueryHandler(throw_dice, pattern=r"^throw:\d+:[12]$"))

    # پیام‌های مدیریتی باید قبل از claim پردازش شوند.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=list(ADMIN_IDS)), admin_text), group=0)
    app.add_handler(MessageHandler(
        filters.Regex(rf"^{re.escape(CLAIM_KEYWORD)}$") & filters.TEXT & ~filters.COMMAND,
        claim_points
    ), group=1)

    logger.info("Bot started polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
