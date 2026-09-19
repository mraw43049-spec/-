import asyncio
import io
import json
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile, InputMediaPhoto
from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
from telegram.ext import (
    ApplicationBuilder, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ChatMemberHandler,
    ContextTypes, MessageHandler, filters
)

from config import (
    ADMIN_IDS, BOT_TOKEN, CLAIM_COOLDOWN_SECONDS, CLAIM_KEYWORD, REFERRAL_REWARD,
    CLAIM_POINTS_MAX, CLAIM_POINTS_MIN, REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL,
    REQUIRED_CHANNEL_2, REQUIRED_CHANNEL_2_URL, DATABASE_URL
)
from database import (
    Challenge, FoxHunt, GroupChat, InjuredFox, User, BankAccount, BankTransaction, RubyTable, RubySmuggling, JailWallMemory,
    FootballMatch, FootballPrediction, GiftOrder, FactoryOrder, FactoryInventory, MarketPrice, Referral, PointsPurchase, get_session, init_db
)
from game_logic import (
    GAME_EMOJIS, GAME_NAMES_FA, HUNT_ITEMS, fox_level_reward,
    fox_production_interval, fox_production_per_second, fox_rank, fox_upgrade_cost, fox_storage_capacity, get_level_for_points,
    get_unlocked_games, points_to_next_level, points_needed_for_level,
    FRIDGE_UNLOCK_LEVEL, FRIDGE_MAX_LEVEL, fridge_capacity, fridge_upgrade_cost, fridge_cook_seconds,
    FACTORY_UNLOCK_LEVEL, FACTORY_BUILD_COST, FACTORY_BUILD_SECONDS, FACTORY_STORAGE_MAX_LEVEL,
    FACTORY_MACHINE_MAX_LEVEL, FACTORY_WORKERS_MAX_LEVEL, FACTORY_TIERS, FACTORY_TIERS_BY_KEY,
    FACTORY_ITEM_INDEX, factory_storage_capacity, factory_machine_hours_for_100, factory_workers_capacity,
    factory_upgrade_cost, factory_unlocked_tiers, factory_order_plan,
    FACTORY_MARKET_UPDATE_SECONDS, factory_market_roll_price
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

FOX_UNLOCK_LEVEL = 3
FOX_MAX_LEVEL = 25
FOX_HUNGER_INTERVAL_SECONDS = 25 * 60  # هر ۲۵ دقیقه یک واحد غذا از شکم روباه کم می‌شود.
INJURED_FOX_INTERVAL = 20 * 60
INJURED_FOX_COST = 10
INJURED_FOX_REWARD_MIN = 200
INJURED_FOX_REWARD_MAX = 2000
INJURED_FOX_MAX_CLAIMS = 5
INJURED_FOX_EVENT_TIMEOUT = 3 * 60
FOX_CLAIM_COOLDOWN = 5 * 60
HUNT_COOLDOWN = 15 * 60
HUNT_DECISION_TIMEOUT = 120
TRANSFER_COOLDOWN = 60
BANK_CARD_TRANSFER_COOLDOWN = 5 * 60
BANK_CARD_TRANSFER_FEE_RATE = 0.05
TRANSFER_MAX = 500_000
WHEEL_COOLDOWN = 24 * 60 * 60
WHEEL_REWARDS = [100, 250, 350, 450, 0, 500, 750, 1000]
WHEEL_LABELS = ['100 روب پوینت', '250 روب پوینت', '350 روب پوینت', '450 روب پوینت', 'پوچ', '500 روب پوینت', '750 روب پوینت', '1000 روب پوینت']
RUBY_MAX_ENTRY = 3_000_000
BACKUP_INTERVAL_SECONDS = 24 * 60 * 60  # هر ۲۴ ساعت یک بکاپ خودکار برای ادمین‌ها فرستاده می‌شود

# ---------- مریضی روباه ----------
FOX_SICK_UNLOCK_LEVEL = 6
FOX_SICK_INTERVAL_SECONDS = 48 * 60 * 60  # هر ۴۸ ساعت یک‌بار روباه مریض می‌شود.
FOX_SICK_REASONS = ["سرماخوردگی", "خوردن غذای فاسد", "خستگی بیش از حد", "سرمازدگی توی جنگل", "دل‌درد ناگهانی"]
FOX_PILL_COST = 5000
FOX_PILL_INTERVAL_SECONDS = 3 * 60
FOX_PILL_DOSES_NEEDED = 3
FOX_SYRUP_COST = 10000
FOX_SYRUP_INTERVAL_SECONDS = 60
FOX_SYRUP_DOSES_NEEDED = 3
FOX_REST_DURATION_SECONDS = 60 * 60

# ---------- قاچاق روباهیو ----------
SMUGGLING_UNLOCK_LEVEL = 8
SMUGGLING_MIN = 3
SMUGGLING_MAX = 15
SMUGGLING_PRICE_PER_FOX = 5000
SMUGGLING_BASE_SECONDS = 60 * 60
SMUGGLING_EXTRA_PER_FOX = 20 * 60
SMUGGLING_FINE = 25000
SMUGGLING_JAIL_SECONDS = 60 * 60
SPAM_WINDOW_SECONDS = 10
SPAM_MESSAGE_LIMIT = 6
SPAM_JAIL_SECONDS = 15 * 60
SPAM_FINE = 750

# ---------- کارخونه روبی ----------
FACTORY_PERCENT_OPTIONS = [25, 50, 75, 100]

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


FA_DIGITS_TABLE = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_fa_digits(value):
    return str(value).translate(FA_DIGITS_TABLE)


def gregorian_to_jalali(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد تقویم جلالی)."""
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no += gd2
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm, jd = 12, j_day_no + 1
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i + 1
            jd = j_day_no + 1
            break
        j_day_no -= j_days_in_month[i]
    return jy, jm, jd


def tehran_dt(dt):
    """زمان یو‌تی‌سی را به وقت محلی تهران (UTC+3:30) می‌برد."""
    base = aware(dt) if dt is not None else now_utc()
    return base + timedelta(hours=3, minutes=30)


def jalali_datetime_str(dt):
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return to_fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}  {dt.hour:02d}:{dt.minute:02d}")


def mask_telegram_id(uid):
    s = str(uid)
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def reply_kwargs(message):
    # پاسخ همیشه به پیام همان کاربر متصل می‌شود.
    return {"reply_to_message_id": message.message_id}

# ---------- عضویت اجباری ----------

REQUIRED_CHANNELS = [
    (REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL, "📢 عضویت در کانال اصلی"),
    (REQUIRED_CHANNEL_2, REQUIRED_CHANNEL_2_URL, "🎁 عضویت در کانال هدایا"),
]

async def is_member(bot, user_id: int, channel=None) -> bool:
    channel = channel or REQUIRED_CHANNEL
    try:
        m = await bot.get_chat_member(channel, user_id)
        return m.status in ("member", "administrator", "creator") or bool(getattr(m, "is_member", False))
    except Exception as e:
        logger.warning("Membership check failed for %s: %s", channel, e)
        return False


async def is_member_all(bot, user_id: int) -> bool:
    for channel, _url, _label in REQUIRED_CHANNELS:
        if not channel:
            continue
        if not await is_member(bot, user_id, channel):
            return False
    return True


def join_keyboard():
    rows = [[InlineKeyboardButton(label, url=url)] for channel, url, label in REQUIRED_CHANNELS if channel]
    rows.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_membership")])
    return InlineKeyboardMarkup(rows)


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # هر زمان ربات یک پیام/دستور از گروه دریافت کرد، گروه را برای رویدادهای دوره‌ای ثبت کن.
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        session = get_session()
        try:
            row = session.get(GroupChat, update.effective_chat.id)
            if row is None:
                row = GroupChat(chat_id=update.effective_chat.id, title=update.effective_chat.title or "گپ", active=1)
                session.add(row)
            else:
                row.active = 1
                row.title = update.effective_chat.title or row.title
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
    user = update.effective_user
    if user is None:
        return False
    if user.id in ADMIN_IDS:
        return True
    if await is_member_all(context.bot, user.id):
        return True
    text = "🔒 برای استفاده از ربات اول باید عضو کانال‌های زیر بشی.\n\nبعد از عضویت روی «عضو شدم، بررسی کن» بزن."
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

def user_level_requirement(level):
    """تعداد روب‌روب تجمعی لازم برای رسیدن به هر سطح کاربر."""
    level = max(1, int(level))
    req = {
        1: 0, 2: 5, 3: 15, 4: 40, 5: 70, 6: 115, 7: 175, 8: 250,
        9: 350, 10: 500, 11: 700, 12: 950, 13: 1250, 14: 1650,
        15: 2150, 16: 2600, 17: 3600, 18: 4600, 19: 5800, 20: 7250,
    }
    if level <= 20:
        return req[level]
    # ادامه نامحدود بعد از سطح 20 با رشد تدریجی.
    value = req[20]
    step = 900
    for lv in range(21, level + 1):
        value += step
        step += 250
    return value

def user_level_from_roobrub(count):
    count=max(0,int(count or 0))
    level=1
    while user_level_requirement(level+1)<=count:
        level+=1
    return level

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
            fox_belly_capacity=3,
            fox_points=0,
            fox_storage=0,
            fox_total_earned=0,
            fox_production_remainder=0.0,
        fox_claim_count=0, hunt_count=0, fox_rescued_count=0, fox_prestige_count=0,
            fox_last_hunger_at=now_utc(),
            wheel_last_spin_at=None,
            wheel_last_reward=None,
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
        if user.fox_belly_capacity is None or user.fox_belly_capacity < 3:
            user.fox_belly_capacity = max(3, int(user.fox_belly or 3)); changed = True
        if user.fox_points is None:
            user.fox_points = 0; changed = True
        if user.fox_storage is None:
            user.fox_storage = 0; changed = True
        if user.fox_total_earned is None:
            user.fox_total_earned = 0; changed = True
        if user.fox_production_remainder is None:
            user.fox_production_remainder = 0.0; changed = True
        if user.fox_claim_count is None: user.fox_claim_count = 0; changed = True
        if user.hunt_count is None: user.hunt_count = 0; changed = True
        if user.fox_rescued_count is None: user.fox_rescued_count = 0; changed = True
        if user.fox_prestige_count is None: user.fox_prestige_count = 0; changed = True
        if user.fox_last_hunger_at is None: user.fox_last_hunger_at = now_utc(); changed = True
        if not hasattr(user, 'wheel_last_spin_at'): pass
        if user.wheel_last_reward is None: user.wheel_last_reward = None
        calculated = user_level_from_roobrub(user.fox_claim_count or 0)
        if user.level != calculated:
            user.level = calculated; changed = True
        if changed:
            session.commit()
    return user


def get_or_create_user_by_id(session, telegram_id):
    """برای مواردی که فقط آیدی عددی کاربر داریم و آبجکت تلگرامش رو نداریم (مثلاً گیرنده روب پوینت)."""
    user = session.get(User, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=None,
            first_name=None,
            points=0,
            total_earned=0,
            level=1,
            fox_name="مکار",
            fox_level=1,
            fox_belly=3,
            fox_belly_capacity=3,
            fox_points=0,
            fox_storage=0,
            fox_total_earned=0,
            fox_production_remainder=0.0,
            fox_claim_count=0, hunt_count=0, fox_rescued_count=0, fox_prestige_count=0,
            fox_last_hunger_at=now_utc(),
            wheel_last_spin_at=None,
            wheel_last_reward=None,
        )
        session.add(user)
        session.commit()
    return user


def add_points(session, user, amount):
    user.points = max(0, user.points + amount)
    if amount > 0:
        user.total_earned += amount
    old = user.level
    user.level = user_level_from_roobrub(user.fox_claim_count or 0)
    return old, user.level


def apply_level_rewards(session, user, old_level, new_level):
    """جایزه روب‌پوینت هر لول؛ فقط برای لول‌های جدید و حداکثر تا 35."""
    rewards = []
    if new_level <= old_level:
        return rewards
    start = max(2, old_level + 1)
    end = new_level
    for lvl in range(start, end + 1):
        reward = fox_level_reward(lvl)
        user.fox_points += reward
        rewards.append((lvl, reward))
    return rewards

# ---------- مریضی روباه ----------

def clear_fox_sickness(user):
    user.fox_sick_since = None
    user.fox_sick_reason = None
    user.fox_sick_treatment = None
    user.fox_sick_doses_given = 0
    user.fox_sick_next_dose_at = None
    user.fox_sick_rest_until = None


def _start_fox_sickness(user, now):
    user.fox_sick_since = now
    user.fox_sick_reason = random.choice(FOX_SICK_REASONS)
    user.fox_sick_treatment = None
    user.fox_sick_doses_given = 0
    user.fox_sick_next_dose_at = None
    user.fox_sick_rest_until = None
    user.fox_last_sick_at = now


def sync_fox_sickness(user):
    """وضعیت مریضی روباه رو با گذر زمان به‌روز می‌کنه: اگه استراحتش تموم شده خودش خوب می‌شه،
    همون لحظه‌ای که کاربر برای اولین بار لول 6 بشه روباه مریض می‌شه، و از اون به بعد هر بار
    که خوب بشه، دقیقاً 48 ساعت بعد دوباره مریض می‌شه (این چرخه تا آخر ادامه داره).
    مقدار برگشتی یعنی چیزی تغییر کرده یا نه."""
    if (user.level or 1) < FOX_SICK_UNLOCK_LEVEL:
        return False
    now = now_utc()
    if user.fox_sick_since:
        if user.fox_sick_treatment == 'rest' and user.fox_sick_rest_until and now >= aware(user.fox_sick_rest_until):
            clear_fox_sickness(user)
            user.fox_last_sick_at = now
            return True
        return False
    last = aware(user.fox_last_sick_at)
    if last is None:
        # اولین باری که کاربر به لول 6 می‌رسه، همون لحظه روباه مریض می‌شه.
        _start_fox_sickness(user, now)
        return True
    if (now - last).total_seconds() >= FOX_SICK_INTERVAL_SECONDS:
        _start_fox_sickness(user, now)
        return True
    return False


def fox_sickness_message(user):
    reason = user.fox_sick_reason or "یه دلیل نامعلوم"
    progress = ""
    if user.fox_sick_treatment in ('pill', 'syrup'):
        needed = FOX_PILL_DOSES_NEEDED if user.fox_sick_treatment == 'pill' else FOX_SYRUP_DOSES_NEEDED
        label = "💊 قرص" if user.fox_sick_treatment == 'pill' else "🧴 شربت"
        given = int(user.fox_sick_doses_given or 0)
        progress = f"\n\n✅ تا الان {given}/{needed} بار {label} دادی."
    elif user.fox_sick_treatment == 'rest':
        remaining = max(0, int((aware(user.fox_sick_rest_until) - now_utc()).total_seconds())) if user.fox_sick_rest_until else 0
        progress = f"\n\n🛌 روباهت خوابیده؛ {format_duration(remaining)} دیگه خودش خوب می‌شه."
    return (
        f"🤒 روباهت به‌خاطر {reason} مریض شده و تا خوب نشه هیچ کاری نمی‌تونه انجام بده!\n\n"
        f"💊 قرص — {FOX_PILL_COST:,} روب‌پوینت هر بار؛ هر {FOX_PILL_INTERVAL_SECONDS//60} دقیقه یک‌بار، {FOX_PILL_DOSES_NEEDED} بار پشت‌سرهم بده تا خوب بشه.\n"
        f"🧴 شربت — {FOX_SYRUP_COST:,} روب‌پوینت هر بار؛ هر {FOX_SYRUP_INTERVAL_SECONDS} ثانیه یک‌بار، {FOX_SYRUP_DOSES_NEEDED} بار پشت‌سرهم بده تا خوب بشه.\n"
        f"🛌 استراحت — رایگان؛ روباه {FOX_REST_DURATION_SECONDS//3600} ساعت می‌خوابه و بعدش خودش خوب می‌شه.\n\n"
        "یکی از گزینه‌ها رو انتخاب کن ⬇️"
        + progress
    )


def fox_sickness_keyboard(owner_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💊 دادن قرص", callback_data=f"foxsick:pill:{owner_id}")],
        [InlineKeyboardButton("🧴 دادن شربت", callback_data=f"foxsick:syrup:{owner_id}")],
        [InlineKeyboardButton("🛌 استراحت کردن", callback_data=f"foxsick:rest:{owner_id}")],
    ])


async def guard_fox_sickness(update, context, session, user):
    """اگه روباه مریضه، پیام درمان رو نشون می‌ده و True برمی‌گردونه (یعنی کار دیگه‌ای انجام نشه)."""
    if sync_fox_sickness(user):
        session.commit()
    if not user.fox_sick_since:
        return False
    if update.message:
        await update.message.reply_text(
            fox_sickness_message(user), reply_markup=fox_sickness_keyboard(update.effective_user.id), **reply_kwargs(update.message)
        )
    elif update.callback_query:
        await update.callback_query.answer("🤒 روباهت مریضه؛ اول درمانش کن.", show_alert=True)
    return True


async def fox_sickness_button(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 3: return
    _, choice, owner_s = parts
    owner_id = int(owner_s)
    if q.from_user.id != owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.", show_alert=True); return
    if not await require_membership(update, context): return
    session = get_session()
    try:
        user = get_or_create_user(session, q.from_user)
        sync_fox_sickness(user)
        if not user.fox_sick_since:
            session.commit()
            await q.answer("🎉 روباهت از قبل خوب شده!", show_alert=True)
            try:
                await q.message.edit_text("🎉 روباهت خوبه و آماده‌ی کاره!", reply_markup=None)
            except Exception:
                pass
            return
        now = now_utc()
        if user.fox_sick_treatment and user.fox_sick_treatment != choice:
            cur_label = {"pill": "💊 قرص", "syrup": "🧴 شربت", "rest": "🛌 استراحت"}.get(user.fox_sick_treatment, "؟")
            await q.answer(f"❌ قبلاً درمان {cur_label} رو شروع کردی؛ باید همون رو ادامه بدی.", show_alert=True); return
        if choice == 'rest':
            user.fox_sick_treatment = 'rest'
            user.fox_sick_rest_until = now + timedelta(seconds=FOX_REST_DURATION_SECONDS)
            session.commit()
            await q.answer("🛌 روباهت خوابید.")
            try:
                await q.message.edit_text(
                    f"🛌 روباهت به‌خاطر {user.fox_sick_reason} رفت بخوابه.\n"
                    f"⏱ بعد از {format_duration(FOX_REST_DURATION_SECONDS)} خودش خوب می‌شه؛ تا اون‌موقع صبر کن.",
                    reply_markup=None
                )
            except Exception:
                pass
            return
        if choice in ('pill', 'syrup'):
            cost = FOX_PILL_COST if choice == 'pill' else FOX_SYRUP_COST
            interval = FOX_PILL_INTERVAL_SECONDS if choice == 'pill' else FOX_SYRUP_INTERVAL_SECONDS
            doses_needed = FOX_PILL_DOSES_NEEDED if choice == 'pill' else FOX_SYRUP_DOSES_NEEDED
            next_at = aware(user.fox_sick_next_dose_at)
            if next_at and now < next_at:
                remaining = int((next_at - now).total_seconds())
                await q.answer(f"⏳ {format_duration(remaining)} دیگه صبر کن تا بتونی دوباره بدی.", show_alert=True); return
            if (user.fox_points or 0) < cost:
                await q.answer(f"❌ روب‌پوینت کافی نداری؛ {cost:,} لازمه.", show_alert=True); return
            user.fox_points -= cost
            user.fox_sick_treatment = choice
            user.fox_sick_doses_given = int(user.fox_sick_doses_given or 0) + 1
            user.fox_sick_next_dose_at = now + timedelta(seconds=interval)
            cured = user.fox_sick_doses_given >= doses_needed
            label = "💊 قرص" if choice == 'pill' else "🧴 شربت"
            if cured:
                clear_fox_sickness(user)
                user.fox_last_sick_at = now
            session.commit()
            if cured:
                await q.answer("🎉 روباهت خوب شد!")
                try:
                    await q.message.edit_text(f"{label} رو دادی و روباهت کامل خوب شد! 🎉", reply_markup=None)
                except Exception:
                    pass
            else:
                remain = doses_needed - user.fox_sick_doses_given
                await q.answer(f"{label} دادی؛ {remain} بار دیگه مونده.")
                try:
                    await q.message.edit_text(fox_sickness_message(user), reply_markup=fox_sickness_keyboard(owner_id))
                except Exception:
                    pass
            return
    finally:
        session.close()

# ---------- زندان روبی و قاچاق روباهیو ----------
def _jail_time_left(user):
    if not user.jail_until:
        return 0
    return max(0, int((aware(user.jail_until) - now_utc()).total_seconds()))


def jail_duration_text(seconds):
    seconds=max(0,int(seconds))
    m,s=divmod(seconds,60); h,m=divmod(m,60)
    if h: return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def jail_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ نوشتن خاطره", callback_data=f"jail:memory:{user_id}")],
        [InlineKeyboardButton("💸 پرداخت جریمه", callback_data=f"jail:pay:{user_id}")],
    ])


def jail_wall_memory_text(session, user):
    row=session.query(JailWallMemory).filter(JailWallMemory.author_id != user.telegram_id).order_by(JailWallMemory.created_at.desc()).first()
    if row:
        memory=row.text
        author=f"{row.author_id}"
    else:
        memory="هنوز خاطره‌ای از روباه‌های دیگر روی دیوار نوشته نشده."
        author="—"
    arrested=jalali_datetime_str(tehran_dt(user.jail_arrested_at)) if user.jail_arrested_at else "—"
    total=session.query(User).filter(User.jail_until != None).count()
    left=_jail_time_left(user)
    return (\
        "🦊 زندان روبی ⛓️\\n\\n"
        "🚨 شما روباه بدی بودین و زندانی شدید ❗️\\n\\n"
        f"📝 دلیل حبس : {user.jail_reason or 'تخلف در روباهیو'}\\n"
        f"⏳ مدت حبس : {jail_duration_text(left)}\\n"
        f"🏦 جریمه نقدی : {int(user.jail_fine or 0):,} روب‌پوینت 🪙\\n"
        "┘─ میتونید با پرداخت جریمه از زندان آزاد شوید\\n\\n"
        f"👮 دستگیر شده در : {arrested}\\n\\n"
        f"👥 تعداد کل زندانیان : {total}\\n\\n"
        "✏️ خاطرات نوشته شده روی دیوار سلول\\n"
        f"✍️ خاطره : {memory}\\n"
        f"┘─ نوشته شده توسط : {author}"
    ).replace("\\n", "\n")


def free_jail_text():
    return "🦊 زندان روبی ⛓️\\n\\n😇 شما روباهی ناناز و خوبی هستی!\\nآزادانه و بدون هیچ مشکلی زندانی نیستی، پس با خیال راحت روب روب کن!".replace("\\n", "\n")


async def jail_command(update, context):
    if not await require_membership(update, context): return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if not await _active_jail(session,user):
            await update.message.reply_text(free_jail_text(), **reply_kwargs(update.message)); return
        text=jail_wall_memory_text(session,user)
        kb=jail_keyboard(user.telegram_id)
    finally: session.close()
    await update.message.reply_text(text,reply_markup=kb,**reply_kwargs(update.message))


async def jail_button(update,context):
    q=update.callback_query
    parts=(q.data or '').split(':')
    if len(parts)!=3: return
    action=parts[1]; owner_id=int(parts[2])
    if q.from_user.id!=owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.",show_alert=True); return
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user)
        if not await _active_jail(session,user):
            await q.answer("😇 دیگر زندانی نیستی.",show_alert=True); return
        if action=='memory':
            context.user_data['jail_memory_wait']=True
            await q.answer()
            await q.message.reply_text("✏️ خاطره‌ای کوتاه برای دیوار زندان بنویس؛ خاطره‌ات برای یک زندانی دیگر نمایش داده می‌شود.")
            return
        if action=='pay':
            fine=int(user.jail_fine or 0)
            if int(user.fox_points or 0)<fine:
                await q.answer(f"❌ روب‌پوینت کافی نداری. جریمه: {fine:,}",show_alert=True); return
            user.fox_points-=fine
            user.jail_until=None; user.jail_reason=None; user.jail_fine=0; user.jail_arrested_at=None
            session.commit()
            await q.answer("✅ جریمه پرداخت شد و آزاد شدی!")
            await q.message.edit_text(free_jail_text())
    finally: session.close()


async def handle_jail_memory_text(update,context):
    if not update.message or not update.message.text or not context.user_data.get('jail_memory_wait'):
        return False
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if not await _active_jail(session,user):
            context.user_data.pop('jail_memory_wait',None); return False
        text=update.message.text.strip()
        if len(text)<2 or len(text)>300:
            await update.message.reply_text("❌ خاطره باید بین ۲ تا ۳۰۰ کاراکتر باشد.",**reply_kwargs(update.message)); return True
        session.add(JailWallMemory(author_id=user.telegram_id,text=text,created_at=now_utc()))
        session.commit(); context.user_data.pop('jail_memory_wait',None)
        await update.message.reply_text("✍️ خاطره‌ات روی دیوار سلول نوشته شد. برای یک زندانی دیگر نمایش داده می‌شود.",**reply_kwargs(update.message))
        return True
    finally: session.close()


async def complete_smuggling(session, record):
    if record.status!='pending' or now_utc() < aware(record.completes_at): return None
    user=session.get(User,record.user_id)
    if not user:
        record.status='success'; record.reward=0; session.commit(); return None
    if random.random()*100 < float(record.risk_percent):
        record.status='caught'; record.reward=0
        user.jail_until=now_utc()+timedelta(seconds=SMUGGLING_JAIL_SECONDS)
        user.jail_reason='قاچاق کردن روباه های بی گناه'
        user.jail_fine=SMUGGLING_FINE
        user.jail_arrested_at=now_utc()
        session.commit()
        return ('caught',user,record)
    reward=int(record.count)*SMUGGLING_PRICE_PER_FOX
    record.status='success'; record.reward=reward
    user.fox_points=int(user.fox_points or 0)+reward
    session.commit()
    return ('success',user,record)


async def settle_all_smuggling(context):
    session=get_session()
    try:
        rows=session.query(RubySmuggling).filter(RubySmuggling.status=='pending',RubySmuggling.completes_at<=now_utc()).all()
        for row in rows:
            result=await complete_smuggling(session,row)
            if result:
                status,user,record=result
                try:
                    if status=='success':
                        await context.bot.send_message(user.telegram_id,f"🦊 قاچاق روباهیو با موفقیت انجام شد!\\n\\n🥩 {record.count} روباه به کباب تبدیل شدند.\\n💰 پاداش: +{record.reward:,} روب‌پوینت 🪙")
                    else:
                        await context.bot.send_message(user.telegram_id,"🚨 قاچاق روباهیو لو رفت!\\n\\n⛓️ توسط گرگ‌های پلیس دستگیر شدی و به زندان روبی افتادی. برای دیدن سلولت بنویس «زندان روبی».")
                except Exception: pass
    finally: session.close()


def smuggling_status_text(user,record):
    left=max(0,int((aware(record.completes_at)-now_utc()).total_seconds()))
    return (f"🦊 قاچاق روباهیو 🥷\\n\\n✨ تعداد روباه های قاچاقی : {record.count} / {SMUGGLING_MAX}\\n"
            f"🩹 تعداد کل روباه های زخمی : {int(user.injured_fox_stock or 0)}\\n\\n"
            f"⏳ زمان باقی‌مانده : {jail_duration_text(left)}\\n\\n🚨 ریسک گیر افتادن : {record.risk_percent:.2f}%\\n"
            "┘─ ❓ اگه گیر بیوفتی، میوفتی زندان و هیچی گیرت نمیاد").replace("\\n", "\n")


def smuggling_select_text(user,count):
    risk=count*5
    duration=SMUGGLING_BASE_SECONDS+(count-SMUGGLING_MIN)*SMUGGLING_EXTRA_PER_FOX
    return (f"🦊 قاچاق روباهیو 🥷\\n\\n✨ تعداد روباه های قاچاقی : {count} / {SMUGGLING_MAX}\\n"
            f"🩹 تعداد کل روباه های زخمی : {int(user.injured_fox_stock or 0)}\\n\\n"
            f"⏳ زمان مورد نیاز قاچاق : {jail_duration_text(duration)}\\n\\n"
            f"🚨 ریسک گیر افتادن : {risk:.2f}%\\n"
            "┘─ ❓ اگه گیر بیوفتی، میوفتی زندان و هیچی گیرت نمیاد\\n\\n"
            "➕ جهت افزودن تعداد روباه های قاچاقی\\n➖ جهت کاهش تعداد روباه های قاچاقی\\n➰ جهت افزودن تمامی روباه های قاچاقی").replace("\\n", "\n")


def smuggling_keyboard(user_id,count):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕",callback_data=f"smuggle:plus:{user_id}:{count}"),InlineKeyboardButton("➖",callback_data=f"smuggle:minus:{user_id}:{count}"),InlineKeyboardButton("➰",callback_data=f"smuggle:all:{user_id}:{count}")],
        [InlineKeyboardButton("✅ تایید قاچاق",callback_data=f"smuggle:confirm:{user_id}:{count}")],
    ])


async def smuggling_command(update,context):
    if not await require_membership(update,context): return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if user.level<SMUGGLING_UNLOCK_LEVEL:
            await update.message.reply_text(f"🔒 قاچاق روبی از سطح {SMUGGLING_UNLOCK_LEVEL} باز می‌شود.\\n⭐ سطح فعلی تو: {user.level}".replace("\\n","\n"),**reply_kwargs(update.message)); return
        pending=session.query(RubySmuggling).filter(RubySmuggling.user_id==user.telegram_id,RubySmuggling.status=='pending').order_by(RubySmuggling.id.desc()).first()
        if pending:
            result=await complete_smuggling(session,pending)
            if result:
                status,_,rec=result
                if status=='success':
                    await update.message.reply_text(f"🦊 قاچاق روباهیو تمام شد!\\n\\n🥩 {rec.count} روباه قاچاق شد.\\n💰 پاداش: +{rec.reward:,} روب‌پوینت 🪙".replace("\\n","\n"),**reply_kwargs(update.message))
                else:
                    await update.message.reply_text("🚨 گیر افتادی!\\n\\n⛓️ به زندان روبی افتادی. برای دیدن سلولت بنویس «زندان روبی».".replace("\\n","\n"),**reply_kwargs(update.message))
                return
            await update.message.reply_text(smuggling_status_text(user,pending),**reply_kwargs(update.message)); return
        stock=int(user.injured_fox_stock or 0)
        if stock<SMUGGLING_MIN:
            await update.message.reply_text(f"🩹 فقط {stock} روباه زخمی آماده برای قاچاق داری.\\n❌ حداقل {SMUGGLING_MIN} روباه لازم است.".replace("\\n","\n"),**reply_kwargs(update.message)); return
        count=SMUGGLING_MIN
        await update.message.reply_text(smuggling_select_text(user,count),reply_markup=smuggling_keyboard(user.telegram_id,count),**reply_kwargs(update.message))
    finally: session.close()


async def smuggling_button(update,context):
    q=update.callback_query
    parts=(q.data or '').split(':')
    if len(parts)!=4:return
    _,action,owner_s,count_s=parts; owner_id=int(owner_s); count=int(count_s)
    if q.from_user.id!=owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.",show_alert=True);return
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user)
        if user.level<SMUGGLING_UNLOCK_LEVEL:
            await q.answer("🔒 این بخش از سطح ۸ باز می‌شود.",show_alert=True);return
        if session.query(RubySmuggling).filter(RubySmuggling.user_id==owner_id,RubySmuggling.status=='pending').first():
            await q.answer("⏳ یک قاچاق در حال انجام داری.",show_alert=True);return
        stock=int(user.injured_fox_stock or 0)
        if action in ('plus','minus','all'):
            if action=='plus': count=min(SMUGGLING_MAX,count+1)
            elif action=='minus': count=max(SMUGGLING_MIN,count-1)
            else: count=min(SMUGGLING_MAX,stock)
            await q.answer()
            await q.message.edit_text(smuggling_select_text(user,count),reply_markup=smuggling_keyboard(owner_id,count));return
        if action=='confirm':
            if count<SMUGGLING_MIN or count>SMUGGLING_MAX or count>stock:
                await q.answer("❌ تعداد روباه کافی نیست یا خارج از محدوده است.",show_alert=True);return
            duration=SMUGGLING_BASE_SECONDS+(count-SMUGGLING_MIN)*SMUGGLING_EXTRA_PER_FOX
            started=now_utc(); complete=started+timedelta(seconds=duration)
            user.injured_fox_stock=stock-count
            rec=RubySmuggling(user_id=owner_id,count=count,risk_percent=count*5,duration_seconds=duration,started_at=started,completes_at=complete,status='pending',created_at=started)
            session.add(rec);session.commit()
            await q.answer("🥷 قاچاق شروع شد!")
            await q.message.edit_text(smuggling_status_text(user,rec))
    finally: session.close()

# ---------- پروفایل و منو ----------


# حداقل تعداد اعضای گروه برای اینکه ربات در گروه فعال بماند.
MIN_GROUP_MEMBERS = 20

# فهرست یکپارچه‌ی راهنما؛ هم در پیام خوش‌آمدگویی و هم در دکمه‌های راهنمای کامل استفاده می‌شود.
GUIDE_TOPICS = [
    ("💰 روب روب / هور هور / عو عو", "هر ۵ دقیقه یک‌بار برای دریافت روب‌پوینت؛ از لول ۱ فعال است."),
    ("🏹 شکار", "از لول ۲ فعال است؛ هر ۱۵ دقیقه یک شکار و ۱۲۰ ثانیه برای تصمیم‌گیری."),
    ("🦊 روباه / روبی / روباهیو", "از لول ۳ فعال است؛ پنل روباه، تولید روب‌پوینت، ارتقا و تغییر نام."),
    ("🎮 بازی روبی", "از لول ۳ فعال است؛ منوی بازی‌های روبی و ساخت میز بازی."),
    ("🏦 بانک / بانک روبی", "از لول ۴ فعال است؛ افتتاح حساب و مدیریت بانک."),
    ("🃏 کازینو روبی", "از لول ۵ فعال است؛ منوی قمارهای روبی و ساخت میز."),
    ("👤 روبام / روباش", "پروفایل روبی خودت یا کاربری که روی پیامش ریپلای کرده‌ای."),
    ("🏆 لیدر برد", "رتبه‌بندی ۱۰۰ نفر برتر در بخش‌های روب‌پوینت، روباه زخمی، شکار و روب روب."),
    ("🎡 گردونه / چرخ شانس", "روزی یک‌بار؛ جایزه به‌صورت تصادفی انتخاب می‌شود."),
    ("🥷 قاچاق روباهیو", "از لول ۸ فعال است؛ ۳ تا ۱۵ روباه زخمی را قاچاق کن. هر روباه ۵٬۰۰۰ روب‌پوینت ارزش دارد؛ ریسک و زمان با تعداد روباه‌ها بیشتر می‌شود."),
    ("⛓️ زندان روبی", "اگر در قاچاق گیر بیفتی یا اسپم شدید کنی، موقتاً زندانی می‌شوی. در زندان فقط پنل زندان، خاطره و پرداخت جریمه فعال است."),
    ("➕ افزودن ربات به گروه", f"فقط گروه‌های بالای {MIN_GROUP_MEMBERS} عضو قابل قبولن؛ در غیر این صورت روباهیو خودش از گروه خارج می‌شه."),
]


def welcome_text():
    return (
        "به دنیای روباهیو خوش اومدی 🦊\n\n"
        "من یه روباه بازیگوشم که میام توی گروهت زندگی می‌کنم؛ "
        "بچه‌های گروه با نوشتن «روب روب» بهم غذا می‌دن، روب‌پوینت جمع می‌کنن، "
        "می‌رن شکار، بازی‌های گروهی راه می‌ندازن و برای رتبه‌ی اول توی لیدربرد رقابت می‌کنن.\n\n"
        "🐾 چیزهایی که می‌تونی توی گروهت باهام تجربه کنی:\n"
        "• جمع کردن روب‌پوینت و بالا رفتن لول\n"
        "• داشتن روباه شخصی خودت، تغذیه و ارتقاش\n"
        "• رفتن به شکار و نجات روباه‌های زخمی\n"
        "• بازی‌های گروهی (دوز، سنگ‌کاغذقیچی، دارت، بسکتبال، بولینگ)\n"
        "• بانک روبی برای پس‌انداز و انتقال پوینت\n"
        "• گردونه‌ی شانس روزانه و جدول امتیازات\n\n"
        f"⚠️ نکته: من فقط توی گروه‌های بالای {MIN_GROUP_MEMBERS} نفر مستقر می‌شم؛ "
        "اگه گروهت کوچیک‌تر باشه خودم به‌آرومی از گروه خارج می‌شم.\n\n"
        "برای شروع، منو به گروهت اضافه کن یا از راهنمای کامل استفاده کن 👇"
    )


def welcome_keyboard(context):
    rows = []
    username = getattr(context.bot, "username", None)
    if username:
        rows.append([InlineKeyboardButton("➕ افزودن من به گروه", url=f"https://t.me/{username}?startgroup=true")])
    rows.append([InlineKeyboardButton("📖 راهنمای کامل ❓", callback_data="guide:main")])
    return InlineKeyboardMarkup(rows)


def guide_list_text():
    return "📖 راهنمای کامل ربات روباهیو 🦊\n\nهر بخشی رو که می‌خوای بیشتر بدونی لمس کن ⬇️"


def guide_list_keyboard():
    rows = [[InlineKeyboardButton(title, callback_data=f"guide:item:{i}")] for i, (title, _desc) in enumerate(GUIDE_TOPICS)]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="guide:home")])
    return InlineKeyboardMarkup(rows)


def guide_item_text(idx):
    title, desc = GUIDE_TOPICS[idx]
    return f"{title}\n\n┘─ {desc}"


def guide_item_keyboard(idx):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به راهنما", callback_data="guide:main")]])


async def start_command(update, context):
    # پیلود رفرال رو همین اول ذخیره می‌کنیم؛ چون اگه کاربر هنوز عضو کانال‌ها نباشه،
    # require_membership همینجا برمی‌گرده و قبلاً کد رفرال اصلاً پردازش نمی‌شد.
    if context.args:
        payload = context.args[0].strip()
        if re.fullmatch(r"ref_\d+", payload):
            context.user_data['pending_referral'] = payload
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        existing = session.get(User, update.effective_user.id)
        user = get_or_create_user(session, update.effective_user)
        payload = context.user_data.pop('pending_referral', None)
        if existing is None and payload:
            await handle_referral_signup(session, user, payload, context)
    finally:
        session.close()
    await update.message.reply_text(welcome_text(), reply_markup=welcome_keyboard(context), **reply_kwargs(update.message))


async def handle_referral_signup(session, new_user, payload, context):
    """وقتی کاربر جدید از لینک اختصاصی یکی دیگه وارد می‌شه، یک زیرمجموعه‌ی در-انتظار-تایید می‌سازه."""
    m = re.fullmatch(r"ref_(\d+)", (payload or "").strip())
    if not m:
        return
    referrer_id = int(m.group(1))
    if referrer_id == new_user.telegram_id:
        return
    referrer = session.get(User, referrer_id)
    if referrer is None:
        return
    already = session.query(Referral).filter(Referral.referred_id == new_user.telegram_id).first()
    if already:
        return
    referral = Referral(referrer_id=referrer_id, referred_id=new_user.telegram_id, status="pending")
    session.add(referral)
    session.commit()
    referred_display = (
        f"@{new_user.username}" if new_user.username else (new_user.first_name or "کاربر ناشناس")
    )
    referrer_display = (
        f"@{referrer.username}" if referrer.username else (referrer.first_name or "کاربر ناشناس")
    )
    # آمار معرف (کل/تاییدشده/در انتظار) رو همینجا حساب می‌کنیم تا هم توی پیام ادمین
    # برای تصمیم‌گیری نشون داده بشه، هم برای خود معرف فرستاده بشه؛ چون قبلاً معرف
    # هیچ اطلاعی از ثبت شدن زیرمجموعه‌ش نمی‌گرفت و فقط پیام ادمین می‌رفت.
    total = session.query(Referral).filter(Referral.referrer_id == referrer_id).count()
    approved = session.query(Referral).filter(Referral.referrer_id == referrer_id, Referral.status == "approved").count()
    pending = session.query(Referral).filter(Referral.referrer_id == referrer_id, Referral.status == "pending").count()
    caption = (
        "🔗 زیرمجموعه‌ی جدید در انتظار تایید\n\n"
        f"👤 معرف: {referrer_display} (آیدی: {referrer_id})\n"
        f"🆕 کاربر جدید: {referred_display}\n\n"
        f"📊 آمار این معرف: {total:,} کل | {approved:,} تاییدشده | {pending:,} در انتظار\n"
        f"💰 در صورت تایید، {REFERRAL_REWARD:,} روب‌پوینت به معرف داده می‌شه."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"ref:approve:{referral.id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"ref:reject:{referral.id}"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=kb)
        except Exception:
            logger.warning("ارسال زیرمجموعه‌ی جدید به ادمین %s ناموفق بود", admin_id)
    # به خودِ معرف هم خبر بدیم که دعوتش ثبت شده و در انتظار تاییده، وگرنه معرف تا وقتی
    # خودش دستی /رفرال رو نزنه، هیچ‌وقت متوجه نمی‌شه که کسی با لینکش وارد شده.
    try:
        await context.bot.send_message(
            chat_id=referrer_id,
            text=(
                f"🔗 {referred_display} با لینک اختصاصی تو وارد ربات شد!\n"
                "⏳ این زیرمجموعه الان در انتظار تایید پشتیبانیه.\n\n"
                f"👥 کل زیرمجموعه: {total:,}\n"
                f"✅ تاییدشده: {approved:,}\n"
                f"⏳ در انتظار تایید: {pending:,}"
            )
        )
    except Exception:
        logger.info("اطلاع‌رسانی آمار زیرمجموعه به معرف %s ناموفق بود", referrer_id)


async def referral_admin_button(update, context):
    q = update.callback_query
    if not q or not q.from_user or q.from_user.id not in ADMIN_IDS:
        await q.answer("⛔️ این دکمه فقط برای پشتیبانیه.", show_alert=True)
        return
    m = re.fullmatch(r"ref:(approve|reject):(\d+)", q.data or "")
    if not m:
        await q.answer()
        return
    action, referral_id = m.group(1), int(m.group(2))
    session = get_session()
    try:
        referral = session.get(Referral, referral_id)
        if not referral:
            await q.answer("این زیرمجموعه دیگه پیدا نشد.", show_alert=True)
            return
        if referral.status != "pending":
            await q.answer("قبلاً روی این زیرمجموعه تصمیم گرفته شده.", show_alert=True)
            return
        referred = session.get(User, referral.referred_id)
        referrer = session.get(User, referral.referrer_id)
        referred_display = (
            f"@{referred.username}" if referred and referred.username else (referred.first_name if referred else "کاربر ناشناس")
        )
        referrer_display = (
            f"@{referrer.username}" if referrer and referrer.username else (referrer.first_name if referrer else "کاربر ناشناس")
        )
        if action == "approve":
            referral.status = "approved"
            referral.reward = REFERRAL_REWARD
            referral.decided_at = now_utc()
            referral.decided_by = q.from_user.id
            if referrer:
                referrer.fox_points = (referrer.fox_points or 0) + REFERRAL_REWARD
            session.commit()
            await q.answer("✅ تایید شد.", show_alert=True)
            try:
                await q.message.edit_text(
                    f"✅ زیرمجموعه تایید شد.\n\n👤 معرف: {referrer_display}\n🆕 کاربر: {referred_display}\n"
                    f"💰 {REFERRAL_REWARD:,} روب‌پوینت به معرف اضافه شد."
                )
            except Exception:
                pass
            if referrer:
                try:
                    await context.bot.send_message(
                        chat_id=referrer.telegram_id,
                        text=f"🎉 زیرمجموعه‌ی تو تایید شد و {REFERRAL_REWARD:,} روب‌پوینت گرفتی!"
                    )
                except Exception:
                    pass
        else:
            referral.status = "rejected"
            referral.decided_at = now_utc()
            referral.decided_by = q.from_user.id
            session.commit()
            await q.answer("❌ رد شد.", show_alert=True)
            try:
                await q.message.edit_text(
                    f"❌ زیرمجموعه رد شد.\n\n👤 معرف: {referrer_display}\n🆕 کاربر: {referred_display}"
                )
            except Exception:
                pass
    finally:
        session.close()


def referral_text(user, session, bot_username):
    total = session.query(Referral).filter(Referral.referrer_id == user.telegram_id).count()
    approved = session.query(Referral).filter(Referral.referrer_id == user.telegram_id, Referral.status == "approved").count()
    pending = session.query(Referral).filter(Referral.referrer_id == user.telegram_id, Referral.status == "pending").count()
    earned = approved * REFERRAL_REWARD
    link = f"https://t.me/{bot_username}?start=ref_{user.telegram_id}" if bot_username else "لینک بعد از تنظیم یوزرنیم ربات فعال می‌شه."
    return (
        "🔗 زیرمجموعه‌گیری روباهیو\n\n"
        "هر کسی با لینک اختصاصی خودت وارد ربات بشه، بعد از تایید پشتیبانی "
        f"{REFERRAL_REWARD:,} روب‌پوینت بهت می‌ده!\n\n"
        f"🔗 لینک اختصاصی تو:\n{link}\n\n"
        f"👥 کل زیرمجموعه: {total:,}\n"
        f"✅ تاییدشده: {approved:,}\n"
        f"⏳ در انتظار تایید: {pending:,}\n"
        f"💰 روب‌پوینت کسب‌شده از زیرمجموعه: {earned:,}"
    )


async def referral_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        bot_username = getattr(context.bot, "username", None)
        text = referral_text(user, session, bot_username)
    finally:
        session.close()
    await update.message.reply_text(text, **reply_kwargs(update.message))


async def guide_callback(update, context):
    q = update.callback_query
    data = q.data or ""
    if data == "guide:home":
        await q.answer()
        try:
            await q.message.edit_text(welcome_text(), reply_markup=welcome_keyboard(context))
        except Exception:
            pass
        return
    if data == "guide:main":
        await q.answer()
        try:
            await q.message.edit_text(guide_list_text(), reply_markup=guide_list_keyboard())
        except Exception:
            pass
        return
    m = re.fullmatch(r"guide:item:(\d+)", data)
    if m:
        idx = int(m.group(1))
        if 0 <= idx < len(GUIDE_TOPICS):
            await q.answer()
            try:
                await q.message.edit_text(guide_item_text(idx), reply_markup=guide_item_keyboard(idx))
            except Exception:
                pass
        return


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


async def ruby_games_command(update, context):
    if not await require_membership(update, context): return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        if user.level<3:
            await update.message.reply_text("🔒 پیوستن و ساخت بازی روبی از لول 3 باز می‌شود.",**reply_kwargs(update.message)); return
    finally: session.close()
    owner_id=update.effective_user.id
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 بازی روبی دوز XO",callback_data=f"rg:xo:{owner_id}")],
        [InlineKeyboardButton("🔫 بازی روبی سنگ کاغذ قیچی",callback_data=f"rg:rps:{owner_id}")],
        [InlineKeyboardButton("🎯 بازی روبی دارت",callback_data=f"rg:darts:{owner_id}")],
        [InlineKeyboardButton("🏀 بازی روبی بسکتبال",callback_data=f"rg:basketball:{owner_id}")],
        [InlineKeyboardButton("🎳 بازی روبی بولینگ",callback_data=f"rg:bowling:{owner_id}")],
    ])
    await update.message.reply_text("🕹 بازی های روبی 🦊\n\n❗️ لطفا بازی مورد نظر را انتخاب کنید ⬇️\n\n🧩 بازی روبی دوز XO\n┘─ محدودیت بازیکن : 2 روباه🦊\n\n🔫 بازی روبی سنگ کاغذ قیچی\n┘─ محدودیت بازیکن : 2 روباه🦊\n\n🎯 بازی روبی دارت\n┘─ محدودیت بازیکن : 2 - 4 روباه🦊\n\n🏀 بازی روبی بسکتبال\n┘─ محدودیت بازیکن : 2 - 3 روباه🦊\n\n🎳 بازی روبی بولینگ\n┘─ محدودیت بازیکن : 2 - 4 روباه🦊\n\n⛔️ فقط خودت می‌تونی روی این پنل بزنی.",reply_markup=kb,**reply_kwargs(update.message))


async def casino_command(update, context):
    if not await require_membership(update, context): return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        if user.level<CASINO_UNLOCK_LEVEL:
            await update.message.reply_text(f"🔒 کازینو روبی از سطح {CASINO_UNLOCK_LEVEL} باز می‌شود.\n⭐ سطح فعلی تو: {user.level}",**reply_kwargs(update.message)); return
    finally: session.close()
    owner_id=update.effective_user.id
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 گردونه شانس",callback_data=f"rg:cz_wheel:{owner_id}")],
        [InlineKeyboardButton("🎲 تاس",callback_data=f"rg:cz_dice:{owner_id}")],
        [InlineKeyboardButton("🐇 خرگوش خور",callback_data=f"rg:cz_rabbit:{owner_id}")],
        [InlineKeyboardButton("🃏 بازی دوتایی‌ها",callback_data=f"rg:cz_pairs:{owner_id}")],
    ])
    await update.message.reply_text("🃏 کازینو روبی🦊\n\n❗️ لطفا قمار مورد نظر را انتخاب کنید ⬇️\n\n🎰 گردونه شانس\n┘─ محدودیت بازیکن : 1 - 3 روباه🦊\n\n🎲 تاس\n┘─ محدودیت بازیکن : 1 - 2 روباه🦊\n\n🐇 خرگوش خور\n┘─ محدودیت بازیکن : 2 - 2 روباه🦊\n\n🃏 بازی دوتایی‌ها\n┘─ محدودیت بازیکن : 2 روباه🦊 · 30 خانه · 15 جفت\n┘─ زمان هر نوبت: 60 ثانیه\n\n⛔️ فقط خودت می‌تونی روی این پنل بزنی.",reply_markup=kb,**reply_kwargs(update.message))

RUBY_GAME_CONFIG={
    # key: (نام, حداقل بازیکن, حداکثر بازیکن, امکان مبلغ ورودی)
    "xo":("🧩 بازی روبی دوز XO",2,2,True),"rps":("🔫 بازی روبی سنگ کاغذ قیچی",2,2,True),
    "darts":("🎯 بازی روبی دارت",2,4,True),"basketball":("🏀 بازی روبی بسکتبال",2,3,True),"bowling":("🎳 بازی روبی بولینگ",2,4,True),
    "cz_wheel":("🎰 گردونه شانس",1,3,True),"cz_dice":("🎲 تاس",1,2,True),"cz_rabbit":("🐇 خرگوش خور",2,2,True),
    "cz_pairs":("🃏 بازی دوتایی‌ها",2,2,True),
}
CASINO_UNLOCK_LEVEL = 5

# ایموجی مخصوص هر بازی روبی که کاربر باید خودش با ریپلای روی پنل بفرستد.
RUBY_GAME_EMOJI={"darts":"🎯","basketball":"🏀","bowling":"🎳","cz_dice":"🎲","cz_wheel":"🎰"}
RUBY_EMOJI_TO_GAME={v:k for k,v in RUBY_GAME_EMOJI.items()}

# شرط‌بندی تاس کازینو: در حالت دو نفره از بین 4 گزینه یکی رو سازنده انتخاب می‌کنه؛
# نقطه‌مقابلش خودکار برای حریف می‌شه (فرد↔زوج ، بالاترین تاس↔پایین‌ترین تاس).
# در حالت تکی فقط فرد/زوج معنا داره.
DICE_BET_LABELS = {"odd": "🔢 فرد", "even": "🔢 زوج", "high": "⬆️ بالاترین تاس", "low": "⬇️ پایین‌ترین تاس"}
DICE_BET_COMPLEMENT = {"odd": "even", "even": "odd", "high": "low", "low": "high"}
DICE_SOLO_WIN_MULTIPLIER = 1.9  # ضریب برد بازی تکی تاس (فرد/زوج)

def dice_bet_wins(bet, my_value, other_value):
    if bet == 'odd': return (my_value + other_value) % 2 == 1
    if bet == 'even': return (my_value + other_value) % 2 == 0
    if bet == 'high': return my_value > other_value
    if bet == 'low': return my_value < other_value
    return False

# گردونه شانس: بر اساس اسلات‌ماشین تلگرام (dice.value از 1 تا 64).
# value=43 یعنی سه‌تا لیمو 🍋 و value=64 یعنی سه‌تا هفت 7️⃣ (جکپات).
WHEEL_WIN_THRESHOLD = 50  # بالای این امتیاز، جایزه‌ی عادی تعلق می‌گیره.
WHEEL_WIN_MULTIPLIER = 1.5  # ضریب جایزه‌ی عادی (امتیاز بالای 50).
WHEEL_JACKPOT_MULTIPLIER = 2.7  # ضریب جایزه وقتی دقیقاً 7️⃣7️⃣7️⃣ (جکپات) بیاد.
# دیکد مقدار اسلات‌ماشین تلگرام (1 تا 64) به سه مهره‌ی هر ردیف.
# فرمول استاندارد: v=value-1 در مبنای 4 نوشته می‌شه؛ رقم‌ها: 0=BAR ، 1=🍇 ، 2=🍋 ، 3=7️⃣
WHEEL_REEL_SYMBOL = {0: "🅱️BAR", 1: "🍇", 2: "🍋", 3: "7️⃣"}
WHEEL_REEL_POINTS = {0: 10, 1: 15, 2: 18, 3: 20}

def wheel_decode(value):
    v = value - 1
    d1 = v % 4; v //= 4
    d2 = v % 4; v //= 4
    d3 = v % 4
    return [d1, d2, d3]

def wheel_score(value):
    digits = wheel_decode(value)
    points = sum(WHEEL_REEL_POINTS[d] for d in digits)
    combo = " ".join(WHEEL_REEL_SYMBOL[d] for d in digits)
    return points, combo

def wheel_is_jackpot(value):
    """دقیقاً سه‌تا 7️⃣ (بیشترین مقدار اسلات‌ماشین یعنی 64)."""
    return value == 64

RUBY_COOLDOWN_SECONDS = 90  # هر کاربر هر 1 دقیقه و 30 ثانیه فقط یک‌بار می‌تواند بازی روبی جدید بسازد/وارد شود

RPS_CHOICES = {"rock": "✊", "paper": "🖐", "scissors": "✌️"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
RPS_TOTAL_ROUNDS = 5

XO_LINES = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]

def ruby_cooldown_remaining(user):
    last = aware(user.last_ruby_game_at)
    if not last:
        return 0
    remaining = RUBY_COOLDOWN_SECONDS - (now_utc()-last).total_seconds()
    return max(0, int(remaining))

def ruby_table_keyboard(table_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 شرکت کردن در بازی",callback_data=f"rjoin:{table_id}")]])

def rps_keyboard(tid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(RPS_CHOICES['rock'],callback_data=f"rrps:{tid}:rock"),
        InlineKeyboardButton(RPS_CHOICES['paper'],callback_data=f"rrps:{tid}:paper"),
        InlineKeyboardButton(RPS_CHOICES['scissors'],callback_data=f"rrps:{tid}:scissors"),
    ]])

RPS_ROUND_TIMEOUT_SECONDS = 60

def render_rps_panel(tid,name,pot_line,ids,names_by_id,state,extra=""):
    wins=state.get('wins',{})
    starter=state.get('starter')
    lines=[]
    for uid in ids:
        tag=" 🎬 (شروع‌کننده این راند)" if uid==starter else ""
        lines.append(f"👤 {names_by_id.get(uid,str(uid))} — {wins.get(str(uid),0)} برد{tag}")
    pending=[uid for uid in ids if str(uid) not in state.get('choices',{})]
    wait_line=("\n\n⏳ در انتظار انتخاب: "+"، ".join(names_by_id.get(uid,str(uid)) for uid in pending)) if pending else ""
    extra_block=f"{extra}\n\n" if extra else ""
    text=(f"🕹 {name}\n\n🎮 بازی در جریانه!{pot_line}\n\n"
          f"{extra_block}"
          f"🔁 راند {state.get('round',1)} از {RPS_TOTAL_ROUNDS}\n\n"+"\n".join(lines)+wait_line+
          f"\n\n⏱ هر بازیکن {RPS_ROUND_TIMEOUT_SECONDS} ثانیه وقت داره انتخاب کنه؛ اگه ننداخت بازنده‌ی راند می‌شه.")
    return text,rps_keyboard(tid)

def xo_keyboard(tid,board):
    rows=[]
    for r in range(3):
        row=[]
        for c in range(3):
            i=r*3+c
            label=board[i] if board[i] else "◻️"
            row.append(InlineKeyboardButton(label,callback_data=f"rxo:{tid}:{i}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def render_xo_panel(tid,name,pot_line,ids,names_by_id,state):
    turn_id=state['turn']; turn_symbol=state['symbols'].get(str(turn_id),'?')
    lines=[f"{state['symbols'].get(str(uid),'?')} — {names_by_id.get(uid,str(uid))}" for uid in ids]
    text=(f"🕹 {name}\n\n🎮 بازی در جریانه!{pot_line}\n\n"+"\n".join(lines)+
          f"\n\n▶️ نوبت: {names_by_id.get(turn_id,str(turn_id))} ({turn_symbol})")
    return text,xo_keyboard(tid,state['board'])

def xo_winner_symbol(board):
    for a,b,c in XO_LINES:
        if board[a] and board[a]==board[b]==board[c]:
            return board[a]
    return None

RABBIT_CELLS = 20  # تعداد خونه‌های بازی خرگوش خور

def rabbit_keyboard(tid, state):
    revealed = set(state.get('revealed') or [])
    rows=[]
    for r in range(4):
        row=[]
        for c in range(5):
            i = r*5+c
            label = "🐇" if i in revealed else str(i+1)
            row.append(InlineKeyboardButton(label, callback_data=f"rrabbit:{tid}:{i}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def render_rabbit_panel(tid,name,pot_line,ids,names_by_id,state):
    phase = state.get('phase','plant')
    if phase=='plant':
        planted = list(state.get('paws',{}).keys())
        waiting = [names_by_id.get(uid,str(uid)) for uid in ids if str(uid) not in planted]
        text = (
            f"🕹 {name}\n\n🐾 هر بازیکن باید مخفیانه یکی از خونه‌ها رو به‌عنوان پنجه‌ش انتخاب کنه.{pot_line}\n\n"
            "روی یکی از خونه‌ها بزن؛ فقط خودت می‌فهمی کجا گذاشتی 🤫\n\n"
            f"⏳ در انتظار: {'، '.join(waiting) if waiting else '...'}"
        )
    else:
        turn_id = state.get('turn')
        text = (
            f"🕹 {name}\n\n🎮 مرحله‌ی شکار شروع شد!{pot_line}\n\n"
            "روی خونه‌ها بزن تا خرگوش پیدا کنی؛ هرکی پنجه🐾 رو پیدا کنه می‌بازه!\n\n"
            f"▶️ نوبت: {names_by_id.get(turn_id,str(turn_id))}"
        )
    return text, rabbit_keyboard(tid, state)


# ---------- بازی دوتایی‌ها 🃏 ----------
PAIRS_TOTAL_CELLS = 30
PAIRS_TOTAL_PAIRS = 15
PAIRS_TURN_SECONDS = 60
PAIRS_MISMATCH_REVEAL_SECONDS = 1.2
PAIRS_SYMBOLS = ["🍒","🍋","🍇","🍉","🍊","🥝","🍎","🍓","🍌","🥥","🍍","🥕","🌟","💎","🦊"]

def pairs_keyboard(tid, state):
    deck = state.get("deck", [])
    matched = set(state.get("matched", []))
    opened = set(state.get("open", []))
    rows=[]
    for r in range(5):
        row=[]
        for c in range(6):
            i=r*6+c
            label=deck[i] if i in matched or i in opened else "❔"
            row.append(InlineKeyboardButton(label, callback_data=f"rpairs:{tid}:{i}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def pairs_remaining_seconds(state):
    raw=state.get("turn_started_at")
    if not raw:
        return PAIRS_TURN_SECONDS
    try:
        started=datetime.fromisoformat(raw)
        if started.tzinfo is None:
            started=started.replace(tzinfo=timezone.utc)
        elapsed=(now_utc()-started).total_seconds()
        return max(0, int(PAIRS_TURN_SECONDS-elapsed))
    except Exception:
        return PAIRS_TURN_SECONDS

def render_pairs_panel(tid, name, pot_line, ids, names_by_id, state, extra=""):
    turn=state.get("turn")
    scores=state.get("scores",{})
    remaining=pairs_remaining_seconds(state)
    matched=len(state.get("matched",[]))
    score_lines="\n".join(
        f"{i+1}️⃣ {names_by_id.get(uid,str(uid))} — {scores.get(str(uid),0)} جفت"
        for i,uid in enumerate(ids)
    )
    text=(
        f"🃏 {name}\n\n🎮 بازی دوتایی‌ها در جریانه!{pot_line}\n"
        f"🧩 خانه‌ها: {matched}/{PAIRS_TOTAL_CELLS} باز شده\n\n"
        f"{score_lines}\n\n▶️ نوبت: {names_by_id.get(turn,str(turn))}\n"
        f"⏱ زمان باقی‌مانده نوبت: {remaining} ثانیه"
        + (f"\n\n{extra}" if extra else "")
    )
    return text,pairs_keyboard(tid,state)

async def _pairs_refresh(context, tid, token):
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='cz_pairs':
            return
        state=json.loads(t.state or '{}')
        if state.get("turn_token")!=token:
            return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        players=[session.get(User,i) for i in ids]
        names={u.telegram_id:user_display_name(u) for u in players if u}
        text,kb=render_pairs_panel(t.id,RUBY_GAME_CONFIG['cz_pairs'][0],
            f"\n🏆 جایزه میز: {t.pot:,} روب‌پوینت" if t.entry_amount>0 else "",
            ids,names,state)
        chat_id=t.chat_id; message_id=t.message_id
    finally:
        session.close()
    try:
        await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
    except Exception:
        pass
    if context.job_queue:
        left=pairs_remaining_seconds(state)
        if left>0:
            context.job_queue.run_once(_pairs_refresh,min(5,left),data={"tid":tid,"token":token})

async def pairs_turn_timeout(context):
    data=context.job.data
    tid=int(data["tid"]); token=data["token"]
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='cz_pairs':
            return
        state=json.loads(t.state or '{}')
        if state.get("turn_token")!=token or state.get("lock"):
            return
        left=pairs_remaining_seconds(state)
        if left>0:
            if context.job_queue:
                context.job_queue.run_once(pairs_turn_timeout,left,data=data)
            return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        current=state.get("turn")
        other=[uid for uid in ids if uid!=current][0]
        state["turn"]=other
        state["turn_started_at"]=now_utc().isoformat()
        state["turn_token"]=f"{tid}-{other}-{int(now_utc().timestamp()*1000)}"
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names={u.telegram_id:user_display_name(u) for u in players if u}
        chat_id=t.chat_id; message_id=t.message_id; newtoken=state["turn_token"]
        pot=t.pot; entry=t.entry_amount
        session.commit()
    finally:
        session.close()
    text,kb=render_pairs_panel(tid,RUBY_GAME_CONFIG['cz_pairs'][0],
        f"\n🏆 جایزه میز: {pot:,} روب‌پوینت" if entry>0 else "",ids,names,state,
        extra=f"⏰ نوبت {names.get(current,str(current))} تمام شد؛ نوبت {names.get(other,str(other))} است.")
    try:
        await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
    except Exception:
        pass
    if context.job_queue:
        context.job_queue.run_once(pairs_turn_timeout,PAIRS_TURN_SECONDS,data={"tid":tid,"token":newtoken})
        context.job_queue.run_once(_pairs_refresh,1,data={"tid":tid,"token":newtoken})

async def pairs_mismatch_next_turn(context):
    data=context.job.data
    tid=int(data["tid"]); token=data["token"]
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='cz_pairs':
            return
        state=json.loads(t.state or '{}')
        if state.get("turn_token")!=token or not state.get("lock"):
            return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        current=state.get("turn")
        other=[uid for uid in ids if uid!=current][0]
        state["open"]=[]
        state["lock"]=False
        state["turn"]=other
        state["turn_started_at"]=now_utc().isoformat()
        state["turn_token"]=f"{tid}-{other}-{int(now_utc().timestamp()*1000)}"
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names={u.telegram_id:user_display_name(u) for u in players if u}
        chat_id=t.chat_id; message_id=t.message_id; newtoken=state["turn_token"]
        pot=t.pot; entry=t.entry_amount
        session.commit()
    finally:
        session.close()
    text,kb=render_pairs_panel(tid,RUBY_GAME_CONFIG['cz_pairs'][0],
        f"\n🏆 جایزه میز: {pot:,} روب‌پوینت" if entry>0 else "",ids,names,state,
        extra=f"❌ جفت نشد؛ نوبت {names.get(other,str(other))} است.")
    try:
        await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
    except Exception:
        pass
    if context.job_queue:
        context.job_queue.run_once(pairs_turn_timeout,PAIRS_TURN_SECONDS,data={"tid":tid,"token":newtoken})
        context.job_queue.run_once(_pairs_refresh,1,data={"tid":tid,"token":newtoken})

async def ruby_pairs_move(update,context):
    q=update.callback_query
    try:
        _,tid_s,cell_s=q.data.split(":"); tid=int(tid_s); cell=int(cell_s)
    except Exception:
        return
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='cz_pairs':
            await q.answer("بازی فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        uid=q.from_user.id
        if uid not in ids:
            await q.answer("تو بازیکن این میز نیستی.",show_alert=True); return
        state=json.loads(t.state or '{}')
        if state.get("turn")!=uid:
            await q.answer("⏳ نوبت تو نیست.",show_alert=True); return
        if state.get("lock"):
            await q.answer("⏳ نتیجه این دو کارت در حال نمایش است.",show_alert=True); return
        if pairs_remaining_seconds(state)<=0:
            await q.answer("⏰ زمان این نوبت تمام شده؛ صبر کن تا نوبت بعدی شروع شود.",show_alert=True); return
        deck=state.get("deck",[])
        matched=set(state.get("matched",[]))
        opened=list(state.get("open",[]))
        if cell in matched or cell in opened:
            await q.answer("این خانه قابل انتخاب نیست.",show_alert=True); return
        opened.append(cell)
        state["open"]=opened
        extra=""
        finished=False
        winner_ids=[]
        if len(opened)==2:
            a,b=opened
            if deck[a]==deck[b]:
                matched.update(opened)
                state["matched"]=list(sorted(matched))
                state["open"]=[]
                state.setdefault("scores",{})
                state["scores"][str(uid)]=state["scores"].get(str(uid),0)+1
                extra=f"🎯 {deck[a]} جفت شد! +1 جفت برای {user_display_name(session.get(User,uid))}"
                if len(matched)>=PAIRS_TOTAL_CELLS:
                    finished=True
                    t.status='finished'
                    best=max(state["scores"].values())
                    winner_ids=[int(k) for k,v in state["scores"].items() if v==best]
                    if t.pot>0 and winner_ids:
                        share=t.pot//len(winner_ids)
                        for wid in winner_ids:
                            u=session.get(User,wid)
                            if u: u.fox_points=(u.fox_points or 0)+share
                    state["turn_token"]=None
                else:
                    other=[x for x in ids if x!=uid][0]
                    state["turn"]=other
                    state["turn_started_at"]=now_utc().isoformat()
                    state["turn_token"]=f"{tid}-{other}-{int(now_utc().timestamp()*1000)}"
            else:
                state["lock"]=True
                extra=f"❌ {deck[a]} و {deck[b]} جفت نبودند."
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names={u.telegram_id:user_display_name(u) for u in players if u}
        chat_id=t.chat_id; message_id=t.message_id
        state_snapshot=state.copy()
        pot=t.pot or 0; entry=t.entry_amount
        newtoken=state.get("turn_token")
        session.commit()
    finally:
        session.close()

    await q.answer()
    pot_line=f"\n🏆 جایزه میز: {pot:,} روب‌پوینت" if entry>0 else ""
    if finished:
        score_lines="\n".join(f"👤 {names.get(uid,str(uid))} — {state_snapshot['scores'].get(str(uid),0)} جفت" for uid in ids)
        if len(winner_ids)==1:
            result=(f"🏆 {names.get(winner_ids[0],str(winner_ids[0]))} برنده شد و {pot:,} روب‌پوینت گرفت! 🎉"
                    if pot>0 else f"🏆 {names.get(winner_ids[0],str(winner_ids[0]))} برنده شد! 🎉")
        else:
            share=pot//len(winner_ids) if winner_ids else 0
            result=f"🤝 مساوی شد؛ {', '.join(names.get(x,str(x)) for x in winner_ids)} برنده شدند."
            if pot>0: result+=f" هر نفر {share:,} روب‌پوینت گرفت."
        text=f"🃏 {RUBY_GAME_CONFIG['cz_pairs'][0]}\n\n🏁 بازی تمام شد!\n\n{score_lines}\n\n{result}"
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=None)
        except Exception:
            pass
        return

    text,kb=render_pairs_panel(tid,RUBY_GAME_CONFIG['cz_pairs'][0],pot_line,ids,names,state_snapshot,extra=extra)
    try:
        await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
    except Exception:
        pass
    if state_snapshot.get("lock"):
        if context.job_queue:
            context.job_queue.run_once(pairs_mismatch_next_turn,PAIRS_MISMATCH_REVEAL_SECONDS,
                                       data={"tid":tid,"token":state_snapshot["turn_token"]})
    elif newtoken and context.job_queue:
        context.job_queue.run_once(pairs_turn_timeout,PAIRS_TURN_SECONDS,data={"tid":tid,"token":newtoken})
        context.job_queue.run_once(_pairs_refresh,1,data={"tid":tid,"token":newtoken})

def create_pairs_state(ids):
    deck=[]
    for symbol in PAIRS_SYMBOLS:
        deck.extend([symbol,symbol])
    random.shuffle(deck)
    starter=ids[0]
    token=f"starter-{starter}-{int(now_utc().timestamp()*1000)}"
    return {"deck":deck,"matched":[],"open":[],"scores":{str(uid):0 for uid in ids},
            "turn":starter,"turn_started_at":now_utc().isoformat(),"turn_token":token,"lock":False}

async def ruby_game_select(update,context):
    q=update.callback_query
    parts=q.data.split(":")
    if len(parts)!=3: return
    _,key,owner_s=parts; owner_id=int(owner_s)
    if q.from_user.id!=owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.",show_alert=True); return
    if not await require_membership(update,context): return
    name,minp,maxp,allow_fee=RUBY_GAME_CONFIG[key]
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user)
        remaining=ruby_cooldown_remaining(user)
    finally: session.close()
    if remaining>0:
        await q.answer(f"⏳ هر {RUBY_COOLDOWN_SECONDS} ثانیه فقط یک‌بار می‌تونی بازی روبی بسازی/بری تو بازی. {remaining} ثانیه دیگه صبر کن.",show_alert=True); return
    await q.answer()
    chat_id=q.message.chat_id; message_id=q.message.message_id
    if minp==maxp:
        await ask_ruby_entry_amount(chat_id,message_id,context,key,minp,owner_id)
    else:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"{n} نفر",callback_data=f"rcount:{key}:{n}:{owner_id}") for n in range(minp,maxp+1)]])
        await q.message.edit_text(f"🕹 {name}\n\n👥 میز رو برای چند نفر بچینم؟",reply_markup=kb)

async def ruby_count_select(update,context):
    q=update.callback_query
    parts=q.data.split(":")
    if len(parts)!=4: return
    _,key,count,owner_s=parts; count=int(count); owner_id=int(owner_s)
    if q.from_user.id!=owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.",show_alert=True); return
    if not await require_membership(update,context): return
    await q.answer()
    await ask_ruby_entry_amount(q.message.chat_id,q.message.message_id,context,key,count,owner_id)

async def ask_ruby_entry_amount(chat_id,message_id,context,key,count,owner_id):
    name,minp,maxp,allow_fee=RUBY_GAME_CONFIG[key]
    if not allow_fee:
        # این بازی هنوز منطق تعیین برنده ندارد، فعلاً فقط رایگان قابل ساخت است.
        await finalize_ruby_setup(chat_id,message_id,context,key,count,0,owner_id)
        return
    context.user_data['ruby_setup']={'key':key,'count':count,'chat_id':chat_id,'message_id':message_id,'owner_id':owner_id}
    await context.bot.edit_message_text(
        chat_id=chat_id,message_id=message_id,
        text=(
            f"🕹 {name}\n\n👥 تعداد بازیکن: {count} نفر\n\n"
            f"💰 مبلغ ورودی هر نفر رو بفرست (روب‌پوینت).\n"
            f"سقف مجاز: {RUBY_MAX_ENTRY:,} روب‌پوینت.\nبرای بازی رایگان عدد 0 رو بفرست.\n"
            "مثال: 50k / 50کا / 50م / 200000\n\n"
            "👇 جواب این پیام رو (یا فقط عدد رو) در همین چت بفرست."
        )
    )

async def finalize_ruby_setup(chat_id,message_id,context,key,count,amount,owner_id):
    name,minp,maxp,allow_fee=RUBY_GAME_CONFIG[key]
    fee_text = "رایگان ✅" if amount<=0 else f"{amount:,} روب‌پوینت 🪙"
    if key == 'cz_dice':
        bet_keys = ['odd', 'even'] if count <= 1 else ['odd', 'even', 'high', 'low']
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(DICE_BET_LABELS[b], callback_data=f"rdicebet:{count}:{amount}:{owner_id}:{b}")] for b in bet_keys])
        bet_hint = "روی تک تاست شرط ببند:" if count <= 1 else "شرطت رو انتخاب کن؛ نقطه‌مقابلش خودکار برای حریفت می‌شه:"
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=f"🕹 {name}\n\n👥 تعداد بازیکن: {count} نفر\n💰 مبلغ ورودی : {fee_text}\n\n🎲 {bet_hint}",
            reply_markup=kb
        )
        return
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛠 ساخت میز بازی",callback_data=f"rcreate:{key}:{count}:{amount}:{owner_id}")]])
    await context.bot.edit_message_text(
        chat_id=chat_id,message_id=message_id,
        text=f"🕹 {name}\n\n👥 تعداد بازیکن: {count} نفر\n💰 مبلغ ورودی : {fee_text}\n\nآماده‌ای؟",
        reply_markup=kb
    )

async def handle_ruby_entry_text(update,context):
    setup=context.user_data.get('ruby_setup')
    if not setup: return False
    if update.effective_user.id!=setup.get('owner_id'):
        return False
    context.user_data.pop('ruby_setup',None)
    if not await require_membership(update,context): return True
    chat_id=setup['chat_id']; message_id=setup['message_id']; owner_id=setup['owner_id']
    try:
        amount=parse_amount(update.message.text)
        if amount<0: raise ValueError
    except Exception:
        await update.message.reply_text("❌ مبلغ نامعتبره؛ یک عدد بفرست (مثلاً 0 یا 50000).",**reply_kwargs(update.message)); return True
    if amount>RUBY_MAX_ENTRY:
        await update.message.reply_text(f"❌ سقف مبلغ ورودی {RUBY_MAX_ENTRY:,} روب‌پوینته.",**reply_kwargs(update.message)); return True
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if amount>0 and (user.fox_points or 0)<amount:
            await update.message.reply_text(f"❌ روب‌پوینت کافی نداری.\n💰 موجودی: {int(user.fox_points or 0):,}",**reply_kwargs(update.message)); return True
    finally: session.close()
    await finalize_ruby_setup(chat_id,message_id,context,setup['key'],setup['count'],amount,owner_id)
    return True

async def ruby_create_table(update,context):
    q=update.callback_query
    parts=q.data.split(":")
    if len(parts)!=5: return
    _,key,count,amount,owner_s=parts; count=int(count); amount=int(amount); owner_id=int(owner_s)
    if q.from_user.id!=owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.",show_alert=True); return
    if not await require_membership(update,context): return
    name,minp,maxp,allow_fee=RUBY_GAME_CONFIG[key]
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user)
        remaining=ruby_cooldown_remaining(user)
        if remaining>0:
            await q.answer(f"⏳ {remaining} ثانیه دیگه صبر کن تا بتونی دوباره بازی روبی بسازی.",show_alert=True); return
        if amount>0 and (user.fox_points or 0)<amount:
            await q.answer("❌ روب‌پوینت کافی نداری.",show_alert=True); return
        if amount>0:
            user.fox_points-=amount
        user.last_ruby_game_at=now_utc()
        table=RubyTable(chat_id=q.message.chat_id,game_type=key,creator_id=user.telegram_id,max_players=count,entry_amount=amount,pot=amount,players=str(user.telegram_id),status='open',message_id=q.message.message_id,created_at=now_utc())
        session.add(table); session.commit(); tid=table.id
        creator_name=user_display_name(user)
    finally: session.close()
    await q.answer("میز ساخته شد!")
    fee_line = "🏆 بازی رایگان روبی" if amount<=0 else f"💰 مبلغ ورودی: {amount:,} روب‌پوینت 🪙\n🏆 جایزه کل میز: {amount*count:,} روب‌پوینت"
    if count<=1:
        # بازی تکی: نیازی به پیوستن کسی نیست، همون لحظه شروع می‌شه.
        session=get_session()
        try:
            t=session.get(RubyTable,tid)
            t.status='active'
            if key=='cz_rabbit':
                t.state=json.dumps({"phase":"plant","paws":{},"revealed":[]})
            session.commit()
        finally: session.close()
        if key in RUBY_GAME_EMOJI:
            emoji=RUBY_GAME_EMOJI.get(key)
            move_line=f"\n\nروی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست تا بچرخونی/بندازی."
            await q.message.edit_text(f"🕹 {name}\n\n🎮 بازی شروع شد!\n{fee_line}{move_line}",reply_markup=None)
        else:
            await q.message.edit_text(f"🕹 {name}\n\n🎮 بازی شروع شد!\n{fee_line}",reply_markup=None)
        return
    await q.message.edit_text(f"🕹 {name}\n\n{fee_line}\n\n1️⃣ بازیکن : {creator_name}\n" + "\n".join(f"{i}️⃣ بازیکن : …" for i in range(2,count+1)) + "\n\n⏳ این میز بازی فقط 60 ثانیه اعتبار دارد…",reply_markup=ruby_table_keyboard(tid))
    context.job_queue.run_once(expire_ruby_table,60,data=tid) if context.job_queue else None

async def ruby_dice_bet_select(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 5: return
    _, count, amount, owner_s, bet = parts
    count = int(count); amount = int(amount); owner_id = int(owner_s)
    if bet not in DICE_BET_COMPLEMENT: return
    if q.from_user.id != owner_id:
        await q.answer("⛔ این پنل برای کاربر دیگری است.", show_alert=True); return
    if not await require_membership(update, context): return
    key = 'cz_dice'
    name, minp, maxp, allow_fee = RUBY_GAME_CONFIG[key]
    session = get_session()
    try:
        user = get_or_create_user(session, q.from_user)
        remaining = ruby_cooldown_remaining(user)
        if remaining > 0:
            await q.answer(f"⏳ {remaining} ثانیه دیگه صبر کن تا بتونی دوباره بازی روبی بسازی.", show_alert=True); return
        if amount > 0 and (user.fox_points or 0) < amount:
            await q.answer("❌ روب‌پوینت کافی نداری.", show_alert=True); return
        if amount > 0:
            user.fox_points -= amount
        user.last_ruby_game_at = now_utc()
        table = RubyTable(chat_id=q.message.chat_id, game_type=key, creator_id=user.telegram_id, max_players=count,
                           entry_amount=amount, pot=amount, players=str(user.telegram_id), status='open',
                           message_id=q.message.message_id, created_at=now_utc(),
                           state=json.dumps({"bets": {str(user.telegram_id): bet}}))
        session.add(table); session.commit(); tid = table.id
        creator_name = user_display_name(user)
    finally:
        session.close()
    await q.answer("میز ساخته شد!")
    fee_line = "🏆 بازی رایگان روبی" if amount <= 0 else f"💰 مبلغ ورودی: {amount:,} روب‌پوینت 🪙\n🏆 جایزه کل میز: {amount*count:,} روب‌پوینت"
    bet_line = f"\n🎲 شرط تو: {DICE_BET_LABELS[bet]}"
    if count <= 1:
        session = get_session()
        try:
            t = session.get(RubyTable, tid)
            t.status = 'active'
            session.commit()
        finally:
            session.close()
        emoji = RUBY_GAME_EMOJI.get(key)
        move_line = f"\n\nروی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست تا بندازی."
        await q.message.edit_text(f"🕹 {name}\n\n🎮 بازی شروع شد!\n{fee_line}{bet_line}{move_line}", reply_markup=None)
        return
    await q.message.edit_text(
        f"🕹 {name}\n\n{fee_line}{bet_line}\n\n1️⃣ بازیکن : {creator_name}\n" +
        "\n".join(f"{i}️⃣ بازیکن : …" for i in range(2, count+1)) +
        "\n\n⏳ این میز بازی فقط 60 ثانیه اعتبار دارد…",
        reply_markup=ruby_table_keyboard(tid)
    )
    context.job_queue.run_once(expire_ruby_table, 60, data=tid) if context.job_queue else None


async def _refund_ruby_table(session,t):
    """مبلغ ورودی همه بازیکنانی که تا الان وارد میز شده‌اند را برمی‌گرداند."""
    if not t.entry_amount: return
    ids=[int(x) for x in (t.players or '').split(',') if x]
    for uid in ids:
        u=session.get(User,uid)
        if u: u.fox_points=(u.fox_points or 0)+t.entry_amount

async def expire_ruby_table(context):
    tid=int(context.job.data); session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='open':
            return
        t.status='expired'
        refunded=bool(t.entry_amount)
        await _refund_ruby_table(session,t)
        session.commit()
        chat_id=t.chat_id; message_id=t.message_id; name=RUBY_GAME_CONFIG[t.game_type][0]
    finally:
        session.close()
    note="\n💰 مبلغ ورودی همه بازیکنان به موجودیشون برگشت داده شد." if refunded else ""
    text=f"🕹 {name}\n\n⏰ مهلت این میز تمام شد و بسته شد.{note}"
    try:
        if message_id:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text)
        else:
            await context.bot.send_message(chat_id=chat_id,text=text)
    except Exception:
        pass

async def ruby_join_table(update,context):
    q=update.callback_query; tid=int(q.data.split(":")[1]); session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='open' or (now_utc()-aware(t.created_at)).total_seconds()>60:
            if t and t.status=='open':
                t.status='expired'; await _refund_ruby_table(session,t); session.commit()
            await q.answer("⏰ این میز دیگر فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        if q.from_user.id in ids: await q.answer("قبلاً وارد شده‌ای.",show_alert=True); return
        if len(ids)>=t.max_players: await q.answer("میز پر شده است.",show_alert=True); return
        joiner=get_or_create_user(session,q.from_user)
        remaining=ruby_cooldown_remaining(joiner)
        if remaining>0:
            await q.answer(f"⏳ {remaining} ثانیه دیگه صبر کن تا بتونی دوباره وارد بازی روبی بشی.",show_alert=True); return
        if t.entry_amount>0 and (joiner.fox_points or 0)<t.entry_amount:
            await q.answer(f"❌ برای ورود {t.entry_amount:,} روب‌پوینت لازم داری.",show_alert=True); return
        if t.entry_amount>0:
            joiner.fox_points-=t.entry_amount; t.pot=(t.pot or 0)+t.entry_amount
        joiner.last_ruby_game_at=now_utc()
        ids.append(q.from_user.id); t.players=','.join(map(str,ids))
        game_type=t.game_type
        if len(ids)>=t.max_players:
            t.status='active'
            if game_type=='rps':
                # شروع‌کننده اولین راند، همیشه سازنده میز است (اولین نفر در لیست بازیکنان).
                t.state=json.dumps({"round":1,"wins":{str(i):0 for i in ids},"choices":{},"starter":ids[0]})
            elif game_type=='xo':
                t.state=json.dumps({"board":[""]*9,"turn":ids[0],"symbols":{str(ids[0]):"X",str(ids[1]):"O"}})
            elif game_type=='cz_rabbit':
                t.state=json.dumps({"phase":"plant","paws":{},"revealed":[]})
            elif game_type=='cz_pairs':
                t.state=json.dumps(create_pairs_state(ids))
            elif game_type=='cz_dice':
                st=json.loads(t.state or '{}'); bets=st.get('bets',{})
                creator_bet=bets.get(str(ids[0]))
                if creator_bet: bets[str(q.from_user.id)]=DICE_BET_COMPLEMENT.get(creator_bet,creator_bet)
                t.state=json.dumps({"bets":bets})
        session.commit(); players=[session.get(User,i) for i in ids]; name=RUBY_GAME_CONFIG[t.game_type][0]; pot=t.pot; entry=t.entry_amount; state_raw=t.state; tid_=t.id
    finally: session.close()
    await q.answer("🎮 وارد بازی شدی!")
    if len(ids)>=t.max_players:
        pot_line = f"\n🏆 جایزه میز: {pot:,} روب‌پوینت" if entry>0 else ""
        names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
        if game_type in RUBY_GAME_EMOJI:
            emoji=RUBY_GAME_EMOJI.get(game_type)
            move_line = f"\n\nنوبت پرتابه! روی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست تا خودت پرتاب کنی."
            if game_type=='cz_dice':
                bets=json.loads(state_raw or '{}').get('bets',{})
                player_lines='\n'.join(f"{i+1}️⃣ بازیکن : {user_display_name(u)} — {DICE_BET_LABELS.get(bets.get(str(u.telegram_id)),'?')} — ⏳ در انتظار پرتاب" for i,u in enumerate(players))
            else:
                player_lines='\n'.join(f"{i+1}️⃣ بازیکن : {user_display_name(u)} — ⏳ در انتظار پرتاب" for i,u in enumerate(players))
            await q.message.edit_text(
                f"🕹 {name}\n\n🎮 بازی شروع شد!{pot_line}\n\n"+player_lines+move_line,
                reply_markup=None
            )
        elif game_type=='rps':
            state=json.loads(state_raw or '{}')
            text,kb=render_rps_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
            if context.job_queue:
                context.job_queue.run_once(rps_round_timeout,RPS_ROUND_TIMEOUT_SECONDS,data={'tid':tid_,'round':1})
        elif game_type=='xo':
            state=json.loads(state_raw or '{}')
            text,kb=render_xo_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
        elif game_type=='cz_rabbit':
            state=json.loads(state_raw or '{}')
            text,kb=render_rabbit_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
        elif game_type=='cz_pairs':
            state=json.loads(state_raw or '{}')
            text,kb=render_pairs_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
            if context.job_queue:
                token=state.get('turn_token')
                context.job_queue.run_once(pairs_turn_timeout,PAIRS_TURN_SECONDS,data={'tid':tid_,'token':token})
                context.job_queue.run_once(_pairs_refresh,1,data={'tid':tid_,'token':token})
    else:
        await q.message.edit_text(f"🕹 {name}\n\n"+'\n'.join(f"{i+1}️⃣ بازیکن : {user_display_name(u) if u else '…'}" for i,u in enumerate(players))+"\n\n⏳ منتظر بازیکن بعدی…",reply_markup=ruby_table_keyboard(tid))

async def ruby_rps_choice(update,context):
    q=update.callback_query; _,tid_s,choice=q.data.split(":"); tid=int(tid_s)
    if choice not in RPS_CHOICES:
        await q.answer(); return
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='rps':
            await q.answer("بازی فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        if q.from_user.id not in ids:
            await q.answer("تو بازیکن این میز نیستی.",show_alert=True); return
        state=json.loads(t.state or '{}'); state.setdefault('choices',{}); state.setdefault('wins',{}); state.setdefault('round',1)
        uid_str=str(q.from_user.id)
        if uid_str in state['choices']:
            await q.answer("قبلاً انتخابتو کردی؛ منتظر حریف باش.",show_alert=True); return
        starter=state.get('starter')
        if starter and uid_str!=str(starter) and str(starter) not in state['choices']:
            starter_user=session.get(User,int(starter))
            starter_name=user_display_name(starter_user) if starter_user else "حریفت"
            await q.answer(f"⏳ چون راند قبل رو برده، اول باید {starter_name} انتخابشو بزنه؛ صبر کن.",show_alert=True); return
        state['choices'][uid_str]=choice
        round_complete = all(str(i) in state['choices'] for i in ids)
        round_no=state['round']; ca=cb=None; round_winner=None; match_finished=False; winners=None; pot=0
        if round_complete:
            ca=state['choices'][str(ids[0])]; cb=state['choices'][str(ids[1])]
            if ca==cb: round_winner=None
            elif RPS_BEATS[ca]==cb: round_winner=ids[0]
            else: round_winner=ids[1]
            if round_winner:
                state['wins'][str(round_winner)]=state['wins'].get(str(round_winner),0)+1
                # راند بعدی رو کسی شروع می‌کنه که راند قبل رو برده
                state['starter']=round_winner
            state['round']+=1; state['choices']={}
            if state['round']>RPS_TOTAL_ROUNDS:
                match_finished=True; t.status='finished'
                wins=state['wins']; best=max(wins.values()) if wins else 0
                winners=[int(u) for u,v in wins.items() if v==best] if wins else []
                pot=t.pot or 0
                if pot>0 and winners:
                    share=pot//len(winners)
                    for uid in winners:
                        u=session.get(User,uid)
                        if u: u.fox_points=(u.fox_points or 0)+share
        wins_snapshot=dict(state.get('wins',{}))
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
        name=RUBY_GAME_CONFIG['rps'][0]; entry=t.entry_amount; pot_total=t.pot; chat_id=t.chat_id; message_id=t.message_id
        state_snapshot=dict(state); tid_=t.id
        session.commit()
    finally:
        session.close()

    await q.answer("راند تموم شد!" if round_complete else "انتخابت ثبت شد؛ منتظر حریف بمون.")
    pot_line=f"\n🏆 جایزه میز: {pot_total:,} روب‌پوینت" if entry>0 else ""

    if round_complete:
        if round_winner:
            reveal=(f"🔁 نتیجه راند {round_no}: {names_by_id.get(ids[0])} {RPS_CHOICES[ca]}"
                    f"  در برابر  {names_by_id.get(ids[1])} {RPS_CHOICES[cb]}\n"
                    f"🏅 برنده راند: {names_by_id.get(round_winner)}")
        else:
            reveal=(f"🔁 نتیجه راند {round_no}: {names_by_id.get(ids[0])} {RPS_CHOICES[ca]}"
                    f"  در برابر  {names_by_id.get(ids[1])} {RPS_CHOICES[cb]}\n🤝 راند مساوی شد")
    else:
        reveal=""

    if match_finished:
        score_lines=[f"👤 {names_by_id.get(uid,str(uid))} — {wins_snapshot.get(str(uid),0)} برد" for uid in ids]
        if winners and pot_total>0:
            share=pot_total//len(winners)
            wnames=[names_by_id.get(uid,str(uid)) for uid in winners]
            if len(winners)==1:
                result_line=f"🏆 {wnames[0]} برنده شد و {share:,} روب‌پوینت گرفت! 🎉"
            else:
                result_line=f"🤝 مساوی شد بین {', '.join(wnames)}؛ هرکدوم {share:,} روب‌پوینت گرفتن."
        else:
            result_line="🏁 بازی تموم شد."
        text=(f"🕹 {name}\n\n"+(reveal+"\n\n" if reveal else "")+"\n".join(score_lines)+f"\n\n{result_line}")
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=None)
        except Exception:
            pass
    else:
        text,kb=render_rps_panel(tid_,name,pot_line,ids,names_by_id,state_snapshot,extra=reveal)
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass
        if round_complete and context.job_queue:
            context.job_queue.run_once(rps_round_timeout,RPS_ROUND_TIMEOUT_SECONDS,data={'tid':tid_,'round':state_snapshot['round']})

async def rps_round_timeout(context):
    """
    اگه یکی از بازیکن‌ها تو مهلت 60 ثانیه‌ای انتخابشو نزنه، بازنده‌ی همون راند میشه
    و طرف مقابل برنده‌ی راند و شروع‌کننده‌ی راند بعدی می‌شه. اگه هیچ‌کدوم انتخاب
    نکنن، میز لغو و مبلغ ورودی (در صورت وجود) برگردانده می‌شود.
    """
    data=context.job.data; tid=data['tid']; round_no=data['round']
    session=get_session()
    cancelled=False; match_finished=False; winners=None; loser=None; winner=None; round_completed_no=None
    wins_snapshot=None; state_snapshot=None
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='rps':
            return
        state=json.loads(t.state or '{}')
        if state.get('round')!=round_no:
            return  # راند قبلاً به‌صورت عادی جلو رفته؛ این تایمر دیگه معتبر نیست
        ids=[int(x) for x in (t.players or '').split(',') if x]
        state.setdefault('choices',{}); state.setdefault('wins',{})
        missing=[uid for uid in ids if str(uid) not in state['choices']]
        if not missing:
            return
        players=[session.get(User,i) for i in ids]
        names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
        name=RUBY_GAME_CONFIG['rps'][0]; entry=t.entry_amount; chat_id=t.chat_id; message_id=t.message_id
        pot_total=t.pot

        if len(missing)==len(ids):
            cancelled=True
            t.status='finished'
            await _refund_ruby_table(session,t)
        else:
            loser=missing[0]; winner=[i for i in ids if i!=loser][0]
            state['wins'][str(winner)]=state['wins'].get(str(winner),0)+1
            state['starter']=winner
            round_completed_no=state['round']
            state['round']+=1; state['choices']={}
            if state['round']>RPS_TOTAL_ROUNDS:
                match_finished=True; t.status='finished'
                wins=state['wins']; best=max(wins.values()) if wins else 0
                winners=[int(u) for u,v in wins.items() if v==best] if wins else []
                pot_total=t.pot or 0
                if pot_total>0 and winners:
                    share=pot_total//len(winners)
                    for uid in winners:
                        u=session.get(User,uid)
                        if u: u.fox_points=(u.fox_points or 0)+share
            wins_snapshot=dict(state.get('wins',{}))
            t.state=json.dumps(state)
            state_snapshot=dict(state)
        session.commit()
    finally:
        session.close()

    if cancelled:
        refund_note="\n💰 مبلغ ورودی به موجودی هر دو نفر برگشت داده شد." if entry>0 else ""
        text=f"🕹 {name}\n\n⏰ هیچ‌کدوم از بازیکن‌ها تو {RPS_ROUND_TIMEOUT_SECONDS} ثانیه انتخابی نکردن؛ بازی لغو شد.{refund_note}"
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=None)
        except Exception:
            pass
        return

    pot_line=f"\n🏆 جایزه میز: {pot_total:,} روب‌پوینت" if entry>0 else ""
    reveal=(f"⏱ {names_by_id.get(loser,str(loser))} تو {RPS_ROUND_TIMEOUT_SECONDS} ثانیه انتخاب نکرد و بازنده‌ی راند {round_completed_no} شد.\n"
            f"🏅 برنده راند: {names_by_id.get(winner,str(winner))}")

    if match_finished:
        score_lines=[f"👤 {names_by_id.get(uid,str(uid))} — {wins_snapshot.get(str(uid),0)} برد" for uid in ids]
        if winners and pot_total>0:
            share=pot_total//len(winners)
            wnames=[names_by_id.get(uid,str(uid)) for uid in winners]
            if len(winners)==1:
                result_line=f"🏆 {wnames[0]} برنده شد و {share:,} روب‌پوینت گرفت! 🎉"
            else:
                result_line=f"🤝 مساوی شد بین {', '.join(wnames)}؛ هرکدوم {share:,} روب‌پوینت گرفتن."
        else:
            result_line="🏁 بازی تموم شد."
        text=(f"🕹 {name}\n\n{reveal}\n\n"+"\n".join(score_lines)+f"\n\n{result_line}")
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=None)
        except Exception:
            pass
    else:
        text,kb=render_rps_panel(tid,name,pot_line,ids,names_by_id,state_snapshot,extra=reveal)
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass
        if context.job_queue:
            context.job_queue.run_once(rps_round_timeout,RPS_ROUND_TIMEOUT_SECONDS,data={'tid':tid,'round':state_snapshot['round']})

async def ruby_xo_move(update,context):
    q=update.callback_query; _,tid_s,cell_s=q.data.split(":"); tid=int(tid_s); cell=int(cell_s)
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='xo':
            await q.answer("بازی فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        if q.from_user.id not in ids:
            await q.answer("تو بازیکن این میز نیستی.",show_alert=True); return
        state=json.loads(t.state or '{}')
        if state.get('turn')!=q.from_user.id:
            await q.answer("نوبت تو نیست؛ صبر کن.",show_alert=True); return
        board=state['board']
        if board[cell]:
            await q.answer("این خونه قبلاً پر شده.",show_alert=True); return
        symbol=state['symbols'][str(q.from_user.id)]
        board[cell]=symbol
        other_id=[i for i in ids if i!=q.from_user.id][0]
        win_symbol=xo_winner_symbol(board)
        draw = (not win_symbol) and all(board)
        match_finished=False; winner_id=None; pot=0
        if win_symbol or draw:
            match_finished=True; t.status='finished'
            pot=t.pot or 0
            if win_symbol:
                winner_id=q.from_user.id
                if pot>0:
                    u=session.get(User,winner_id)
                    if u: u.fox_points=(u.fox_points or 0)+pot
            else:
                if pot>0:
                    share=pot//2
                    for uid in ids:
                        u=session.get(User,uid)
                        if u: u.fox_points=(u.fox_points or 0)+share
        else:
            state['turn']=other_id
        state['board']=board
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
        name=RUBY_GAME_CONFIG['xo'][0]; entry=t.entry_amount; pot_total=t.pot; chat_id=t.chat_id; message_id=t.message_id
        state_snapshot=dict(state); state_snapshot['board']=list(board); tid_=t.id
        session.commit()
    finally:
        session.close()

    await q.answer()
    pot_line=f"\n🏆 جایزه میز: {pot_total:,} روب‌پوینت" if entry>0 else ""
    if match_finished:
        lines=[f"{state_snapshot['symbols'].get(str(uid),'?')} — {names_by_id.get(uid,str(uid))}" for uid in ids]
        if winner_id and pot_total>0:
            result_line=f"🏆 {names_by_id.get(winner_id)} برنده شد و {pot_total:,} روب‌پوینت گرفت! 🎉"
        elif winner_id:
            result_line=f"🏆 {names_by_id.get(winner_id)} برنده شد!"
        elif pot_total>0:
            share=pot_total//2
            result_line=f"🤝 بازی مساوی شد؛ هرکدوم {share:,} روب‌پوینت گرفتن."
        else:
            result_line="🤝 بازی مساوی شد."
        text=f"🕹 {name}\n\n"+"\n".join(lines)+f"\n\n{result_line}"
        kb=xo_keyboard(tid_,state_snapshot['board'])
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass
    else:
        text,kb=render_xo_panel(tid_,name,pot_line,ids,names_by_id,state_snapshot)
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass

async def ruby_rabbit_choice(update,context):
    q=update.callback_query; _,tid_s,cell_s=q.data.split(":"); tid=int(tid_s); cell=int(cell_s)
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type!='cz_rabbit':
            await q.answer("بازی فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        uid=q.from_user.id
        if uid not in ids:
            await q.answer("تو بازیکن این میز نیستی.",show_alert=True); return
        state=json.loads(t.state or '{}')
        name=RUBY_GAME_CONFIG['cz_rabbit'][0]; entry=t.entry_amount; chat_id=t.chat_id; message_id=t.message_id

        if state.get('phase')=='plant':
            if str(uid) in state.get('paws',{}):
                await q.answer("قبلاً پنجه‌تو گذاشتی؛ صبر کن حریفت هم بذاره.",show_alert=True); return
            state.setdefault('paws',{})[str(uid)]=cell
            if len(state['paws'])>=len(ids):
                state['phase']='hunt'; state['turn']=ids[0]; state['revealed']=[]
            t.state=json.dumps(state)
            players=[session.get(User,i) for i in ids]
            names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
            pot_total=t.pot; state_snapshot=dict(state); tid_=t.id
            session.commit()
            await q.answer(f"🐾 پنجه‌ات رو مخفیانه تو خونه {cell+1} گذاشتی!",show_alert=True)
            pot_line=f"\n🏆 جایزه میز: {pot_total:,} روب‌پوینت" if entry>0 else ""
            text,kb=render_rabbit_panel(tid_,name,pot_line,ids,names_by_id,state_snapshot)
            try:
                await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
            except Exception:
                pass
            return

        # مرحله شکار
        if state.get('turn')!=uid:
            await q.answer("نوبت تو نیست؛ صبر کن.",show_alert=True); return
        revealed=set(state.get('revealed') or [])
        if cell in revealed:
            await q.answer("این خونه قبلاً باز شده.",show_alert=True); return
        paws=state.get('paws',{})
        if paws.get(str(uid))==cell:
            await q.answer("این خونه پنجه‌ی خودته؛ نمی‌تونی همونجا رو بزنی.",show_alert=True); return
        hit_paw = cell in paws.values()
        match_finished=False; loser_id=None; winner_id=None; pot=0
        if hit_paw:
            match_finished=True; t.status='finished'
            pot=t.pot or 0
            loser_id=uid
            winner_id=[i for i in ids if i!=uid][0]
            if pot>0:
                w=session.get(User,winner_id)
                if w: w.fox_points=(w.fox_points or 0)+pot
        else:
            revealed.add(cell)
            state['revealed']=list(revealed)
            other_id=[i for i in ids if i!=uid][0]
            state['turn']=other_id
        t.state=json.dumps(state)
        players=[session.get(User,i) for i in ids]
        names_by_id={u.telegram_id:user_display_name(u) for u in players if u}
        pot_total=t.pot; state_snapshot=dict(state); tid_=t.id
        session.commit()
    finally:
        session.close()

    await q.answer()
    pot_line=f"\n🏆 جایزه میز: {pot_total:,} روب‌پوینت" if entry>0 else ""
    if match_finished:
        paw_lines=[f"🐾 خونه {c+1} — پنجه {names_by_id.get(int(uidk),uidk)}" for uidk,c in paws.items()]
        result_line = (
            f"😵 {names_by_id.get(loser_id)} پنجه رو پیدا کرد و باخت!\n"
            f"🏆 {names_by_id.get(winner_id)} برنده شد" + (f" و {pot_total:,} روب‌پوینت گرفت! 🎉" if pot_total>0 else "!")
        )
        text=f"🕹 {name}\n\n"+"\n".join(paw_lines)+f"\n\n{result_line}"
        kb=rabbit_keyboard(tid_, {"revealed": list(range(RABBIT_CELLS))})
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass
    else:
        text,kb=render_rabbit_panel(tid_,name,pot_line,ids,names_by_id,state_snapshot)
        try:
            await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=kb)
        except Exception:
            pass

def _parse_ruby_scores(raw):
    scores={}
    for pair in (raw or '').split(','):
        if ':' in pair:
            uid,val=pair.split(':'); scores[int(uid)]=int(val)
    return scores

async def ruby_dice_reply(update, context):
    """
    کاربر خودش با ریپلای روی پنل بازی روبی، ایموجی بازی (🎯/🏀/🎳/🎲/🎰) رو می‌فرسته و
    تلگرام خودش انیمیشن پرتاب رو برای همون کاربر نشون می‌ده. ما فقط نتیجه رو
    می‌خونیم و همون یک پیام پنل بازی رو ویرایش می‌کنیم؛ پیام جدیدی ارسال نمی‌شود.
    """
    msg = update.message
    if not msg or not msg.reply_to_message or not msg.dice:
        return
    game_type = RUBY_EMOJI_TO_GAME.get(msg.dice.emoji)
    if not game_type:
        return
    reply_id = msg.reply_to_message.message_id
    value = msg.dice.value
    session = get_session()
    try:
        t = session.query(RubyTable).filter_by(
            chat_id=msg.chat_id, message_id=reply_id, status='active', game_type=game_type
        ).first()
        if not t:
            return
        ids = [int(x) for x in (t.players or '').split(',') if x]
        if msg.from_user.id not in ids:
            return
        scores = _parse_ruby_scores(t.scores)
        if msg.from_user.id in scores:
            return
        scores[msg.from_user.id] = value
        t.scores = ','.join(f"{u}:{v}" for u, v in scores.items())
        finished = all(i in scores for i in ids)

        if game_type == 'cz_wheel':
            # هر بازیکن مستقل از بقیه می‌چرخونه؛ رقابتی بین بازیکنا نیست.
            wheel_wins = {}
            if finished:
                t.status = 'finished'
                for uid, v in scores.items():
                    pts, _combo = wheel_score(v)
                    if pts > WHEEL_WIN_THRESHOLD:
                        multiplier = WHEEL_JACKPOT_MULTIPLIER if wheel_is_jackpot(v) else WHEEL_WIN_MULTIPLIER
                        win_amount = int(round(t.entry_amount * multiplier))
                        wheel_wins[uid] = win_amount
                        u = session.get(User, uid)
                        if u and win_amount > 0: u.fox_points = (u.fox_points or 0) + win_amount
            players = [session.get(User, i) for i in ids]
            name = RUBY_GAME_CONFIG[t.game_type][0]
            entry = t.entry_amount; chat_id = t.chat_id; message_id = t.message_id
            names_by_id = {u.telegram_id: user_display_name(u) for u in players if u}
        elif game_type == 'cz_dice':
            bets = json.loads(t.state or '{}').get('bets', {})
            dice_wins = {}; tie = False
            if finished:
                t.status = 'finished'
                if len(ids) == 1:
                    uid = ids[0]; my_val = scores[uid]
                    won = (bets.get(str(uid)) == 'odd') == (my_val % 2 == 1)
                    if won and t.entry_amount > 0:
                        win_amount = int(round(t.entry_amount * DICE_SOLO_WIN_MULTIPLIER))
                        dice_wins[uid] = win_amount
                        u = session.get(User, uid)
                        if u: u.fox_points = (u.fox_points or 0) + win_amount
                    elif won:
                        dice_wins[uid] = 0
                else:
                    a, b = ids[0], ids[1]
                    win_a = dice_bet_wins(bets.get(str(a)), scores[a], scores[b])
                    win_b = dice_bet_wins(bets.get(str(b)), scores[b], scores[a])
                    pot = t.pot or 0
                    if win_a and not win_b:
                        dice_wins[a] = pot
                        u = session.get(User, a)
                        if u and pot > 0: u.fox_points = (u.fox_points or 0) + pot
                    elif win_b and not win_a:
                        dice_wins[b] = pot
                        u = session.get(User, b)
                        if u and pot > 0: u.fox_points = (u.fox_points or 0) + pot
                    else:
                        tie = True
                        if t.entry_amount > 0:
                            for uid in ids:
                                u = session.get(User, uid)
                                if u: u.fox_points = (u.fox_points or 0) + t.entry_amount
            players = [session.get(User, i) for i in ids]
            name = RUBY_GAME_CONFIG[t.game_type][0]
            entry = t.entry_amount; chat_id = t.chat_id; message_id = t.message_id; dice_pot = t.pot or 0
            names_by_id = {u.telegram_id: user_display_name(u) for u in players if u}
        else:
            winners = None; pot = 0
            if finished:
                t.status = 'finished'
                best = max(scores.values())
                winners = [u for u, v in scores.items() if v == best]
                pot = t.pot or 0
                if pot > 0 and winners:
                    share = pot // len(winners)
                    for uid in winners:
                        u = session.get(User, uid)
                        if u: u.fox_points = (u.fox_points or 0) + share
            players = [session.get(User, i) for i in ids]
            name = RUBY_GAME_CONFIG[t.game_type][0]
            entry = t.entry_amount; chat_id = t.chat_id; message_id = t.message_id
            names_by_id = {u.telegram_id: user_display_name(u) for u in players if u}
        session.commit()
    finally:
        session.close()

    if game_type == 'cz_wheel':
        lines = []
        for i, uid in enumerate(ids):
            uname = names_by_id.get(uid, str(uid))
            if uid in scores:
                _pts, combo = wheel_score(scores[uid])
                if uid in wheel_wins:
                    lines.append(f"{i+1}️⃣ {uname} — {combo} 🎉 برد {wheel_wins[uid]:,} روب‌پوینت")
                else:
                    lines.append(f"{i+1}️⃣ {uname} — {combo} ❌ باخت")
            else:
                lines.append(f"{i+1}️⃣ {uname} — ⏳ در انتظار چرخوندن")
        if not finished:
            text = (
                f"🕹 {name}\n\n🎰 هرکس مستقل از بقیه می‌چرخونه! اگه شانس بیاری جایزه می‌گیری؛ 7️⃣7️⃣7️⃣ یعنی جکپات کامل 🎉\n\n"
                + "\n".join(lines) +
                "\n\n🎰 نفرات بعدی: روی همین پیام ریپلای کن و ایموجی 🎰 رو بفرست."
            )
        else:
            text = f"🕹 {name}\n\n" + "\n".join(lines) + "\n\n🏁 بازی تموم شد."
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception:
            pass
        return

    if game_type == 'cz_dice':
        pot_line = f"\n🏆 جایزه میز: {dice_pot:,} روب‌پوینت" if entry > 0 and len(ids) > 1 else ""
        lines = []
        for i, uid in enumerate(ids):
            uname = names_by_id.get(uid, str(uid))
            bet_label = DICE_BET_LABELS.get(bets.get(str(uid)), '?')
            if uid in scores:
                lines.append(f"{i+1}️⃣ {uname} — {bet_label} — عدد {scores[uid]} 🎲")
            else:
                lines.append(f"{i+1}️⃣ {uname} — {bet_label} — ⏳ در انتظار پرتاب")
        if not finished:
            emoji = RUBY_GAME_EMOJI.get(game_type)
            text = (
                f"🕹 {name}\n\n🎮 بازی در جریانه!{pot_line}\n\n" + "\n".join(lines) +
                f"\n\nنفرات بعدی: روی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست."
            )
        elif len(ids) == 1:
            uid = ids[0]
            if uid in dice_wins and dice_wins[uid] > 0:
                text = f"🕹 {name}\n\n" + "\n".join(lines) + f"\n\n🎉 برنده شدی و {dice_wins[uid]:,} روب‌پوینت گرفتی!"
            elif uid in dice_wins:
                text = f"🕹 {name}\n\n" + "\n".join(lines) + "\n\n🎉 شرطت درست بود!"
            else:
                text = f"🕹 {name}\n\n" + "\n".join(lines) + "\n\n❌ شرطت درست از آب درنیومد؛ باختی."
        elif tie:
            text = f"🕹 {name}\n\n" + "\n".join(lines) + "\n\n🤝 مساوی شد؛ مبلغ ورودی به هر دو برگشت داده شد."
        else:
            winner_uid = next(iter(dice_wins), None)
            wname = names_by_id.get(winner_uid, str(winner_uid))
            text = f"🕹 {name}\n\n" + "\n".join(lines) + f"\n\n🏆 {wname} برنده شد و {dice_wins[winner_uid]:,} روب‌پوینت گرفت! 🎉"
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception:
            pass
        return

    pot_line = f"\n🏆 جایزه میز: {pot:,} روب‌پوینت" if entry > 0 else ""
    lines = []
    for i, uid in enumerate(ids):
        uname = names_by_id.get(uid, str(uid))
        if uid in scores:
            lines.append(f"{i+1}️⃣ {uname} — عدد {scores[uid]} 🎯")
        else:
            lines.append(f"{i+1}️⃣ {uname} — ⏳ در انتظار پرتاب")

    if not finished:
        emoji = RUBY_GAME_EMOJI.get(game_type)
        text = (
            f"🕹 {name}\n\n🎮 بازی در جریانه!{pot_line}\n\n" + "\n".join(lines) +
            f"\n\nنفرات بعدی: روی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست."
        )
    else:
        if winners and pot > 0:
            share = pot // len(winners)
            wnames = [names_by_id.get(uid, str(uid)) for uid in winners]
            if len(winners) == 1:
                result_line = f"🏆 {wnames[0]} برنده شد و {share:,} روب‌پوینت گرفت! 🎉"
            else:
                result_line = f"🤝 مساوی شد بین {', '.join(wnames)}؛ هرکدوم {share:,} روب‌پوینت گرفتن."
        else:
            result_line = "🏁 بازی تموم شد."
        text = f"🕹 {name}\n\n" + "\n".join(lines) + f"\n\n{result_line}"

    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except Exception:
        pass

async def game_command(update, context):
    await games_command(update, context)

# ---------- گردونه روزانه روبی ----------

async def wheel_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        last = aware(user.wheel_last_spin_at)
        if last is not None:
            remaining = WHEEL_COOLDOWN - (now_utc() - last).total_seconds()
            if remaining > 0:
                await update.message.reply_text(
                    "🐾 حالا روب روب کن؛ برای گردونه هنوز زوده عزیزم🐾\n\n"
                    f"⏱ زمان گردونه بعدی: {format_duration(remaining)} دیگر",
                    **reply_kwargs(update.message)
                )
                return

        reward = random.choice(WHEEL_REWARDS)
        user.wheel_last_spin_at = now_utc()
        user.wheel_last_reward = reward
        if reward > 0:
            user.fox_points = int(user.fox_points or 0) + reward
        session.commit()
        new_balance = int(user.fox_points or 0)
    except Exception:
        session.rollback()
        logger.exception("daily wheel failed")
        await update.message.reply_text("❌ گردونه فعلاً با مشکل روبه‌رو شد؛ دوباره تلاش کن.", **reply_kwargs(update.message))
        return
    finally:
        session.close()

    reward_text = "پوچ 😢" if reward == 0 else f"+{reward:,} روب پوینت 🪙"
    await update.message.reply_text(
        "🎡 گردونه روبی 🦊\n\n"
        f"🏆 برنده شدی: {reward_text}\n"
        f"💰 موجودی روب‌پوینت: {new_balance:,}\n\n"
        "⏱ گردونه بعدی: 24 ساعت دیگر",
        **reply_kwargs(update.message)
    )


# ---------- روباه ----------

def fox_keyboard(user_id, user_level, fox_level=None, fox_prestige_count=0):
    rows=[[InlineKeyboardButton("🧲 برداشت روب پوینت ها",callback_data=f"fox:collect:{user_id}")]]
    lvl = max(1, min(FOX_MAX_LEVEL, int(fox_level or 1)))
    if lvl < FOX_MAX_LEVEL:
        rows.append([InlineKeyboardButton("⭐ ارتقای سطح روباه",callback_data=f"fox:upgrade:{user_id}")])
    rows.append([InlineKeyboardButton("✏️ تغییر اسم روباه",callback_data=f"fox:rename:{user_id}")])
    return InlineKeyboardMarkup(rows)


def fox_profile_text(user):
    lvl = max(1, min(FOX_MAX_LEVEL, int(user.fox_level or 1)))
    belly_cap = min(20, max(1, int(user.fox_belly_capacity or 3)))
    storage_cap = fox_storage_capacity(lvl)
    storage = min(storage_cap, int(user.fox_storage or 0))
    produced_total = int(user.fox_total_earned or 0)
    rate = int(fox_production_per_second(lvl))
    lines = [
        f"🦊 روباه {user.fox_name or 'مکار'}",
        "",
        f"💕 نام : {user.fox_name or 'مکار'}",
        f"🍖 شکم : {int(user.fox_belly or 0)} / {belly_cap}",
        "",
        f"🌟 مقام : {fox_rank(lvl)}",
        f"⭐️ سطح : {lvl} / {FOX_MAX_LEVEL}",
        "",
        f"💰 روب پوینت های تولید شده : {produced_total:,} 🪙",
        f"💫 تولید روب پوینت در ثانیه : {rate:,} 🪙",
        f"📦 ظرفیت : {storage:,} / {storage_cap:,} 🪙",
    ]
    if storage >= storage_cap:
        lines += ["", "🔴 ظرفیت پره! تا برداشت نزنی روباه دوباره کار نمی‌کنه."]
    if int(user.fox_belly or 0) < 2:
        lines += ["", "😡 شکم روباه حداقل باید 2 غذا داشته باشه تا تولید کنه."]
    if lvl >= FOX_MAX_LEVEL:
        lines += ["", "🏆 روباه به آخرین سطح رسیده!"]
    else:
        lines += ["", f"⭐ هزینه ارتقای بعدی: {fox_upgrade_cost(lvl):,} روب‌پوینت"]
    return "\n".join(lines)


def settle_fox_hunger(user):
    """هر FOX_HUNGER_INTERVAL_SECONDS (۲۵ دقیقه) یک واحد غذا از شکم روباه کم می‌شود؛
    این کار مدام و بدون توقف ادامه دارد (زیر صفر نمی‌رود)."""
    now = now_utc()
    if user.fox_last_hunger_at is None:
        user.fox_last_hunger_at = now
        return 0
    elapsed = max(0.0, (now - aware(user.fox_last_hunger_at)).total_seconds())
    intervals = int(elapsed // FOX_HUNGER_INTERVAL_SECONDS)
    if intervals <= 0:
        return 0
    belly = max(0, int(user.fox_belly or 0))
    lost = min(belly, intervals)
    user.fox_belly = belly - lost
    # ساعت را فقط به اندازه‌ی بازه‌های کامل‌شده جلو می‌بریم (نه تا "now")
    # تا باقیمانده‌ی زمانِ ناقص برای بازه‌ی بعدی از دست نرود؛ حتی وقتی شکم
    # صفر است ساعت باید جلو برود، وگرنه با اولین غذا چند بازه‌ی قبلی یکجا کم می‌شود.
    user.fox_last_hunger_at = aware(user.fox_last_hunger_at) + timedelta(seconds=intervals * FOX_HUNGER_INTERVAL_SECONDS)
    return lost


def update_fox_production(user):
    """
    تولید امن روباه:
    - لول 1 تا 20: به‌ترتیب 1 تا 20 روب‌پوینت در ثانیه.
    - لول 21 تا 25 نیز دقیقاً 20 در ثانیه.
    - تولید هیچ‌وقت از فضای خالی مخزن بیشتر محاسبه نمی‌شود.
    - وقتی مخزن پر است، زمان تولید فریز می‌شود.
    - بعد از برداشت، ساعت تولید دقیقاً از همان لحظه دوباره شروع می‌شود؛
      بنابراین زمان قدیمی نمی‌تواند باعث تولید ناگهانی هزاران روب‌پوینت شود.
    """
    settle_fox_hunger(user)
    now = now_utc()
    level = max(1, min(FOX_MAX_LEVEL, int(user.fox_level or 1)))
    storage_cap = fox_storage_capacity(level)
    storage = max(0, int(user.fox_storage or 0))

    if user.fox_production_remainder is None or user.fox_production_remainder < 0:
        user.fox_production_remainder = 0.0

    # اگر ظرفیت پر است، هیچ زمان/تولید معوقی جمع نشود.
    if storage >= storage_cap:
        user.fox_last_production_at = now
        user.fox_production_remainder = 0.0
        return 0.0

    # اولین اجرای سیستم یا داده‌ی قدیمیِ بدون timestamp: از همین لحظه شروع کن.
    if user.fox_last_production_at is None:
        user.fox_last_production_at = now
        user.fox_production_remainder = 0.0
        return 0.0

    # شکم کمتر از 2 باشد، تولید متوقف است و زمان معوق جمع نمی‌شود.
    if (user.fox_belly or 0) < 2:
        user.fox_last_production_at = now
        user.fox_production_remainder = 0.0
        return 0.0

    elapsed = max(0.0, (now - aware(user.fox_last_production_at)).total_seconds())
    rate = fox_production_per_second(level)

    # حداکثر تعداد قابل تولید فقط به اندازه‌ی فضای خالی مخزن است.
    room = max(0, storage_cap - storage)
    if room <= 0:
        user.fox_last_production_at = now
        user.fox_production_remainder = 0.0
        return 0.0

    total = float(user.fox_production_remainder or 0.0) + elapsed * rate
    whole = min(room, int(total))

    if whole >= room:
        # مخزن همین الان پر شد؛ باقی‌مانده‌ی زمان عمداً دور ریخته می‌شود
        # تا بعد از برداشت، تولید از زمان برداشت شروع شود.
        user.fox_production_remainder = 0.0
        user.fox_last_production_at = now
    else:
        user.fox_production_remainder = total - whole
        user.fox_last_production_at = now

    return float(max(0, whole))

def settle_fox_production(user):
    """محاسبه تولید معوق روباه و ذخیره آن در انبار روباه تا سقف ظرفیت (جدا از موجودی قابل‌خرج کاربر)."""
    produced = update_fox_production(user)
    if produced <= 0:
        return 0
    cap = fox_storage_capacity(max(1, min(FOX_MAX_LEVEL, int(user.fox_level or 1))))
    current = int(user.fox_storage or 0)
    room = max(0, cap - current)
    add = min(room, int(produced))
    if add > 0:
        user.fox_storage = current + add
        user.fox_total_earned = int(user.fox_total_earned or 0) + add
    return add

def next_fox_point_seconds(user):
    if (user.fox_belly or 0) < 2:
        return 0
    rate = fox_production_per_second(max(1, min(FOX_MAX_LEVEL, int(user.fox_level or 1))))
    if rate <= 0:
        return 0
    remainder = float(user.fox_production_remainder or 0.0)
    needed = max(0.0, 1.0 - remainder)
    return max(1, int(needed / rate))

async def restore_fox_panel(bot, chat_id, message_id, owner_id):
    await asyncio.sleep(4)
    session=get_session()
    try:
        user=session.get(User,owner_id)
        if not user or user.level<FOX_UNLOCK_LEVEL:return
        settle_fox_production(user);session.commit();text=fox_profile_text(user);markup=fox_keyboard(user.telegram_id,user.level,user.fox_level,user.fox_prestige_count)
    finally:session.close()
    try:await bot.edit_message_text(text=text,chat_id=chat_id,message_id=message_id,reply_markup=markup)
    except Exception as e:logger.debug("restore fox panel: %s",e)


async def fox_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        if user.level < FOX_UNLOCK_LEVEL:
            await update.message.reply_text(
                f"🔒 روباه در سطح {FOX_UNLOCK_LEVEL} باز می‌شود.\n"
                f"⭐ سطح فعلی تو: {user.level}", **reply_kwargs(update.message)
            )
            return
        settle_fox_production(user)
        session.commit()
        text = fox_profile_text(user)
        owner_level=user.level; owner_fox_level=user.fox_level; owner_prestige=user.fox_prestige_count
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=fox_keyboard(update.effective_user.id, owner_level, owner_fox_level, owner_prestige), **reply_kwargs(update.message))


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
            amount = int(user.fox_storage or 0)
            user.fox_points = int(user.fox_points or 0) + amount
            user.fox_storage = 0
            # برداشت = شروع یک چرخه‌ی کاملاً جدید؛ هیچ زمان قدیمی منتقل نمی‌شود.
            user.fox_last_production_at = now_utc()
            user.fox_production_remainder = 0.0
            session.commit()
            nxt = next_fox_point_seconds(user)
            next_text = f"⏱ روب‌پوینت بعدی حدود {format_duration(nxt)} دیگر تولید می‌شود." if nxt else "⏸ تولید متوقف است تا شکم حداقل 2 غذا داشته باشد."
            await q.answer("برداشت انجام شد! 💰")
            await q.message.edit_text(fox_profile_text(user) + f"\n\n💰 {amount:,} روب‌پوینت به موجودیت اضافه شد.\n{next_text}")
            asyncio.create_task(restore_fox_panel(context.bot,q.message.chat_id,q.message.message_id,user.telegram_id))
            return
        if action == "upgrade":
            lvl = max(1, min(FOX_MAX_LEVEL, int(user.fox_level or 1)))
            if lvl >= FOX_MAX_LEVEL:
                await q.answer("🏆 روباه به آخرین سطح (25) رسیده است.", show_alert=True)
            else:
                cost = fox_upgrade_cost(lvl)
                if user.fox_points < cost:
                    await q.answer(f"روب‌پوینت کافی نیست. {cost:,.0f} لازم داری.", show_alert=True)
                else:
                    user.fox_points -= cost
                    user.fox_level += 1
                    # با هر ارتقا یک جای غذا به ظرفیت شکم اضافه می‌شود؛ سقف 20 است.
                    user.fox_belly_capacity = min(20, int(user.fox_belly_capacity or 3) + 1)
                    user.fox_last_production_at = now_utc()
                    session.commit()
                    await q.answer(f"🦊 روباه رفت لول {user.fox_level}!", show_alert=True)
                    await q.message.edit_text(fox_profile_text(user) + f"\n\n🎉 روباه به لول {user.fox_level} رسید!\n🏅 مقام جدید: {fox_rank(user.fox_level)}")
                    asyncio.create_task(restore_fox_panel(context.bot,q.message.chat_id,q.message.message_id,user.telegram_id))
                    return
        elif action in ("resetask", "resetyes", "resetno"):
            await q.answer("ℹ️ روباه حالا حداکثر تا سطح 25 ارتقا پیدا می‌کنه و ریست چرخه‌ای نداره.", show_alert=True)
            await q.message.edit_text(fox_profile_text(user), reply_markup=fox_keyboard(user.telegram_id, user.level, user.fox_level, user.fox_prestige_count))
            return
        elif action == "hunt":
            await handle_hunt_request(q, session, user, context)
            return
        elif action == "fridge":
            if user.level < FRIDGE_UNLOCK_LEVEL:
                await q.answer(f"❄️ یخچال روبی در سطح {FRIDGE_UNLOCK_LEVEL} باز می‌شود.", show_alert=True)
                return
            items = settle_all_fridge_items(session, user.telegram_id)
            session.commit()
            await q.answer()
            await q.message.reply_text(fridge_text(user, items), reply_markup=fridge_keyboard(user, items))
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
    weight = round(random.uniform(item["weight_min"], item["weight_max"]), 2)
    hunt = FoxHunt(user_id=user.telegram_id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending", weight=weight)
    user.last_hunt_at = now_utc()
    user.hunt_count=(user.hunt_count or 0)+1
    session.add(hunt)
    chat = q.message.chat if q.message else None
    if chat: bump_city_stat(session, chat.id, chat.title, city_hunt_total=1)
    session.commit()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.telegram_id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.telegram_id}")],
        [InlineKeyboardButton("❄️ انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.telegram_id}")],
    ])
    await q.answer()
    emoji_msg = await q.message.reply_text(emoji)
    await asyncio.sleep(3)
    await emoji_msg.reply_text(
        f"🎯 شما {item['name']} را شکار کردید!\n🍖 ارزش غذایی: {item['nutrition']}\n💰 ارزش فروش: {item['sell']:,} روب‌پوینت\n\nچه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
        reply_markup=kb
    )
    if chat: await maybe_level_up_city(context, chat.id)


async def hunt_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
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
        weight = round(random.uniform(item["weight_min"], item["weight_max"]), 2)
        hunt = FoxHunt(user_id=user.telegram_id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending", weight=weight)
        user.last_hunt_at = now_utc()
        user.hunt_count = (user.hunt_count or 0) + 1
        session.add(hunt)
        chat = update.effective_chat
        if chat: bump_city_stat(session, chat.id, chat.title, city_hunt_total=1)
        session.commit()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.telegram_id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.telegram_id}")],
            [InlineKeyboardButton("❄️ انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.telegram_id}")],
        ])
        emoji_msg = await update.message.reply_text(emoji, **reply_kwargs(update.message))
        await asyncio.sleep(3)
        await emoji_msg.reply_text(
            f"🎯 شما {item['name']} را شکار کردید!\n🍖 ارزش غذایی: {item['nutrition']}\n💰 ارزش فروش: {item['sell']:,} روب‌پوینت\n\nچه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
            reply_markup=kb
        )
    finally:
        session.close()
    if update.effective_chat: await maybe_level_up_city(context, update.effective_chat.id)


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
            cap = int(user.fox_belly_capacity or 3)
            user.fox_belly = min(cap, user.fox_belly + hunt.nutrition)
            hunt.status = "fed"
            session.commit()
            await q.answer("🦊 شکار به روباه داده شد!")
            await q.message.edit_text(
                f"🦊 {hunt.emoji} {hunt.item_name} به روباه داده شد.\n"
                f"🍖 شکم روباه: {old}/{cap} → {user.fox_belly}/{cap}\n\n"
                f"⚡ تولید روب‌پوینت وقتی شکم حداقل ۲ واحد غذا داشته باشد فعال است."
            )
        elif action == "sell":
            user.fox_points += hunt.sell_value
            hunt.status = "sold"
            session.commit()
            await q.answer("💰 فروخته شد!")
            await q.message.edit_text(f"💰 {hunt.emoji} {hunt.item_name} فروخته شد و {hunt.sell_value:,} روب پوینت گرفتی.\n🪙 موجودی روب‌پوینت: {int(user.fox_points):,}")
        elif action == "fridge":
            if user.level < FRIDGE_UNLOCK_LEVEL:
                await q.answer(f"❄️ یخچال روبی در سطح {FRIDGE_UNLOCK_LEVEL} باز می‌شود.", show_alert=True)
                return
            cap = fridge_capacity(user.fridge_level)
            current_count = session.query(FoxHunt).filter(FoxHunt.user_id == user.telegram_id, FoxHunt.status == "fridge").count()
            if current_count >= cap:
                await q.answer(f"❄️ یخچال پر است! ({current_count}/{cap}) اول یه چیزی رو بفروش یا بخور.", show_alert=True)
                return
            hunt.status = "fridge"
            hunt.cooked = 0
            hunt.cooking_started_at = None
            session.commit()
            await q.answer("❄️ داخل یخچال روبی قرار گرفت!")
            await q.message.edit_text(f"❄️ {hunt.emoji} {hunt.item_name} داخل یخچال روبی ذخیره شد. ({current_count + 1}/{cap})")
    finally:
        session.close()

# ---------- یخچال روبی ----------

FRIDGE_SEPARATOR = "〰️〰️〰️〰️〰️〰️〰️"


def settle_fridge_item(hunt):
    """اگر آیتمی در حال پخت بوده و زمانش تموم شده، ارزش غذایی و ارزش فروشش دو برابر می‌شود."""
    if hunt.status == "fridge" and not hunt.cooked and hunt.cooking_started_at:
        duration = fridge_cook_seconds(hunt.nutrition)
        if (now_utc() - aware(hunt.cooking_started_at)).total_seconds() >= duration:
            hunt.nutrition = int(hunt.nutrition) * 2
            hunt.sell_value = int(hunt.sell_value) * 2
            hunt.cooked = 1
            hunt.cooking_started_at = None
    return hunt


def settle_all_fridge_items(session, user_id):
    items = session.query(FoxHunt).filter(FoxHunt.user_id == user_id, FoxHunt.status == "fridge").order_by(FoxHunt.id.desc()).all()
    for it in items:
        settle_fridge_item(it)
    return items


def fridge_cook_remaining(hunt):
    if hunt.status == "fridge" and not hunt.cooked and hunt.cooking_started_at:
        duration = fridge_cook_seconds(hunt.nutrition)
        left = duration - (now_utc() - aware(hunt.cooking_started_at)).total_seconds()
        return max(0, int(left))
    return 0


def fridge_item_block(hunt):
    item = HUNT_ITEMS.get(hunt.emoji, {})
    rarity = item.get("rarity", "معمولی")
    rarity_emoji = item.get("rarity_emoji", "⚪️")
    if hunt.cooked:
        state = "پخته"
    elif hunt.cooking_started_at:
        state = "در حال پخت"
    else:
        state = "خام"
    weight = hunt.weight if hunt.weight is not None else 0.0
    lines = [
        f"{hunt.emoji} {hunt.item_name} | {rarity} {rarity_emoji} | ({state})",
        f"┘─ ⚖️ وزن : {weight:g} کیلو",
        f"┘─ 💰 ارزش : {hunt.sell_value:,} 🪙",
        f"┘─ 🍖 ارزش غذایی : {hunt.nutrition}",
    ]
    if state == "در حال پخت":
        lines.append(f"┘─ 🔥 باقی‌مانده تا پخت : {format_duration(fridge_cook_remaining(hunt))}")
    return "\n".join(lines)


def fridge_text(user, items):
    level = max(1, min(FRIDGE_MAX_LEVEL, int(user.fridge_level or 1)))
    cap = fridge_capacity(level)
    lines = [
        f"❄️ یخچال روبی {user_display_name(user)}",
        "",
        f"⭐️ سطح یخچال : {level} / {FRIDGE_MAX_LEVEL}",
        "",
        f"🦊 ظرفیت یخچال : {len(items)} / {cap}",
        "",
        FRIDGE_SEPARATOR,
    ]
    if not items:
        lines += ["", "یخچال فعلاً خالی است.", "", FRIDGE_SEPARATOR]
    else:
        for hunt in items:
            lines += ["", fridge_item_block(hunt), "", FRIDGE_SEPARATOR]
    if level >= FRIDGE_MAX_LEVEL:
        lines += ["", "✨ یخچال در آخرین سطح ممکن میباشد."]
    else:
        cost = fridge_upgrade_cost(level)
        cost_text = "رایگان 🎁" if cost == 0 else f"{cost:,} روب‌پوینت"
        lines += ["", f"⭐ ارتقای بعدی یخچال : {cost_text} (+۱ جای جدید)"]
    return "\n".join(lines)


def fridge_keyboard(user, items):
    owner_id = user.telegram_id
    rows, row = [], []
    for idx, hunt in enumerate(items, start=1):
        row.append(InlineKeyboardButton(str(idx), callback_data=f"fridge:item:{hunt.id}:{owner_id}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    level = max(1, min(FRIDGE_MAX_LEVEL, int(user.fridge_level or 1)))
    if level < FRIDGE_MAX_LEVEL:
        cost = fridge_upgrade_cost(level)
        cost_label = "رایگان 🎁" if cost == 0 else f"{cost:,} روب‌پوینت"
        rows.append([InlineKeyboardButton(f"⭐ ارتقای یخچال ({cost_label})", callback_data=f"fridge:upgrade:0:{owner_id}")])
    return InlineKeyboardMarkup(rows) if rows else None


def fridge_item_keyboard(hunt, owner_id):
    rows = []
    if hunt.cooked:
        rows.append([
            InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"fridge:feed:{hunt.id}:{owner_id}"),
            InlineKeyboardButton("💰 فروختن", callback_data=f"fridge:sell:{hunt.id}:{owner_id}"),
        ])
    elif hunt.cooking_started_at:
        rows.append([InlineKeyboardButton("🔄 بررسی وضعیت پخت", callback_data=f"fridge:item:{hunt.id}:{owner_id}")])
    else:
        rows.append([
            InlineKeyboardButton("🔥 پختن", callback_data=f"fridge:cook:{hunt.id}:{owner_id}"),
        ])
        rows.append([
            InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"fridge:feed:{hunt.id}:{owner_id}"),
            InlineKeyboardButton("💰 فروختن", callback_data=f"fridge:sell:{hunt.id}:{owner_id}"),
        ])
    rows.append([InlineKeyboardButton("🔙 بازگشت به یخچال", callback_data=f"fridge:view:0:{owner_id}")])
    return InlineKeyboardMarkup(rows)


async def fridge_button(update, context):
    q = update.callback_query
    try:
        _, action, arg1_s, owner_s = q.data.split(":")
        arg1, owner_id = int(arg1_s), int(owner_s)
    except Exception:
        return
    if q.from_user.id != owner_id:
        await q.answer("⛔ این یخچال برای کاربر دیگری است.", show_alert=True)
        return
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = session.get(User, owner_id)
        if not user:
            await q.answer("کاربر پیدا نشد.", show_alert=True)
            return
        if user.level < FRIDGE_UNLOCK_LEVEL:
            await q.answer(f"❄️ یخچال روبی در سطح {FRIDGE_UNLOCK_LEVEL} باز می‌شود.", show_alert=True)
            return
        if action == "view":
            items = settle_all_fridge_items(session, user.telegram_id)
            session.commit()
            await q.answer()
            await q.message.edit_text(fridge_text(user, items), reply_markup=fridge_keyboard(user, items))
            return
        if action == "upgrade":
            level = max(1, min(FRIDGE_MAX_LEVEL, int(user.fridge_level or 1)))
            if level >= FRIDGE_MAX_LEVEL:
                await q.answer("✨ یخچال به آخرین سطح رسیده است.", show_alert=True)
                return
            cost = fridge_upgrade_cost(level)
            if cost and (user.fox_points or 0) < cost:
                await q.answer(f"روب‌پوینت کافی نیست. {cost:,} روب‌پوینت لازم داری.", show_alert=True)
                return
            if cost:
                user.fox_points -= cost
            user.fridge_level = level + 1
            session.commit()
            items = settle_all_fridge_items(session, user.telegram_id)
            session.commit()
            await q.answer(f"❄️ یخچال ارتقا پیدا کرد! سطح {user.fridge_level}", show_alert=True)
            await q.message.edit_text(fridge_text(user, items), reply_markup=fridge_keyboard(user, items))
            return
        # از اینجا به بعد، اکشن‌ها مربوط به یک آیتم مشخص داخل یخچال هستند.
        hunt = session.get(FoxHunt, arg1)
        if not hunt or hunt.user_id != owner_id or hunt.status != "fridge":
            await q.answer("این آیتم دیگر در یخچال نیست.", show_alert=True)
            return
        settle_fridge_item(hunt)
        if action == "item":
            session.commit()
            await q.answer()
            await q.message.edit_text(fridge_item_block(hunt), reply_markup=fridge_item_keyboard(hunt, owner_id))
            return
        if action == "cook":
            if hunt.cooked:
                await q.answer("🍖 این آیتم قبلاً پخته شده.", show_alert=True)
            elif hunt.cooking_started_at:
                remaining = fridge_cook_remaining(hunt)
                await q.answer(f"🔥 در حال پخت است. {format_duration(remaining)} مانده.", show_alert=True)
            else:
                hunt.cooking_started_at = now_utc()
                session.commit()
                duration = fridge_cook_seconds(hunt.nutrition)
                await q.answer(f"🔥 پخت شروع شد! {format_duration(duration)} طول می‌کشد.", show_alert=True)
            await q.message.edit_text(fridge_item_block(hunt), reply_markup=fridge_item_keyboard(hunt, owner_id))
            return
        if action == "sell":
            sold_value = hunt.sell_value
            sold_name = f"{hunt.emoji} {hunt.item_name}"
            user.fox_points = (user.fox_points or 0) + sold_value
            hunt.status = "sold"
            hunt.cooking_started_at = None
            session.commit()
            items = settle_all_fridge_items(session, user.telegram_id)
            session.commit()
            await q.answer("💰 فروخته شد!")
            await q.message.edit_text(
                f"💰 {sold_name} فروخته شد و {sold_value:,} روب‌پوینت گرفتی.\n"
                f"🪙 موجودی روب‌پوینت: {int(user.fox_points):,}\n\n" + fridge_text(user, items),
                reply_markup=fridge_keyboard(user, items)
            )
            return
        if action == "feed":
            settle_fox_production(user)
            fed_name = f"{hunt.emoji} {hunt.item_name}"
            old = user.fox_belly
            cap = int(user.fox_belly_capacity or 3)
            user.fox_belly = min(cap, user.fox_belly + hunt.nutrition)
            hunt.status = "fed"
            hunt.cooking_started_at = None
            session.commit()
            items = settle_all_fridge_items(session, user.telegram_id)
            session.commit()
            await q.answer("🦊 شکار به روباه داده شد!")
            await q.message.edit_text(
                f"🦊 {fed_name} به روباه داده شد.\n"
                f"🍖 شکم روباه: {old}/{cap} → {user.fox_belly}/{cap}\n\n" + fridge_text(user, items),
                reply_markup=fridge_keyboard(user, items)
            )
            return
    finally:
        session.close()
    await q.answer()

# ---------- جمع‌آوری روب‌پوینت ----------

FOX_CLAIM_ALIASES={"روب روب","هور هور","عو عو","روب روب!","هور هور!","عو عو!"}

async def collect_fox_points(update,context):
    if not await require_membership(update,context):return
    session=get_session()
    chat=update.effective_chat
    try:
        user=get_or_create_user(session,update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        if user.level<1:
            await update.message.reply_text("🔒 دریافت روب‌پوینت از سطح 1 باز می‌شود.",**reply_kwargs(update.message));return
        claim_cooldown = FOX_CLAIM_COOLDOWN
        if chat and is_group_chat_id(chat.id) and session.get(GroupChat, chat.id):
            claim_cooldown = max(30, FOX_CLAIM_COOLDOWN - CITY_CLAIM_COOLDOWN_BONUS)  # باف شهر: روب روب سریعتر
        left=seconds_left(user.last_fox_claim_at,claim_cooldown)
        if left:
            await update.message.reply_text(f"⏳ دریافت بعدی روب‌پوینت: {format_duration(left)} دیگر.",**reply_kwargs(update.message));return
        earned=random.randint(CLAIM_POINTS_MIN,CLAIM_POINTS_MAX)
        old_level=user.level
        user.fox_points+=earned;user.fox_total_earned+=earned;user.fox_claim_count=(user.fox_claim_count or 0)+1;user.last_fox_claim_at=now_utc()
        user.level=user_level_from_roobrub(user.fox_claim_count)
        rewards=apply_level_rewards(session,user,old_level,user.level)
        if chat: bump_city_stat(session, chat.id, chat.title, city_claim_total=1)
        session.commit()
        text=f"🦊 +{earned:,} روب‌پوینت دریافت کردی!\n💰 موجودی روب‌پوینت: {user.fox_points:,}\n🐾 روب روب‌ها: {user.fox_claim_count:,}\n⏱ دریافت بعدی: 5 دقیقه دیگر"
        if user.level>old_level: text += "\n\n"+level_up_message(old_level,user.level,rewards)
        await update.message.reply_text(text,**reply_kwargs(update.message))
    finally:session.close()
    if chat: await maybe_level_up_city(context, chat.id)

# ---------- تغییر نام روباه ----------

async def handle_bank_text(update, context):
    action=context.user_data.get('bank_action')
    if not action: return False
    context.user_data.pop('bank_action',None)
    if not await require_membership(update,context): return True
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user); account=session.query(BankAccount).filter(BankAccount.user_id==user.telegram_id).first()
        if not account: await update.message.reply_text('ابتدا بانک روبی را افتتاح کن.',**reply_kwargs(update.message)); return True
        if action=='deposit':
            amount=parse_amount(update.message.text)
            if amount<=0 or user.fox_points<amount: await update.message.reply_text('❌ روب‌پوینت کافی نیست.',**reply_kwargs(update.message)); return True
            user.fox_points-=amount; account.balance+=amount; session.add(BankTransaction(account_number=account.account_number,direction='deposit',amount=amount,description='واریز به بانک')); session.commit(); msg='➕ واریز انجام شد.'
        else:
            parts=update.message.text.split()
            if len(parts)!=2: raise ValueError
            amount=parse_amount(parts[0]); dest=parts[1]
            target=session.get(BankAccount,dest)
            if not target or target.user_id==user.telegram_id or amount<=0:
                raise ValueError
            left=seconds_left(account.last_card_transfer_at, BANK_CARD_TRANSFER_COOLDOWN)
            if left:
                await update.message.reply_text(
                    f'⏳ کارت به کارت بعدی {format_duration(left)} دیگر فعال می‌شود.',
                    **reply_kwargs(update.message)
                )
                return True
            fee=max(1, int(amount * BANK_CARD_TRANSFER_FEE_RATE))
            total=amount+fee
            if account.balance < total:
                await update.message.reply_text(
                    f'❌ موجودی بانک کافی نیست.\n💰 مبلغ انتقال: {amount:,}\n💳 کارمزد 5٪: {fee:,}\n📌 مجموع برداشت: {total:,} روب‌پوینت',
                    **reply_kwargs(update.message)
                )
                return True
            target_user=session.get(User,target.user_id)
            context.user_data['pending_bank_transfer']={
                'dest':dest,'amount':amount,'fee':fee,'total':total,
                'target_user_id':target.user_id
            }
            kb=InlineKeyboardMarkup([[
                InlineKeyboardButton('✅ بله',callback_data=f'bankconfirm:yes:{user.telegram_id}'),
                InlineKeyboardButton('❌ خیر',callback_data=f'bankconfirm:no:{user.telegram_id}')
            ]])
            msg=(f'🦊 کارت به کارت روبی 💳\n\n❓ آیا از انتقال اطمینان دارید؟\n\n'
                 f'💰 مبلغ دریافتی گیرنده: {amount:,} روب‌پوینت\n'
                 f'💳 کارمزد 5٪: {fee:,} روب‌پوینت\n'
                 f'📤 مجموع کسر از بانک: {total:,} روب‌پوینت\n'
                 f'💳 حساب مقصد: {dest}\n👤 گیرنده: {user_display_name(target_user)}\n'
                 f'⏱ محدودیت: هر 5 دقیقه یک کارت به کارت')
            await update.message.reply_text(msg,reply_markup=kb,**reply_kwargs(update.message)); return True
    except Exception:
        session.rollback(); msg='❌ فرمت یا موجودی/حساب مقصد نادرست است.'
    finally: session.close()
    await update.message.reply_text(msg,**reply_kwargs(update.message)); return True

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
        if await guard_fox_sickness(update, context, session, user): return
        if user.level < FRIDGE_UNLOCK_LEVEL:
            await update.message.reply_text(f"❄️ یخچال روبی در سطح {FRIDGE_UNLOCK_LEVEL} باز می‌شود.", **reply_kwargs(update.message))
            return
        items = settle_all_fridge_items(session, user.telegram_id)
        session.commit()
        text = fridge_text(user, items)
        markup = fridge_keyboard(user, items)
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=markup, **reply_kwargs(update.message))


# ---------- کارخونه روبی ----------

def factory_is_admin_account(user):
    return int(user.telegram_id) in ADMIN_IDS


def factory_settle_orders(session, user_id):
    """سفارش‌هایی که زمانشون تموم شده رو فقط برمی‌گردونه؛ جمع‌آوریشون دستیه (دکمه‌ی برداشت)."""
    return (
        session.query(FactoryOrder)
        .filter(FactoryOrder.user_id == user_id, FactoryOrder.collected == 0)
        .order_by(FactoryOrder.id.asc())
        .all()
    )


def factory_active_order_for_item(session, user_id, item_key):
    """اگه از این محصول یک سفارش تمام‌نشده (هنوز جمع‌آوری‌نشده) داشته باشه برش می‌گردونه."""
    return (
        session.query(FactoryOrder)
        .filter(FactoryOrder.user_id == user_id, FactoryOrder.item_key == item_key, FactoryOrder.collected == 0)
        .order_by(FactoryOrder.id.asc())
        .first()
    )


def factory_storage_used(orders):
    return sum(int(o.quantity or 0) for o in orders)


def factory_is_ready(user):
    if not user.factory_built:
        return False
    if factory_is_admin_account(user):
        return True
    if not user.factory_build_started_at:
        return False
    return (now_utc() - aware(user.factory_build_started_at)).total_seconds() >= FACTORY_BUILD_SECONDS


def factory_build_remaining(user):
    if not user.factory_build_started_at:
        return 0
    return seconds_left(user.factory_build_started_at, FACTORY_BUILD_SECONDS)


def factory_produced_total_of(user):
    if factory_is_admin_account(user):
        return max(int(user.factory_produced_total or 0), FACTORY_TIERS[-1]["unlock_produced"])
    return int(user.factory_produced_total or 0)


def factory_intro_text(user):
    return (
        "🦊 کارخونه روبی 🏭\n\n"
        f"از سطح {FACTORY_UNLOCK_LEVEL} می‌تونی کارخونه‌ی خودتو تعمیر کنی و ازش تولید و فروش داشته باشی.\n\n"
        f"💰 هزینه‌ی تعمیر: {FACTORY_BUILD_COST:,} روب‌پوینت\n"
        f"⏳ زمان آماده‌سازی بعد از تعمیر: {format_duration(FACTORY_BUILD_SECONDS)}"
    )


def factory_building_text(user):
    remaining = factory_build_remaining(user)
    return (
        "🔧 کارخونه روبی در حال تعمیره...\n\n"
        f"⏳ تا افتتاح: {format_duration(remaining)}"
    )


def factory_panel_text(user, orders):
    used = factory_storage_used(orders)
    storage_level = max(1, min(FACTORY_STORAGE_MAX_LEVEL, int(user.factory_storage_level or 1)))
    workers_level = max(1, min(FACTORY_WORKERS_MAX_LEVEL, int(user.factory_workers_level or 1)))
    machine_level = max(1, min(FACTORY_MACHINE_MAX_LEVEL, int(user.factory_machine_level or 1)))
    capacity = factory_storage_capacity(storage_level)
    workers_cap = factory_workers_capacity(workers_level)
    active_count = len(orders)
    hours_100 = factory_machine_hours_for_100(machine_level)
    produced = factory_produced_total_of(user)
    return (
        "🦊 کارخونه روبی 🏭\n\n"
        f"💼 مدیر کارخونه : {user_display_name(user)}\n\n"
        "🧳 انبار کارخونه\n"
        f"┘─ 🔺 ظرفیت انبار : {used:,} / {capacity:,} محصول\n"
        f"┘─ ⭐️ سطح : {storage_level}\n\n"
        "🤒 کارگران کارخونه\n"
        f"┘─ 🦊 تعداد کارگران : {active_count} / {workers_cap} روباه\n"
        f"┘─ ⭐️ سطح : {workers_level}\n\n"
        "🖨 دستگاه های تولید\n"
        f"┘─ ⏳ زمان تولید محصول (۱۰۰٪) : {format_duration(hours_100 * 3600)}\n"
        f"┘─ ⭐️ سطح : {machine_level}\n\n"
        f"🌟 سطح کارخونه : {machine_level}\n"
        f"‏┘─ 🌡{produced:,} محصول تولید شده\n\n"
        "🧮 شما درحال مدیریت کارخانه خود میباشید."
    )


def factory_home_keyboard(owner_id, orders=None):
    rows = []
    if orders:
        for o in orders:
            remaining = seconds_left(o.started_at, (aware(o.ready_at) - aware(o.started_at)).total_seconds())
            if remaining <= 0:
                info = FACTORY_ITEM_INDEX.get(o.item_key, {"name": o.item_key})
                rows.append([InlineKeyboardButton(
                    f"📦 برداشت {o.item_key} {info['name']} ({o.quantity:,} عدد)",
                    callback_data=f"factory:collect:{o.id}:{owner_id}"
                )])
    rows += [
        [InlineKeyboardButton("تولید🪄", callback_data=f"factory:menu:production:{owner_id}")],
        [InlineKeyboardButton("📦 انبار محصول (فروش)", callback_data=f"factory:wh:0:{owner_id}")],
        [InlineKeyboardButton("کارکنان🦊", callback_data=f"factory:menu:workers:{owner_id}")],
        [InlineKeyboardButton("انبار🛖", callback_data=f"factory:menu:storage:{owner_id}")],
        [InlineKeyboardButton("دستگاه های تولید 🖨", callback_data=f"factory:menu:machine:{owner_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def factory_get_or_create_market_price(session, item_key):
    """قیمت روز یک محصول رو برمی‌گردونه؛ اگه هنوز ردیفی نداشته باشه، با سقف قیمت قبلی می‌سازدش."""
    row = session.get(MarketPrice, item_key)
    if row:
        return row
    info = FACTORY_ITEM_INDEX.get(item_key, {})
    ceiling = int(info.get("sell") or 1)
    price = factory_market_roll_price(ceiling)
    row = MarketPrice(item_key=item_key, price=price, high_price=price, low_price=price, updated_at=now_utc())
    session.add(row)
    session.commit()
    return row


def factory_warehouse_text(user, session):
    produced = factory_produced_total_of(user)
    unlocked_tiers = factory_unlocked_tiers(produced)
    inv_rows = session.query(FactoryInventory).filter(FactoryInventory.user_id == user.telegram_id).all()
    inv_map = {r.item_key: int(r.quantity or 0) for r in inv_rows}
    lines = ["📦 انبار و بازار کارخونه", "", "قیمت هر محصول هر ۲۵ دقیقه یک بار تو بازار تغییر می‌کنه.", ""]
    for t in unlocked_tiers:
        lines.append(t["title"])
        for emoji, name, cost, sell in t["items"]:
            price_row = factory_get_or_create_market_price(session, emoji)
            qty = inv_map.get(emoji, 0)
            lines.append(
                f"┘─ {emoji} {name} | موجودی: {qty:,} | 💰 قیمت الان: {price_row.price:,} | "
                f"📈 بیشترین قیمت: {price_row.high_price:,} | 📉 کمترین قیمت: {price_row.low_price:,}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def factory_warehouse_keyboard(user, session, owner_id):
    produced = factory_produced_total_of(user)
    unlocked_tiers = factory_unlocked_tiers(produced)
    inv_rows = session.query(FactoryInventory).filter(
        FactoryInventory.user_id == user.telegram_id, FactoryInventory.quantity > 0
    ).all()
    inv_map = {r.item_key: int(r.quantity or 0) for r in inv_rows}
    rows = []
    for t in unlocked_tiers:
        for emoji, name, cost, sell in t["items"]:
            qty = inv_map.get(emoji, 0)
            if qty > 0:
                rows.append([InlineKeyboardButton(
                    f"💰 فروش {emoji} {name} ({qty:,} عدد)", callback_data=f"factory:sell:{emoji}:{owner_id}"
                )])
    if inv_map:
        rows.append([InlineKeyboardButton("💰 فروش کل انبار", callback_data=f"factory:sellall:0:{owner_id}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:home:0:{owner_id}")])
    return InlineKeyboardMarkup(rows)


def factory_build_keyboard(owner_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        f"🔧 تعمیر کارخونه ({FACTORY_BUILD_COST:,} روب‌پوینت)", callback_data=f"factory:build:0:{owner_id}"
    )]])


def factory_production_menu_text(user):
    produced = factory_produced_total_of(user)
    lines = ["🪄 خط‌های تولید کارخونه:", ""]
    for t in FACTORY_TIERS:
        if produced >= t["unlock_produced"]:
            lines.append(f"✅ {t['title']}")
        else:
            lines.append(f"🔒 {t['title']} (نیازمند {t['unlock_produced']:,} محصول تولیدشده)")
    return "\n".join(lines)


def factory_production_menu_keyboard(user, owner_id):
    produced = factory_produced_total_of(user)
    rows = []
    for t in FACTORY_TIERS:
        if produced >= t["unlock_produced"]:
            rows.append([InlineKeyboardButton(t["title"], callback_data=f"factory:tier:{t['key']}:{owner_id}")])
        else:
            rows.append([InlineKeyboardButton(f"🔒 {t['title']}", callback_data=f"factory:locked:0:{owner_id}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:home:0:{owner_id}")])
    return InlineKeyboardMarkup(rows)


def factory_tier_text(tier):
    lines = [f"{tier['title']}", "", "یکی از محصولات این خط تولید رو انتخاب کن:", ""]
    for emoji, name, cost, sell in tier["items"]:
        lines.append(f"{emoji} {name} | ساخت هر عدد: {cost:,} روب‌پوینت | سقف فروش هر عدد: {sell:,} روب‌پوینت")
    return "\n".join(lines)


def factory_tier_keyboard(tier, owner_id):
    rows = [[InlineKeyboardButton(f"{emoji} {name}", callback_data=f"factory:item:{tier['key']}:{emoji}:{owner_id}")]
            for emoji, name, cost, sell in tier["items"]]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:menu:production:{owner_id}")])
    return InlineKeyboardMarkup(rows)


def factory_item_text(item_key, user):
    info = FACTORY_ITEM_INDEX[item_key]
    storage_level = max(1, min(FACTORY_STORAGE_MAX_LEVEL, int(user.factory_storage_level or 1)))
    machine_level = max(1, min(FACTORY_MACHINE_MAX_LEVEL, int(user.factory_machine_level or 1)))
    lines = [f"{item_key} {info['name']}", ""]
    for p in FACTORY_PERCENT_OPTIONS:
        plan = factory_order_plan(item_key, p, storage_level, machine_level)
        lines.append(
            f"┘─ {p}٪ : {plan['quantity']:,} عدد | هزینه: {plan['cost']:,} روب‌پوینت | "
            f"زمان: {format_duration(plan['seconds'])} | ارزش فروش: {plan['sell_total']:,} روب‌پوینت"
        )
    return "\n".join(lines)


def factory_item_keyboard(tier_key, item_key, owner_id):
    row = [InlineKeyboardButton(f"{p}٪", callback_data=f"factory:pct:{tier_key}:{item_key}:{p}:{owner_id}")
           for p in FACTORY_PERCENT_OPTIONS]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:tier:{tier_key}:{owner_id}")]])


def factory_progress_bar(percent, length=5):
    percent = max(0, min(100, int(percent or 0)))
    filled = max(0, min(length, round(percent / 100 * length)))
    return "▰" * filled + "▱" * (length - filled)


def factory_producing_status_text(user, order):
    info = FACTORY_ITEM_INDEX.get(order.item_key, {"name": order.item_key})
    total_seconds = max(1, (aware(order.ready_at) - aware(order.started_at)).total_seconds())
    remaining = seconds_left(order.started_at, total_seconds)
    percent = int(round((total_seconds - remaining) / total_seconds * 100))
    percent = max(0, min(100, percent))
    bar = factory_progress_bar(percent)
    remaining_text = "تکمیل شد ✅" if remaining <= 0 else format_duration(remaining)
    return (
        "🦊 کارخونه روبی 🏭\n\n"
        f"💼 مدیر کارخونه : {user_display_name(user)}\n\n"
        f"✨ درحال تولید {order.item_key} {info['name']} ..\n"
        f"┘─ ⏳ زمان باقی مانده : {remaining_text}\n"
        f"┘─ ✅ تکمیل شده : {bar} | {percent}%\n\n"
        "❗️ شما درحال تولید این محصول هستی؛ از هر محصول فقط یک سفارش هم‌زمان ممکنه.\n\n"
        "❓ آیا از لغو تولید این محصول مطمئنی؟ (روب‌پوینتش کامل بهت برمی‌گرده)"
    )


def factory_producing_status_keyboard(order, owner_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ بله", callback_data=f"factory:cancelorder:{order.id}:{owner_id}"),
            InlineKeyboardButton("❌ خیر", callback_data=f"factory:home:0:{owner_id}"),
        ]
    ])


def factory_orders_text(orders):
    if not orders:
        return "\n\nفعلاً هیچ سفارش تولیدی در جریان نیست."
    lines = ["", "📦 سفارش‌های تولید:"]
    for o in orders:
        info = FACTORY_ITEM_INDEX.get(o.item_key, {"name": o.item_key})
        remaining = seconds_left(o.started_at, (aware(o.ready_at) - aware(o.started_at)).total_seconds())
        if remaining <= 0:
            state = "✅ آماده‌ی برداشت"
        else:
            state = f"⏳ {format_duration(remaining)} مانده"
        lines.append(f"┘─ {o.item_key} {info['name']} × {o.quantity:,} — {state}")
    return "\n".join(lines)


def factory_orders_keyboard(orders, owner_id):
    rows = []
    for o in orders:
        remaining = seconds_left(o.started_at, (aware(o.ready_at) - aware(o.started_at)).total_seconds())
        if remaining <= 0:
            info = FACTORY_ITEM_INDEX.get(o.item_key, {"name": o.item_key})
            rows.append([InlineKeyboardButton(
                f"💰 برداشت {o.item_key} {info['name']} ({o.sell_total:,} روب‌پوینت)",
                callback_data=f"factory:collect:{o.id}:{owner_id}"
            )])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:home:0:{owner_id}")])
    return InlineKeyboardMarkup(rows)


def factory_upgrade_text(kind, user):
    if kind == "storage":
        level = max(1, min(FACTORY_STORAGE_MAX_LEVEL, int(user.factory_storage_level or 1)))
        cap = factory_storage_capacity(level)
        cost = factory_upgrade_cost(level, FACTORY_STORAGE_MAX_LEVEL)
        title = "🧳 انبار کارخونه"
        cur = f"ظرفیت فعلی: {cap:,} محصول"
        nxt = f"ظرفیت بعدی: {factory_storage_capacity(level + 1):,} محصول" if cost else ""
    elif kind == "workers":
        level = max(1, min(FACTORY_WORKERS_MAX_LEVEL, int(user.factory_workers_level or 1)))
        cap = factory_workers_capacity(level)
        cost = factory_upgrade_cost(level, FACTORY_WORKERS_MAX_LEVEL)
        title = "🤒 کارگران کارخونه"
        cur = f"تعداد کارگر فعلی: {cap} روباه"
        nxt = f"تعداد کارگر بعدی: {factory_workers_capacity(level + 1)} روباه" if cost else ""
    else:
        level = max(1, min(FACTORY_MACHINE_MAX_LEVEL, int(user.factory_machine_level or 1)))
        hours = factory_machine_hours_for_100(level)
        cost = factory_upgrade_cost(level, FACTORY_MACHINE_MAX_LEVEL)
        title = "🖨 دستگاه های تولید"
        cur = f"زمان تولید ۱۰۰٪ فعلی: {format_duration(hours * 3600)}"
        nxt = f"زمان تولید ۱۰۰٪ بعدی: {format_duration(factory_machine_hours_for_100(level + 1) * 3600)}" if cost else ""
    lines = [title, "", f"⭐ سطح فعلی: {level}", cur]
    if cost:
        lines += ["", nxt, f"💰 هزینه‌ی ارتقا: {cost:,} روب‌پوینت"]
    else:
        lines += ["", "✨ این بخش در آخرین سطح ممکنه."]
    return "\n".join(lines)


def factory_upgrade_keyboard(kind, user, owner_id):
    max_level = {"storage": FACTORY_STORAGE_MAX_LEVEL, "workers": FACTORY_WORKERS_MAX_LEVEL, "machine": FACTORY_MACHINE_MAX_LEVEL}[kind]
    level_attr = {"storage": "factory_storage_level", "workers": "factory_workers_level", "machine": "factory_machine_level"}[kind]
    level = max(1, min(max_level, int(getattr(user, level_attr) or 1)))
    rows = []
    cost = factory_upgrade_cost(level, max_level)
    if cost:
        rows.append([InlineKeyboardButton(f"⭐ ارتقا ({cost:,} روب‌پوینت)", callback_data=f"factory:upg:{kind}:{owner_id}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"factory:home:0:{owner_id}")])
    return InlineKeyboardMarkup(rows)


async def update_market_prices_job(context):
    """هر ۲۵ دقیقه قیمت همه‌ی محصولات کارخونه رو تصادفی توی بازه‌ی مجاز عوض می‌کند."""
    session = get_session()
    try:
        for item_key, info in FACTORY_ITEM_INDEX.items():
            ceiling = int(info.get("sell") or 1)
            new_price = factory_market_roll_price(ceiling)
            row = session.get(MarketPrice, item_key)
            if not row:
                row = MarketPrice(
                    item_key=item_key, price=new_price, high_price=new_price, low_price=new_price, updated_at=now_utc()
                )
                session.add(row)
            else:
                row.price = new_price
                row.high_price = max(int(row.high_price or new_price), new_price)
                row.low_price = min(int(row.low_price or new_price), new_price)
                row.updated_at = now_utc()
        session.commit()
    except Exception as e:
        logger.exception("update_market_prices_job failed: %s", e)
        session.rollback()
    finally:
        session.close()


async def factory_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if user.level < FACTORY_UNLOCK_LEVEL:
            await update.message.reply_text(
                f"🏭 کارخونه روبی از سطح {FACTORY_UNLOCK_LEVEL} باز می‌شود.\n⭐ سطح فعلی تو: {user.level}",
                **reply_kwargs(update.message)
            )
            return
        if factory_is_admin_account(user) and not user.factory_built:
            user.factory_built = 1
            user.factory_build_started_at = now_utc() - timedelta(seconds=FACTORY_BUILD_SECONDS)
            session.commit()
        if not user.factory_built:
            text, markup = factory_intro_text(user), factory_build_keyboard(user.telegram_id)
        elif not factory_is_ready(user):
            text, markup = factory_building_text(user), None
        else:
            orders = factory_settle_orders(session, user.telegram_id)
            text = factory_panel_text(user, orders) + factory_orders_text(orders)
            markup = factory_home_keyboard(user.telegram_id, orders)
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=markup, **reply_kwargs(update.message))


async def factory_button(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    try:
        owner_id = int(parts[-1])
    except Exception:
        await q.answer()
        return
    if q.from_user.id != owner_id:
        await q.answer("⛔ این کارخونه برای کاربر دیگری است.", show_alert=True)
        return
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = session.get(User, owner_id)
        if not user:
            await q.answer("کاربر پیدا نشد.", show_alert=True)
            return
        if user.level < FACTORY_UNLOCK_LEVEL:
            await q.answer(f"🏭 کارخونه روبی از سطح {FACTORY_UNLOCK_LEVEL} باز می‌شود.", show_alert=True)
            return
        action = parts[1]

        if action == "locked":
            await q.answer("🔒 این خط تولید هنوز باز نشده.", show_alert=True)
            return

        if action == "build":
            if user.factory_built:
                await q.answer("کارخونه قبلاً تعمیر شده.", show_alert=True)
                return
            if (user.fox_points or 0) < FACTORY_BUILD_COST:
                await q.answer(f"روب‌پوینت کافی نیست. {FACTORY_BUILD_COST:,} روب‌پوینت لازم داری.", show_alert=True)
                return
            user.fox_points -= FACTORY_BUILD_COST
            user.factory_built = 1
            user.factory_build_started_at = now_utc()
            session.commit()
            await q.answer("🔧 تعمیر کارخونه شروع شد!", show_alert=True)
            await q.message.edit_text(factory_building_text(user), reply_markup=None)
            return

        if not user.factory_built:
            await q.answer("هنوز کارخونه رو تعمیر نکردی.", show_alert=True)
            return
        if not factory_is_ready(user):
            await q.answer("کارخونه هنوز آماده‌ی افتتاح نیست.", show_alert=True)
            await q.message.edit_text(factory_building_text(user), reply_markup=None)
            return

        if action == "home":
            orders = factory_settle_orders(session, user.telegram_id)
            await q.answer()
            await q.message.edit_text(
                factory_panel_text(user, orders) + factory_orders_text(orders),
                reply_markup=factory_home_keyboard(owner_id, orders)
            )
            return

        if action == "menu":
            kind = parts[2]
            if kind == "production":
                await q.answer()
                await q.message.edit_text(factory_production_menu_text(user), reply_markup=factory_production_menu_keyboard(user, owner_id))
            elif kind in ("storage", "workers", "machine"):
                await q.answer()
                await q.message.edit_text(factory_upgrade_text(kind, user), reply_markup=factory_upgrade_keyboard(kind, user, owner_id))
            return

        if action == "tier":
            tier_key = parts[2]
            tier = FACTORY_TIERS_BY_KEY.get(tier_key)
            produced = factory_produced_total_of(user)
            if not tier or produced < tier["unlock_produced"]:
                await q.answer("🔒 این خط تولید هنوز باز نشده.", show_alert=True)
                return
            await q.answer()
            await q.message.edit_text(factory_tier_text(tier), reply_markup=factory_tier_keyboard(tier, owner_id))
            return

        if action == "item":
            tier_key, item_key = parts[2], parts[3]
            tier = FACTORY_TIERS_BY_KEY.get(tier_key)
            produced = factory_produced_total_of(user)
            if not tier or produced < tier["unlock_produced"] or item_key not in FACTORY_ITEM_INDEX:
                await q.answer("🔒 این خط تولید هنوز باز نشده.", show_alert=True)
                return
            active_order = factory_active_order_for_item(session, owner_id, item_key)
            await q.answer()
            if active_order:
                await q.message.edit_text(
                    factory_producing_status_text(user, active_order),
                    reply_markup=factory_producing_status_keyboard(active_order, owner_id)
                )
                return
            await q.message.edit_text(factory_item_text(item_key, user), reply_markup=factory_item_keyboard(tier_key, item_key, owner_id))
            return

        if action == "pct":
            tier_key, item_key, percent_s = parts[2], parts[3], parts[4]
            tier = FACTORY_TIERS_BY_KEY.get(tier_key)
            produced = factory_produced_total_of(user)
            if not tier or produced < tier["unlock_produced"] or item_key not in FACTORY_ITEM_INDEX:
                await q.answer("🔒 این خط تولید هنوز باز نشده.", show_alert=True)
                return
            active_order = factory_active_order_for_item(session, owner_id, item_key)
            if active_order:
                await q.answer("⏳ از این محصول همین الان یک سفارش در حال تولیده.", show_alert=True)
                await q.message.edit_text(
                    factory_producing_status_text(user, active_order),
                    reply_markup=factory_producing_status_keyboard(active_order, owner_id)
                )
                return
            orders = factory_settle_orders(session, user.telegram_id)
            workers_level = max(1, min(FACTORY_WORKERS_MAX_LEVEL, int(user.factory_workers_level or 1)))
            workers_cap = factory_workers_capacity(workers_level)
            if len(orders) >= workers_cap:
                await q.answer("🦊 همه‌ی کارگرها مشغول‌اند. یک سفارش رو برداشت کن یا کارگر بیشتری استخدام کن.", show_alert=True)
                return
            storage_level = max(1, min(FACTORY_STORAGE_MAX_LEVEL, int(user.factory_storage_level or 1)))
            machine_level = max(1, min(FACTORY_MACHINE_MAX_LEVEL, int(user.factory_machine_level or 1)))
            plan = factory_order_plan(item_key, int(percent_s), storage_level, machine_level)
            capacity = factory_storage_capacity(storage_level)
            used = factory_storage_used(orders)
            if used + plan["quantity"] > capacity:
                await q.answer("🧳 انبار کارخونه جا نداره. اول انبار رو ارتقا بده یا سفارش‌های آماده رو بردار.", show_alert=True)
                return
            if (user.fox_points or 0) < plan["cost"]:
                await q.answer(f"روب‌پوینت کافی نیست. {plan['cost']:,} روب‌پوینت لازم داری.", show_alert=True)
                return
            user.fox_points -= plan["cost"]
            order = FactoryOrder(
                user_id=user.telegram_id, tier_key=tier_key, item_key=item_key, percent=int(percent_s),
                quantity=plan["quantity"], cost_paid=plan["cost"], sell_total=plan["sell_total"],
                started_at=now_utc(), ready_at=now_utc() + timedelta(seconds=plan["seconds"]), collected=0,
            )
            session.add(order)
            session.commit()
            orders = factory_settle_orders(session, user.telegram_id)
            await q.answer(f"🏭 تولید {item_key} شروع شد!", show_alert=True)
            await q.message.edit_text(
                factory_panel_text(user, orders) + factory_orders_text(orders),
                reply_markup=factory_home_keyboard(owner_id, orders)
            )
            return

        if action == "collect":
            order_id = int(parts[2])
            order = session.get(FactoryOrder, order_id)
            if not order or order.user_id != owner_id or order.collected:
                await q.answer("این سفارش دیگر در دسترس نیست.", show_alert=True)
                return
            if now_utc() < aware(order.ready_at):
                await q.answer("⏳ هنوز آماده نشده.", show_alert=True)
                return
            order.collected = 1
            inv = session.get(FactoryInventory, (owner_id, order.item_key))
            if inv:
                inv.quantity = int(inv.quantity or 0) + order.quantity
            else:
                inv = FactoryInventory(user_id=owner_id, item_key=order.item_key, quantity=order.quantity)
                session.add(inv)
            user.factory_produced_total = int(user.factory_produced_total or 0) + order.quantity
            session.commit()
            orders = factory_settle_orders(session, user.telegram_id)
            info = FACTORY_ITEM_INDEX.get(order.item_key, {"name": order.item_key})
            await q.answer(f"📦 {order.quantity:,} عدد {info['name']} به انبار محصول اضافه شد!", show_alert=True)
            await q.message.edit_text(
                f"📦 {order.item_key} {info['name']} × {order.quantity:,} به انبار محصول اضافه شد.\n"
                "برای فروش با قیمت روز بازار، وارد «📦 انبار محصول» شو.\n\n"
                + factory_panel_text(user, orders) + factory_orders_text(orders),
                reply_markup=factory_home_keyboard(owner_id, orders)
            )
            return

        if action == "cancelorder":
            order_id = int(parts[2])
            order = session.get(FactoryOrder, order_id)
            if not order or order.user_id != owner_id or order.collected:
                cur_orders = factory_settle_orders(session, user.telegram_id)
                await q.answer("این سفارش دیگر در دسترس نیست.", show_alert=True)
                await q.message.edit_text(
                    factory_panel_text(user, cur_orders) + factory_orders_text(cur_orders),
                    reply_markup=factory_home_keyboard(owner_id, cur_orders)
                )
                return
            info = FACTORY_ITEM_INDEX.get(order.item_key, {"name": order.item_key})
            refund = int(order.cost_paid or 0)
            user.fox_points = (user.fox_points or 0) + refund
            session.delete(order)
            session.commit()
            orders = factory_settle_orders(session, user.telegram_id)
            await q.answer(f"❌ تولید {info['name']} لغو شد؛ {refund:,} روب‌پوینت برگشت.", show_alert=True)
            await q.message.edit_text(
                factory_panel_text(user, orders) + factory_orders_text(orders),
                reply_markup=factory_home_keyboard(owner_id, orders)
            )
            return

        if action == "wh":
            await q.answer()
            await q.message.edit_text(
                factory_warehouse_text(user, session),
                reply_markup=factory_warehouse_keyboard(user, session, owner_id)
            )
            return

        if action == "sell":
            item_key = parts[2]
            inv = session.get(FactoryInventory, (owner_id, item_key))
            qty = int(inv.quantity or 0) if inv else 0
            if qty <= 0:
                await q.answer("از این محصول چیزی تو انبار نداری.", show_alert=True)
                return
            price_row = factory_get_or_create_market_price(session, item_key)
            total = qty * int(price_row.price)
            inv.quantity = 0
            user.fox_points = (user.fox_points or 0) + total
            session.commit()
            info = FACTORY_ITEM_INDEX.get(item_key, {"name": item_key})
            await q.answer(f"💰 {qty:,} عدد {info['name']} به قیمت {price_row.price:,} فروخته شد؛ +{total:,} روب‌پوینت!", show_alert=True)
            await q.message.edit_text(
                factory_warehouse_text(user, session),
                reply_markup=factory_warehouse_keyboard(user, session, owner_id)
            )
            return

        if action == "sellall":
            inv_rows = session.query(FactoryInventory).filter(
                FactoryInventory.user_id == owner_id, FactoryInventory.quantity > 0
            ).all()
            if not inv_rows:
                await q.answer("انبار محصولت خالیه.", show_alert=True)
                return
            total = 0
            for inv in inv_rows:
                price_row = factory_get_or_create_market_price(session, inv.item_key)
                total += int(inv.quantity) * int(price_row.price)
                inv.quantity = 0
            user.fox_points = (user.fox_points or 0) + total
            session.commit()
            await q.answer(f"💰 کل انبار فروخته شد؛ +{total:,} روب‌پوینت!", show_alert=True)
            await q.message.edit_text(
                factory_warehouse_text(user, session),
                reply_markup=factory_warehouse_keyboard(user, session, owner_id)
            )
            return

        if action == "upg":
            kind = parts[2]
            max_level = {"storage": FACTORY_STORAGE_MAX_LEVEL, "workers": FACTORY_WORKERS_MAX_LEVEL, "machine": FACTORY_MACHINE_MAX_LEVEL}[kind]
            level_attr = {"storage": "factory_storage_level", "workers": "factory_workers_level", "machine": "factory_machine_level"}[kind]
            level = max(1, min(max_level, int(getattr(user, level_attr) or 1)))
            cost = factory_upgrade_cost(level, max_level)
            if not cost:
                await q.answer("✨ این بخش در آخرین سطح ممکنه.", show_alert=True)
                return
            if (user.fox_points or 0) < cost:
                await q.answer(f"روب‌پوینت کافی نیست. {cost:,} روب‌پوینت لازم داری.", show_alert=True)
                return
            user.fox_points -= cost
            setattr(user, level_attr, level + 1)
            session.commit()
            await q.answer("⭐ ارتقا با موفقیت انجام شد!", show_alert=True)
            await q.message.edit_text(factory_upgrade_text(kind, user), reply_markup=factory_upgrade_keyboard(kind, user, owner_id))
            return
    finally:
        session.close()
    await q.answer()


# ---------- روباه زخمی در گپ ----------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INJURED_FOX_TRAPPED_IMAGE = os.path.join(BASE_DIR, "injured_fox_trapped.png")
INJURED_FOX_RESCUED_IMAGE = os.path.join(BASE_DIR, "injured_fox_rescued.png")


def injured_fox_keyboard(event_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🦊 نجات", callback_data=f"injured:rescue:{event_id}")]
    ])


def injured_fox_text(attempts=0):
    return (
        "🦊 روباه زخمی پیدا شده، کسی نیست نجاتش بده 😢\n\n"
        f"🛟 تلاش‌ها: {attempts}/3\n"
        f"💰 هزینه هر تلاش: {INJURED_FOX_COST} روب‌پوینت"
    )



async def bot_joined_group(update, context):
    cm = update.my_chat_member
    if not cm or cm.chat.type not in ("group", "supergroup"):
        return
    if cm.new_chat_member.status not in ("member", "administrator"):
        return
    old_status = cm.old_chat_member.status if cm.old_chat_member else None
    # فقط زمانی که ربات تازه به گروه اضافه شده (نه صرفا ارتقا به ادمین) تعداد اعضا چک می‌شود.
    if old_status in (None, "left", "kicked"):
        member_count = None
        try:
            member_count = await context.bot.get_chat_member_count(cm.chat.id)
        except Exception as e:
            logger.warning("get_chat_member_count failed: %s", e)
        if member_count is not None and member_count <= MIN_GROUP_MEMBERS:
            try:
                await context.bot.send_message(
                    chat_id=cm.chat.id,
                    text=(
                        f"🦊 ببخشید، روباهیو فقط توی گروه‌های بالای {MIN_GROUP_MEMBERS} نفر فعالیت می‌کنه.\n"
                        f"این گروه الان {member_count} عضو داره.\n"
                        "هروقت گروهت بزرگ‌تر شد، دوباره اضافه‌م کن! 🌸"
                    ),
                )
            except Exception:
                pass
            try:
                await context.bot.leave_chat(cm.chat.id)
            except Exception as e:
                logger.warning("leave_chat failed: %s", e)
            return
    session = get_session()
    try:
        row = session.get(GroupChat, cm.chat.id)
        if row is None:
            session.add(GroupChat(chat_id=cm.chat.id, title=cm.chat.title or "گپ", active=1))
            session.commit()
        else:
            row.active = 1
            row.title = cm.chat.title or row.title
            session.commit()
    finally:
        session.close()
    try:
        await context.bot.send_message(chat_id=cm.chat.id, text="یه روباه مکار و باهوش اینجاست 🦊 نمی‌خوای روب روب کنی براش💲🎃")
    except Exception:
        pass

async def register_group_chat(update, context):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    session = get_session()
    try:
        row = session.get(GroupChat, chat.id)
        is_new = row is None
        if row is None:
            row = GroupChat(chat_id=chat.id, title=chat.title or "گپ", active=1)
            session.add(row)
        else:
            row.title = chat.title or row.title
            row.active = 1
        session.commit()
        if is_new:
            try:
                await context.bot.send_message(chat_id=chat.id, text="یه روباه مکار و باهوش اینجاست 🦊 نمی‌خوای روب روب کنی براش💲🎃")
            except Exception:
                pass
    except Exception as e:
        session.rollback()
        logger.warning("register group failed: %s", e)
    finally:
        session.close()


async def post_injured_fox_job(context):
    session = get_session()
    try:
        chats = session.query(GroupChat).filter(GroupChat.active == 1).all()
        chat_ids = [c.chat_id for c in chats]
    finally:
        session.close()

    for chat_id in chat_ids:
        try:
            # هر 20 دقیقه یک روباه زخمی جدید در هر گپی که ربات در آن فعال دیده شده.
            required = random.randint(1, 4)  # 1/2/3 = نجات در همان تلاش؛ 4 = هر سه تلاش ناموفق
            session = get_session()
            try:
                event = InjuredFox(chat_id=chat_id, required_attempts=required, attempts=0, status="pending", attempt_log="")
                session.add(event)
                session.commit()
                event_id = event.id
            finally:
                session.close()

            with open(INJURED_FOX_TRAPPED_IMAGE, "rb") as photo:
                msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo),
                    caption=injured_fox_text(0),
                    reply_markup=injured_fox_keyboard(event_id),
                )
            session = get_session()
            try:
                event = session.get(InjuredFox, event_id)
                if event:
                    event.message_id = msg.message_id
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("post injured fox failed in %s: %s", chat_id, e)


async def injured_fox_button(update, context):
    q = update.callback_query
    try:
        _, action, event_id_s = q.data.split(":")
        event_id = int(event_id_s)
    except Exception:
        await q.answer("درخواست نامعتبر است.", show_alert=True)
        return
    if action != "rescue":
        return
    if not await require_membership(update, context):
        return

    session = get_session()
    try:
        event = session.get(InjuredFox, event_id)
        if event and event.status == "pending" and (now_utc() - aware(event.created_at)).total_seconds() > INJURED_FOX_EVENT_TIMEOUT:
            event.status = "dead"
            session.commit()
        if not event or event.status != "pending":
            await q.answer("این روباه دیگر قابل نجات نیست.", show_alert=True)
            return
        if event.attempts >= 3:
            await q.answer("تمام تلاش‌ها انجام شده است.", show_alert=True)
            return

        user = get_or_create_user(session, q.from_user)
        if (user.fox_points or 0) < INJURED_FOX_COST:
            await q.answer("❌ برای نجات روباه حداقل 10 روب‌پوینت لازم داری.", show_alert=True)
            return

        user.fox_points -= INJURED_FOX_COST
        event.attempts += 1
        attempt = event.attempts
        actor = user_display_name(user)
        log = (event.attempt_log or "")
        event.attempt_log = (log + "\n" if log else "") + f"تلاش {attempt}: {actor} (آیدی {user.telegram_id})"

        if attempt >= event.required_attempts and attempt <= 3:
            event.status = "rescued"
            event.rescuer_id = user.telegram_id
            user.fox_rescued_count = (user.fox_rescued_count or 0) + 1
            user.injured_fox_stock = (user.injured_fox_stock or 0) + 1
            reward = random.randint(INJURED_FOX_REWARD_MIN, INJURED_FOX_REWARD_MAX)
            claims = random.randint(1, INJURED_FOX_MAX_CLAIMS)
            user.fox_points += reward
            user.fox_claim_count = (user.fox_claim_count or 0) + claims
            bump_city_stat(session, event.chat_id, city_rescued_total=1, city_claim_total=claims)
            session.commit()
            rescuer_name = user_display_name(user)
            text = (
                f"🦊 روباه زخمی پس از {attempt} تلاش نجات پیدا کرد 😇🦊\n\n"
                f"👤 {rescuer_name} روباه زخمی را نجات داد.\n\n"
                f"💝 پاداش ⬇️\n"
                f"┘─ +{reward:,} روب‌پوینت 🪙\n"
                f"┘─ روباه زخمی برای شما {claims} بار روب روب کرد 🐾\n\n📋 تلاش‌ها:\n{event.attempt_log}"
            )
            message_id = event.message_id
        else:
            if attempt == 1:
                text = injured_fox_text(1) + f"\n\n🏹 شکارچی درحال نزدیک شدن است و روباه هنوز نجات پیدا نکرده 😢\n\n📋 تلاش‌ها:\n{event.attempt_log}"
            elif attempt == 2:
                text = injured_fox_text(2) + f"\n\n🐺 گله گرگ به روباه زخمی درحال نزدیک شدن است و کسی روباه زخمی را نجات نداد 😢\n\n📋 تلاش‌ها:\n{event.attempt_log}"
            else:
                event.status = "dead"
                text = f"💔 روباه در اثر افتادن در تله جان داد 😢\n\n📋 تلاش‌ها:\n{event.attempt_log}"
            session.commit()
            message_id = event.message_id
    finally:
        # مقادیر لازم را قبل از بستن session نگه می‌داریم؛ SQLAlchemy بعد از commit
        # ممکن است attributeهای event را expire کند.
        if event is None:
            final_status = "missing"
            final_chat_id = q.message.chat_id
            final_event_id = event_id
            final_message_id = None
        else:
            final_status = event.status
            final_chat_id = event.chat_id
            final_event_id = event.id
            final_message_id = message_id
        session.close()

    await q.answer("🦊 نجات موفق بود!" if final_status == "rescued" else "تلاش انجام شد.")
    try:
        if final_status == "rescued":
            # اول تلاش می‌کنیم همان پیام را از عکس «گرفتار» به عکس «نجات‌یافته»
            # تبدیل کنیم. برای بعضی نسخه‌ها/شرایط Telegram، ویرایش media ممکن
            # است خطا بدهد؛ در آن حالت حتماً fallback اجرا می‌شود تا کاربر
            # عکس نجات‌یافته + متن پاداش را از دست ندهد.
            try:
                with open(INJURED_FOX_RESCUED_IMAGE, "rb") as photo:
                    photo_input = InputFile(photo, filename=INJURED_FOX_RESCUED_IMAGE)
                    media = InputMediaPhoto(media=photo_input, caption=text)
                    await context.bot.edit_message_media(
                        chat_id=final_chat_id,
                        message_id=final_message_id,
                        media=media,
                        reply_markup=None,
                    )
            except Exception as edit_error:
                logger.warning("edit rescued fox media failed; using send fallback: %s", edit_error)
                # fallback مطمئن: پیام قدیمی را حذف و پیام نجات را با عکس دوم می‌فرستیم.
                try:
                    await context.bot.delete_message(
                        chat_id=final_chat_id, message_id=final_message_id
                    )
                except Exception as delete_error:
                    logger.warning("could not delete trapped fox message: %s", delete_error)
                with open(INJURED_FOX_RESCUED_IMAGE, "rb") as photo:
                    await context.bot.send_photo(
                        chat_id=final_chat_id,
                        photo=InputFile(photo, filename=INJURED_FOX_RESCUED_IMAGE),
                        caption=text,
                    )
        elif final_status == "dead":
            await context.bot.edit_message_caption(
                chat_id=final_chat_id,
                message_id=final_message_id,
                caption=text,
                reply_markup=None,
            )
        else:
            await context.bot.edit_message_caption(
                chat_id=final_chat_id,
                message_id=final_message_id,
                caption=text,
                reply_markup=injured_fox_keyboard(final_event_id),
            )
    except Exception as e:
        logger.warning("update injured fox message failed: %s", e)
    if final_status == "rescued":
        await maybe_level_up_city(context, final_chat_id)

# ---------- بانک روبی ----------

BANK_OPEN_COST = 5000
BANK_CHANGE_COST = 3000
BANK_INTEREST_RATE = 0.03
BANK_INTEREST_INTERVAL_SECONDS = 12 * 60 * 60

def ensure_bank(session, user):
    account = session.query(BankAccount).filter(BankAccount.user_id == user.telegram_id).first()
    if account is None:
        if (user.fox_points or 0) < BANK_OPEN_COST:
            return None, False
        user.fox_points -= BANK_OPEN_COST
        import secrets
        for _ in range(20):
            number = ''.join(str(secrets.randbelow(10)) for _ in range(12))
            if not session.get(BankAccount, number): break
        account = BankAccount(account_number=number, user_id=user.telegram_id, balance=0, last_interest_at=now_utc(), last_card_transfer_at=None)
        session.add(account)
        session.flush()
        session.add(BankTransaction(account_number=number, direction='fee', amount=BANK_OPEN_COST, description='افتتاح شعبه بانک'))
    return account, True

def apply_bank_interest(account, session):
    # سود 3 درصد به ازای هر 12 ساعت کامل؛ اگر چند بازه گذشته باشد، سود مرکب اعمال می‌شود.
    now = now_utc()
    if not account.last_interest_at:
        account.last_interest_at = now
        return 0
    elapsed=(now-aware(account.last_interest_at)).total_seconds()
    if elapsed < BANK_INTEREST_INTERVAL_SECONDS or account.balance <= 0:
        return 0
    periods=int(elapsed//BANK_INTEREST_INTERVAL_SECONDS)
    gain=int(account.balance*((1+BANK_INTEREST_RATE)**periods-1))
    if gain>0:
        account.balance += gain
        session.add(BankTransaction(
            account_number=account.account_number,
            direction='interest',
            amount=gain,
            description=f'سود بانکی {periods} بازه 12 ساعته'
        ))
    account.last_interest_at=now
    return gain

def bank_keyboard(account):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➖ برداشت',callback_data=f'bank:withdraw:{account.user_id}'), InlineKeyboardButton('➕ واریز',callback_data=f'bank:deposit:{account.user_id}')],
        [InlineKeyboardButton('💳 کارت به کارت روبی🦊',callback_data=f'bank:transfer:{account.user_id}'), InlineKeyboardButton('📃 تراکنش‌ها',callback_data=f'bank:transactions:{account.user_id}')],
        [InlineKeyboardButton('➿ تغییر حساب روبی',callback_data=f'bank:change:{account.user_id}')],
    ])

def bank_text(user, account):
    return (f'🦊 بانک روبی 🏦\n\n💳 شماره حساب : {account.account_number}\n👤 به نام : {user_display_name(user)}\n\n💰 موجودی حساب : {account.balance:,} 🪙\n\n🤑 سود بانکی\n┘─ 🛍 درصد سود : 3%\n┘─ 📥 مبلغ واریزی : بر اساس موجودی بانک\n┘─ ⏳ زمان واریز : هر 12 ساعت\n\n❗️ برای مدیریت حساب بانکی از گزینه‌های زیر استفاده کن.')

def parse_amount(raw):
    trans=str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    s=str(raw).strip().lower().translate(trans).replace(',','').replace('٬','').replace('٫','.')
    mult=1
    for suffix, factor in (("میل",1_000_000),("m",1_000_000),("م",1_000_000),("کی",1_000),("کا",1_000),("k",1_000)):
        if s.endswith(suffix):
            mult=factor; s=s[:-len(suffix)]; break
    if not s.isdigit(): raise ValueError
    return int(s)*mult


async def bank_command(update,context):
    if not await require_membership(update,context): return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if await guard_fox_sickness(update, context, session, user): return
        if user.level<4:
            await update.message.reply_text('🔒 بانک روبی از لول 4 باز می‌شود.',**reply_kwargs(update.message)); return
        account,ok=ensure_bank(session,user)
        if not ok:
            await update.message.reply_text('❌ برای افتتاح شعبه بانک 5,000 روب‌پوینت لازم داری.',**reply_kwargs(update.message)); return
        apply_bank_interest(account,session); session.commit(); text=bank_text(user,account); kb=bank_keyboard(account)
    finally: session.close()
    await update.message.reply_text(text,reply_markup=kb,**reply_kwargs(update.message))

async def bank_button(update,context):
    q=update.callback_query
    try: _,action,uid_s=q.data.split(':'); uid=int(uid_s)
    except: return
    if q.from_user.id!=uid: await q.answer('⛔ این پنل برای کاربر دیگری است.',show_alert=True); return
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user); account=session.query(BankAccount).filter(BankAccount.user_id==uid).first()
        if not account:
            await q.answer('ابتدا شعبه بانک را افتتاح کن.',show_alert=True); return
        apply_bank_interest(account,session); session.commit()
        if action=='withdraw':
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('25٪',callback_data=f'bank:w:{uid}:25'),InlineKeyboardButton('50٪',callback_data=f'bank:w:{uid}:50')],[InlineKeyboardButton('75٪',callback_data=f'bank:w:{uid}:75'),InlineKeyboardButton('100٪',callback_data=f'bank:w:{uid}:100')]])
            await q.answer(); await q.message.edit_text(bank_text(user,account)+'\n\n➖ درصد برداشت را انتخاب کن:',reply_markup=kb); return
        if action=='w': return
        if action=='deposit': context.user_data['bank_action']='deposit'; await q.answer(); await q.message.edit_text(bank_text(user,account)+'\n\n➕ مبلغ واریز را در جواب همین پنل بفرست.\nمثال: 50k / 50کا / 50میل / 50م / 50m'); return
        if action=='transfer': context.user_data['bank_action']='transfer'; await q.answer(); await q.message.edit_text(bank_text(user,account)+'\n\n🦊 کارت به کارت روبی 💳\n\n🔺 مبلغ و شماره حساب مقصد را در جواب همین پنل بفرست.\nمثال: 500 123456789000\n\n⏱ هر 5 دقیقه یک‌بار · کارمزد 5٪'); return
        if action=='transactions':
            rows=session.query(BankTransaction).filter(BankTransaction.account_number==account.account_number).order_by(BankTransaction.id.desc()).limit(10).all()
            txt='📃 آخرین تراکنش‌ها\n\n' + ('\n'.join(f"{r.created_at:%Y-%m-%d %H:%M} | {('به حساب ' + str(r.counterparty_user_id)) if r.direction in ('card_out','card_transfer_out') else ('از حساب ' + str(r.counterparty_user_id)) if r.counterparty_user_id else r.description or r.direction} | {r.amount:,} 🪙" for r in rows[:3]) if rows else 'تراکنشی ثبت نشده است.')
            await q.answer(); await q.message.edit_text(bank_text(user,account)+'\n\n'+txt,reply_markup=bank_keyboard(account)); return
        if action=='change':
            if user.fox_points < BANK_CHANGE_COST: await q.answer('❌ 3,000 روب‌پوینت لازم داری.',show_alert=True); return
            import secrets
            newnum=''.join(str(secrets.randbelow(10)) for _ in range(12))
            while session.get(BankAccount,newnum): newnum=''.join(str(secrets.randbelow(10)) for _ in range(12))
            oldnum=account.account_number
            user.fox_points-=BANK_CHANGE_COST
            account.account_number=newnum
            session.query(BankTransaction).filter(BankTransaction.account_number==oldnum).update({BankTransaction.account_number:newnum}, synchronize_session=False)
            session.commit(); await q.answer('✅ شماره حساب روبی تغییر کرد.'); return
    finally: session.close()

async def bank_transfer_confirm(update, context):
    q=update.callback_query
    try: _,action,uid_s=q.data.split(":"); uid=int(uid_s)
    except Exception: return
    if q.from_user.id!=uid:
        await q.answer("⛔ این تأیید برای کاربر دیگری است.",show_alert=True); return
    pending=context.user_data.get("pending_bank_transfer")
    if not pending:
        await q.answer("این انتقال دیگر فعال نیست.",show_alert=True); return
    if action=="no":
        context.user_data.pop("pending_bank_transfer",None)
        await q.answer("لغو شد."); await q.message.edit_text("❌ کارت به کارت لغو شد."); return
    session=get_session()
    try:
        user=session.get(User,uid); account=session.query(BankAccount).filter(BankAccount.user_id==uid).first()
        dest=pending['dest']; amount=int(pending['amount']); fee=int(pending.get('fee', max(1,int(amount*BANK_CARD_TRANSFER_FEE_RATE))))
        total=int(pending.get('total', amount+fee)); target=session.get(BankAccount,dest)
        if not user or not account or not target or target.user_id==uid:
            await q.answer("❌ حساب مبدأ یا مقصد نامعتبر است.",show_alert=True); return
        left=seconds_left(account.last_card_transfer_at, BANK_CARD_TRANSFER_COOLDOWN)
        if left:
            await q.answer(f"⏳ کارت به کارت بعدی {format_duration(left)} دیگر فعال می‌شود.",show_alert=True); return
        if account.balance<total:
            await q.answer("❌ موجودی بانک برای مبلغ + کارمزد کافی نیست.",show_alert=True); return
        target_user=session.get(User,target.user_id)
        account.balance-=total
        target.balance+=amount
        account.last_card_transfer_at=now_utc()
        session.add(BankTransaction(account_number=account.account_number,counterparty_account=dest,counterparty_user_id=target.user_id,direction='card_out',amount=amount,description=f'کارت به کارت (کارمزد 5٪: {fee:,})'))
        session.add(BankTransaction(account_number=account.account_number,direction='fee',amount=fee,description='کارمزد 5٪ کارت به کارت'))
        session.add(BankTransaction(account_number=dest,counterparty_account=account.account_number,counterparty_user_id=uid,direction='card_in',amount=amount,description='کارت به کارت'))
        session.commit(); context.user_data.pop('pending_bank_transfer',None)
        await q.answer("✅ کارت به کارت انجام شد!")
        await q.message.edit_text(
            f"✅ {amount:,} روب‌پوینت با موفقیت کارت به کارت شد.\n"
            f"💳 کارمزد 5٪: {fee:,}\n📤 مجموع کسرشده: {total:,}\n"
            f"💳 حساب مقصد: {dest}\n👤 گیرنده: {user_display_name(target_user)}\n"
            f"🏦 موجودی جدید بانک: {account.balance:,}\n⏱ کارت به کارت بعدی: 5 دقیقه دیگر"
        )
        await notify_user_private(context.bot, target_user.telegram_id, f"💳 {amount:,} روب‌پوینت به حساب روبی شما واریز شد.\n👤 فرستنده: {user_display_name(user)}\n💳 حساب شما: {dest}")
    finally: session.close()

async def bank_withdraw_button(update,context):
    q=update.callback_query
    _,_,uid_s,pct_s=q.data.split(':'); uid=int(uid_s); pct=int(pct_s)
    if q.from_user.id!=uid: await q.answer('⛔ این پنل برای تو نیست.',show_alert=True); return
    session=get_session()
    try:
        user=session.get(User,uid); account=session.query(BankAccount).filter(BankAccount.user_id==uid).first()
        amount=(account.balance*pct)//100
        if amount<=0: await q.answer('موجودی کافی نیست.',show_alert=True); return
        account.balance-=amount; user.fox_points+=amount; session.add(BankTransaction(account_number=account.account_number,direction='withdraw',amount=amount,description=f'برداشت {pct}%')); session.commit()
        await q.answer('برداشت انجام شد.'); await q.message.edit_text(bank_text(user,account),reply_markup=bank_keyboard(account))
    finally: session.close()

# ---------- فروشگاه گیفت روبی ----------

GIFT_TIERS = {
    "15": {
        "tier_label": "گیفت 15 استارزی",
        "price": 60000,
        "options": {
            "teddy": {"name": "تدی", "emoji": "🧸"},
            "heart": {"name": "قلب", "emoji": "💝"},
        },
    },
    "25": {
        "tier_label": "گیفت 25 استارزی",
        "price": 98000,
        "options": {
            "box": {"name": "کادو", "emoji": "🎁"},
            "rose": {"name": "گل رز", "emoji": "🌹"},
        },
    },
    "50": {
        "tier_label": "گیفت 50 استارزی",
        "price": 200000,
        "options": {
            "cake": {"name": "کیک", "emoji": "🎂"},
            "bouquet": {"name": "دسته گل", "emoji": "💐"},
            "rocket": {"name": "سفینه", "emoji": "🚀"},
            "champagne": {"name": "شامپاین", "emoji": "🍾"},
        },
    },
}
GIFT_CARD_NUMBER = "6219861851160068"
GIFT_CARD_OWNER = "ظریفی"
GIFT_CHANNEL_USERNAME = "@foxfrenzy_gift"
GIFT_MAX_QTY = 20
GIFT_NO_TEXT_KEYBOARD = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 بدون متن", callback_data="gift:notext:0:0")]])


def gift_option_label(tier, option_key):
    opt = GIFT_TIERS[tier]["options"][option_key]
    return f"{opt['emoji']} {opt['name']}"


def gift_shop_text():
    return "🎁 فروشگاه روبی\n\nیکی از بخش‌های زیر رو انتخاب کن ⬇️"


def gift_shop_keyboard():
    rows = [
        [InlineKeyboardButton("🦊 خرید روب پوینت", callback_data="points:shop:0:0")],
        [InlineKeyboardButton("🎁 خرید گیفت استارزی", callback_data="gift:tiers:0:0")],
    ]
    return InlineKeyboardMarkup(rows)


def gift_tiers_text():
    lines = ["🎁 خرید گیفت استارزی", "", "یکی از تعرفه‌های استارزی رو انتخاب کن ⬇️", ""]
    for tier in GIFT_TIERS.values():
        icons = " ".join(o["emoji"] for o in tier["options"].values())
        lines.append(f"┘─ {tier['tier_label']} {icons} — {tier['price']:,} تومان")
    return "\n".join(lines)


def gift_tiers_keyboard():
    rows = [
        [InlineKeyboardButton(f"{tier['tier_label']} ({tier['price']:,} تومان)", callback_data=f"gift:pick:{key}:0")]
        for key, tier in GIFT_TIERS.items()
    ]
    rows.append([InlineKeyboardButton("🔙 بازگشت به فروشگاه", callback_data="gift:backshop:0:0")])
    return InlineKeyboardMarkup(rows)


def gift_options_text(tier):
    t = GIFT_TIERS[tier]
    return f"{t['tier_label']}\n\n🎨 یکی از طرح‌های گیفت رو انتخاب کن ⬇️"


def gift_options_keyboard(tier):
    t = GIFT_TIERS[tier]
    rows = [
        [InlineKeyboardButton(gift_option_label(tier, key), callback_data=f"gift:opt:{tier}:{key}")]
        for key in t["options"]
    ]
    rows.append([InlineKeyboardButton("🔙 بازگشت به تعرفه‌ها", callback_data="gift:backtiers:0:0")])
    return InlineKeyboardMarkup(rows)


def gift_qty_text(tier, option_key, qty):
    t = GIFT_TIERS[tier]
    label = gift_option_label(tier, option_key)
    return (
        f"{t['tier_label']} — {label}\n\n"
        f"🔢 تعداد رو با دکمه‌های ➖ و ➕ تنظیم کن.\n"
        f"💳 قیمت واحد: {t['price']:,} تومان\n"
        f"💰 جمع کل ({qty} عدد): {t['price'] * qty:,} تومان\n\n"
        f"وقتی تعداد درست بود، روی «✅ تایید تعداد» بزن."
    )


def gift_qty_keyboard(tier, option_key, qty):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"gift:qty:{tier}:dec"),
            InlineKeyboardButton(str(qty), callback_data="gift:noop:0:0"),
            InlineKeyboardButton("➕", callback_data=f"gift:qty:{tier}:inc"),
        ],
        [InlineKeyboardButton("✅ تایید تعداد", callback_data=f"gift:qtyok:{tier}:0")],
        [InlineKeyboardButton("🔙 بازگشت به طرح‌ها", callback_data=f"gift:backopt:{tier}:0")],
    ])


def gift_order_summary_text(flow):
    tier = GIFT_TIERS[flow["gift_type"]]
    label = gift_option_label(flow["gift_type"], flow["gift_option"])
    qty = flow["qty"]
    total = tier["price"] * qty
    gift_text_display = flow.get("gift_text") or "بدون متن"
    return (
        f"🧾 خلاصه سفارش\n\n"
        f"🎁 گیفت: {tier['tier_label']} — {label} × {qty}\n"
        f"👤 آیدی عددی گیرنده: {flow['recipient_id']}\n"
        f"📝 متن گیفت: {gift_text_display}\n"
        f"💰 مبلغ قابل پرداخت: {total:,} تومان\n\n"
        f"💳 پرداخت کارت به کارت به شماره کارت زیر:\n"
        f"{GIFT_CARD_NUMBER}\n"
        f"به نام: {GIFT_CARD_OWNER}\n\n"
        f"بعد از واریز، عکس رسیدِ پرداخت رو همینجا بفرست.\n\n"
        f"⚠️ توجه: فقط عکس رسید رو بفرست. اگه غیر از عکس رسید چیز دیگه‌ای بفرستی، "
        f"به‌طور دائم از ربات بن می‌شی."
    )


async def gift_shop_command(update, context):
    if not await require_membership(update, context):
        return
    context.user_data.pop("gift_flow", None)
    context.user_data.pop("points_flow", None)
    await update.message.reply_text(gift_shop_text(), reply_markup=gift_shop_keyboard(), **reply_kwargs(update.message))


async def gift_button(update, context):
    q = update.callback_query
    try:
        _, action, arg1, arg2 = q.data.split(":")
    except Exception:
        await q.answer()
        return
    if not await require_membership(update, context):
        return
    if action == "noop":
        await q.answer()
        return
    if action == "backshop":
        context.user_data.pop("gift_flow", None)
        context.user_data.pop("points_flow", None)
        await q.answer()
        await q.message.edit_text(gift_shop_text(), reply_markup=gift_shop_keyboard())
        return
    if action == "tiers":
        context.user_data.pop("gift_flow", None)
        await q.answer()
        await q.message.edit_text(gift_tiers_text(), reply_markup=gift_tiers_keyboard())
        return
    if action == "backtiers":
        context.user_data.pop("gift_flow", None)
        await q.answer()
        await q.message.edit_text(gift_tiers_text(), reply_markup=gift_tiers_keyboard())
        return
    if action == "backopt":
        tier = arg1
        if tier not in GIFT_TIERS:
            await q.answer()
            return
        context.user_data["gift_flow"] = {"stage": "options", "gift_type": tier}
        await q.answer()
        await q.message.edit_text(gift_options_text(tier), reply_markup=gift_options_keyboard(tier))
        return
    if action == "pick":
        tier = arg1
        if tier not in GIFT_TIERS:
            await q.answer()
            return
        context.user_data["gift_flow"] = {"stage": "options", "gift_type": tier}
        await q.answer()
        await q.message.edit_text(gift_options_text(tier), reply_markup=gift_options_keyboard(tier))
        return
    if action == "opt":
        tier, option_key = arg1, arg2
        if tier not in GIFT_TIERS or option_key not in GIFT_TIERS[tier]["options"]:
            await q.answer()
            return
        context.user_data["gift_flow"] = {"stage": "qty", "gift_type": tier, "gift_option": option_key, "qty": 1}
        await q.answer()
        await q.message.edit_text(gift_qty_text(tier, option_key, 1), reply_markup=gift_qty_keyboard(tier, option_key, 1))
        return
    if action == "qty":
        tier, direction = arg1, arg2
        flow = context.user_data.get("gift_flow") or {}
        if flow.get("gift_type") != tier or flow.get("stage") != "qty" or not flow.get("gift_option"):
            await q.answer("لطفاً دوباره از فروشگاه شروع کن.", show_alert=True)
            return
        option_key = flow["gift_option"]
        qty = flow.get("qty", 1)
        qty = min(GIFT_MAX_QTY, qty + 1) if direction == "inc" else max(1, qty - 1)
        flow["qty"] = qty
        context.user_data["gift_flow"] = flow
        await q.answer()
        await q.message.edit_text(gift_qty_text(tier, option_key, qty), reply_markup=gift_qty_keyboard(tier, option_key, qty))
        return
    if action == "qtyok":
        tier = arg1
        flow = context.user_data.get("gift_flow") or {}
        if flow.get("gift_type") != tier or not flow.get("gift_option"):
            await q.answer("لطفاً دوباره از فروشگاه شروع کن.", show_alert=True)
            return
        flow["stage"] = "await_recipient"
        flow["started_at"] = now_utc().isoformat()
        context.user_data["gift_flow"] = flow
        await q.answer()
        label = gift_option_label(tier, flow["gift_option"])
        await q.message.edit_text(
            f"{GIFT_TIERS[tier]['tier_label']} — {label} × {flow['qty']}\n\n"
            "👤 آیدی عددی کاربر گیرنده گیفت رو بفرست.\n"
            "(برای گرفتن آیدی عددی خودت یا هر کاربر دیگه می‌تونی به @userinfobot پیام بدی)"
        )
        return
    if action == "notext":
        flow = context.user_data.get("gift_flow") or {}
        if flow.get("stage") != "await_text":
            await q.answer()
            return
        flow["gift_text"] = ""
        flow["stage"] = "await_receipt"
        context.user_data["gift_flow"] = flow
        await q.answer()
        await q.message.edit_text(gift_order_summary_text(flow))
        return
    await q.answer()


async def handle_gift_text(update, context):
    flow = context.user_data.get("gift_flow")
    if not flow or not update.message or not update.message.text:
        return False
    stage = flow.get("stage")
    if stage not in ("await_recipient", "await_text"):
        return False
    text = update.message.text.strip()
    if stage == "await_recipient":
        if not re.fullmatch(r"\d{5,15}", text):
            await update.message.reply_text(
                "❗️ آیدی عددی معتبر نیست. فقط آیدی عددی کاربر گیرنده رو بفرست (مثلاً با @userinfobot پیدا کن).",
                **reply_kwargs(update.message)
            )
            return True
        flow["recipient_id"] = text
        flow["stage"] = "await_text"
        context.user_data["gift_flow"] = flow
        await update.message.reply_text(
            "📝 حالا متن گیفت رو بفرست؛ یعنی چی روی گیفت نوشته بشه.\n"
            "یا اگه نمی‌خوای متنی روی گیفت باشه، دکمه زیر رو بزن.",
            reply_markup=GIFT_NO_TEXT_KEYBOARD,
            **reply_kwargs(update.message)
        )
        return True
    if stage == "await_text":
        flow["gift_text"] = text[:300]
        flow["stage"] = "await_receipt"
        context.user_data["gift_flow"] = flow
        await update.message.reply_text(gift_order_summary_text(flow), **reply_kwargs(update.message))
        return True
    return False


async def finalize_gift_order(update, context, flow):
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        tier = GIFT_TIERS[flow["gift_type"]]
        option_key = flow["gift_option"]
        design_label = gift_option_label(flow["gift_type"], option_key)
        qty = flow["qty"]
        total = tier["price"] * qty
        try:
            started_at = datetime.fromisoformat(flow["started_at"])
        except Exception:
            started_at = now_utc()
        order = GiftOrder(
            user_id=user.telegram_id,
            recipient_id=int(flow["recipient_id"]),
            gift_type=flow["gift_type"],
            gift_design=option_key,
            quantity=qty,
            unit_price=tier["price"],
            total_price=total,
            gift_text=flow.get("gift_text") or "",
            receipt_file_id=update.message.photo[-1].file_id,
            status="pending",
            started_at=started_at,
        )
        session.add(order)
        session.commit()
        order_id = order.id
        context.user_data.pop("gift_flow", None)
        await update.message.reply_text(
            f"✅ سفارش شما ثبت شد (شماره سفارش: {order_id}).\n"
            f"تیم پشتیبانی رسیدت رو بررسی می‌کنه و به‌زودی گیفت برای آیدی {order.recipient_id} ارسال می‌شه.",
            **reply_kwargs(update.message)
        )
        caption = (
            f"🆕 سفارش گیفت #{order_id}\n\n"
            f"🎁 نوع گیفت: {tier['tier_label']} — {design_label} × {qty}\n"
            f"💰 مبلغ: {total:,} تومان\n"
            f"👤 آیدی سفارش‌دهنده: {order.user_id}\n"
            f"🎯 آیدی گیرنده: {order.recipient_id}\n"
            f"📝 متن گیفت: {order.gift_text or 'بدون متن'}\n"
            f"🕐 زمان سفارش: {jalali_datetime_str(tehran_dt(order.created_at))}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_photo(chat_id=admin_id, photo=order.receipt_file_id, caption=caption)
            except Exception:
                logger.warning("ارسال سفارش گیفت به ادمین %s ناموفق بود", admin_id)
        order.status = "delivered"
        order.delivered_at = now_utc()
        session.commit()
        elapsed = int((aware(order.delivered_at) - aware(order.started_at)).total_seconds()) if order.started_at else 0
        channel_text = (
            f"👍 سفارش {order_id} تحویل شد\n\n"
            f"🎁 گیفت: {tier['tier_label']} — {design_label} × {qty}\n"
            f"💳 {to_fa_digits(f'{total:,}')} تومان · کارت به کارت\n"
            f"⏰ از سفارش تا تحویل: {to_fa_digits(format_duration(elapsed))}\n"
            f" خریدار: {mask_telegram_id(order.user_id)}\n\n"
            f"⏳ {jalali_datetime_str(tehran_dt(order.delivered_at))}\n"
            f"تحویل داده شد\n\n"
            f"🛍 خرید از روباهیو🦊: @fox_119bot"
        )
        try:
            await context.bot.send_message(chat_id=GIFT_CHANNEL_USERNAME, text=channel_text)
        except Exception:
            logger.warning("ارسال پیام کانال گیفت ناموفق بود")
    finally:
        session.close()


async def gift_flow_gate(update, context):
    """وقتی کاربر منتظر ارسال رسیده: عکس یعنی ثبت سفارش، هر چیز دیگه یعنی بن دائم."""
    flow = context.user_data.get("gift_flow")
    if not flow or flow.get("stage") != "await_receipt":
        return
    if not update.message:
        return
    if update.message.photo:
        await finalize_gift_order(update, context, flow)
        raise ApplicationHandlerStop
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        user.is_banned = 1
        session.commit()
    finally:
        session.close()
    context.user_data.pop("gift_flow", None)
    await update.message.reply_text("⛔️ چون به‌جای عکس رسید چیز دیگه‌ای فرستادی، به‌طور دائم از ربات بن شدی.")
    raise ApplicationHandlerStop


# ---------- خرید روب پوینت 🦊 ----------

POINTS_PACKAGES = {
    "1": {"points": 250000, "price": 15000},
    "2": {"points": 500000, "price": 22000},
    "3": {"points": 1000000, "price": 45000},
    "4": {"points": 3000000, "price": 130000},
}
POINTS_CARD_NUMBER = GIFT_CARD_NUMBER
POINTS_CARD_OWNER = GIFT_CARD_OWNER
POINTS_CHANNEL_USERNAME = GIFT_CHANNEL_USERNAME
POINTS_SUPPORT_CONTACT = "@escotch"


def points_package_label(key):
    p = POINTS_PACKAGES[key]
    return f"{p['points']:,} روب پوینت — {p['price']:,} تومان"


def points_shop_text():
    return (
        "🦊 خرید روب پوینت\n\n"
        "یکی از بسته‌های زیر رو انتخاب کن ⬇️\n\n"
        f"در صورت بروز مشکل با پشتیبانی تماس بگیرید: {POINTS_SUPPORT_CONTACT}"
    )


def points_shop_keyboard():
    rows = [
        [InlineKeyboardButton(points_package_label(key), callback_data=f"points:pick:{key}:0")]
        for key in POINTS_PACKAGES
    ]
    rows.append([InlineKeyboardButton("🔙 بازگشت به فروشگاه", callback_data="gift:backshop:0:0")])
    return InlineKeyboardMarkup(rows)


def points_order_summary_text(flow):
    pkg = POINTS_PACKAGES[flow["package_key"]]
    return (
        f"🧾 خلاصه سفارش\n\n"
        f"🪙 روب پوینت: {pkg['points']:,}\n"
        f"👤 آیدی عددی گیرنده: {flow['recipient_id']}\n"
        f"💰 مبلغ قابل پرداخت: {pkg['price']:,} تومان\n\n"
        f"💳 پرداخت کارت به کارت به شماره کارت زیر:\n"
        f"{POINTS_CARD_NUMBER}\n"
        f"به نام: {POINTS_CARD_OWNER}\n\n"
        f"بعد از واریز، عکس رسیدِ پرداخت رو همینجا بفرست.\n\n"
        f"⚠️ توجه: فقط عکس رسید واقعی پرداخت رو بفرست تا سفارش برای پشتیبانی ارسال بشه.\n"
        f"🚫 اگه رسید فیک (جعلی) بفرستی، توسط پشتیبانی به‌طور دائم از ربات بن می‌شی.\n"
        f"در صورت بروز مشکل با پشتیبانی تماس بگیرید: {POINTS_SUPPORT_CONTACT}"
    )


async def points_shop_entry(update, context):
    """ورود به بخش «خرید روب پوینت» از داخل فروشگاه روبی."""
    context.user_data.pop("points_flow", None)
    await update.callback_query.message.edit_text(points_shop_text(), reply_markup=points_shop_keyboard())


async def points_button(update, context):
    q = update.callback_query
    try:
        _, action, arg1, arg2 = q.data.split(":")
    except Exception:
        await q.answer()
        return
    if not await require_membership(update, context):
        return
    if action == "shop":
        context.user_data.pop("gift_flow", None)
        await q.answer()
        await points_shop_entry(update, context)
        return
    if action == "backshop":
        context.user_data.pop("points_flow", None)
        await q.answer()
        await q.message.edit_text(points_shop_text(), reply_markup=points_shop_keyboard())
        return
    if action == "pick":
        key = arg1
        if key not in POINTS_PACKAGES:
            await q.answer()
            return
        context.user_data["points_flow"] = {
            "stage": "await_recipient",
            "package_key": key,
            "started_at": now_utc().isoformat(),
        }
        await q.answer()
        pkg = POINTS_PACKAGES[key]
        await q.message.edit_text(
            f"🪙 بسته انتخابی: {pkg['points']:,} روب پوینت — {pkg['price']:,} تومان\n\n"
            "👤 آیدی عددی کاربری که می‌خوای روب پوینت رو دریافت کنه وارد کن.\n"
            "(برای گرفتن آیدی عددی خودت یا هر کاربر دیگه می‌تونی به @userinfobot پیام بدی)"
        )
        return
    await q.answer()


async def handle_points_text(update, context):
    flow = context.user_data.get("points_flow")
    if not flow or not update.message or not update.message.text:
        return False
    if flow.get("stage") != "await_recipient":
        return False
    text = update.message.text.strip()
    if not re.fullmatch(r"\d{5,15}", text):
        await update.message.reply_text(
            "❗️ آیدی عددی معتبر نیست. فقط آیدی عددیِ کاربر گیرنده رو بفرست (مثلاً با @userinfobot پیدا کن).",
            **reply_kwargs(update.message)
        )
        return True
    flow["recipient_id"] = text
    flow["stage"] = "await_receipt"
    context.user_data["points_flow"] = flow
    await update.message.reply_text(points_order_summary_text(flow), **reply_kwargs(update.message))
    return True


def points_admin_caption(order):
    pkg = POINTS_PACKAGES[order.package_key]
    return (
        f"🆕 سفارش خرید روب پوینت #{order.id}\n\n"
        f"🪙 مقدار: {pkg['points']:,} روب پوینت\n"
        f"💰 مبلغ: {pkg['price']:,} تومان\n"
        f"👤 آیدی عددی سفارش‌دهنده: {order.user_id}\n"
        f"🎯 آیدی عددی گیرنده: {order.recipient_id}\n"
        f"🕐 زمان سفارش: {jalali_datetime_str(tehran_dt(order.created_at))}\n\n"
        f"⏳ وضعیت: در انتظار بررسی"
    )


def points_admin_keyboard(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"pts:approve:{order_id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"pts:reject:{order_id}"),
    ]])


def points_channel_text(order, status_line):
    pkg = POINTS_PACKAGES[order.package_key]
    return (
        f"🦊 سفارش خرید روب پوینت #{order.id}\n\n"
        f"🪙 مقدار: {pkg['points']:,} روب پوینت\n"
        f"💳 {pkg['price']:,} تومان · کارت به کارت\n"
        f"👤 سفارش‌دهنده: {mask_telegram_id(order.user_id)}\n"
        f"🎯 گیرنده: {mask_telegram_id(order.recipient_id)}\n"
        f"🕐 {jalali_datetime_str(tehran_dt(order.created_at))}\n\n"
        f"{status_line}\n\n"
        f"🛍 خرید از روباهیو🦊: @fox_119bot"
    )


async def finalize_points_order(update, context, flow):
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        pkg = POINTS_PACKAGES[flow["package_key"]]
        try:
            started_at = datetime.fromisoformat(flow["started_at"])
        except Exception:
            started_at = now_utc()
        order = PointsPurchase(
            user_id=user.telegram_id,
            recipient_id=int(flow["recipient_id"]),
            package_key=flow["package_key"],
            points_amount=pkg["points"],
            price=pkg["price"],
            receipt_file_id=update.message.photo[-1].file_id,
            status="pending",
            started_at=started_at,
        )
        session.add(order)
        session.commit()
        order_id = order.id
        context.user_data.pop("points_flow", None)
        await update.message.reply_text(
            f"✅ شما روب پوینت سفارش داده‌اید (شماره سفارش: {order_id}).\n"
            f"⏳ منتظر تایید پشتیبانی باشید؛ به‌زودی {order.points_amount:,} روب پوینت به آیدی {order.recipient_id} اضافه می‌شه.\n"
            f"در صورت بروز مشکل با پشتیبانی تماس بگیرید: {POINTS_SUPPORT_CONTACT}",
            **reply_kwargs(update.message)
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=order.receipt_file_id,
                    caption=points_admin_caption(order),
                    reply_markup=points_admin_keyboard(order_id),
                )
            except Exception:
                logger.warning("ارسال سفارش خرید روب پوینت به ادمین %s ناموفق بود", admin_id)
        try:
            msg = await context.bot.send_message(
                chat_id=POINTS_CHANNEL_USERNAME,
                text=points_channel_text(order, "⏳ وضعیت: در حال بررسی")
            )
            order.channel_message_id = msg.message_id
            session.commit()
        except Exception:
            logger.warning("ارسال پیام کانال خرید روب پوینت ناموفق بود")
    finally:
        session.close()


async def points_flow_gate(update, context):
    """وقتی کاربر منتظر ارسال رسیده برای خرید روب پوینت: فقط عکس رسید پذیرفته می‌شه."""
    flow = context.user_data.get("points_flow")
    if not flow or flow.get("stage") != "await_receipt":
        return
    if not update.message:
        return
    if update.message.photo:
        await finalize_points_order(update, context, flow)
        raise ApplicationHandlerStop
    await update.message.reply_text(
        "⚠️ فقط عکس رسید پرداخت رو بفرست تا سفارش برای پشتیبانی ارسال بشه.",
        **reply_kwargs(update.message)
    )
    raise ApplicationHandlerStop


async def purchase_flow_gate(update, context):
    """گیت مشترک برای فلوهای «خرید گیفت استارزی» و «خرید روب پوینت».

    هر دو گیت قبلاً جدا و هر دو با filters.ALL روی گروه -9 ثبت شده بودند؛
    چون گروه‌های PTB فقط اولین هندلرِ match‌شده را اجرا می‌کنند و
    filters.ALL همیشه match می‌شود، gift_flow_gate همیشه زودتر اجرا و
    نوبت points_flow_gate هیچ‌وقت نمی‌رسید (حتی برای کاربرهایی که اصلاً
    gift_flow نداشتند). این تابع هر دو را به ترتیب داخل یک هندلر واحد
    صدا می‌زند تا هر دو فلو واقعاً بررسی شوند.
    """
    if context.user_data.get("gift_flow"):
        await gift_flow_gate(update, context)
        return
    if context.user_data.get("points_flow"):
        await points_flow_gate(update, context)
        return


async def points_admin_button(update, context):
    q = update.callback_query
    if not q or not q.from_user or q.from_user.id not in ADMIN_IDS:
        await q.answer("⛔️ این دکمه فقط برای پشتیبانیه.", show_alert=True)
        return
    m = re.fullmatch(r"pts:(approve|reject):(\d+)", q.data or "")
    if not m:
        await q.answer()
        return
    action, order_id = m.group(1), int(m.group(2))
    session = get_session()
    try:
        order = session.get(PointsPurchase, order_id)
        if not order:
            await q.answer("این سفارش دیگه پیدا نشد.", show_alert=True)
            return
        if order.status != "pending":
            await q.answer("قبلاً روی این سفارش تصمیم گرفته شده.", show_alert=True)
            return
        pkg = POINTS_PACKAGES[order.package_key]
        if action == "approve":
            recipient = get_or_create_user_by_id(session, order.recipient_id)
            recipient.fox_points = (recipient.fox_points or 0) + order.points_amount
            order.status = "approved"
            order.decided_at = now_utc()
            order.decided_by = q.from_user.id
            session.commit()
            await q.answer("✅ تایید شد.", show_alert=True)
            try:
                await q.message.edit_caption(caption=points_admin_caption(order) + "\n✅ تایید شد و پوینت واریز شد.")
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=order.user_id,
                    text=f"✅ سفارش شما (#{order.id}) تایید شد و {order.points_amount:,} روب پوینت به آیدی {order.recipient_id} اضافه شد."
                )
            except Exception:
                pass
            if order.recipient_id != order.user_id:
                try:
                    await context.bot.send_message(
                        chat_id=order.recipient_id,
                        text=f"🎉 {order.points_amount:,} روب پوینت به حساب تو اضافه شد!"
                    )
                except Exception:
                    pass
            if order.channel_message_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=POINTS_CHANNEL_USERNAME,
                        message_id=order.channel_message_id,
                        text=points_channel_text(order, "✅ وضعیت: تایید شد و تحویل داده شد")
                    )
                except Exception:
                    pass
        else:
            order.status = "rejected"
            order.decided_at = now_utc()
            order.decided_by = q.from_user.id
            session.commit()
            await q.answer("❌ رد شد.", show_alert=True)
            try:
                await q.message.edit_caption(caption=points_admin_caption(order) + "\n❌ رد شد.")
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"❌ سفارش شما (#{order.id}) رد شد.\n"
                        f"در صورت بروز مشکل با پشتیبانی تماس بگیرید: {POINTS_SUPPORT_CONTACT}"
                    )
                )
            except Exception:
                pass
            if order.channel_message_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=POINTS_CHANNEL_USERNAME,
                        message_id=order.channel_message_id,
                        text=points_channel_text(order, "❌ وضعیت: رد شد")
                    )
                except Exception:
                    pass
    finally:
        session.close()


async def _active_jail(session, user):
    if not user:
        return False
    until = getattr(user, "jail_until", None)
    if until and now_utc() < aware(until):
        return True
    if until:
        user.jail_until = None
        user.jail_reason = None
        user.jail_fine = 0
        user.jail_arrested_at = None
        session.commit()
    return False


def jail_block_text(user):
    return (
        "⛓️ شما در زندان روبی هستید!\n\n"
        "😡 شما روباه بدی بودی و توسط گرگ‌های پلیس دستگیر شدی.\n"
        '🔒 برای دیدن سلول خودت بنویس «زندان روبی».\n'
        "🚫 تا پایان حبس هیچ بخش دیگری از ربات برایت فعال نیست."
    )


async def ban_gate(update, context):
    """محرومیت قبلی + زندان روبی را قبل از تمام بخش‌های ربات اعمال می‌کند."""
    user_tg = update.effective_user
    if not user_tg or user_tg.id in ADMIN_IDS:
        return
    text = (update.message.text or "").strip() if update.message else ""
    jail_cmd = text in {"زندان روبی", "زندان روباهیو", "⛓️ زندان روبی"}
    session = get_session()
    try:
        u = session.get(User, user_tg.id)
        if not u:
            return
        # بن قبلی
        banned = bool(getattr(u, "is_banned", 0))
        if not banned and getattr(u, "banned_until", None):
            if now_utc() < aware(u.banned_until):
                banned = True
            else:
                u.banned_until = None
                session.commit()
        if banned:
            raise ApplicationHandlerStop

        # ضداسپم: ۶ پیام متنی در ۱۰ ثانیه = ۱۵ دقیقه زندان روبی.
        if update.message and update.message.text and not jail_cmd and not context.user_data.get("jail_memory_wait"):
            now=now_utc()
            window=aware(getattr(u,"spam_window_at",None))
            if not window or (now-window).total_seconds()>SPAM_WINDOW_SECONDS:
                u.spam_window_at=now; u.spam_count=1
            else:
                u.spam_count=int(u.spam_count or 0)+1
            if u.spam_count>=SPAM_MESSAGE_LIMIT:
                u.spam_count=0; u.spam_window_at=None
                u.jail_until=now+timedelta(seconds=SPAM_JAIL_SECONDS)
                u.jail_reason="اسپم کردن پیام‌های ربات"
                u.jail_fine=SPAM_FINE
                u.jail_arrested_at=now
                session.commit()
                await update.message.reply_text("🚨 اسپم زیاد انجام دادی و گرگ‌های پلیس دستگیرت کردند!\n\n⛓️ مدت حبس: ۱۵ دقیقه\n🏦 جریمه: ۷۵۰ روب‌پوینت\n\nبرای ورود به سلول بنویس «زندان روبی».".replace("\\n","\n"),**reply_kwargs(update.message))
                raise ApplicationHandlerStop
            session.commit()

        jailed = await _active_jail(session, u)
        if jailed:
            # دستور زندان روبی و جریان نوشتن خاطره اجازه عبور دارند.
            if jail_cmd or context.user_data.get("jail_memory_wait"):
                return
            if update.message:
                await update.message.reply_text(jail_block_text(u), **reply_kwargs(update.message))
            raise ApplicationHandlerStop
    finally:
        session.close()


async def jail_callback_gate(update, context):
    """هیچ دکمه‌ای جز دکمه‌های خود زندان در زمان حبس قابل استفاده نیست."""
    q = update.callback_query
    if not q or not q.from_user or q.from_user.id in ADMIN_IDS:
        return
    session = get_session()
    try:
        u = session.get(User, q.from_user.id)
        if not u or not await _active_jail(session, u):
            return
        if (q.data or "").startswith("jail:"):
            return
        await q.answer("⛓️ اول باید از زندان روبی آزاد شوی.", show_alert=True)
        raise ApplicationHandlerStop
    finally:
        session.close()


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
        amount = parse_amount(raw_amount)
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"transfer:yes:{sender.telegram_id}:{receiver.telegram_id}:{amount}"), InlineKeyboardButton("❌ لغو", callback_data=f"transfer:no:{sender.telegram_id}:{receiver.telegram_id}:{amount}")]])
        await update.message.reply_text(
            f"💸 انتقال روب پوینت\n\n🦊 فرستنده: {sender.first_name or sender.telegram_id}\n👤 گیرنده: {receiver.first_name or receiver.telegram_id}\n💰 مقدار: {amount:,}\n\nتایید می‌کنی؟",
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
        await q.message.edit_text(f"✅ {amount:,} روب پوینت با موفقیت انتقال یافت.\n👤 گیرنده: {user_display_name(receiver)}\n⏳ انتقال بعدی 1 دقیقه دیگر.")
        await notify_user_private(context.bot, receiver.telegram_id, f"💸 {amount:,} روب پوینت از طرف {user_display_name(sender)} برای شما ارسال شد. 🦊")
    finally:
        session.close()

# ---------- سطح و قابلیت‌ها ----------

def level_capabilities(level):
    caps=["💰 روب روب / هور هور / عو عو"]
    if level >= 2: caps.append("🏹 شکار")
    if level >= 3: caps += ["🦊 روباه", "🎮 پیوستن به بازی", "🕹 ساخت بازی روبی"]
    if level >= 4: caps.append("🏦 بانک روبی")
    return "\n".join(caps) if caps else "🔒 قابلیت جدیدی هنوز باز نشده است."

def level_new_capabilities(level):
    """فقط قابلیت‌هایی که دقیقاً در همین سطح باز می‌شوند، نه کل قابلیت‌های تجمعی."""
    caps=[]
    if level == 1: caps.append("💰 روب روب / هور هور / عو عو")
    if level == 2: caps.append("🏹 شکار")
    if level == 3: caps += ["🦊 روباه", "🎮 پیوستن به بازی", "🕹 ساخت بازی روبی"]
    if level == 4: caps.append("🏦 بانک روبی")
    return "\n".join(caps) if caps else None

def level_up_message(old_level, new_level, rewards):
    parts=[]
    for lvl, reward in rewards:
        new_caps = level_new_capabilities(lvl)
        text = f"🎉 تبریک! به لول {lvl} صعود کردی!"
        if new_caps:
            text += f"\n\n🔓 قابلیت جدید باز شد:\n{new_caps}"
        text += f"\n\n💝 جایزه: +{reward:,} روب پوینت 🪙"
        parts.append(text)
    return "\n\n".join(parts)

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
        user.points += earned
        user.total_earned += earned
        user.last_claim_at = now
        old_level = user.level
        user.level = user_level_from_roobrub(user.fox_claim_count or 0)
        rewards = []
        session.commit()
        text = f"⚡ +{earned} پوینت!\n💰 موجودی: {user.points}\n📈 کل کسب‌شده: {user.total_earned}"
        if user.level > old_level:
            text += "\n\n" + level_up_message(old_level, user.level, rewards)
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

async def notify_user_private(bot, user_id, text):
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.info("Could not notify user %s: %s", user_id, e)


async def _send_to_user_safe(bot, uid, text, max_retries=3):
    """
    ارسال پیام به یک کاربر، با احترام به محدودیت نرخ ارسال تلگرام (Flood control).
    اگه تلگرام بگه صبر کن (RetryAfter)، به‌جای اینکه فوراً «ناموفق» حساب بشه،
    همون مدت صبر می‌کنه و دوباره امتحان می‌کنه.
    """
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id=uid, text=text)
            return True
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
        except (Forbidden, BadRequest):
            # کاربر بات رو بلاک کرده یا چت دیگه معتبر نیست؛ تلاش دوباره فایده‌ای نداره.
            return False
        except (TimedOut, NetworkError):
            await asyncio.sleep(1.5)
        except Exception:
            return False
    return False


async def broadcast_to_users(bot, user_ids, text, delay=0.05):
    """
    پیام رو یکی‌یکی به کاربرا می‌فرسته، با یه فاصله‌ی کوچیک بین هر ارسال تا به
    محدودیت نرخ ارسال تلگرام (حدود ۳۰ پیام در ثانیه) نخوریم. قبلاً همه‌ی پیام‌ها
    پشت‌سرهم و بدون وقفه فرستاده می‌شدن؛ بعد از چند پیام اول تلگرام باقی
    ارسال‌ها رو با خطای Flood رد می‌کرد و اونا بی‌هیچ تلاش دوباره‌ای «ناموفق»
    حساب می‌شدن — همین باعث می‌شد پیام همگانی فقط برای چند نفر اول بره.
    """
    ok = fail = 0
    for uid in user_ids:
        sent = await _send_to_user_safe(bot, uid, text)
        if sent:
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(delay)
    return ok, fail


def admin_only(user_id): return user_id in ADMIN_IDS

def build_backup_file():
    """
    یک فایل JSON از همه‌ی کاربران (روب‌پوینت، لول، امتیاز و ...) و حساب‌های
    بانکی می‌سازه. این فقط یک نسخه‌ی پشتیبان برای بازیابی دستیه؛ جای دیتابیس
    اصلی رو نمی‌گیره، ولی اگه یه جا دیتابیس زنده اشتباهی خالی/ریست بشه، با این
    فایل می‌شه اطلاعات روب‌پوینت و لول کاربرا رو دستی برگردوند.
    """
    session = get_session()
    try:
        users = session.query(User).all()
        data = {
            "generated_at": now_utc().isoformat(),
            "users_count": len(users),
            "users": [{
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "points": u.points,
                "total_earned": u.total_earned,
                "level": u.level,
                "fox_name": u.fox_name,
                "fox_level": u.fox_level,
                "fox_belly": u.fox_belly,
                "fox_points": u.fox_points,
                "fox_total_earned": u.fox_total_earned,
                "fox_claim_count": u.fox_claim_count,
                "hunt_count": u.hunt_count,
                "fox_rescued_count": u.fox_rescued_count,
            } for u in users],
            "bank_accounts": [{
                "account_number": a.account_number,
                "user_id": a.user_id,
                "balance": a.balance,
            } for a in session.query(BankAccount).all()],
        }
    finally:
        session.close()
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"backup_{now_utc().strftime('%Y%m%d_%H%M%S')}.json"
    return raw, filename

async def send_backup_to_admins(context, caption="📦 بکاپ خودکار روزانه"):
    try:
        raw, filename = build_backup_file()
    except Exception:
        logger.exception("backup build failed")
        return
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_document(chat_id=admin_id, document=io.BytesIO(raw), filename=filename, caption=caption)
        except Exception:
            pass  # یعنی اون ادمین هنوز پی‌وی ربات رو استارت نزده

async def daily_backup_job(context):
    await send_backup_to_admins(context)

def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats")],
        [InlineKeyboardButton("👥 تعداد کاربران", callback_data="admin:users")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🦊 افزودن/کسر روب‌پوینت", callback_data="admin:addpoints")],
        [InlineKeyboardButton("🎁 هدیه روب‌پوینت به همه", callback_data="admin:giftall")],
        [InlineKeyboardButton("⭐ تنظیم سطح", callback_data="admin:setlevel")],
        [InlineKeyboardButton("🦊 تنظیم روب‌پوینت", callback_data="admin:setfoxpoints")],
        [InlineKeyboardButton("⚽ پیش‌بینی فوتبال", callback_data="admin:football")],
        [InlineKeyboardButton("🚫 محرومیت کاربر", callback_data="admin:banmenu")],
        [InlineKeyboardButton("📦 دریافت بکاپ اطلاعات", callback_data="admin:backup")],
    ])


def ban_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ ۱ روزه", callback_data="admin:banset:1")],
        [InlineKeyboardButton("⏱ ۷ روزه", callback_data="admin:banset:7")],
        [InlineKeyboardButton("⏱ ۳۰ روزه", callback_data="admin:banset:30")],
        [InlineKeyboardButton("⛔ دائم", callback_data="admin:banset:permanent")],
        [InlineKeyboardButton("✅ رفع محرومیت", callback_data="admin:banset:unban")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:back")],
    ])


async def admin_command(update, context):
    if not await require_membership(update, context): return
    if not admin_only(update.effective_user.id): await update.message.reply_text("⛔ دسترسی نداری.", **reply_kwargs(update.message)); return
    await update.message.reply_text("🛠 پنل مدیریت\n\nبرای عملیات متنی، بعد از زدن گزینه مربوطه مقدار را بفرست.", reply_markup=admin_main_keyboard(), **reply_kwargs(update.message))


async def admin_callback(update, context):
    q = update.callback_query
    if not admin_only(q.from_user.id): await q.answer("دسترسی نداری.", show_alert=True); return
    action = q.data.split(":")[1]; await q.answer()
    if action == "stats":
        session=get_session()
        try:
            users=session.query(User).count(); points=sum((u.points or 0) for u in session.query(User).all()); earned=sum((u.total_earned or 0) for u in session.query(User).all()); games=session.query(Challenge).count(); fox=sum((u.fox_points or 0) for u in session.query(User).all())
            ref_total=session.query(Referral).count(); ref_approved=session.query(Referral).filter(Referral.status=="approved").count(); ref_pending=session.query(Referral).filter(Referral.status=="pending").count()
        finally: session.close()
        await q.message.reply_text(f"📊 آمار کلی\n\n👥 کاربران: {users}\n💰 پوینت معمولی: {points}\n📈 کل کسب‌شده: {earned}\n🦊 روب‌پوینت: {fox:,.2f}\n🎮 بازی‌ها: {games}\n\n🔗 زیرمجموعه‌گیری: {ref_total} کل | {ref_approved} تاییدشده | {ref_pending} در انتظار")
    elif action == "users":
        session=get_session()
        try: count=session.query(User).count()
        finally: session.close()
        await q.message.reply_text(f"👥 تعداد کاربران ثبت‌شده: {count}")
    elif action == "broadcast": context.user_data["admin_action"]="broadcast"; await q.message.reply_text("📣 متن پیام همگانی را بفرست.")
    elif action == "addpoints": context.user_data["admin_action"]="addpoints"; await q.message.reply_text("🦊 فرمت: آیدی عددی کاربر + مقدار روب‌پوینت")
    elif action == "giftall":
        context.user_data["admin_action"]="giftall"
        await q.message.reply_text("🎁 چند روب‌پوینت به همه‌ی کاربرا هدیه داده بشه؟\nفقط عدد بفرست (مثلاً 500). برای کسر از همه، عدد منفی بفرست.")
    elif action == "setlevel": context.user_data["admin_action"]="setlevel"; await q.message.reply_text("⭐ فرمت: آیدی عددی کاربر + سطح")
    elif action == "setfoxpoints": context.user_data["admin_action"]="setfoxpoints"; await q.message.reply_text("🦊 فرمت: آیدی عددی کاربر + مقدار روب‌پوینت")
    elif action == "banmenu":
        await q.message.reply_text("🚫 محرومیت کاربر\n\nمدت محرومیت رو انتخاب کن یا محرومیت رو بردار:", reply_markup=ban_menu_keyboard())
    elif action == "backup":
        raw, filename = build_backup_file()
        await q.message.reply_document(document=io.BytesIO(raw), filename=filename, caption="📦 بکاپ اطلاعات کاربران (دستی)")


BAN_OPTION_LABELS = {
    "1": "۱ روزه",
    "7": "۷ روزه",
    "30": "۳۰ روزه",
    "permanent": "دائم",
    "unban": "رفع محرومیت",
}


async def admin_banset_callback(update, context):
    q = update.callback_query
    if not admin_only(q.from_user.id):
        await q.answer("دسترسی نداری.", show_alert=True)
        return
    option = q.data.split(":")[2]
    if option not in BAN_OPTION_LABELS:
        await q.answer()
        return
    await q.answer()
    context.user_data["admin_action"] = f"ban:{option}"
    await q.message.reply_text(f"🚫 محرومیت ({BAN_OPTION_LABELS[option]})\n\nآیدی عددی کاربر مورد نظر رو بفرست.")


async def admin_text(update, context):
    if not admin_only(update.effective_user.id): return
    action=context.user_data.get("admin_action")
    if not action: return
    context.user_data.pop("admin_action",None); text=update.message.text.strip()
    if action == "broadcast":
        session=get_session()
        try: users=[u.telegram_id for u in session.query(User).all()]
        finally: session.close()
        await update.message.reply_text(f"📣 در حال ارسال به {len(users)} کاربر... ممکنه چند دقیقه طول بکشه.", **reply_kwargs(update.message))
        ok, fail = await broadcast_to_users(context.bot, users, "📢 پیام مدیریت:\n\n"+text)
        await update.message.reply_text(f"✅ ارسال شد: {ok}\n❌ ناموفق (بلاک/حذف حساب): {fail}", **reply_kwargs(update.message)); return
    if action == "giftall":
        cleaned = text.replace(",", "").replace("،", "").strip()
        if not cleaned.lstrip("-").isdigit():
            await update.message.reply_text("❗️ فقط یک عدد بفرست (مثلاً 500 یا 500-).", **reply_kwargs(update.message)); return
        amount = int(cleaned)
        if amount == 0:
            await update.message.reply_text("مقدار نمی‌تونه صفر باشه.", **reply_kwargs(update.message)); return
        session=get_session()
        try:
            users = session.query(User).all()
            for u in users:
                u.fox_points = max(0, int(u.fox_points or 0) + amount)
            session.commit()
            user_ids = [u.telegram_id for u in users]
        finally:
            session.close()
        count = len(user_ids)
        await update.message.reply_text(f"🎁 روب‌پوینت {count} کاربر آپدیت شد.\n📣 در حال اطلاع‌رسانی...", **reply_kwargs(update.message))
        if amount > 0:
            gift_text = f"🎉 هدیه‌ی پشتیبانی!\n\n🦊 {amount:,} روب‌پوینت به همه‌ی کاربرا هدیه داده شد و به حساب شما هم اضافه شد! 🦊"
        else:
            gift_text = f"📢 اطلاعیه پشتیبانی\n\n🦊 {abs(amount):,} روب‌پوینت از حساب همه‌ی کاربرا کسر شد."
        ok, fail = await broadcast_to_users(context.bot, user_ids, gift_text)
        await update.message.reply_text(f"✅ روب‌پوینت {count} کاربر آپدیت شد.\n📨 اطلاع‌رسانی موفق: {ok}\n❌ ناموفق (بلاک/حذف حساب): {fail}", **reply_kwargs(update.message)); return
    if action == "football_add_match":
        await football_add_match_text(update, context); return
    if action.startswith("ban:"):
        option = action.split(":", 1)[1]
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❗️ فقط آیدی عددی کاربر رو بفرست.", **reply_kwargs(update.message)); return
        uid = int(text)
        session=get_session()
        try:
            user=session.get(User,uid)
            if not user: await update.message.reply_text("کاربر پیدا نشد.", **reply_kwargs(update.message)); return
            if option == "unban":
                user.is_banned = 0
                user.banned_until = None
                session.commit()
                await update.message.reply_text(f"✅ محرومیت کاربر {uid} برداشته شد.", **reply_kwargs(update.message))
                await notify_user_private(context.bot, uid, "📢 اطلاعیه پشتیبانی\n\n✅ محرومیت شما لغو شد و می‌تونی دوباره از ربات استفاده کنی.")
            elif option == "permanent":
                user.is_banned = 1
                user.banned_until = None
                session.commit()
                await update.message.reply_text(f"⛔ کاربر {uid} به‌طور دائم محروم شد.", **reply_kwargs(update.message))
                await notify_user_private(context.bot, uid, "📢 اطلاعیه پشتیبانی\n\n⛔️ شما به‌طور دائم از ربات محروم شدید.")
            else:
                days = int(option)
                until = now_utc() + timedelta(days=days)
                user.is_banned = 0
                user.banned_until = until
                session.commit()
                until_text = jalali_datetime_str(tehran_dt(until))
                await update.message.reply_text(f"⏱ کاربر {uid} به مدت {BAN_OPTION_LABELS[option]} محروم شد.\nتا: {until_text}", **reply_kwargs(update.message))
                await notify_user_private(context.bot, uid, f"📢 اطلاعیه پشتیبانی\n\n⏱ شما به مدت {BAN_OPTION_LABELS[option]} از ربات محروم شدید.\nپایان محرومیت: {until_text}")
        finally:
            session.close()
        return
    parts=text.split()
    if len(parts)!=2 or not all(p.lstrip("-").isdigit() for p in parts): await update.message.reply_text("فرمت اشتباه است.", **reply_kwargs(update.message)); return
    uid,value=int(parts[0]),int(parts[1]); session=get_session()
    try:
        user=session.get(User,uid)
        if not user: await update.message.reply_text("کاربر پیدا نشد.", **reply_kwargs(update.message)); return
        if action=="addpoints":
            old_points=int(user.fox_points or 0)
            user.fox_points=max(0,old_points+value)
            session.commit()
            await update.message.reply_text(f"🦊 انجام شد.\nروب‌پوینت کاربر: {user.fox_points:,}",**reply_kwargs(update.message))
            await notify_user_private(context.bot, uid, f"📢 اطلاعیه پشتیبانی\n\n🦊 روب‌پوینت‌های شما توسط پشتیبانی تغییر کرد.\n💰 مقدار قبلی: {old_points:,}\n💰 مقدار جدید: {user.fox_points:,}")
        elif action=="setlevel":
            if value<1 or value>100: await update.message.reply_text("سطح باید بین 1 تا 100 باشد.", **reply_kwargs(update.message)); return
            old_level=int(user.level or 1)
            user.level=value
            user.fox_claim_count=max(int(user.fox_claim_count or 0),user_level_requirement(value))
            rewards=apply_level_rewards(session,user,old_level,value) if value>old_level else []
            session.commit()
            await update.message.reply_text(f"✅ سطح کاربر شد {user.level}\n🐾 روب روب‌ها: {user.fox_claim_count:,}", **reply_kwargs(update.message))
            msg=f"📢 اطلاعیه پشتیبانی\n\n⭐ سطح شما توسط پشتیبانی تغییر کرد.\nسطح قبلی: {old_level}\nسطح جدید: {value}\n\n🔓 قابلیت‌های این سطح:\n{level_capabilities(value)}"
            if rewards:
                msg += "\n\n" + level_up_message(old_level,value,rewards)
            await notify_user_private(context.bot, uid, msg)
        elif action=="setfoxpoints":
            old_points=int(user.fox_points or 0)
            user.fox_points=max(0,value)
            session.commit()
            await update.message.reply_text(f"🦊 روب‌پوینت کاربر: {user.fox_points:,.2f}", **reply_kwargs(update.message))
            await notify_user_private(context.bot, uid, f"📢 اطلاعیه پشتیبانی\n\n🦊 روب‌پوینت‌های شما توسط پشتیبانی تنظیم شد.\n💰 مقدار قبلی: {old_points:,}\n💰 مقدار جدید: {user.fox_points:,}")
    finally: session.close()


# ---------- پیش‌بینی فوتبال ----------
FOOTBALL_PREDICTION_REWARD = 1500
FOOTBALL_CHOICE_LABELS = {'home': 'برد میزبان', 'draw': 'مساوی', 'away': 'برد میهمان'}


def football_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن بازی", callback_data="admin:football:add")],
        [InlineKeyboardButton("📋 لیست بازی‌ها", callback_data="admin:football:matches")],
        [InlineKeyboardButton("🗳 پیش‌بینی‌های در انتظار تایید", callback_data="admin:football:pending")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:back")],
    ])


def _football_matches_admin_view(session):
    matches = session.query(FootballMatch).order_by(FootballMatch.id.desc()).limit(25).all()
    rows = []
    if not matches:
        text = "📋 هیچ بازی‌ای ثبت نشده."
    else:
        lines = ["📋 لیست بازی‌ها:\n"]
        for m in matches:
            status_icon = "🟢 باز" if (m.status or 'open') == 'open' else "🔴 بسته"
            lines.append(f"#{m.id} | {status_icon}\n⚽ {m.team_home} 🆚 {m.team_away}\n🕒 {m.match_time}\n")
            rows.append([
                InlineKeyboardButton(f"🔁 تغییر وضعیت #{m.id}", callback_data=f"admin:football:toggle:{m.id}"),
                InlineKeyboardButton(f"🗑 حذف #{m.id}", callback_data=f"admin:football:del:{m.id}"),
            ])
        text = "\n".join(lines)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:football")])
    return text, InlineKeyboardMarkup(rows)


def _football_pending_admin_view(session):
    preds = (session.query(FootballPrediction)
             .filter(FootballPrediction.status == 'pending')
             .order_by(FootballPrediction.id.asc()).limit(20).all())
    rows = []
    if not preds:
        text = "🗳 هیچ پیش‌بینی در انتظار تاییدی نیست."
    else:
        lines = ["🗳 پیش‌بینی‌های در انتظار تایید:\n"]
        for p in preds:
            m = session.get(FootballMatch, p.match_id)
            u = session.get(User, p.user_id)
            uname = user_display_name(u) if u else str(p.user_id)
            match_label = f"{m.team_home} 🆚 {m.team_away}" if m else f"بازی #{p.match_id}"
            lines.append(f"#{p.id} | 👤 {uname} | ⚽ {match_label} | 🔮 {FOOTBALL_CHOICE_LABELS.get(p.choice, p.choice)}")
            rows.append([
                InlineKeyboardButton(f"✅ تایید #{p.id}", callback_data=f"admin:football:appr:{p.id}"),
                InlineKeyboardButton(f"❌ رد #{p.id}", callback_data=f"admin:football:rej:{p.id}"),
            ])
        text = "\n".join(lines)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:football")])
    return text, InlineKeyboardMarkup(rows)


async def _edit_or_send(q, text, kb):
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, reply_markup=kb)


async def admin_football_callback(update, context):
    q = update.callback_query
    if not admin_only(q.from_user.id):
        await q.answer("دسترسی نداری.", show_alert=True); return
    data = q.data

    if data == "admin:back":
        await q.answer()
        await _edit_or_send(q, "🛠 پنل مدیریت\n\nبرای عملیات متنی، بعد از زدن گزینه مربوطه مقدار را بفرست.", admin_main_keyboard())
        return

    if data == "admin:football":
        await q.answer()
        await _edit_or_send(q, "⚽ مدیریت پیش‌بینی فوتبال", football_admin_keyboard())
        return

    if data == "admin:football:add":
        context.user_data["admin_action"] = "football_add_match"
        await q.answer()
        await q.message.reply_text(
            "➕ افزودن بازی فوتبال\n\nسه خط بفرست (هرکدوم تو یه خط):\n"
            "۱) نام تیم میزبان\n۲) نام تیم مهمان\n۳) تاریخ و ساعت بازی\n\n"
            "مثال:\nپرسپولیس\nاستقلال\n1404/08/02 - ساعت 20:00"
        )
        return

    if data == "admin:football:matches":
        await q.answer()
        session = get_session()
        try:
            text, kb = _football_matches_admin_view(session)
        finally:
            session.close()
        await _edit_or_send(q, text, kb)
        return

    if data.startswith("admin:football:toggle:"):
        match_id = int(data.split(":")[3])
        session = get_session()
        try:
            m = session.get(FootballMatch, match_id)
            if not m:
                await q.answer("پیدا نشد.", show_alert=True); return
            m.status = 'closed' if (m.status or 'open') == 'open' else 'open'
            session.commit()
            text, kb = _football_matches_admin_view(session)
        finally:
            session.close()
        await q.answer("وضعیت بازی تغییر کرد.")
        await _edit_or_send(q, text, kb)
        return

    if data.startswith("admin:football:del:"):
        match_id = int(data.split(":")[3])
        session = get_session()
        try:
            m = session.get(FootballMatch, match_id)
            if not m:
                await q.answer("پیدا نشد.", show_alert=True); return
            session.query(FootballPrediction).filter_by(match_id=match_id).delete()
            session.delete(m)
            session.commit()
            text, kb = _football_matches_admin_view(session)
        finally:
            session.close()
        await q.answer("🗑 بازی حذف شد.")
        await _edit_or_send(q, text, kb)
        return

    if data == "admin:football:pending":
        await q.answer()
        session = get_session()
        try:
            text, kb = _football_pending_admin_view(session)
        finally:
            session.close()
        await _edit_or_send(q, text, kb)
        return

    if data.startswith("admin:football:appr:") or data.startswith("admin:football:rej:"):
        approve = data.startswith("admin:football:appr:")
        pred_id = int(data.split(":")[3])
        session = get_session()
        notify_uid = None; notify_text = None
        try:
            p = session.get(FootballPrediction, pred_id)
            if not p or p.status != 'pending':
                await q.answer("این پیش‌بینی قبلاً بررسی شده.", show_alert=True); return
            m = session.get(FootballMatch, p.match_id)
            match_label = f"{m.team_home} 🆚 {m.team_away}" if m else f"بازی #{p.match_id}"
            if approve:
                user = session.get(User, p.user_id)
                if user:
                    user.fox_points = int(user.fox_points or 0) + FOOTBALL_PREDICTION_REWARD
                p.status = 'approved'
                p.reward = FOOTBALL_PREDICTION_REWARD
                notify_text = (
                    f"📢 اطلاعیه پشتیبانی\n\n✅ پیش‌بینی شما برای بازی {match_label} تایید شد!\n"
                    f"🎁 جایزه: {FOOTBALL_PREDICTION_REWARD:,} روب‌پوینت به حسابت اضافه شد."
                )
            else:
                p.status = 'rejected'
                notify_text = f"📢 اطلاعیه پشتیبانی\n\n❌ پیش‌بینی شما برای بازی {match_label} رد شد."
            p.reviewed_at = now_utc()
            notify_uid = p.user_id
            session.commit()
            text, kb = _football_pending_admin_view(session)
        finally:
            session.close()
        await q.answer("✅ تایید شد." if approve else "❌ رد شد.")
        if notify_uid and notify_text:
            await notify_user_private(context.bot, notify_uid, notify_text)
        await _edit_or_send(q, text, kb)
        return


async def football_add_match_text(update, context):
    """پردازش متن سه‌خطی پشتیبانی برای افزودن بازی جدید."""
    raw = update.message.text.strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3:
        await update.message.reply_text(
            "❌ فرمت اشتباهه. سه خط بفرست:\nتیم میزبان\nتیم مهمان\nتاریخ و ساعت",
            **reply_kwargs(update.message)
        )
        return
    team_home, team_away, match_time = lines[0], lines[1], " ".join(lines[2:])
    session = get_session()
    try:
        m = FootballMatch(team_home=team_home, team_away=team_away, match_time=match_time,
                           status='open', created_by=update.effective_user.id)
        session.add(m)
        session.commit()
        match_id = m.id
    finally:
        session.close()
    await update.message.reply_text(
        f"✅ بازی #{match_id} اضافه شد و برای پیش‌بینی کاربرا باز شد.\n⚽ {team_home} 🆚 {team_away}\n🕒 {match_time}",
        **reply_kwargs(update.message)
    )


def football_match_text(m):
    status_label = "🟢 باز برای پیش‌بینی" if (m.status or 'open') == 'open' else "🔴 بسته"
    return f"⚽ {m.team_home} 🆚 {m.team_away}\n🕒 {m.match_time}\nوضعیت: {status_label}"


async def football_predict_command(update, context):
    if not await require_membership(update, context): return
    session = get_session()
    try:
        matches = (session.query(FootballMatch).filter(FootballMatch.status == 'open')
                   .order_by(FootballMatch.id.desc()).limit(20).all())
        if not matches:
            await update.message.reply_text("⚽ فعلاً هیچ بازی‌ای برای پیش‌بینی باز نیست.", **reply_kwargs(update.message))
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⚽ {m.team_home} 🆚 {m.team_away} | {m.match_time}", callback_data=f"fbpred:match:{m.id}")]
            for m in matches
        ])
    finally:
        session.close()
    await update.message.reply_text("⚽ پیش‌بینی فوتبال\n\nیه بازی رو انتخاب کن:", reply_markup=kb, **reply_kwargs(update.message))


async def football_predict_match_button(update, context):
    q = update.callback_query
    if not await require_membership(update, context): return
    try:
        match_id = int(q.data.split(":")[2])
    except Exception:
        return
    session = get_session()
    try:
        m = session.get(FootballMatch, match_id)
        if not m or (m.status or 'open') != 'open':
            await q.answer("❌ این بازی دیگه برای پیش‌بینی باز نیست.", show_alert=True); return
        user = get_or_create_user(session, q.from_user)
        existing = session.query(FootballPrediction).filter_by(match_id=match_id, user_id=user.telegram_id).first()
        if existing:
            await q.answer("✅ قبلاً برای این بازی پیش‌بینی کردی.", show_alert=True); return
        text = football_match_text(m) + "\n\n🔮 پیش‌بینیت رو انتخاب کن:"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🏠 برد {m.team_home}", callback_data=f"fbpred:pick:{m.id}:home")],
            [InlineKeyboardButton("🤝 مساوی", callback_data=f"fbpred:pick:{m.id}:draw")],
            [InlineKeyboardButton(f"🚩 برد {m.team_away}", callback_data=f"fbpred:pick:{m.id}:away")],
        ])
    finally:
        session.close()
    await q.answer()
    await _edit_or_send(q, text, kb)


async def football_predict_pick_button(update, context):
    q = update.callback_query
    if not await require_membership(update, context): return
    try:
        _, _, match_id_s, choice = q.data.split(":")
        match_id = int(match_id_s)
    except Exception:
        return
    if choice not in FOOTBALL_CHOICE_LABELS:
        return
    session = get_session()
    try:
        m = session.get(FootballMatch, match_id)
        if not m or (m.status or 'open') != 'open':
            await q.answer("❌ این بازی دیگه برای پیش‌بینی باز نیست.", show_alert=True); return
        user = get_or_create_user(session, q.from_user)
        existing = session.query(FootballPrediction).filter_by(match_id=match_id, user_id=user.telegram_id).first()
        if existing:
            await q.answer("✅ قبلاً برای این بازی پیش‌بینی کردی.", show_alert=True); return
        pred = FootballPrediction(match_id=match_id, user_id=user.telegram_id, choice=choice, status='pending')
        session.add(pred)
        session.commit()
        text = (
            f"✅ پیش‌بینی شما ثبت شد!\n\n⚽ {m.team_home} 🆚 {m.team_away}\n🕒 {m.match_time}\n"
            f"🔮 پیش‌بینی شما: {FOOTBALL_CHOICE_LABELS[choice]}\n\n"
            f"⏳ منتظر تایید پشتیبانی باش؛ در صورت تایید {FOOTBALL_PREDICTION_REWARD:,} روب‌پوینت جایزه می‌گیری."
        )
    finally:
        session.close()
    await q.answer("🔮 پیش‌بینیت ثبت شد!")
    try:
        await q.message.edit_text(text)
    except Exception:
        pass


async def membership_callback(update, context):
    q=update.callback_query
    if q.data!="check_membership": return
    if await is_member_all(context.bot,q.from_user.id):
        await q.answer("عضویت تأیید شد! 🎉")
        session = get_session()
        try:
            existing = session.get(User, q.from_user.id)
            user = get_or_create_user(session, q.from_user)
            payload = context.user_data.pop('pending_referral', None)
            if existing is None and payload:
                await handle_referral_signup(session, user, payload, context)
        finally:
            session.close()
        try:
            await q.message.edit_text(welcome_text(), reply_markup=welcome_keyboard(context))
        except Exception:
            await context.bot.send_message(chat_id=q.message.chat_id, text=welcome_text(), reply_markup=welcome_keyboard(context))
    else: await q.answer("هنوز عضویتت تأیید نشده.",show_alert=True)


def user_display_name(user):return user.username or user.first_name or str(user.telegram_id)
def ranking_position(session,field,value):return session.query(User).filter(getattr(User,field)>value).count()+1
def fox_level_requirement(level):
    req={1:0,2:5,3:15,4:40,5:70,6:115,7:175,8:250,9:350,10:500,11:700,12:950,13:1250,14:1650,15:2150,16:2600,17:3600,18:4600,19:5800,20:7250}
    if level<=20:return req[level]
    value=7250;step=900
    for _ in range(21,level+1):value+=step;step+=250
    return value
async def roobam_command(update,context):
    if not await require_membership(update,context):return
    target=update.message.reply_to_message.from_user if update.message.reply_to_message and update.message.reply_to_message.from_user else update.effective_user
    session=get_session()
    try:
        user=get_or_create_user(session,target);rp=ranking_position(session,'fox_points',user.fox_points or 0);rr=ranking_position(session,'fox_claim_count',user.fox_claim_count or 0);rs=ranking_position(session,'fox_rescued_count',user.fox_rescued_count or 0)
        lvl=max(1,int(user.level or 1)); claim_count=int(user.fox_claim_count or 0); current_req=user_level_requirement(lvl); user_req=user_level_requirement(lvl+1); user_progress=max(0,claim_count-current_req); needed=max(0,user_req-current_req); n=15; f=n if needed==0 or user_progress>=needed else min(n,int(user_progress/needed*n)); bar='▰'*f+'▱'*(n-f)
        text=(f"╮──「 🦊 پروفایل روبی 🦊 」\n\n┐─ 👤 کاربر : {user_display_name(user)}\n‏┘─ 🪪 آیدی : {user.telegram_id}\n\n"+f"┐─ 💰 روب پوینت ها : {int(user.fox_points):,} 🪙\n┘─ 🎖️ رتبه ({rp:,})\n"+f"┐─ 🐾 روب روب ها : {int(user.fox_claim_count or 0):,}\n┘─ 🎖️ رتبه ({rr:,})\n\n"+f"┐─ 🦊 روباه های زخمی نجات یافته : {int(user.fox_rescued_count or 0):,}\n┘─ 🎖️ رتبه ({rs:,})\n\n"+f"╯─ ⭐️ سطح : {lvl} | {max(0, needed-user_progress):,} / {needed:,} {bar}")
    finally:session.close()
    await update.message.reply_text(text,**reply_kwargs(update.message))
# ---------- شهر روبی ----------

CITY_BASE_REQ = {'points': 150, 'rescued': 5, 'hunts': 10, 'treasury': 100_000}
CITY_REQ_GROWTH = 1.5       # ضریب رشد هدف روب‌روب/روباه‌زخمی/شکار در هر ارتقا
CITY_TREASURY_GROWTH = 4    # دارایی مورد نیاز خزانه هر ارتقا ۴ برابر می‌شه
CITY_MAX_LEVEL = 11         # سطح شروع ۱؛ با ۱۰ بار ارتقا به ۱۱ می‌رسه
CITY_CLAIM_COOLDOWN_BONUS = 10  # ثانیه؛ باف «روب روب سریع‌تر»
CITY_DONATE_REWARD = 200    # پاداش هر دونیت‌کننده هنگام ارتقای شهر

# ---------- انتخابات شهرداری ----------
CITY_MAYOR_UNLOCK_LEVEL = 5            # از این سطح شهر به بعد انتخابات فعال می‌شه
CITY_MAYOR_CANDIDACY_COST = 10_000     # هزینه‌ی کاندید شدن
CITY_MAYOR_CANDIDATE_CAPACITY = 5      # حداکثر تعداد کاندید
CITY_MAYOR_TERM_SECONDS = 3 * 24 * 3600        # دوره‌ی شهرداری: هر 3 روز عوض می‌شه
CITY_MAYOR_CANDIDACY_WINDOW_SECONDS = 24 * 3600  # مهلت ثبت‌نام کاندیدها قبل از شروع خودکار رای‌گیری
CITY_MAYOR_VOTING_SECONDS = 5 * 3600           # رای‌گیری حداکثر 5 ساعت طول می‌کشه

def city_requirements(level):
    """هدف لازم برای رفتن از `level` فعلی به سطح بعدی."""
    idx = max(0, (level or 1) - 1)
    mult = CITY_REQ_GROWTH ** idx
    return {
        'points': int(round(CITY_BASE_REQ['points'] * mult)),
        'rescued': int(round(CITY_BASE_REQ['rescued'] * mult)),
        'hunts': int(round(CITY_BASE_REQ['hunts'] * mult)),
        'treasury': int(CITY_BASE_REQ['treasury'] * (CITY_TREASURY_GROWTH ** idx)),
    }

def fa_compact_number(n):
    n = int(n or 0)
    if abs(n) < 1000:
        return f"{n:,}"
    val = n / 1000
    s = f"{val:.2f}".rstrip('0').rstrip('.')
    return f"{s} هزار"

def is_group_chat_id(chat_id):
    return bool(chat_id) and chat_id < 0

def city_ranking_position(session, field, value):
    return session.query(GroupChat).filter(getattr(GroupChat, field) > (value or 0)).count() + 1

def bump_city_stat(session, chat_id, chat_title=None, **deltas):
    """مقادیر شهرِ همون گپ رو با deltas افزایش می‌ده؛ فقط برای گروه/سوپرگروه (چون آیدی‌شون منفیه)."""
    if not is_group_chat_id(chat_id):
        return None
    row = session.get(GroupChat, chat_id)
    if row is None:
        row = GroupChat(chat_id=chat_id, title=chat_title or "گپ", active=1)
        session.add(row); session.flush()
    if row.city_level is None:
        row.city_level = 1
    for field, delta in deltas.items():
        setattr(row, field, (getattr(row, field) or 0) + delta)
    return row

def city_keyboard(chat_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏦 دونیت به خزانه شهر", callback_data=f"citydonate:{chat_id}")]])

def city_mayor_display_label(row):
    if row.city_mayor_id and row.city_mayor_name:
        return f"{row.city_mayor_name} (منتخب مردم 🗳)"
    return f"{row.city_owner_name or 'نامشخص'} (مالک)" if row.city_owner_name else "نامشخص"

def city_panel_text(session, row):
    level = row.city_level or 1
    claim_total = row.city_claim_total or 0
    rescued_total = row.city_rescued_total or 0
    hunt_total = row.city_hunt_total or 0
    treasury = row.city_treasury or 0
    r_claim = city_ranking_position(session, 'city_claim_total', claim_total)
    r_rescued = city_ranking_position(session, 'city_rescued_total', rescued_total)
    r_hunt = city_ranking_position(session, 'city_hunt_total', hunt_total)
    r_treasury = city_ranking_position(session, 'city_treasury', treasury)
    mayor = city_mayor_display_label(row)
    mayor_hint = "\n┘─ 🗳 برای شرکت تو انتخابات شهرداری بنویس «شهردار روبی»" if level >= CITY_MAYOR_UNLOCK_LEVEL else ""
    if level >= CITY_MAX_LEVEL:
        goals_block = "🏆 شهر به بالاترین سطح ممکن رسیده!"
    else:
        req = city_requirements(level)
        goals_block = (
            "🎯 هدف بعدی شهر برای ارتقا سطح ⬇️\n"
            f"┘─ 🐾 روب روب های مورد نیاز : {req['points']:,}\n"
            f"┘─ 🦊 روباه های زخمی مورد نیاز : {req['rescued']:,}\n"
            f"┘─ ⚔️ شکار های مورد نیاز : {req['hunts']:,}\n"
            f"┘─ 🏦 دارایی مورد نیاز خزانه : {fa_compact_number(req['treasury'])} روب پوینت 🪙"
        )
    return (
        f"🦊 شهر روبی {row.title or 'گپ'} 🏰\n\n"
        f"🦁 شهردار : {mayor}{mayor_hint}\n\n"
        f"⭐️ سطح شهر : {level}\n\n"
        f"🐾 روب روب ها : {fa_compact_number(claim_total)}\n"
        f"┘─ 🎖️ رتبه شهر از نظر روب روب کردن (#{r_claim:,})\n\n"
        f"🦊 جمعیت : {fa_compact_number(rescued_total)} روباه\n"
        f"┘─ 🎖️ رتبه شهر از نظر روباه های زخمی (#{r_rescued:,})\n\n"
        f"⚔️ شکار ها : {fa_compact_number(hunt_total)}\n"
        f"┘─ 🎖️ رتبه شهر از نظر شکار (#{r_hunt:,})\n\n"
        f"🏦 خزانه : {fa_compact_number(treasury)} 🪙\n"
        f"┘─ 🎖️ رتبه شهر از نظر خزانه (#{r_treasury:,})\n\n"
        "⏫ باف های شهر ⬇️\n"
        f"┘─ 🐾 روب روب سریعتر : -{CITY_CLAIM_COOLDOWN_BONUS} ثانیه ⏳\n"
        "┘─ 🦊 افزایش جمعیت شهر (روباه های زخمی)\n\n"
        f"{goals_block}"
    )

async def city_command(update, context):
    if not await require_membership(update, context): return
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.message.reply_text("🏙 شهر روبی فقط مخصوص گپ‌هاست؛ این دستور رو تو یه گروه بفرست.", **reply_kwargs(update.message))
        return
    session = get_session()
    try:
        row = session.get(GroupChat, chat.id)
        if row is None:
            row = GroupChat(chat_id=chat.id, title=chat.title or "گپ", active=1)
            session.add(row); session.flush()
        row.title = chat.title or row.title
        if row.city_level is None:
            row.city_level = 1
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            creator = next((a for a in admins if a.status == "creator"), None)
            if creator:
                row.city_owner_id = creator.user.id
                row.city_owner_name = creator.user.full_name or (f"@{creator.user.username}" if creator.user.username else str(creator.user.id))
        except Exception:
            pass
        session.commit()
        text = city_panel_text(session, row)
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=city_keyboard(chat.id), **reply_kwargs(update.message))

async def city_donate_button(update, context):
    q = update.callback_query
    try:
        _, chat_id_s = q.data.split(":")
        chat_id = int(chat_id_s)
    except Exception:
        return
    if not await require_membership(update, context): return
    context.user_data['city_donate_chat_id'] = chat_id
    await q.answer()
    await q.message.reply_text("🏦 مبلغی که می‌خوای به خزانه‌ی شهر دونیت کنی رو بفرست.\nمثال: 5000 / 5k / 5کا")

async def handle_city_donate_text(update, context):
    chat_id = context.user_data.get('city_donate_chat_id')
    if not chat_id:
        return False
    context.user_data.pop('city_donate_chat_id', None)
    if not await require_membership(update, context): return True
    try:
        amount = parse_amount(update.message.text)
    except Exception:
        await update.message.reply_text("❌ مبلغ نامعتبره؛ مثلاً بنویس: 5000 یا 5k", **reply_kwargs(update.message)); return True
    if amount <= 0:
        await update.message.reply_text("❌ مبلغ نامعتبره.", **reply_kwargs(update.message)); return True
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
        if (user.fox_points or 0) < amount:
            await update.message.reply_text("❌ روب‌پوینت کافی نداری.", **reply_kwargs(update.message)); return True
        row = session.get(GroupChat, chat_id)
        if not row:
            await update.message.reply_text("❌ این گپ شهر نداره.", **reply_kwargs(update.message)); return True
        user.fox_points -= amount
        row.city_treasury = (row.city_treasury or 0) + amount
        donors = set(x for x in (row.city_donors or '').split(',') if x)
        donors.add(str(user.telegram_id))
        row.city_donors = ','.join(donors)
        session.commit()
        chat_title = row.title
    finally:
        session.close()
    await update.message.reply_text(f"🏦 {amount:,} روب‌پوینت به خزانه‌ی شهر «{chat_title}» دونیت کردی! 🙏", **reply_kwargs(update.message))
    await maybe_level_up_city(context, chat_id)
    return True

async def maybe_level_up_city(context, chat_id):
    """اگه شهر به همه‌ی هدف‌های سطح بعد رسیده باشه، ارتقاش می‌ده، به دونیت‌کننده‌های این چرخه
    ۲۰۰ روب‌پوینت می‌ده و تو پیوی بهشون خبر می‌ده، و تو گپ تبریک می‌گه."""
    if not is_group_chat_id(chat_id):
        return
    session = get_session()
    new_level = None; donor_ids = []; chat_title = "گپ"
    try:
        row = session.get(GroupChat, chat_id)
        if not row:
            return
        if row.city_level is None:
            row.city_level = 1
        if row.city_level >= CITY_MAX_LEVEL:
            return
        req = city_requirements(row.city_level)
        if not ((row.city_claim_total or 0) >= req['points'] and (row.city_rescued_total or 0) >= req['rescued']
                and (row.city_hunt_total or 0) >= req['hunts'] and (row.city_treasury or 0) >= req['treasury']):
            return
        row.city_level += 1
        new_level = row.city_level
        donor_ids = [int(x) for x in (row.city_donors or '').split(',') if x]
        row.city_donors = ''
        chat_title = row.title or "گپ"
        for did in donor_ids:
            u = session.get(User, did)
            if u: u.fox_points = (u.fox_points or 0) + CITY_DONATE_REWARD
        session.commit()
    finally:
        session.close()
    if new_level is None:
        return
    try:
        await context.bot.send_message(
            chat_id,
            f"🎉🏙 تبریک میگم! شهر روبی «{chat_title}» به سطح {new_level} ارتقا پیدا کرد! 🥳\n"
            "همه‌ی اهالی گپ دست‌مریزاد 👏"
        )
    except Exception:
        pass
    for did in donor_ids:
        try:
            await context.bot.send_message(
                did,
                f"🎉 ممنون بابت دونیتت به خزانه‌ی شهر «{chat_title}»!\n"
                f"همین کمک باعث شد شهر بره سطح {new_level} و بابتش {CITY_DONATE_REWARD:,} روب‌پوینت بهت هدیه دادیم 🎁"
            )
        except Exception:
            pass

# ---------- انتخابات شهرداری (از سطح شهر 5 به بعد) ----------

def city_mayor_candidate_ids(row):
    return [int(x) for x in (row.city_election_candidates or '').split(',') if x]

def city_mayor_votes_map(row):
    """{آیدی رای‌دهنده: آیدی کاندید}"""
    votes = {}
    for pair in (row.city_election_votes or '').split(','):
        if not pair or ':' not in pair:
            continue
        voter_s, cand_s = pair.split(':', 1)
        try:
            votes[int(voter_s)] = int(cand_s)
        except ValueError:
            continue
    return votes

def city_mayor_vote_counts(row):
    counts = {cid: 0 for cid in city_mayor_candidate_ids(row)}
    for cand_id in city_mayor_votes_map(row).values():
        counts[cand_id] = counts.get(cand_id, 0) + 1
    return counts

def city_mayor_start_candidacy(row):
    row.city_election_status = 'candidacy'
    row.city_election_candidates = ''
    row.city_election_votes = ''
    row.city_election_candidacy_ends_at = now_utc() + timedelta(seconds=CITY_MAYOR_CANDIDACY_WINDOW_SECONDS)
    row.city_election_voting_ends_at = None

def city_mayor_start_voting(row):
    row.city_election_status = 'voting'
    row.city_election_voting_ends_at = now_utc() + timedelta(seconds=CITY_MAYOR_VOTING_SECONDS)

def city_mayor_panel_text(session, row):
    status = row.city_election_status or 'none'
    title = row.title or 'گپ'
    if status == 'candidacy':
        cands = city_mayor_candidate_ids(row)
        end = aware(row.city_election_candidacy_ends_at)
        left = max(0, int((end - now_utc()).total_seconds())) if end else 0
        lines = [
            f"🗳 ثبت‌نام کاندیدهای شهرداری «{title}» بازه!",
            f"💰 هزینه‌ی کاندید شدن : {CITY_MAYOR_CANDIDACY_COST:,} روب‌پوینت",
            f"👥 ظرفیت کاندید : {len(cands)} / {CITY_MAYOR_CANDIDATE_CAPACITY}",
            f"⏳ مهلت ثبت‌نام : {format_duration(left)} دیگه (یا زودتر اگه ظرفیت پر بشه)",
        ]
        if cands:
            lines.append("")
            lines.append("👤 کاندیدهای فعلی ⬇️")
            for cid in cands:
                u = session.get(User, cid)
                lines.append(f"┘─ {user_display_name(u) if u else cid}")
        return "\n".join(lines)
    if status == 'voting':
        cands = city_mayor_candidate_ids(row)
        counts = city_mayor_vote_counts(row)
        end = aware(row.city_election_voting_ends_at)
        left = max(0, int((end - now_utc()).total_seconds())) if end else 0
        lines = [
            f"🗳 رای‌گیری شهرداری «{title}» در جریانه!",
            f"⏳ تا پایان رای‌گیری : {format_duration(left)} دیگه",
            "",
            "👤 کاندیدها ⬇️",
        ]
        for cid in cands:
            u = session.get(User, cid)
            lines.append(f"┘─ {user_display_name(u) if u else cid} — {counts.get(cid, 0):,} رای")
        lines.append("")
        lines.append("هر کاربر فقط یک بار می‌تونه رای بده.")
        return "\n".join(lines)
    if row.city_mayor_id:
        end = aware(row.city_mayor_term_ends_at)
        left = max(0, int((end - now_utc()).total_seconds())) if end else 0
        return (
            f"🦁 شهردار فعلی «{title}» : {row.city_mayor_name or row.city_mayor_id}\n"
            f"⏳ تا پایان این دوره : {format_duration(left)} دیگه\n"
            "بعد از پایان دوره، دور بعدی انتخابات خودکار باز می‌شه."
        )
    return f"🗳 هنوز شهرداری برای «{title}» انتخاب نشده؛ همین الان یه دور جدید انتخابات باز شد."

def city_mayor_keyboard(session, row):
    status = row.city_election_status or 'none'
    if status == 'candidacy':
        return InlineKeyboardMarkup([[InlineKeyboardButton(
            f"🙋 کاندید شدن ({CITY_MAYOR_CANDIDACY_COST:,} روب‌پوینت)", callback_data=f"citymayor:cand:{row.chat_id}"
        )]])
    if status == 'voting':
        rows = []
        for cid in city_mayor_candidate_ids(row):
            u = session.get(User, cid)
            name = user_display_name(u) if u else str(cid)
            rows.append([InlineKeyboardButton(f"🗳 رای به {name}", callback_data=f"citymayor:vote:{row.chat_id}:{cid}")])
        return InlineKeyboardMarkup(rows) if rows else None
    return None

async def city_mayor_command(update, context):
    if not await require_membership(update, context): return
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.message.reply_text("🗳 انتخابات شهرداری فقط مخصوص گپ‌هاست؛ این دستور رو تو یه گروه بفرست.", **reply_kwargs(update.message))
        return
    session = get_session()
    started_new = False
    try:
        row = session.get(GroupChat, chat.id)
        if row is None:
            row = GroupChat(chat_id=chat.id, title=chat.title or "گپ", active=1)
            session.add(row); session.flush()
        row.title = chat.title or row.title
        if row.city_level is None:
            row.city_level = 1
        level = row.city_level or 1
        locked = level < CITY_MAYOR_UNLOCK_LEVEL
        if locked:
            text = (
                f"🔒 انتخابات شهرداری از سطح شهر {CITY_MAYOR_UNLOCK_LEVEL} به بعد باز می‌شه.\n"
                f"⭐️ سطح فعلی شهر : {level}"
            )
            markup = None
        else:
            status = row.city_election_status or 'none'
            term_ends = aware(row.city_mayor_term_ends_at)
            if not (status == 'none' and row.city_mayor_id and term_ends and now_utc() < term_ends):
                if status == 'none':
                    city_mayor_start_candidacy(row)
                    status = 'candidacy'
                    started_new = True
            text = city_mayor_panel_text(session, row)
            markup = city_mayor_keyboard(session, row)
        chat_id = row.chat_id
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=markup, **reply_kwargs(update.message))
    if started_new and context.job_queue:
        context.job_queue.run_once(
            city_mayor_candidacy_timeout_job, CITY_MAYOR_CANDIDACY_WINDOW_SECONDS,
            data=chat_id, name=f"citymayor-cand-{chat_id}"
        )

async def city_mayor_candidate_button(update, context):
    q = update.callback_query
    try:
        _, _, chat_id_s = q.data.split(":")
        chat_id = int(chat_id_s)
    except Exception:
        return
    if not await require_membership(update, context): return
    session = get_session()
    capacity_full = False
    try:
        row = session.get(GroupChat, chat_id)
        if not row or (row.city_level or 1) < CITY_MAYOR_UNLOCK_LEVEL:
            await q.answer("❌ این انتخابات فعال نیست.", show_alert=True); return
        if (row.city_election_status or 'none') != 'candidacy':
            await q.answer("⏳ الان زمان ثبت‌نام کاندید نیست.", show_alert=True); return
        cands = city_mayor_candidate_ids(row)
        user = get_or_create_user(session, q.from_user)
        if user.telegram_id in cands:
            await q.answer("✅ قبلاً کاندید شدی.", show_alert=True); return
        if len(cands) >= CITY_MAYOR_CANDIDATE_CAPACITY:
            await q.answer("❌ ظرفیت کاندیدها پر شده.", show_alert=True); return
        if (user.fox_points or 0) < CITY_MAYOR_CANDIDACY_COST:
            await q.answer("❌ روب‌پوینت کافی نداری.", show_alert=True); return
        user.fox_points -= CITY_MAYOR_CANDIDACY_COST
        cands.append(user.telegram_id)
        row.city_election_candidates = ','.join(str(c) for c in cands)
        capacity_full = len(cands) >= CITY_MAYOR_CANDIDATE_CAPACITY
        if capacity_full:
            city_mayor_start_voting(row)
        session.commit()
        text = city_mayor_panel_text(session, row)
        markup = city_mayor_keyboard(session, row)
    finally:
        session.close()
    await q.answer("🙋 کاندید شدی!")
    try:
        await q.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    if capacity_full and context.job_queue:
        context.job_queue.run_once(
            city_mayor_voting_timeout_job, CITY_MAYOR_VOTING_SECONDS,
            data=chat_id, name=f"citymayor-vote-{chat_id}"
        )

async def city_mayor_vote_button(update, context):
    q = update.callback_query
    try:
        _, _, chat_id_s, cand_id_s = q.data.split(":")
        chat_id = int(chat_id_s); cand_id = int(cand_id_s)
    except Exception:
        return
    if not await require_membership(update, context): return
    session = get_session()
    try:
        row = session.get(GroupChat, chat_id)
        if not row or (row.city_election_status or 'none') != 'voting':
            await q.answer("❌ الان رای‌گیری فعال نیست.", show_alert=True); return
        if cand_id not in city_mayor_candidate_ids(row):
            await q.answer("❌ این کاندید معتبر نیست.", show_alert=True); return
        user = get_or_create_user(session, q.from_user)
        votes = city_mayor_votes_map(row)
        if user.telegram_id in votes:
            await q.answer("✅ قبلاً رای دادی.", show_alert=True); return
        votes[user.telegram_id] = cand_id
        row.city_election_votes = ','.join(f"{v}:{c}" for v, c in votes.items())
        session.commit()
        text = city_mayor_panel_text(session, row)
        markup = city_mayor_keyboard(session, row)
    finally:
        session.close()
    await q.answer("🗳 رایت ثبت شد!")
    try:
        await q.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass

async def city_mayor_candidacy_timeout_job(context):
    """اگه بعد از مهلت ثبت‌نام هنوز تو فاز candidacy بودیم: با حداقل یه کاندید رای‌گیری رو شروع می‌کنه،
    وگرنه (صفر کاندید) انتخابات رو می‌بنده تا دفعه‌ی بعد با «شهردار روبی» دوباره باز بشه."""
    chat_id = int(context.job.data)
    session = get_session()
    try:
        row = session.get(GroupChat, chat_id)
        if not row or (row.city_election_status or 'none') != 'candidacy':
            return
        cands = city_mayor_candidate_ids(row)
        chat_title = row.title or "گپ"
        if not cands:
            row.city_election_status = 'none'
            row.city_election_candidacy_ends_at = None
            session.commit()
            no_candidates = True
        else:
            city_mayor_start_voting(row)
            session.commit()
            no_candidates = False
    finally:
        session.close()
    if no_candidates:
        try:
            await context.bot.send_message(
                chat_id,
                f"🗳 مهلت ثبت‌نام کاندیدهای شهرداری «{chat_title}» تموم شد و هیچ‌کس کاندید نشد؛ "
                "دفعه‌ی بعد که «شهردار روبی» زده بشه، ثبت‌نام دوباره باز می‌شه."
            )
        except Exception:
            pass
        return
    try:
        await context.bot.send_message(
            chat_id,
            f"🗳 مهلت ثبت‌نام کاندیدهای شهرداری «{chat_title}» تموم شد؛ رای‌گیری شروع شد!\n"
            "برای رای دادن بنویس «شهردار روبی»."
        )
    except Exception:
        pass
    if context.job_queue:
        context.job_queue.run_once(
            city_mayor_voting_timeout_job, CITY_MAYOR_VOTING_SECONDS,
            data=chat_id, name=f"citymayor-vote-{chat_id}"
        )

async def city_mayor_voting_timeout_job(context):
    """رای‌گیری رو می‌بنده، کاندیدی که بیشترین رای رو داره (در تساوی، اولین کاندید ثبت‌نامی) شهردار می‌کنه،
    دوره‌ی 3 روزه‌ی شهرداریش رو شروع می‌کنه و اعلام عمومی/خصوصی می‌فرسته."""
    chat_id = int(context.job.data)
    session = get_session()
    winner_id = None
    try:
        row = session.get(GroupChat, chat_id)
        if not row or (row.city_election_status or 'none') != 'voting':
            return
        cands = city_mayor_candidate_ids(row)
        counts = city_mayor_vote_counts(row)
        chat_title = row.title or "گپ"
        best = -1
        for cid in cands:
            c = counts.get(cid, 0)
            if c > best:
                best = c; winner_id = cid
        winner_name = None
        if winner_id:
            u = session.get(User, winner_id)
            winner_name = user_display_name(u) if u else str(winner_id)
            row.city_mayor_id = winner_id
            row.city_mayor_name = winner_name
            row.city_mayor_term_ends_at = now_utc() + timedelta(seconds=CITY_MAYOR_TERM_SECONDS)
        row.city_election_status = 'none'
        row.city_election_candidates = ''
        row.city_election_votes = ''
        row.city_election_candidacy_ends_at = None
        row.city_election_voting_ends_at = None
        session.commit()
    finally:
        session.close()
    if not winner_id:
        try:
            await context.bot.send_message(chat_id, f"🗳 رای‌گیری شهرداری «{chat_title}» بدون کاندید تموم شد.")
        except Exception:
            pass
        return
    term_days = CITY_MAYOR_TERM_SECONDS // 86400
    try:
        await context.bot.send_message(
            chat_id,
            f"🎉 «{winner_name}» با بیشترین رای، شهردار جدید «{chat_title}» شد! 🦁\n"
            f"این دوره {term_days} روز ادامه داره."
        )
    except Exception:
        pass
    try:
        await context.bot.send_message(winner_id, f"🎉 تبریک! تو شهردار جدید «{chat_title}» شدی 🦁🏰")
    except Exception:
        pass

CITY_LEADERBOARD_CATEGORIES = [
    ('city_hunt_total', '⚔️ شکارها'),
    ('city_claim_total', '🐾 روب روب ها'),
    ('city_treasury', '💰 خزانه'),
    ('city_rescued_total', '🦊 جمعیت شهر'),
]
CITY_LEADERBOARD_MAP = dict(CITY_LEADERBOARD_CATEGORIES)

LEADERBOARD_CATEGORIES = [
    ('fox_points', '💰 روب پوینت 🦊'),
    ('fox_rescued_count', '🎃 روباه های زخمی'),
    ('hunt_count', '⚔️ شکار'),
    ('fox_claim_count', '🐾 روب روب'),
]
LEADERBOARD_CATEGORY_MAP = dict(LEADERBOARD_CATEGORIES)

LEADERBOARD_LIMIT = 100      # حداکثر تعداد نفراتی که در رتبه‌بندی در نظر گرفته می‌شوند
LEADERBOARD_PAGE_SIZE = 10   # تعداد نفرات در هر صفحه


def leaderboard_city_keyboard():
    rows = [[InlineKeyboardButton(title, callback_data=f"lb:gcat:{field}:1")] for field, title in CITY_LEADERBOARD_CATEGORIES]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="lb:root")])
    return InlineKeyboardMarkup(rows)


def leaderboard_root_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 لیدر برد جهانی", callback_data="lb:global")],
        [InlineKeyboardButton("👥 لیدر برد گروهی", callback_data="lb:group")],
    ])


def leaderboard_global_keyboard():
    rows = [[InlineKeyboardButton(title, callback_data=f"lb:cat:{field}:1")] for field, title in LEADERBOARD_CATEGORIES]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="lb:root")])
    return InlineKeyboardMarkup(rows)


def _leaderboard_page_bounds(total_rows, page):
    """صفحه‌بندی بدون حذف هیچ نفری: تعداد صفحات از روی کل نفرات محاسبه می‌شود."""
    total_pages = max(1, -(-total_rows // LEADERBOARD_PAGE_SIZE))  # ceil division
    page = max(1, min(page, total_pages))
    start = (page - 1) * LEADERBOARD_PAGE_SIZE
    end = start + LEADERBOARD_PAGE_SIZE
    return start, end, page, total_pages


def _render_leaderboard_page(title, entries, page):
    """entries: لیست تاپل‌های (متن_ردیف) از قبل رتبه‌بندی‌شده برای کل ۱۰۰ نفر."""
    start, end, page, total_pages = _leaderboard_page_bounds(len(entries), page)
    page_rows = entries[start:end]
    lines = [f'╭──「 {title} 」', '']
    for row_text in page_rows:
        lines.append(row_text)
        lines.append('')  # کمی فاصله بین هر نفر و نفر بعدی
    if not page_rows:
        lines.append('هنوز کسی در این بخش رتبه‌ای ندارد.')
        lines.append('')
    lines.append(f'📄 صفحه {page} از {total_pages}')
    return '\n'.join(lines), page, total_pages


def build_city_leaderboard_text(session, field, title, page=1):
    rows = session.query(GroupChat).order_by(getattr(GroupChat, field).desc(), GroupChat.chat_id.asc()).limit(LEADERBOARD_LIMIT).all()
    entries = [f'{i}. {r.title or "گپ"} — {fa_compact_number(getattr(r, field) or 0)}' for i, r in enumerate(rows, 1)]
    return _render_leaderboard_page(title, entries, page)


def build_leaderboard_text(session, field, title, page=1):
    users = session.query(User).order_by(getattr(User, field).desc(), User.telegram_id.asc()).limit(LEADERBOARD_LIMIT).all()
    entries = [f'{i}. {user_display_name(u)} — {int(getattr(u, field) or 0):,}' for i, u in enumerate(users, 1)]
    return _render_leaderboard_page(title, entries, page)


def leaderboard_page_keyboard(kind, field, page, total_pages, back_data):
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"lb:{kind}:{field}:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"lb:{kind}:{field}:{page+1}"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_data)])
    return InlineKeyboardMarkup(rows)


async def leaderboard_command(update, context):
    if not await require_membership(update, context): return
    await update.message.reply_text(
        "🏆 لیدر برد کدوم بخش رو می‌خوای ببینی؟",
        reply_markup=leaderboard_root_keyboard(), **reply_kwargs(update.message)
    )

async def leaderboard_button(update, context):
    q = update.callback_query
    data = q.data
    if data == "lb:root":
        await q.answer()
        try: await q.message.edit_text("🏆 لیدر برد کدوم بخش رو می‌خوای ببینی؟", reply_markup=leaderboard_root_keyboard())
        except Exception: pass
        return
    if data == "lb:global":
        await q.answer()
        try: await q.message.edit_text("🌍 لیدر برد جهانی — کدوم رتبه‌بندی رو می‌خوای ببینی؟", reply_markup=leaderboard_global_keyboard())
        except Exception: pass
        return
    if data == "lb:group":
        await q.answer()
        try: await q.message.edit_text("👥 لیدر برد گروهی — کدوم رتبه‌بندی رو می‌خوای ببینی؟", reply_markup=leaderboard_city_keyboard())
        except Exception: pass
        return
    if data.startswith("lb:gcat:"):
        parts = data.split(":")
        field = parts[2]
        try:
            page = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            page = 1
        if field not in CITY_LEADERBOARD_MAP:
            await q.answer(); return
        await q.answer()
        session = get_session()
        try:
            text, page, total_pages = build_city_leaderboard_text(session, field, CITY_LEADERBOARD_MAP[field], page)
        finally:
            session.close()
        kb = leaderboard_page_keyboard("gcat", field, page, total_pages, "lb:group")
        try: await q.message.edit_text(text, reply_markup=kb)
        except Exception: pass
        return
    if data.startswith("lb:cat:"):
        parts = data.split(":")
        field = parts[2]
        try:
            page = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            page = 1
        if field not in LEADERBOARD_CATEGORY_MAP:
            await q.answer(); return
        await q.answer()
        session = get_session()
        try:
            text, page, total_pages = build_leaderboard_text(session, field, LEADERBOARD_CATEGORY_MAP[field], page)
        finally:
            session.close()
        kb = leaderboard_page_keyboard("cat", field, page, total_pages, "lb:global")
        try: await q.message.edit_text(text, reply_markup=kb)
        except Exception: pass
        return

async def text_router(update, context):
    if not update.message or not update.message.text: return
    if await handle_jail_memory_text(update, context): return
    if await handle_gift_text(update, context): return
    if await handle_points_text(update, context): return
    if await handle_bank_text(update, context): return
    if await handle_fox_rename_text(update, context): return
    if await handle_ruby_entry_text(update, context): return
    if await handle_city_donate_text(update, context): return
    text=update.message.text.strip()
    if text in FOX_CLAIM_ALIASES:
        await collect_fox_points(update,context); return
    if text in {"روبام","روبام!","روباش","روباش!"}: await roobam_command(update,context); return
    if text in {"گردونه", "چرخ شانس", "🎡 گردونه", "🎡 چرخ شانس"}: await wheel_command(update,context); return
    if text in {"لیدر برد","لیدربرد","leaderboard","Leaderboard"}: await leaderboard_command(update,context); return
    if text in {"شهر روبی","شهر روباهیو","شهر روباه","🦊 شهر روبی"}: await city_command(update,context); return
    if text in {"شهردار روبی","شهردار","🦁 شهردار روبی"}: await city_mayor_command(update,context); return
    if re.sub(r"\s+", " ", text) in {"روباه", "روباه روباه", "روبی", "روباهیو", "🦊 روباه", "🦊 روبی", "🦊 روباهیو"}:
        await fox_command(update, context); return
    if text in {"زندان روبی", "زندان روباهیو", "⛓️ زندان روبی"}:
        await jail_command(update, context); return
    if text in {"قاچاق روبی", "قاچاق روباهیو", "🥷 قاچاق روبی", "🥷 قاچاق روباهیو"}:
        await smuggling_command(update, context); return
    if text in {"شکار", "شکار!", "🏹 شکار"}:
        await hunt_command(update, context); return
    if text in {"یخچال روبی", "🧊 یخچال روبی"}:
        await fridge_command(update, context); return
    if text in {"کارخونه روبی", "کارخونه روبی!", "کارخونه", "🏭 کارخونه روبی"}:
        await factory_command(update, context); return
    if re.sub(r"[\s‌]+", " ", text) in {"رفرال", "زیرمجموعه گیری", "زیر مجموعه گیری", "🔗 رفرال", "زیرمجموعه"}:
        await referral_command(update, context); return
    if text in {"بانک", "بانک روبی", "🏦 بانک روبی"}:
        await bank_command(update, context); return
    if text in {"شاپ روبی", "فروشگاه روبی", "🎁 شاپ روبی", "🎁 فروشگاه روبی"}:
        await gift_shop_command(update, context); return
    if text in {"بازی روبی", "بازی های روبی", "بازی‌های روبی", "🕹 بازی های روبی"}:
        await ruby_games_command(update, context); return
    if text in {"کازینو روبی", "کازینو", "🃏 کازینو روبی"}:
        await casino_command(update, context); return
    if re.sub(r"[\s‌]+", " ", text) in {"پیش بینی", "پیش بینی فوتبال", "⚽ پیش بینی", "پیشبینی"}:
        await football_predict_command(update, context); return
    # انتقال روب پوینت 50 — فقط با ریپلای به گیرنده
    m = re.fullmatch(r"انتقال\s+روب\s+پوینت\s+([0-9۰-۹.,]+(?:k|کی|کا|m|م|میل)?)", text, re.I)
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
    m = re.fullmatch(r"/(روباه(?:\s+روباه)?|روبی|روباهیو|شکار|یخچال|کارخونه(?:\s+روبی)?|روبام|روباش|لیدربرد|گردونه|چرخ|بازی(?:\s+روبی)?|کازینو(?:\s+روبی)?|شهر(?:\s+روبی)?|شهردار(?:\s+روبی)?|قاچاق(?:\s+روبی|\s+روباهیو)?|زندان(?:\s+روبی|\s+روباهیو)?|رفرال|زیرمجموعه(?:\s+گیری)?)(?:@\w+)?", text)
    if m:
        cmd = m.group(1)
        if cmd in {"روباه","روبی","روباهیو"}: await fox_command(update,context)
        elif cmd in {"کارخونه روبی","کارخونه"}: await factory_command(update,context)
        elif cmd in {"رفرال","زیرمجموعه","زیرمجموعه گیری"}: await referral_command(update,context)
        elif cmd in {"بازی روبی","بازی"}: await ruby_games_command(update,context)
        elif cmd in {"کازینو روبی","کازینو"}: await casino_command(update,context)
        elif cmd in {"گردونه","چرخ"}: await wheel_command(update,context)
        elif cmd in {"قاچاق روبی","قاچاق روباهیو","قاچاق"}: await smuggling_command(update,context)
        elif cmd in {"زندان روبی","زندان روباهیو","زندان"}: await jail_command(update,context)
        elif cmd=="شکار": await hunt_command(update,context)
        elif cmd=="یخچال": await fridge_command(update,context)
        elif cmd in {"روبام","روباش"}: await roobam_command(update,context)
        elif cmd in {"شهردار روبی","شهردار"}: await city_mayor_command(update,context)
        elif cmd in {"شهر روبی","شهر"}: await city_command(update,context)
        else: await leaderboard_command(update,context)
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
    if app.job_queue is None:
        raise RuntimeError("JobQueue is unavailable. Install python-telegram-bot[job-queue].")
    app.add_handler(CommandHandler("start",start_command))
    app.add_handler(CommandHandler("profile",profile_command))
    app.add_handler(CommandHandler("games",games_command))
    app.add_handler(CommandHandler("game",game_command))
    app.add_handler(CommandHandler("challenge",challenge_command))
    app.add_handler(CommandHandler("admin",admin_command))
    app.add_handler(CommandHandler("transfer",transfer_command))
    app.add_handler(CommandHandler("hunt",hunt_command))
    app.add_handler(CommandHandler("fox",fox_command))
    app.add_handler(CommandHandler("factory",factory_command))
    app.add_handler(CommandHandler("referral",referral_command))
    app.add_handler(CommandHandler("roobam",roobam_command))
    app.add_handler(CommandHandler("leaderboard",leaderboard_command))
    app.add_handler(CallbackQueryHandler(jail_callback_gate), group=-20)
    app.add_handler(CallbackQueryHandler(membership_callback,pattern=r"^check_membership$"))
    app.add_handler(CallbackQueryHandler(guide_callback,pattern=r"^guide:(main|home|item:\d+)$"))
    app.add_handler(CallbackQueryHandler(admin_callback,pattern=r"^admin:(stats|users|broadcast|addpoints|giftall|setlevel|setfoxpoints|banmenu|backup)$"))
    app.add_handler(CallbackQueryHandler(admin_banset_callback,pattern=r"^admin:banset:(?:1|7|30|permanent|unban)$"))
    app.add_handler(CallbackQueryHandler(accept_challenge,pattern=r"^accept:\d+$"))
    app.add_handler(CallbackQueryHandler(throw_dice,pattern=r"^throw:\d+:[12]$"))
    app.add_handler(CallbackQueryHandler(fox_button,pattern=r"^fox:(collect|upgrade|hunt|fridge|rename|resetask|resetyes|resetno):\d+$"))
    app.add_handler(CallbackQueryHandler(hunt_button,pattern=r"^hunt:(feed|sell|fridge):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(fridge_button,pattern=r"^fridge:(view|item|cook|sell|feed|upgrade):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(factory_button,pattern=r"^factory:"))
    app.add_handler(CallbackQueryHandler(referral_admin_button,pattern=r"^ref:(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_game_select,pattern=r"^rg:(xo|rps|darts|basketball|bowling|cz_wheel|cz_dice|cz_rabbit|cz_pairs):\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_count_select,pattern=r"^rcount:(xo|rps|darts|basketball|bowling|cz_wheel|cz_dice|cz_rabbit|cz_pairs):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_create_table,pattern=r"^rcreate:(xo|rps|darts|basketball|bowling|cz_wheel|cz_rabbit|cz_pairs):\d+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_dice_bet_select,pattern=r"^rdicebet:\d+:\d+:\d+:(odd|even|high|low)$"))
    app.add_handler(CallbackQueryHandler(ruby_join_table,pattern=r"^rjoin:\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_rps_choice,pattern=r"^rrps:\d+:(rock|paper|scissors)$"))
    app.add_handler(CallbackQueryHandler(ruby_xo_move,pattern=r"^rxo:\d+:[0-8]$"))
    app.add_handler(CallbackQueryHandler(ruby_rabbit_choice,pattern=r"^rrabbit:\d+:(?:[0-9]|1[0-9])$"))
    app.add_handler(CallbackQueryHandler(ruby_pairs_move,pattern=r"^rpairs:\d+:(?:[0-9]|1[0-9]|2[0-9])$"))
    app.add_handler(MessageHandler(filters.REPLY & filters.Dice.ALL, ruby_dice_reply), group=0)
    app.add_handler(CallbackQueryHandler(bank_transfer_confirm,pattern=r"^bankconfirm:(yes|no):\d+$"))
    app.add_handler(CallbackQueryHandler(bank_withdraw_button,pattern=r"^bank:w:\d+:(?:25|50|75|100)$"))
    app.add_handler(CallbackQueryHandler(bank_button,pattern=r"^bank:(?:withdraw|deposit|transfer|transactions|change):\d+$"))
    app.add_handler(CallbackQueryHandler(gift_button,pattern=r"^gift:(?:pick|opt|qty|qtyok|backshop|backopt|tiers|backtiers|notext|noop):[^:]+:[^:]+$"))
    app.add_handler(CallbackQueryHandler(points_button,pattern=r"^points:(?:shop|pick|backshop):[^:]+:[^:]+$"))
    app.add_handler(CallbackQueryHandler(points_admin_button,pattern=r"^pts:(?:approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(transfer_button,pattern=r"^transfer:(yes|no):\d+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(injured_fox_button,pattern=r"^injured:rescue:\d+$"))
    app.add_handler(CallbackQueryHandler(fox_sickness_button,pattern=r"^foxsick:(pill|syrup|rest):\d+$"))
    app.add_handler(CallbackQueryHandler(jail_button,pattern=r"^jail:(memory|pay):\d+$"))
    app.add_handler(CallbackQueryHandler(smuggling_button,pattern=r"^smuggle:(plus|minus|all|confirm):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(leaderboard_button,pattern=r"^lb:"))
    app.add_handler(CallbackQueryHandler(city_donate_button,pattern=r"^citydonate:-?\d+$"))
    app.add_handler(CallbackQueryHandler(city_mayor_candidate_button,pattern=r"^citymayor:cand:-?\d+$"))
    app.add_handler(CallbackQueryHandler(city_mayor_vote_button,pattern=r"^citymayor:vote:-?\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_football_callback,pattern=r"^admin:(football(:.*)?|back)$"))
    app.add_handler(CallbackQueryHandler(football_predict_match_button,pattern=r"^fbpred:match:\d+$"))
    app.add_handler(CallbackQueryHandler(football_predict_pick_button,pattern=r"^fbpred:pick:\d+:(home|draw|away)$"))
    # دستورهای فارسی با MessageHandler ثبت می‌شوند؛ CommandHandler آن‌ها را رد می‌کند.
    app.add_handler(MessageHandler(filters.Regex(r"^/(?:روباه|روبی|روباهیو|شکار|یخچال|کارخونه(?:\s+روبی)?|روبام|روباش|لیدربرد|گردونه|چرخ|بازی(?:\s+روبی)?|کازینو(?:\s+روبی)?|شهر(?:\s+روبی)?|شهردار(?:\s+روبی)?|قاچاق(?:\s+روبی|\s+روباهیو)?|زندان(?:\s+روبی|\s+روباهیو)?)(?:@\w+)?$") | filters.Regex(r"^/انتقال(?:@\w+)?(?:\s+روب\s+پوینت)?\s+[0-9,]+$"), persian_slash_router), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=list(ADMIN_IDS)),admin_text),group=0)
    app.add_handler(MessageHandler(filters.ALL,ban_gate),group=-10)
    app.add_handler(MessageHandler(filters.ALL,purchase_flow_gate),group=-9)
    app.add_handler(MessageHandler(filters.Regex(rf"^{re.escape(CLAIM_KEYWORD)}$"),claim_points),group=1)
    app.add_handler(ChatMemberHandler(bot_joined_group, ChatMemberHandler.MY_CHAT_MEMBER), group=-2)
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, register_group_chat), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router),group=2)
    if app.job_queue:
        app.job_queue.run_repeating(settle_all_smuggling, interval=30, first=10, name="ruby-smuggling-settler")
        app.job_queue.run_repeating(post_injured_fox_job, interval=INJURED_FOX_INTERVAL, first=5, name="injured-fox")
        app.job_queue.run_repeating(update_market_prices_job, interval=FACTORY_MARKET_UPDATE_SECONDS, first=15, name="factory-market")
        if ADMIN_IDS:
            app.job_queue.run_repeating(daily_backup_job, interval=BACKUP_INTERVAL_SECONDS, first=60, name="daily-backup")
    db_kind = "PostgreSQL (پایدار ✅)" if DATABASE_URL.startswith("postgres") else "SQLite محلی (⚠️ روی Railway بدون Volume با هر دیپلوی پاک می‌شود)"
    logger.info(f"Database in use: {db_kind}")
    logger.info("Bot started polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
