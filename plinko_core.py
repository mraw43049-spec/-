"""منطق مشترک پلینکو بین مینی‌اپ (main.py) و کازینوی ربات (bot.py).
نتیجه همیشه سمت سرور و با random امن تعیین می‌شه؛ مینی‌اپ و گیف فقط همون مسیر رو نمایش می‌دن."""
import os
import random
import time
from datetime import datetime, timezone

from sqlalchemy import text

ROWS = 14                      # ۱۴ ردیف میخ → ۱۵ خانه
MIN_ENTRY = int(os.environ.get("PLINKO_MIN_ENTRY", "1000") or 1000)
MAX_ENTRY = int(os.environ.get("PLINKO_MAX_ENTRY", "5000000") or 5000000)
COOLDOWN = float(os.environ.get("PLINKO_COOLDOWN", "45") or 45)   # ثانیه؛ فاصله‌ی بعد از «اتمام» بازی تا پرتاب بعدی
ANIM_SECONDS = float(os.environ.get("PLINKO_ANIM_SECONDS", "7") or 7)  # مدت نمایش گیف/انیمیشن؛ شمارش ۴۵ ثانیه بعد از تموم شدنش شروع می‌شه

# ضرایب ۱۵ خانه (از چپ به راست). بازگشت به بازیکن: آرام ≈ ۹۸٫۵٪ ، وحشی ≈ ۹۵٫۳٪
# سهمیه‌ی روزانه: آرام ۱۵ ، وحشی ۵۰ ؛ پشتیبانی (ADMIN_IDS) نامحدود
MODES = {
    "calm": {"title": "آرام", "sub": "ضریب‌های ملایم", "daily_limit": 15,
             "mult": [7.5, 4, 2.5, 1.6, 1.3, 1.1, 1, 0.4, 1, 1.1, 1.3, 1.6, 2.5, 4, 7.5]},
    "wild": {"title": "وحشی", "sub": "ضریب‌های درخشان", "daily_limit": 50,
             "mult": [12, 20, 12, 5, 2, 1.3, 0, 0, 0, 1.3, 2, 5, 12, 20, 12]},
}
DEFAULT_MODE = "wild"

_rng = random.SystemRandom()


def roll(rows: int = ROWS):
    """مسیر توپ: هر ردیف ۰=چپ یا ۱=راست؛ خانه‌ی نهایی = تعداد راست‌ها."""
    path = [_rng.getrandbits(1) for _ in range(rows)]
    return path, sum(path)


def payout(amount: int, mult: float) -> int:
    return int(amount * mult + 1e-9)


def ensure_table(engine):
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS plinko_cooldown (user_id BIGINT PRIMARY KEY, ready_at DOUBLE PRECISION NOT NULL DEFAULT 0)"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS plinko_daily_plays (user_id BIGINT NOT NULL, risk VARCHAR(8) NOT NULL, play_day VARCHAR(10) NOT NULL, plays INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, risk, play_day))"))
    except Exception as exc:  # noqa: BLE001
        print(f"[plinko] daily counter table init failed: {exc}")


def cooldown_left(session, uid: int) -> int:
    """ثانیه‌های باقی‌مونده تا پرتاب بعدی (مشترک بین ربات و مینی‌اپ؛ تو دیتابیس ذخیره می‌شه)."""
    ready = session.execute(text("SELECT ready_at FROM plinko_cooldown WHERE user_id=:uid"), {"uid": int(uid)}).scalar()
    left = float(ready or 0) - time.time()
    return int(left) + 1 if left > 0 else 0


def cooldown_start(session, uid: int):
    """بعد از هر پرتاب صدا زده می‌شه: ۴۵ ثانیه بعد از اتمام انیمیشن می‌تونه دوباره بازی کنه."""
    ready = time.time() + ANIM_SECONDS + COOLDOWN
    session.execute(text("INSERT INTO plinko_cooldown (user_id, ready_at) VALUES (:uid, :r) ON CONFLICT (user_id) DO UPDATE SET ready_at = :r"),
                    {"uid": int(uid), "r": ready})


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def daily_used(session, uid: int, mode: str) -> int:
    return int(session.execute(text("SELECT plays FROM plinko_daily_plays WHERE user_id=:uid AND risk=:risk AND play_day=:day"),
                               {"uid": int(uid), "risk": mode, "day": today()}).scalar() or 0)


def daily_inc(session, uid: int, mode: str):
    session.execute(text("INSERT INTO plinko_daily_plays (user_id, risk, play_day, plays) VALUES (:uid, :risk, :day, 1) ON CONFLICT (user_id, risk, play_day) DO UPDATE SET plays = plinko_daily_plays.plays + 1"),
                    {"uid": int(uid), "risk": mode, "day": today()})


def result_text(amount: int, mult: float, pay: int) -> str:
    profit = pay - amount
    if profit > 0:
        head = f"🎉 ضریب ×{mult:g}! {profit:,} روب‌پوینت سود کردی."
    elif profit == 0:
        head = f"😐 ضریب ×{mult:g}؛ پولت برگشت."
    else:
        head = f"😢 ضریب ×{mult:g}؛ {abs(profit):,} روب‌پوینت باختی."
    return head
