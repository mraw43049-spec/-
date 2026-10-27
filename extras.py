# -*- coding: utf-8 -*-
"""امکانات بیشتر سلف: پاسخ خودکار، پیام‌های حذف/ویرایش‌شده، ذخیره مدیای تایمردار،
منشن‌گیر، ناظر کلمه/کاربر، سکوت/بلاک سریع و دستورهای ابزار (حساب، قیمت، تاریخ، اذان، کوتاه‌کن لینک، استوری).
تنظیمات هر کاربر داخل همان JSON پروفایل (sb._pget/_pput) ذخیره می‌شود."""
import asyncio
import io
import logging
import random
import re
import time
from collections import OrderedDict

import selfbot as sb
import selftools as tools

logger = logging.getLogger("selfextras")

DEFAULT_AR = "سلام! الان آنلاین نیستم؛ هر وقت برگشتم جواب می‌دم 🙏"
AR_COOLDOWN = 6 * 3600        # به هر نفر حداکثر هر ۶ ساعت یک‌بار
AR_MAX_PER_HOUR = 20          # سقف کل پاسخ‌های خودکار در ساعت (برای ایمنی اکانت)
CACHE_MAX = 1500
CACHE_TTL = 48 * 3600
WL_MAX = 10
NOTIFY_PER_MIN = 20
WL_COOLDOWN = 20

MU_MAX = 30                   # حداکثر کاربر ساکت‌شده
TOOL_PER_MIN = 20             # سقف دستورهای ابزار در دقیقه (برای جلوگیری از فشار به سرویس‌های بیرونی)

TOGGLES = ("ar_on", "del_on", "ttl_on", "mn_on", "wl_on", "mu_on")
CB_ACTIONS = ("more", "mt", "ar_text", "wl", "wl_add", "wl_del", "mu", "mu_add", "mu_del", "city", "thelp")
TEXT_STEPS = ("ar_text", "wl_add", "mu_add", "city")
CMD_WORDS = ("mute", "unmute", "block", "unblock", "undo", "calc", "price", "date", "prayer", "short", "story")

TOOLS_HELP = (
    "› راهنمای ابزارها\n\n"
    ".حساب 25*4+10  ← ماشین‌حساب (یا ریپلای روی پیام)\n"
    ".قیمت  ← خلاصه | .قیمت دلار / یورو / طلا / سکه / بیتکوین ...\n"
    ".تاریخ  ← شمسی/میلادی/قمری | .تاریخ 1405/8/5 ← تبدیل\n"
    ".اذان  ← اوقات شرعی شهر پیش‌فرض | .اذان مشهد\n"
    ".کوتاه لینک  ← کوتاه‌کردن لینک (یا ریپلای روی پیام لینک‌دار)\n"
    ".استوری  ← (ریپلای روی استوری، یا با لینک t.me/user/s/1) ذخیره توی Saved Messages\n"
    ".سکوت  ← (ریپلای) ساکت‌کردن کاربر | .سکوت خاموش\n"
    ".بلاک  ← (ریپلای) بلاک تلگرامی | .رفع بلاک"
)

_cache = {}      # uid -> OrderedDict[msg_id -> rec]
_ar_seen = {}    # uid -> {sender_id: ts}
_ar_hist = {}    # uid -> [ts]
_notif_hist = {}  # uid -> [ts]
_wl_seen = {}    # (uid, chat, item) -> ts
_mn_seen = {}    # (uid, chat, msg_id) -> ts
_tool_hist = {}  # uid -> [ts]


# ---------- کمکی‌ها ----------
def _name(e):
    if e is None:
        return "ناشناس"
    n = " ".join(x for x in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if x)
    return n or getattr(e, "title", None) or (("@" + e.username) if getattr(e, "username", None) else str(getattr(e, "id", "؟")))


def _link(chat, mid):
    try:
        from telethon.tl.types import Channel
        un = getattr(chat, "username", None)
        if un:
            return f"https://t.me/{un}/{mid}"
        if isinstance(chat, Channel):
            return f"https://t.me/c/{chat.id}/{mid}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _kind(msg):
    for attr, label in (("photo", "عکس"), ("video", "ویدیو"), ("voice", "ویس"), ("video_note", "ویدیو مسیج"),
                        ("sticker", "استیکر"), ("gif", "گیف"), ("audio", "آهنگ"), ("document", "فایل")):
        if getattr(msg, attr, None):
            return label
    return "رسانه" if getattr(msg, "media", None) else ""


