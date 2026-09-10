import logging
import random
import re
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters
)

from config import (
    ADMIN_IDS, BOT_TOKEN, CLAIM_COOLDOWN_SECONDS, CLAIM_KEYWORD,
    CLAIM_POINTS_MAX, CLAIM_POINTS_MIN, REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL
)
from database import Challenge, FoxHunt, User, get_session, init_db
from game_logic import (
    GAME_EMOJIS, GAME_NAMES_FA, HUNT_ITEMS, fox_capacity, fox_level_reward,
    fox_production_per_second, fox_rank, fox_upgrade_cost, get_level_for_points,
    get_unlocked_games, points_to_next_level, points_needed_for_level
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

FOX_UNLOCK_LEVEL = 3
FOX_MAX_LEVEL = 35
HUNT_COOLDOWN = 15 * 60
HUNT_DECISION_TIMEOUT = 120
TRANSFER_COOLDOWN = 60
TRANSFER_MAX = 500_000

# ---------- ابزارهای عمومی ----------

def now_utc():
    return datetime.now(timezone.utc)


def aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def seconds_left(dt, duration):
    if dt is None:
        return 0
    return max(0, int(duration - (now_utc() - aware(dt)).total_seconds()))


def format_duration(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ساعت و {m} دقیقه"
    if m:
        return f"{m} دقیقه و {s} ثانیه"
    return f"{s} ثانیه"


def reply_kwargs(message):
    # پاسخ همیشه به پیام همان کاربر متصل می‌شود.
    return {"reply_to_message_id": message.message_id}

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
    if user.id in ADMIN_IDS:
        return True
    if await is_member(context.bot, user.id):
        return True
    text = "🔒 برای استفاده از ربات اول باید عضو کانال بشی.\n\nبعد از عضویت روی «عضو شدم، بررسی کن» بزن."
    if update.callback_query:
        await update.callback_query.answer("اول باید عضو کانال بشی.", show_alert=True)
        try:
            await update.callback_query.message.edit_text(text, reply_markup=join_keyboard())
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(text, reply_markup=join_keyboard(), **reply_kwargs(update.message))
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
            fox_name="مکار",
            fox_level=1,
            fox_belly=3,
            fox_points=0,
            fox_total_earned=0,
            fox_production_remainder=0.0,
        )
        session.add(user)
        session.commit()
    else:
        changed = False
        if user.username != tg_user.username:
            user.username = tg_user.username; changed = True
        if user.first_name != tg_user.first_name:
            user.first_name = tg_user.first_name; changed = True
        if not user.fox_name:
            user.fox_name = "مکار"; changed = True
        if not user.fox_level or user.fox_level < 1:
            user.fox_level = 1; changed = True
        if user.fox_belly is None:
            user.fox_belly = 3; changed = True
        if user.fox_points is None:
            user.fox_points = 0; changed = True
        if user.fox_total_earned is None:
            user.fox_total_earned = 0; changed = True
        if user.fox_production_remainder is None:
            user.fox_production_remainder = 0.0; changed = True
        calculated = get_level_for_points(user.points or 0)
        if user.level != calculated:
            user.level = calculated; changed = True
        if changed:
            session.commit()
    return user


def add_points(session, user, amount):
    user.points = max(0, user.points + amount)
    if amount > 0:
        user.total_earned += amount
    old = user.level
    user.level = get_level_for_points(user.points)
    return old, user.level


def apply_level_rewards(session, user, old_level, new_level):
    """جایزه روب‌پوینت هر لول؛ فقط برای لول‌های جدید و حداکثر تا 35."""
    rewards = []
    if new_level <= old_level:
        return rewards
    start = max(2, old_level + 1)
    end = min(new_level, FOX_MAX_LEVEL)
    for lvl in range(start, end + 1):
        reward = fox_level_reward(lvl)
        user.fox_points += reward
        rewards.append((lvl, reward))
    return rewards

# ---------- پروفایل و منو ----------

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
        f"برای پوینت معمولی «{CLAIM_KEYWORD}» رو بفرست.\n"
        f"🦊 در لول 3 روباه برایت باز می‌شود.\n"
        "🦊 دستورهای روباه: روباه / روبی / روباهیو\n"
        "💰 جمع‌کردن روب‌پوینت: روب روب / هور هور / عو عو\n"
        "🏹 شکار: شکار\n\n"
        "📌 /profile — آمار کامل\n🎮 /games — بازی‌ها\n🛠 /admin — پنل مدیریت",
        **reply_kwargs(update.message)
    )


async def profile_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        next_level, remaining = points_to_next_level(user.points)
        next_text = f"{remaining} پوینت تا لول {next_level}" if next_level else "🏆 بالاترین لول فعلی"
        unlocked = get_unlocked_games(user.level)
        games = "، ".join(GAME_NAMES_FA[g] for g in unlocked) if unlocked else "هنوز بازی‌ای باز نشده"
        text = (
            f"👤 آمار {user.first_name or 'کاربر'}\n\n"
            f"💰 پوینت فعلی: {user.points}\n📈 پوینت کسب‌شده: {user.total_earned}\n"
            f"⭐ سطح: {user.level}\n⏳ {next_text}\n🎮 بازی‌های باز: {games}"
        )
    finally:
        session.close()
    await update.message.reply_text(text, **reply_kwargs(update.message))


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
        "روی پیام حریف ریپلای کن و /challenge dice بفرست.",
        **reply_kwargs(update.message)
    )


