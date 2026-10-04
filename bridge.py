# -*- coding: utf-8 -*-
"""
وصل شدن دو گپ به هم: «روباهیو وصل شو»

1) کاربر تو گپ A می‌نویسه «روباهیو وصل شو» → پیام «دارم شما رو به اولین گپی که در رو باز کنه وصل می‌کنم»
   با دکمه‌ی «لغو جستجو»؛ به همه‌ی گپ‌های دیگه‌ی ربات پیام دعوت با دکمه‌ی «بله، در رو باز کن» میره.
2) اولین گپی که دکمه رو بزنه به A وصل می‌شه. به هر دو گپ خبر میره: «۳۰ دقیقه فرصت گفت و گو دارید»
   با دکمه‌های «گزارش» (فقط کسایی که توی اون گفت و گو هستن) و «پایان گفت و گو» (فقط ادمین‌های همون گپ).
3) تا وقتی وصلن فقط پیامی از تونل رد می‌شه که روی پیام «اونوریا» (یا پیام «وصل شدید») ریپلای شده باشه.
   قالب: «👤 اسم از گپ فلان» و زیرش متن به صورت نقل‌قول. لینک و یوزرنیم هرگز رد نمی‌شه (به فرستنده اخطار داده می‌شه).
   زیر هر پیام رسیده دکمه‌ی «گزارش» هست و روی پیام فرستنده ربات 🕊 ری‌اکشن می‌زنه (یعنی پیامت رفت اونور).
   گزارش‌ها برای پشتیبانی میره و پشتیبانی می‌تونه کاربر رو از «روباهیو وصل شو» محروم کنه (دیگه پیامش رد نمی‌شه).
4) بعد از ۳۰ دقیقه یا با «پایان گفت و گو» هر دو گپ از هم جدا می‌شن.
"""
import asyncio
import html
import json
import json as _json_mod
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from database import BridgeBan, ChatBridge, ChatBridgeMessage, GroupChat, User, get_session

try:
    from config import ADMIN_IDS
except Exception:  # noqa: BLE001
    ADMIN_IDS = []

logger = logging.getLogger(__name__)

BRIDGE_TALK_SECONDS = 30 * 60        # مدت گفت و گو بعد از وصل شدن
BRIDGE_SEARCH_TTL = 60 * 60          # اگه تا یک ساعت هیچ گپی در رو باز نکرد جستجو تموم می‌شه
BRIDGE_REQUEST_COOLDOWN = 3 * 60     # فاصله‌ی دو درخواست پشت‌سرهم از یک گپ (ضد اسپم)
RETENTION_SECONDS = 7 * 24 * 3600    # لاگ پیام‌ها (برای گزارش) یک هفته نگه داشته می‌شه
REACTION = "🕊"

_TRIGGER_RE = re.compile(r"^\s*روباهیو[\s\u200c]+وصل[\s\u200c]*شو[\s\.\!؟\?]*$")
_CACHE = {}      # chat_id -> {"id", "partner", "ends"}  (فقط گفت و گوهای وصل)
_LOCKS = {}      # bridge_id -> asyncio.Lock  (ترتیب پیام‌ها حفظ بشه)
_last_purge = [0.0]
_BANNED = set()          # user_id های محروم‌شده از «روباهیو وصل شو»
_ban_notice = {}         # user_id -> آخرین زمانی که پیام «محروم هستی» دیده

LINK_WARNING = "⚠️ لینک و یوزرنیم از تونل لونه‌ها رد نمی‌شن"
BANNED_NOTICE = "🚫 شما از «روباهیو وصل شو» محروم شدید و پیام‌هاتون از تونل لونه‌ها رد نمی‌شه."

_TLDS = ("com|net|org|info|biz|edu|gov|io|me|ly|co|xyz|app|link|site|online|top|club|shop|store|dev|ai|gl|gd|to|so|be|im|"
         "sh|ws|vip|live|fun|pro|page|click|work|tv|cc|in|cn|tk|ml|ga|cf|gq|ru|de|uk|us|fr|it|es|nl|tr|ir|ae|pk|iq|sa|"
         "af|az|am|tj|uz|kz|ua|pl|ca|au|jp|kr|br|mx|ar|za|ng|eg|id|my|sg|vn|th|ph|pw|me|st|su|eu|asia|cloud|space|tech|"
         "website|digital|network|world|today|news|blog|bio|ink|one|zip|mov")
_LINK_RE = re.compile(
    r"(?:\b[a-z][a-z0-9+.\-]{1,15}://)"                        # هر scheme://
    r"|(?:\bwww\s*\.)"
    r"|(?:\b(?:t|telegram)\s*\.\s*(?:me|dog)\b)"
    r"|(?:\btg\s*:)"
    r"|(?:\bjoinchat\b)"
    r"|(?:\b[a-z0-9][a-z0-9\-]{0,62}(?:\.[a-z0-9\-]{1,63})*\.(?:" + _TLDS + r")\b)",
    re.I)
_USER_RE = re.compile(r"@\s?[a-z0-9_]{3,}", re.I)
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def _norm(text) -> str:
    t = unicodedata.normalize("NFKC", str(text or "")).replace("。", ".")
    return _INVISIBLE.sub("", t)


def contains_link(text, entities=()) -> bool:
    """لینک، دامنه، یوزرنیم یا منشن (حتی لینکِ مخفی پشت متن) داخل پیام هست؟"""
    for e in entities or ():
        if getattr(e, "type", None) in ("url", "text_link", "mention", "text_mention"):
            return True
    n = _norm(text)
    return bool(_LINK_RE.search(n) or _USER_RE.search(n))


def now_utc():
    return datetime.now(timezone.utc)


def aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def esc(t) -> str:
    return html.escape(str(t or ""), quote=False)