async def _notify(uid, text):
    """اعلان توی چت ربات؛ سقف تعداد در دقیقه برای جلوگیری از اسپم."""
    bot = sb._botref[0]
    if not bot:
        return
    now = time.time()
    h = [t for t in _notif_hist.get(uid, []) if now - t < 60]
    if len(h) >= NOTIFY_PER_MIN:
        return
    h.append(now)
    _notif_hist[uid] = h
    try:
        await bot.send_message(uid, text[:4000], disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        logger.info("extras notify %s: %s", uid, e)


def cleanup(uid):
    _cache.pop(uid, None)
    _ar_seen.pop(uid, None)
    _ar_hist.pop(uid, None)
    _notif_hist.pop(uid, None)
    _tool_hist.pop(uid, None)


def match_watch(items, text, sender_id, username):
    """آیتم‌های ناظر که با این پیام جور هستن (کلمه / @یوزرنیم / آیدی عددی)."""
    low = (text or "").lower()
    un = (username or "").lower()
    out = []
    for it in items or []:
        k = it.lower()
        if k.startswith("@"):
            if un and k[1:] == un:
                out.append(it)
        elif k.isdigit():
            if sender_id is not None and int(k) == int(sender_id):
                out.append(it)
        elif k and k in low:
            out.append(it)
    return out


# ---------- اتصال هندلرها ----------
def attach(uid, client):
    from telethon import events

    async def _in(ev):
        await _safe(on_incoming(uid, client, ev))

    async def _ed(ev):
        await _safe(on_edited(uid, ev))

    async def _del(ev):
        await _safe(on_deleted(uid, ev))

    client.add_event_handler(_in, events.NewMessage(incoming=True))
    client.add_event_handler(_ed, events.MessageEdited(incoming=True))
    client.add_event_handler(_del, events.MessageDeleted())


async def _safe(coro):
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.info("extras handler: %s", e)


# ---------- پیام ورودی ----------
async def on_incoming(uid, client, ev):
    d = sb._pget(uid)
    if not any(d.get(k) for k in TOGGLES):
        return
    msg = ev.message
    if msg is None:
        return
    try:
        snd = await ev.get_sender()
    except Exception:  # noqa: BLE001
        snd = None
    sid = getattr(snd, "id", None)
    if sid is not None and sid == sb._bot_id[0]:
        return
    text = msg.raw_text or ""

    # ۰) سکوت: پیام کاربرِ ساکت‌شده — در پی‌وی فقط از سمت خودت پاک می‌شود؛ بقیهٔ امکانات هم نادیده‌اش می‌گیرند
    if d.get("mu_on") and sid is not None and str(sid) in (d.get("mu_ids") or {}):
        if ev.is_private:
            try:
                await client.delete_messages(ev.chat_id, [msg.id], revoke=False)
            except Exception as e:  # noqa: BLE001
                logger.info("extras mute delete %s: %s", uid, e)
        return

    # ۲) حافظهٔ پیام‌ها برای حذف/ویرایش (فقط چت‌های خصوصی)
    if d.get("del_on") and ev.is_private:
        c = _cache.setdefault(uid, OrderedDict())
        c[msg.id] = {"chat": ev.chat_id, "name": _name(snd), "text": text, "media": _kind(msg), "ts": time.time()}
        while len(c) > CACHE_MAX:
            c.popitem(last=False)

    # ۳) ذخیرهٔ خودکار مدیای تایمردار
    if d.get("ttl_on") and getattr(getattr(msg, "media", None), "ttl_seconds", None):
        ok = await _save_media(client, msg, "me", f"⏱ مدیای تایمردار از {_name(snd)}" + (f"\n{text}" if text else ""))
        if not ok:
            await _notify(uid, f"⚠️ مدیای تایمردار از {_name(snd)} رسید ولی ذخیره نشد.")

    # ۱) پاسخ خودکار
    if d.get("ar_on") and ev.is_private and snd is not None and not getattr(snd, "bot", False) and sid != 777000:
        now = time.time()
        seen = _ar_seen.setdefault(uid, {})
        if now - seen.get(sid, 0) >= AR_COOLDOWN:
            hist = [t for t in _ar_hist.get(uid, []) if now - t < 3600]
            if len(hist) < AR_MAX_PER_HOUR:
                seen[sid] = now
                hist.append(now)
                _ar_hist[uid] = hist
                if len(seen) > 5000:
                    for k in sorted(seen, key=seen.get)[:1000]:
                        seen.pop(k, None)
                await asyncio.sleep(random.uniform(2, 5))
                await client.send_message(ev.chat_id, (d.get("ar_text") or DEFAULT_AR)[:500])

    # ۴) منشن‌گیر
    if d.get("mn_on") and ev.is_group and getattr(msg, "mentioned", False):
        key = (uid, ev.chat_id, msg.id)
        if key not in _mn_seen:
            _mn_seen[key] = time.time()
            if len(_mn_seen) > 3000:
                _mn_seen.clear()
            try:
                chat = await ev.get_chat()
            except Exception:  # noqa: BLE001
                chat = None
            link = _link(chat, msg.id)
            await _notify(uid, f"📣 تگ شدی\n👥 گروه: {_name(chat)}\n👤 از: {_name(snd)}\n💬 {text[:300] or '[' + (_kind(msg) or 'بدون متن') + ']'}"
                          + (f"\n🔗 {link}" if link else ""))

    # ۹) ناظر
    items = d.get("wl_items") or []
    if d.get("wl_on") and items:
        hits = match_watch(items, text, sid, getattr(snd, "username", None))
        if hits:
            now = time.time()
            fresh = [h for h in hits if now - _wl_seen.get((uid, ev.chat_id, h), 0) >= WL_COOLDOWN]
            for h in fresh:
                _wl_seen[(uid, ev.chat_id, h)] = now
            if len(_wl_seen) > 3000:
                _wl_seen.clear()
            if fresh:
                try:
                    chat = await ev.get_chat()
                except Exception:  # noqa: BLE001
                    chat = None
                link = _link(chat, msg.id)
                await _notify(uid, f"👁 ناظر: {'، '.join(fresh)}\n💬 چت: {_name(chat)}\n👤 از: {_name(snd)}\n📝 {text[:300] or '[' + (_kind(msg) or 'بدون متن') + ']'}"
                              + (f"\n🔗 {link}" if link else ""))


# ---------- ویرایش و حذف ----------
async def on_edited(uid, ev):
    if not sb._pget(uid).get("del_on") or not ev.is_private:
        return
    c = _cache.get(uid)
    rec = c.get(ev.message.id) if c else None
    new = ev.message.raw_text or ""
    if rec and rec["text"] != new:
        old = rec["text"]
        rec["text"] = new
        await _notify(uid, f"✏️ پیام ویرایش شد\n👤 از: {rec['name']}\n⬅️ قبل: {old[:500] or '[بدون متن]'}\n➡️ بعد: {new[:500] or '[بدون متن]'}")


async def on_deleted(uid, ev):
    if not sb._pget(uid).get("del_on"):
        return
    c = _cache.get(uid)
    if not c:
        return
    now = time.time()
    out = []
    for mid in ev.deleted_ids or []:
        rec = c.get(mid)
        if not rec:
            continue
        if ev.chat_id and rec["chat"] != ev.chat_id:
            continue
        c.pop(mid, None)
        if now - rec["ts"] <= CACHE_TTL:
            out.append(rec)
    for rec in out[:10]:
        body = rec["text"] or (f"[{rec['media']}]" if rec["media"] else "[بدون متن]")
        await _notify(uid, f"🗑 پیام حذف شد\n👤 از: {rec['name']}\n💬 {body[:800]}" + (f"\n📎 همراه با {rec['media']}" if rec["media"] and rec["text"] else ""))
    if len(out) > 10:
        await _notify(uid, f"🗑 و {len(out) - 10} پیام حذف‌شدهٔ دیگر.")


# ---------- ذخیرهٔ مدیا ----------
async def _save_media(client, msg, dest, caption):
    try:
        data = await client.download_media(msg, file=bytes)
        if not data:
            return False
        ext = getattr(getattr(msg, "file", None), "ext", None) or ".bin"
        bio = io.BytesIO(data)
        bio.name = "media" + ext
        await client.send_file(dest, bio, caption=caption[:1000])
        return True
    except Exception as e:  # noqa: BLE001
        logger.info("extras save media: %s", e)
        return False


async def save_replied(uid, ev):
    """دستور .ذخیره (ریپلای روی مدیا) → مدیا به Saved Messages می‌رود."""
    client = sb._clients.get(uid)
    if not client or not ev.is_reply:
        return "روی مدیای موردنظر ریپلای کن و بنویس .ذخیره"
    r = await ev.get_reply_message()
    if not r or not getattr(r, "media", None):
        return "پیام ریپلای‌شده مدیا ندارد."
    ok = await _save_media(client, r, "me", "💾 ذخیره‌شده با .ذخیره")
    return "✅ توی Saved Messages ذخیره شد." if ok else "❌ ذخیره نشد؛ احتمالاً مدیا قبلاً منقضی یا باز شده."


# ---------- پنل ----------
def _st(d, k):
    return "روشن" if d.get(k) else "خاموش"


def more_panel(uid, page=1):
    """«امکانات بیشتر»؛ صفحهٔ ۱: امکانات قبلی — صفحهٔ ۲: سکوت، شهر اذان و راهنمای ابزارها."""
    d = sb._pget(uid)
    B, KB = sb.B, sb.KB
    note = "" if uid in sb._clients else "⚠️ اکانت وصل نیست؛ این امکانات بعد از اتصال کار می‌کنن.\n\n"

    def t(k, label):
        return B(f"{label}: {_st(d, k)}", callback_data=f"self:mt:{k}:{page}", style="success" if d.get(k) else "primary")

    if page == 2:
        mu = d.get("mu_ids") or {}
        tx = (note + "› امکانات بیشتر (۲/۲)\n\n"
              f"🔇 سکوت: {_st(d, 'mu_on')} — {len(mu)} نفر؛ پیام‌های جدیدشان در پی‌وی از سمت تو پاک می‌شود (.سکوت با ریپلای)\n"
              f"🕌 شهر پیش‌فرض اذان: {d.get('city') or 'تهران'}\n"
              "🧰 ابزارها: .حساب  .قیمت  .تاریخ  .اذان  .کوتاه  .استوری  .بلاک")
        kb = KB([
            [t("mu_on", "سکوت"), B("مدیریت سکوت", callback_data="self:mu", style="primary")],
            [B("شهر اذان: " + (d.get("city") or "تهران"), callback_data="self:city", style="primary"),
             B("راهنمای ابزارها", callback_data="self:thelp", style="primary")],
            [B("◀ صفحهٔ قبل", callback_data="self:more:1", style="primary"),
             B("بازگشت", callback_data="self:home", style="primary")],
        ])
        return tx[:1000], kb

    wl = d.get("wl_items") or []
    tx = (note + "› امکانات بیشتر (۱/۲)\n\n"
          f"🤖 پاسخ خودکار: {_st(d, 'ar_on')} — به پی‌وی‌ها (هر نفر حداکثر هر ۶ ساعت یک‌بار) جواب می‌ده\n"
          f"🗑 حذف/ویرایش: {_st(d, 'del_on')} — پیام پاک‌شده یا ویرایش‌شدهٔ پی‌وی‌ها رو برات می‌فرسته\n"
          f"⏱ مدیای تایمردار: {_st(d, 'ttl_on')} — عکس/ویدیوی یک‌بارمصرف خودکار توی Saved Messages ذخیره می‌شه (دستی: ریپلای + .ذخیره)\n"
          f"📣 منشن‌گیر: {_st(d, 'mn_on')} — هر تگ توی گروه‌ها با لینک پیام خبرت می‌کنه\n"
          f"👁 ناظر: {_st(d, 'wl_on')} — {len(wl)} مورد (کلمه، @یوزرنیم یا آیدی عددی)")
    kb = KB([
        [t("ar_on", "پاسخ خودکار"), B("متن پاسخ", callback_data="self:ar_text", style="primary")],
        [t("del_on", "حذف/ویرایش"), t("ttl_on", "مدیای تایمردار")],
        [t("mn_on", "منشن‌گیر"), t("wl_on", "ناظر")],
        [B("مدیریت ناظر", callback_data="self:wl", style="primary")],
        [B("صفحهٔ بعد ▶", callback_data="self:more:2", style="success")],
        [B("بازگشت", callback_data="self:home", style="primary")],
    ])
    return tx[:1000], kb


def wl_panel(uid):
    d = sb._pget(uid)
    items = d.get("wl_items") or []
    B, KB = sb.B, sb.KB
    tx = "› مدیریت ناظر\n\n" + (
        "موردی ثبت نشده.\nکلمه، @یوزرنیم یا آیدی عددی اضافه کن؛ هر وقت توی هر چتی دیده بشه خبرت می‌کنم."
        if not items else "برای حذف، روی هر مورد بزن:") + f"\n(حداکثر {WL_MAX} مورد)"
    rows = [[B(f"🗑 {it[:40]}", callback_data=f"self:wl_del:{i}", style="danger")] for i, it in enumerate(items)]
    if len(items) < WL_MAX:
        rows.append([B("افزودن مورد", callback_data="self:wl_add", style="success")])
    rows.append([B("بازگشت", callback_data="self:more", style="primary")])
    return tx, KB(rows)


def mu_panel(uid):
    d = sb._pget(uid)
    ids = d.get("mu_ids") or {}
    B, KB = sb.B, sb.KB
    tx = ("› مدیریت سکوت\n\n"
          + ("کسی ساکت نشده.\nروی پیام کاربر ریپلای کن و بنویس .سکوت، یا با دکمهٔ زیر اضافه کن."
             if not ids else "برای برداشتن سکوت، روی هر مورد بزن:")
          + f"\n(حداکثر {MU_MAX} نفر)\n\n"
          "⚠️ در پی‌وی پیام‌های جدیدشان فقط از سمت خودت پاک می‌شود (طرف مقابل چیزی نمی‌بیند). "
          "در گروه‌ها تلگرام اجازهٔ حذف پیام دیگران را نمی‌دهد؛ فقط اعلان‌های سلف (منشن‌گیر/ناظر) برایشان قطع می‌شود.")
    rows = [[B(f"🔇 {name[:30]}", callback_data=f"self:mu_del:{tid}", style="danger")] for tid, name in ids.items()]
    if len(ids) < MU_MAX:
        rows.append([B("افزودن کاربر", callback_data="self:mu_add", style="success")])
    rows.append([B("بازگشت", callback_data="self:more:2", style="primary")])
    return tx[:1000], KB(rows)


async def handle_cb(uid, a, p, qm, context):
    ud = context.user_data
    B, KB = sb.B, sb.KB
    if a == "more":
        page = int(p[2]) if len(p) > 2 and p[2].isdigit() else 1
        tx, kb = more_panel(uid, 2 if page == 2 else 1)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "mt":
        key = p[2] if len(p) > 2 else ""
        page = int(p[3]) if len(p) > 3 and p[3].isdigit() else 1
        if key in TOGGLES:
            d = sb._pget(uid)
            d[key] = not bool(d.get(key))
            if key == "ar_on" and d[key] and not d.get("ar_text"):
                d["ar_text"] = DEFAULT_AR
            sb._pput(uid, d)
        tx, kb = more_panel(uid, 2 if page == 2 else 1)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "ar_text":
        ud["self_st"] = {"step": "ar_text"}
        cur = sb._pget(uid).get("ar_text") or DEFAULT_AR
        await context.bot.send_message(uid, f"متن فعلی:\n{cur}\n\nمتن جدید پاسخ خودکار رو بفرست (حداکثر ۵۰۰ حرف). برای لغو بنویس «لغو».")
    elif a == "wl":
        tx, kb = wl_panel(uid)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "wl_add":
        ud["self_st"] = {"step": "wl_add"}
        await context.bot.send_message(uid, "کلمه، @یوزرنیم یا آیدی عددی رو بفرست (چندتا رو با خط جدید یا کاما جدا کن). برای لغو بنویس «لغو».")
    elif a == "wl_del":
        d = sb._pget(uid)
        items = d.get("wl_items") or []
        try:
            items.pop(int(p[2]))
        except Exception:  # noqa: BLE001
            pass
        d["wl_items"] = items
        sb._pput(uid, d)
        tx, kb = wl_panel(uid)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "mu":
        tx, kb = mu_panel(uid)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "mu_add":
        ud["self_st"] = {"step": "mu_add"}
        await context.bot.send_message(uid, "آیدی عددی یا @یوزرنیم کاربر رو بفرست (چندتا رو با خط جدید یا کاما جدا کن). "
                                            "برای @یوزرنیم باید اکانت سلف وصل باشه. برای لغو بنویس «لغو».")
    elif a == "mu_del":
        d = sb._pget(uid)
        ids = d.get("mu_ids") or {}
        ids.pop(p[2] if len(p) > 2 else "", None)
        d["mu_ids"] = ids
        sb._pput(uid, d)
        tx, kb = mu_panel(uid)
        await qm.edit_text(tx, reply_markup=kb)
    elif a == "city":
        ud["self_st"] = {"step": "city"}
        await context.bot.send_message(uid, "اسم شهر رو بفرست؛ شهرهای پشتیبانی‌شده:\n" + "، ".join(tools.CITY_NAMES)
                                       + "\n\nبرای لغو بنویس «لغو».")
    elif a == "thelp":
        await qm.edit_text(TOOLS_HELP, reply_markup=KB([[B("بازگشت", callback_data="self:more:2", style="primary")]]))


async def _mu_add_text(uid, text):
    """آیدی عددی یا @یوزرنیم‌های متن را به لیست سکوت اضافه می‌کند؛ تعداد اضافه‌شده را برمی‌گرداند."""
    from telethon.tl.types import User
    d = sb._pget(uid)
    ids = d.get("mu_ids") or {}
    client = sb._clients.get(uid)
    added = 0
    for raw in re.split(r"[,\n،]+", text or ""):
        x = sb.fa2en(raw).strip()
        if not x or len(ids) >= MU_MAX:
            continue
        tid, name = None, x[:40]
        try:
            if x.lstrip("@").isdigit():
                tid = int(x.lstrip("@"))
                if client:
                    try:
                        ent = await asyncio.wait_for(client.get_entity(tid), 10)
                        name = _name(ent)[:40]
                    except Exception:  # noqa: BLE001
                        pass
            elif client and re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,31}", x):
                ent = await asyncio.wait_for(client.get_entity(x.lstrip("@")), 10)
                if isinstance(ent, User):
                    tid, name = ent.id, _name(ent)[:40]
        except Exception as e:  # noqa: BLE001
            logger.info("extras mu_add resolve %s: %s", uid, e)
        if tid is None or tid in (uid, sb._bot_id[0], 777000) or str(tid) in ids:
            continue
        ids[str(tid)] = name
        added += 1
    d["mu_ids"] = ids
    if added:
        d["mu_on"] = True
    sb._pput(uid, d)
    return added


