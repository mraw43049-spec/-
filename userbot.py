"""
ارسال خودکار از اکانت شخصی (Telethon)
هر N دقیقه (پیش‌فرض ۱۵) یک متن ثابت به یک چت/ربات می‌فرسته، منتظر جواب می‌مونه و یکی از دکمه‌های جواب رو می‌زنه.

Variables در Railway:
  API_ID, API_HASH      ← از my.telegram.org
  USERBOT_SETUP_KEY     ← یه رمز دلخواه، فقط برای باز کردن صفحهٔ ورود (/userbot/setup)
بعد از ورود، همهٔ تنظیمات با دستور توی خود تلگرام انجام می‌شه: «.پنل» بنویس.
اختیاری (مقدار پیش‌فرض؛ با پنل عوض می‌شن): TARGET_CHAT, MESSAGE_TEXT, INTERVAL_MIN=15,
  BUTTON_MODE=random|first|last|text|none, BUTTON_TEXT, REPLY_WAIT_SEC=20, TG_SESSION

اگه API_ID/API_HASH یا ورود نباشه این بخش کلاً خاموش می‌مونه و به بقیهٔ ربات کاری نداره.
"""
import asyncio
import hmac
import html as _html
import logging
import os
import random
import threading
import time
from urllib.parse import parse_qs

log = logging.getLogger("userbot")

_ENGINE = None


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


# ---------------- ذخیرهٔ سشن در دیتابیس ----------------
def configure(engine):
    """جدول ذخیرهٔ سشن رو می‌سازه و engine رو نگه می‌داره."""
    global _ENGINE
    _ENGINE = engine
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS userbot_session ("
                "id INTEGER PRIMARY KEY, session TEXT NOT NULL, updated_at DOUBLE PRECISION)"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS userbot_settings (k TEXT PRIMARY KEY, v TEXT)"))
    except Exception:  # noqa: BLE001
        log.exception("userbot: ساخت جدول سشن ناموفق بود")


def _db_get():
    if _ENGINE is None:
        return ""
    try:
        from sqlalchemy import text
        with _ENGINE.begin() as conn:
            row = conn.execute(text("SELECT session FROM userbot_session WHERE id = 1")).first()
        return (row[0] or "").strip() if row else ""
    except Exception:  # noqa: BLE001
        log.exception("userbot: خوندن سشن از دیتابیس ناموفق بود")
        return ""


def _db_set(sess):
    from sqlalchemy import text
    with _ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO userbot_session (id, session, updated_at) VALUES (1, :s, :t) "
            "ON CONFLICT (id) DO UPDATE SET session = :s, updated_at = :t"), {"s": sess, "t": time.time()})


def _session():
    return _env("TG_SESSION") or _db_get()


def _enabled():
    return all(_env(k) for k in ("API_ID", "API_HASH")) and bool(_session())


def _pick(buttons, mode, text):
    """buttons: لیست دکمه‌ها (بدون دکمه‌های لینک)."""
    if not buttons:
        return None
    if mode == "first":
        return buttons[0]
    if mode == "last":
        return buttons[-1]
    if mode == "text" and text:
        for b in buttons:
            if text in (b.text or ""):
                return b
        return None
    return random.choice(buttons)


async def _resolve(client, target):
    """TARGET_CHAT می‌تونه @یوزرنیم، آیدی عددی (مثل -1001234567890) یا اسم دقیق گروه توی لیست چت‌هات باشه."""
    t = target.strip()
    if t.startswith("https://t.me/") or t.startswith("t.me/"):
        t = "@" + t.rstrip("/").split("/")[-1]
    if t.lstrip("-").isdigit():
        await client.get_dialogs(limit=None)        # تا تلگرام گروه‌ها رو بشناسه
        return await client.get_entity(int(t))
    if t.startswith("@"):
        return await client.get_entity(t)
    # اسم گروه: اول مطابقت دقیق، بعد شامل‌شدن
    names = []
    contains = None
    async for d in client.iter_dialogs():
        nm = (d.name or "").strip()
        names.append(nm)
        if nm.lower() == t.lower():
            return d.entity
        if contains is None and t.lower() in nm.lower():
            contains = d.entity
    if contains is not None:
        return contains
    log.error("userbot: چتی با اسم «%s» پیدا نشد. چت‌های موجود: %s", t, " | ".join(names[:25]))
    raise RuntimeError("TARGET_CHAT پیدا نشد")


