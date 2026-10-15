"""منطق بازی موشک 🚀 (Crash) برای مینی‌اپ — پروازهای همگانیِ خودکار.

- موشک مثل یک «پرواز مشترک» کار می‌کنه: هر پرواز ۵ ثانیه فرصت شرط‌بندی داره، بعد برای همه پرتاب می‌شه و تو یه ضریبِ تصادفی سقوط می‌کنه.
  بعد از سقوط، ۵ ثانیه‌ی بعد پرواز بعدی خودکار شروع می‌شه. همه‌ی بازیکنانِ یه پرواز برای هم دیده می‌شن.
- نقطه‌ی سقوط همون لحظه‌ی ساخته شدن پرواز با random امن (SystemRandom) سمت سرور تعیین و تو دیتابیس ذخیره می‌شه
  و تا پایان پرواز هیچ‌جا برای مینی‌اپ فرستاده نمی‌شه.
- ضریب فقط تابعی از زمانِ سرور ـه: ضریب(t) = e^(GROWTH * t). برداشت (cashout) و سقوط هم با ساعت سرور بررسی می‌شن.
- پرداخت پله‌ایه: به‌ازای هر ۱٫۰۰ ضریب، یک پله. (حالت step: ورودی × پله ؛ حالت flat: ورودی + (پله − ۱))
- همه‌ی مقدارها با متغیرهای محیطی (Railway) قابل تنظیمه.
"""
import math
import os
import random

from sqlalchemy import text

MIN_ENTRY = int(os.environ.get("ROCKET_MIN_ENTRY", "1000") or 1000)
MAX_ENTRY = int(os.environ.get("ROCKET_MAX_ENTRY", "2500000") or 2500000)
WAIT = float(os.environ.get("ROCKET_WAIT", "5") or 5)                  # ثانیه؛ فاصله‌ی بین سقوط و پرتابِ پرواز بعدی (زمان شرط‌بندی)
EDGE = float(os.environ.get("ROCKET_EDGE", "0.04") or 0.04)           # سهم خانه؛ بازگشت به بازیکن ≈ ۹۶٪
MAX_MULT = float(os.environ.get("ROCKET_MAX_MULT", "100") or 100)     # سقف ضریب؛ رسیدن بهش = برداشت خودکار با همین ضریب
GROWTH = float(os.environ.get("ROCKET_GROWTH", "0.06") or 0.06)       # سرعت رشد ضریب؛ ×۲ ≈ ۱۱٫۵ ثانیه ، ×۱۰ ≈ ۳۸ ثانیه
MIN_HOLD = float(os.environ.get("ROCKET_MIN_HOLD", "1.5") or 1.5)     # ثانیه بعد از پرتاب؛ قبلش «برداشت» دستی ممکن نیست
BUY_RATE = int(os.environ.get("ROCKET_BUY_RATE", "1500000") or 1500000)    # هر ۱ روب‌تون = چند روب‌پوینت (خرید روب‌تون)
SELL_RATE = int(os.environ.get("ROCKET_SELL_RATE", "1000000") or 1000000)  # فروش ۱ روب‌تون = چند روب‌پوینت
PAYOUT_MODE = (os.environ.get("ROCKET_PAYOUT_MODE", "step") or "step").strip().lower()
if PAYOUT_MODE not in ("step", "flat"):
    PAYOUT_MODE = "step"
MIN_AUTO = 2                                                           # کمترین ضریب برداشت خودکار (عدد صحیح)

_rng = random.SystemRandom()


def mult_at(t: float) -> float:
    """ضریب در t ثانیه بعد از پرتاب (دو رقم اعشار، رو به پایین)."""
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


def flight_len(cp: float) -> float:
    """چند ثانیه بعد از پرتاب موشک می‌رسه به ضریبِ سقوط."""
    cp = min(float(cp), MAX_MULT)
    return math.log(cp) / GROWTH + (0.02 if cp >= MAX_MULT else 0.0)


def steps(mult: float) -> int:
    """تعداد پله‌های کامل ضریب (هر ۱٫۰۰ = یک پله؛ از ×۱٫۰۰ = پله‌ی اول)."""
    return max(1, int(math.floor(float(mult) + 1e-9)))


