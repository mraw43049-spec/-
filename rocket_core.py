"""منطق بازی موشک 🚀 (شرط روی ضریب) برای مینی‌اپ (main.py) و کازینوی ربات (bot.py).

بازی چطوری کار می‌کنه؟
- بازیکن با «روب‌پوینت» روی یه ضریب هدف شرط می‌بنده (مثلاً ۱٬۰۰۰٬۰۰۰ روی ×۲).
- موشک بالا می‌ره؛ شمارنده از −۱٫۰۰ شروع می‌شه، از ۰ و ۱ رد می‌شه و بعد با ضریبِ رو‌به‌رشد بالا می‌ره.
  اگه موشک قبل از سقوط به ضریب هدف برسه، بازیکن «ورودی × ضریب هدف» می‌گیره (۱M روی ×۲ ← ۲M)؛ اگه قبلش سقوط کنه، ورودی می‌سوزه.
- مینی‌اپ: پروازهای همگانیِ خودکار؛ هر پرواز ۱۰ ثانیه فرصت شرط‌بندی داره، بعد برای همه پرتاب می‌شه و تو یه ضریب تصادفی سقوط می‌کنه.
  ۱۰ ثانیه بعد از سقوط پرواز بعدی شروع می‌شه. ربات: هر شرط یه پرواز جداست و نتیجه به‌صورت گیف نمایش داده می‌شه.
- نقطه‌ی سقوط سمت سرور با random امن تعیین و تا پایان پرواز برای مینی‌اپ فرستاده نمی‌شه.
- P(رسیدن به ×x) = (1 − EDGE) / x ؛ یعنی بازگشت به بازیکن ≈ ۹۶٪ برای هر ضریب هدف.
- همه‌ی مقدارها با متغیرهای محیطی (Railway) قابل تنظیمه.
"""
import math
import os
import random
import time

from sqlalchemy import text

MIN_ENTRY = int(os.environ.get("ROCKET_MIN_ENTRY", "1000") or 1000)           # روب‌پوینت
MAX_ENTRY = int(os.environ.get("ROCKET_MAX_ENTRY", "5000000") or 5000000)     # سقف شرط: ۵ میلیون روب‌پوینت
WAIT = float(os.environ.get("ROCKET_WAIT", "10") or 10)                        # ثانیه؛ فاصله‌ی سقوط تا پرتاب بعدی (زمان شرط‌بندی)
RISE = float(os.environ.get("ROCKET_RISE", "2") or 2)                          # ثانیه؛ بالا اومدن شمارنده از −۱ تا ۱ (بلند شدن از سکو)
EDGE = float(os.environ.get("ROCKET_EDGE", "0.04") or 0.04)                    # سهم خانه؛ بازگشت به بازیکن ≈ ۹۶٪
MAX_MULT = float(os.environ.get("ROCKET_MAX_MULT", "100") or 100)              # سقف ضریب
MIN_TARGET = float(os.environ.get("ROCKET_MIN_TARGET", "1.1") or 1.1)          # کمترین ضریب هدف
GROWTH = float(os.environ.get("ROCKET_GROWTH", "0.06") or 0.06)                # سرعت رشد ضریب بعد از ۱٫۰۰؛ ×۲ ≈ ۱۱٫۵ ثانیه
BUY_RATE = int(os.environ.get("ROCKET_BUY_RATE", "1500000") or 1500000)        # هر ۱ روب‌تون = چند روب‌پوینت (خرید روب‌تون)
SELL_RATE = int(os.environ.get("ROCKET_SELL_RATE", "1000000") or 1000000)      # فروش ۱ روب‌تون = چند روب‌پوینت
OWNER_ID = int(os.environ.get("ROCKET_OWNER_ID", "7287316708") or 7287316708)  # فعلاً فقط برای همین حساب

_rng = random.SystemRandom()


def roll_crash() -> float:
    """نقطه‌ی سقوط: P(crash >= x) = (1-EDGE)/x ؛ با احتمال ≈EDGE همون اول (×۱٫۰۰) سقوط می‌کنه."""
    r = _rng.random()
    cp = (1.0 - EDGE) / (1.0 - r)
    cp = math.floor(cp * 100) / 100.0
    return max(1.0, cp)


def display_at(t: float) -> float:
    """عددی که روی موشک دیده می‌شه، t ثانیه بعد از پرتاب: از −۱ تا ۱ در RISE ثانیه (نرم)، بعد e^(GROWTH·(t−RISE))."""
    if t <= 0:
        return -1.0
    if t < RISE:
        u = t / RISE
        s = u * u * (3 - 2 * u)
        return -1.0 + 2.0 * s
    try:
        m = math.exp(GROWTH * (t - RISE))
    except OverflowError:
        return MAX_MULT
    return min(MAX_MULT, math.floor(m * 100 + 1e-9) / 100.0)


def hit_time(x: float) -> float:
    """چند ثانیه بعد از پرتاب شمارنده به ضریب x (≥۱) می‌رسه."""
    return RISE + math.log(max(1.0, float(x))) / GROWTH


