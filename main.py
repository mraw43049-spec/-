"""
بک‌اند مینی‌اپ روبی.

این فایل سه کار می‌کنه:
1) initData تلگرام رو چک می‌کنه (auth.py)
2) چندتا API ساده برای خوندن اطلاعات از همون دیتابیس بات اصلی (database.py) می‌ده
3) خودِ فایل‌های فرانت‌اند (پوشه‌ی ../frontend) رو هم سرو می‌کنه،
   یعنی لازم نیست جدا هاستش کنی؛ همین یه سرویس کافیه.

فقط دو متغیر محیطی لازم داره (در فایل .env.example توضیح داده شده):
  BOT_TOKEN      -> همون توکن باتت
  DATABASE_URL   -> همون آدرس دیتابیسی که bot.py استفاده می‌کنه
"""
import os
import sys
from pathlib import Path

# پوشه‌ی ریشه‌ی پروژه (جایی که bot.py و database.py هستن) رو به مسیر پایتون اضافه می‌کنیم
# تا بتونیم database.py رو مستقیم ایمپورت کنیم؛ بدون اینکه هیچ مدلی رو دوباره تعریف کنیم.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from auth import extract_telegram_user, validate_init_data

try:
    from database import Referral, User, get_session
except ImportError as e:
    raise RuntimeError(
        "نتونستم database.py رو پیدا کنم. مطمئن شو ساختار پوشه‌ها همینه:\n"
        "  project-root/\n"
        "    bot.py\n"
        "    database.py\n"
        "    miniapp/backend/main.py   <- همین فایل\n"
    ) from e

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("متغیر محیطی BOT_TOKEN ست نشده.")

app = FastAPI(title="Ruby Fox Mini App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_telegram_user(x_init_data: str = Header(..., alias="X-Init-Data")):
    """هر درخواست باید initData معتبر تلگرام رو توی هدر X-Init-Data بفرسته."""
    parsed = validate_init_data(x_init_data, BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="initData نامعتبر یا منقضی‌شده است.")
    tg_user = extract_telegram_user(parsed)
    if not tg_user or "id" not in tg_user:
        raise HTTPException(status_code=401, detail="اطلاعات کاربر در initData پیدا نشد.")
    return tg_user


def display_name(u: User) -> str:
    return u.username or u.first_name or str(u.telegram_id)


@app.get("/api/profile")
def get_profile(tg_user: dict = Depends(current_telegram_user)):
    session = get_session()
    try:
        user = session.get(User, tg_user["id"])
        if not user:
            raise HTTPException(
                status_code=404,
                detail="هنوز توی بات ثبت‌نام نکردی؛ اول یه پیام به بات بده (مثلاً /start) بعد دوباره مینی‌اپ رو باز کن.",
            )
        rank = (
            session.query(User).filter(User.fox_points > (user.fox_points or 0)).count() + 1
        )
        referral_count = (
            session.query(func.count(Referral.id))
            .filter(Referral.referrer_id == user.telegram_id, Referral.status == "approved")
            .scalar()
            or 0
        )
        return {
            "telegram_id": user.telegram_id,
            "display_name": display_name(user),
            "fox_name": user.fox_name,
            "fox_level": user.fox_level,
            "fox_points": int(user.fox_points or 0),
            "fox_belly": user.fox_belly,
            "fox_belly_capacity": user.fox_belly_capacity,
            "hunt_count": int(user.hunt_count or 0),
            "fox_claim_count": int(user.fox_claim_count or 0),
            "fox_rescued_count": int(user.fox_rescued_count or 0),
            "owl_catch_count": int(user.owl_catch_count or 0),
            "referral_count": int(referral_count),
            "points_rank": rank,
        }
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
                .limit(50)
                .all()
            )
            ids = [r[0] for r in rows]
            users_by_id = {u.telegram_id: u for u in session.query(User).filter(User.telegram_id.in_(ids or [0])).all()}
            entries = [
                {"rank": i + 1, "name": display_name(users_by_id[uid]), "value": cnt}
                for i, (uid, cnt) in enumerate(rows)
                if uid in users_by_id
            ]
            return {"category": "referral", "label": "رفرال", "emoji": "👑", "entries": entries}
        finally:
            session.close()

    if category not in LEADERBOARD_FIELDS:
        raise HTTPException(status_code=400, detail=f"دسته‌ی نامعتبر. یکی از این‌ها باشه: {list(LEADERBOARD_FIELDS) + ['referral']}")

    field_name, label, emoji = LEADERBOARD_FIELDS[category]
    session = get_session()
    try:
        users = (
            session.query(User)
            .order_by(getattr(User, field_name).desc(), User.telegram_id.asc())
            .limit(50)
            .all()
        )
        entries = [
            {"rank": i + 1, "name": display_name(u), "value": int(getattr(u, field_name) or 0)}
            for i, u in enumerate(users)
        ]
        return {"category": category, "label": label, "emoji": emoji, "entries": entries}
    finally:
        session.close()


# فایل‌های فرانت‌اند (index.html / app.js / style.css) رو از همین سرویس سرو می‌کنیم.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
