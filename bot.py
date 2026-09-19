import asyncio
import io
import json
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile, InputMediaPhoto, MessageEntity, User as TgUser
from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
from telegram.ext import (
    ApplicationBuilder, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ChatMemberHandler,
    ContextTypes, MessageHandler, filters, ExtBot
)

from config import (
    ADMIN_IDS, BOT_TOKEN, CLAIM_COOLDOWN_SECONDS, CLAIM_KEYWORD, REFERRAL_REWARD,
    CLAIM_POINTS_MAX, CLAIM_POINTS_MIN, REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL,
    REQUIRED_CHANNEL_2, REQUIRED_CHANNEL_2_URL, DATABASE_URL
)
from database import (
    Challenge, FoxHunt, GroupChat, InjuredFox, User, BankAccount, BankTransaction, RubyTable, RubySmuggling, JailWallMemory,
    FootballMatch, FootballPrediction, GiftOrder, FactoryOrder, FactoryInventory, MarketPrice, Referral, PointsPurchase, FriendRequest, Friendship, CityDonation, GiftCode, GiftCodeRedemption, get_session, init_db
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

# ---------- نام‌های آبی و کلیک‌پذیر (TEXT_MENTION) ----------
# هر جا اسم یک کاربر داخل «متن» پیام می‌آید با user_mention(...) / mention_of(...) نوشته می‌شود.
# این توابع دور اسم چند نشانه‌ی نامرئی می‌گذارند و wrapper پایین (روی ExtBot) قبل از ارسال به تلگرام
# آن‌ها را به entity از نوع text_mention تبدیل می‌کند: اسم آبی می‌شود و با لمس آن، پروفایل
# تلگرامی همان کاربر باز می‌شود. متن دکمه‌ها و alert ها همیشه ساده (بدون لینک) می‌مانند.
_M_OPEN = '\u2063'
_M_SEP = '\u2064'
_M_CLOSE = '\u2063'
_MENTION_RE = re.compile('\u2063(-?\\d+)\u2064(.*?)\u2063', re.S)
_MAX_ENTITIES = 100

def _u16len(s):
    return len(s.encode('utf-16-le')) // 2

def _clean_mention_name(name):
    return str(name).replace(_M_OPEN, '').replace(_M_SEP, '')

def mention_of(user_id, name=None):
    name = _clean_mention_name(name if name not in (None, '') else user_id)
    return f"{_M_OPEN}{int(user_id)}{_M_SEP}{name}{_M_CLOSE}"

def strip_mentions(text):
    """نشانه‌ها را برمی‌دارد و فقط اسم را نگه می‌دارد (برای دکمه‌ها، alert ها و جاهایی که entity ندارند)."""
    if not isinstance(text, str) or _M_OPEN not in text:
        return text
    text = _MENTION_RE.sub(lambda m: m.group(2), text)
    return text.replace(_M_OPEN, '').replace(_M_SEP, '')

def extract_mentions(text):
    """(متن تمیز، لیست entity) را برمی‌گرداند؛ offset ها بر اساس UTF-16 هستند."""
    if not isinstance(text, str) or _M_OPEN not in text:
        return text, None
    out = []; ents = []; pos = 0; off = 0
    for m in _MENTION_RE.finditer(text):
        seg = text[pos:m.start()]
        out.append(seg); off += _u16len(seg)
        name = m.group(2)
        if name and len(ents) < _MAX_ENTITIES:
            ents.append(MessageEntity(type=MessageEntity.TEXT_MENTION, offset=off, length=_u16len(name),
                                      user=TgUser(id=int(m.group(1)), first_name=name[:64] or 'user', is_bot=False)))
        out.append(name); off += _u16len(name); pos = m.end()
    out.append(text[pos:])
    clean = ''.join(out).replace(_M_OPEN, '').replace(_M_SEP, '')
    return clean, (ents or None)

def _wrap_bot_method(name, text_key, ent_key, pos):
    orig = getattr(ExtBot, name)
    async def wrapper(self, *args, **kwargs):
        args = list(args)
        where = None; text = None
        if text_key in kwargs:
            where = 'kw'; text = kwargs[text_key]
        elif pos is not None and len(args) > pos:
            where = 'pos'; text = args[pos]
        if not (isinstance(text, str) and _M_OPEN in text):
            return await orig(self, *args, **kwargs)
        clean, ents = extract_mentions(text)
        if ent_key is None or kwargs.get(ent_key):
            ents = None    # برای alert ها entity معنا ندارد؛ اگر خودمان entity داده باشیم دست نمی‌زنیم
        def call(t, e):
            a = list(args); k = dict(kwargs)
            if where == 'kw': k[text_key] = t
            else: a[pos] = t
            if e: k[ent_key] = e
            return orig(self, *a, **k)
        if ents:
            try:
                return await call(clean, ents)
            except BadRequest as e:
                # مثلاً کاربری که تلگرام نمی‌شناسد؛ پیام باید حتماً برود، حتی بدون لینک.
                logger.warning('text_mention rejected (%s); retrying without entities', e)
        return await call(clean, None)
    wrapper.__name__ = getattr(orig, '__name__', name)
    setattr(ExtBot, name, wrapper)

def install_mention_support():
    if getattr(ExtBot, '_fox_mentions_installed', False):
        return
    _wrap_bot_method('send_message', 'text', 'entities', 1)
    _wrap_bot_method('edit_message_text', 'text', 'entities', 0)
    _wrap_bot_method('send_photo', 'caption', 'caption_entities', 2)
    _wrap_bot_method('send_document', 'caption', 'caption_entities', 2)
    _wrap_bot_method('edit_message_caption', 'caption', 'caption_entities', 3)
    _wrap_bot_method('answer_callback_query', 'text', None, 1)
    ExtBot._fox_mentions_installed = True

install_mention_support()

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
        f"@{new_user.username}" if new_user.username else mention_of(new_user.telegram_id, new_user.first_name or "کاربر ناشناس")
    )
    referrer_display = (
        f"@{referrer.username}" if referrer.username else mention_of(referrer.telegram_id, referrer.first_name or "کاربر ناشناس")
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
            f"@{referred.username}" if referred and referred.username else (mention_of(referred.telegram_id, referred.first_name) if referred else "کاربر ناشناس")
        )
        referrer_display = (
            f"@{referrer.username}" if referrer and referrer.username else (mention_of(referrer.telegram_id, referrer.first_name) if referrer else "کاربر ناشناس")
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
            f"👤 آمار {mention_of(user.telegram_id, user.first_name or 'کاربر')}\n\n"
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

def profile_buttons(ids, names_by_id=None):
    names_by_id = names_by_id or {}
    rows=[]
    for uid in ids:
        rows.append([InlineKeyboardButton(f"👤 {strip_mentions(names_by_id.get(uid, str(uid)))}", url=f"tg://user?id={uid}")])
    return rows

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
    kb=rps_keyboard(tid); kb.inline_keyboard.extend(profile_buttons(ids,names_by_id)); return text,kb

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
          f"\n\n▶️ نوبت: {names_by_id.get(turn_id,str(turn_id))} ({turn_symbol})\n⏱ زمان باقی‌مانده نوبت: {ruby_turn_remaining(state)} ثانیه")
    kb=xo_keyboard(tid,state['board']); kb.inline_keyboard.extend(profile_buttons(ids,names_by_id)); return text,kb

