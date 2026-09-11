import asyncio
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, ChatMemberHandler,
    ContextTypes, MessageHandler, filters
)

from config import (
    ADMIN_IDS, BOT_TOKEN, CLAIM_COOLDOWN_SECONDS, CLAIM_KEYWORD,
    CLAIM_POINTS_MAX, CLAIM_POINTS_MIN, REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL
)
from database import Challenge, FoxHunt, GroupChat, InjuredFox, User, BankAccount, BankTransaction, RubyTable, get_session, init_db
from game_logic import (
    GAME_EMOJIS, GAME_NAMES_FA, HUNT_ITEMS, fox_capacity, fox_level_reward,
    fox_production_interval, fox_production_per_second, fox_rank, fox_upgrade_cost, fox_storage_capacity, get_level_for_points,
    get_unlocked_games, points_to_next_level, points_needed_for_level
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

FOX_UNLOCK_LEVEL = 3
FOX_MAX_LEVEL = 35
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
TRANSFER_MAX = 500_000
WHEEL_COOLDOWN = 24 * 60 * 60
WHEEL_REWARDS = [100, 250, 350, 450, 0, 500, 750, 1000]
WHEEL_LABELS = ['100 روب پوینت', '250 روب پوینت', '350 روب پوینت', '450 روب پوینت', 'پوچ', '500 روب پوینت', '750 روب پوینت', '1000 روب پوینت']
WHEEL_GIF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wheel_gifs')

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
            fox_points=0,
            fox_total_earned=0,
            fox_production_remainder=0.0,
        fox_claim_count=0, hunt_count=0, fox_rescued_count=0,
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
        if user.fox_points is None:
            user.fox_points = 0; changed = True
        if user.fox_total_earned is None:
            user.fox_total_earned = 0; changed = True
        if user.fox_production_remainder is None:
            user.fox_production_remainder = 0.0; changed = True
        if user.fox_claim_count is None: user.fox_claim_count = 0; changed = True
        if user.hunt_count is None: user.hunt_count = 0; changed = True
        if user.fox_rescued_count is None: user.fox_rescued_count = 0; changed = True
        if user.fox_last_hunger_at is None: user.fox_last_hunger_at = now_utc(); changed = True
        if not hasattr(user, 'wheel_last_spin_at'): pass
        if user.wheel_last_reward is None: user.wheel_last_reward = None
        calculated = user_level_from_roobrub(user.fox_claim_count or 0)
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

# ---------- پروفایل و منو ----------

async def start_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        get_or_create_user(session, update.effective_user)
    finally:
        session.close()
    await update.message.reply_text("🦊 خوش اومدی! عضویتت تأیید شد. حالا دستورهای ربات برات آماده‌ست.", **reply_kwargs(update.message))
    command_messages = [
        ("💰 روب روب / هور هور / عو عو", "هر ۵ دقیقه یک‌بار برای دریافت روب‌پوینت؛ از لول ۱ فعال است."),
        ("🏹 شکار", "از لول ۲ فعال است؛ هر ۱۵ دقیقه یک شکار و ۱۲۰ ثانیه برای تصمیم‌گیری."),
        ("🦊 روباه / روبی / روباهیو", "از لول ۳ فعال است؛ پنل روباه، تولید روب‌پوینت، ارتقا و تغییر نام."),
        ("🎮 بازی روبی", "از لول ۳ فعال است؛ منوی بازی‌های روبی و ساخت میز بازی."),
        ("🏦 بانک / بانک روبی", "از لول ۴ فعال است؛ افتتاح حساب و مدیریت بانک."),
        ("👤 روبام / روباش", "پروفایل روبی خودت یا کاربری که روی پیامش ریپلای کرده‌ای."),
        ("🏆 لیدر برد", "رتبه‌بندی ۱۰۰ نفر برتر در بخش‌های روب‌پوینت، روباه زخمی، شکار و روب روب."),
        ("🎡 گردونه / چرخ شانس", "روزی یک‌بار؛ جایزه به‌صورت تصادفی انتخاب می‌شود."),
    ]
    for title, desc in command_messages:
        await update.message.reply_text(f"{title}\n┘─ {desc}")


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
        if user.level<3:
            await update.message.reply_text("🔒 پیوستن و ساخت بازی روبی از لول 3 باز می‌شود.",**reply_kwargs(update.message)); return
    finally: session.close()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 بازی روبی دوز XO",callback_data="rg:xo" )],
        [InlineKeyboardButton("🔫 بازی روبی سنگ کاغذ قیچی",callback_data="rg:rps")],
        [InlineKeyboardButton("🎯 بازی روبی دارت",callback_data="rg:darts")],
        [InlineKeyboardButton("🏀 بازی روبی بسکتبال",callback_data="rg:basketball")],
        [InlineKeyboardButton("🎳 بازی روبی بولینگ",callback_data="rg:bowling")],
    ])
    await update.message.reply_text("🕹 بازی های روبی 🦊\n\n❗️ لطفا بازی مورد نظر را انتخاب کنید ⬇️\n\n🧩 بازی روبی دوز XO\n┘─ محدودیت بازیکن : 2 پیشی\n\n🔫 بازی روبی سنگ کاغذ قیچی\n┘─ محدودیت بازیکن : 2 پیشی\n\n🎯 بازی روبی دارت\n┘─ محدودیت بازیکن : 2 - 4 پیشی\n\n🏀 بازی روبی بسکتبال\n┘─ محدودیت بازیکن : 2 - 3 پیشی\n\n🎳 بازی روبی بولینگ\n┘─ محدودیت بازیکن : 2 - 4 پیشی",reply_markup=kb,**reply_kwargs(update.message))