async def handle_text(uid, st, text, msg, context):
    step = st.get("step")
    if text in ("لغو", "/cancel"):
        await msg.reply_text("لغو شد.")
        return
    d = sb._pget(uid)
    panel = (more_panel, (uid,))
    if step == "ar_text":
        d["ar_text"] = text[:500]
        sb._pput(uid, d)
        await msg.reply_text("✅ متن پاسخ خودکار ذخیره شد.")
    elif step == "wl_add":
        items = d.get("wl_items") or []
        raw = [x.strip() for x in text.replace("،", ",").replace("\n", ",").split(",")]
        added = 0
        for x in raw:
            x = x.strip()[:40]
            if not x or x.lower() in [i.lower() for i in items] or len(items) >= WL_MAX:
                continue
            items.append(x)
            added += 1
        d["wl_items"] = items
        if added:
            d["wl_on"] = True
        sb._pput(uid, d)
        await msg.reply_text(f"✅ {added} مورد اضافه شد." if added else "موردی اضافه نشد (تکراری، خالی یا سقف ۱۰ مورد).")
    elif step == "mu_add":
        added = await _mu_add_text(uid, text)
        await msg.reply_text(f"✅ {added} نفر ساکت شد." if added
                             else "موردی اضافه نشد (پیدا نشد، تکراری، سقف پر، یا اکانت سلف وصل نیست).")
        panel = (mu_panel, (uid,))
    elif step == "city":
        name = tools.find_city(text)
        if name:
            d["city"] = name
            sb._pput(uid, d)
            await msg.reply_text(f"✅ شهر پیش‌فرض اذان: {name}")
        else:
            await msg.reply_text("این شهر پشتیبانی نمی‌شه؛ یکی از این‌ها رو بنویس:\n" + "، ".join(tools.CITY_NAMES))
        panel = (more_panel, (uid, 2))
    tx, kb = panel[0](*panel[1])
    await msg.reply_text(tx, reply_markup=kb)