# ---------------- تنظیمات قابل‌تغییر با دستور (توی دیتابیس) ----------------
_CFG_CACHE = {"t": 0.0, "d": {}}


def _cfg_all(force=False):
    if not force and time.time() - _CFG_CACHE["t"] < 3:
        return _CFG_CACHE["d"]
    d = {}
    if _ENGINE is not None:
        try:
            from sqlalchemy import text
            with _ENGINE.begin() as conn:
                for k, v in conn.execute(text("SELECT k, v FROM userbot_settings")).all():
                    d[k] = v
        except Exception:  # noqa: BLE001
            log.exception("userbot: خوندن تنظیمات ناموفق بود")
            return _CFG_CACHE["d"]
    _CFG_CACHE.update(t=time.time(), d=d)
    return d


def _cfg_set(k, v):
    if _ENGINE is None:
        return
    from sqlalchemy import text
    with _ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO userbot_settings (k, v) VALUES (:k, :v) "
            "ON CONFLICT (k) DO UPDATE SET v = :v"), {"k": k, "v": str(v)})
    _cfg_all(force=True)


def _settings():
    db = _cfg_all()
    env_target, env_text = _env("TARGET_CHAT"), _env("MESSAGE_TEXT")
    try:
        interval = float(db.get("interval") or _env("INTERVAL_MIN", "15"))
    except ValueError:
        interval = 15.0
    act = db.get("active")
    if act is None:
        act = "1" if (env_target and env_text) else "0"
    try:
        last = float(db.get("last_sent") or 0)
    except ValueError:
        last = 0.0
    try:
        wait = max(3.0, float(_env("REPLY_WAIT_SEC", "20")))
    except ValueError:
        wait = 20.0
    return {
        "target": db.get("target") or env_target,
        "target_name": db.get("target_name", ""),
        "text": db.get("text") or env_text,
        "interval": max(1.0, interval),
        "mode": (db.get("mode") or _env("BUTTON_MODE", "random")).lower(),
        "btn_text": db.get("btn_text") or _env("BUTTON_TEXT"),
        "active": act == "1",
        "last": last,
        "wait": wait,
    }


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MODE_NAMES = {"random": "تصادفی", "first": "اولین دکمه", "last": "آخرین دکمه", "none": "هیچ (فقط پیام)", "text": "دکمه‌ای با متن مشخص"}
_MODE_ALIAS = {"random": "random", "تصادفی": "random", "first": "first", "اولی": "first", "اول": "first",
               "last": "last", "آخری": "last", "آخر": "last", "none": "none", "هیچ": "none", "بدون": "none", "نه": "none"}
_CMDS = {"پنل", "panel", "گروه", "کلمه", "فاصله", "دکمه", "روشن", "خاموش", "الان"}


def _panel_text(cfg):
    if cfg["active"] and cfg["target"] and cfg["text"]:
        left = max(0.0, cfg["last"] + cfg["interval"] * 60 - time.time())
        state = "روشن ✅ (ارسال بعدی تا %d دقیقه دیگه)" % round(left / 60) if cfg["last"] else "روشن ✅ (اولین ارسال به‌زودی)"
    else:
        state = "خاموش ⛔"
    mode = _MODE_NAMES.get(cfg["mode"], cfg["mode"])
    if cfg["mode"] == "text" and cfg["btn_text"]:
        mode += " «%s»" % cfg["btn_text"]
    target = cfg["target_name"] or cfg["target"] or "تنظیم نشده"
    return (
        "🎛 پنل ارسال خودکار\n\n"
        "وضعیت: %s\nگروه مقصد: %s\nکلمه: %s\nفاصله: هر %g دقیقه\nدکمه: %s\n\n"
        "دستورها (هر چتی بنویس؛ جوابش توی Saved Messages می‌آد):\n"
        ".گروه ← داخل خود گروه بنویس تا همون گروه مقصد بشه\n"
        ".گروه اسم-گروه ← یا با اسم/یوزرنیم/آیدی\n"
        ".کلمه سلام ← کلمهٔ ارسالی\n"
        ".فاصله 15 ← هر چند دقیقه\n"
        ".دکمه تصادفی | اولی | آخری | هیچ ← کدوم دکمه زده بشه\n"
        ".دکمه متن جایزه ← دکمه‌ای که متنش این رو داره\n"
        ".روشن / .خاموش\n"
        ".الان ← همین الان یکبار بفرست"
    ) % (state, target, cfg["text"] or "تنظیم نشده", cfg["interval"], mode)