async def ruby_game_select(update,context):
    q=update.callback_query
    if not await require_membership(update,context): return
    names={"xo":"🧩 روبی دوز XO","rps":"🔫 روبی سنگ کاغذ قیچی","darts":"🎯 روبی دارت","basketball":"🏀 روبی بسکتبال","bowling":"🎳 روبی بولینگ"}
    key=q.data.split(":")[1]
    await q.answer()
    await q.message.reply_text(f"{names.get(key,'🎮 بازی روبی')} انتخاب شد.\n\n⚠️ این نسخه بازی‌ها را بدون شرط‌بندی و پرداخت مبلغ اجرا می‌کند. برای شروع بازی، روی پیام حریف ریپلای کن و دعوت بازی را بفرست.")

RUBY_GAME_CONFIG={
    "xo":("🧩 بازی روبی دوز XO",2),"rps":("🔫 بازی روبی سنگ کاغذ قیچی",2),
    "darts":("🎯 بازی روبی دارت",4),"basketball":("🏀 بازی روبی بسکتبال",3),"bowling":("🎳 بازی روبی بولینگ",4)
}

def ruby_table_keyboard(table_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 شرکت کردن در بازی",callback_data=f"rjoin:{table_id}")]])

async def ruby_game_select(update,context):
    q=update.callback_query
    if not await require_membership(update,context): return
    key=q.data.split(":")[1]; name,maxp=RUBY_GAME_CONFIG[key]
    await q.answer()
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛠 ساخت میز بازی",callback_data=f"rcreate:{key}")]])
    await q.message.reply_text(f"🕹 {name}\n\n❗️ لطفا میز بازی را بچینید\n\n💰 مبلغ ورودی : رایگان ✅",reply_markup=kb)

async def ruby_create_table(update,context):
    q=update.callback_query; key=q.data.split(":")[1]
    if not await require_membership(update,context): return
    session=get_session()
    try:
        user=get_or_create_user(session,q.from_user); name,maxp=RUBY_GAME_CONFIG[key]
        table=RubyTable(chat_id=q.message.chat_id,game_type=key,creator_id=user.telegram_id,max_players=maxp,status='open',players=str(user.telegram_id),created_at=now_utc())
        session.add(table); session.commit(); tid=table.id
    finally: session.close()
    await q.answer("میز ساخته شد!")
    await q.message.edit_text(f"🕹 {name}\n\n🏆 بازی رایگان روبی\n\n1️⃣ بازیکن : {user_display_name(user)}\n" + "\n".join(f"{i}️⃣ بازیکن : …" for i in range(2,maxp+1)) + "\n\n⏳ این میز بازی فقط 60 ثانیه اعتبار دارد…",reply_markup=ruby_table_keyboard(tid))
    context.job_queue.run_once(expire_ruby_table,60,data=tid) if context.job_queue else None

async def expire_ruby_table(context):
    tid=int(context.job.data); session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if t and t.status=='open':
            t.status='expired'; session.commit()
            chat_id=t.chat_id
        else:
            return
    finally:
        session.close()
    try:
        await context.bot.send_message(chat_id=chat_id,text="⏰ مهلت ساخت میز بازی روبی تمام شد و میز بسته شد.")
    except Exception:
        pass

async def ruby_join_table(update,context):
    q=update.callback_query; tid=int(q.data.split(":")[1]); session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='open' or (now_utc()-aware(t.created_at)).total_seconds()>60:
            if t: t.status='expired'; session.commit()
            await q.answer("⏰ این میز دیگر فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        if q.from_user.id in ids: await q.answer("قبلاً وارد شده‌ای.",show_alert=True); return
        if len(ids)>=t.max_players: await q.answer("میز پر شده است.",show_alert=True); return
        get_or_create_user(session,q.from_user); ids.append(q.from_user.id); t.players=','.join(map(str,ids))
        if len(ids)>=t.max_players: t.status='active'
        session.commit(); players=[session.get(User,i) for i in ids]; name=RUBY_GAME_CONFIG[t.game_type][0]
    finally: session.close()
    await q.answer("🎮 وارد بازی شدی!")
    if len(ids)>=t.max_players:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ انجام حرکت",callback_data=f"rmove:{tid}")]])
        await q.message.edit_text(f"🕹 {name}\n\n🎮 بازی شروع شد!\n\n"+'\n'.join(f"{i+1}️⃣ بازیکن : {user_display_name(u)}" for i,u in enumerate(players)),reply_markup=kb)
    else:
        await q.message.edit_text(f"🕹 {name}\n\n"+'\n'.join(f"{i+1}️⃣ بازیکن : {user_display_name(u) if u else '…'}" for i,u in enumerate(players))+"\n\n⏳ منتظر بازیکن بعدی…",reply_markup=ruby_table_keyboard(tid))

async def ruby_move(update,context):
    q=update.callback_query; tid=int(q.data.split(":")[1]); session=get_session()
    try:
        t=session.get(RubyTable,tid)
        if not t or t.status!='active': await q.answer("بازی فعال نیست.",show_alert=True); return
        ids=[int(x) for x in (t.players or '').split(',') if x]
        if q.from_user.id not in ids: await q.answer("تو بازیکن این میز نیستی.",show_alert=True); return
        if t.game_type=='darts': emoji='🎯'
        elif t.game_type=='basketball': emoji='🏀'
        elif t.game_type=='bowling': emoji='🎳'
        else: emoji=None
    finally: session.close()
    if emoji:
        await q.answer(); msg=await context.bot.send_dice(chat_id=t.chat_id,emoji=emoji); value=msg.dice.value
        await context.bot.send_message(chat_id=t.chat_id,text=f"🎮 {user_display_name(q.from_user)} عدد {value} آورد.")
    else:
        await q.answer("برای این بازی، حرکت مخصوص آن در نسخه بعدی تکمیل می‌شود.",show_alert=True)

async def game_command(update, context):
    await games_command(update, context)

# ---------- گردونه روزانه روبی ----------

async def wheel_command(update, context):
    if not await require_membership(update, context):
        return
    session = get_session()
    try:
        user = get_or_create_user(session, update.effective_user)
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

        selected = random.randrange(len(WHEEL_REWARDS))
        reward = WHEEL_REWARDS[selected]
        user.wheel_last_spin_at = now_utc()
        user.wheel_last_reward = reward
        if reward > 0:
            user.fox_points = int(user.fox_points or 0) + reward
        session.commit()
        gif_path = os.path.join(WHEEL_GIF_DIR, f"wheel_{selected}.gif")
    except Exception:
        session.rollback()
        logger.exception("daily wheel failed")
        await update.message.reply_text("❌ گردونه فعلاً با مشکل روبه‌رو شد؛ دوباره تلاش کن.", **reply_kwargs(update.message))
        return
    finally:
        session.close()

    if not os.path.exists(gif_path):
        await update.message.reply_text("❌ فایل گردونه پیدا نشد.", **reply_kwargs(update.message))
        return

    spin_caption = "🎡 گردونه روبی 🦊\n\nدر حال چرخش..."
    try:
        with open(gif_path, 'rb') as f:
            sent = await update.message.reply_animation(
                animation=InputFile(f),
                caption=spin_caption,
                **reply_kwargs(update.message)
            )
        await asyncio.sleep(4.15)
        reward_text = "پوچ 😢" if reward == 0 else f"+{reward:,} روب پوینت 🪙"
        final_caption = (
            "🎡 گردونه روبی 🦊\n\n"
            "🎉 گردونه متوقف شد!\n"
            f"🏆 برنده شدی: {reward_text}\n\n"
            "⏱ گردونه بعدی: 24 ساعت دیگر"
        )
        try:
            await context.bot.edit_message_caption(
                chat_id=sent.chat_id,
                message_id=sent.message_id,
                caption=final_caption
            )
        except Exception:
            # اگر تلگرام ویرایش کپشن انیمیشن را نپذیرفت، نتیجه حتماً به‌صورت پیام جداگانه ارسال شود.
            await context.bot.send_message(
                chat_id=sent.chat_id,
                text=final_caption,
                reply_to_message_id=sent.message_id
            )
    except Exception:
        logger.exception("wheel animation send failed")
        await update.message.reply_text("❌ ارسال گردونه انجام نشد.", **reply_kwargs(update.message))


# ---------- روباه ----------

def fox_keyboard(user_id, user_level, fox_level=None):
    rows=[[InlineKeyboardButton("🧲 برداشت روب پوینت ها",callback_data=f"fox:collect:{user_id}")]]
    if fox_level is None or int(fox_level)<FOX_MAX_LEVEL:
        rows.append([InlineKeyboardButton("⭐ ارتقا مقام",callback_data=f"fox:upgrade:{user_id}")])
    rows.append([InlineKeyboardButton("✏️ تغییر اسم روباه",callback_data=f"fox:rename:{user_id}")])
    return InlineKeyboardMarkup(rows)


def fox_profile_text(user):
    lvl=max(1,min(FOX_MAX_LEVEL,user.fox_level or 1)); cap=fox_capacity(lvl); rate=fox_production_per_second(lvl)
    interval = fox_production_interval(lvl)
    lines=[
        f"🦊 {user.fox_name or 'مکار'}",
        "",
        f"❤️ شکم روباه: {user.fox_belly}/{cap}",
        "",
        f"🏅 مقام: {fox_rank(lvl)}",
        f"⭐ لول روباه: {lvl}/{FOX_MAX_LEVEL}",
        "",
        f"🪙 روب پوینت های تولید شده: {int(user.fox_points):,}",
        f"⚡ تولید: هر {interval:g} ثانیه 1 روب‌پوینت",
        f"📦 ظرفیت ذخیره روب‌پوینت: {fox_storage_capacity(lvl):,}",
    ]
    if (user.fox_belly or 0) < 2: lines.append("🦊 من دیگه کار نمی‌کنم 🦊😡 شکمم حداقل 2 غذا می‌خواد.")
    lines.append(f"💰 هزینه ارتقا: {fox_upgrade_cost(lvl):,} روب پوینت" if lvl<FOX_MAX_LEVEL else "🏆 روباه به آخرین سطح رسیده است.")
    return "\n".join(lines)


def update_fox_production(user):
    """تولید تجمعی؛ روباه با حداقل 2 غذا کار می‌کند و هر 10 دقیقه یک غذا مصرف می‌کند."""
    now = now_utc()
    if user.fox_last_production_at is None:
        user.fox_last_production_at = now
    if user.fox_last_hunger_at is None:
        user.fox_last_hunger_at = now
    hunger_elapsed = max(0.0, (now - aware(user.fox_last_hunger_at)).total_seconds())
    if hunger_elapsed >= 600:
        meals = int(hunger_elapsed // 600)
        user.fox_belly = max(0, (user.fox_belly or 0) - meals)
        user.fox_last_hunger_at = now - timedelta(seconds=hunger_elapsed % 600)
    elapsed = max(0.0, (now - aware(user.fox_last_production_at)).total_seconds())
    user.fox_last_production_at = now
    if (user.fox_belly or 0) < 2:
        return 0.0
    # بخش اعشاری تولید را نگه می‌داریم تا هیچ روب‌پوینتی به‌خاطر گرد کردن از بین نرود.
    total = float(user.fox_production_remainder or 0.0) + elapsed * fox_production_per_second(user.fox_level)
    whole = int(total)
    user.fox_production_remainder = total - whole
    return float(whole)

def settle_fox_production(user):
    """محاسبه تولید معوق روباه و ذخیره آن تا سقف ظرفیت."""
    produced = update_fox_production(user)
    if produced <= 0:
        return 0
    cap = fox_storage_capacity(user.fox_level)
    current = int(user.fox_points or 0)
    room = max(0, cap - current)
    add = min(room, int(produced))
    if add > 0:
        user.fox_points = current + add
        user.fox_total_earned = int(user.fox_total_earned or 0) + add
    return add

def next_fox_point_seconds(user):
    if (user.fox_belly or 0) < 2:
        return 0
    rate = fox_production_per_second(user.fox_level)
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
        settle_fox_production(user);session.commit();text=fox_profile_text(user);markup=fox_keyboard(user.telegram_id,user.level,user.fox_level)
    finally:session.close()
    try:await bot.edit_message_text(text=text,chat_id=chat_id,message_id=message_id,reply_markup=markup)
    except Exception as e:logger.debug("restore fox panel: %s",e)


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
        owner_level=user.level; owner_fox_level=user.fox_level
    finally:
        session.close()
    await update.message.reply_text(text, reply_markup=fox_keyboard(update.effective_user.id, owner_level, owner_fox_level), **reply_kwargs(update.message))


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
            user.fox_points = 0
            session.commit()
            nxt = next_fox_point_seconds(user)
            next_text = f"⏱ روب‌پوینت بعدی حدود {format_duration(nxt)} دیگر تولید می‌شود." if nxt else "⏸ تولید متوقف است تا شکم حداقل 2 غذا داشته باشد."
            await q.answer("برداشت انجام شد! 💰")
            await q.message.edit_text(fox_profile_text(user) + f"\n\n💰 {amount:,} روب پوینت برداشت شد.\n{next_text}")
            asyncio.create_task(restore_fox_panel(context.bot,q.message.chat_id,q.message.message_id,user.telegram_id))
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
                    # با هر ارتقا یک جای غذا به ظرفیت شکم اضافه می‌شود؛ غذای فعلی حفظ می‌شود.
                    user.fox_belly = min(user.fox_belly, fox_capacity(user.fox_level))
                    user.fox_last_production_at = now_utc()
                    session.commit()
                    await q.answer(f"🦊 روباه رفت لول {user.fox_level}!", show_alert=True)
                    await q.message.edit_text(fox_profile_text(user) + f"\n\n🎉 روباه به لول {user.fox_level} رسید!\n🏅 مقام جدید: {fox_rank(user.fox_level)}")
                    asyncio.create_task(restore_fox_panel(context.bot,q.message.chat_id,q.message.message_id,user.telegram_id))
                    return
        elif action == "hunt":
            await handle_hunt_request(q, session, user, context)
            return
        elif action == "fridge":
            if user.level < 7:
                await q.answer("🧊 یخچال روبی در سطح 7 باز می‌شود.", show_alert=True)
                return
            items = session.query(FoxHunt).filter(FoxHunt.user_id == user.telegram_id, FoxHunt.status == "fridge").order_by(FoxHunt.id.desc()).limit(20).all()
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
    hunt = FoxHunt(user_id=user.telegram_id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending")
    user.last_hunt_at = now_utc()
    user.hunt_count=(user.hunt_count or 0)+1
    session.add(hunt)
    session.commit()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.telegram_id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.telegram_id}")],
        [InlineKeyboardButton("🧊 انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.telegram_id}")],
    ])
    await q.answer()
    emoji_msg = await q.message.reply_text(emoji)
    await asyncio.sleep(3)
    await emoji_msg.reply_text(
        f"🎯 شما {item['name']} را شکار کردید!\n🍖 ارزش غذایی: {item['nutrition']}\n\nچه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
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
        hunt = FoxHunt(user_id=user.telegram_id, emoji=emoji, item_name=item["name"], nutrition=item["nutrition"], sell_value=item["sell"], status="pending")
        user.last_hunt_at = now_utc()
        session.add(hunt)
        session.commit()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🦊 دادن به روباه", callback_data=f"hunt:feed:{hunt.id}:{user.telegram_id}"), InlineKeyboardButton("💰 فروختن", callback_data=f"hunt:sell:{hunt.id}:{user.telegram_id}")],
            [InlineKeyboardButton("🧊 انداختن در یخچال روبی", callback_data=f"hunt:fridge:{hunt.id}:{user.telegram_id}")],
        ])
        emoji_msg = await update.message.reply_text(emoji, **reply_kwargs(update.message))
        await asyncio.sleep(3)
        await emoji_msg.reply_text(
            f"🎯 شما {item['name']} را شکار کردید!\n🍖 ارزش غذایی: {item['nutrition']}\n\nچه کار خواهید کرد؟\n⏱ 120 ثانیه فرصت تصمیم‌گیری دارید وگرنه شکار می‌پره.",
            reply_markup=kb
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

FOX_CLAIM_ALIASES={"روب روب","هور هور","عو عو","روب روب!","هور هور!","عو عو!"}

async def collect_fox_points(update,context):
    if not await require_membership(update,context):return
    session=get_session()
    try:
        user=get_or_create_user(session,update.effective_user)
        if user.level<1:
            await update.message.reply_text("🔒 دریافت روب‌پوینت از سطح 1 باز می‌شود.",**reply_kwargs(update.message));return
        left=seconds_left(user.last_fox_claim_at,FOX_CLAIM_COOLDOWN)
        if left:
            await update.message.reply_text(f"⏳ دریافت بعدی روب‌پوینت: {format_duration(left)} دیگر.",**reply_kwargs(update.message));return
        earned=random.randint(CLAIM_POINTS_MIN,CLAIM_POINTS_MAX)
        old_level=user.level
        user.fox_points+=earned;user.fox_total_earned+=earned;user.fox_claim_count=(user.fox_claim_count or 0)+1;user.last_fox_claim_at=now_utc()
        user.level=user_level_from_roobrub(user.fox_claim_count)
        rewards=apply_level_rewards(session,user,old_level,user.level)
        session.commit()
        text=f"🦊 +{earned:,} روب‌پوینت دریافت کردی!\n💰 موجودی روب‌پوینت: {user.fox_points:,}\n🐾 روب روب‌ها: {user.fox_claim_count:,}\n⏱ دریافت بعدی: 5 دقیقه دیگر"
        if user.level>old_level: text += "\n\n"+level_up_message(old_level,user.level,rewards)
        await update.message.reply_text(text,**reply_kwargs(update.message))
    finally:session.close()

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
            if not target or target.user_id==user.telegram_id or amount<=0 or user.fox_points<amount: raise ValueError
            target_user=session.get(User,target.user_id)
            context.user_data['pending_bank_transfer']={'dest':dest,'amount':amount,'target_user_id':target.user_id}
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله',callback_data=f'bankconfirm:yes:{user.telegram_id}'),InlineKeyboardButton('❌ خیر',callback_data=f'bankconfirm:no:{user.telegram_id}')]])
            msg=(f'🦊 کارت به کارت روبی 💳\n\n❓ آیا از انتقال اطمینان دارید؟\n\n💰 مبلغ: {amount:,} روب‌پوینت\n💳 حساب مقصد: {dest}\n👤 گیرنده: {user_display_name(target_user)}')
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
        if user.level < 7:
            await update.message.reply_text("🧊 یخچال روبی در سطح 7 باز می‌شود.", **reply_kwargs(update.message))
            return
        items = session.query(FoxHunt).filter(FoxHunt.user_id == user.telegram_id, FoxHunt.status == "fridge").order_by(FoxHunt.id.desc()).limit(20).all()
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
            reward = random.randint(INJURED_FOX_REWARD_MIN, INJURED_FOX_REWARD_MAX)
            claims = random.randint(1, INJURED_FOX_MAX_CLAIMS)
            user.fox_points += reward
            user.fox_claim_count = (user.fox_claim_count or 0) + claims
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

# ---------- بانک روبی ----------

BANK_OPEN_COST = 5000
BANK_CHANGE_COST = 3000
BANK_INTEREST_RATE = 0.03

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
        account = BankAccount(account_number=number, user_id=user.telegram_id, balance=0, last_interest_at=now_utc())
        session.add(account)
        session.flush()
        session.add(BankTransaction(account_number=number, direction='fee', amount=BANK_OPEN_COST, description='افتتاح شعبه بانک'))
    return account, True

def apply_bank_interest(account, session):
    # سود 3 درصد روزانه، حداکثر یک بار در هر 24 ساعت.
    now = now_utc()
    if not account.last_interest_at:
        account.last_interest_at = now; return 0
    elapsed=(now-aware(account.last_interest_at)).total_seconds()
    if elapsed < 86400 or account.balance <= 0: return 0
    days=int(elapsed//86400)
    gain=int(account.balance*((1+BANK_INTEREST_RATE)**days-1))
    if gain>0:
        account.balance += gain
        session.add(BankTransaction(account_number=account.account_number,direction='interest',amount=gain,description='سود بانکی'))
    account.last_interest_at=now
    return gain

def bank_keyboard(account):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➖ برداشت',callback_data=f'bank:withdraw:{account.user_id}'), InlineKeyboardButton('➕ واریز',callback_data=f'bank:deposit:{account.user_id}')],
        [InlineKeyboardButton('💳 کارت به کارت روبی🦊',callback_data=f'bank:transfer:{account.user_id}'), InlineKeyboardButton('📃 تراکنش‌ها',callback_data=f'bank:transactions:{account.user_id}')],
        [InlineKeyboardButton('➿ تغییر حساب روبی',callback_data=f'bank:change:{account.user_id}')],
    ])

