# -*- coding: utf-8 -*-
"""
قابلیت «سلف» روبی.

- پشتیبانی از پنل مدیریت (🤖 سلف) با آیدی عددی کاربر، سلف رو برای اون کاربر فعال/غیرفعال می‌کنه.
- کاربرِ فعال‌شده با /self (یا نوشتن «سلف») اکانتش رو وصل می‌کنه و تا ۳ کلمه تنظیم می‌کنه:
  هر کلمه = (کلمه، گپ، تایمر، جای دکمه: چپ/وسط/راست/خالی).
- وقتی کاربر از اکانت خودش دقیقاً اون کلمه رو توی همون گپ بفرسته، بعد از تایمر، سلف روی دکمه‌ی انتخاب‌شده‌ی
  پیام ربات (ریپلای یا آخرین پیام دکمه‌دار ربات‌های دیگه) کلیک می‌کنه. روی ربات روباهیو هیچ‌وقت کلیک نمی‌کنه.

امنیت: سشن‌ها رمزنگاری‌شده ذخیره می‌شن (Fernet)، سلف هیچ‌وقت روی ربات روباهیو کلیک نمی‌کنه،
محدودیت سرعت داره و کاربر هر لحظه می‌تونه اتصال رو قطع کنه (خروج کامل از سشن).

متغیرهای Railway: SELF_API_ID و SELF_API_HASH (از my.telegram.org)، اختیاری: SELF_KEY.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, Text
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from database import Base, get_session

logger = logging.getLogger(__name__)

MAX_SLOTS = 3
MAX_DELAY = 3600
POS = {"l": "⬅️ چپ", "m": "⏺ وسط", "r": "➡️ راست", "n": "⬜ خالی"}
API_ID = int(os.environ.get("SELF_API_ID", "0") or 0)
API_HASH = os.environ.get("SELF_API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()


class SelfAccess(Base):
    __tablename__ = "self_access"
    user_id = Column(BigInteger, primary_key=True)
    enabled = Column(Boolean, default=True)
    paused = Column(Boolean, default=False)
    phone = Column(String, nullable=True)
    session_enc = Column(Text, nullable=True)
    slots = Column(Text, default="[]")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------- ابزارها ----------
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa2en(s):
    return (s or "").translate(_FA)


def norm(s):
    return re.sub(r"[\u200c\u200d\ufe0f\s]+", " ", s or "").strip().lower()


def _fernet():
    from cryptography.fernet import Fernet
    raw = os.environ.get("SELF_KEY", "").strip() or ("rubahio-self:" + BOT_TOKEN)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def enc(s):
    return _fernet().encrypt(s.encode()).decode()


def dec(s):
    return _fernet().decrypt(s.encode()).decode()


def configured():
    return bool(API_ID and API_HASH)


def get_row(uid):
    s = get_session()
    try:
        r = s.get(SelfAccess, uid)
        if r:
            s.expunge(r)
        return r
    finally:
        s.close()


def save_row(uid, **kw):
    s = get_session()
    try:
        r = s.get(SelfAccess, uid)
        if not r:
            r = SelfAccess(user_id=uid, enabled=True, paused=False, slots="[]")
            s.add(r)
        for k, v in kw.items():
            setattr(r, k, v)
        s.commit()
    finally:
        s.close()


def slots_of(row):
    try:
        v = json.loads(row.slots or "[]")
        return [x for x in v if isinstance(x, dict)][:MAX_SLOTS]
    except Exception:
        return []


def parse_delay(text):
    m = re.match(r"^(\d{1,5})\s*(s|m|ثانیه|دقیقه)?$", fa2en(text).strip().lower())
    if not m:
        return None
    n = int(m.group(1)) * (60 if m.group(2) in ("m", "دقیقه") else 1)
    return n if 0 <= n <= MAX_DELAY else None


def fmt_delay(n):
    n = int(n or 0)
    return f"{n // 60} دقیقه" if n >= 60 and n % 60 == 0 else f"{n} ثانیه"


# ---------- هسته‌ی سلف (Telethon) ----------
_clients = {}
_slots = {}
_paused = {}
_hist = {}
_last = {}
_login = {}
_bot_id = [0]


def _load_runtime(uid, row):
    _slots[uid] = slots_of(row)
    _paused[uid] = bool(row.paused)


async def stop_client(uid, logout=False):
    c = _clients.pop(uid, None)
    _slots.pop(uid, None)
    if c:
        try:
            if logout:
                await c.log_out()
            else:
                await c.disconnect()
        except Exception:
            try:
                await c.disconnect()
            except Exception:
                pass


async def start_client(uid):
    if not configured():
        return False
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    row = get_row(uid)
    if not (row and row.enabled and row.session_enc):
        return False
    await stop_client(uid)
    try:
        client = TelegramClient(StringSession(dec(row.session_enc)), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            save_row(uid, session_enc=None)
            await client.disconnect()
            return False
    except Exception as e:  # noqa: BLE001
        logger.warning("self start failed %s: %s", uid, e)
        return False
    _load_runtime(uid, row)

    async def _h(ev, _uid=uid):
        await _on_out(_uid, ev)
    client.add_event_handler(_h, events.NewMessage(outgoing=True))
    _clients[uid] = client
    return True


async def _on_out(uid, ev):
    if _paused.get(uid):
        return
    txt = norm(ev.raw_text or "")
    if not txt:
        return
    for i, s in enumerate(_slots.get(uid, [])):
        if s and s.get("word") and s.get("chat") and s.get("pos", "n") != "n" and ev.chat_id == s["chat"] and ev.chat_id != _bot_id[0] and norm(s["word"]) == txt:
            now = time.time()
            if now - _last.get((uid, i), 0) < 2:
                continue
            h = [t for t in _hist.get(uid, []) if now - t < 60]
            if len(h) >= 20:
                return
            h.append(now)
            _hist[uid] = h
            _last[(uid, i)] = now
            asyncio.create_task(_fire(uid, ev, s))


def _pick_button(msg, pos):
    rows = [r for r in (msg.buttons or []) if r]
    if not rows or pos == "n":
        return None
    row = rows[0]
    if pos == "l":
        return row[0]
    if pos == "r":
        return row[-1]
    if len(row) == 1:
        return row[0]
    return row[len(row) // 2] if len(row) % 2 == 1 else None


async def _usable(m):
    """پیام دکمه‌دار از یک ربات؛ هیچ‌وقت ربات روباهیو."""
    if not m.buttons or m.sender_id == _bot_id[0]:
        return False
    snd = await m.get_sender()
    return bool(snd and getattr(snd, "bot", False))


async def _fire(uid, ev, s):
    try:
        await asyncio.sleep(max(0, int(s.get("delay", 0))))
        client = _clients.get(uid)
        if not client or _paused.get(uid) or ev.chat_id == _bot_id[0]:
            return
        pos = s.get("pos", "n")
        target = None
        if ev.is_reply:
            m = await ev.get_reply_message()
            if m and await _usable(m):
                target = m
        if not target:
            async for m in client.iter_messages(ev.chat_id, limit=15):
                if m.buttons and await _usable(m):
                    target = m
                    break
        btn = _pick_button(target, pos) if target else None
        if btn:
            await btn.click()
    except Exception as e:  # noqa: BLE001
        logger.info("self fire failed %s: %s", uid, e)


async def start_all(app):
    _bot_id[0] = app.bot.id
    if not configured():
        logger.info("self: SELF_API_ID/SELF_API_HASH تنظیم نشده؛ سلف غیرفعال است")
        return
    s = get_session()
    try:
        ids = [r.user_id for r in s.query(SelfAccess).filter(SelfAccess.enabled.is_(True), SelfAccess.session_enc.isnot(None)).all()]
    finally:
        s.close()

    async def _go():
        for uid in ids:
            try:
                await start_client(uid)
            except Exception as e:  # noqa: BLE001
                logger.warning("self autostart %s: %s", uid, e)
            await asyncio.sleep(1.5)
    asyncio.create_task(_go())


async def _dialogs(client):
    out = []
    try:
        async for d in client.iter_dialogs(limit=300):
            if d.id == _bot_id[0]:
                continue
            if d.is_group:
                out.append((d.id, d.name or str(d.id), True))
            elif d.is_user and getattr(d.entity, "bot", False):
                out.append((d.id, d.name or str(d.id), False))
    except Exception as e:  # noqa: BLE001
        logger.info("dialogs failed: %s", e)
    return out


# ---------- پنل کاربر ----------
def _panel(uid):
    row = get_row(uid)
    sl = slots_of(row)
    on = uid in _clients
    lines = ["🤖 <b>سلف روبی</b>\n",
             f"🔌 اتصال: {'✅ وصل' if on else '❌ قطع'}",
             f"⚙️ وضعیت: {'⏸ متوقف' if row.paused else '▶️ فعال'}\n",
             "کلمه رو توی گپ انتخابی از اکانت خودت بفرست؛ بعد از تایمر، دکمه‌ی انتخابی (چپ/وسط/راست) زده می‌شه.\n"]
    kb = []
    for i in range(MAX_SLOTS):
        s = sl[i] if i < len(sl) else None
        if s and s.get("word"):
            t = f"{i + 1}️⃣ «{s['word']}» {(s.get('title') or '💬؟')[:12]} {POS[s.get('pos', 'n')]}"
        else:
            t = f"{i + 1}️⃣ ➕ تنظیم کلمه"
        kb.append([B(t[:60], callback_data=f"self:s:{i}")])
    kb.append([B("🔌 قطع اتصال" if on else "🔗 اتصال اکانت", callback_data="self:disc" if on else "self:conn")])
    kb.append([B("▶️ فعال‌سازی" if row.paused else "⏸ توقف موقت", callback_data="self:tog")])
    return "\n".join(lines), KB(kb)


def _slot_panel(uid, i):
    row = get_row(uid)
    sl = slots_of(row)
    s = sl[i] if i < len(sl) else {}
    t = (f"{i + 1}️⃣ <b>کلمه‌ی {i + 1}</b>\n\n📝 کلمه: {s.get('word') or '—'}\n"
         f"💬 گپ: {s.get('title') or '—'}\n"
         f"⏱ تایمر: {fmt_delay(s.get('delay', 0)) if s.get('word') else '—'}\n🎯 دکمه: {POS[s.get('pos', 'n')]}")
    kb = KB([[B("📝 کلمه", callback_data=f"self:e:{i}:word"), B("💬 گپ", callback_data=f"self:cp:{i}:0")],
             [B("⏱ تایمر", callback_data=f"self:e:{i}:delay"), B("🎯 دکمه", callback_data=f"self:pm:{i}")],
             [B("🗑 حذف", callback_data=f"self:d:{i}"), B("🔙 بازگشت", callback_data="self:home")]])
    return t, kb


def _get_slots(uid):
    row = get_row(uid)
    sl = slots_of(row)
    while len(sl) < MAX_SLOTS:
        sl.append({})
    return sl


def _put_slots(uid, sl):
    save_row(uid, slots=json.dumps(sl, ensure_ascii=False))
    row = get_row(uid)
    if uid in _clients:
        _load_runtime(uid, row)


def _allowed(uid):
    r = get_row(uid)
    return bool(r and r.enabled)


async def cmd_self(update, context):
    u = update.effective_user
    if update.effective_chat.type != "private":
        return
    if not _allowed(u.id):
        raise ApplicationHandlerStop   # برای کسی که سلف نداره هیچ پیامی نمی‌آد
    t, kb = _panel(u.id)
    await update.effective_message.reply_text(t, reply_markup=kb, parse_mode="HTML")


async def cb_user(update, context):
    q = update.callback_query
    uid = q.from_user.id
    if not _allowed(uid):
        await q.answer()
        return
    p = q.data.split(":")
    a = p[1]
    ud = context.user_data
    await q.answer()

    async def home():
        ud.pop("self_st", None)
        t, kb = _panel(uid)
        await q.message.edit_text(t, reply_markup=kb, parse_mode="HTML")

    if a == "home":
        await home()
    elif a == "tog":
        r = get_row(uid)
        save_row(uid, paused=not r.paused)
        if uid in _clients:
            _load_runtime(uid, get_row(uid))
        await home()
    elif a == "s":
        i = int(p[2])
        t, kb = _slot_panel(uid, i)
        await q.message.edit_text(t, reply_markup=kb, parse_mode="HTML")
    elif a == "e":
        i, f = int(p[2]), p[3]
        ud["self_st"] = {"step": f, "slot": i}
        ask = {"word": "📝 کلمه رو بفرست (دقیقاً همونی که می‌خوای از اکانتت بگی):",
               "delay": "⏱ تایمر رو بفرست؛ مثلاً <code>30</code> (ثانیه) یا <code>5 دقیقه</code> (حداکثر ۶۰ دقیقه):",
               }[f]
        await q.message.edit_text(ask, parse_mode="HTML", reply_markup=KB([[B("🔙 بازگشت", callback_data=f"self:s:{i}")]]))
    elif a == "pm":
        i = int(p[2])
        await q.message.edit_text("🎯 کدوم دکمه‌ی پیام ربات زده بشه؟\n(⬜ خالی = هیچ دکمه‌ای زده نشه)", reply_markup=KB([
            [B(POS["l"], callback_data=f"self:p:{i}:l"), B(POS["m"], callback_data=f"self:p:{i}:m"), B(POS["r"], callback_data=f"self:p:{i}:r")],
            [B(POS["n"], callback_data=f"self:p:{i}:n")], [B("🔙 بازگشت", callback_data=f"self:s:{i}")]]))
    elif a == "p":
        i, v = int(p[2]), p[3]
        if v in POS:
            sl = _get_slots(uid)
            sl[i]["pos"] = v
            sl[i].setdefault("delay", 0)
            _put_slots(uid, sl)
        t, kb = _slot_panel(uid, i)
        await q.message.edit_text(t, reply_markup=kb, parse_mode="HTML")
    elif a == "cp":
        i, pg = int(p[2]), int(p[3])
        c = _clients.get(uid)
        if not c:
            await q.answer("اول اکانتت رو وصل کن.", show_alert=True)
            return
        if pg == 0 or "self_dl" not in ud:
            ud["self_dl"] = await _dialogs(c)
        pg = max(0, pg - 1)   # مقدار callback = شماره‌ی صفحه + ۱ (۰ یعنی تازه‌سازی)
        dl = ud["self_dl"]
        per = 8
        pg = max(0, min(pg, max(0, (len(dl) - 1) // per)))
        kb = [[B(("👥 " if g else "🤖 ") + n[:28], callback_data=f"self:cs:{i}:{pg * per + k}")] for k, (cid, n, g) in enumerate(dl[pg * per:(pg + 1) * per])]
        nav = []
        if pg > 0:
            nav.append(B("◀️", callback_data=f"self:cp:{i}:{pg}"))
        if (pg + 1) * per < len(dl):
            nav.append(B("▶️", callback_data=f"self:cp:{i}:{pg + 2}"))
        if nav:
            kb.append(nav)
        kb.append([B("🔙 بازگشت", callback_data=f"self:s:{i}")])
        await q.message.edit_text("💬 کلمه توی کدوم گپ گفته بشه؟ (گروه‌ها و چت ربات‌های دیگه)" if dl else "گپی پیدا نشد.", reply_markup=KB(kb))
    elif a == "cs":
        i, k = int(p[2]), int(p[3])
        dl = ud.get("self_dl") or []
        if k >= len(dl):
            await q.answer("لیست قدیمی شده؛ دوباره باز کن.", show_alert=True)
            return
        sl = _get_slots(uid)
        sl[i]["chat"], sl[i]["title"] = dl[k][0], dl[k][1][:40]
        sl[i].setdefault("delay", 0)
        _put_slots(uid, sl)
        t, kb = _slot_panel(uid, i)
        await q.message.edit_text("✅ گپ انتخاب شد.\n\n" + t, reply_markup=kb, parse_mode="HTML")
    elif a == "d":
        i = int(p[2])
        sl = _get_slots(uid)
        sl[i] = {}
        _put_slots(uid, sl)
        await home()
    elif a == "conn":
        if not configured():
            await q.message.edit_text("⚠️ سلف هنوز روی سرور راه‌اندازی نشده (SELF_API_ID / SELF_API_HASH). به پشتیبانی بگو.",
                                      reply_markup=KB([[B("🔙", callback_data="self:home")]]))
            return
        ud["self_st"] = {"step": "phone"}
        await q.message.edit_text(
            "🔗 <b>اتصال اکانت</b>\n\n⚠️ سلف از اکانت شخصی خودت استفاده می‌کنه؛ ریسکش با خودته و فقط برای همین ربات کار می‌کنه. "
            "هر وقت خواستی «قطع اتصال» رو بزن تا سشن کامل بسته بشه.\n\n"
            "شماره‌ت رو با کد کشور بفرست، مثلاً <code>+98912xxxxxxx</code>\n(برای انصراف: لغو)",
            parse_mode="HTML", reply_markup=KB([[B("🔙 بازگشت", callback_data="self:home")]]))
    elif a == "disc":
        await q.message.edit_text("🔌 اتصال قطع بشه و سشن اکانتت کامل بسته بشه؟",
                                  reply_markup=KB([[B("✅ بله، قطع کن", callback_data="self:discy"), B("لغو", callback_data="self:home")]]))
    elif a == "discy":
        await stop_client(uid, logout=True)
        save_row(uid, session_enc=None, phone=None)
        await home()


async def _drop_login(uid):
    d = _login.pop(uid, None)
    if d:
        try:
            await d["client"].disconnect()
        except Exception:
            pass


async def user_text(update, context):
    msg = update.effective_message
    u = update.effective_user
    if not msg or not u or update.effective_chat.type != "private" or not msg.text:
        return
    text = msg.text.strip()
    ud = context.user_data
    # --- ورودی‌های مدیر ---
    aa = ud.get("admin_action")
    if isinstance(aa, str) and aa.startswith("self_") and u.id in ADMIN_IDS:
        await _admin_input(update, context, aa, text)
        raise ApplicationHandlerStop
    if text == "سلف":
        await cmd_self(update, context)   # برای کاربر بدون سلف ساکت است
        raise ApplicationHandlerStop
    st = ud.get("self_st")
    if not st:
        return
    uid = u.id
    if not _allowed(uid):
        ud.pop("self_st", None)
        return
    raise_stop = True
    try:
        if text in ("لغو", "/cancel"):
            ud.pop("self_st", None)
            await _drop_login(uid)
            await msg.reply_text("لغو شد.")
        elif st["step"] in ("word", "delay"):
            i, f = st["slot"], st["step"]
            sl = _get_slots(uid)
            if f == "delay":
                v = parse_delay(text)
                if v is None:
                    await msg.reply_text("❗️ عدد درست بفرست؛ مثلاً 30 یا 5 دقیقه (حداکثر ۶۰ دقیقه).")
                    raise ApplicationHandlerStop
            else:
                v = text[:40]
            sl[i][f] = v
            sl[i].setdefault("delay", 0)
            _put_slots(uid, sl)
            ud.pop("self_st", None)
            t, kb = _slot_panel(uid, i)
            await msg.reply_text("✅ ذخیره شد.\n\n" + t, reply_markup=kb, parse_mode="HTML")
        elif st["step"] == "phone":
            phone = "+" + re.sub(r"\D", "", fa2en(text))
            if not re.match(r"^\+\d{8,15}$", phone):
                await msg.reply_text("❗️ شماره نامعتبره؛ مثل +98912xxxxxxx بفرست.")
                raise ApplicationHandlerStop
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            await _drop_login(uid)
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            sent = await client.send_code_request(phone)
            _login[uid] = {"client": client, "phone": phone, "hash": sent.phone_code_hash, "ts": time.time()}
            st["step"] = "code"
            await msg.reply_text("📨 کد تلگرام برات اومد. <b>با فاصله بین رقم‌ها</b> بفرست تا تلگرام بلاکش نکنه؛ مثلاً <code>1 2 3 4 5</code>",
                                 parse_mode="HTML")
        elif st["step"] in ("code", "pw"):
            d = _login.get(uid)
            if not d or time.time() - d["ts"] > 600:
                ud.pop("self_st", None)
                await _drop_login(uid)
                await msg.reply_text("⌛ زمان اتصال تموم شد؛ دوباره از /self شروع کن.")
                raise ApplicationHandlerStop
            from telethon import errors
            try:
                if st["step"] == "code":
                    await d["client"].sign_in(d["phone"], re.sub(r"\D", "", fa2en(text)), phone_code_hash=d["hash"])
                else:
                    await d["client"].sign_in(password=text)
                    try:
                        await msg.delete()
                    except Exception:
                        pass
            except errors.SessionPasswordNeededError:
                st["step"] = "pw"
                await msg.reply_text("🔐 تأیید دومرحله‌ای داری؛ رمزش رو بفرست (پیامت بعد از خوندن پاک می‌شه).")
                raise ApplicationHandlerStop
            except (errors.PhoneCodeInvalidError, errors.PasswordHashInvalidError):
                await msg.reply_text("❌ اشتباهه؛ دوباره بفرست (یا لغو).")
                raise ApplicationHandlerStop
            except errors.PhoneCodeExpiredError:
                ud.pop("self_st", None)
                await _drop_login(uid)
                await msg.reply_text("⌛ کد منقضی شد؛ دوباره از /self اتصال بزن.")
                raise ApplicationHandlerStop
            sess = d["client"].session.save()
            save_row(uid, session_enc=enc(sess), phone=d["phone"])
            await _drop_login(uid)
            ud.pop("self_st", None)
            ok = await start_client(uid)
            t, kb = _panel(uid)
            await msg.reply_text(("✅ اکانت وصل شد!\n\n" if ok else "⚠️ ذخیره شد ولی اتصال بالا نیومد.\n\n") + t,
                                 reply_markup=kb, parse_mode="HTML")
    except ApplicationHandlerStop:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("self user_text: %s", e)
        await msg.reply_text("⚠️ خطا: " + str(e)[:150])
    if raise_stop:
        raise ApplicationHandlerStop


# ---------- پنل مدیر ----------
ADMIN_IDS = set()


def admin_menu_kb():
    return KB([[B("➕ فعال‌سازی برای کاربر", callback_data="selfa:on")],
               [B("⏹ غیرفعال‌سازی کاربر", callback_data="selfa:off")],
               [B("🗑 حذف کامل (خروج از سشن)", callback_data="selfa:del")],
               [B("📋 لیست کاربران سلف", callback_data="selfa:list")],
               [B("🔙 بازگشت", callback_data="admin:back")]])


async def cb_admin(update, context):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("دسترسی نداری.", show_alert=True)
        return
    a = q.data.split(":")[1]
    await q.answer()
    if a == "menu":
        context.user_data.pop("admin_action", None)
        await q.message.reply_text("🤖 مدیریت سلف" + ("" if configured() else "\n\n⚠️ SELF_API_ID / SELF_API_HASH تنظیم نشده."),
                                   reply_markup=admin_menu_kb())
    elif a in ("on", "off", "del"):
        context.user_data["admin_action"] = "self_" + a
        await q.message.reply_text("🆔 آیدی عددی کاربر رو بفرست:")
    elif a == "list":
        s = get_session()
        try:
            rows = s.query(SelfAccess).all()
            lines = [f"{'✅' if r.enabled else '⏹'} <code>{r.user_id}</code> {'🔗' if r.user_id in _clients else '—'}" for r in rows]
        finally:
            s.close()
        await q.message.reply_text("📋 کاربران سلف (✅ مجاز | 🔗 وصل):\n\n" + ("\n".join(lines) if lines else "خالیه."),
                                   parse_mode="HTML", reply_markup=admin_menu_kb())


async def _admin_input(update, context, action, text):
    context.user_data.pop("admin_action", None)
    context.user_data["ai_skip_msg"] = update.message.message_id
    t = fa2en(text).strip()
    if not t.isdigit():
        context.user_data["admin_action"] = action
        await update.message.reply_text("❗️ فقط آیدی عددی بفرست.")
        return
    uid = int(t)
    bot = context.bot
    if action == "self_on":
        save_row(uid, enabled=True)
        if get_row(uid).session_enc:
            await start_client(uid)
        await update.message.reply_text(f"✅ سلف برای {uid} فعال شد.", reply_markup=admin_menu_kb())
        try:
            await bot.send_message(uid, "✅ پشتیبانی «سلف» رو برات فعال کرد.\nبرای تنظیم، /self رو بزن یا بنویس «سلف».")
        except Exception:
            pass
    elif action == "self_off":
        if not get_row(uid):
            await update.message.reply_text("❌ این کاربر سلف نداره.", reply_markup=admin_menu_kb())
            return
        save_row(uid, enabled=False)
        await stop_client(uid)
        await update.message.reply_text(f"⏹ سلف {uid} غیرفعال شد.", reply_markup=admin_menu_kb())
    else:
        r = get_row(uid)
        if not r:
            await update.message.reply_text("❌ این کاربر سلف نداره.", reply_markup=admin_menu_kb())
            return
        await stop_client(uid, logout=True)
        s = get_session()
        try:
            x = s.get(SelfAccess, uid)
            if x:
                s.delete(x)
                s.commit()
        finally:
            s.close()
        await update.message.reply_text(f"🗑 سلف {uid} کامل حذف شد.", reply_markup=admin_menu_kb())


def register(app, admin_ids):
    ADMIN_IDS.clear()
    ADMIN_IDS.update(admin_ids)
    app.add_handler(CommandHandler("self", cmd_self), group=-5)
    app.add_handler(CallbackQueryHandler(cb_user, pattern=r"^self:"), group=-5)
    app.add_handler(CallbackQueryHandler(cb_admin, pattern=r"^selfa:"), group=-5)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, user_text), group=-5)