# ---------- دستورهای ابزار و سکوت/بلاک (از چت‌ها با نقطه) ----------
def _rate_ok(uid):
    now = time.time()
    h = [t for t in _tool_hist.get(uid, []) if now - t < 60]
    if len(h) >= TOOL_PER_MIN:
        _tool_hist[uid] = h
        return False
    h.append(now)
    _tool_hist[uid] = h
    return True


async def _target(ev):
    """هدف دستور سکوت/بلاک: فرستندهٔ پیامِ ریپلای‌شده؛ یا در پی‌وی، طرف گفتگو. → (entity, input_peer) یا (None, None)."""
    from telethon.tl.types import User
    if ev.is_reply:
        r = await ev.get_reply_message()
        if r is not None and not r.out:
            snd = await r.get_sender()
            if isinstance(snd, User):
                return snd, await r.get_input_sender()
    if ev.is_private:
        chat = await ev.get_chat()
        if isinstance(chat, User):
            return chat, await ev.get_input_chat()
    return None, None


_NEED_TARGET = "روی پیام یه کاربر ریپلای کن (توی پی‌وی هم می‌تونی بدون ریپلای بنویسی)."


async def _cmd_mute(uid, ev, on):
    ent, _ = await _target(ev)
    if ent is None:
        return _NEED_TARGET, False
    tid = ent.id
    if tid in (uid, sb._bot_id[0], 777000):
        return "نمی‌شه این حساب رو ساکت کرد.", False
    d = sb._pget(uid)
    ids = d.get("mu_ids") or {}
    name = _name(ent)[:40]
    if on:
        if str(tid) not in ids and len(ids) >= MU_MAX:
            return f"سقف {MU_MAX} نفر پُره؛ از پنل ← امکانات بیشتر ← مدیریت سکوت یکی رو بردار.", False
        ids[str(tid)] = name
        d["mu_ids"], d["mu_on"] = ids, True
        sb._pput(uid, d)
        return f"🔇 «{name}» ساکت شد؛ پیام‌های جدیدش توی پی‌وی از سمت تو پاک می‌شه. برداشتن: .سکوت خاموش", False
    if ids.pop(str(tid), None) is None:
        return f"«{name}» توی لیست سکوت نبود.", False
    d["mu_ids"] = ids
    sb._pput(uid, d)
    return f"🔔 سکوت «{name}» برداشته شد.", False