def bank_text(user, account):
    return (f'🦊 بانک روبی 🏦\n\n💳 شماره حساب : {account.account_number}\n👤 به نام : {user_display_name(user)}\n\n💰 موجودی حساب : {account.balance:,} 🪙\n\n🤑 سود بانکی\n┘─ 🛍 درصد سود : 3%\n┘─ 📥 مبلغ واریزی : محاسبه روزانه بر اساس موجودی\n┘─ ⏳ زمان واریز : هر 24 ساعت\n\n❗️ برای مدیریت حساب بانکی از گزینه‌های زیر استفاده کن.')

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
            await q.answer(); await q.message.reply_text(bank_text(user,account)+'\n\n➖ درصد برداشت را انتخاب کن:',reply_markup=kb); return
        if action=='w': return
        if action=='deposit': context.user_data['bank_action']='deposit'; await q.answer(); await q.message.reply_text(bank_text(user,account)+'\n\n➕ مبلغ واریز را در جواب همین پنل بفرست.\nمثال: 50k / 50کا / 50میل / 50م / 50m'); return
        if action=='transfer': context.user_data['bank_action']='transfer'; await q.answer(); await q.message.reply_text('🦊 کارت به کارت روبی 💳\n\n🔺 مبلغ و شماره حساب مقصد را در جواب همین پنل بفرست.\nمثال: 500 123456789000'); return
        if action=='transactions':
            rows=session.query(BankTransaction).filter(BankTransaction.account_number==account.account_number).order_by(BankTransaction.id.desc()).limit(10).all()
            txt='📃 آخرین تراکنش‌ها\n\n' + ('\n'.join(f"{r.created_at:%Y-%m-%d %H:%M} | {('به حساب ' + str(r.counterparty_user_id)) if r.direction in ('card_out','card_transfer_out') else ('از حساب ' + str(r.counterparty_user_id)) if r.counterparty_user_id else r.description or r.direction} | {r.amount:,} 🪙" for r in rows[:3]) if rows else 'تراکنشی ثبت نشده است.')
            await q.answer(); await q.message.reply_text(txt); return
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
        dest=pending['dest']; amount=int(pending['amount']); target=session.get(BankAccount,dest)
        if not user or not account or not target or target.user_id==uid or account.balance<amount:
            await q.answer("❌ موجودی حساب یا حساب مقصد نامعتبر است.",show_alert=True); return
        target_user=session.get(User,target.user_id)
        account.balance-=amount; target.balance+=amount
        session.add(BankTransaction(account_number=account.account_number,counterparty_account=dest,counterparty_user_id=target.user_id,direction='card_out',amount=amount,description='کارت به کارت'))
        session.add(BankTransaction(account_number=dest,counterparty_account=account.account_number,counterparty_user_id=uid,direction='card_in',amount=amount,description='کارت به کارت'))
        session.commit(); context.user_data.pop('pending_bank_transfer',None)
        await q.answer("✅ کارت به کارت انجام شد!")
        await q.message.edit_text(f"✅ {amount:,} روب‌پوینت با موفقیت کارت به کارت شد.\n💳 حساب مقصد: {dest}\n👤 گیرنده: {user_display_name(target_user)}\n🏦 موجودی جدید بانک: {account.balance:,}")
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

