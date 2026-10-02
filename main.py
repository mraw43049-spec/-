"""
بک‌اند مینی‌اپ روبی (نسخه‌ی بدون پوشه: همه‌ی فایل‌ها کنار bot.py هستن).

- پروفایل روباه (با اسکین فعال) + دکمه‌های روباه (برداشت / ارتقا / تغییر نام / جنسیت)
- لیدربرد روب‌پوینت
- منطق برداشت و ارتقا از خود bot.py استفاده می‌کنه تا دقیقاً مثل بات رفتار کنه.
"""
import hashlib
import hmac
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
import httpx

from auth import extract_telegram_user, validate_init_data

try:
    from database import ChatMessage, Referral, User, engine, get_session
except ImportError as e:
    raise RuntimeError("نتونستم database.py رو پیدا کنم؛ main.py باید کنار bot.py باشه.") from e

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("متغیر محیطی BOT_TOKEN ست نشده.")

app = FastAPI(title="Ruby Fox Mini App API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# جدول چت‌روم اگه هنوز ساخته نشده باشه (مثلاً مینی‌اپ جدا از بات بالا بیاد) همین‌جا ساخته می‌شه.
try:
    ChatMessage.__table__.create(bind=engine, checkfirst=True)
except Exception as _e:  # noqa: BLE001
    print(f"[miniapp] could not create chat table: {_e}")

NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}

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
    return out


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


def _fetch_avatar_from_telegram(uid: int):
    """عکس پروفایل رو از Bot API می‌گیره؛ اگه نداشت/بسته بود None."""
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{base}/getUserProfilePhotos", params={"user_id": uid, "limit": 1}).json()
        photos = (r.get("result") or {}).get("photos") or []
        if not photos or not photos[0]:
            return None
        sizes = photos[0]
        # کوچیک‌ترین سایزی که حداقل ~160px باشه تا سریع لود بشه
        pick = next((p for p in sizes if (p.get("width") or 0) >= 160), sizes[-1])
        f = c.get(f"{base}/getFile", params={"file_id": pick["file_id"]}).json()
        path = (f.get("result") or {}).get("file_path")
        if not path:
            return None
        img = c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
        if img.status_code != 200:
            return None
        return img.content


@app.get("/api/avatar/{uid}")
def get_avatar(uid: int, s: str = ""):
    if not hmac.compare_digest(s or "", _avatar_sig(uid)):
        raise HTTPException(status_code=403, detail="لینک نامعتبره.")
    f = _AVATAR_DIR / f"{uid}.jpg"
    miss = _AVATAR_DIR / f"{uid}.none"
    now = time.time()
    if f.exists() and now - f.stat().st_mtime < _AVATAR_TTL:
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    if miss.exists() and now - miss.stat().st_mtime < _AVATAR_MISS_TTL:
        raise HTTPException(status_code=404, detail="بدون عکس.")
    try:
        data = _fetch_avatar_from_telegram(uid)
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
def current_telegram_user(x_init_data: str = Header(..., alias="X-Init-Data")):
    parsed = validate_init_data(x_init_data, BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="initData نامعتبر یا منقضی‌شده است.")
    tg_user = extract_telegram_user(parsed)
    if not tg_user or "id" not in tg_user:
        raise HTTPException(status_code=401, detail="اطلاعات کاربر در initData پیدا نشد.")
    return tg_user


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
        "fox_belly_capacity": min(20, max(1, int(user.fox_belly_capacity or 3))),
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
        rank = session.query(User).filter(User.fox_points > (user.fox_points or 0)).count() + 1
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
        user.fox_belly_capacity = min(20, int(user.fox_belly_capacity or 3) + 1)
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
    "hunt": ("hunt_count", "شکار", "⚔️"),
    "owl": ("owl_catch_count", "جغد", "🦉"),
    "rescued": ("fox_rescued_count", "نجات روباه", "🦊"),
}