def flight_len(cp: float) -> float:
    """چند ثانیه بعد از پرتاب موشک به ضریبِ سقوط می‌رسه و می‌ترکه."""
    cp = min(float(cp), MAX_MULT)
    return hit_time(cp) + (0.02 if cp >= MAX_MULT else 0.0)


def valid_target(a) -> bool:
    try:
        a = float(a)
    except Exception:
        return False
    return (MIN_TARGET - 1e-9) <= a <= MAX_MULT + 1e-9 and abs(a * 100 - round(a * 100)) < 1e-6


def payout(bet: int, target: float) -> int:
    """برد = ورودی × ضریب هدف (۱M روی ×۲ ← ۲M)."""
    return int(int(bet) * float(target) + 1e-9)


def is_win(cp: float, target: float) -> bool:
    """اگه موشک قبل از سقوط به هدف برسه بردی (برابر شدن با نقطه‌ی سقوط = سقوط)."""
    cp, a = float(cp), float(target)
    return a < cp or (cp >= MAX_MULT and a <= MAX_MULT)


def evaluate(crash_point: float, target, t: float):
    """وضعیت شرط t ثانیه بعد از پرتاب: ("flying", عدد فعلی) | ("cashed", هدف) | ("crashed", نقطه‌ی سقوط)."""
    cp = float(crash_point)
    if target:
        a = float(target)
        if is_win(cp, a) and t >= hit_time(a):
            return "cashed", a
    if cp < MAX_MULT and t >= flight_len(cp):
        return "crashed", cp
    if cp >= MAX_MULT and t >= flight_len(cp):
        return "cashed", MAX_MULT          # (فقط برای شرط‌های بدون هدف؛ در عمل هدف همیشه هست)
    return "flying", display_at(t)


# ----------------------------------------------------------------- دیتابیس
def ensure_table(engine):
    try:
        sqlite = engine.dialect.name == "sqlite"
        idcol = "INTEGER PRIMARY KEY AUTOINCREMENT" if sqlite else "BIGSERIAL PRIMARY KEY"
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS rocket_rounds ("
                "id BIGINT PRIMARY KEY, crash_point DOUBLE PRECISION NOT NULL, "
                "bet_open_at DOUBLE PRECISION NOT NULL, liftoff_at DOUBLE PRECISION NOT NULL, crash_at DOUBLE PRECISION NOT NULL)"))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS rocket_bets ("
                f"id {idcol}, user_id BIGINT NOT NULL, round_id BIGINT, bet BIGINT NOT NULL, target DOUBLE PRECISION NOT NULL, "
                "status VARCHAR(10) NOT NULL DEFAULT 'active', final_mult DOUBLE PRECISION, crash_point DOUBLE PRECISION, "
                "payout BIGINT NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL, ended_at DOUBLE PRECISION)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS rocket_bets_user_idx ON rocket_bets (user_id, status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS rocket_bets_round_idx ON rocket_bets (round_id)"))
            # فقط یک شرط فعال برای هر کاربر
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS rocket_bets_one_active ON rocket_bets (user_id) WHERE status = 'active'"))
    except Exception as exc:  # noqa: BLE001
        print(f"[rocket] table init failed: {exc}")
    # نسخه‌ی قبلیِ بازی (شرط با روب‌تون): شرط‌های نیمه‌کاره‌ای که مونده باشن برگردونده می‌شن
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT id, user_id, bet FROM rocket_games WHERE status='active'")).fetchall()
            for r in rows:
                conn.execute(text("UPDATE users SET rub_toon = COALESCE(rub_toon, 0) + :b WHERE telegram_id = :u"), {"b": int(r[2]), "u": int(r[1])})
                conn.execute(text("UPDATE rocket_games SET status='cancelled' WHERE id=:i"), {"i": int(r[0])})
    except Exception:  # noqa: BLE001
        pass   # جدول قدیمی وجود نداره؛ مشکلی نیست


def latest_round(session):
    return session.execute(text(
        "SELECT id, crash_point, bet_open_at, liftoff_at, crash_at FROM rocket_rounds ORDER BY id DESC LIMIT 1")).mappings().first()


def get_round(session, rid: int):
    return session.execute(text(
        "SELECT id, crash_point, bet_open_at, liftoff_at, crash_at FROM rocket_rounds WHERE id=:i"), {"i": int(rid)}).mappings().first()


def ensure_round(session, now: float):
    """پروازِ جاری رو برمی‌گردونه؛ اگه پرواز قبلی تموم شده باشه، پرواز بعدی (با WAIT ثانیه شرط‌بندی) ساخته می‌شه."""
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
        "SELECT b.id, b.bet, b.target, b.round_id, r.crash_point, r.liftoff_at "
        "FROM rocket_bets b JOIN rocket_rounds r ON r.id = b.round_id "
        "WHERE b.user_id=:u AND b.status='active' ORDER BY b.id DESC LIMIT 1"), {"u": int(uid)}).mappings().first()


