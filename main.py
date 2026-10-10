"""
بک‌اند مینی‌اپ روبی (نسخه‌ی بدون پوشه: همه‌ی فایل‌ها کنار bot.py هستن).

- پروفایل روباه (با اسکین فعال) + دکمه‌های روباه (برداشت / ارتقا / تغییر نام / جنسیت)
- لیدربرد روب‌پوینت
- منطق برداشت و ارتقا از خود bot.py استفاده می‌کنه تا دقیقاً مثل بات رفتار کنه.
"""
import asyncio
import hashlib
import hmac
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, text
import httpx

import attack_owl
from auth import extract_telegram_user, validate_init_data

try:
    from database import ChatMessage, PendingAttack, Referral, User, engine, get_session
except ImportError as e:
    raise RuntimeError("نتونستم database.py رو پیدا کنم؛ main.py باید کنار bot.py باشه.") from e

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("متغیر محیطی BOT_TOKEN ست نشده.")

app = FastAPI(title="Ruby Fox Mini App API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=800)   # صفحه و جواب‌های JSON فشرده می‌شن → لود سریع‌تر

# جدول چت‌روم اگه هنوز ساخته نشده باشه (مثلاً مینی‌اپ جدا از بات بالا بیاد) همین‌جا ساخته می‌شه.
for _tbl in (ChatMessage, PendingAttack):
    try:
        _tbl.__table__.create(bind=engine, checkfirst=True)
    except Exception as _e:  # noqa: BLE001
        print(f"[miniapp] could not create table {_tbl.__tablename__}: {_e}")


def _warm_up():
    """import سنگین education (که کتابخونه‌ی تلگرام رو می‌کشه) و bot رو قبل از اولین درخواست انجام می‌ده."""
    try:
        import education  # noqa: F401
        for t in (education.EducationProgress, education.EduUserQuestion):
            try:
                t.__table__.create(bind=engine, checkfirst=True)
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        print(f"[miniapp] warm-up education failed: {e}")
    try:
        import bot  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"[miniapp] warm-up bot failed: {e}")


@app.on_event("startup")
def _startup_warm():
    import threading
    threading.Thread(target=_warm_up, daemon=True).start()


