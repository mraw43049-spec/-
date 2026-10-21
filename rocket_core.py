# -*- coding: utf-8 -*-
"""موشک همگانی (Crash) برای مینی‌اپ + بات.

ورود ثابت: ۵۰٬۰۰۰ روب‌پوینت برای هر پرواز (چه با ضریب هدف، چه بدون ضریب).
دو حالت برداشت:
  ۱) با ضریب هدف: به محض رسیدن موشک به هدف، خودکار برداشت می‌شود.
  ۲) بدون ضریب (target = 0): بازیکن خودش وسط پرواز «برداشت» می‌زند؛ اگر موشک به سقف برسد خودکار در سقف برداشت می‌شود.
سقف ضریب: ×۱۰۰.
هر ضریب کامل که بازیکن با هدفش به آن برسد = ۱ ستاره.
تبدیل: ۵۰ ستاره → ۱٬۰۰۰٬۰۰۰ روب‌پوینت.
"""
from __future__ import annotations

import math
import os
import random
import time
from typing import Any, Optional

from sqlalchemy import text

# ---------- تنظیمات (قابل override با env روی Railway) ----------
MIN_ENTRY = int(os.environ.get("ROCKET_MIN_ENTRY", "50000"))
MAX_ENTRY = int(os.environ.get("ROCKET_MAX_ENTRY", "50000"))  # ثابت ۵۰هزار
MAX_MULT = float(os.environ.get("ROCKET_MAX_MULT", "100"))  # سقف ضریب موشک
MIN_TARGET = float(os.environ.get("ROCKET_MIN_TARGET", "1.2"))
EDGE = float(os.environ.get("ROCKET_EDGE", "0.04"))  # حاشیه خانه
GROWTH = float(os.environ.get("ROCKET_GROWTH", "0.06"))  # شیب رشد ضریب
RISE = float(os.environ.get("ROCKET_RISE", "12"))  # ثانیه تقریبی تا سقف
START = float(os.environ.get("ROCKET_START", "-1.5"))
WAIT = float(os.environ.get("ROCKET_WAIT", "10"))  # ثانیه شرط‌بندی
COOLDOWN = float(os.environ.get("ROCKET_COOLDOWN", "10"))  # بین پروازها
BUY_RATE = int(os.environ.get("ROCKET_BUY_RATE", "1000"))  # روب‌پوینت برای ۱ روب‌تون
SELL_RATE = int(os.environ.get("ROCKET_SELL_RATE", "800"))

# سیستم ستاره
STARS_PER_MULT = 1  # هر ۱ ضریب = ۱ ستاره
STARS_REDEEM_MIN = 50
STARS_REDEEM_REWARD = 1_000_000  # روب‌پوینت


def payout(amount: int, target: float) -> int:
    """پرداخت کلاسیک: شرط × ضریب هدف (برای سازگاری با بات)."""
    return int(math.floor(amount * float(target)))


def valid_target(t: float) -> bool:
    try:
        t = float(t)
    except (TypeError, ValueError):
        return False
    if t < MIN_TARGET - 1e-9 or t > MAX_MULT + 1e-9:
        return False
    # حداکثر دو رقم اعشار
    return abs(round(t, 2) - t) < 1e-9


def is_manual(target) -> bool:
    """شرط بدون ضریب هدف (برداشت دستی) با target <= 0 ذخیره می‌شود."""
    try:
        return float(target or 0) <= 1e-9
    except (TypeError, ValueError):
        return True


def display_mult(elapsed: float) -> float:
    """ضریب نمایشی دقیقاً مثل مینی‌اپ: گرد به پایین تا دو رقم اعشار و حداکثر MAX_MULT."""
    m = mult_at_elapsed(elapsed)
    return min(MAX_MULT, math.floor(m * 100 + 1e-9) / 100)


def roll_crash() -> float:
    """نقطه سقوط با حاشیه خانه (فرمول استاندارد crash):
    P(cp >= x) = (1 - EDGE) / x برای x >= 1، و با احتمال EDGE موشک همان ×۱ سقوط می‌کند.
    (قبلاً یک شاخهٔ اضافهٔ «r < EDGE → ×۱» بالاترین بخش توزیع را هم به سقوط فوری تبدیل می‌کرد؛
    نتیجه این بود که هیچ پروازی از حدود ×۲۴ بالاتر نمی‌رفت و سقف ×۱۰۰ عملاً غیرقابل‌رسیدن بود.)"""
    r = 1.0 - random.random()          # در بازهٔ (0, 1]
    cp = (1.0 - EDGE) / max(1e-12, r)  # r >= 1-EDGE → cp <= 1 → همان ×۱ (سقوط فوری با احتمال EDGE)
    return min(MAX_MULT * 1.01, max(1.0, cp))