async def game_command(update, context):
    await games_command(update, context)

# ---------- روباه ----------

def fox_keyboard(user_id, user_level):
    rows = [
        [InlineKeyboardButton("🧲 برداشت روب پوینت ها", callback_data=f"fox:collect:{user_id}")],
        [InlineKeyboardButton("⭐ ارتقا مقام", callback_data=f"fox:upgrade:{user_id}")],
        [InlineKeyboardButton("✏️ تغییر اسم روباه", callback_data=f"fox:rename:{user_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def fox_profile_text(user):
    lvl = max(1, min(FOX_MAX_LEVEL, user.fox_level or 1))
    cap = fox_capacity(lvl)
    rate = fox_production_per_second(lvl)
    return (
        f"🦊 {user.fox_name or 'مکار'}\n\n"
        f"❤️ شکم روباه: {user.fox_belly}/{cap}\n\n"
        f"🏅 مقام: {fox_rank(lvl)}\n"
        f"⭐ لول روباه: {lvl}/{FOX_MAX_LEVEL}\n\n"
        f"🪙 روب پوینت های تولید شده: {int(user.fox_points):,}\n"
        f"⚡ روب پوینت در ثانیه: {rate:.2f}\n"
        f"🎒 ظرفیت شکم: {cap:,}\n"
        f"📦 ظرفیت ذخیره روب‌پوینت: {fox_storage_capacity(lvl):,}\n"
        f"💰 هزینه ارتقا: {fox_upgrade_cost(lvl):,} روب پوینت"
    )


def update_fox_production(user):
    """تولید تجمعی را تا لحظه فعلی حساب می‌کند؛ فقط وقتی شکم کامل است."""
    if user.fox_last_production_at is None:
        user.fox_last_production_at = now_utc()
        return 0.0
    elapsed = max(0.0, (now_utc() - aware(user.fox_last_production_at)).total_seconds())
    user.fox_last_production_at = now_utc()
    if user.fox_belly < fox_capacity(user.fox_level):
        return 0.0
    rate = fox_production_per_second(user.fox_level)
    produced = elapsed * rate
    return produced


def settle_fox_production(user):
    """تولید را محاسبه و با سقف 1000/3500/... ذخیره می‌کند."""
    produced = update_fox_production(user)
    cap = fox_storage_capacity(user.fox_level)
    before = int(user.fox_points or 0)
    if produced <= 0:
        return 0.0
    total = float(user.fox_production_remainder or 0.0) + produced
    whole = int(total)
    remainder = total - whole
    room = max(0, cap - before)
    added = min(room, whole)
    user.fox_points = before + added
    if added > 0:
        user.fox_total_earned += added
    # وقتی ظرفیت پر شد، زمان تولید بعدی از همان لحظه ادامه پیدا می‌کند و چیزی پشت ظرفیت جمع نمی‌شود.
    user.fox_production_remainder = 0.0 if added < whole else remainder
    return float(added)


def fox_storage_capacity(level):
    # دنباله درخواستی: 1000، 3500، 7000، 11500، ...
    level = max(1, int(level))
    n = level - 1
    return 1000 + 2000 * n + 500 * n * n


async def fox_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < FOX_UNLOCK_LEVEL:
            await update.message.reply_text(
                f"🔒 روباه در سطح {FOX_UNLOCK_LEVEL} باز می‌شود.\n"
                f"⭐ سطح فعلی تو: {user.level}", **reply_kwargs(update.message)
            )
            return
        settle_fox_production(user)
        session.commit()
        text = fox_profile_text(user) + f"\n🧺 ظرفیت نگهداری روب‌پوینت: {fox_storage_capacity(user.fox_level):,}"
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=fox_keyboard(update.effective_user.id, user.level), **reply_kwargs(update.message))


async def fox_button(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 3:
        return
    _, action, owner_s = parts
    owner_id = int(owner_s)
    if q.from_user.id != owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.", show_alert=True)
        return
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, q.from_user)
        if user.level < FOX_UNLOCK_LEVEL:
            await q.answer("روباه از سطح 3 باز می‌شود.", show_alert=True)
            return
        settle_fox_production(user)
        if action == "collect":
            amount = int(user.fox_points or 0)
            if user.fox_belly < fox_capacity(user.fox_level):
                await q.answer("🦊 شکم روباه هنوز پر نیست.", show_alert=True)
            else:
                user.fox_points = 0
                session.commit()
                nxt = next_fox_point_seconds(user)
                next_text = f"⏱ روب‌پوینت بعدی حدود {format_duration(nxt)} دیگر تولید می‌شود." if nxt else "⏸ تولید متوقف است تا شکم کامل شود."
                await q.answer("برداشت انجام شد! 💰")
                await q.message.edit_text(fox_profile_text(user) + f"\n\n💰 {amount:,} روب پوینت برداشت شد.\n{next_text}", reply_markup=fox_keyboard(user.id, user.level))
            return
        if action == "upgrade":
            lvl = user.fox_level
            if lvl >= FOX_MAX_LEVEL:
                await q.answer("روباه به بالاترین لول رسیده! 🏆", show_alert=True)
            else:
                cost = fox_upgrade_cost(lvl)
                if user.fox_points < cost:
                    await q.answer(f"روب‌پوینت کافی نیست. {cost:,.0f} لازم داری.", show_alert=True)
                else:
                    user.fox_points -= cost
                    user.fox_level += 1
                    # با هر ارتقا فقط ظرفیت شکم +2 می‌شود؛ غذای فعلی مصرف یا اضافه نمی‌شود.
                    user.fox_belly = min(user.fox_belly, fox_capacity(user.fox_level))
                    user.fox_last_production_at = now_utc()
                    session.commit()
                    await q.answer(f"🦊 روباه رفت لول {user.fox_level}!", show_alert=True)
                    await q.message.edit_text(fox_profile_text(user) + f"\n\n🎉 روباه ارتقا یافت!\n🏅 مقام جدید: {fox_rank(user.fox_level)}", reply_markup=fox_keyboard(user.id, user.level))
                    return
        elif action == "hunt":
            await handle_hunt_request(q, session, user, context)
            return
        elif action == "fridge":
            if user.level < 7:
                await q.answer("🧊 یخچال روبی در سطح 7 باز می‌شود.", show_alert=True)
                return
            items = session.query(FoxHunt).filter(FoxHunt.user_id == user.id, FoxHunt.status == "fridge").order_by(FoxHunt.id.desc()).limit(20).all()
            if not items:
                await q.answer("یخچال روبی خالی است.", show_alert=True)
                return
            text = "🧊 یخچال روبی\n\n" + "\n".join(f"{i.emoji} {i.item_name} — ارزش غذایی {i.nutrition} — فروش {i.sell_value:,} روب پوینت" for i in items)
            await q.answer()
            await q.message.reply_text(text)
            return
        elif action == "rename":
            context.user_data["fox_rename"] = True
            await q.answer()
            await q.message.reply_text("✏️ اسم جدید روباه را بفرست.\nحداکثر 16 کاراکتر.")
            return
        session.commit()
    finally:
        session.close()
    await q.answer()

# ---------- شکار ----------

async def handle_hunt_request(q, session, user, context):
    remaining = seconds_left(user.last_hunt_at, HUNT_COOLDOWN)
    if remaining:
        await q.answer(f"⏳ شکار بعدی: {format_duration(remaining)} دیگر.", show_alert=True)
        return
    emoji = random.choice(list(HUNT_ITEMS.keys()))
    item = HUNT_ITEMS[emoji]
    hunt = FoxHunt(user_id=user.id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending")
    user.last_hunt_at = now_utc()
    session.add(hunt)
    session.commit()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.id}")],
        [InlineKeyboardButton("🧊 انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.id}")],
    ])
    await q.answer()
    await q.message.reply_text(
        f"{emoji}\n\n🎯 شما {item['name']} را شکار کردید!\n"
        f"🍖 ارزش غذایی: {item['nutrition']}\n\n"
        f"چه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
        reply_markup=kb
    )


