"""
Ruby Fox Mini App API.
- Validates Telegram WebApp initData.
- Reads the same User/Referral tables used by the main bot.
- Exposes a richer fox/profile API without replacing or migrating the bot database.
- Serves the Mini App frontend from the same FastAPI service.
"""
import os
import sys
import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, inspect

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from auth import extract_telegram_user, validate_init_data

try:
    from database import Referral, User, get_session
except ImportError as e:
    raise RuntimeError(
        "database.py پیدا نشد. ساختار باید project-root/database.py و "
        "project-root/miniapp/backend/main.py باشد."
    ) from e

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("متغیر محیطی BOT_TOKEN ست نشده.")

app = FastAPI(title="Ruby Fox Mini App API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_telegram_user(x_init_data: str = Header(..., alias="X-Init-Data")):
    parsed = validate_init_data(x_init_data, BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="initData نامعتبر یا منقضی‌شده است.")
    tg_user = extract_telegram_user(parsed)
    if not tg_user or "id" not in tg_user:
        raise HTTPException(status_code=401, detail="اطلاعات کاربر در initData پیدا نشد.")
    return tg_user


def display_name(u: User) -> str:
    return getattr(u, "username", None) or getattr(u, "first_name", None) or str(u.telegram_id)


def model_data(u: User) -> dict[str, Any]:
    """Return only mapped User columns; never expose secrets."""
    try:
        mapper = inspect(User)
        return {attr.key: getattr(u, attr.key, None) for attr in mapper.column_attrs}
    except Exception:
        return dict(getattr(u, "__dict__", {}))


def first_value(data: dict[str, Any], names: list[str], default=None):
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def normalize_skin(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {
            "name": raw.get("name") or raw.get("title") or raw.get("id") or "اسکین فعال",
            "image": raw.get("image") or raw.get("image_url") or raw.get("url"),
            "gender": raw.get("gender"),
            "id": raw.get("id"),
        }
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {
                "name": parsed.get("name") or parsed.get("title") or parsed.get("id") or "اسکین فعال",
                "image": parsed.get("image") or parsed.get("image_url") or parsed.get("url"),
                "gender": parsed.get("gender"),
                "id": parsed.get("id"),
            }
    except Exception:
        pass
    return {"name": text, "image": None, "gender": None, "id": text}


def build_fox_payload(user: User) -> dict[str, Any]:
    data = model_data(user)

    gender = first_value(data, [
        "fox_gender", "gender", "fox_sex", "sex"
    ])
    skin = first_value(data, [
        "active_skin", "fox_skin", "equipped_skin", "current_skin",
        "selected_skin", "skin"
    ])
    skin_image = first_value(data, [
        "active_skin_image", "fox_skin_image", "equipped_skin_image",
        "skin_image", "current_skin_image"
    ])
    emoji = first_value(data, [
        "fox_emoji", "active_emoji", "equipped_emoji", "selected_emoji"
    ])

    # Preserve any useful skin-related fields already present in the real User model.
    skin_fields = {
        k: v for k, v in data.items()
        if any(token in k.lower() for token in ("skin", "emoji"))
        and "token" not in k.lower()
    }

    return {
        "name": first_value(data, ["fox_name"], "مکار"),
        "level": int(first_value(data, ["fox_level"], 0) or 0),
        "points": int(first_value(data, ["fox_points"], 0) or 0),
        "belly": first_value(data, ["fox_belly"], 0),
        "belly_capacity": first_value(data, ["fox_belly_capacity"], 15),
        "gender": gender,
        "active_skin": normalize_skin(skin) if skin is not None else None,
        "active_skin_image": skin_image,
        "active_emoji": emoji,
        "skin_fields": skin_fields,
    }


@app.get("/api/profile")
def get_profile(tg_user: dict = Depends(current_telegram_user)):
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(
                status_code=404,
                detail="هنوز توی بات ثبت‌نام نکردی؛ اول /start بزن و دوباره مینی‌اپ را باز کن.",
            )

        fox_points = int(getattr(user, "fox_points", 0) or 0)
        rank = session.query(User).filter(User.fox_points > fox_points).count() + 1

        referral_count = 0
        if Referral is not None:
            referral_count = (
                session.query(func.count(Referral.id))
                .filter(
                    Referral.referrer_id == user.telegram_id,
                    Referral.status == "approved",
                )
                .scalar() or 0
            )

        fox = build_fox_payload(user)
        return {
            "telegram_id": user.telegram_id,
            "display_name": display_name(user),
            "fox": fox,
            # Backwards-compatible keys for old frontend versions.
            "fox_name": fox["name"],
            "fox_level": fox["level"],
            "fox_points": fox["points"],
            "fox_belly": fox["belly"],
            "fox_belly_capacity": fox["belly_capacity"],
            "hunt_count": int(getattr(user, "hunt_count", 0) or 0),
            "fox_claim_count": int(getattr(user, "fox_claim_count", 0) or 0),
            "fox_rescued_count": int(getattr(user, "fox_rescued_count", 0) or 0),
            "owl_catch_count": int(getattr(user, "owl_catch_count", 0) or 0),
            "referral_count": int(referral_count),
            "points_rank": rank,
        }
    finally:
        session.close()


@app.get("/api/fox")
def get_fox(tg_user: dict = Depends(current_telegram_user)):
    """Dedicated endpoint used by the Mini App fox card."""
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="کاربر در دیتابیس بات پیدا نشد.")
        return build_fox_payload(user)
    finally:
        session.close()


LEADERBOARD_FIELDS = {
    "points": ("fox_points", "روب‌پوینت", "💰"),
    "hunt": ("hunt_count", "شکار", "⚔️"),
    "owl": ("owl_catch_count", "جغد", "🦉"),
    "rescued": ("fox_rescued_count", "روباه نجات‌یافته", "🦊"),
}


@app.get("/api/leaderboard")
def get_leaderboard(category: str = "points", tg_user: dict = Depends(current_telegram_user)):
    if category == "referral":
        session = get_session()
        try:
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
                {"rank": i + 1, "name": display_name(users_by_id[uid]), "value": cnt}
                for i, (uid, cnt) in enumerate(rows) if uid in users_by_id
            ]
            return {"category": "referral", "label": "رفرال", "emoji": "👑", "entries": entries}
        finally:
            session.close()

    if category not in LEADERBOARD_FIELDS:
        raise HTTPException(status_code=400, detail="دسته‌ی لیدربرد نامعتبر است.")

    field_name, label, emoji = LEADERBOARD_FIELDS[category]
    session = get_session()
    try:
        users = (
            session.query(User)
            .order_by(getattr(User, field_name).desc(), User.telegram_id.asc())
            .limit(50).all()
        )
        entries = [
            {
                "rank": i + 1,
                "name": display_name(u),
                "value": int(getattr(u, field_name) or 0),
            }
            for i, u in enumerate(users)
        ]
        return {"category": category, "label": label, "emoji": emoji, "entries": entries}
    finally:
        session.close()


# The bot's real economy/game handlers remain the source of truth.
# We intentionally do NOT mutate User here because database.py/bot.py were not
# supplied in this upload; blindly changing balances/cooldowns could corrupt data.
@app.get("/api/health")
def health():
    return {"ok": True, "service": "ruby-miniapp", "version": "2.0"}


# Flat layout: index.html sits next to main.py. Only this one file is served
# (never mount the whole folder, it would expose bot.py / config.py).
INDEX_FILE = Path(__file__).resolve().parent / "index.html"


@app.get("/")
def index():
    return FileResponse(str(INDEX_FILE), media_type="text/html")