def ruby_turn_remaining(state):
    raw=state.get('turn_started_at')
    if not raw: return 60
    try:
        started=datetime.fromisoformat(raw)
        if started.tzinfo is None: started=started.replace(tzinfo=timezone.utc)
        return max(0,int(60-(now_utc()-started).total_seconds()))
    except Exception: return 60

async def ruby_simple_turn_timeout(context):
    tid=int(context.job.data['tid']); token=context.job.data.get('token')
    session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active' or t.game_type not in ('xo','cz_rabbit'): return
        state=json.loads(t.state or '{}')
        if token and state.get('turn_token')!=token: return
        if ruby_turn_remaining(state)>0:
            context.job_queue.run_once(ruby_simple_turn_timeout,ruby_turn_remaining(state),data={'tid':tid,'token':state.get('turn_token')}); return
        ids=[int(x) for x in (t.players or '').split(',') if x]; current=state.get('turn')
        if current not in ids: return
        winner=[x for x in ids if x!=current][0]
        t.status='finished'; pot=t.pot or 0
        if pot:
            u=session.get(User,winner)
            if u: u.fox_points=(u.fox_points or 0)+pot
        state['turn_token']=None; t.state=json.dumps(state); session.commit()
        players=[session.get(User,i) for i in ids]; names={u.telegram_id:user_mention(u) for u in players if u}
        chat_id=t.chat_id; message_id=t.message_id; name=RUBY_GAME_CONFIG[t.game_type][0]
    finally: session.close()
    text=f"🕹 {name}\n\n⏰ نوبت {names.get(current,str(current))} تمام شد و در ۶۰ ثانیه حرکت نکرد.\n🏆 {names.get(winner,str(winner))} برنده شد!"+(f"\n💰 جایزه: {pot:,} روب‌پوینت" if pot else '')
    try: await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=None)
    except Exception: pass

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
            f"▶️ نوبت: {names_by_id.get(turn_id,str(turn_id))}\n⏱ زمان باقی‌مانده نوبت: {ruby_turn_remaining(state)} ثانیه"
        )
    kb=rabbit_keyboard(tid,state); kb.inline_keyboard.extend(profile_buttons(ids,names_by_id)); return text,kb


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
    kb=pairs_keyboard(tid,state); kb.inline_keyboard.extend(profile_buttons(ids,names_by_id)); return text,kb

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
        names={u.telegram_id:user_mention(u) for u in players if u}
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
        names={u.telegram_id:user_mention(u) for u in players if u}
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
        names={u.telegram_id:user_mention(u) for u in players if u}
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
                extra=f"🎯 {deck[a]} جفت شد! +1 جفت برای {user_mention(session.get(User,uid))}"
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
        names={u.telegram_id:user_mention(u) for u in players if u}
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
        ),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت",callback_data=f"rubysetup:back:{owner_id}")]])
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