async def _cmd_block(uid, ev, on):
    client = sb._clients.get(uid)
    ent, inp = await _target(ev)
    if client is None or ent is None or inp is None:
        return _NEED_TARGET, False
    if ent.id in (uid, sb._bot_id[0], 777000):
        return "نمی‌شه این حساب رو بلاک کرد.", False
    from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
    await client(BlockRequest(id=inp) if on else UnblockRequest(id=inp))
    name = _name(ent)[:40]
    return (f"⛔️ «{name}» بلاک شد. برداشتن: .رفع بلاک" if on else f"✅ بلاک «{name}» برداشته شد."), False


async def _reply_text(ev):
    if ev.is_reply:
        r = await ev.get_reply_message()
        if r is not None:
            return r.raw_text or "", getattr(r, "entities", None)
    return "", None


async def _dispatch(uid, ev, cmd, arg):
    """→ (متن، نگه‌داشتن پیام). نگه‌داشتن=True یعنی جواب بعد از ۱۰ ثانیه پاک نشود."""
    if cmd == "mute":
        return await _cmd_mute(uid, ev, on=norm_arg(arg) not in ("خاموش", "off", "غیرفعال", "حذف"))
    if cmd == "unmute":
        return await _cmd_mute(uid, ev, on=False)
    if cmd == "block":
        return await _cmd_block(uid, ev, on=True)
    if cmd == "unblock":
        return await _cmd_block(uid, ev, on=False)
    if cmd == "undo":
        what = norm_arg(arg)
        if what in ("سکوت", "mute"):
            return await _cmd_mute(uid, ev, on=False)
        if what in ("بلاک", "block"):
            return await _cmd_block(uid, ev, on=False)
        return "مثل: .رفع سکوت   یا   .رفع بلاک", False

    if cmd == "calc":
        expr = arg
        if not expr.strip():
            expr = (await _reply_text(ev))[0]
        if not expr.strip():
            return "🧮 مثل: .حساب 25*4+10   (یا ریپلای روی پیامی که عبارت داره)", False
        try:
            e, res = tools.calc(expr)
        except tools.CalcError as ex:
            return f"❌ {ex}\n🧮 مثل: .حساب (12+8)*3/2   |   .حساب sqrt(144)", False
        return f"🧮 {e} = {res}", True

    if cmd == "price":
        try:
            return await tools.price_text(arg), True
        except Exception as e:  # noqa: BLE001
            logger.info("extras price: %s", e)
            return "❌ منبع قیمت الان در دسترس نیست؛ چند دقیقهٔ دیگه دوباره امتحان کن.", False

    if cmd == "date":
        return tools.date_text(arg), True

    if cmd == "prayer":
        d = sb._pget(uid)
        want = arg.strip() or d.get("city") or "تهران"
        if not tools.find_city(want):
            return "این شهر پشتیبانی نمی‌شه. شهرها:\n" + "، ".join(tools.CITY_NAMES), False
        try:
            return await tools.prayer_text(want), True
        except Exception as e:  # noqa: BLE001
            logger.info("extras prayer: %s", e)
            return "❌ سرویس اوقات شرعی الان در دسترس نیست؛ بعداً دوباره امتحان کن.", False

    if cmd == "short":
        text, ents = arg, None
        urls = tools.find_urls(text)
        if not urls:
            text, ents = await _reply_text(ev)
            urls = tools.find_urls(text, ents)
        if not urls:
            return "🔗 مثل: .کوتاه https://example.com/very/long/link   (یا ریپلای روی پیام لینک‌دار)", False
        lines = []
        for u in urls:
            try:
                lines.append(await tools.shorten(u))
            except Exception as e:  # noqa: BLE001
                logger.info("extras shorten: %s", e)
                lines.append("❌ کوتاه نشد: " + (u[:40] + "…" if len(u) > 40 else u))
        return "🔗 لینک کوتاه:\n" + "\n".join(lines), True

    if cmd == "story":
        client = sb._clients.get(uid)
        if client is None:
            return "اکانت سلف وصل نیست.", False
        return await tools.story_save(client, ev, arg), False
    return None, False


def norm_arg(s):
    return sb.norm(s)


async def handle_cmd(uid, ev, cmd, arg):
    """نقطهٔ ورود دستورهای نقطه‌ای این فایل؛ از selfbot._handle_dot صدا زده می‌شود."""
    if not _rate_ok(uid):
        await sb._say(uid, ev, "⏳ دستورها پشت‌سرهم زیاد شد؛ یه دقیقه صبر کن.")
        return
    try:
        out, keep = await _dispatch(uid, ev, cmd, arg)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.info("extras cmd %s: %s", cmd, e)
        out, keep = "❌ انجام نشد؛ دوباره امتحان کن.", False
    if out:
        await sb._say(uid, ev, out, keep=keep)