# ---------------------------------------------------------------------------
# عکس بنر (روباه انیمیشنی که به دنیاهای دیگه وصل می‌شه) برای پیام جستجو و دعوت‌نامه
# ---------------------------------------------------------------------------
_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_CANDIDATES = [os.path.join(_ASSETS, n) for n in ("fox_portal.jpg", "fox_portal.jpeg", "fox_portal.png")]
_CANDIDATES += [os.path.join(os.path.dirname(os.path.abspath(__file__)), n)
                for n in ("fox_portal.jpg", "fox_portal.jpeg", "fox_portal.png")]
BANNER_PATH = next((c for c in _CANDIDATES if os.path.exists(c)), None)
_IMG = {"bytes": None, "file_id": None, "origin": ""}


def _banner_source():
    """file_id کش‌شده → فایل assets (اگه هست) → نسخه‌ی داخل کد (bridge_banner.py)."""
    if _IMG["file_id"]:
        return _IMG["file_id"]
    if _IMG["bytes"] is None:
        data, origin = b"", ""
        if BANNER_PATH:
            try:
                with open(BANNER_PATH, "rb") as f:
                    data, origin = f.read(), f"فایل {BANNER_PATH}"
            except Exception as e:  # noqa: BLE001
                logger.warning("bridge banner file unreadable: %r", e)
        if not data:
            try:
                from bridge_banner import BANNER_JPEG
                data, origin = BANNER_JPEG, "نسخه‌ی داخل کد (bridge_banner.py)"
            except Exception as e:  # noqa: BLE001
                logger.warning("bridge banner embedded copy unavailable: %r", e)
        _IMG["bytes"], _IMG["origin"] = data, origin
        logger.warning("bridge banner source: %s (%d bytes)", origin or "هیچ‌کدوم پیدا نشد!", len(data))
    return _IMG["bytes"] or None


async def _send_banner(bot, chat_id, caption, markup=None, reply_to=None):
    """عکس + متن به‌عنوان کپشن. اگه عکس نبود/نرفت، همون متن ساده فرستاده می‌شه."""
    rp = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
    src = _banner_source()
    if src:
        try:
            m = await _safe(bot.send_photo, chat_id=chat_id, photo=src, caption=caption,
                            reply_markup=markup, reply_parameters=rp)
            if m.photo and not _IMG["file_id"]:
                _IMG["file_id"] = m.photo[-1].file_id
            return m
        except Exception as e:  # noqa: BLE001
            if _IMG["file_id"]:
                _IMG["file_id"] = None      # شاید file_id معتبر نبود؛ دفعه‌ی بعد دوباره آپلود می‌شه
            logger.warning("bridge banner photo failed (%s: %s); falling back to text", type(e).__name__, e)
    return await _safe(bot.send_message, chat_id=chat_id, text=caption, reply_markup=markup, reply_parameters=rp)


# ---------------------------------------------------------------------------
# اخطار «فقط برای خودت» (لینک/محرومیت)
# ---------------------------------------------------------------------------
# تلگرام برای ربات‌ها پیامِ «قابل مشاهده فقط برای شما» رو با پارامتر مخصوص می‌ده. اسم دقیق اون پارامتر
# رو اینجا حدس نمی‌زنیم؛ اگه از مستندات تلگرام پیداش کردی، توی Railway متغیر محیطی زیر رو ست کن (JSON):
#   BRIDGE_PRIVATE_NOTICE_KWARGS={"اسم_پارامتر": "{user_id}"}
# مقدار "{user_id}" با آیدی کاربرِ خاطی جایگزین می‌شه و با api_kwargs به sendMessage اضافه می‌شه.
# اگه ست نشده باشه، اخطار به‌صورت ریپلای میاد و بعد از چند ثانیه خودش پاک می‌شه.
NOTICE_SECONDS = 8
_PRIVATE_KW = {}
try:
    _PRIVATE_KW = _json_mod.loads(os.environ.get("BRIDGE_PRIVATE_NOTICE_KWARGS", "") or "{}")
    if not isinstance(_PRIVATE_KW, dict):
        _PRIVATE_KW = {}
except Exception:  # noqa: BLE001
    _PRIVATE_KW = {}
_bg_tasks = set()


async def _delete_later(bot, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def wait_kb(bid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("لغو جستجو", callback_data=f"brg:cancel:{bid}")]])


def invite_kb(bid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("بله، در رو باز کن 🚪", callback_data=f"brg:ok:{bid}")]])


def connected_kb(bid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚨 گزارش", callback_data=f"brg:rep:{bid}"),
        InlineKeyboardButton("🔚 پایان گفت و گو", callback_data=f"brg:end:{bid}"),
    ]])


