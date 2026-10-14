"""منطق بازی موشک 🚀 (Crash) برای مینی‌اپ.

- نقطه‌ی سقوط موشک همون لحظه‌ی شروع بازی با random امن (SystemRandom) سمت سرور تعیین و تو دیتابیس ذخیره می‌شه
  و تا پایان بازی هیچ‌جا برای مینی‌اپ فرستاده نمی‌شه.
- ضریب فقط تابعی از زمانِ سرور ـه: ضریب(t) = e^(GROWTH * t). برداشت (cashout) و سقوط هم با ساعت سرور بررسی می‌شن.
- همه‌ی مقدارها با متغیرهای محیطی (Railway) قابل تنظیمه.
"""
import math
import os
import random
import time

from sqlalchemy import text

MIN_ENTRY = int(os.environ.get("ROCKET_MIN_ENTRY", "1000") or 1000)
MAX_ENTRY = int(os.environ.get("ROCKET_MAX_ENTRY", "2500000") or 2500000)
COOLDOWN = float(os.environ.get("ROCKET_COOLDOWN", "20") or 20)       # ثانیه؛ بعد از اتمام هر بازی
EDGE = float(os.environ.get("ROCKET_EDGE", "0.04") or 0.04)           # سهم خانه؛ بازگشت به بازیکن ≈ ۹۶٪
MAX_MULT = float(os.environ.get("ROCKET_MAX_MULT", "100") or 100)     # سقف ضریب؛ رسیدن بهش = برداشت خودکار با همین ضریب
GROWTH = float(os.environ.get("ROCKET_GROWTH", "0.06") or 0.06)       # سرعت رشد ضریب؛ ×۲ ≈ ۱۱٫۵ ثانیه ، ×۱۰ ≈ ۳۸ ثانیه
MIN_HOLD = float(os.environ.get("ROCKET_MIN_HOLD", "1.5") or 1.5)     # ثانیه؛ تا موشک از سکو بلند نشده «برداشت» دستی ممکن نیست (جلوگیری از پس‌گرفتن فوریِ ورودی)
BUY_RATE = int(os.environ.get("ROCKET_BUY_RATE", "1500000") or 1500000)    # هر ۱ روب‌تون = چند روب‌پوینت (خرید روب‌تون)
SELL_RATE = int(os.environ.get("ROCKET_SELL_RATE", "1000000") or 1000000)  # فروش ۱ روب‌تون = چند روب‌پوینت
MIN_AUTO = 1.1                                                         # کمترین ضریب برداشت خودکار

_rng = random.SystemRandom()


def mult_at(t: float) -> float:
    """ضریب در t ثانیه بعد از شروع (دو رقم اعشار، رو به پایین)."""
    if t <= 0:
        return 1.0
    try:
        m = math.exp(GROWTH * t)
    except OverflowError:
        return MAX_MULT
    return math.floor(m * 100 + 1e-9) / 100.0


def roll_crash() -> float:
    """نقطه‌ی سقوط: P(crash >= x) = (1-EDGE)/x ؛ با احتمال EDGE همون لحظه‌ی اول (×۱٫۰۰) سقوط می‌کنه."""
    r = _rng.random()
    cp = (1.0 - EDGE) / (1.0 - r)
    cp = math.floor(cp * 100) / 100.0
    return max(1.0, cp)


def payout(bet: int, mult: float) -> int:
    return int(bet * mult + 1e-9)


def evaluate(crash_point: float, auto_cash, t: float):
    """وضعیت بازی در t ثانیه بعد از شروع.
    برمی‌گردونه: ("flying", cur) یا ("cashed", ضریب) یا ("crashed", crash_point)."""
    cur = mult_at(t)
    cp = float(crash_point)
    if auto_cash:
        a = float(auto_cash)
        if MIN_AUTO <= a <= MAX_MULT and a < cp and cur >= a:
            return "cashed", a
    if cp >= MAX_MULT:
        if cur >= MAX_MULT:
            return "cashed", MAX_MULT
    elif cur >= cp:
        return "crashed", cp
    return "flying", min(cur, MAX_MULT)


def ensure_table(engine):
    try:
        sqlite = engine.dialect.name == "sqlite"
        idcol = "INTEGER PRIMARY KEY AUTOINCREMENT" if sqlite else "BIGSERIAL PRIMARY KEY"
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS rocket_games ("
                f"id {idcol}, user_id BIGINT NOT NULL, bet BIGINT NOT NULL, "
                "crash_point DOUBLE PRECISION NOT NULL, auto_cash DOUBLE PRECISION, "
                "started_at DOUBLE PRECISION NOT NULL, status VARCHAR(10) NOT NULL DEFAULT 'active', "
                "final_mult DOUBLE PRECISION, payout BIGINT NOT NULL DEFAULT 0, ended_at DOUBLE PRECISION)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS rocket_user_idx ON rocket_games (user_id, status)"))
            # فقط یک بازی فعال برای هر کاربر
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS rocket_one_active ON rocket_games (user_id) WHERE status = 'active'"))
    except Exception as exc:  # noqa: BLE001
        print(f"[rocket] table init failed: {exc}")


def get_active(session, uid: int):
    return session.execute(text(
        "SELECT id, bet, crash_point, auto_cash, started_at FROM rocket_games "
        "WHERE user_id=:u AND status='active' ORDER BY id DESC LIMIT 1"), {"u": int(uid)}).mappings().first()


def create_game(session, uid: int, bet: int, crash_point: float, auto_cash, now: float):
    session.execute(text(
        "INSERT INTO rocket_games (user_id, bet, crash_point, auto_cash, started_at, status) "
        "VALUES (:u, :b, :c, :a, :t, 'active')"),
        {"u": int(uid), "b": int(bet), "c": float(crash_point), "a": auto_cash, "t": float(now)})


def finish_game(session, game_id: int, status: str, final_mult: float, pay: int, now: float) -> bool:
    """فقط اگه هنوز active باشه تموم می‌شه (جلوگیری از پرداخت دوباره)."""
    res = session.execute(text(
        "UPDATE rocket_games SET status=:s, final_mult=:m, payout=:p, ended_at=:t WHERE id=:i AND status='active'"),
        {"s": status, "m": float(final_mult), "p": int(pay), "t": float(now), "i": int(game_id)})
    return (res.rowcount or 0) > 0


def cooldown_left(session, uid: int, now: float) -> int:
    last = session.execute(text("SELECT MAX(ended_at) FROM rocket_games WHERE user_id=:u"), {"u": int(uid)}).scalar()
    left = float(last or 0) + COOLDOWN - now
    return int(left) + 1 if left > 0 else 0


def history(session, uid: int, limit: int = 12):
    rows = session.execute(text(
        "SELECT crash_point, status, final_mult, bet, payout FROM rocket_games "
        "WHERE user_id=:u AND status <> 'active' ORDER BY id DESC LIMIT :n"), {"u": int(uid), "n": int(limit)}).mappings().all()
    return [{"crash": min(float(r["crash_point"]), MAX_MULT), "status": r["status"],
             "mult": float(r["final_mult"] or 0), "bet": int(r["bet"]), "payout": int(r["payout"])} for r in rows]