async def _handle_cmd(client, event, me_id, cmd, arg, state):
    cfg = _settings()
    if cmd in ("پنل", "panel"):
        return _panel_text(cfg)
    if cmd == "گروه":
        if not arg:
            if event.chat_id == me_id:
                return "⚠️ این دستور رو داخل خود گروه بنویس؛ یا با اسم: .گروه اسم-گروه"
            chat = await event.get_chat()
            name = getattr(chat, "title", None) or getattr(chat, "first_name", None) or str(event.chat_id)
            _cfg_set("target", event.chat_id)
            _cfg_set("target_name", name)
            state["entity"] = None
            return "✅ گروه مقصد: %s" % name
        try:
            ent = await _resolve(client, arg)
        except Exception:  # noqa: BLE001
            return "⚠️ چتی با این مشخصات پیدا نشد (اکانتت باید عضوش باشه). اسم دقیق یا @یوزرنیم رو بنویس."
        name = getattr(ent, "title", None) or getattr(ent, "first_name", None) or arg
        _cfg_set("target", arg)
        _cfg_set("target_name", name)
        state["entity"] = None
        return "✅ گروه مقصد: %s" % name
    if cmd == "کلمه":
        if not arg:
            return "کلمهٔ فعلی: %s" % (cfg["text"] or "تنظیم نشده")
        _cfg_set("text", arg)
        return "✅ کلمه: %s" % arg
    if cmd == "فاصله":
        try:
            v = float(arg.translate(_DIGITS).replace("،", ".").replace(",", "."))
        except ValueError:
            return "⚠️ عدد بنویس، مثل: .فاصله 15"
        if v < 1:
            return "⚠️ حداقل فاصله ۱ دقیقه‌ست."
        _cfg_set("interval", v)
        return "✅ فاصله: هر %g دقیقه" % v
    if cmd == "دکمه":
        a = arg.strip()
        if a.startswith("متن "):
            _cfg_set("mode", "text")
            _cfg_set("btn_text", a[4:].strip())
            return "✅ دکمه‌ای که متنش شامل «%s» باشه زده می‌شه" % a[4:].strip()
        m = _MODE_ALIAS.get(a.lower())
        if not m:
            return "⚠️ یکی از اینا: .دکمه تصادفی | اولی | آخری | هیچ  یا  .دکمه متن جایزه"
        _cfg_set("mode", m)
        return "✅ دکمه: %s" % _MODE_NAMES[m]
    if cmd in ("روشن", "الان"):
        if not (cfg["target"] and cfg["text"]):
            return "⚠️ اول گروه (.گروه) و کلمه (.کلمه) رو تنظیم کن."
        if cmd == "روشن":
            _cfg_set("active", "1")
        state["force"] = True
        return "✅ روشن شد؛ الان اولین پیام می‌ره" if cmd == "روشن" else "📤 همین الان می‌فرستم"
    if cmd == "خاموش":
        _cfg_set("active", "0")
        return "⛔ خاموش شد"
    return ""


async def _send_once(client, state, cfg):
    from telethon.errors import FloodWaitError  # noqa: F401  (توی حلقهٔ بیرونی گرفته می‌شه)
    if state.get("entity") is None or state.get("key") != cfg["target"]:
        state["entity"] = await _resolve(client, cfg["target"])
        state["key"] = cfg["target"]
    entity = state["entity"]
    sent = await client.send_message(entity, cfg["text"])
    _cfg_set("last_sent", time.time())
    if cfg["mode"] == "none":
        return
    loop = asyncio.get_event_loop()
    deadline = loop.time() + cfg["wait"]
    clicked = False
    while loop.time() < deadline and not clicked:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(entity, limit=6, min_id=sent.id)
        for m in msgs:
            if getattr(m, "out", False) or not getattr(m, "buttons", None):
                continue
            rep = getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None)
            if rep != sent.id and not getattr(getattr(m, "sender", None), "bot", False):
                continue            # پیام یکی از اعضای گروه؛ دکمه‌اش رو نزن
            flat = [b for row in m.buttons for b in row if not getattr(b, "url", None)]
            choice = _pick(flat, cfg["mode"], cfg["btn_text"])
            if choice is None:
                continue
            await choice.click()
            log.info("userbot: دکمهٔ «%s» زده شد", choice.text)
            clicked = True
            break
    if not clicked:
        log.warning("userbot: بعد از ارسال، پیامی با دکمه نیومد")