def report_only_kb(bid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚨 گزارش", callback_data=f"brg:rep:{bid}")]])


def msg_kb(mid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚨 گزارش", callback_data=f"brg:rm:{mid}")]])


INVITE_TEXT = ("یک لونه روباه 🦊🏠 می‌خواهد با شما گفت و گو کند.\n\n"
               "آیا مایل هستید آن‌ها را بپذیرید؟")
WAIT_TEXT = ("🦊🚪 دارم شما رو به اولین گپی که در رو باز کنه وصل می‌کنم.\n\n"
             "منتظر بمانید ⏳")


# ---------------------------------------------------------------------------
# ابزارها
# ---------------------------------------------------------------------------
def safe_title(title) -> str:
    """اسم گپ برای نمایش توی تونل: لینک/یوزرنیم حذف می‌شه."""
    t = _norm(title or "")
    t = re.sub(r"(?:[a-z][a-z0-9+.\-]{1,15}://|www\.|t\.me/|telegram\.me/)\S+", "", t, flags=re.I)
    t = re.sub(r"@\s?\w+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:40] or "یک لونه"


def clean_text_name(n) -> str:
    """اسم خام → فقط اسم؛ هر چیزی شبیه لینک، @یوزرنیم یا شماره حذف می‌شه."""
    n = str(n or "").replace("\u2063", "").replace("\u2064", "")
    n = re.sub(r"(?:https?://|www\.|t\.me/)\S+", "", n, flags=re.I)
    n = re.sub(r"@\w+", "", n)
    n = re.sub(r"\+?\d[\d\s\-()]{6,}\d", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n[:40] or "کاربر"


def clean_name(user) -> str:
    """فقط اسم حساب کاربر (بدون لینک/یوزرنیم/شماره)."""
    return clean_text_name(getattr(user, "full_name", None) or user.first_name or "")


async def _safe(fn, *a, **kw):
    """یک بار تلاش مجدد برای RetryAfter؛ بقیه‌ی خطاها به بالا می‌رن."""
    try:
        return await fn(*a, **kw)
    except RetryAfter as e:
        await asyncio.sleep(min(float(e.retry_after), 5.0))
        return await fn(*a, **kw)


async def _is_chat_admin(bot, chat_id, user_id) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:  # noqa: BLE001
        return False


async def _is_chat_member(bot, chat_id, user_id) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status not in ("left", "kicked")
    except Exception:  # noqa: BLE001
        return True    # نتونستیم چک کنیم؛ خود دکمه توی همون گپ زده شده


def _active_for_chat(session, chat_id):
    return (session.query(ChatBridge)
            .filter(ChatBridge.status.in_(("searching", "connected")))
            .filter((ChatBridge.chat_id == chat_id) | (ChatBridge.partner_chat_id == chat_id))
            .order_by(ChatBridge.id.desc()).first())


def _load_cache(session=None):
    own = session is None
    session = session or get_session()
    try:
        rows = session.query(ChatBridge).filter(ChatBridge.status == "connected").all()
        cache = {}
        for r in rows:
            ends = aware(r.ends_at).timestamp() if r.ends_at else 0
            cache[r.chat_id] = {"id": r.id, "partner": r.partner_chat_id, "ends": ends}
            cache[r.partner_chat_id] = {"id": r.id, "partner": r.chat_id, "ends": ends}
        _CACHE.clear()
        _CACHE.update(cache)
    finally:
        if own:
            session.close()


def _json(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _load_bans():
    s = get_session()
    try:
        ids = {r[0] for r in s.query(BridgeBan.user_id).all()}
    finally:
        s.close()
    _BANNED.clear()
    _BANNED.update(ids)


def _set_ban(uid: int, banned: bool, by: int):
    s = get_session()
    try:
        row = s.get(BridgeBan, uid)
        if banned and not row:
            s.add(BridgeBan(user_id=uid, banned_by=by))
        elif not banned and row:
            s.delete(row)
        s.commit()
    finally:
        s.close()
    if banned:
        _BANNED.add(uid)
    else:
        _BANNED.discard(uid)


async def _edit(bot, chat_id, message_id, text, markup=None, photo=True):
    """ویرایش پیام. پیام‌های جستجو/دعوت عکس‌دارن (کپشن)، پیام‌های دیگه متنی‌ان؛ هر دو حالت امتحان می‌شه."""
    chat_id, message_id = int(chat_id), int(message_id)
    order = ("caption", "text") if photo else ("text", "caption")
    for kind in order:
        try:
            if kind == "caption":
                await _safe(bot.edit_message_caption, chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup)
            else:
                await _safe(bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
            continue
        except Exception:  # noqa: BLE001
            return


async def _clear_search_messages(bot, req_id, text, skip_chat=None):
    """پیام «منتظر بمانید» و همه‌ی دعوت‌های یک جستجو رو بی‌دکمه می‌کنه."""
    s = get_session()
    try:
        req = s.get(ChatBridge, req_id)
        if not req:
            return
        wait_id, chat_id, bc = req.wait_message_id, req.chat_id, _json(req.broadcast)
    finally:
        s.close()
    if wait_id:
        await _edit(bot, chat_id, wait_id, text)
    for cid, mid in bc.items():
        if skip_chat is not None and int(cid) == int(skip_chat):
            continue
        await _edit(bot, cid, mid, "ℹ️ این درخواست دیگه فعال نیست.")
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# ۱) شروع جستجو
# ---------------------------------------------------------------------------
async def handle_text(update, context) -> bool:
    msg = update.message
    if not msg or not msg.text or not _TRIGGER_RE.match(msg.text):
        return False
    chat, user = update.effective_chat, update.effective_user
    if not chat or not user:
        return False
    reply = {"reply_to_message_id": msg.message_id}
    if user.id in _BANNED:
        await msg.reply_text(BANNED_NOTICE, **reply)
        return True
    if chat.type not in ("group", "supergroup"):
        await msg.reply_text("🦊 این دستور فقط داخل گروه کار می‌کنه.", **reply)
        return True
    s = get_session()
    try:
        cur = _active_for_chat(s, chat.id)
        if cur and cur.status == "connected":
            other = safe_title(cur.partner_title if cur.chat_id == chat.id else cur.chat_title)
            await msg.reply_text(f"🔗 این گپ همین الان به «{other}» وصله.", **reply)
            return True
        if cur and cur.status == "searching":
            await msg.reply_text("🔎 جستجو هنوز ادامه داره؛ اگه نمی‌خوای، دکمه‌ی «لغو جستجو» رو بزن.", **reply)
            return True
        last = (s.query(ChatBridge).filter(ChatBridge.chat_id == chat.id)
                .order_by(ChatBridge.id.desc()).first())
        if last and last.created_at:
            gone = (now_utc() - aware(last.created_at)).total_seconds()
            if gone < BRIDGE_REQUEST_COOLDOWN:
                left = int(BRIDGE_REQUEST_COOLDOWN - gone)
                await msg.reply_text(f"⏳ {left // 60} دقیقه و {left % 60} ثانیه‌ی دیگه می‌تونی دوباره درخواست بدی.", **reply)
                return True
        req = ChatBridge(chat_id=chat.id, chat_title=chat.title or "گپ", requester_id=user.id,
                         status="searching", expires_at=now_utc() + timedelta(seconds=BRIDGE_SEARCH_TTL))
        s.add(req)
        s.commit()
        bid = req.id
    finally:
        s.close()
    wait = await _send_banner(context.bot, chat.id, WAIT_TEXT, wait_kb(bid), reply_to=msg.message_id)
    s = get_session()
    try:
        s.query(ChatBridge).filter(ChatBridge.id == bid).update({"wait_message_id": wait.message_id})
        s.commit()
    finally:
        s.close()
    context.application.create_task(_broadcast(context.bot, bid), update=update)
    return True


def _status_of(bid):
    s = get_session()
    try:
        r = s.get(ChatBridge, bid)
        return r.status if r else None
    finally:
        s.close()


def _save_broadcast(bid, sent):
    s = get_session()
    try:
        s.query(ChatBridge).filter(ChatBridge.id == bid).update({"broadcast": json.dumps(sent)})
        s.commit()
    finally:
        s.close()


async def _broadcast(bot, bid):
    """دعوت‌نامه رو برای همه‌ی گپ‌های دیگه‌ی ربات می‌فرسته (به ترتیب و آروم تا فلود نشه)."""
    s = get_session()
    try:
        req = s.get(ChatBridge, bid)
        if not req:
            return
        busy = set(_CACHE.keys())
        targets = [c.chat_id for c in s.query(GroupChat).filter(GroupChat.active == 1).all()
                   if c.chat_id != req.chat_id and c.chat_id not in busy]
    finally:
        s.close()
    sent = {}
    for i, cid in enumerate(targets):
        if i % 5 == 0 and _status_of(bid) != "searching":
            break
        try:
            m = await _send_banner(bot, cid, INVITE_TEXT, invite_kb(bid))
            sent[str(cid)] = m.message_id
        except (Forbidden, BadRequest):
            pass
        except Exception as e:  # noqa: BLE001
            logger.info("bridge invite to %s failed: %s", cid, e)
        if sent and len(sent) % 5 == 0:
            _save_broadcast(bid, sent)
        await asyncio.sleep(0.07)
    _save_broadcast(bid, sent)
    # اگه وسط ارسال لغو شد یا یه گپ قبول کرد، دعوت‌هایی که تازه رفتن رو هم جمع کن
    s = get_session()
    try:
        r = s.get(ChatBridge, bid)
        st, partner = (r.status, r.partner_chat_id) if r else (None, None)
    finally:
        s.close()
    if st and st != "searching":
        for cid, mid in sent.items():
            if st == "connected" and partner is not None and int(cid) == int(partner):
                continue
            await _edit(bot, cid, mid, "ℹ️ این درخواست دیگه فعال نیست.")
            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# ۲) دکمه‌ها
# ---------------------------------------------------------------------------
async def button(update, context):
    q = update.callback_query
    try:
        _, action, raw = q.data.split(":")
        rid = int(raw)
    except Exception:  # noqa: BLE001
        await q.answer()
        return
    if not q.message:
        await q.answer()
        return
    if action == "ok":
        await _accept(q, context, rid)
    elif action == "cancel":
        await _cancel(q, context, rid)
    elif action == "end":
        await _end_button(q, context, rid)
    elif action == "rep":
        await _report_bridge(q, context, rid)
    elif action == "rm":
        await _report_message(q, context, rid)
    elif action in ("ban", "unban", "dismiss"):
        await _support_decision(q, context, action, rid)
    else:
        await q.answer()


async def _cancel(q, context, bid):
    s = get_session()
    try:
        req = s.get(ChatBridge, bid)
        if not req or req.status != "searching":
            await q.answer("این جستجو تموم شده.", show_alert=True)
            return
        uid = q.from_user.id
        ok = uid == req.requester_id or uid in ADMIN_IDS or await _is_chat_admin(context.bot, req.chat_id, uid)
        if not ok:
            await q.answer("فقط کسی که درخواست داده یا ادمین‌های گپ می‌تونن جستجو رو لغو کنن.", show_alert=True)
            return
        n = (s.query(ChatBridge).filter(ChatBridge.id == bid, ChatBridge.status == "searching")
             .update({"status": "cancelled", "ended_at": now_utc(), "ended_by": uid}, synchronize_session=False))
        s.commit()
    finally:
        s.close()
    if n != 1:
        await q.answer("این جستجو تموم شده.", show_alert=True)
        return
    await q.answer("جستجو لغو شد.")
    await _clear_search_messages(context.bot, bid, "🚫 جستجو لغو شد.")


async def _accept(q, context, bid):
    chat = q.message.chat
    uid = q.from_user.id
    if uid in _BANNED:
        await q.answer("🚫 شما از «روباهیو وصل شو» محروم هستید.", show_alert=True)
        return
    own_cancel = []
    s = get_session()
    try:
        req = s.get(ChatBridge, bid)
        if not req or req.status != "searching" or (req.expires_at and aware(req.expires_at) <= now_utc()):
            await q.answer("این درخواست دیگه فعال نیست.", show_alert=True)
            await _edit(context.bot, chat.id, q.message.message_id, "ℹ️ این درخواست دیگه فعال نیست.")
            return
        if chat.id == req.chat_id:
            await q.answer("این درخواست مال خود همین گپه 🙂", show_alert=True)
            return
        cur = _active_for_chat(s, chat.id)
        if cur and cur.status == "connected":
            await q.answer("این گپ همین الان داره با یه گپ دیگه گفت و گو می‌کنه.", show_alert=True)
            return
        # اگه خود این گپ هم داشت دنبال گپ می‌گشت، جستجوی خودش لغو می‌شه
        for o in s.query(ChatBridge).filter(ChatBridge.chat_id == chat.id, ChatBridge.status == "searching").all():
            if (s.query(ChatBridge).filter(ChatBridge.id == o.id, ChatBridge.status == "searching")
                    .update({"status": "cancelled", "ended_at": now_utc(), "ended_by": uid}, synchronize_session=False)):
                own_cancel.append(o.id)
        ends = now_utc() + timedelta(seconds=BRIDGE_TALK_SECONDS)
        n = (s.query(ChatBridge).filter(ChatBridge.id == bid, ChatBridge.status == "searching")
             .update({"status": "connected", "partner_chat_id": chat.id, "partner_title": chat.title or "گپ",
                      "partner_user_id": uid, "connected_at": now_utc(), "ends_at": ends}, synchronize_session=False))
        s.commit()
        if n != 1:
            await q.answer("یه گپ دیگه زودتر در رو باز کرد 😅", show_alert=True)
            return
        s.expire_all()
        req = s.get(ChatBridge, bid)
        a_chat, a_title, b_chat, b_title = req.chat_id, req.chat_title, chat.id, (chat.title or "گپ")
        wait_id = req.wait_message_id
        bc = _json(req.broadcast)
    finally:
        s.close()

    _load_cache()
    await q.answer("🚪 در باز شد!")
    bot = context.bot
    # جستجوهای قبلیِ خودِ گپ B
    for oid in own_cancel:
        await _clear_search_messages(bot, oid, "🚫 جستجو لغو شد (به یک گپ دیگه وصل شدی).")
    # پیام‌های دعوت و انتظار
    if wait_id:
        await _edit(bot, a_chat, wait_id, "✅ یک گپ در رو باز کرد!")
    await _edit(bot, b_chat, q.message.message_id, "✅ در رو باز کردی!")
    for cid, mid in bc.items():
        if int(cid) == int(b_chat):
            continue
        await _edit(bot, cid, mid, "ℹ️ این درخواست توسط گپ دیگه‌ای پذیرفته شد.")
        await asyncio.sleep(0.05)

    def text_for(other):
        return (f"✅ شما به گپ «{other}» وصل شدید!\n\n"
                f"⏳ {BRIDGE_TALK_SECONDS // 60} دقیقه فرصت گفت و گو دارید.\n"
                "برای فرستادن پیام، روی پیام اونوریا (یا همین پیام) ریپلای کن؛ پیامت به شکل نقل‌قول با اسمت می‌ره.\n"
                "⚠️ لینک و یوزرنیم از تونل لونه‌ها رد نمی‌شن.")
    msgs = {}
    for cid, other in ((a_chat, safe_title(b_title)), (b_chat, safe_title(a_title))):
        try:
            m = await _safe(bot.send_message, chat_id=cid, text=text_for(other), reply_markup=connected_kb(bid))
            msgs[str(cid)] = m.message_id
        except Exception as e:  # noqa: BLE001
            logger.warning("bridge connect msg to %s failed: %s", cid, e)
    s = get_session()
    try:
        s.query(ChatBridge).filter(ChatBridge.id == bid).update({"connect_msgs": json.dumps(msgs)})
        s.commit()
    finally:
        s.close()


def _bridge_stats(bid):
    """(تعداد پیام‌های ردوبدل‌شده، اسم پرپیام‌ترین فرد یا None). فقط اسم، بدون آیدی/یوزرنیم."""
    s = get_session()
    try:
        rows = (s.query(ChatBridgeMessage.sender_id, ChatBridgeMessage.sender_name, ChatBridgeMessage.id)
                .filter(ChatBridgeMessage.bridge_id == bid, ChatBridgeMessage.dst_message_id.isnot(None))
                .order_by(ChatBridgeMessage.id).limit(20000).all())
    finally:
        s.close()
    if not rows:
        return 0, None
    counts, first, name = {}, {}, {}
    for sid, sname, mid in rows:
        counts[sid] = counts.get(sid, 0) + 1
        first.setdefault(sid, mid)
        name[sid] = sname          # آخرین اسمی که استفاده کرده
    top = sorted(counts, key=lambda k: (-counts[k], first[k]))[0]
    return len(rows), clean_text_name(name[top])


def _final_caption(bid, reason):
    total, top = _bridge_stats(bid)
    lines = [reason, ""]
    if total == 0:
        lines.append("💬 هیچ پیامی رد و بدل نشد.")
    else:
        lines.append(f"💬 تعداد پیام‌های رد و بدل‌شده: {total:,}")
        lines.append(f"🏆 بیشترین پیام رو داده: {top}")
    return "\n".join(lines)


async def _finish(bot, bid, by, text):
    """گفت و گو رو تموم می‌کنه (اتمیک؛ فقط یک بار) و عکس پایان + آمار رو برای هر دو گپ می‌فرسته."""
    s = get_session()
    try:
        n = (s.query(ChatBridge).filter(ChatBridge.id == bid, ChatBridge.status == "connected")
             .update({"status": "ended", "ended_at": now_utc(), "ended_by": by}, synchronize_session=False))
        s.commit()
        if n != 1:
            return False
        req = s.get(ChatBridge, bid)
        chats = [req.chat_id, req.partner_chat_id]
        cmsgs = _json(req.connect_msgs)
    finally:
        s.close()
    _load_cache()
    caption = _final_caption(bid, text)
    for cid in chats:
        try:
            await _send_banner(bot, cid, caption)
        except Exception as e:  # noqa: BLE001
            logger.info("bridge end msg to %s failed: %s", cid, e)
        mid = cmsgs.get(str(cid))
        if mid:    # دکمه‌ی پایان برداشته می‌شه؛ «گزارش» می‌مونه
            try:
                await _safe(bot.edit_message_reply_markup, chat_id=cid, message_id=int(mid), reply_markup=report_only_kb(bid))
            except Exception:  # noqa: BLE001
                pass
    return True


async def _end_button(q, context, bid):
    chat = q.message.chat
    s = get_session()
    try:
        req = s.get(ChatBridge, bid)
        if not req or chat.id not in (req.chat_id, req.partner_chat_id):
            await q.answer("این دکمه مال این گفت و گو نیست.", show_alert=True)
            return
        if req.status != "connected":
            await q.answer("این گفت و گو قبلاً تموم شده.", show_alert=True)
            return
    finally:
        s.close()
    if not await _is_chat_admin(context.bot, chat.id, q.from_user.id):
        await q.answer("فقط ادمین‌های این گپ می‌تونن گفت و گو رو تموم کنن.", show_alert=True)
        return
    done = await _finish(context.bot, bid, q.from_user.id,
                         "🔌 گفت و گو توسط یکی از ادمین‌ها پایان یافت و اتصال دو گپ قطع شد.")
    await q.answer("گفت و گو پایان یافت." if done else "این گفت و گو قبلاً تموم شده.", show_alert=not done)


# ---------------------------------------------------------------------------
# تصمیم پشتیبانی روی گزارش‌ها
# ---------------------------------------------------------------------------
async def _support_decision(q, context, action, uid):
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("این دکمه فقط برای پشتیبانیه.", show_alert=True)
        return
    if action == "dismiss":
        await q.answer("گزارش رد شد.")
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        return
    _set_ban(uid, action == "ban", q.from_user.id)
    await q.answer("🚫 کاربر از «روباهیو وصل شو» محروم شد." if action == "ban" else "✅ محرومیت برداشته شد.", show_alert=True)
    # دکمه‌ی همین کاربر بین «محروم کردن» و «رفع محرومیت» جابه‌جا می‌شه
    try:
        old = q.message.reply_markup.inline_keyboard if q.message.reply_markup else []
        rows = []
        for row in old:
            new_row = []
            for btn in row:
                cd = btn.callback_data or ""
                if cd in (f"brg:ban:{uid}", f"brg:unban:{uid}"):
                    name = btn.text.split(" ", 2)[-1] if " " in btn.text else str(uid)
                    if action == "ban":
                        btn = InlineKeyboardButton("✅ رفع محرومیت " + name, callback_data=f"brg:unban:{uid}")
                    else:
                        btn = InlineKeyboardButton("🚫 محروم کردن " + name, callback_data=f"brg:ban:{uid}")
                new_row.append(btn)
            rows.append(new_row)
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# گزارش به پشتیبانی
# ---------------------------------------------------------------------------
async def _to_support(bot, text, markup=None) -> bool:
    ok = False
    for aid in list(ADMIN_IDS):
        try:
            await _safe(bot.send_message, chat_id=aid, text=text[:4000], parse_mode="HTML",
                        disable_web_page_preview=True, reply_markup=markup)
            ok = True
        except Exception as e:  # noqa: BLE001
            logger.info("bridge report to admin %s failed: %s", aid, e)
    return ok


def support_kb(users):
    """دکمه‌های تصمیم پشتیبانی: محروم کردن هر کاربرِ دخیل یا رد گزارش."""
    rows = []
    for uid, name in users:
        label = ("✅ رفع محرومیت " if uid in _BANNED else "🚫 محروم کردن ") + (name or str(uid))[:22]
        cb = f"brg:{'unban' if uid in _BANNED else 'ban'}:{uid}"
        rows.append([InlineKeyboardButton(label, callback_data=cb)])
    rows.append([InlineKeyboardButton("✖️ رد گزارش", callback_data="brg:dismiss:0")])
    return InlineKeyboardMarkup(rows)


def _user_line(s, uid, fallback_name=""):
    u = s.get(User, uid)
    uname = f" @{u.username}" if u and u.username else ""
    return f'<a href="tg://user?id={uid}">{esc(fallback_name or (u.first_name if u else "") or uid)}</a>{esc(uname)} (<code>{uid}</code>)'


async def _report_bridge(q, context, bid):
    chat, uid = q.message.chat, q.from_user.id
    s = get_session()
    try:
        req = s.get(ChatBridge, bid)
        if not req or req.status in ("searching", "cancelled", "expired") or chat.id not in (req.chat_id, req.partner_chat_id):
            await q.answer("این گزارش مربوط به این گفت و گو نیست.", show_alert=True)
            return
        if not await _is_chat_member(context.bot, chat.id, uid):
            await q.answer("فقط اعضای این گفت و گو می‌تونن گزارش بدن.", show_alert=True)
            return
        reporters = set(filter(None, (req.reporters or "").split(",")))
        if str(uid) in reporters:
            await q.answer("قبلاً گزارش دادی؛ پشتیبانی بررسی می‌کنه.", show_alert=True)
            return
        reporters.add(str(uid))
        req.reporters = ",".join(sorted(reporters))
        s.commit()
        rows = (s.query(ChatBridgeMessage).filter(ChatBridgeMessage.bridge_id == bid)
                .order_by(ChatBridgeMessage.id.desc()).limit(15).all())[::-1]
        titles = {req.chat_id: req.chat_title, req.partner_chat_id: req.partner_title}
        lines = [f"🚨 <b>گزارش گفت و گوی دو گپ</b> (#{bid})",
                 f"🏠 گپ اول: {esc(req.chat_title)} (<code>{req.chat_id}</code>)",
                 f"🏠 گپ دوم: {esc(req.partner_title)} (<code>{req.partner_chat_id}</code>)",
                 f"📍 گزارش از گپ: {esc(titles.get(chat.id))}",
                 f"👤 گزارش‌دهنده: {_user_line(s, uid, q.from_user.full_name)}",
                 "", "📜 آخرین پیام‌ها:"]
        for r in rows:
            src = esc(titles.get(r.src_chat_id))
            snippet = esc((r.text or f"[{r.kind}]")[:200])
            lines.append(f"• [{src}] {_user_line(s, r.sender_id, r.sender_name)}: {snippet}")
        if not rows:
            lines.append("(پیامی رد و بدل نشده بود)")
        seen, suspects = set(), []
        for r in rows:
            if r.sender_id not in seen and len(suspects) < 6:
                seen.add(r.sender_id)
                suspects.append((r.sender_id, r.sender_name))
    finally:
        s.close()
    lines.append("\n👇 تصمیم با پشتیبانیه: کاربر خاطی رو از «روباهیو وصل شو» محروم کن یا گزارش رو رد کن.")
    sent = await _to_support(context.bot, "\n".join(lines), support_kb(suspects))
    await q.answer("🚨 گزارشت برای پشتیبانی ارسال شد." if sent else "ارسال گزارش با مشکل روبه‌رو شد؛ بعداً دوباره امتحان کن.", show_alert=True)


async def _report_message(q, context, mid):
    chat, uid = q.message.chat, q.from_user.id
    s = get_session()
    try:
        row = s.get(ChatBridgeMessage, mid)
        if not row or row.dst_chat_id != chat.id:
            await q.answer("این پیام دیگه قابل گزارش نیست.", show_alert=True)
            return
        reporters = set(filter(None, (row.reporters or "").split(",")))
        if str(uid) in reporters:
            await q.answer("این پیام رو قبلاً گزارش دادی.", show_alert=True)
            return
        reporters.add(str(uid))
        row.reporters = ",".join(sorted(reporters))
        s.commit()
        br = s.get(ChatBridge, row.bridge_id)
        titles = {br.chat_id: br.chat_title, br.partner_chat_id: br.partner_title} if br else {}
        text = "\n".join([
            f"🚨 <b>گزارش کاربر از گفت و گوی دو گپ</b> (#{row.bridge_id})",
            f"👤 کاربر گزارش‌شده: {_user_line(s, row.sender_id, row.sender_name)}",
            f"🏠 از گپ: {esc(titles.get(row.src_chat_id))} (<code>{row.src_chat_id}</code>)",
            f"📍 گزارش در گپ: {esc(titles.get(row.dst_chat_id))} (<code>{row.dst_chat_id}</code>)",
            f"🙋 گزارش‌دهنده: {_user_line(s, uid, q.from_user.full_name)}",
            f"📝 نوع پیام: {esc(row.kind)}",
            f"💬 متن: {esc((row.text or '')[:600]) or '—'}",
            "",
            "👇 تصمیم با پشتیبانیه: محروم کن یا گزارش رو رد کن.",
        ])
        sender = (row.sender_id, row.sender_name)
    finally:
        s.close()
    sent = await _to_support(context.bot, text, support_kb([sender]))
    await q.answer("🚨 کاربر برای پشتیبانی گزارش شد." if sent else "ارسال گزارش با مشکل روبه‌رو شد.", show_alert=True)


# ---------------------------------------------------------------------------
# ۳) رد و بدل کردن پیام‌ها
# ---------------------------------------------------------------------------
def _kind(msg):
    if msg.text:
        return "text"
    for k in ("photo", "video", "animation", "voice", "audio", "document", "sticker", "video_note"):
        if getattr(msg, k, None):
            return k
    return None


async def relay(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user or user.is_bot or chat.type not in ("group", "supergroup"):
        return
    info = _CACHE.get(chat.id)
    if not info or info["ends"] <= time.time():
        return
    if not msg.reply_to_message:          # فقط ریپلای‌ها از تونل رد می‌شن
        return
    if msg.text and (msg.text.startswith("/") or _TRIGGER_RE.match(msg.text)):
        return
    kind = _kind(msg)
    if not kind:
        return
    lock = _LOCKS.setdefault(info["id"], asyncio.Lock())
    context.application.create_task(_relay_task(context.bot, lock, dict(info), chat, user, msg, kind), update=update)


async def _relay_task(bot, lock, info, chat, user, msg, kind):
    async with lock:
        try:
            await _relay_one(bot, info, chat, user, msg, kind)
        except Exception:  # noqa: BLE001
            logger.exception("bridge relay failed")


async def _notice(bot, chat_id, msg, text, user_id=None):
    """اخطار برای فرستنده؛ ترجیحاً فقط برای خودش دیده بشه (BRIDGE_PRIVATE_NOTICE_KWARGS)، وگرنه ریپلای موقت."""
    rp = ReplyParameters(message_id=msg.message_id, allow_sending_without_reply=True)
    if _PRIVATE_KW and user_id is not None:
        extra = {k: (str(v).replace("{user_id}", str(user_id)) if isinstance(v, str) else v) for k, v in _PRIVATE_KW.items()}
        try:
            await _safe(bot.send_message, chat_id=chat_id, text=text, reply_parameters=rp, api_kwargs=extra)
            return
        except Exception as e:  # noqa: BLE001
            logger.info("bridge private notice failed (%s); falling back", e)
    try:
        m = await _safe(bot.send_message, chat_id=chat_id, text=text, reply_parameters=rp)
        t = asyncio.create_task(_delete_later(bot, chat_id, m.message_id, NOTICE_SECONDS))
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)
    except Exception:  # noqa: BLE001
        pass


async def _relay_one(bot, info, chat, user, msg, kind):
    dst = info["partner"]
    rid = msg.reply_to_message.message_id
    raw_text = (msg.text or msg.caption or "")
    s = get_session()
    try:
        # آیا روی پیامِ «اونوریا» (کپیِ رسیده از گپ مقابل) یا پیام «وصل شدید» ریپلای شده؟
        hit = (s.query(ChatBridgeMessage).filter(ChatBridgeMessage.bridge_id == info["id"],
                                                 ChatBridgeMessage.dst_chat_id == chat.id,
                                                 ChatBridgeMessage.dst_message_id == rid).first())
        reply_to = None
        if hit:
            reply_to = hit.src_message_id          # پیام اصلی اون طرف
        else:
            br = s.get(ChatBridge, info["id"])
            cm = _json(br.connect_msgs) if br else {}
            if str(rid) != str(cm.get(str(chat.id))):
                return                              # ریپلای روی چیزی نیست که به اونور مربوط باشه
            if cm.get(str(dst)):
                reply_to = int(cm[str(dst)])
    finally:
        s.close()

    # محروم‌شده‌ها پیامشون رد نمی‌شه (و یه پیام قابل‌مشاهده می‌گیرن)
    if user.id in _BANNED:
        if time.time() - _ban_notice.get(user.id, 0) > 600:
            _ban_notice[user.id] = time.time()
            await _notice(bot, chat.id, msg, BANNED_NOTICE, user.id)
        return
    # لینک و یوزرنیم به هیچ وجه از تونل رد نمی‌شه
    ents = tuple(msg.entities or ()) + tuple(msg.caption_entities or ())
    if contains_link(raw_text, ents):
        await _notice(bot, chat.id, msg, LINK_WARNING, user.id)
        return

    name = clean_name(user)
    head = f"👤 <b>{esc(name)}</b> از گپ «{esc(safe_title(chat.title))}»"
    s = get_session()
    try:
        row = ChatBridgeMessage(bridge_id=info["id"], src_chat_id=chat.id, src_message_id=msg.message_id,
                                dst_chat_id=dst, sender_id=user.id, sender_name=(user.full_name or "")[:80],
                                kind=kind, text=raw_text[:500])
        s.add(row)
        s.flush()
        row_id = row.id
        s.commit()
    finally:
        s.close()

    rp = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
    kb = msg_kb(row_id)
    sent_id = None
    try:
        if kind == "text":
            body = f"{head}\n<blockquote>{esc(raw_text[:3500])}</blockquote>"
            m = await _safe(bot.send_message, chat_id=dst, text=body, parse_mode="HTML",
                            reply_markup=kb, reply_parameters=rp)
            sent_id = m.message_id
        elif kind in ("sticker", "video_note"):
            label = "🎭 استیکر" if kind == "sticker" else "⭕ ویدیو پیام"
            h = await _safe(bot.send_message, chat_id=dst, text=f"{head}\n<blockquote>{label}</blockquote>",
                            parse_mode="HTML", reply_parameters=rp)
            m = await _safe(bot.copy_message, chat_id=dst, from_chat_id=chat.id, message_id=msg.message_id,
                            reply_markup=kb,
                            reply_parameters=ReplyParameters(message_id=h.message_id, allow_sending_without_reply=True))
            sent_id = m.message_id
        else:
            cap = head
            if msg.caption:
                cap += f"\n<blockquote>{esc(msg.caption[:800])}</blockquote>"
            m = await _safe(bot.copy_message, chat_id=dst, from_chat_id=chat.id, message_id=msg.message_id,
                            caption=cap, parse_mode="HTML", reply_markup=kb, reply_parameters=rp)
            sent_id = m.message_id
    except Exception as e:  # noqa: BLE001
        logger.info("bridge relay to %s failed: %s", dst, e)

    s = get_session()
    try:
        if sent_id:
            s.query(ChatBridgeMessage).filter(ChatBridgeMessage.id == row_id).update({"dst_message_id": sent_id})
        else:
            s.query(ChatBridgeMessage).filter(ChatBridgeMessage.id == row_id).delete()
        s.commit()
    finally:
        s.close()
    if sent_id:
        try:    # 🕊 یعنی پیامت رفت اونور
            await _safe(bot.set_message_reaction, chat.id, msg.message_id, reaction=REACTION)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# ۴) پایان خودکار
# ---------------------------------------------------------------------------
async def tick(context):
    bot = context.bot
    s = get_session()
    try:
        now = now_utc()
        searching = [r.id for r in s.query(ChatBridge.id).filter(ChatBridge.status == "searching", ChatBridge.expires_at <= now).all()]
        talking = [r.id for r in s.query(ChatBridge.id).filter(ChatBridge.status == "connected", ChatBridge.ends_at <= now).all()]
    finally:
        s.close()
    for bid in searching:
        s = get_session()
        try:
            n = (s.query(ChatBridge).filter(ChatBridge.id == bid, ChatBridge.status == "searching")
                 .update({"status": "expired", "ended_at": now_utc()}, synchronize_session=False))
            s.commit()
        finally:
            s.close()
        if n == 1:
            await _clear_search_messages(bot, bid, "⌛ هیچ گپی در رو باز نکرد؛ جستجو تموم شد.")
    for bid in talking:
        await _finish(bot, bid, 0, f"⏳ مهلت {BRIDGE_TALK_SECONDS // 60} دقیقه‌ای گفت و گو تموم شد و اتصال دو گپ قطع شد.")
    _load_cache()
    try:
        _load_bans()
    except Exception:  # noqa: BLE001
        pass
    if time.time() - _last_purge[0] > 3600:
        _last_purge[0] = time.time()
        s = get_session()
        try:
            cut = now_utc() - timedelta(seconds=RETENTION_SECONDS)
            s.query(ChatBridgeMessage).filter(ChatBridgeMessage.created_at < cut).delete(synchronize_session=False)
            s.commit()
        except Exception:  # noqa: BLE001
            s.rollback()
        finally:
            s.close()


async def banner_test(update, context):
    """/bannertest (فقط ادمین‌های ربات): عکس بنر رو می‌فرسته و اگه نشد دلیل دقیق رو می‌گه."""
    user, msg, chat = update.effective_user, update.effective_message, update.effective_chat
    if not user or user.id not in ADMIN_IDS or not msg:
        return
    src = _banner_source()
    if not src:
        await msg.reply_text("❌ هیچ نسخه‌ای از عکس بنر پیدا نشد (نه assets/fox_portal.jpg، نه bridge_banner.py).")
        return
    origin = _IMG["origin"] or "file_id کش‌شده"
    try:
        m = await context.bot.send_photo(chat_id=chat.id, photo=src, caption=f"✅ تست بنر موفق بود.\nمنبع: {origin}")
        if m.photo and not _IMG["file_id"]:
            _IMG["file_id"] = m.photo[-1].file_id
    except Exception as e:  # noqa: BLE001
        await msg.reply_text(f"❌ ارسال عکس خطا داد:\n{type(e).__name__}: {e}\n\nمنبع عکس: {origin}")


def register(app):
    """هندلرها و جاب‌ها رو به اپلیکیشن اضافه می‌کنه (از bot.py صدا زده می‌شه)."""
    app.add_handler(CommandHandler("bannertest", banner_test))
    app.add_handler(CallbackQueryHandler(button, pattern=r"^brg:(ok|cancel|end|rep|rm|ban|unban|dismiss):\d+$"))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & (
            filters.TEXT | filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.ALL
            | filters.AUDIO | filters.VOICE | filters.Sticker.ALL | filters.VIDEO_NOTE),
        relay), group=7)
    try:
        _load_cache()
        _load_bans()
    except Exception:  # noqa: BLE001
        logger.exception("bridge cache load failed")
    _banner_source()      # همون ابتدا توی لاگ می‌نویسه عکس از کجا برداشته شد
    if app.job_queue:
        app.job_queue.run_repeating(tick, interval=20, first=15, name="bridge-tick")