async def hunt_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < 2:
            await update.message.reply_text("🔒 شکار از سطح 2 باز می‌شود.", **reply_kwargs(update.message))
            return
        remaining = seconds_left(user.last_hunt_at, HUNT_COOLDOWN)
        if remaining:
            await update.message.reply_text(f"⏳ شکار بعدی {format_duration(remaining)} دیگر فعال می‌شود.", **reply_kwargs(update.message))
            return
        # اینجا همان منطق دکمه شکار، اما با پیام واقعیِ ریپلای‌شده اجرا می‌شود.
        emoji = random.choice(list(HUNT_ITEMS.keys()))
        item = HUNT_ITEMS[emoji]
        hunt = FoxHunt(user_id=user.id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending")
        user.last_hunt_at = now_utc()
        session.add(hunt)
        session.commit()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.id}")],
            [InlineKeyboardButton("🧊 انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.id}")],
        ])
        await update.message.reply_text(
            f"{emoji}\n\n🎯 شما {item['name']} را شکار کردید!\n🍖 ارزش غذایی: {item['nutrition']}\n\n"
            "چه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
            reply_markup=kb, **reply_kwargs(update.message)
        )
    finally:
        session.close()


async def hunt_button(update, context):
    q = update.callback_query
    try:
        _, action, hid_s, owner_s = q.data.split(":")
        hid, owner_id = int(hid_s), int(owner_s)
    except Exception:
        return
    if q.from_user.id != owner_id:
        await q.answer("⛔ این شکار برای کاربر دیگری است.", show_alert=True)
        return
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        hunt = session.get(FoxHunt, hid)
        user = session.get(User, owner_id)
        if not hunt or not user or hunt.status != "pending":
            await q.answer("این شکار دیگر فعال نیست.", show_alert=True)
            return
        if (now_utc() - aware(hunt.created_at)).total_seconds() > HUNT_DECISION_TIMEOUT:
            hunt.status = "expired"
            session.commit()
            await q.answer("⏰ فرصت تصمیم‌گیری تمام شد؛ شکار پرید!", show_alert=True)
            return
        settle_fox_production(user)
        if action == "feed":
            old = user.fox_belly
            user.fox_belly = min(fox_capacity(user.fox_level), user.fox_belly + hunt.nutrition)
            hunt.status = "fed"
            session.commit()
            await q.answer("🦊 شکار به روباه داده شد!")
            await q.message.edit_text(
                f"🦊 {hunt.emoji} {hunt.item_name} به روباه داده شد.\n"
                f"🍖 شکم روباه: {old}/{fox_capacity(user.fox_level)} → {user.fox_belly}/{fox_capacity(user.fox_level)}\n\n"
                f"⚡ تولید روب‌پوینت فقط وقتی شکم کاملاً پر باشد فعال است."
            )
        elif action == "sell":
            user.fox_points += hunt.sell_value
            hunt.status = "sold"
            session.commit()
            await q.answer("💰 فروخته شد!")
            await q.message.edit_text(f"💰 {hunt.emoji} {hunt.item_name} فروخته شد و {hunt.sell_value:,} روب پوینت گرفتی.\n🪙 موجودی روب‌پوینت: {int(user.fox_points):,}")
        elif action == "fridge":
            if user.level < 7:
                await q.answer("🧊 یخچال روبی در سطح 7 باز می‌شود.", show_alert=True)
                return
            hunt.status = "fridge"
            session.commit()
            await q.answer("🧊 داخل یخچال روبی قرار گرفت!")
            await q.message.edit_text(f"🧊 {hunt.emoji} {hunt.item_name} داخل یخچال روبی ذخیره شد.")
    finally:
        session.close()