async def _run_once_loop():
    """True = باید دوباره تلاش بشه، False = ورود معتبر نیست (دیگه تلاش نکن)."""
    from telethon import TelegramClient, events
    from telethon.errors import FloodWaitError
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(_session()), int(_env("API_ID")), _env("API_HASH"))
    await client.connect()
    try:
        if not await client.is_user_authorized():
            log.error("userbot: سشن معتبر نیست (از تنظیمات تلگرام > دستگاه‌ها بسته شده؟)؛ دوباره از صفحهٔ /userbot/setup وارد شو.")
            return False
        me = await client.get_me()
        state = {"entity": None, "key": None, "force": False}

        @client.on(events.NewMessage(outgoing=True))
        async def _on_cmd(event):
            raw = (event.raw_text or "").strip()
            if not raw.startswith("."):
                return
            cmd, _, arg = raw[1:].partition(" ")
            cmd, arg = cmd.strip(), arg.strip()
            if cmd not in _CMDS or raw == _settings()["text"]:
                return
            try:
                reply = await _handle_cmd(client, event, me.id, cmd, arg, state)
            except Exception as e:  # noqa: BLE001
                log.exception("userbot: خطا در دستور %s", cmd)
                reply = "⚠️ خطا: %s" % str(e)[:200]
            if event.chat_id != me.id:
                try:
                    await event.delete()           # دستور توی گروه دیده نشه
                except Exception:  # noqa: BLE001
                    pass
            if reply:
                await client.send_message("me", reply)

        log.info("userbot: روشنه؛ توی تلگرام «.پنل» بنویس")
        while True:
            try:
                cfg = _settings()
                due = cfg["last"] + cfg["interval"] * 60
                go = state.pop("force", False) or (cfg["active"] and time.time() >= due)
                if go and cfg["target"] and cfg["text"]:
                    await _send_once(client, state, cfg)
            except FloodWaitError as e:
                log.warning("userbot: FloodWait %ss", e.seconds)
                await asyncio.sleep(e.seconds + 5)
            except Exception:  # noqa: BLE001
                log.exception("userbot: خطا در این دور")
                try:
                    _cfg_set("last_sent", time.time())     # تا هر ۲ ثانیه تکرار نشه
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(2)
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


# ====================== صفحهٔ ورود با مرورگر ======================
_PENDING = {}          # یک ورود در حال انجام: client, phone, hash, ts
_PENDING_TTL = 600


def _norm_phone(p):
    p = "".join(ch for ch in (p or "") if ch.isdigit() or ch == "+")
    if p.startswith("00"):
        p = "+" + p[2:]
    if p.startswith("09") and len(p) == 11:      # 09123456789 → +989123456789
        p = "+98" + p[1:]
    elif p.startswith("98") and not p.startswith("+"):
        p = "+" + p
    elif p and not p.startswith("+"):
        p = "+" + p
    return p


async def _drop_pending():
    c = _PENDING.pop("client", None)
    _PENDING.clear()
    if c is not None:
        try:
            await c.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _err_text(e):
    n = type(e).__name__
    m = {
        "PhoneNumberInvalidError": "شماره درست نیست. مثل +989123456789 بنویس.",
        "PhoneCodeInvalidError": "کد اشتباهه. دوباره بزن.",
        "PhoneCodeExpiredError": "کد منقضی شده؛ از اول شروع کن تا کد جدید بیاد.",
        "PasswordHashInvalidError": "رمز دومرحله‌ای اشتباهه.",
        "ApiIdInvalidError": "API_ID یا API_HASH اشتباهه؛ توی Variables چک کن.",
        "FloodWaitError": "تلگرام موقتاً محدود کرده؛ بعداً دوباره امتحان کن (%s ثانیه)." % getattr(e, "seconds", "؟"),
        "PhoneNumberBannedError": "این شماره توسط تلگرام مسدوده.",
    }
    return m.get(n) or ("%s: %s" % (n, str(e)[:200]))