def payout(bet: int, mult: float) -> int:
    n = steps(mult)
    if PAYOUT_MODE == "flat":
        return int(bet) + n - 1      # هر ۱٫۰۰ ضریب = دقیقاً ۱ روب‌تون سود (مستقل از مبلغ ورودی)
    return int(bet) * n              # هر ۱٫۰۰ ضریب = ۱ برابرِ ورودی؛ بین پله‌ها چیزی اضافه نمی‌شه


def valid_auto(a) -> bool:
    try:
        a = float(a)
    except Exception:
        return False
    return abs(a - round(a)) < 1e-9 and MIN_AUTO <= a <= MAX_MULT


def evaluate(crash_point: float, auto_cash, t: float):
    """وضعیت شرط در t ثانیه بعد از پرتاب.
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


# ----------------------------------------------------------------- دیتابیس
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
            # فقط یک شرط فعال برای هر کاربر
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS rocket_one_active ON rocket_games (user_id) WHERE status = 'active'"))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS rocket_rounds ("
                "id BIGINT PRIMARY KEY, crash_point DOUBLE PRECISION NOT NULL, "
                "bet_open_at DOUBLE PRECISION NOT NULL, liftoff_at DOUBLE PRECISION NOT NULL, crash_at DOUBLE PRECISION NOT NULL)"))
    except Exception as exc:  # noqa: BLE001
        print(f"[rocket] table init failed: {exc}")
    try:   # ستونِ پروازِ هر شرط (دیتابیس‌های قدیمی)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE rocket_games ADD COLUMN round_id BIGINT"))
    except Exception:  # noqa: BLE001
        pass   # از قبل هست
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS rocket_round_idx ON rocket_games (round_id)"))
    except Exception as exc:  # noqa: BLE001
        print(f"[rocket] round index failed: {exc}")


def latest_round(session):
    return session.execute(text(
        "SELECT id, crash_point, bet_open_at, liftoff_at, crash_at FROM rocket_rounds ORDER BY id DESC LIMIT 1")).mappings().first()


def get_round(session, rid: int):
    return session.execute(text(
        "SELECT id, crash_point, bet_open_at, liftoff_at, crash_at FROM rocket_rounds WHERE id=:i"), {"i": int(rid)}).mappings().first()


def ensure_round(session, now: float):
    """پروازِ جاری رو برمی‌گردونه؛ اگه پرواز قبلی تموم شده باشه، پرواز بعدی (با ۵ ثانیه شرط‌بندی) ساخته می‌شه."""
    r = latest_round(session)
    if r is not None and float(r["crash_at"]) > now:
        return r
    if r is not None:
        nl = float(r["crash_at"]) + WAIT
        if nl >= now:
            open_at, lift = float(r["crash_at"]), nl
        else:                       # مدتی کسی نبوده؛ شمارش از اول
            open_at, lift = now, now + WAIT
        nid = int(r["id"]) + 1
    else:
        open_at, lift, nid = now, now + WAIT, 1
    cp = roll_crash()
    session.execute(text(
        "INSERT INTO rocket_rounds (id, crash_point, bet_open_at, liftoff_at, crash_at) "
        "VALUES (:i, :c, :o, :l, :e) ON CONFLICT (id) DO NOTHING"),
        {"i": nid, "c": float(cp), "o": float(open_at), "l": float(lift), "e": float(lift + flight_len(cp))})
    return latest_round(session)


def get_active(session, uid: int):
    return session.execute(text(
        "SELECT g.id, g.bet, g.auto_cash, g.started_at, g.round_id, "
        "COALESCE(r.crash_point, g.crash_point) AS crash_point, COALESCE(r.liftoff_at, g.started_at) AS liftoff_at "
        "FROM rocket_games g LEFT JOIN rocket_rounds r ON r.id = g.round_id "
        "WHERE g.user_id=:u AND g.status='active' ORDER BY g.id DESC LIMIT 1"), {"u": int(uid)}).mappings().first()


def create_game(session, uid: int, bet: int, crash_point: float, auto_cash, now: float, round_id: int):
    session.execute(text(
        "INSERT INTO rocket_games (user_id, bet, crash_point, auto_cash, started_at, status, round_id) "
        "VALUES (:u, :b, :c, :a, :t, 'active', :r)"),
        {"u": int(uid), "b": int(bet), "c": float(crash_point), "a": auto_cash, "t": float(now), "r": int(round_id)})


def finish_game(session, game_id: int, status: str, final_mult: float, pay: int, now: float) -> bool:
    """فقط اگه هنوز active باشه تموم می‌شه (جلوگیری از پرداخت دوباره)."""
    res = session.execute(text(
        "UPDATE rocket_games SET status=:s, final_mult=:m, payout=:p, ended_at=:t WHERE id=:i AND status='active'"),
        {"s": status, "m": float(final_mult), "p": int(pay), "t": float(now), "i": int(game_id)})
    return (res.rowcount or 0) > 0


def credit(session, uid: int, amount: int):
    if amount:
        session.execute(text("UPDATE users SET rub_toon = COALESCE(rub_toon, 0) + :p WHERE telegram_id = :u"),
                        {"p": int(amount), "u": int(uid)})


def settle_all(session, now: float) -> int:
    """همه‌ی شرط‌های فعالی که تکلیفشون روشن شده (سقوط، یا رسیدن به برداشت خودکار) تسویه و پرداخت می‌شن."""
    rows = session.execute(text(
        "SELECT g.id, g.user_id, g.bet, g.auto_cash, "
        "COALESCE(r.crash_point, g.crash_point) AS crash_point, COALESCE(r.liftoff_at, g.started_at) AS liftoff_at "
        "FROM rocket_games g LEFT JOIN rocket_rounds r ON r.id = g.round_id "
        "WHERE g.status='active' AND COALESCE(r.liftoff_at, g.started_at) <= :n LIMIT 500"), {"n": float(now)}).mappings().all()
    n = 0
    for g in rows:
        status, m = evaluate(g["crash_point"], g["auto_cash"], now - float(g["liftoff_at"]))
        if status == "flying":
            continue
        pay = payout(int(g["bet"]), m) if status == "cashed" else 0
        if finish_game(session, g["id"], status, m, pay, now):
            credit(session, g["user_id"], pay)
            n += 1
    if n:
        session.commit()
    return n


def players(session, round_id: int, limit: int = 40):
    rows = session.execute(text(
        "SELECT g.user_id, g.bet, g.auto_cash, g.status, g.final_mult, g.payout, "
        "COALESCE(u.username, u.first_name, 'بازیکن') AS name "
        "FROM rocket_games g LEFT JOIN users u ON u.telegram_id = g.user_id "
        "WHERE g.round_id=:r AND g.status <> 'cancelled' ORDER BY g.bet DESC, g.id ASC LIMIT :n"),
        {"r": int(round_id), "n": int(limit)}).mappings().all()
    return [{"uid": int(x["user_id"]), "name": str(x["name"]), "bet": int(x["bet"]), "status": x["status"],
             "mult": float(x["final_mult"] or 0), "payout": int(x["payout"] or 0),
             "auto": (float(x["auto_cash"]) if x["auto_cash"] else None)} for x in rows]


def recent_crashes(session, now: float, n: int = 16):
    rows = session.execute(text(
        "SELECT id, crash_point FROM rocket_rounds WHERE crash_at <= :n ORDER BY id DESC LIMIT :k"),
        {"n": float(now), "k": int(n)}).mappings().all()
    return [{"id": int(r["id"]), "crash": min(float(r["crash_point"]), MAX_MULT)} for r in rows]


def history(session, uid: int, now: float, limit: int = 12):
    """پروازهای تمام‌شده‌ی کاربر. نقطه‌ی سقوطِ پروازی که هنوز تموم نشده (کاربر زودتر برداشت کرده) نمایش داده نمی‌شه."""
    rows = session.execute(text(
        "SELECT g.crash_point, g.status, g.final_mult, g.bet, g.payout, r.crash_at "
        "FROM rocket_games g LEFT JOIN rocket_rounds r ON r.id = g.round_id "
        "WHERE g.user_id=:u AND g.status IN ('cashed','crashed') ORDER BY g.id DESC LIMIT :n"),
        {"u": int(uid), "n": int(limit)}).mappings().all()
    out = []
    for r in rows:
        done = r["crash_at"] is None or float(r["crash_at"]) <= now
        out.append({"crash": (min(float(r["crash_point"]), MAX_MULT) if done else None), "status": r["status"],
                    "mult": float(r["final_mult"] or 0), "bet": int(r["bet"]), "payout": int(r["payout"])})
    return out