def level_up_message(old_level, new_level, rewards):
    parts=[]
    for lvl, reward in rewards:
        parts.append(f"🎉 تبریک! به لول {lvl} صعود کردی!\n\n🔓 قابلیت‌های این سطح:\n{level_capabilities(lvl)}\n\n💝 جایزه: +{reward:,} روب پوینت 🪙")
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

def admin_only(user_id): return user_id in ADMIN_IDS

async def admin_command(update, context):
    if not await require_membership(update, context): return
    if not admin_only(update.effective_user.id): await update.message.reply_text("⛔ دسترسی نداری.", **reply_kwargs(update.message)); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats")],
        [InlineKeyboardButton("👥 تعداد کاربران", callback_data="admin:users")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🦊 افزودن/کسر روب‌پوینت", callback_data="admin:addpoints")],
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
    elif action == "addpoints": context.user_data["admin_action"]="addpoints"; await q.message.reply_text("🦊 فرمت: آیدی عددی کاربر + مقدار روب‌پوینت")
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


async def membership_callback(update, context):
    q=update.callback_query
    if q.data!="check_membership": return
    if await is_member(context.bot,q.from_user.id):
        await q.answer("عضویت تأیید شد! 🎉")
        await q.message.edit_text("✅ عضویتت تأیید شد!\n\n🦊 دستورهای ربات جداگانه برات ارسال می‌شوند.")
        command_messages = [
            ("💰 روب روب / هور هور / عو عو", "هر ۵ دقیقه یک‌بار برای دریافت روب‌پوینت؛ از لول ۱ فعال است."),
            ("🏹 شکار", "از لول ۲ فعال است؛ هر ۱۵ دقیقه یک شکار و ۱۲۰ ثانیه برای تصمیم‌گیری."),
            ("🦊 روباه / روبی / روباهیو", "از لول ۳ فعال است؛ پنل روباه، تولید روب‌پوینت، ارتقا و تغییر نام."),
            ("🎮 بازی روبی", "از لول ۳ فعال است؛ منوی بازی‌های روبی و ساخت میز بازی."),
            ("🏦 بانک / بانک روبی", "از لول ۴ فعال است؛ افتتاح حساب و مدیریت بانک."),
            ("👤 روبام / روباش", "پروفایل روبی خودت یا کاربری که روی پیامش ریپلای کرده‌ای."),
            ("🏆 لیدر برد", "رتبه‌بندی ۱۰۰ نفر برتر در بخش‌های روب‌پوینت، روباه زخمی، شکار و روب روب."),
            ("🎡 گردونه / چرخ شانس", "روزی یک‌بار؛ جایزه به‌صورت تصادفی انتخاب می‌شود."),
        ]
        for title, desc in command_messages:
            await context.bot.send_message(chat_id=q.message.chat_id, text=f"{title}\n┘─ {desc}")
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
        text=(f"╮──「 🦊 پروفایل روبی 🦊 」\n\n┐─ 👤 کاربر : {user_display_name(user)}\n‏┘─ 🪪 آیدی : {user.telegram_id}\n\n"+f"┐─ 💰 روب پوینت ها : {int(user.fox_points):,} 🪙\n┘─ 🎖️ رتبه ({rp:,})\n"+f"┐─ 🐾 روب روب ها : {int(user.fox_claim_count or 0):,}\n┘─ 🎖️ رتبه ({rr:,})\n\n"+f"┐─ 🐈 روباه های زخمی نجات یافته : {int(user.fox_rescued_count or 0):,}\n┘─ 🎖️ رتبه ({rs:,})\n\n"+f"╯─ ⭐️ سطح : {lvl} | {max(0, needed-user_progress):,} / {needed:,} {bar}")
    finally:session.close()
    await update.message.reply_text(text,**reply_kwargs(update.message))
async def leaderboard_command(update,context):
    if not await require_membership(update,context):return
    session=get_session()
    try:
        configs=[('روب پوینت 🦊','fox_points'),('روباه های زخمی 🎃','fox_rescued_count'),('شکار ⚔️','hunt_count'),('روب روب 🐾','fox_claim_count')];blocks=[]
        for title,field in configs:
            users=session.query(User).order_by(getattr(User,field).desc(),User.telegram_id.asc()).limit(100).all();blocks.append('\n'.join([f'╭──「 {title} 」']+[f'{i}. {user_display_name(u)} — {int(getattr(u,field) or 0):,}' for i,u in enumerate(users,1)]))
        text='\n\n'.join(blocks)
    finally:session.close()
    for i in range(0,len(text),3900):await update.message.reply_text(text[i:i+3900],**reply_kwargs(update.message))

async def text_router(update, context):
    if not update.message or not update.message.text: return
    if await handle_bank_text(update, context): return
    if await handle_fox_rename_text(update, context): return
    text=update.message.text.strip()
    if text in FOX_CLAIM_ALIASES:
        await collect_fox_points(update,context); return
    if text in {"روبام","روبام!","روباش","روباش!"}: await roobam_command(update,context); return
    if text in {"گردونه", "چرخ شانس", "🎡 گردونه", "🎡 چرخ شانس"}: await wheel_command(update,context); return
    if text in {"لیدر برد","لیدربرد","leaderboard","Leaderboard"}: await leaderboard_command(update,context); return
    if re.sub(r"\s+", " ", text) in {"روباه", "روباه روباه", "روبی", "روباهیو", "🦊 روباه", "🦊 روبی", "🦊 روباهیو"}:
        await fox_command(update, context); return
    if text in {"شکار", "شکار!", "🏹 شکار"}:
        await hunt_command(update, context); return
    if text in {"یخچال روبی", "🧊 یخچال روبی"}:
        await fridge_command(update, context); return
    if text in {"بانک", "بانک روبی", "🏦 بانک روبی"}:
        await bank_command(update, context); return
    if text in {"بازی روبی", "بازی های روبی", "بازی‌های روبی", "🕹 بازی های روبی"}:
        await ruby_games_command(update, context); return
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
    m = re.fullmatch(r"/(روباه(?:\s+روباه)?|روبی|روباهیو|شکار|یخچال|روبام|روباش|لیدربرد|گردونه|چرخ|بازی(?:\s+روبی)?)(?:@\w+)?", text)
    if m:
        cmd = m.group(1)
        if cmd in {"روباه","روبی","روباهیو"}: await fox_command(update,context)
        elif cmd in {"بازی روبی","بازی"}: await ruby_games_command(update,context)
        elif cmd in {"گردونه","چرخ"}: await wheel_command(update,context)
        elif cmd=="شکار": await hunt_command(update,context)
        elif cmd=="یخچال": await fridge_command(update,context)
        elif cmd in {"روبام","روباش"}: await roobam_command(update,context)
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
    app.add_handler(CommandHandler("roobam",roobam_command))
    app.add_handler(CommandHandler("leaderboard",leaderboard_command))
    app.add_handler(CallbackQueryHandler(membership_callback,pattern=r"^check_membership$"))
    app.add_handler(CallbackQueryHandler(admin_callback,pattern=r"^admin:(stats|users|broadcast|addpoints|setlevel|setfoxpoints)$"))
    app.add_handler(CallbackQueryHandler(accept_challenge,pattern=r"^accept:\d+$"))
    app.add_handler(CallbackQueryHandler(throw_dice,pattern=r"^throw:\d+:[12]$"))
    app.add_handler(CallbackQueryHandler(fox_button,pattern=r"^fox:(collect|upgrade|hunt|fridge|rename):\d+$"))
    app.add_handler(CallbackQueryHandler(hunt_button,pattern=r"^hunt:(feed|sell|fridge):\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_game_select,pattern=r"^rg:(xo|rps|darts|basketball|bowling)$"))
    app.add_handler(CallbackQueryHandler(ruby_create_table,pattern=r"^rcreate:(xo|rps|darts|basketball|bowling)$"))
    app.add_handler(CallbackQueryHandler(ruby_join_table,pattern=r"^rjoin:\d+$"))
    app.add_handler(CallbackQueryHandler(ruby_move,pattern=r"^rmove:\d+$"))
    app.add_handler(CallbackQueryHandler(bank_transfer_confirm,pattern=r"^bankconfirm:(yes|no):\d+$"))
    app.add_handler(CallbackQueryHandler(bank_withdraw_button,pattern=r"^bank:w:\d+:(?:25|50|75|100)$"))
    app.add_handler(CallbackQueryHandler(bank_button,pattern=r"^bank:(?:withdraw|deposit|transfer|transactions|change):\d+$"))
    app.add_handler(CallbackQueryHandler(transfer_button,pattern=r"^transfer:(yes|no):\d+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(injured_fox_button,pattern=r"^injured:rescue:\d+$"))
    # دستورهای فارسی با MessageHandler ثبت می‌شوند؛ CommandHandler آن‌ها را رد می‌کند.
    app.add_handler(MessageHandler(filters.Regex(r"^/(?:روباه|روبی|روباهیو|شکار|یخچال|روبام|روباش|لیدربرد|گردونه|چرخ|بازی(?:\s+روبی)?)(?:@\w+)?$") | filters.Regex(r"^/انتقال(?:@\w+)?(?:\s+روب\s+پوینت)?\s+[0-9,]+$"), persian_slash_router), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=list(ADMIN_IDS)),admin_text),group=0)
    app.add_handler(MessageHandler(filters.Regex(rf"^{re.escape(CLAIM_KEYWORD)}$"),claim_points),group=1)
    app.add_handler(ChatMemberHandler(bot_joined_group, ChatMemberHandler.MY_CHAT_MEMBER), group=-2)
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, register_group_chat), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router),group=2)
    if app.job_queue:
        app.job_queue.run_repeating(post_injured_fox_job, interval=INJURED_FOX_INTERVAL, first=5, name="injured-fox")
    logger.info("Bot started polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