async def ruby_setup_back(update,context):
    q=update.callback_query
    try: owner=int(q.data.split(':')[2])
    except Exception: return
    if q.from_user.id!=owner:
        await q.answer('⛔ این پنل برای کاربر دیگری است.',show_alert=True); return
    setup=context.user_data.pop('ruby_setup',{})
    key=setup.get('key','')
    await q.answer()
    if key.startswith('cz_'):
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('🎰 گردونه شانس',callback_data=f'rg:cz_wheel:{owner}')],[InlineKeyboardButton('🎲 تاس',callback_data=f'rg:cz_dice:{owner}')],[InlineKeyboardButton('🐇 خرگوش خور',callback_data=f'rg:cz_rabbit:{owner}')],[InlineKeyboardButton('🃏 بازی دوتایی‌ها',callback_data=f'rg:cz_pairs:{owner}')]])
        text='🃏 کازینو روبی🦊\n\n❗️ قمار مورد نظر را انتخاب کن:'
    else:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('🧩 بازی روبی دوز XO',callback_data=f'rg:xo:{owner}')],[InlineKeyboardButton('🔫 بازی روبی سنگ کاغذ قیچی',callback_data=f'rg:rps:{owner}')],[InlineKeyboardButton('🎯 بازی روبی دارت',callback_data=f'rg:darts:{owner}')],[InlineKeyboardButton('🏀 بازی روبی بسکتبال',callback_data=f'rg:basketball:{owner}')],[InlineKeyboardButton('🎳 بازی روبی بولینگ',callback_data=f'rg:bowling:{owner}')]])
        text='🕹 بازی‌های روبی🦊\n\n❗️ بازی مورد نظر را انتخاب کن:'
    try: await q.message.edit_text(text,reply_markup=kb)
    except Exception: pass

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
        creator_name=user_mention(user)
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
                t.state=json.dumps({"phase":"plant","paws":{},"revealed":[],"turn_started_at":now_utc().isoformat(),"turn_token":f"{t.id}-{ids[0]}-{int(now_utc().timestamp()*1000)}"})
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
        creator_name = user_mention(user)
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
                t.state=json.dumps({"board":[""]*9,"turn":ids[0],"turn_started_at":now_utc().isoformat(),"turn_token":f"{t.id}-{ids[0]}-{int(now_utc().timestamp()*1000)}","symbols":{str(ids[0]):"X",str(ids[1]):"O"}})
            elif game_type=='cz_rabbit':
                t.state=json.dumps({"phase":"plant","paws":{},"revealed":[],"turn_started_at":now_utc().isoformat(),"turn_token":f"{t.id}-{ids[0]}-{int(now_utc().timestamp()*1000)}"})
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
        names_by_id={u.telegram_id:user_mention(u) for u in players if u}
        if game_type in RUBY_GAME_EMOJI:
            emoji=RUBY_GAME_EMOJI.get(game_type)
            move_line = f"\n\nنوبت پرتابه! روی همین پیام ریپلای کن و ایموجی {emoji} رو بفرست تا خودت پرتاب کنی."
            if game_type=='cz_dice':
                bets=json.loads(state_raw or '{}').get('bets',{})
                player_lines='\n'.join(f"{i+1}️⃣ بازیکن : {user_mention(u)} — {DICE_BET_LABELS.get(bets.get(str(u.telegram_id)),'?')} — ⏳ در انتظار پرتاب" for i,u in enumerate(players))
            else:
                player_lines='\n'.join(f"{i+1}️⃣ بازیکن : {user_mention(u)} — ⏳ در انتظار پرتاب" for i,u in enumerate(players))
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
            if context.job_queue:
                context.job_queue.run_once(ruby_simple_turn_timeout,ruby_turn_remaining(state),data={'tid':tid_,'token':state.get('turn_token')})
        elif game_type=='cz_rabbit':
            state=json.loads(state_raw or '{}')
            text,kb=render_rabbit_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
            if context.job_queue and state.get('phase')=='hunt':
                context.job_queue.run_once(ruby_simple_turn_timeout,ruby_turn_remaining(state),data={'tid':tid_,'token':state.get('turn_token')})
        elif game_type=='cz_pairs':
            state=json.loads(state_raw or '{}')
            text,kb=render_pairs_panel(tid_,name,pot_line,ids,names_by_id,state)
            await q.message.edit_text(text,reply_markup=kb)
            if context.job_queue:
                token=state.get('turn_token')
                context.job_queue.run_once(pairs_turn_timeout,PAIRS_TURN_SECONDS,data={'tid':tid_,'token':token})
                context.job_queue.run_once(_pairs_refresh,1,data={'tid':tid_,'token':token})
    else:
        await q.message.edit_text(f"🕹 {name}\n\n"+'\n'.join(f"{i+1}️⃣ بازیکن : {user_mention(u) if u else '…'}" for i,u in enumerate(players))+"\n\n⏳ منتظر بازیکن بعدی…",reply_markup=ruby_table_keyboard(tid))

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
        names_by_id={u.telegram_id:user_mention(u) for u in players if u}
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
    اگه یکی از بازیکن‌ها تو مهلت 60 ثانیه‌ای انتخابشو نزنه، بازنده‌ی همون راند 