def is_win(crash_point: float, target: float) -> bool:
    return float(crash_point) + 1e-12 >= float(target)


def mult_at_elapsed(elapsed: float) -> float:
    """ضریب نمایشی بر اساس زمان از liftoff؛ دقیقاً هم‌ساعت با مینی‌اپ:
    RISE ثانیه اول از START تا ×۱ بالا می‌رود، بعدش نمایی رشد می‌کند."""
    if elapsed <= 0:
        return START
    if elapsed < RISE:
        u = elapsed / RISE
        return START + (1.0 - START) * (u * u * (3 - 2 * u))
    return min(MAX_MULT, math.exp(GROWTH * (elapsed - RISE)))


def elapsed_for_mult(mult: float) -> float:
    """چند ثانیه بعد از liftoff ضریب به mult می‌رسد (با احتساب RISE ثانیه‌ی اول)."""
    return RISE + math.log(max(1.0, mult)) / max(1e-9, GROWTH)


def ensure_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rocket_rounds (
                id SERIAL PRIMARY KEY,
                crash_point DOUBLE PRECISION NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                liftoff_at DOUBLE PRECISION NOT NULL,
                crash_at DOUBLE PRECISION NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rocket_bets (
                id SERIAL PRIMARY KEY,
                round_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                bet INTEGER NOT NULL,
                target DOUBLE PRECISION NOT NULL,
                crash_point DOUBLE PRECISION NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                final_mult DOUBLE PRECISION,
                payout INTEGER NOT NULL DEFAULT 0,
                stars_awarded INTEGER NOT NULL DEFAULT 0,
                created_at DOUBLE PRECISION NOT NULL,
                ended_at DOUBLE PRECISION,
                UNIQUE (round_id, user_id)
            )
        """))
    # مهاجرت: اگر جدول‌ها از نسخه‌ی قدیمی مانده باشند ستون‌های جاافتاده اضافه می‌شن
    # (هر دستور تراکنش جدا دارد تا خطای یکی بقیه را خراب نکند)
    stmts = [
        "ALTER TABLE rocket_rounds ADD COLUMN IF NOT EXISTS crash_point DOUBLE PRECISION NOT NULL DEFAULT 1",
        "ALTER TABLE rocket_rounds ADD COLUMN IF NOT EXISTS created_at DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_rounds ADD COLUMN IF NOT EXISTS liftoff_at DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_rounds ADD COLUMN IF NOT EXISTS crash_at DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS round_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS bet INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS target DOUBLE PRECISION NOT NULL DEFAULT 2",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS crash_point DOUBLE PRECISION NOT NULL DEFAULT 1",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS final_mult DOUBLE PRECISION",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS payout INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS stars_awarded INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS created_at DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS ended_at DOUBLE PRECISION",
        "CREATE INDEX IF NOT EXISTS ix_rocket_bets_user ON rocket_bets (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_rocket_bets_status ON rocket_bets (status)",
    ]
    for st in stmts:
        try:
            with engine.begin() as conn:
                conn.execute(text(st))
        except Exception:
            pass

    # ستون‌های قدیمی که کد فعلی پرشون نمی‌کنه ولی NOT NULL و بدون پیش‌فرضن، INSERT رو با خطای ۵۰۰ می‌شکنن.
    # فقط NOT NULL اون ستون‌ها برداشته می‌شه (چیزی حذف نمی‌شه).
    try:
        if engine.dialect.name == "postgresql":
            # ستون id بدون شمارندهٔ خودکار (جدول قدیمی) → INSERT با id=NULL می‌شکنه؛ شمارنده ساخته و وصل می‌شه.
            for tbl in ("rocket_rounds", "rocket_bets"):
                try:
                    with engine.begin() as conn:
                        has_default = conn.execute(text(
                            "SELECT column_default FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = 'id'"),
                            {"t": tbl}).all()
                        if has_default and has_default[0][0] is None:
                            seq = tbl + "_id_seq"
                            conn.execute(text('CREATE SEQUENCE IF NOT EXISTS "%s"' % seq))
                            conn.execute(text('ALTER TABLE "%s" ALTER COLUMN id SET DEFAULT nextval(\'"%s"\')' % (tbl, seq)))
                            conn.execute(text('SELECT setval(\'"%s"\', COALESCE((SELECT MAX(id) FROM "%s"), 0) + 1, false)' % (seq, tbl)))
                except Exception:
                    pass
            expected = {
                "rocket_rounds": {"id", "crash_point", "created_at", "liftoff_at", "crash_at"},
                "rocket_bets": {"id", "round_id", "user_id", "bet", "target", "crash_point", "status", "final_mult",
                                "payout", "stars_awarded", "created_at", "ended_at"},
            }
            with engine.begin() as conn:
                legacy = conn.execute(text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name IN ('rocket_rounds','rocket_bets') "
                    "AND is_nullable = 'NO' AND column_default IS NULL")).all()
            for t, col in legacy:
                if col in expected.get(t, set()):
                    continue
                try:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE "%s" ALTER COLUMN "%s" DROP NOT NULL' % (t, col)))
                except Exception:
                    pass
    except Exception:
        pass


def _row(m) -> dict:
    return dict(m) if m is not None else None


_ROUND_COLS = "id, crash_point, created_at, liftoff_at, crash_at"


def _current_round(session, now: float):
    # فقط دورهای همگانی (دور تک‌نفره‌ی بات: crash_at == liftoff_at)
    return session.execute(text(
        "SELECT " + _ROUND_COLS + " FROM rocket_rounds "
        "WHERE crash_at > :n AND crash_at > liftoff_at ORDER BY id DESC LIMIT 1"), {"n": now}).mappings().first()


def ensure_round(session, now: float) -> dict:
    """دور فعال (شرط‌بندی یا پرواز) را برگردان؛ اگر نبود دور جدید بساز.
    دور جدید همیشه یک ردیف واقعی است تا شرط‌ها به همان دور بخورند، نه دور قبلی."""
    row = _current_round(session, now)
    if row:
        return _row(row)

    # جلوگیری از ساخت دو دور هم‌زمان (چند کاربر هم‌زمان poll می‌کنند)
    try:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(884201)"))
            row = _current_round(session, now)
            if row:
                return _row(row)
    except Exception:
        pass

    last = session.execute(text(
        "SELECT crash_at FROM rocket_rounds WHERE crash_at > liftoff_at ORDER BY id DESC LIMIT 1")).mappings().first()
    liftoff = now + WAIT
    if last:
        # بین سقوط قبلی و پرتاب بعدی حداقل COOLDOWN ثانیه فاصله
        liftoff = max(liftoff, float(last["crash_at"]) + COOLDOWN)

    cp = roll_crash()
    crash_at = liftoff + elapsed_for_mult(min(cp, MAX_MULT))
    session.execute(text("""
        INSERT INTO rocket_rounds (crash_point, created_at, liftoff_at, crash_at)
        VALUES (:cp, :c, :l, :ca)
    """), {"cp": cp, "c": now, "l": liftoff, "ca": crash_at})
    session.flush()
    row = session.execute(text(
        "SELECT " + _ROUND_COLS + " FROM rocket_rounds ORDER BY id DESC LIMIT 1")).mappings().first()
    return _row(row)


def players(session, round_id: int) -> list:
    rows = session.execute(text("""
        SELECT b.id, b.user_id AS uid, b.bet, b.target, b.status, b.final_mult AS mult,
               b.payout, b.stars_awarded,
               COALESCE(u.username, u.first_name, 'بازیکن') AS name
        FROM rocket_bets b
        LEFT JOIN users u ON u.telegram_id = b.user_id
        WHERE b.round_id = :r
        ORDER BY b.id
    """), {"r": round_id}).mappings().all()
    return [dict(x) for x in rows]


def get_active(session, user_id: int) -> Optional[dict]:
    row = session.execute(text("""
        SELECT b.id, b.round_id, b.user_id, b.bet, b.target, b.crash_point, b.status,
               b.final_mult, b.payout, b.created_at, r.liftoff_at, r.crash_at
        FROM rocket_bets b
        JOIN rocket_rounds r ON r.id = b.round_id
        WHERE b.user_id = :u AND b.status = 'active'
        ORDER BY b.id DESC LIMIT 1
    """), {"u": user_id}).mappings().first()
    return _row(row)


def create_bet(session, user_id: int, amount: int, target: float,
               crash_point: float, now: float, round_id: int) -> int:
    session.execute(text("""
        INSERT INTO rocket_bets
            (round_id, user_id, bet, target, crash_point, status, payout, stars_awarded, created_at)
        VALUES
            (:r, :u, :b, :t, :cp, 'active', 0, 0, :n)
    """), {"r": round_id, "u": user_id, "b": amount, "t": target, "cp": crash_point, "n": now})
    session.flush()
    rid = session.execute(text("SELECT id FROM rocket_bets WHERE round_id=:r AND user_id=:u"),
                          {"r": round_id, "u": user_id}).scalar()
    return int(rid)


def finish_bet(session, bet_id: int, status: str, final_mult: float, pay: int, now: float) -> bool:
    res = session.execute(text("""
        UPDATE rocket_bets
        SET status = :s, final_mult = :m, payout = :p, ended_at = :n
        WHERE id = :id AND status = 'active'
    """), {"s": status, "m": final_mult, "p": pay, "n": now, "id": bet_id})
    return res.rowcount > 0


def settle_all(session, now: float) -> None:
    """شرط‌های active که زمان رسیدنشان گذشته را تسویه کن و ستاره بده."""
    rows = session.execute(text("""
        SELECT b.id, b.user_id, b.bet, b.target, b.crash_point, b.stars_awarded,
               r.liftoff_at, r.crash_at
        FROM rocket_bets b
        JOIN rocket_rounds r ON r.id = b.round_id
        WHERE b.status = 'active'
        ORDER BY b.id
    """)).mappings().all()
    for b in rows:
        liftoff = float(b["liftoff_at"])
        crash_at = float(b["crash_at"])
        cp = float(b["crash_point"])
        target = float(b["target"] or 0)
        amount = int(b["bet"])
        # هنوز پرواز شروع نشده
        if now < liftoff:
            continue
        if is_manual(target):
            # بدون ضریب: اگر بازیکن خودش برداشت نکرده باشد، فقط وقتی موشک به سقف برسد
            # خودکار در سقف برداشت می‌شود؛ در غیر این صورت با سقوط می‌سوزد.
            win = cp + 1e-12 >= MAX_MULT
            win_mult = MAX_MULT
        else:
            win = is_win(cp, target)
            win_mult = target
        reach_at = liftoff + elapsed_for_mult(win_mult)
        if win:
            # برنده وقتی ضریب به هدف (یا سقف) برسد
            if now < reach_at:
                continue
            pay = payout(amount, win_mult)
            if not finish_bet(session, int(b["id"]), "cashed", win_mult, pay, now):
                continue
            # واریز روب‌پوینت + ستاره
            session.execute(text("""
                UPDATE users SET fox_points = COALESCE(fox_points,0) + :p
                WHERE telegram_id = :u
            """), {"p": pay, "u": int(b["user_id"])})
            stars = max(0, int(math.floor(win_mult + 1e-9))) * STARS_PER_MULT
            if stars > 0:
                session.execute(text("""
                    UPDATE users SET rocket_stars = COALESCE(rocket_stars,0) + :s
                    WHERE telegram_id = :u
                """), {"s": stars, "u": int(b["user_id"])})
                session.execute(text("""
                    UPDATE rocket_bets SET stars_awarded = :s WHERE id = :id
                """), {"s": stars, "id": int(b["id"])})
        else:
            # بازنده وقتی موشک سقوط کند
            if now < crash_at:
                continue
            finish_bet(session, int(b["id"]), "crashed", min(cp, MAX_MULT), 0, now)


def manual_cashout(session, bet: dict, now: float):
    """برداشت دستی وسط پرواز. ضریب با ساعت «سرور» حساب می‌شود (نه کلاینت).
    ترتیب قفل‌ها مثل settle_all است (اول شرط، بعد کاربر) تا deadlock نشود.
    خروجی: (نتیجه | None, کد_خطا | None)"""
    liftoff = float(bet["liftoff_at"])
    crash_at = float(bet["crash_at"])
    cp = float(bet["crash_point"])
    if now < liftoff:
        return None, "not_flying"
    if now >= crash_at:
        return None, "crashed"
    m = display_mult(now - liftoff)
    if m < MIN_TARGET - 1e-9:
        return None, "too_early"
    if m > cp + 1e-9:
        return None, "crashed"
    amount = int(bet["bet"])
    pay = payout(amount, m)
    if not finish_bet(session, int(bet["id"]), "cashed", m, pay, now):
        return None, "settled"
    uid = int(bet["user_id"])
    session.execute(text("""
        UPDATE users SET fox_points = COALESCE(fox_points,0) + :p
        WHERE telegram_id = :u
    """), {"p": pay, "u": uid})
    stars = max(0, int(math.floor(m + 1e-9))) * STARS_PER_MULT
    if stars > 0:
        session.execute(text("""
            UPDATE users SET rocket_stars = COALESCE(rocket_stars,0) + :s
            WHERE telegram_id = :u
        """), {"s": stars, "u": uid})
        session.execute(text("""
            UPDATE rocket_bets SET stars_awarded = :s WHERE id = :id
        """), {"s": stars, "id": int(bet["id"])})
    return {"mult": m, "payout": pay, "stars": stars, "bet": amount,
            "target": float(bet.get("target") or 0)}, None


def recent_crashes(session, now: float, limit: int = 12) -> list:
    rows = session.execute(text("""
        SELECT crash_point FROM rocket_rounds
        WHERE crash_at <= :n AND crash_at > liftoff_at
        ORDER BY id DESC LIMIT :lim
    """), {"n": now, "lim": limit}).mappings().all()
    return [float(min(float(r["crash_point"]), MAX_MULT)) for r in rows]


def history(session, user_id: int, now: float, limit: int = 15) -> list:
    rows = session.execute(text("""
        SELECT bet, target, crash_point, status, final_mult, payout, stars_awarded, ended_at, created_at
        FROM rocket_bets
        WHERE user_id = :u AND status IN ('cashed','crashed','cancelled')
        ORDER BY id DESC LIMIT :lim
    """), {"u": user_id, "lim": limit}).mappings().all()
    out = []
    for r in rows:
        out.append({
            "bet": int(r["bet"]),
            "target": float(r["target"]),
            "crash_point": float(min(float(r["crash_point"] or 0), MAX_MULT)),
            "status": r["status"],
            "final_mult": float(r["final_mult"] or 0),
            "mult": float(r["final_mult"] or 0),
            "crash": float(min(float(r["crash_point"] or 0), MAX_MULT)),
            "payout": int(r["payout"] or 0),
            "stars": int(r["stars_awarded"] or 0),
            "ended_at": float(r["ended_at"] or r["created_at"] or 0),
        })
    return out


def record_solo(session, user_id: int, amount: int, target: float, cp: float,
                status: str, final_mult: float, pay: int) -> None:
    """ثبت بازی تک‌نفره بات (بدون round همگانی)."""
    now = time.time()
    session.execute(text("""
        INSERT INTO rocket_rounds (crash_point, created_at, liftoff_at, crash_at)
        VALUES (:cp, :n, :n, :n)
    """), {"cp": cp, "n": now})
    session.flush()
    rid = session.execute(text("SELECT id FROM rocket_rounds ORDER BY id DESC LIMIT 1")).scalar()
    stars = 0
    if status == "cashed":
        stars = max(0, int(math.floor(float(target) + 1e-9))) * STARS_PER_MULT
        if stars > 0:
            session.execute(text("""
                UPDATE users SET rocket_stars = COALESCE(rocket_stars,0) + :s
                WHERE telegram_id = :u
            """), {"s": stars, "u": user_id})
    session.execute(text("""
        INSERT INTO rocket_bets
            (round_id, user_id, bet, target, crash_point, status, final_mult, payout, stars_awarded, created_at, ended_at)
        VALUES
            (:r, :u, :b, :t, :cp, :s, :m, :p, :st, :n, :n)
    """), {
        "r": rid, "u": user_id, "b": amount, "t": target, "cp": cp,
        "s": status, "m": final_mult, "p": pay, "st": stars, "n": now,
    })