# ---------- جمع‌آوری روب‌پوینت ----------

FOX_CLAIM_ALIASES = {"روب روب", "هور هور", "عو عو", "روب روب!", "هور هور!", "عو عو!"}


def next_fox_point_seconds(user):
    if user.fox_belly < fox_capacity(user.fox_level):
        return None
    rate = fox_production_per_second(user.fox_level)
    remainder = float(user.fox_production_remainder or 0.0)
    return max(1, int((1.0 - remainder) / rate + 0.999999))


async def collect_fox_points(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < FOX_UNLOCK_LEVEL:
            await update.message.reply_text("🔒 روباه در سطح 3 باز می‌شود.", **reply_kwargs(update.message))
            return
        before = user.fox_points
        produced = settle_fox_production(user)
        if user.fox_belly < fox_capacity(user.fox_level):
            session.commit()
            await update.message.reply_text(
                f"🦊 روباه هنوز سیر نشده!\n❤️ شکم: {user.fox_belly}/{fox_capacity(user.fox_level)}\n"
                "🏹 با «شکار» غذا پیدا کن و شکمش را کامل پر کن.\n"
                f"⏱ شکار بعدی: {format_duration(seconds_left(user.last_hunt_at, HUNT_COOLDOWN)) if seconds_left(user.last_hunt_at, HUNT_COOLDOWN) else 'الان آماده است'}",
                **reply_kwargs(update.message)
            )
            return
        amount = user.fox_points
        user.fox_points = 0
        session.commit()
        nxt = next_fox_point_seconds(user)
        next_text = f"⏱ روب‌پوینت بعدی حدود {format_duration(nxt)} دیگر تولید می‌شود." if nxt is not None else "⏸ تا وقتی شکم روباه کامل نباشد تولید متوقف است."
        await update.message.reply_text(
            f"🦊 برداشت روب پوینت ها\n\n💰 +{int(amount):,} روب پوینت برداشت شد.\n"
            f"⚡ تولید فعلی: {fox_production_per_second(user.fox_level):.2f} روب‌پوینت در ثانیه\n"
            f"📦 ظرفیت: {fox_storage_capacity(user.fox_level):,}\n{next_text}",
            **reply_kwargs(update.message)
        )
    finally:
        session.close()

# ---------- تغییر نام روباه ----------

async def handle_fox_rename_text(update, context):
    if not context.user_data.get("fox_rename"):
        return False
    context.user_data.pop("fox_rename", None)
    if not await require_membership(update, context):
        return True
    name = update.message.text.strip()
    if not name or len(name) > 16:
        await update.message.reply_text("❌ اسم باید بین 1 تا 16 کاراکتر باشد.", **reply_kwargs(update.message))
        return True
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < FOX_UNLOCK_LEVEL:
            await update.message.reply_text("🔒 روباه در سطح 3 باز می‌شود.", **reply_kwargs(update.message))
            return True
        user.fox_name = name
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(f"✅ اسم روباه تغییر کرد به: 🦊 {name}", **reply_kwargs(update.message))
    return True

async def fridge_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < 7:
            await update.message.reply_text("🧊 یخچال روبی در سطح 7 باز می‌شود.", **reply_kwargs(update.message))
            return
        items = session.query(FoxHunt).filter(FoxHunt.user_id == user.id, FoxHunt.status == "fridge").order_by(FoxHunt.id.desc()).limit(20).all()
        if not items:
            text = "🧊 یخچال روبی\n\nیخچال فعلاً خالی است."
        else:
            text = "🧊 یخچال روبی\n\n" + "\n".join(
                f"{i.emoji} {i.item_name} — ارزش غذایی {i.nutrition} — فروش {i.sell_value:,} روب پوینت"
                for i in items
            )
    finally:
        session.close()
    await update.message.reply_text(text, **reply_kwargs(update.message))

# ---------- انتقال روب‌پوینت ----------

async def transfer_command(update, context):
    if not await require_membership(update, context):
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await update.message.reply_text("👥 برای انتقال، روی پیام کاربر موردنظر ریپلای کن و بنویس: انتقال روب پوینت 50", **reply_kwargs(update.message))
        return
    raw_amount = context.args[-1] if context.args else context.user_data.pop("transfer_amount", None)
    if raw_amount is None:
        await update.message.reply_text("فرمت: انتقال روب پوینت 50", **reply_kwargs(update.message))
        return
    try:
        amount = int(str(raw_amount).replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ مقدار انتقال باید عدد باشد.", **reply_kwargs(update.message))
        return
    target = update.message.reply_to_message.from_user
    if target.id == update.effective_user.id or target.is_bot:
        await update.message.reply_text("❌ انتقال به خودت یا ربات مجاز نیست.", **reply_kwargs(update.message))
        return
    if amount <= 0 or amount > TRANSFER_MAX:
        await update.message.reply_text(f"❌ سقف هر انتقال {TRANSFER_MAX:,} روب پوینت است.", **reply_kwargs(update.message))
        return
    session = get_session()
    try:
        sender = get_or_create_user(session, update.effective_user)
        receiver = get_or_create_user(session, target)
        if sender.level < 2:
            await update.message.reply_text("🔒 انتقال روب پوینت از سطح 2 باز می‌شود.", **reply_kwargs(update.message))
            return
        left = seconds_left(sender.last_transfer_at, TRANSFER_COOLDOWN)
        if left:
            await update.message.reply_text(f"⏳ انتقال بعدی را {format_duration(left)} دیگر می‌توانی انجام بدهی.", **reply_kwargs(update.message))
            return
        settle_fox_production(sender)
        if sender.fox_points < amount:
            await update.message.reply_text(f"❌ روب‌پوینت کافی نیست. موجودی: {int(sender.fox_points):,}", **reply_kwargs(update.message))
            return
        session.commit()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"transfer:yes:{sender.id}:{receiver.id}:{amount}"), InlineKeyboardButton("❌ لغو", callback_data=f"transfer:no:{sender.id}:{receiver.id}:{amount}")]])
        await update.message.reply_text(
            f"💸 انتقال روب پوینت\n\n🦊 فرستنده: {sender.first_name or sender.id}\n👤 گیرنده: {receiver.first_name or receiver.id}\n💰 مقدار: {amount:,}\n\nتایید می‌کنی؟",
            reply_markup=kb, **reply_kwargs(update.message)
        )
    finally:
        session.close()