# ---------------------------------------------------------------------------
# صفحات وب مینی‌اپ
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
@app.get("/miniapp", include_in_schema=False)
@app.get("/lobby", include_in_schema=False)
def miniapp_home():
    """نمایش رابط کاربری مینی‌اپ در دامنهٔ اصلی و مسیر /miniapp."""
    page = BASE_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="فایل index.html در کنار main.py پیدا نشد.")
    return FileResponse(page, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

@app.get("/health", include_in_schema=False)
def health_check():
    return {"ok": True, "service": "ruby-fox-miniapp"}


NO_CACHE = {"Cache-Control": "no-cache"}   # هر بار چک می‌کنه؛ اگه عوض نشده باشه ۳۰۴ می‌گیره (بدون دانلود دوباره)

# ---------------------------------------------------------------------------
# اسکین‌ها (همون کلیدهای bot.py)
# ---------------------------------------------------------------------------
SKIN_INFO = {
    "lightning": "⚡ رعد و برق",
    "ice": "❄ یخی",
    "fire": "🔥 آتشین",
    "basketball": "🏀 بسکتبالیست",
    "vampire": "🧛🏻‍♀️ خون‌آشامی",
}
FREE_SKINS = ("basketball",)


def skin_image_file(key: str, gender: str):
    if key not in SKIN_INFO or gender not in ("male", "female"):
        return None
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = BASE_DIR / f"vip_{key}_{gender}.{ext}"
        if p.exists():
            return p
    return None


def active_skins(user):
    """همون منطق vip_active_skins در bot.py"""
    owned = []
    for k in (user.fox_skin or "").split(","):
        k = k.strip()
        if k in SKIN_INFO and k not in owned:
            owned.append(k)
    for k in FREE_SKINS:
        if k not in owned:
            owned.append(k)
    raw = user.fox_skins_active
    if raw is None:
        if int(user.fox_skin_active or 0) == 1:
            return [k for k in owned if k not in FREE_SKINS]
        return []
    out = []
    for k in raw.split(","):
        k = k.strip()
        if k in owned and k not in out:
            out.append(k)
    # فقط یک اسکین فعال؛ اگر داده قدیمی خراب باشد آخرین مقدار معتبر برنده است.
    return out[-1:] if out else []


@app.get("/skin/{key}/{gender}")
def get_skin_image(key: str, gender: str):
    p = skin_image_file(key, gender)
    if not p:
        raise HTTPException(status_code=404, detail="عکس پیدا نشد.")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# عکس پروفایل تلگرام (برای لیدربرد و چت)
# ---------------------------------------------------------------------------
# تگ <img> نمی‌تونه هدر بفرسته، پس لینک عکس با امضای HMAC ساخته می‌شه (فقط بک‌اند می‌تونه لینک معتبر بسازه).
_AVATAR_SECRET = hashlib.sha256(b"avatar:" + BOT_TOKEN.encode()).digest()
_AVATAR_DIR = Path(os.environ.get("AVATAR_CACHE_DIR", "/tmp/ruby_avatars"))
_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
_AVATAR_TTL = 6 * 3600          # عکس‌ها هر ۶ ساعت یه بار از تلگرام دوباره گرفته می‌شن
_AVATAR_MISS_TTL = 30 * 60      # کاربرِ بدون عکس: ۳۰ دقیقه بعد دوباره تلاش می‌کنیم


def _avatar_sig(uid: int) -> str:
    return hmac.new(_AVATAR_SECRET, str(int(uid)).encode(), hashlib.sha256).hexdigest()[:16]


def avatar_url(uid: int) -> str:
    return f"/api/avatar/{int(uid)}?s={_avatar_sig(uid)}"


_avatar_sem = asyncio.Semaphore(4)       # حداکثر ۴ دانلود هم‌زمان از تلگرام
_avatar_inflight: dict = {}              # جلوگیری از دانلود تکراریِ یک عکس
_avatar_client = {"c": None}


def _aclient():
    if _avatar_client["c"] is None:
        _avatar_client["c"] = httpx.AsyncClient(timeout=10)
    return _avatar_client["c"]


async def _fetch_avatar_from_telegram(uid: int):
    """عکس پروفایل رو از Bot API می‌گیره؛ اگه نداشت/بسته بود None."""
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with _avatar_sem:
        c = _aclient()
        r = (await c.get(f"{base}/getUserProfilePhotos", params={"user_id": uid, "limit": 1})).json()
        photos = (r.get("result") or {}).get("photos") or []
        if not photos or not photos[0]:
            return None
        sizes = photos[0]
        # کوچیک‌ترین سایزی که حداقل ~160px باشه تا سریع لود بشه
        pick = next((p for p in sizes if (p.get("width") or 0) >= 160), sizes[-1])
        f = (await c.get(f"{base}/getFile", params={"file_id": pick["file_id"]})).json()
        path = (f.get("result") or {}).get("file_path")
        if not path:
            return None
        img = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
        if img.status_code != 200:
            return None
        return img.content


@app.get("/api/avatar/{uid}")
async def get_avatar(uid: int, s: str = ""):
    if not hmac.compare_digest(s or "", _avatar_sig(uid)):
        raise HTTPException(status_code=403, detail="لینک نامعتبره.")
    f = _AVATAR_DIR / f"{uid}.jpg"
    miss = _AVATAR_DIR / f"{uid}.none"
    now = time.time()
    if f.exists() and now - f.stat().st_mtime < _AVATAR_TTL:
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    if miss.exists() and now - miss.stat().st_mtime < _AVATAR_MISS_TTL:
        raise HTTPException(status_code=404, detail="بدون عکس.")
    task = _avatar_inflight.get(uid)
    if task is None:
        task = asyncio.ensure_future(_fetch_avatar_from_telegram(uid))
        _avatar_inflight[uid] = task
        task.add_done_callback(lambda _t, u=uid: _avatar_inflight.pop(u, None))
    try:
        data = await asyncio.shield(task)
    except Exception:  # noqa: BLE001
        data = None
    if data:
        f.write_bytes(data)
        if miss.exists():
            miss.unlink()
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    if f.exists():  # تلگرام جواب نداد ولی نسخه‌ی قدیمی داریم
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=600"})
    miss.write_text("1")
    raise HTTPException(status_code=404, detail="بدون عکس.")


# ---------------------------------------------------------------------------
# احراز هویت
# ---------------------------------------------------------------------------
def _auth_user(init_data: str):
    parsed = validate_init_data(init_data, BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="initData نامعتبر یا منقضی‌شده است.")
    tg_user = extract_telegram_user(parsed)
    if not tg_user or "id" not in tg_user:
        raise HTTPException(status_code=401, detail="اطلاعات کاربر در initData پیدا نشد.")
    return tg_user


# ---------------------------------------------------------------------------
# عضویت اجباری (دقیقاً همون کانال‌های بات: REQUIRED_CHANNEL و REQUIRED_CHANNEL_2)
# ---------------------------------------------------------------------------
def _load_required_channels():
    try:
        from config import REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL, REQUIRED_CHANNEL_2, REQUIRED_CHANNEL_2_URL
        raw = [(REQUIRED_CHANNEL, REQUIRED_CHANNEL_URL, "📢 عضویت در کانال اصلی"),
               (REQUIRED_CHANNEL_2, REQUIRED_CHANNEL_2_URL, "🎁 عضویت در کانال هدایا")]
    except Exception:  # noqa: BLE001  (اگه config.py کنار این فایل نبود از متغیرهای محیطی می‌خونیم)
        raw = [(os.environ.get("REQUIRED_CHANNEL", ""), os.environ.get("REQUIRED_CHANNEL_URL", ""), "📢 عضویت در کانال اصلی"),
               (os.environ.get("REQUIRED_CHANNEL_2", ""), os.environ.get("REQUIRED_CHANNEL_2_URL", ""), "🎁 عضویت در کانال هدایا")]
    out = []
    for ch, url, label in raw:
        ch = str(ch or "").strip()
        if not ch:
            continue
        url = str(url or "").strip()
        if not url and ch.startswith("@"):
            url = "https://t.me/" + ch[1:]
        out.append({"chat": ch, "url": url, "label": label})
    return out


def _load_admin_ids():
    try:
        from config import ADMIN_IDS
        return {int(x) for x in ADMIN_IDS}
    except Exception:  # noqa: BLE001
        return {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}


REQUIRED_CHANNELS = _load_required_channels()
ADMIN_ID_SET = _load_admin_ids()
if not REQUIRED_CHANNELS:
    print("[miniapp] WARNING: هیچ کانال اجباری‌ای پیدا نشد (REQUIRED_CHANNEL خالیه)؛ عضویت چک نمی‌شه!")

_TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_tg_http = httpx.Client(timeout=8, limits=httpx.Limits(max_connections=30, max_keepalive_connections=10))
_MEMBER_OK_TTL = 90          # عضو بود: ۹۰ ثانیه دوباره چک نمی‌کنیم (سریع و بدون فشار روی تلگرام)
_MEMBER_NO_TTL = 5           # عضو نبود: ۵ ثانیه (که بعد از عضویت زود وارد بشه)
_MEMBER_GRACE = 1800         # اگه تلگرام جواب نداد و تا ۳۰ دقیقه پیش عضو بود، ردش نمی‌کنیم
_member_cache: dict = {}     # uid -> (زمان چک, عضو؟)
_member_locks = [threading.Lock() for _ in range(64)]


def _is_member_of(channel: str, uid: int):
    """True/False؛ اگه تلگرام خطا داد None."""
    try:
        r = _tg_http.get(f"{_TG_API}/getChatMember", params={"chat_id": channel, "user_id": uid}).json()
    except Exception as e:  # noqa: BLE001
        print(f"[miniapp] membership check failed for {channel}: {e}")
        return None
    if not r.get("ok"):
        print(f"[miniapp] getChatMember({channel}) -> {r.get('description')}")
        # «user not found / participant invalid» یعنی عضو نیست؛ بقیه‌ی خطاها (مثلاً بات ادمین نیست) خطای واقعی‌ان
        desc = str(r.get("description") or "").lower()
        if "user not found" in desc or "participant_id_invalid" in desc:
            return False
        return None
    m = r.get("result") or {}
    return m.get("status") in ("member", "administrator", "creator") or bool(m.get("is_member"))


def membership_ok(uid: int, force: bool = False) -> bool:
    uid = int(uid)
    if uid in ADMIN_ID_SET or not REQUIRED_CHANNELS:
        return True
    now = time.time()
    hit = _member_cache.get(uid)
    if hit and not force and now - hit[0] < (_MEMBER_OK_TTL if hit[1] else _MEMBER_NO_TTL):
        return hit[1]
    with _member_locks[uid % 64]:       # چند درخواست هم‌زمانِ یک کاربر فقط یک بار از تلگرام می‌پرسن
        hit = _member_cache.get(uid)
        if hit and not force and time.time() - hit[0] < (_MEMBER_OK_TTL if hit[1] else _MEMBER_NO_TTL):
            return hit[1]
        ok, errored = True, False
        for ch in REQUIRED_CHANNELS:
            res = _is_member_of(ch["chat"], uid)
            if res is None:
                errored = True
                continue
            if res is False:
                ok = False
                break
        if ok and errored:
            # تلگرام جواب نداد: فقط اگه تازه عضو بوده بذار بمونه، وگرنه رد
            ok = bool(hit and hit[1] and time.time() - hit[0] < _MEMBER_GRACE)
            if ok:
                return True          # کش رو دست نمی‌زنیم تا دفعه‌ی بعد دوباره چک بشه
        if len(_member_cache) > 20000:
            _member_cache.clear()
        _member_cache[uid] = (time.time(), ok)
        return ok


def _not_member_detail():
    return {
        "code": "not_member",
        "message": "برای استفاده از مینی‌اپ اول باید عضو کانال‌های ربات بشی.",
        "channels": [{"label": c["label"], "url": c["url"]} for c in REQUIRED_CHANNELS],
    }


def current_telegram_user_raw(x_init_data: str = Header(..., alias="X-Init-Data")):
    """فقط هویت (بدون چک عضویت) — برای خود endpoint بررسی عضویت."""
    return _auth_user(x_init_data)


def _restriction_detail(uid: int):
    """بن، جریمه‌ی پرداخت‌نشده، زندان روبی یا مریضی روباه = مینی‌اپ کلاً بسته است (ادمین‌ها معافن)."""
    uid = int(uid)
    if uid in ADMIN_ID_SET:
        return None

    def aw(d):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    def det(kind, title, message):
        return {"code": "restricted", "kind": kind, "title": title, "message": message}

    session = get_session()
    try:
        u = session.get(User, uid)
        if not u:
            return None
        now = datetime.now(timezone.utc)
        if int(getattr(u, "is_banned", 0) or 0) or (getattr(u, "banned_until", None) and aw(u.banned_until) > now):
            return det("ban", "⛔ دسترسی بسته شده", "دسترسی‌ات به ربات بسته شده.")
        fine = int(getattr(u, "fine_amount", 0) or 0)
        if fine > 0:
            reason = (getattr(u, "fine_reason", None) or "").strip()
            return det("fine", "💸 جریمه‌ی پرداخت‌نشده",
                       f"مبلغ جریمه: {fine:,} روب‌پوینت" + (f"\nدلیل: {reason}" if reason else "") +
                       "\n\nتا پرداخت جریمه از توی بات (دکمه‌ی «پرداخت جریمه») به مینی‌اپ دسترسی نداری.")
        ju = getattr(u, "jail_until", None)
        if ju and aw(ju) > now:
            left = int((aw(ju) - now).total_seconds())
            h, m = left // 3600, (left % 3600) // 60
            return det("jail", "⛓️ زندانی هستی",
                       f"زمان باقی‌مانده: {h} ساعت و {m} دقیقه\n\nتا پایان حبس نمی‌تونی از مینی‌اپ استفاده کنی.")
        try:
            botmod = load_botmod()
            if int(u.level or 1) >= botmod.FOX_SICK_UNLOCK_LEVEL:
                if botmod.sync_fox_sickness(u):
                    session.commit()
        except Exception:  # noqa: BLE001
            pass
        if u.fox_sick_since is not None:
            return det("sick", "🤒 روباهت مریضه",
                       "تا وقتی روباهت مریضه نمی‌تونی از مینی‌اپ استفاده کنی.\nاول از توی بات درمانش کن، بعد برگرد.")
    finally:
        session.close()
    return None


def current_telegram_user(x_init_data: str = Header(..., alias="X-Init-Data")):
    """هویت + عضویت اجباری + نبودن محدودیت (زندان/جریمه/مریضی/بن)؛ همه‌ی endpointهای مینی‌اپ از این استفاده می‌کنن."""
    tg_user = _auth_user(x_init_data)
    if not membership_ok(tg_user["id"]):
        raise HTTPException(status_code=403, detail=_not_member_detail())
    blocked = _restriction_detail(tg_user["id"])
    if blocked:
        raise HTTPException(status_code=403, detail=blocked)
    return tg_user


@app.get("/api/membership")
def api_membership(tg_user: dict = Depends(current_telegram_user_raw)):
    ok = membership_ok(tg_user["id"], force=True)
    return {"ok": ok, "channels": [{"label": c["label"], "url": c["url"]} for c in REQUIRED_CHANNELS]}


def display_name(u: User) -> str:
    return u.username or u.first_name or str(u.telegram_id)


def load_botmod():
    """منطق بازی از خود bot.py (دقیقاً همون چیزی که بات استفاده می‌کنه)."""
    try:
        import bot as botmod
        return botmod
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"نتونستم منطق بازی رو لود کنم: {e}")