async def step_send(phone):
    """('code'|'error', پیام)"""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    if not (_env("API_ID") and _env("API_HASH")):
        return "error", "اول API_ID و API_HASH رو توی Variables بذار."
    await _drop_pending()
    phone = _norm_phone(phone)
    if len(phone) < 8:
        return "error", "شماره درست نیست. مثل 09123456789 یا +989123456789 بنویس."
    client = TelegramClient(StringSession(), int(_env("API_ID")), _env("API_HASH"))
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as e:  # noqa: BLE001
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        log.exception("userbot setup: ارسال کد ناموفق")
        return "error", _err_text(e)
    _PENDING.update(client=client, phone=phone, hash=sent.phone_code_hash, ts=time.time())
    return "code", "کد توی خود تلگرام (چت «Telegram» با علامت تیک آبی) برات اومده."


async def _finish(client):
    sess = client.session.save()
    _db_set(sess)
    await _drop_pending()
    start_in_background()
    return "done", "وصل شد ✅ حالا توی تلگرام (هر چتی) بنویس: .پنل"


async def step_code(code):
    """('password'|'done'|'error'|'expired', پیام)"""
    from telethon.errors import SessionPasswordNeededError
    c = _PENDING.get("client")
    if c is None or time.time() - _PENDING.get("ts", 0) > _PENDING_TTL:
        await _drop_pending()
        return "expired", "زمان تموم شد یا ورود از اول شروع نشده. دوباره شماره رو بزن."
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    try:
        await c.sign_in(phone=_PENDING["phone"], code=code, phone_code_hash=_PENDING["hash"])
    except SessionPasswordNeededError:
        return "password", "این اکانت رمز دومرحله‌ای داره؛ رمزش رو بزن."
    except Exception as e:  # noqa: BLE001
        log.exception("userbot setup: ورود با کد ناموفق")
        if type(e).__name__ == "PhoneCodeExpiredError":
            await _drop_pending()
            return "expired", _err_text(e)
        return "error", _err_text(e)
    return await _finish(c)


async def step_password(pw):
    c = _PENDING.get("client")
    if c is None or time.time() - _PENDING.get("ts", 0) > _PENDING_TTL:
        await _drop_pending()
        return "expired", "زمان تموم شد. دوباره از اول شروع کن."
    try:
        await c.sign_in(password=pw or "")
    except Exception as e:  # noqa: BLE001
        log.exception("userbot setup: ورود با رمز ناموفق")
        return "error", _err_text(e)
    return await _finish(c)


_CSS = ("body{font-family:system-ui,Tahoma,sans-serif;background:#0f1424;color:#eef;margin:0;padding:18px;line-height:1.9}"
        ".c{max-width:460px;margin:0 auto;background:#1a2036;border-radius:16px;padding:20px}"
        "h2{margin:.2em 0 .6em}input{width:100%;box-sizing:border-box;padding:14px;margin:8px 0;border-radius:10px;"
        "border:1px solid #3a4568;background:#0f1424;color:#fff;font-size:18px;direction:ltr;text-align:center}"
        "button{width:100%;padding:14px;border:0;border-radius:10px;background:#3b82f6;color:#fff;font-size:17px;margin-top:6px}"
        ".m{background:#223;border-radius:10px;padding:10px;margin:10px 0}.e{background:#4a1d28}.o{background:#173a2a}small{opacity:.75}")


def _page(body):
    return ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>ورود</title>'
            '<style>' + _CSS + '</style></head><body><div class="c">' + body + '</div></body></html>')


def _form(action, key, label, field, kind="text", btn="ادامه", hint=""):
    k = _html.escape(key, quote=True)
    return ('<form method="post" action="%s"><input type="hidden" name="key" value="%s">'
            '<label>%s</label><input name="%s" type="%s" autocomplete="off" autofocus>%s'
            '<button type="submit">%s</button></form>' % (action, k, label, field, kind,
                                                          ("<small>%s</small>" % hint) if hint else "", btn))


def _msg(text, cls=""):
    return '<div class="m %s">%s</div>' % (cls, _html.escape(text))