async def transfer_button(update, context):
    q = update.callback_query
    try:
        _, action, sender_s, receiver_s, amount_s = q.data.split(":")
        sender_id, receiver_id, amount = int(sender_s), int(receiver_s), int(amount_s)
    except Exception:
        return
    if q.from_user.id != sender_id:
        await q.answer("⛔ این انتقال برای کاربر دیگری است.", show_alert=True)
        return
    session = get_session()
    try:
        sender = session.get(User, sender_id)
        receiver = session.get(User, receiver_id)
        if not sender or not receiver:
            await q.answer("کاربر پیدا نشد.", show_alert=True); return
        if action == "no":
            await q.answer("انتقال لغو شد.")
            await q.message.edit_text("❌ انتقال روب پوینت لغو شد.")
            return
        if sender.level < 2:
            await q.answer("انتقال از سطح 2 باز می‌شود.", show_alert=True); return
        left = seconds_left(sender.last_transfer_at, TRANSFER_COOLDOWN)
        if left:
            await q.answer(f"⏳ {format_duration(left)} تا انتقال بعدی.", show_alert=True); return
        settle_fox_production(sender)
        if sender.fox_points < amount:
            await q.answer("روب‌پوینت کافی نیست.", show_alert=True); return
        sender.fox_points -= amount
        receiver.fox_points += amount
        sender.last_transfer_at = now_utc()
        session.commit()
        await q.answer("✅ انتقال انجام شد!")
        await q.message.edit_text(f"✅ {amount:,} روب پوینت با موفقیت انتقال یافت.\n⏳ انتقال بعدی 1 دقیقه دیگر.")
    finally:
        session.close()

# ---------- هور معمولی ----------