def fox_state(session, user, botmod=None):
    """وضعیت کامل روباه برای نمایش. اگه botmod داده بشه تولید معوق هم حساب می‌شه."""
    max_level = 25
    unlock = 3
    if botmod is not None:
        max_level = botmod.FOX_MAX_LEVEL
        unlock = botmod.FOX_UNLOCK_LEVEL
    lvl = max(1, min(max_level, int(user.fox_level or 1)))
    skins = active_skins(user)
    skin_key = skins[-1] if skins else ""
    gender = user.fox_gender or ""
    image = None
    if skin_key and skin_image_file(skin_key, gender):
        image = f"/skin/{skin_key}/{gender}"

    state = {
        "locked": int(user.level or 1) < unlock,
        "unlock_level": unlock,
        "sick": user.fox_sick_since is not None,
        "fox_name": user.fox_name or "مکار",
        "fox_gender": gender,
        "fox_level": lvl,
        "max_level": max_level,
        "fox_points": int(user.fox_points or 0),
        "fox_storage": int(user.fox_storage or 0),
        "fox_belly": int(user.fox_belly or 0),
        "fox_belly_capacity": botmod.fox_belly_cap(user),
        "skin_key": skin_key,
        "skin_title": SKIN_INFO.get(skin_key, ""),
        "skin_image": image,
        "active_skins": [SKIN_INFO[k] for k in skins],
    }
    if botmod is not None:
        state["fox_rank"] = botmod.fox_rank(lvl)
        state["storage_capacity"] = int(botmod.fox_storage_capacity(lvl))
        state["rate"] = int(botmod.fox_production_per_second(lvl)) + int(botmod.vip_rate_bonus(user))
        state["upgrade_cost"] = None if lvl >= max_level else int(botmod.fox_upgrade_cost(lvl))
        state["fox_storage"] = min(state["storage_capacity"], int(user.fox_storage or 0))
    return state


# ---------------------------------------------------------------------------
# پروفایل
# ---------------------------------------------------------------------------
_last_resolve = {"t": 0.0}


def _attacks_payload(session, user_id: int):
    """حمله‌های منتظر تصمیمِ این کاربر (برای کارت مینی‌اپ)."""
    if time.time() - _last_resolve["t"] >= 10:      # هر ۱۰ ثانیه یک بار کافیه (بات هم جاب خودش رو داره)
        _last_resolve["t"] = time.time()
        try:
            attack_owl.resolve_expired()   # منقضی‌ها همین‌جا هم اجرا می‌شن
        except Exception:  # noqa: BLE001
            pass
    out = []
    for att in attack_owl.pending_for_target(session, user_id):
        attacker = session.get(User, att.attacker_id)
        out.append({
            "id": att.id,
            "attacker": display_name(attacker) if attacker else str(att.attacker_id),
            "amount": int(att.amount or 0),
            "left": attack_owl.left_seconds(att),
        })
    return out


@app.get("/api/attacks")
def attacks_list(tg_user: dict = Depends(current_telegram_user)):
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        return {"attacks": _attacks_payload(session, tg_user["id"]), "owls": int(user.owl_catch_count or 0) if user else 0}
    finally:
        session.close()


@app.post("/api/attacks/{att_id}/{action}")
def attacks_decide(att_id: int, action: str, tg_user: dict = Depends(current_telegram_user)):
    if action not in ("protect", "allow"):
        raise HTTPException(status_code=400, detail="عملیات نامعتبره.")
    res = attack_owl.resolve(att_id, action, by_user_id=tg_user["id"])
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error", "خطا"))
    if res["status"] == "protected":
        msg = "🦉 یکی از جغدهات خرج شد و حمله خنثی شد!"
    elif res["status"] == "timeout":
        msg = "⏰ مهلت تموم شده بود؛ حمله اجرا شد."
    else:
        msg = "⚔️ حمله انجام شد."
    return {"message": msg, "status": res["status"]}


def _level_requirement_fallback(level):
    """کپی دقیق جدول سطح کاربر بات (برای وقتی که بات لود نشده)."""
    level = max(1, int(level))
    req = {1: 0, 2: 5, 3: 15, 4: 40, 5: 70, 6: 115, 7: 175, 8: 250, 9: 350, 10: 500, 11: 700, 12: 950,
           13: 1250, 14: 1650, 15: 2150, 16: 2600, 17: 3600, 18: 4600, 19: 5800, 20: 7250}
    if level <= 20:
        return req[level]
    value, step = req[20], 900
    for _ in range(21, level + 1):
        value += step
        step += 250
    return value


def user_level_info(user, botmod=None):
    """پیشرفت سطح کاربر؛ دقیقاً با فرمول «پروفایل روبی» بات: روب‌روب‌ها منهای حد نصاب سطح فعلی."""
    req = getattr(botmod, "user_level_requirement", None) or _level_requirement_fallback
    lvl = max(1, int(user.level or 1))
    claims = int(user.fox_claim_count or 0)
    cur_req, next_req = req(lvl), req(lvl + 1)
    needed = max(0, next_req - cur_req)
    done = max(0, claims - cur_req)
    if needed == 0 or done >= needed:
        done_c, percent = needed, 100
    else:
        done_c, percent = done, int(done * 100 / needed)
    return {
        "level": lvl, "next_level": lvl + 1, "claims": claims,
        "done": done_c, "needed": needed, "remaining": max(0, needed - done),
        "percent": percent, "total_needed": next_req,
    }


@app.get("/api/profile")
def get_profile(tg_user: dict = Depends(current_telegram_user)):
    # اگه به هر دلیلی منطق بات لود نشد، پروفایل ساده هنوز نشون داده می‌شه (دکمه‌ها خطا می‌دن)
    try:
        botmod = load_botmod()
    except HTTPException:
        botmod = None
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(
                status_code=404,
                detail="هنوز توی بات ثبت‌نام نکردی؛ اول یه پیام به بات بده (مثلاً /start) بعد دوباره مینی‌اپ رو باز کن.",
            )
        if botmod is not None and int(user.level or 1) >= botmod.FOX_UNLOCK_LEVEL and user.fox_sick_since is None:
            # تولید معوق رو حساب می‌کنیم تا انبار روباه به‌روز نشون داده بشه (مثل پنل روباه بات)
            botmod.settle_fox_production(user)
            session.commit()
        rank = session.query(User).filter(User.fox_points > (user.fox_points or 0), ~User.telegram_id.in_(list(ADMIN_ID_SET) or [0])).count() + 1
        referral_count = (
            session.query(func.count(Referral.id))
            .filter(Referral.referrer_id == user.telegram_id, Referral.status == "approved")
            .scalar()
            or 0
        )
        data = fox_state(session, user, botmod)
        data.update({
            "telegram_id": user.telegram_id,
            "avatar": avatar_url(user.telegram_id),
            "display_name": display_name(user),
            "points_rank": rank,
            "hunt_count": int(user.hunt_count or 0),
            "fox_claim_count": int(user.fox_claim_count or 0),
            "fox_rescued_count": int(user.fox_rescued_count or 0),
            "owl_catch_count": int(user.owl_catch_count or 0),
            "referral_count": int(referral_count),
            "total_earned": int(user.fox_total_earned or 0),
            "user_level": user_level_info(user, botmod),
            "attacks": _attacks_payload(session, user.telegram_id),
        })
        return data
    finally:
        session.close()