@app.get("/api/leaderboard")
def get_leaderboard(category: str = "points", tg_user: dict = Depends(current_telegram_user)):
    session = get_session()
    try:
        if category == "referral":
            rows = (
                session.query(Referral.referrer_id, func.count(Referral.id).label("cnt"))
                .filter(Referral.status == "approved")
                .group_by(Referral.referrer_id)
                .order_by(func.count(Referral.id).desc())
                .limit(50).all()
            )
            ids = [r[0] for r in rows]
            users_by_id = {
                u.telegram_id: u
                for u in session.query(User).filter(User.telegram_id.in_(ids or [0])).all()
            }
            entries = [
                {"rank": i + 1, "name": display_name(users_by_id[uid]), "value": int(cnt),
                 "me": uid == tg_user["id"], "avatar": avatar_url(uid)}
                for i, (uid, cnt) in enumerate(rows) if uid in users_by_id
            ]
            return {"category": "referral", "label": "رفرال", "emoji": "👑", "entries": entries}

        if category not in LEADERBOARD_FIELDS:
            raise HTTPException(status_code=400, detail="دسته‌ی لیدربرد نامعتبره.")
        field, label, emoji = LEADERBOARD_FIELDS[category]
        col = getattr(User, field)
        users = session.query(User).order_by(col.desc(), User.telegram_id.asc()).limit(50).all()
        entries = []
        for i, u in enumerate(users):
            skins = active_skins(u)
            entries.append({
                "rank": i + 1,
                "name": display_name(u),
                "value": int(getattr(u, field) or 0),
                "me": u.telegram_id == tg_user["id"],
                "avatar": avatar_url(u.telegram_id),
                "skin": SKIN_INFO.get(skins[-1], "") if skins else "",
            })
        return {"category": category, "label": label, "emoji": emoji, "entries": entries}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# چت‌روم عمومی
# ---------------------------------------------------------------------------
CHAT_MAX_LEN = 300
CHAT_COOLDOWN_SECONDS = 2
CHAT_PAGE = 60
_last_chat_at: dict = {}


class ChatBody(BaseModel):
    text: str


def _chat_blocked(user) -> bool:
    now = datetime.now(timezone.utc)
    if int(user.is_banned or 0):
        return True
    bu = user.banned_until
    if bu is not None:
        if bu.tzinfo is None:
            bu = bu.replace(tzinfo=timezone.utc)
        if bu > now:
            return True
    return False


def _chat_rows(session, rows, me_id):
    ids = {r.user_id for r in rows}
    users = {u.telegram_id: u for u in session.query(User).filter(User.telegram_id.in_(ids or [0])).all()}
    out = []
    for r in rows:
        u = users.get(r.user_id)
        skins = active_skins(u) if u else []
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "name": display_name(u) if u else str(r.user_id),
            "avatar": avatar_url(r.user_id),
            "skin": SKIN_INFO.get(skins[-1], "").split(" ")[0] if skins else "",
            "text": r.text,
            "me": r.user_id == me_id,
            "ts": int(r.created_at.timestamp()) if r.created_at else 0,
        })
    return out


@app.get("/api/chat")
def chat_list(after: int = 0, tg_user: dict = Depends(current_telegram_user)):
    """after=0 → آخرین پیام‌ها؛ after=N → فقط پیام‌های جدیدتر از N."""
    session = get_session()
    try:
        q = session.query(ChatMessage)
        if after > 0:
            rows = q.filter(ChatMessage.id > after).order_by(ChatMessage.id.asc()).limit(200).all()
        else:
            rows = q.order_by(ChatMessage.id.desc()).limit(CHAT_PAGE).all()[::-1]
        return {"messages": _chat_rows(session, rows, tg_user["id"])}
    finally:
        session.close()


@app.post("/api/chat")
def chat_send(body: ChatBody, tg_user: dict = Depends(current_telegram_user)):
    text = " ".join((body.text or "").split())
    if not text:
        raise HTTPException(status_code=400, detail="پیام خالیه.")
    if len(text) > CHAT_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"پیام حداکثر {CHAT_MAX_LEN} کاراکتر می‌تونه باشه.")
    now = time.time()
    if now - _last_chat_at.get(tg_user["id"], 0) < CHAT_COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail="یکم آروم‌تر 😅 چند ثانیه صبر کن.")
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="هنوز توی بات ثبت‌نام نکردی.")
        if _chat_blocked(user):
            raise HTTPException(status_code=403, detail="🚫 اجازه‌ی چت کردن نداری.")
        _last_chat_at[tg_user["id"]] = now
        msg = ChatMessage(user_id=user.telegram_id, text=text)
        session.add(msg)
        session.commit()
        # قدیمی‌ترها رو پاک می‌کنیم تا جدول بزرگ نشه (۲۰۰۰ پیام آخر نگه داشته می‌شه)
        if msg.id % 100 == 0:
            session.query(ChatMessage).filter(ChatMessage.id < msg.id - 2000).delete()
            session.commit()
        return {"message": _chat_rows(session, [msg], user.telegram_id)[0]}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# صفحه‌ی مینی‌اپ (فقط همین یه فایل عمومیه، نه کل پوشه)
# ---------------------------------------------------------------------------
@app.get("/")
def index_page():
    return FileResponse(BASE_DIR / "index.html", headers=NO_CACHE)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "ruby-miniapp"}