def _home(key, note=""):
    status = "الان وصل هستی ✅" if _session() else "هنوز وارد نشدی."
    return _page("<h2>ورود اکانت 🔐</h2>" + (_msg(note, "e") if note else "") + _msg(status) +
                 _form("/userbot/send", key, "شمارهٔ تلگرامت:", "phone", "tel", "فرستادن کد",
                       "مثل 09123456789 یا +989123456789"))


def make_router(engine):
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse

    configure(engine)
    router = APIRouter()

    async def _read(request):
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "ignore")).items()}
        given = form.get("key") or request.query_params.get("key", "")
        want = _env("USERBOT_SETUP_KEY")
        ok = bool(want) and hmac.compare_digest(want.encode(), given.encode())
        return ok, given, form

    def _404():
        return HTMLResponse("Not Found", status_code=404)

    @router.get("/userbot/setup", response_class=HTMLResponse)
    async def setup_page(request: Request):
        ok, key, _f = await _read(request)
        return HTMLResponse(_home(key)) if ok else _404()

    @router.post("/userbot/send", response_class=HTMLResponse)
    async def setup_send(request: Request):
        ok, key, f = await _read(request)
        if not ok:
            return _404()
        kind, text = await step_send(f.get("phone", ""))
        if kind == "code":
            return HTMLResponse(_page("<h2>کد رو بزن</h2>" + _msg(text, "o") +
                                      _form("/userbot/code", key, "کد:", "code", "tel", "ورود",
                                            "این صفحه رو توی تلگرام برای کسی نفرست؛ کد رو همین‌جا بزن.")))
        return HTMLResponse(_home(key, text))

    @router.post("/userbot/code", response_class=HTMLResponse)
    async def setup_code(request: Request):
        ok, key, f = await _read(request)
        if not ok:
            return _404()
        kind, text = await step_code(f.get("code", ""))
        if kind == "done":
            return HTMLResponse(_page("<h2>تمام شد 🎉</h2>" + _msg(text, "o") +
                                      "<small>حالا می‌تونی USERBOT_SETUP_KEY رو از Variables پاک کنی تا این صفحه بسته بشه.</small>"))
        if kind == "password":
            return HTMLResponse(_page("<h2>رمز دومرحله‌ای</h2>" + _msg(text) +
                                      _form("/userbot/password", key, "رمز:", "password", "password", "ورود")))
        if kind == "expired":
            return HTMLResponse(_home(key, text))
        return HTMLResponse(_page("<h2>کد رو بزن</h2>" + _msg(text, "e") +
                                  _form("/userbot/code", key, "کد:", "code", "tel", "ورود")))

    @router.post("/userbot/password", response_class=HTMLResponse)
    async def setup_password(request: Request):
        ok, key, f = await _read(request)
        if not ok:
            return _404()
        kind, text = await step_password(f.get("password", ""))
        if kind == "done":
            return HTMLResponse(_page("<h2>تمام شد 🎉</h2>" + _msg(text, "o") +
                                      "<small>حالا می‌تونی USERBOT_SETUP_KEY رو از Variables پاک کنی تا این صفحه بسته بشه.</small>"))
        if kind == "expired":
            return HTMLResponse(_home(key, text))
        return HTMLResponse(_page("<h2>رمز دومرحله‌ای</h2>" + _msg(text, "e") +
                                  _form("/userbot/password", key, "رمز:", "password", "password", "ورود")))

    return router


def _thread_main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            again = loop.run_until_complete(_run_once_loop())
            if again is False:
                return
        except Exception:  # noqa: BLE001
            log.exception("userbot: قطع شد؛ ۳۰ ثانیه دیگه دوباره وصل می‌شم")
        time.sleep(30)


_started = False
_lock = threading.Lock()


def start_in_background():
    global _started
    if not _enabled():
        log.info("userbot: خاموشه (Variables کامل نیست)")
        return
    with _lock:
        if _started:
            return
        _started = True
    # اگه چند ورکر بالا بیاد، فقط یکی‌شون باید کار کنه (قفل فایل)
    try:
        import fcntl
        global _lockfile
        _lockfile = open("/tmp/userbot.lock", "w")
        fcntl.flock(_lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass
    except OSError:
        log.info("userbot: ورکر دیگه‌ای در حال اجراست")
        return
    threading.Thread(target=_thread_main, name="userbot", daemon=True).start()