def locked_user(session, tg_user, botmod):
    """کاربر رو با قفل ردیف می‌گیره و شرایط استفاده از روباه رو چک می‌کنه."""
    user = (
        session.query(User)
        .filter(User.telegram_id == tg_user["id"])
        .with_for_update()
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
    if int(user.level or 1) < botmod.FOX_UNLOCK_LEVEL:
        raise HTTPException(status_code=403, detail=f"روباه از سطح {botmod.FOX_UNLOCK_LEVEL} باز می‌شه.")
    try:
        botmod.sync_fox_sickness(user)
    except Exception:
        pass
    if user.fox_sick_since is not None:
        session.commit()
        raise HTTPException(status_code=403, detail="روباهت مریضه 🤒 اول از توی بات درمانش کن.")
    return user


# ---------------------------------------------------------------------------
# دکمه‌های روباه
# ---------------------------------------------------------------------------
@app.post("/api/fox/collect")
def fox_collect(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        botmod.settle_fox_production(user)
        amount = int(user.fox_storage or 0)
        user.fox_points = int(user.fox_points or 0) + amount
        user.fox_storage = 0
        # مثل بات: برداشت = شروع یک چرخه‌ی کاملاً جدید
        user.fox_last_production_at = botmod.now_utc()
        user.fox_production_remainder = 0.0
        session.commit()
        if amount <= 0:
            return {"message": "📦 انبار روباه هنوز خالیه؛ کمی صبر کن تا تولید کنه.", "amount": 0,
                    "balance": int(user.fox_points or 0)}
        return {"message": f"💰 {amount:,} روب‌پوینت برداشت شد و به موجودیت اضافه شد.", "amount": amount,
                "balance": int(user.fox_points or 0)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/api/fox/upgrade")
def fox_upgrade(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        botmod.settle_fox_production(user)
        lvl = max(1, min(botmod.FOX_MAX_LEVEL, int(user.fox_level or 1)))
        if lvl >= botmod.FOX_MAX_LEVEL:
            raise HTTPException(status_code=400, detail=f"🏆 روباه به آخرین سطح ({botmod.FOX_MAX_LEVEL}) رسیده.")
        cost = botmod.fox_upgrade_cost(lvl)
        if int(user.fox_points or 0) < cost:
            raise HTTPException(status_code=400, detail=f"روب‌پوینت کافی نیست. {int(cost):,} لازم داری.")
        user.fox_points -= cost
        user.fox_level += 1
        user.fox_belly_capacity = botmod.fox_belly_capacity_for(user.fox_level)
        user.fox_last_production_at = botmod.now_utc()
        session.commit()
        return {"message": f"🦊 روباه رفت لول {user.fox_level}! مقام: {botmod.fox_rank(user.fox_level)}"}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class RenameBody(BaseModel):
    name: str


@app.post("/api/fox/rename")
def fox_rename(body: RenameBody, tg_user: dict = Depends(current_telegram_user)):
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(status_code=400, detail="اسم نمی‌تونه خالی باشه.")
    if len(name) > 16:
        raise HTTPException(status_code=400, detail="اسم حداکثر ۱۶ کاراکتر می‌تونه باشه.")
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        user.fox_name = name
        session.commit()
        return {"message": f"✅ اسم روباه تغییر کرد به: 🦊 {name}"}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class GenderBody(BaseModel):
    gender: str


@app.post("/api/fox/gender")
def fox_gender(body: GenderBody, tg_user: dict = Depends(current_telegram_user)):
    if body.gender not in ("male", "female"):
        raise HTTPException(status_code=400, detail="جنسیت نامعتبره.")
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        if botmod.active_marriage(session, user.telegram_id):
            raise HTTPException(status_code=400, detail="💍 بعد از ازدواج تغییر جنسیت روباه ممنوعه.")
        user.fox_gender = body.gender
        session.commit()
        label = "مرد 👦" if body.gender == "male" else "زن 👧"
        return {"message": f"✅ جنسیت روباه شد: {label}"}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# لیدربرد
# ---------------------------------------------------------------------------
LEADERBOARD_FIELDS = {
    "points": ("fox_points", "روب‌پوینت", "💰"),
    "referral": (None, "رفرال‌ها", "👑"),
    "rescued": ("fox_rescued_count", "روباه‌های زخمی", "🎃"),
    "hunt": ("hunt_count", "شکار", "⚔️"),
    "claim": ("fox_claim_count", "روب روب", "🐾"),
    "edu": (None, "پاسخ درست درس", "🎓"),
    "owl": ("owl_catch_count", "جغد روبی", "🦉"),
}
# نگاشت دسته‌ی مینی‌اپ → کلید لیدربرد بات (برای لقب نفرات اول تا سوم)
_LB_BOT_KEYS = {"points": "fox_points", "referral": "referral_count", "rescued": "fox_rescued_count",
                "hunt": "hunt_count", "claim": "fox_claim_count", "edu": "edu_correct"}


@app.get("/api/ping")
def ping():
    """سبک‌ترین endpoint ممکن؛ مینی‌اپ باهاش پینگ (رفت‌وبرگشت) رو اندازه می‌گیره. بدون احراز هویت و بدون دیتابیس."""
    return Response("ok", media_type="text/plain", headers={"Cache-Control": "no-store"})


def _lb_titles(category):
    try:
        key = _LB_BOT_KEYS.get(category)
        if not key:
            return {}
        return dict(getattr(load_botmod(), "LEADERBOARD_TITLES", {}).get(key, {}) or {})
    except Exception:
        return {}


@app.get("/api/leaderboard")
def get_leaderboard(category: str = "points", tg_user: dict = Depends(current_telegram_user)):
    if category not in LEADERBOARD_FIELDS:
        raise HTTPException(status_code=400, detail="دسته‌ی لیدربرد نامعتبره.")
    field, label, emoji = LEADERBOARD_FIELDS[category]
    titles = _lb_titles(category)
    session = get_session()
    try:
        def base_entry(rank, u, value):
            skins = active_skins(u)
            return {
                "rank": rank,
                "name": display_name(u),
                "value": int(value or 0),
                "me": u.telegram_id == tg_user["id"],
                "avatar": avatar_url(u.telegram_id),
                "skin": SKIN_INFO.get(skins[-1], "") if skins else "",
                "title": titles.get(rank, "") if rank <= 3 else "",
            }

        admin_ids = list(ADMIN_ID_SET) or [0]
        if category == "referral":
            rows = (
                session.query(Referral.referrer_id, func.count(Referral.id).label("cnt"))
                .filter(Referral.status == "approved", ~Referral.referrer_id.in_(admin_ids))
                .group_by(Referral.referrer_id)
                .order_by(func.count(Referral.id).desc())
                .limit(50).all()
            )
            ids = [r[0] for r in rows]
            users_by_id = {u.telegram_id: u for u in session.query(User).filter(User.telegram_id.in_(ids or [0])).all()}
            pairs = [(users_by_id[uid], cnt) for uid, cnt in rows if uid in users_by_id]
        elif category == "edu":
            rows = (
                session.query(User, education.EducationProgress.correct_answers)
                .join(education.EducationProgress, education.EducationProgress.user_id == User.telegram_id)
                .filter(education.EducationProgress.correct_answers > 0, ~User.telegram_id.in_(admin_ids))
                .order_by(education.EducationProgress.correct_answers.desc(), User.telegram_id.asc())
                .limit(50).all()
            )
            pairs = [(u, c) for u, c in rows]
        else:
            col = getattr(User, field)
            users = (session.query(User).filter(~User.telegram_id.in_(admin_ids))
                     .order_by(col.desc(), User.telegram_id.asc()).limit(50).all())
            pairs = [(u, getattr(u, field)) for u in users]
        entries = [base_entry(i + 1, u, v) for i, (u, v) in enumerate(pairs)]
        return {"category": category, "label": label, "emoji": emoji, "entries": entries}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# گردونه‌ی روزانه (همون قوانین بات: ۲۴ ساعت یک‌بار، همون جایزه‌ها)
# ---------------------------------------------------------------------------
def _wheel_left(botmod, user) -> int:
    last = user.wheel_last_spin_at
    if last is None:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return max(0, int(botmod.WHEEL_COOLDOWN - (datetime.now(timezone.utc) - last).total_seconds()))


@app.get("/api/wheel")
def wheel_state(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        left = _wheel_left(botmod, user)
        return {
            "labels": list(botmod.WHEEL_LABELS),
            "rewards": list(botmod.WHEEL_REWARDS),
            "left": left,
            "can_spin": left == 0,
            "last_reward": user.wheel_last_reward,
            "balance": int(user.fox_points or 0),
        }
    finally:
        session.close()


@app.post("/api/wheel/spin")
def wheel_spin(tg_user: dict = Depends(current_telegram_user)):
    import random
    botmod = load_botmod()
    session = get_session()
    try:
        user = (session.query(User).filter(User.telegram_id == tg_user["id"]).with_for_update().first())
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        try:
            botmod.sync_fox_sickness(user)
        except Exception:  # noqa: BLE001
            pass
        if user.fox_sick_since:
            session.commit()
            raise HTTPException(status_code=403, detail="🤒 روباهت مریضه؛ اول از توی بات درمانش کن.")
        left = _wheel_left(botmod, user)
        if left > 0:
            raise HTTPException(status_code=429, detail=f"🐾 هنوز زوده! {left // 3600} ساعت و {(left % 3600) // 60} دقیقه‌ی دیگه.")
        idx = random.randrange(len(botmod.WHEEL_REWARDS))     # معادل random.choice بات؛ اندیس برای انیمیشن لازمه
        reward = int(botmod.WHEEL_REWARDS[idx])
        user.wheel_last_spin_at = datetime.now(timezone.utc)
        user.wheel_last_reward = reward
        if reward > 0:
            user.fox_points = int(user.fox_points or 0) + reward
        session.commit()
        return {
            "index": idx, "reward": reward, "label": botmod.WHEEL_LABELS[idx],
            "balance": int(user.fox_points or 0), "left": int(botmod.WHEEL_COOLDOWN),
            "message": "پوچ 😢" if reward == 0 else f"🎉 +{reward:,} روب‌پوینت برنده شدی!",
        }
    finally:
        session.close()



# ---------------------------------------------------------------------------
# کازینو: بمب 💥 (همون بازی و همون قانون جایزه‌ی بات؛ جدولش هم همون RubyTable)
# موقعیت بمب‌ها فقط سمت سرور می‌مونه و تا پایان بازی برای مینی‌اپ فرستاده نمی‌شه.
# ---------------------------------------------------------------------------
import json as _json
import random as _random


def _bomb_active(session, uid, botmod):
    return (session.query(botmod.RubyTable)
            .filter(botmod.RubyTable.creator_id == uid, botmod.RubyTable.game_type == "cz_bomb",
                    botmod.RubyTable.status == "active")
            .order_by(botmod.RubyTable.id.desc()).with_for_update().first())


def _bomb_game_payload(botmod, t, state=None, reveal=False):
    state = state if state is not None else _json.loads(t.state or "{}")
    safe = int(state.get("safe", 0))
    entry = int(t.entry_amount or 0)
    max_safe = botmod.BOMB_CELLS - botmod.BOMB_COUNT
    out = {
        "id": t.id, "entry": entry, "safe": safe, "max_safe": max_safe,
        "revealed": list(state.get("revealed", [])),
        "cells": botmod.BOMB_CELLS, "bombs_count": botmod.BOMB_COUNT,
        "cashout": int(botmod.bomb_total(safe, entry)),
        "next": int(botmod.bomb_total(safe + 1, entry)) if safe < max_safe else None,
    }
    if reveal:
        out["bombs"] = list(state.get("bombs", []))
        out["bomb_hit"] = state.get("bomb_hit")
    return out


def _bomb_steps(botmod, entry=None):
    """جدول جایزه برای نمایش (اگه ورودی داده بشه، دریافتیِ هر خانه هم حساب می‌شه)."""
    rows = []
    for k in range(1, botmod.BOMB_CELLS - botmod.BOMB_COUNT + 1):
        if k in botmod.BOMB_BONUS_STEPS:
            label = f"+{botmod.BOMB_BONUS_STEPS[k]:,}"
        else:
            label = f"×{botmod.BOMB_MULTIPLIERS[k]:g}"
        rows.append({"n": k, "label": label,
                     "total": int(botmod.bomb_total(k, entry)) if entry else None})
    return rows


def _bomb_guard(botmod, session, user):
    """همون شرط‌های بات: لول کازینو، زندان، بن، مریضی روباه."""
    if int(getattr(user, "is_banned", 0) or 0):
        raise HTTPException(status_code=403, detail="⛔ دسترسی‌ات به ربات بسته شده.")
    ju = getattr(user, "jail_until", None)
    if ju and botmod.now_utc() < botmod.aware(ju):
        raise HTTPException(status_code=403, detail="⛓️ زندانی هستی! تا پایان حبس از کازینو محرومی.")
    if int(user.level or 1) < botmod.CASINO_UNLOCK_LEVEL:
        raise HTTPException(status_code=403, detail=f"🔒 کازینو روبی از سطح {botmod.CASINO_UNLOCK_LEVEL} باز می‌شود. (سطح تو: {int(user.level or 1)})")
    try:
        botmod.sync_fox_sickness(user)
    except Exception:  # noqa: BLE001
        pass
    if user.fox_sick_since:
        session.commit()
        raise HTTPException(status_code=403, detail="🤒 روباهت مریضه؛ اول از توی بات درمانش کن.")


@app.get("/api/bomb")
def bomb_state(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = session.query(User).filter(User.telegram_id == tg_user["id"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        t = (session.query(botmod.RubyTable)
             .filter(botmod.RubyTable.creator_id == user.telegram_id, botmod.RubyTable.game_type == "cz_bomb",
                     botmod.RubyTable.status == "active")
             .order_by(botmod.RubyTable.id.desc()).first())
        return {
            "unlocked": int(user.level or 1) >= botmod.CASINO_UNLOCK_LEVEL,
            "unlock_level": botmod.CASINO_UNLOCK_LEVEL, "level": int(user.level or 1),
            "min_entry": botmod.BOMB_MIN_ENTRY, "max_entry": botmod.CASINO_MAX_ENTRY,
            "balance": int(user.fox_points or 0),
            "cooldown_left": int(botmod.ruby_cooldown_remaining(user, "cz_bomb")),
            "cooldown_total": int(botmod.CASINO_COOLDOWN_SECONDS),
            "steps": _bomb_steps(botmod),
            "game": _bomb_game_payload(botmod, t) if t else None,
        }
    finally:
        session.close()


class BombStart(BaseModel):
    amount: int


@app.post("/api/bomb/start")
def bomb_start(body: BombStart, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        _bomb_guard(botmod, session, user)
        t = _bomb_active(session, user.telegram_id, botmod)
        if t:   # بازی نیمه‌کاره داری؛ دوباره پول نمی‌گیریم
            session.commit()
            return {"game": _bomb_game_payload(botmod, t), "balance": int(user.fox_points or 0), "resumed": True}
        amount = int(body.amount or 0)
        if amount < botmod.BOMB_MIN_ENTRY:
            raise HTTPException(status_code=400, detail=f"❌ حداقل مبلغ ورودی بمب {botmod.BOMB_MIN_ENTRY:,} روب‌پوینته.")
        if amount > botmod.CASINO_MAX_ENTRY:
            raise HTTPException(status_code=400, detail=f"❌ سقف مبلغ ورودی {botmod.CASINO_MAX_ENTRY:,} روب‌پوینته.")
        left = int(botmod.ruby_cooldown_remaining(user, "cz_bomb"))
        if left > 0:
            raise HTTPException(status_code=429, detail=f"⏳ {left // 60} دقیقه و {left % 60} ثانیه‌ی دیگه می‌تونی بازی کازینو بسازی.")
        if int(user.fox_points or 0) < amount:
            raise HTTPException(status_code=400, detail="❌ روب‌پوینت کافی نداری.")
        user.fox_points = int(user.fox_points or 0) - amount
        user.last_casino_game_at = botmod.now_utc()
        state = {"bombs": _random.sample(range(botmod.BOMB_CELLS), botmod.BOMB_COUNT),
                 "revealed": [], "safe": 0, "ended": None, "src": "miniapp"}
        t = botmod.RubyTable(chat_id=int(user.telegram_id), game_type="cz_bomb", creator_id=user.telegram_id,
                             max_players=1, entry_amount=amount, pot=amount, players=str(user.telegram_id),
                             status="active", message_id=None, state=_json.dumps(state), created_at=botmod.now_utc())
        session.add(t)
        session.commit()
        return {"game": _bomb_game_payload(botmod, t, state), "balance": int(user.fox_points or 0), "resumed": False}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class BombOpen(BaseModel):
    cell: int


@app.post("/api/bomb/open")
def bomb_open(body: BombOpen, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        t = _bomb_active(session, user.telegram_id, botmod)
        if not t:
            raise HTTPException(status_code=404, detail="بازی فعالی نداری.")
        state = _json.loads(t.state or "{}")
        idx = int(body.cell)
        if idx < 0 or idx >= botmod.BOMB_CELLS or idx in state.get("revealed", []):
            raise HTTPException(status_code=400, detail="این خانه قبلاً باز شده.")
        entry = int(t.entry_amount or 0)
        if idx in state.get("bombs", []):
            t.status = "finished"; state["ended"] = "bomb"; state["bomb_hit"] = idx
            t.state = _json.dumps(state)
            session.commit()
            return {"ended": "bomb", "payout": 0, "balance": int(user.fox_points or 0),
                    "game": _bomb_game_payload(botmod, t, state, reveal=True),
                    "message": "💥 بمب پیدا شد! بازی تمام شد و جایزه‌ای نگرفتی."}
        state.setdefault("revealed", []).append(idx)
        state["safe"] = int(state.get("safe", 0)) + 1
        if state["safe"] >= botmod.BOMB_CELLS - botmod.BOMB_COUNT:
            payout = int(botmod.bomb_total(state["safe"], entry))
            user.fox_points = int(user.fox_points or 0) + payout
            t.status = "finished"; state["ended"] = "all_safe"
            t.state = _json.dumps(state)
            session.commit()
            return {"ended": "all_safe", "payout": payout, "balance": int(user.fox_points or 0),
                    "game": _bomb_game_payload(botmod, t, state, reveal=True),
                    "message": f"🏆 همه‌ی خانه‌های سالم رو پیدا کردی! {payout:,} روب‌پوینت گرفتی."}
        t.state = _json.dumps(state)
        session.commit()
        return {"ended": None, "payout": 0, "balance": int(user.fox_points or 0),
                "game": _bomb_game_payload(botmod, t, state), "message": "✅ خانه سالم بود!"}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/api/bomb/cashout")
def bomb_cashout(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        t = _bomb_active(session, user.telegram_id, botmod)
        if not t:
            raise HTTPException(status_code=404, detail="بازی فعالی نداری.")
        state = _json.loads(t.state or "{}")
        if int(state.get("safe", 0)) <= 0:
            raise HTTPException(status_code=400, detail="اول حداقل یه خانه‌ی سالم پیدا کن.")
        payout = int(botmod.bomb_total(state.get("safe", 0), t.entry_amount))
        user.fox_points = int(user.fox_points or 0) + payout
        t.status = "finished"; state["ended"] = "cashout"
        t.state = _json.dumps(state)
        session.commit()
        return {"ended": "cashout", "payout": payout, "balance": int(user.fox_points or 0),
                "game": _bomb_game_payload(botmod, t, state, reveal=True),
                "message": f"✅ از بازی خارج شدی و {payout:,} روب‌پوینت گرفتی."}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# کازینو: پلینکو 🔴 (۱۴ ردیف، ۱۵ خانه؛ حالت آرام و وحشی)
# منطق و ضرایب تو plinko_core.py ـه و با کازینوی ربات مشترکه. نتیجه سمت سرور تعیین می‌شه.
# ورودی/سقف/فاصله با PLINKO_MIN_ENTRY / PLINKO_MAX_ENTRY / PLINKO_COOLDOWN تو Railway قابل تنظیمه.
# ---------------------------------------------------------------------------
import plinko_core as _pk

_pk.ensure_table(engine)
PLINKO_ROWS = _pk.ROWS
PLINKO_MIN_ENTRY = _pk.MIN_ENTRY
PLINKO_MAX_ENTRY = _pk.MAX_ENTRY
PLINKO_COOLDOWN = _pk.COOLDOWN
# فاصله‌ی ۴۵ ثانیه‌ای بعد از هر بازی تو دیتابیس نگه داشته می‌شه (plinko_core.cooldown_*) تا بین ربات و مینی‌اپ مشترک باشه


@app.get("/api/plinko")
def plinko_state(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = session.query(User).filter(User.telegram_id == tg_user["id"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        uid = int(user.telegram_id)
        return {
            "unlocked": int(user.level or 1) >= botmod.CASINO_UNLOCK_LEVEL,
            "unlock_level": botmod.CASINO_UNLOCK_LEVEL, "level": int(user.level or 1),
            "disabled": bool(getattr(botmod, "CASINO_DISABLED", False)),
            "min_entry": PLINKO_MIN_ENTRY, "max_entry": PLINKO_MAX_ENTRY,
            "balance": int(user.fox_points or 0),
            "rows": PLINKO_ROWS,
            "default_mode": _pk.DEFAULT_MODE,
            "risks": {k: {"title": v["title"], "sub": v["sub"], "mult": v["mult"], "daily_limit": v["daily_limit"]} for k, v in _pk.MODES.items()},
            "daily_plays": {k: _pk.daily_used(session, uid, k) for k in _pk.MODES},
            "unlimited": uid in botmod.ADMIN_IDS,
            "cooldown_left": _pk.cooldown_left(session, uid), "cooldown_total": int(_pk.COOLDOWN),
        }
    finally:
        session.close()


class PlinkoDrop(BaseModel):
    amount: int
    risk: str = _pk.DEFAULT_MODE


@app.post("/api/plinko/drop")
def plinko_drop(body: PlinkoDrop, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user = locked_user(session, tg_user, botmod)
        if getattr(botmod, "CASINO_DISABLED", False):
            raise HTTPException(status_code=403, detail=getattr(botmod, "CASINO_DISABLED_TEXT", "کازینو فعلاً غیرفعاله."))
        _bomb_guard(botmod, session, user)
        mode_key = str(body.risk or _pk.DEFAULT_MODE)
        mode = _pk.MODES.get(mode_key)
        if not mode:
            raise HTTPException(status_code=400, detail="حالت بازی نامعتبره.")
        amount = int(body.amount or 0)
        if amount < PLINKO_MIN_ENTRY:
            raise HTTPException(status_code=400, detail=f"❌ حداقل مبلغ ورودی پلینکو {PLINKO_MIN_ENTRY:,} روب‌پوینته.")
        if amount > PLINKO_MAX_ENTRY:
            raise HTTPException(status_code=400, detail=f"❌ سقف مبلغ ورودی پلینکو {PLINKO_MAX_ENTRY:,} روب‌پوینته.")
        uid = int(user.telegram_id)
        used = _pk.daily_used(session, uid, mode_key)
        daily_limit = int(mode["daily_limit"])
        unlimited = uid in botmod.ADMIN_IDS
        if not unlimited and used >= daily_limit:
            raise HTTPException(status_code=429, detail=f"⏰ سهمیهٔ امروز این حالت تموم شده ({daily_limit} بار در روز). فردا دوباره بیا.")
        wait_left = _pk.cooldown_left(session, uid)
        if wait_left > 0:
            raise HTTPException(status_code=429, detail=f"⏳ بعد از هر بازی پلینکو باید صبر کنی؛ {wait_left} ثانیه‌ی دیگه می‌تونی دوباره بازی کنی.")
        if int(user.fox_points or 0) < amount:
            raise HTTPException(status_code=400, detail="❌ روب‌پوینت کافی نداری.")
        path, slot = _pk.roll()
        mult = float(mode["mult"][slot])
        payout = _pk.payout(amount, mult)
        user.fox_points = int(user.fox_points or 0) - amount + payout
        _pk.daily_inc(session, uid, mode_key)
        _pk.cooldown_start(session, uid)
        session.commit()
        profit = payout - amount
        used_after = used + 1
        total_assets = int(user.fox_points or 0)
        return {"path": path, "slot": slot, "mult": mult, "amount": amount, "payout": payout, "profit": profit,
                "balance": total_assets, "daily_used": used_after, "daily_limit": daily_limit, "unlimited": unlimited,
                "mode": mode_key, "message": _pk.result_text(amount, mult, payout),
                "cooldown": int(_pk.COOLDOWN)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# روباهیو درس (همون منطق education.py؛ پیشرفت بین بات و مینی‌اپ مشترکه)
# ---------------------------------------------------------------------------
EDU_UNLOCK_COST = 30000
EDU_COOLDOWN = 1500          # ۲۵ دقیقه
EDU_QUESTION_SECONDS = 15
EDU_GRACE = 2                # چند ثانیه‌ی تحمل برای تأخیر شبکه (فقط مینی‌اپ)


def _edu():
    import education
    return education


def _edu_progress(session, uid, lock=False):
    edu = _edu()
    q = session.query(edu.EducationProgress).filter(edu.EducationProgress.user_id == uid)
    if lock:
        q = q.with_for_update()
    p = q.first()
    if not p:
        p = edu.EducationProgress(user_id=uid)
        session.add(p)
        session.flush()
    return p


def _aw(d):
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _edu_active_options(edu, uid, p, session):
    """(سؤال، گزینه‌ها به ترتیب نمایش، اندیس درست در همین ترتیب، طراح) برای سؤال فعال؛ ترتیب گزینه‌ها برای هر سؤال ثابته."""
    topic, qid = p.active_topic, int(p.active_question)
    if qid >= edu.USER_Q_OFFSET:
        r = session.get(edu.EduUserQuestion, qid - edu.USER_Q_OFFSET)
        if not r or r.status != "approved" or r.topic != topic:
            return None
        opts = [(0, r.correct_opt), (1, r.wrong1), (2, r.wrong2)]
        seed = f"{uid}:{qid}:{int(_aw(p.active_expires).timestamp())}"
        _random.Random(seed).shuffle(opts)
        author = session.get(User, r.author_id)
        designer = display_name(author) if author else "کاربر"
        correct_pos = [i for i, (orig, _t) in enumerate(opts) if orig == 0][0]
        return r.question, [t for _o, t in opts], correct_pos, designer
    question, opts, correct = edu.TOPICS[topic][1][qid]
    return question, list(opts), int(correct), ""


def _edu_state(session, uid, p=None):
    edu = _edu()
    p = p or _edu_progress(session, uid)
    now = datetime.now(timezone.utc)
    unlocked = set((p.unlocked or "general").split(","))
    certs = int(p.certificates or 0)
    answers = int(p.correct_answers or 0)
    cooldown = 0
    if p.last_play_at:
        cooldown = max(0, int(EDU_COOLDOWN - (now - _aw(p.last_play_at)).total_seconds()))
    active = None
    if p.active_topic and p.active_question is not None and p.active_expires:
        left = int((_aw(p.active_expires) - now).total_seconds())
        if left > 0:
            got = _edu_active_options(edu, uid, p, session)
            if got:
                question, options, _cp, designer = got
                active = {"topic": p.active_topic, "topic_title": edu.TOPICS[p.active_topic][0],
                          "question": question, "options": options, "designer": designer, "left": left}
    return {
        "title": edu._name(certs),
        "correct_answers": answers,
        "units": int(p.correct or 0),
        "certificates": certs,
        "max_certificates": 15,
        "to_next": max(0, edu._threshold(certs) - answers) if certs < 15 else 0,
        "pending_certificate": bool(p.pending_certificate),
        "next_title": edu._name(certs + 1),
        "tuition": edu._tuition(certs),
        "reward": edu._reward(certs),
        "cooldown": cooldown,
        "unlock_cost": EDU_UNLOCK_COST,
        "topics": [{"key": k, "title": v[0], "unlocked": k in unlocked} for k, v in edu.TOPICS.items()],
        "active": active,
    }


@app.get("/api/botinfo")
def bot_info(tg_user: dict = Depends(current_telegram_user_raw)):
    """یوزرنیم بات (برای دکمه‌ی «طرح سوال» که به پیوی بات می‌ره)."""
    global _BOT_USERNAME
    if not _BOT_USERNAME:
        try:
            r = _tg_http.get(f"{_TG_API}/getMe").json()
            _BOT_USERNAME = (r.get("result") or {}).get("username") or ""
        except Exception:  # noqa: BLE001
            _BOT_USERNAME = ""
    return {"username": _BOT_USERNAME}


_BOT_USERNAME = ""


@app.get("/api/edu")
def edu_state(tg_user: dict = Depends(current_telegram_user)):
    session = get_session()
    try:
        if not session.get(User, tg_user["id"]):
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        p = _edu_progress(session, tg_user["id"])
        session.commit()
        return _edu_state(session, tg_user["id"], p)
    finally:
        session.close()


class EduStart(BaseModel):
    topic: str


@app.post("/api/edu/start")
def edu_start(body: EduStart, tg_user: dict = Depends(current_telegram_user)):
    edu = _edu()
    session = get_session()
    try:
        uid = tg_user["id"]
        user = session.query(User).filter(User.telegram_id == uid).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        p = _edu_progress(session, uid, lock=True)
        if body.topic not in edu.TOPICS:
            raise HTTPException(status_code=400, detail="موضوع نامعتبره.")
        if body.topic not in set((p.unlocked or "general").split(",")):
            raise HTTPException(status_code=403, detail="این موضوع هنوز قفله.")
        now = datetime.now(timezone.utc)
        if p.active_expires and _aw(p.active_expires) > now and p.active_topic:
            return {"state": _edu_state(session, uid, p)}
        if p.last_play_at and (now - _aw(p.last_play_at)).total_seconds() < EDU_COOLDOWN:
            raise HTTPException(status_code=429, detail="هر ۲۵ دقیقه یک سؤال مجازه.")
        topic = body.topic
        seen = _json.loads(p.answered or "{}")
        used = set(seen.get(topic, []))
        pool = edu.TOPICS[topic][1]
        user_qs = {edu.USER_Q_OFFSET + r.id: r for r in session.query(edu.EduUserQuestion).filter(
            edu.EduUserQuestion.topic == topic, edu.EduUserQuestion.status == "approved",
            edu.EduUserQuestion.author_id != uid).all()}
        all_ids = list(range(len(pool))) + list(user_qs.keys())
        available = [i for i in all_ids if i not in used]
        if not available:
            seen[topic] = []
            p.answered = _json.dumps(seen)
            available = all_ids
        qid = _random.choice(available)
        p.active_topic = topic
        p.active_question = qid
        p.active_expires = now + timedelta(seconds=EDU_QUESTION_SECONDS)
        p.last_play_at = now
        session.commit()
        return {"state": _edu_state(session, uid, p)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class EduUnlock(BaseModel):
    topic: str


@app.post("/api/edu/unlock")
def edu_unlock(body: EduUnlock, tg_user: dict = Depends(current_telegram_user)):
    edu = _edu()
    session = get_session()
    try:
        uid = tg_user["id"]
        user = session.query(User).filter(User.telegram_id == uid).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        p = _edu_progress(session, uid, lock=True)
        if body.topic not in edu.TOPICS:
            raise HTTPException(status_code=400, detail="موضوع نامعتبره.")
        unlocked = set((p.unlocked or "general").split(","))
        if body.topic in unlocked:
            return {"message": "این موضوع از قبل باز بوده.", "state": _edu_state(session, uid, p)}
        if int(user.fox_points or 0) < EDU_UNLOCK_COST:
            raise HTTPException(status_code=400, detail="روب‌پوینت کافی نیست.")
        user.fox_points = int(user.fox_points or 0) - EDU_UNLOCK_COST
        unlocked.add(body.topic)
        p.unlocked = ",".join(sorted(unlocked))
        session.commit()
        return {"message": "موضوع با موفقیت خریداری شد ✅", "state": _edu_state(session, uid, p)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class EduAnswer(BaseModel):
    pos: int


@app.post("/api/edu/answer")
def edu_answer(body: EduAnswer, tg_user: dict = Depends(current_telegram_user)):
    edu = _edu()
    session = get_session()
    try:
        uid = tg_user["id"]
        p = _edu_progress(session, uid, lock=True)
        now = datetime.now(timezone.utc)
        if (not p.active_topic or p.active_question is None or not p.active_expires
                or now > _aw(p.active_expires) + timedelta(seconds=EDU_GRACE)):
            p.active_topic = None
            p.active_question = None
            p.active_expires = None
            session.commit()
            raise HTTPException(status_code=400, detail="⏰ زمان سؤال تموم شد؛ این دور پایان یافت.")
        got = _edu_active_options(edu, uid, p, session)
        topic, qid = p.active_topic, int(p.active_question)
        seen = _json.loads(p.answered or "{}")
        seen.setdefault(topic, []).append(qid)
        p.answered = _json.dumps(seen)
        p.active_topic = None
        p.active_question = None
        p.active_expires = None
        if not got:
            session.commit()
            raise HTTPException(status_code=400, detail="این سؤال دیگه در دسترس نیست؛ دوباره تلاش کن.")
        _q, options, correct_pos, _d = got
        if int(body.pos) != correct_pos:
            session.commit()
            return {"result": "wrong", "message": "❌ پاسخ اشتباه بود؛ ۲۵ دقیقه بعد دوباره تلاش کن.",
                    "correct_text": options[correct_pos], "state": _edu_state(session, uid, p)}
        p.correct_answers = int(p.correct_answers or 0) + 1
        p.correct = int(p.correct or 0) + 2
        msg = f"✅ درست! +۲ واحد | 🎯 پاسخ‌های درست: {p.correct_answers}"
        if int(p.certificates or 0) < 15 and p.correct_answers >= edu._threshold(int(p.certificates or 0)):
            p.pending_certificate = 1
            msg += " | 🎓 به حد نصاب مدرک رسیدی!"
        session.commit()
        return {"result": "correct", "message": msg, "state": _edu_state(session, uid, p)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/api/edu/certificate")
def edu_certificate(tg_user: dict = Depends(current_telegram_user)):
    edu = _edu()
    session = get_session()
    try:
        uid = tg_user["id"]
        user = session.query(User).filter(User.telegram_id == uid).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        p = _edu_progress(session, uid, lock=True)
        if not p.pending_certificate:
            raise HTTPException(status_code=400, detail="مدرکی در انتظار تأیید نیست.")
        certs = int(p.certificates or 0)
        cost, reward = edu._tuition(certs), edu._reward(certs)
        if int(user.fox_points or 0) < cost:
            raise HTTPException(status_code=400, detail=f"روب‌پوینت کافی نیست؛ شهریه {cost:,} است.")
        user.fox_points = int(user.fox_points or 0) - cost + reward
        p.certificates = certs + 1
        p.pending_certificate = 0
        session.commit()
        return {"result": "correct", "state": _edu_state(session, uid, p),
                "message": f"🎓 مدرک {edu._name(certs + 1)} صادر شد! شهریه {cost:,} | جایزه {reward:,} روب‌پوینت"}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# بانک روبی (دقیقاً همون منطق بانک داخل بات: افتتاح، واریز، برداشت، کارت‌به‌کارت، سود)
# ---------------------------------------------------------------------------
BANK_MIN_LEVEL = 4


def _bank_models():
    import database
    return database.BankAccount, database.BankTransaction


def _bank_notify(uid: int, text_msg: str):
    """اطلاع‌رسانی بی‌صدا به پیوی کاربر (اگه نشد، مهم نیست)."""
    try:
        _tg_http.post(f"{_TG_API}/sendMessage", json={"chat_id": int(uid), "text": text_msg})
    except Exception:  # noqa: BLE001
        pass


def _parse_amount(botmod, raw) -> int:
    """عدد یا متن مثل 50k / ۵۰کا / 2m / 3میل → عدد صحیح مثبت (همون parse_amount بات)."""
    if isinstance(raw, bool):
        raise ValueError
    if isinstance(raw, (int, float)):
        v = int(raw)
        if v != raw:
            raise ValueError
        return v
    return int(botmod.parse_amount(str(raw)))


def _bank_tx_payload(session, BankTransaction, account_number):
    rows = (session.query(BankTransaction).filter(BankTransaction.account_number == account_number)
            .order_by(BankTransaction.id.desc()).limit(15).all())
    out = []
    for r in rows:
        ts = r.created_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        out.append({
            "id": r.id, "direction": r.direction, "amount": int(r.amount or 0),
            "description": r.description or "",
            "counterparty": r.counterparty_account or "",
            "ts": int(ts.timestamp()) if ts else 0,
        })
    return out


def _bank_payload(session, botmod, user, account):
    BankAccount, BankTransaction = _bank_models()
    wallet = int(user.fox_points or 0)
    storage = 0
    try:
        storage = int(user.fox_storage or 0)
    except Exception:  # noqa: BLE001
        pass
    base = {
        "unlocked": int(user.level or 1) >= BANK_MIN_LEVEL,
        "min_level": BANK_MIN_LEVEL,
        "level": int(user.level or 1),
        "has_account": account is not None,
        "wallet": wallet,
        "open_cost": int(botmod.BANK_OPEN_COST),
        "change_cost": int(botmod.BANK_CHANGE_COST),
        "fee_rate": float(botmod.BANK_CARD_TRANSFER_FEE_RATE),
        "transfer_cooldown": int(botmod.BANK_CARD_TRANSFER_COOLDOWN),
        "interest_interval": int(botmod.BANK_INTEREST_INTERVAL_SECONDS),
        "fox_storage": storage,
        "display_name": display_name(user),
    }
    if account is None:
        base.update({"bank": 0, "total_assets": wallet + storage, "transactions": []})
        return base
    bal = int(account.balance or 0)
    rate = float(botmod.vip_bank_rate(user))
    est = int(bal * rate)
    base.update({
        "account_number": account.account_number,
        "bank": bal,
        "total_assets": wallet + bal + storage,
        "rate": rate,
        "rate_percent": int(round(rate * 100)),
        "next_interest": est,
        "bank_with_interest": bal + est,
        "transfer_left": int(botmod.seconds_left(account.last_card_transfer_at, botmod.BANK_CARD_TRANSFER_COOLDOWN)),
        "interest_left": int(botmod.seconds_left(account.last_interest_at, botmod.BANK_INTEREST_INTERVAL_SECONDS)) if account.last_interest_at else 0,
        "transactions": _bank_tx_payload(session, BankTransaction, account.account_number),
    })
    return base


def _bank_locked(session, uid):
    """کاربر و حساب بانکی با قفل ردیف (بدون خطا اگه حساب نباشه)."""
    BankAccount, _ = _bank_models()
    user = session.query(User).filter(User.telegram_id == uid).with_for_update().first()
    if not user:
        raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
    account = session.query(BankAccount).filter(BankAccount.user_id == uid).with_for_update().first()
    return user, account


def _bank_need_account(user, account):
    if int(user.level or 1) < BANK_MIN_LEVEL:
        raise HTTPException(status_code=403, detail=f"🔒 بانک روبی از لول {BANK_MIN_LEVEL} باز می‌شه.")
    if account is None:
        raise HTTPException(status_code=400, detail="اول باید شعبه‌ی بانک رو افتتاح کنی.")


@app.get("/api/bank")
def bank_state(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    BankAccount, _ = _bank_models()
    session = get_session()
    try:
        uid = tg_user["id"]
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        account = session.query(BankAccount).filter(BankAccount.user_id == uid).with_for_update().first()
        if account is not None:
            botmod.apply_bank_interest(account, session)   # سود دوره‌ای، مثل باز کردن پنل بانک در بات
        session.commit()
        return _bank_payload(session, botmod, user, account)
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/api/bank/open")
def bank_open(tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    session = get_session()
    try:
        user, account = _bank_locked(session, tg_user["id"])
        if int(user.level or 1) < BANK_MIN_LEVEL:
            raise HTTPException(status_code=403, detail=f"🔒 بانک روبی از لول {BANK_MIN_LEVEL} باز می‌شه.")
        if account is not None:
            return {"message": "شعبه‌ات از قبل باز بوده.", **_bank_payload(session, botmod, user, account)}
        account, ok = botmod.ensure_bank(session, user)
        if not ok:
            raise HTTPException(status_code=400, detail=f"❌ برای افتتاح شعبه‌ی بانک {int(botmod.BANK_OPEN_COST):,} روب‌پوینت لازم داری.")
        session.commit()
        return {"message": "🏦 شعبه‌ی بانک روبی افتتاح شد!", **_bank_payload(session, botmod, user, account)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class BankAmount(BaseModel):
    amount: Any


@app.post("/api/bank/deposit")
def bank_deposit(body: BankAmount, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    _, BankTransaction = _bank_models()
    try:
        amount = _parse_amount(botmod, body.amount)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="مبلغ نامعتبره. مثال: 50000 یا 50k")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="مبلغ باید بیشتر از صفر باشه.")
    session = get_session()
    try:
        user, account = _bank_locked(session, tg_user["id"])
        _bank_need_account(user, account)
        if int(user.fox_points or 0) < amount:
            raise HTTPException(status_code=400, detail="❌ روب‌پوینت کافی نیست.")
        botmod.apply_bank_interest(account, session)
        user.fox_points = int(user.fox_points or 0) - amount
        account.balance = int(account.balance or 0) + amount
        session.add(BankTransaction(account_number=account.account_number, direction="deposit", amount=amount, description="واریز به بانک"))
        session.commit()
        return {"message": f"➕ {amount:,} روب‌پوینت به بانک واریز شد.", **_bank_payload(session, botmod, user, account)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class BankWithdraw(BaseModel):
    percent: Optional[int] = None
    amount: Optional[Any] = None


@app.post("/api/bank/withdraw")
def bank_withdraw(body: BankWithdraw, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    _, BankTransaction = _bank_models()
    session = get_session()
    try:
        user, account = _bank_locked(session, tg_user["id"])
        _bank_need_account(user, account)
        botmod.apply_bank_interest(account, session)
        bal = int(account.balance or 0)
        if body.percent is not None:
            if int(body.percent) not in (25, 50, 75, 100):
                raise HTTPException(status_code=400, detail="درصد نامعتبره.")
            amount = (bal * int(body.percent)) // 100
            desc = f"برداشت {int(body.percent)}%"
        elif body.amount is not None:
            try:
                amount = _parse_amount(botmod, body.amount)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="مبلغ نامعتبره. مثال: 50000 یا 50k")
            desc = "برداشت از بانک"
        else:
            raise HTTPException(status_code=400, detail="مبلغ یا درصد برداشت رو بفرست.")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="موجودی کافی نیست.")
        if amount > bal:
            raise HTTPException(status_code=400, detail="❌ موجودی بانک کافی نیست.")
        account.balance = bal - amount
        user.fox_points = int(user.fox_points or 0) + amount
        session.add(BankTransaction(account_number=account.account_number, direction="withdraw", amount=amount, description=desc))
        session.commit()
        return {"message": f"➖ {amount:,} روب‌پوینت به کیف پولت برگشت.", **_bank_payload(session, botmod, user, account)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


class BankLookup(BaseModel):
    dest: str
    amount: Optional[Any] = None


def _clean_account(raw: str) -> str:
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return "".join(ch for ch in str(raw or "").translate(trans) if ch.isdigit())


@app.post("/api/bank/lookup")
def bank_lookup(body: BankLookup, tg_user: dict = Depends(current_telegram_user)):
    """پیش‌نمایش کارت‌به‌کارت (گیرنده + کارمزد + مجموع) قبل از تأیید نهایی."""
    botmod = load_botmod()
    BankAccount, _ = _bank_models()
    session = get_session()
    try:
        uid = tg_user["id"]
        user = session.get(User, uid)
        account = session.query(BankAccount).filter(BankAccount.user_id == uid).first()
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        _bank_need_account(user, account)
        dest = _clean_account(body.dest)
        target = session.get(BankAccount, dest) if dest else None
        if not target:
            raise HTTPException(status_code=404, detail="❌ حسابی با این شماره پیدا نشد.")
        if target.user_id == uid:
            raise HTTPException(status_code=400, detail="❌ نمی‌تونی به حساب خودت کارت‌به‌کارت کنی.")
        target_user = session.get(User, target.user_id)
        out = {"dest": dest, "name": display_name(target_user) if target_user else "کاربر"}
        if body.amount is not None:
            try:
                amount = _parse_amount(botmod, body.amount)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="مبلغ نامعتبره.")
            if amount <= 0:
                raise HTTPException(status_code=400, detail="مبلغ باید بیشتر از صفر باشه.")
            fee = max(1, int(amount * botmod.BANK_CARD_TRANSFER_FEE_RATE))
            out.update({"amount": amount, "fee": fee, "total": amount + fee})
        return out
    finally:
        session.close()


@app.post("/api/bank/transfer")
def bank_transfer(body: BankLookup, tg_user: dict = Depends(current_telegram_user)):
    botmod = load_botmod()
    BankAccount, BankTransaction = _bank_models()
    uid = tg_user["id"]
    dest = _clean_account(body.dest)
    try:
        amount = _parse_amount(botmod, body.amount)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="مبلغ نامعتبره. مثال: 500 یا 5k")
    if amount <= 0 or not dest:
        raise HTTPException(status_code=400, detail="شماره حساب و مبلغ رو درست وارد کن.")
    session = get_session()
    notify = None
    try:
        user, account = _bank_locked(session, uid)
        _bank_need_account(user, account)
        target = session.query(BankAccount).filter(BankAccount.account_number == dest).with_for_update().first()
        if not target:
            raise HTTPException(status_code=404, detail="❌ حسابی با این شماره پیدا نشد.")
        if target.user_id == uid:
            raise HTTPException(status_code=400, detail="❌ نمی‌تونی به حساب خودت کارت‌به‌کارت کنی.")
        left = botmod.seconds_left(account.last_card_transfer_at, botmod.BANK_CARD_TRANSFER_COOLDOWN)
        if left:
            raise HTTPException(status_code=429, detail=f"⏳ کارت‌به‌کارت بعدی {botmod.format_duration(left)} دیگه فعال می‌شه.")
        botmod.apply_bank_interest(account, session)
        fee = max(1, int(amount * botmod.BANK_CARD_TRANSFER_FEE_RATE))
        total = amount + fee
        if int(account.balance or 0) < total:
            raise HTTPException(status_code=400, detail=f"❌ موجودی بانک کافی نیست. مبلغ {amount:,} + کارمزد {fee:,} = {total:,} روب‌پوینت لازمه.")
        target_user = session.get(User, target.user_id)
        account.balance = int(account.balance or 0) - total
        target.balance = int(target.balance or 0) + amount
        account.last_card_transfer_at = datetime.now(timezone.utc)
        session.add(BankTransaction(account_number=account.account_number, counterparty_account=dest, counterparty_user_id=target.user_id,
                                    direction="card_out", amount=amount, description=f"کارت به کارت (کارمزد 5٪: {fee:,})"))
        session.add(BankTransaction(account_number=account.account_number, direction="fee", amount=fee, description="کارمزد 5٪ کارت به کارت"))
        session.add(BankTransaction(account_number=dest, counterparty_account=account.account_number, counterparty_user_id=uid,
                                    direction="card_in", amount=amount, description="کارت به کارت"))
        session.commit()
        notify = (target.user_id, f"💳 {amount:,} روب‌پوینت به حساب روبی شما واریز شد.\n👤 فرستنده: {display_name(user)}\n💳 حساب شما: {dest}")
        payload = _bank_payload(session, botmod, user, account)
        to_name = display_name(target_user) if target_user else "کاربر"
        result = {"message": f"✅ {amount:,} روب‌پوینت برای {to_name} کارت‌به‌کارت شد (کارمزد {fee:,}).", **payload}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()
    if notify:
        _bank_notify(*notify)
    return result


@app.post("/api/bank/change")
def bank_change_card(tg_user: dict = Depends(current_telegram_user)):
    import secrets
    botmod = load_botmod()
    BankAccount, BankTransaction = _bank_models()
    session = get_session()
    try:
        user, account = _bank_locked(session, tg_user["id"])
        _bank_need_account(user, account)
        cost = int(botmod.BANK_CHANGE_COST)
        if int(user.fox_points or 0) < cost:
            raise HTTPException(status_code=400, detail=f"❌ برای تغییر شماره کارت {cost:,} روب‌پوینت لازم داری.")
        old = account.account_number
        new = "".join(str(secrets.randbelow(10)) for _ in range(12))
        while session.get(BankAccount, new):
            new = "".join(str(secrets.randbelow(10)) for _ in range(12))
        user.fox_points = int(user.fox_points or 0) - cost
        account.account_number = new
        session.query(BankTransaction).filter(BankTransaction.account_number == old).update(
            {BankTransaction.account_number: new}, synchronize_session=False)
        session.add(BankTransaction(account_number=new, direction="fee", amount=cost, description="هزینه تغییر شماره کارت"))
        session.commit()
        return {"message": "✅ شماره کارت روبی تغییر کرد.", **_bank_payload(session, botmod, user, account)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()
