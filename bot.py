import logging
import random
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    CLAIM_COOLDOWN_SECONDS,
    CLAIM_KEYWORD,
    CLAIM_POINTS_MAX,
    CLAIM_POINTS_MIN,
)
from database import Challenge, User, get_session, init_db
from game_logic import (
    GAME_EMOJIS,
    GAME_NAMES_FA,
    get_level_for_points,
    get_newly_unlocked_game,
    get_unlocked_games,
    points_to_next_level,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------- توابع کمکی ----------

def get_or_create_user(session, tg_user) -> User:
    user = session.get(User, tg_user.id)
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            points=0,
            level=1,
        )
        session.add(user)
        session.commit()
    else:
        # آپدیت یوزرنیم در صورت تغییر
        if user.username != tg_user.username or user.first_name != tg_user.first_name:
            user.username = tg_user.username
            user.first_name = tg_user.first_name
            session.commit()
    return user


def format_cooldown(seconds_left: int) -> str:
    minutes, seconds = divmod(int(seconds_left), 60)
    if minutes:
        return f"{minutes} دقیقه و {seconds} ثانیه"
    return f"{seconds} ثانیه"


# ---------- کامندها ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        get_or_create_user(session, update.effective_user)
    finally:
        session.close()

    await update.message.reply_text(
        "سلام! 👋\n\n"
        f"هر {CLAIM_COOLDOWN_SECONDS // 60} دقیقه یک‌بار کلمه «{CLAIM_KEYWORD}» رو بفرست تا پوینت بگیری.\n"
        "با بالا رفتن سطحت، بازی‌های دونفره جدید (تاس 🎲، دارت 🎯، بولینگ 🎳، فوتبال ⚽) باز میشن.\n\n"
        "دستورات:\n"
        "/profile - دیدن پوینت، سطح و بازی‌های بازشده\n"
        "/games - لیست بازی‌های قابل‌بازی\n"
        "/challenge - دعوت کردن یه نفر دیگه به بازی (باید روی پیامش ریپلای کنی)"
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        unlocked = get_unlocked_games(user.level)
        unlocked_text = (
            "، ".join(GAME_NAMES_FA[g] for g in unlocked) if unlocked else "هنوز هیچی"
        )
        next_level, remaining = points_to_next_level(user.points)
        if next_level:
            next_text = f"{remaining} پوینت دیگه تا سطح {next_level}"
        else:
            next_text = "به بالاترین سطح رسیدی! 🏆"

        await update.message.reply_text(
            f"📊 پروفایل تو:\n"
            f"پوینت: {user.points}\n"
            f"سطح: {user.level}\n"
            f"بازی‌های بازشده: {unlocked_text}\n"
            f"{next_text}"
        )
    finally:
        session.close()


async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        unlocked = get_unlocked_games(user.level)
    finally:
        session.close()

    if not unlocked:
        await update.message.reply_text(
            "هنوز هیچ بازی‌ای باز نکردی. اول با فرستادن کلمه "
            f"«{CLAIM_KEYWORD}» پوینت جمع کن تا سطحت بره بالا."
        )
        return

    games_list = "\n".join(f"- {GAME_NAMES_FA[g]} {GAME_EMOJIS[g]}" for g in unlocked)
    await update.message.reply_text(
        f"بازی‌های باز شده برای تو:\n{games_list}\n\n"
        "برای دعوت یه نفر به بازی، روی یکی از پیام‌هاش ریپلای کن و بنویس:\n"
        "/challenge dice  (یا darts / bowling / football)"
    )


async def claim_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی کاربر کلمه کلیدی رو بفرسته صدا زده میشه."""
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        now = datetime.now(timezone.utc)

        if user.last_claim_at is not None:
            elapsed = (now - user.last_claim_at).total_seconds()
            if elapsed < CLAIM_COOLDOWN_SECONDS:
                remaining = CLAIM_COOLDOWN_SECONDS - elapsed
                await update.message.reply_text(
                    f"⏳ زود اومدی! {format_cooldown(remaining)} دیگه صبر کن."
                )
                return

        earned = random.randint(CLAIM_POINTS_MIN, CLAIM_POINTS_MAX)
        old_level = user.level
        user.points += earned
        user.last_claim_at = now
        new_level = get_level_for_points(user.points)
        user.level = new_level
        session.commit()

        text = f"✅ {earned} پوینت گرفتی! (مجموع: {user.points})"

        unlocked_game = get_newly_unlocked_game(old_level, new_level)
        if unlocked_game:
            text += (
                f"\n\n🎉 تبریک! به سطح {new_level} رسیدی و بازی "
                f"«{GAME_NAMES_FA[unlocked_game]} {GAME_EMOJIS[unlocked_game]}» "
                "برات باز شد!"
            )

        await update.message.reply_text(text)
    finally:
        session.close()


# ---------- سیستم چالش دونفره ----------

async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "باید روی پیام کسی که می‌خوای دعوتش کنی ریپلای کنی.\n"
            "مثال: روی پیامش ریپلای کن و بنویس /challenge dice"
        )
        return

    if not context.args:
        await update.message.reply_text(
            "بازی رو مشخص کن: dice / darts / bowling / football"
        )
        return

    game_type = context.args[0].lower()
    if game_type not in GAME_EMOJIS:
        await update.message.reply_text("این بازی معتبر نیست.")
        return

    challenger = update.effective_user
    opponent = update.message.reply_to_message.from_user

    if opponent.id == challenger.id:
        await update.message.reply_text("نمیتونی خودتو دعوت کنی 😄")
        return

    if opponent.is_bot:
        await update.message.reply_text("نمیتونی یه بات رو دعوت کنی.")
        return

    session = get_session()
    try:
        challenger_user = get_or_create_user(session, challenger)
        unlocked = get_unlocked_games(challenger_user.level)
        if game_type not in unlocked:
            await update.message.reply_text(
                f"هنوز بازی «{GAME_NAMES_FA[game_type]}» برات باز نشده."
            )
            return

        get_or_create_user(session, opponent)  # مطمئن شو حریف هم ثبت‌نامه

        challenge = Challenge(
            chat_id=update.effective_chat.id,
            game_type=game_type,
            player1_id=challenger.id,
            player2_id=opponent.id,
            status="pending",
        )
        session.add(challenge)
        session.commit()
        challenge_id = challenge.id
    finally:
        session.close()

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ قبول می‌کنم", callback_data=f"accept:{challenge_id}")]]
    )
    await update.message.reply_text(
        f"🎮 {challenger.first_name} از {opponent.first_name} دعوت کرد برای "
        f"بازی {GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]}!\n"
        f"({opponent.first_name} باید دکمه زیر رو بزنه)",
        reply_markup=keyboard,
    )


async def accept_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    challenge_id = int(query.data.split(":")[1])

    session = get_session()
    try:
        challenge = session.get(Challenge, challenge_id)
        if challenge is None or challenge.status != "pending":
            await query.answer("این دعوت دیگه معتبر نیست.", show_alert=True)
            return

        if query.from_user.id != challenge.player2_id:
            await query.answer("این دعوت برای تو نیست!", show_alert=True)
            return

        challenge.status = "active"
        session.commit()

        game_type = challenge.game_type
        p1_id = challenge.player1_id
        p2_id = challenge.player2_id
    finally:
        session.close()

    await query.answer("قبول کردی! نوبت پرتابه.")

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🎲 پرتاب بازیکن ۱", callback_data=f"throw:{challenge_id}:1"
                ),
                InlineKeyboardButton(
                    f"🎲 پرتاب بازیکن ۲", callback_data=f"throw:{challenge_id}:2"
                ),
            ]
        ]
    )
    await query.edit_message_text(
        f"بازی {GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]} شروع شد!\n"
        "هر بازیکن دکمه خودش رو بزنه تا پرتاب کنه.",
        reply_markup=keyboard,
    )


async def throw_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, challenge_id_str, slot_str = query.data.split(":")
    challenge_id = int(challenge_id_str)
    slot = int(slot_str)

    session = get_session()
    try:
        challenge = session.get(Challenge, challenge_id)
        if challenge is None or challenge.status != "active":
            await query.answer("این بازی دیگه فعال نیست.", show_alert=True)
            return

        expected_player = challenge.player1_id if slot == 1 else challenge.player2_id
        if query.from_user.id != expected_player:
            await query.answer("این دکمه برای تو نیست!", show_alert=True)
            return

        already_thrown = (
            challenge.player1_score if slot == 1 else challenge.player2_score
        )
        if already_thrown is not None:
            await query.answer("قبلاً پرتاب کردی!", show_alert=True)
            return

        game_type = challenge.game_type
        chat_id = challenge.chat_id
    finally:
        session.close()

    await query.answer()

    dice_message = await context.bot.send_dice(
        chat_id=chat_id, emoji=GAME_EMOJIS[game_type]
    )
    value = dice_message.dice.value

    session = get_session()
    try:
        challenge = session.get(Challenge, challenge_id)
        if slot == 1:
            challenge.player1_score = value
        else:
            challenge.player2_score = value
        session.commit()

        p1_score = challenge.player1_score
        p2_score = challenge.player2_score
        p1_id = challenge.player1_id
        p2_id = challenge.player2_id
        game_type = challenge.game_type

        finished = p1_score is not None and p2_score is not None
        if finished:
            challenge.status = "finished"
            session.commit()
    finally:
        session.close()

    if not finished:
        await context.bot.send_message(
            chat_id=chat_id, text="پرتاب ثبت شد. منتظر نفر بعدی..."
        )
        return

    p1_user = await context.bot.get_chat(p1_id)
    p2_user = await context.bot.get_chat(p2_id)

    if p1_score > p2_score:
        result_text = f"🏆 برنده: {p1_user.first_name} ({p1_score} در برابر {p2_score})"
    elif p2_score > p1_score:
        result_text = f"🏆 برنده: {p2_user.first_name} ({p2_score} در برابر {p1_score})"
    else:
        result_text = f"🤝 مساوی شد! ({p1_score} در برابر {p2_score})"

    await context.bot.send_message(chat_id=chat_id, text=result_text)


def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("challenge", challenge_command))

    app.add_handler(CallbackQueryHandler(accept_challenge, pattern=r"^accept:\d+$"))
    app.add_handler(CallbackQueryHandler(throw_dice, pattern=r"^throw:\d+:[12]$"))

    app.add_handler(
        MessageHandler(
            filters.Regex(rf"^{CLAIM_KEYWORD}$") & filters.TEXT & ~filters.COMMAND,
            claim_points,
        )
    )

    logger.info("Bot started polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