def create_bet(session, uid: int, bet: int, target: float, crash_point: float, now: float, round_id: int):
    session.execute(text(
        "INSERT INTO rocket_bets (user_id, round_id, bet, target, status, crash_point, created_at) "
        "VALUES (:u, :r, :b, :a, 'active', :c, :t)"),
        {"u": int(uid), "r": int(round_id), "b": int(bet), "a": float(target), "c": float(crash_point), "t": float(now)})


def record_solo(session, uid: int, bet: int, target: float, crash_point: float, status: str, final_mult: float, pay: int):
    """بازی داخل ربات (بدون پروازِ همگانی): نتیجه همون لحظه ثبت می‌شه (برای تاریخچه و لیدربورد)."""
    now = time.time()
    session.execute(text(
        "INSERT INTO rocket_bets (user_id, round_id, bet, target, status, final_mult, crash_point, payout, created_at, ended_at) "
        "VALUES (:u, NULL, :b, :a, :s, :m, :c, :p, :t, :t)"),
        {"u": int(uid), "b": int(bet), "a": float(target), "s": status, "m": float(final_mult),
         "c": float(crash_point), "p": int(pay), "t": now})


def finish_bet(session, bet_id: int, status: str, final_mult: float, pay: int, now: float) -> bool:
    """فقط اگه هنوز active باشه تموم می‌شه (جلوگیری از پرداخت دوباره)."""
    res = session.execute(text(
        "UPDATE rocket_bets SET status=:s, final_mult=:m, payout=:p, ended_at=:t WHERE id=:i AND status='active'"),
        {"s": status, "m": float(final_mult), "p": int(pay), "t": float(now), "i": int(bet_id)})
    return (res.rowcount or 0) > 0


def credit_points(session, uid: int, amount: int):
    if amount:
        session.execute(text("UPDATE users SET fox_points = COALESCE(fox_points, 0) + :p WHERE telegram_id = :u"),
                        {"p": int(amount), "u": int(uid)})


def settle_all(session, now: float) -> int:
    """همه‌ی شرط‌های فعالی که تکلیفشون روشن شده (رسیدن به هدف یا سقوط) تسویه و پرداخت می‌شن."""
    rows = session.execute(text(
        "SELECT b.id, b.user_id, b.bet, b.target, r.crash_point, r.liftoff_at "
        "FROM rocket_bets b JOIN rocket_rounds r ON r.id = b.round_id "
        "WHERE b.status='active' AND r.liftoff_at <= :n LIMIT 500"), {"n": float(now)}).mappings().all()
    n = 0
    for g in rows:
        status, m = evaluate(g["crash_point"], g["target"], now - float(g["liftoff_at"]))
        if status == "flying":
            continue
        pay = payout(int(g["bet"]), m) if status == "cashed" else 0
        if finish_bet(session, g["id"], status, m, pay, now):
            credit_points(session, g["user_id"], pay)
            n += 1
    if n:
        session.commit()
    return n


def players(session, round_id: int, limit: int = 40):
    rows = session.execute(text(
        "SELECT b.user_id, b.bet, b.target, b.status, b.final_mult, b.payout, "
        "COALESCE(u.username, u.first_name, 'بازیکن') AS name "
        "FROM rocket_bets b LEFT JOIN users u ON u.telegram_id = b.user_id "
        "WHERE b.round_id=:r AND b.status <> 'cancelled' ORDER BY b.bet DESC, b.id ASC LIMIT :n"),
        {"r": int(round_id), "n": int(limit)}).mappings().all()
    return [{"uid": int(x["user_id"]), "name": str(x["name"]), "bet": int(x["bet"]), "status": x["status"],
             "mult": float(x["final_mult"] or 0), "payout": int(x["payout"] or 0),
             "target": float(x["target"])} for x in rows]


def recent_crashes(session, now: float, n: int = 16):
    rows = session.execute(text(
        "SELECT id, crash_point FROM rocket_rounds WHERE crash_at <= :n ORDER BY id DESC LIMIT :k"),
        {"n": float(now), "k": int(n)}).mappings().all()
    return [{"id": int(r["id"]), "crash": min(float(r["crash_point"]), MAX_MULT)} for r in rows]


def history(session, uid: int, now: float, limit: int = 12):
    """شرط‌های تمام‌شده‌ی کاربر. نقطه‌ی سقوطِ پروازی که هنوز تموم نشده نمایش داده نمی‌شه."""
    rows = session.execute(text(
        "SELECT b.crash_point, b.status, b.final_mult, b.target, b.bet, b.payout, r.crash_at "
        "FROM rocket_bets b LEFT JOIN rocket_rounds r ON r.id = b.round_id "
        "WHERE b.user_id=:u AND b.status IN ('cashed','crashed') ORDER BY b.id DESC LIMIT :n"),
        {"u": int(uid), "n": int(limit)}).mappings().all()
    out = []
    for r in rows:
        done = r["crash_at"] is None or float(r["crash_at"]) <= now
        out.append({"crash": (min(float(r["crash_point"]), MAX_MULT) if done else None), "status": r["status"],
                    "mult": float(r["final_mult"] or 0), "target": float(r["target"]), "bet": int(r["bet"]), "payout": int(r["payout"])})
    return out