async def claim_points(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        now = now_utc()
        if user.last_claim_at is not None:
            elapsed = (now - aware(user.last_claim_at)).total_seconds()
            if elapsed < CLAIM_COOLDOWN_SECONDS:
                await update.message.reply_text(f"⏳ هنوز زوده! {format_duration(CLAIM_COOLDOWN_SECONDS - elapsed)} دیگه.", **reply_kwargs(update.message))
                return
        earned = random.randint(CLAIM_POINTS_MIN, CLAIM_POINTS_MAX)
        old_level = user.level
        user.points += earned
        user.total_earned += earned
        user.last_claim_at = now
        user.level = get_level_for_points(user.points)
        rewards = apply_level_rewards(session, user, old_level, user.level)
        session.commit()
        text = f"⚡ +{earned} پوینت!\n💰 موجودی: {user.points}\n📈 کل کسب‌شده: {user.total_earned}"
        if user.level > old_level:
            text += f"\n\n🎉 تبریک! رفتی لول {user.level}."
            for lvl, reward in rewards:
                text += f"\n🎁 جایزه لول {lvl}: +{reward:,} روب پوینت"
            if old_level < 3 <= user.level:
                text += "\n🦊 قابلیت روباه برایت باز شد!"
        await update.message.reply_text(text, **reply_kwargs(update.message))
    finally:
        session.close()

# ---------- بازی قبلی ----------

async def challenge_command(update, context):
    if not await require_membership(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام حریف ریپلای کن و بعد /challenge dice بفرست.", **reply_kwargs(update.message)); return
    if not context.args:
        await update.message.reply_text("نوع بازی: dice / darts / bowling / football", **reply_kwargs(update.message)); return
    game_type = context.args[0].lower()
    if game_type not in GAME_EMOJIS:
        await update.message.reply_text("بازی معتبر نیست.", **reply_kwargs(update.message)); return
    challenger = update.effective_user
    opponent = update.message.reply_to_message.from_user
    if opponent.id == challenger.id or opponent.is_bot:
        await update.message.reply_text("این کاربر نمی‌تونه حریف بازی باشه.", **reply_kwargs(update.message)); return
    session = get_session()
    try:
        cuser = get_or_create_user(session, challenger)
        if game_type not in get_unlocked_games(cuser.level):
            await update.message.reply_text("این بازی هنوز برای لولت باز نشده.", **reply_kwargs(update.message)); return
        get_or_create_user(session, opponent)
        challenge = Challenge(chat_id=update.effective_chat.id, game_type=game_type, player1_id=challenger.id, player2_id=opponent.id, status="pending")
        session.add(challenge); session.commit(); cid = challenge.id
    finally:
        session.close()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ قبول می‌کنم", callback_data=f"accept:{cid}")]])
    await update.message.reply_text(f"🎮 {challenger.first_name} تو را به {GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]} دعوت کرد.", reply_markup=kb, **reply_kwargs(update.message))


async def accept_challenge(update, context):
    if not await require_membership(update, context): return
    q = update.callback_query; cid = int(q.data.split(":")[1])
    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if ch is None or ch.status != "pending": await q.answer("این دعوت منقضی شده.", show_alert=True); return
        if q.from_user.id != ch.player2_id: await q.answer("این دعوت برای تو نیست.", show_alert=True); return
        ch.status = "active"; session.commit(); game_type = ch.game_type
    finally: session.close()
    await q.answer("بازی شروع شد!")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 بازیکن ۱", callback_data=f"throw:{cid}:1"), InlineKeyboardButton("🎮 بازیکن ۲", callback_data=f"throw:{cid}:2")]])
    await q.edit_message_text(f"{GAME_NAMES_FA[game_type]} {GAME_EMOJIS[game_type]} شروع شد!\nهر بازیکن فقط دکمه خودش را بزند.", reply_markup=kb)


async def throw_dice(update, context):
    if not await require_membership(update, context): return
    q = update.callback_query; _, cid_s, slot_s = q.data.split(":"); cid, slot = int(cid_s), int(slot_s)
    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if ch is None or ch.status != "active": await q.answer("بازی فعال نیست.", show_alert=True); return
        expected = ch.player1_id if slot == 1 else ch.player2_id
        if q.from_user.id != expected: await q.answer("این دکمه برای تو نیست.", show_alert=True); return
        old = ch.player1_score if slot == 1 else ch.player2_score
        if old is not None: await q.answer("قبلاً بازی کردی.", show_alert=True); return
        game_type, chat_id = ch.game_type, ch.chat_id
    finally: session.close()
    await q.answer(); msg = await context.bot.send_dice(chat_id=chat_id, emoji=GAME_EMOJIS[game_type]); value = msg.dice.value
    session = get_session()
    try:
        ch = session.get(Challenge, cid)
        if slot == 1: ch.player1_score = value
        else: ch.player2_score = value
        p1, p2 = ch.player1_score, ch.player2_score; finished = p1 is not None and p2 is not None
        if finished: ch.status = "finished"
        session.commit(); p1_id, p2_id = ch.player1_id, ch.player2_id
    finally: session.close()
    if not finished:
        await context.bot.send_message(chat_id=chat_id, text="✅ نتیجه ثبت شد؛ منتظر بازیکن بعدی..."); return
    if p1 > p2: winner, loser, text = p1_id, p2_id, f"🏆 بازیکن ۱ برنده شد! {p1} - {p2}"
    elif p2 > p1: winner, loser, text = p2_id, p1_id, f"🏆 بازیکن ۲ برنده شد! {p2} - {p1}"
    else: winner = loser = None; text = f"🤝 مساوی! {p1} - {p2}"
    session = get_session()
    try:
        if winner:
            wu, lu = session.get(User, winner), session.get(User, loser); oldw, neww = add_points(session, wu, 10); oldl, newl = add_points(session, lu, 3)
            apply_level_rewards(session, wu, oldw, neww); apply_level_rewards(session, lu, oldl, newl); session.commit(); text += "\n\n🎁 پاداش بازی: برنده +10 پوینت | بازنده +3 پوینت"
        else:
            u1, u2 = session.get(User, p1_id), session.get(User, p2_id); o1,n1=add_points(session,u1,5); o2,n2=add_points(session,u2,5); apply_level_rewards(session,u1,o1,n1); apply_level_rewards(session,u2,o2,n2); session.commit(); text += "\n\n🎁 پاداش مساوی: هر نفر +5 پوینت"
    finally: session.close()
    await context.bot.send_message(chat_id=chat_id, text=text)

# ---------- پنل ادمین ----------

def admin_only(user_id): return user_id in ADMIN_IDS

async def admin_command(update, context):
    if not await require_membership(update, context): return
    if not admin_only(update.effective_user.id): await update.message.reply_text("⛔ دسترسی نداری.", **reply_kwargs(update.message)); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats")],
        [InlineKeyboardButton("👥 تعداد کاربران", callback_data="admin:users")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")],
        [InlineKeyboardButton("➕ دادن هور پوینت", callback_data="admin:addpoints")],
        [InlineKeyboardButton("⭐ تنظیم سطح", callback_data="admin:setlevel")],
        [InlineKeyboardButton("🦊 تنظیم روب‌پوینت", callback_data="admin:setfoxpoints")],
    ])
    await update.message.reply_text("🛠 پنل مدیریت\n\nبرای عملیات متنی، بعد از زدن گزینه مربوطه مقدار را بفرست.", reply_markup=kb, **reply_kwargs(update.message))


async def admin_callback(update, context):
    q = update.callback_query
    if not admin_only(q.from_user.id): await q.answer("دسترسی نداری.", show_alert=True); return
    action = q.data.split(":")[1]; await q.answer()
    if action == "stats":
        session=get_session()
        try:
            users=session.query(User).count(); points=sum((u.points or 0) for u in session.query(User).all()); earned=sum((u.total_earned or 0) for u in session.query(User).all()); games=session.query(Challenge).count(); fox=sum((u.fox_points or 0) for u in session.query(User).all())
        finally: session.close()
        await q.message.reply_text(f"📊 آمار کلی\n\n👥 کاربران: {users}\n💰 پوینت معمولی: {points}\n📈 کل کسب‌شده: {earned}\n🦊 روب‌پوینت: {fox:,.2f}\n🎮 بازی‌ها: {games}")
    elif action == "users":
        session=get_session()
        try: count=session.query(User).count()
        finally: session.close()
        await q.message.reply_text(f"👥 تعداد کاربران ثبت‌شده: {count}")
    elif action == "broadcast": context.user_data["admin_action"]="broadcast"; await q.message.reply_text("📣 متن پیام همگانی را بفرست.")
    elif action == "addpoints": context.user_data["admin_action"]="addpoints"; await q.message.reply_text("➕ فرمت: آیدی عددی کاربر + مقدار")
    elif action == "setlevel": context.user_data["admin_action"]="setlevel"; await q.message.reply_text("⭐ فرمت: آیدی عددی کاربر + سطح")
    elif action == "setfoxpoints": context.user_data["admin_action"]="setfoxpoints"; await q.message.reply_text("🦊 فرمت: آیدی عددی کاربر + مقدار روب‌پوینت")


async def admin_text(update, context):
    if not admin_only(update.effective_user.id): return
    action=context.user_data.get("admin_action")
    if not action: return
    context.user_data.pop("admin_action",None); text=update.message.text.strip()
    if action == "broadcast":
        session=get_session()
        try: users=[u.telegram_id for u in session.query(User).all()]
        finally: session.close()
        ok=fail=0
        for uid in users:
            try: await context.bot.send_message(uid,"📢 پیام مدیریت:\n\n"+text); ok+=1
            except Exception: fail+=1
        await update.message.reply_text(f"✅ ارسال شد: {ok}\n❌ ناموفق: {fail}", **reply_kwargs(update.message)); return
    parts=text.split()
    if len(parts)!=2 or not all(p.lstrip("-").isdigit() for p in parts): await update.message.reply_text("فرمت اشتباه است.", **reply_kwargs(update.message)); return
    uid,value=int(parts[0]),int(parts[1]); session=get_session()
    try:
        user=session.get(User,uid)
        if not user: await update.message.reply_text("کاربر پیدا نشد.", **reply_kwargs(update.message)); return
        if action=="addpoints":
            old=user.level; user.points=max(0,user.points+value); user.level=get_level_for_points(user.points); rewards=apply_level_rewards(session,user,old,user.level); session.commit(); await update.message.reply_text(f"✅ انجام شد.\nپوینت: {user.points}\nسطح: {user.level}\nروب‌پوینت جایزه: {sum(r for _,r in rewards):,}", **reply_kwargs(update.message))
        elif action=="setlevel":
            if value<1 or value>100: await update.message.reply_text("سطح باید بین 1 تا 100 باشد.", **reply_kwargs(update.message)); return
            user.level=value; user.points=max(user.points,points_needed_for_level(value) or 0); session.commit(); await update.message.reply_text(f"✅ سطح کاربر شد {user.level} (پوینت: {user.points})", **reply_kwargs(update.message))
        elif action=="setfoxpoints":
            user.fox_points=max(0,value); session.commit(); await update.message.reply_text(f"🦊 روب‌پوینت کاربر: {user.fox_points:,.2f}", **reply_kwargs(update.message))
    finally: session.close()


async def membership_callback(update, context):
    q=update.callback_query
    if q.data!="check_membership": return
    if await is_member(context.bot,q.from_user.id):
        await q.answer("عضویت تأیید شد! 🎉"); await q.message.edit_text(f"✅ تأیید شد!\n\nحالا «{CLAIM_KEYWORD}» رو بفرست.")
    else: await q.answer("هنوز عضویتت تأیید نشده.",show_alert=True)


async def text_router(update, context):
    if not update.message or not update.message.text: return
    if await handle_fox_rename_text(update, context): return
    text=update.message.text.strip()
    if text in FOX_CLAIM_ALIASES:
        await collect_fox_points(update,context); return
    if text in {"روباه", "روبی", "روباهیو", "🦊 روباه", "🦊 روبی", "🦊 روباهیو"}:
        await fox_command(update, context); return
    if text in {"شکار", "شکار!", "🏹 شکار"}:
        await hunt_command(update, context); return
    if text in {"یخچال روبی", "🧊 یخچال روبی"}:
        await fridge_command(update, context); return
    # انتقال روب پوینت 50 — فقط با ریپلای به گیرنده
    m = re.fullmatch(r"انتقال\s+روب\s+پوینت\s+([0-9,]+)", text)
    if m:
        context.user_data["transfer_amount"] = m.group(1)
        await transfer_command(update, context); return


async def persian_slash_router(update, context):
    """
    Telegram/Python-Telegram-Bot فقط command name های لاتین/ASCII را
    برای CommandHandler قبول می‌کند. بنابراین /روباه و سایر دستورهای
    فارسی را با MessageHandler پردازش می‌کنیم تا Railway موقع startup کرش نکند.
    """
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    # @BotUsername در انتهای command در گروه‌ها مجاز است.
    m = re.fullmatch(r"/(روباه|روبی|روباهیو|شکار|یخچال)(?:@\w+)?", text)
    if m:
        cmd = m.group(1)
        if cmd in {"روباه", "روبی", "روباهیو"}:
            await fox_command(update, context)
        elif cmd == "شکار":
            await hunt_command(update, context)
        else:
            await fridge_command(update, context)
        return

    # /انتقال روب پوینت 50 — انتقال همچنان فقط با Reply انجام می‌شود.
    m = re.fullmatch(r"/انتقال(?:@\w+)?(?:\s+روب\s+پوینت)?\s+([0-9,]+)", text)
    if m:
        context.user_data["transfer_amount"] = m.group(1)
        await transfer_command(update, context)


def main():
    if not BOT_TOKEN: raise RuntimeError('BOT_TOKEN is missing. Add BOT_TOKEN in Railway Variables.')
    init_db()
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start_command))
    app.add_handler(CommandHandler("profile",profile_command))
    app.add_handler(CommandHandler("games",games_command))
    app.add_handler(CommandHandler("game",game_command))
    app.add_handler(CommandHandler("challenge",challenge_command))
    app.add_handler(CommandHandler("admin",admin_command))
    app.add_handler(CommandHandler("transfer",transfer_command))
    app.add_handler(CommandHandler("hunt",hunt_command))
    app.add_handler(CommandHandler("fox",fox_command))
    app.add_handler(CallbackQueryHandler(membership_callback,pattern=r"^check_membership$"))
    app.add_handler(CallbackQueryHandler(admin_callback,pattern=r"^admin:(stats|users|broadcast|addpoints|setlevel|setfoxpoints)$"))
    app.add_handler(CallbackQueryHandler(accept_challenge,pattern=r"^accept:\d+$"))
    app.add_handler(CallbackQueryHandler(throw_dice,pattern=r"^throw:\d+:[12]$"))
    app.add_handler(CallbackQueryHandler(fox_button,pattern=r"^fox:(collect|upgrade|hunt|fridge|rename):\d+$"))
    app.add_handler(CallbackQueryHandler(hunt_button,pattern=r"^hunt:(feed|sell|fridge):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(transfer_button,pattern=r"^transfer:(yes|no):\d+:\d+:\d+$"))
    # دستورهای فارسی با MessageHandler ثبت می‌شوند؛ CommandHandler آن‌ها را رد می‌کند.
    app.add_handler(MessageHandler(filters.Regex(r"^/(?:روباه|روبی|روباهیو|شکار|یخچال)(?:@\w+)?$") | filters.Regex(r"^/انتقال(?:@\w+)?(?:\s+روب\s+پوینت)?\s+[0-9,]+$"), persian_slash_router), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=list(ADMIN_IDS)),admin_text),group=0)
    app.add_handler(MessageHandler(filters.Regex(rf"^{re.escape(CLAIM_KEYWORD)}$"),claim_points),group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router),group=2)
    logger.info("Bot started polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
