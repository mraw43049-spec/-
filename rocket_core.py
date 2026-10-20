# -*- coding: utf-8 -*-
"""موشک همگانی (Crash) برای مینی‌اپ + بات.

ورود ثابت: ۵۰٬۰۰۰ روب‌پوینت برای هر پرواز.
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
MAX_MULT = float(os.environ.get("ROCKET_MAX_MULT", "10"))
MIN_TARGET = float(os.environ.get("ROCKET_MIN_TARGET", "1.2"))
EDGE = float(os.environ.get("ROCKET_EDGE", "0.04"))  # حاشیه خانه
GROWTH = float(os.environ.get("ROCKET_GROWTH", "0.06"))  # شیب رشد ضریب
RISE = float(os.environ.get("ROCKET_RISE", "12"))  # ثانیه تقریبی تا سقف
START = float(os.environ.get("ROCKET_START", "-1.5"))
WAIT = float(os.environ.get("ROCKET_WAIT", "30"))  # ثانیه شرط‌بندی
COOLDOWN = float(os.environ.get("ROCKET_COOLDOWN", "30"))  # بین پروازها

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


def roll_crash() -> float:
    """نقطه سقوط با حاشیه خانه (فرمول استاندارد crash)."""
    r = random.random()
    if r < EDGE:
        return 1.0
    # (1-edge) / U  — حداقل ۱
    cp = (1.0 - EDGE) / max(1e-12, r)
    return min(MAX_MULT * 1.01, max(1.0, cp))


def is_win(crash_point: float, target: float) -> bool:
    return float(crash_point) + 1e-12 >= float(target)


def mult_at_elapsed(elapsed: float) -> float:
    """ضریب نمایشی بر اساس زمان از liftoff (نمایی)."""
    if elapsed <= 0:
        return START
    # از ۰ به بالا: e^(growth*t) تقریباً
    m = math.exp(GROWTH * elapsed)
    return min(MAX_MULT, max(0.0, m))


def elapsed_for_mult(mult: float) -> float:
    if mult <= 1.0:
        return 0.0
    return math.log(max(1.0, mult)) / max(1e-9, GROWTH)


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
        # مهاجرت ستونه اگر جدول قدیمی باشد
        try:
            conn.execute(text(
                "ALTER TABLE rocket_bets ADD COLUMN IF NOT EXISTS stars_awarded INTEGER NOT NULL DEFAULT 0"
            ))
        except Exception:
            pass
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rocket_bets_user ON rocket_bets (user_id)"
            ))
        except Exception:
            pass
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rocket_bets_status ON rocket_bets (status)"
            ))
        except Exception:
            pass


def _row(m) -> dict:
    return dict(m) if m is not None else None


def _lock_rounds(session) -> None:
    """جلوی ساخته‌شدن هم‌زمان دو دور (چند کاربر هم‌زمان polling می‌کنن) رو روی Postgres می‌گیره."""
    try:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(7287310001)"))
    except Exception:
        pass


def ensure_round(session, now: float) -> dict:
    """دور فعال یا جدید بساز.

    دور جدید همیشه یک ردیف واقعی توی دیتابیسه (هیچ دور ساختگی/موقت وجود نداره)؛
    اگه دور قبلی تازه تموم شده باشه، پرتاب دور بعدی = پایان دور قبلی + COOLDOWN + WAIT.
    این‌طوری هیچ‌کس نمی‌تونه روی دوری که تموم شده (و نتیجه‌ش معلومه) شرط ببنده.
    """
    _lock_rounds(session)
    row = session.execute(text("""
        SELECT id, crash_point, created_at, liftoff_at, crash_at
        FROM rocket_rounds
        WHERE crash_at > :n
        ORDER BY id DESC LIMIT 1
    """), {"n": now}).mappings().first()
    if row:
        return _row(row)

    # آخرین دور همگانی (بازی‌های تک‌نفره‌ی بات liftoff_at == created_at دارن و حساب نمی‌شن)
    last = session.execute(text("""
        SELECT id, crash_at FROM rocket_rounds
        WHERE liftoff_at > created_at
        ORDER BY id DESC LIMIT 1
    """)).mappings().first()

    cp = roll_crash()
    created = now
    liftoff = now + WAIT
    if last and now < float(last["crash_at"]) + COOLDOWN:
        liftoff = float(last["crash_at"]) + COOLDOWN + WAIT
    # زمان سقوط از روی ضریب
    t_crash = elapsed_for_mult(min(cp, MAX_MULT))
    crash_at = liftoff + t_crash
    new_id = session.execute(text("""
        INSERT INTO rocket_rounds (crash_point, created_at, liftoff_at, crash_at)
        VALUES (:cp, :c, :l, :ca)
        RETURNING id
    """), {"cp": cp, "c": created, "l": liftoff, "ca": crash_at}).scalar()
    session.flush()
    return {"id": int(new_id), "crash_point": cp, "created_at": created,
            "liftoff_at": liftoff, "crash_at": crash_at}


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
    """)).mappings().all()
    for b in rows:
        liftoff = float(b["liftoff_at"])
        crash_at = float(b["crash_at"])
        cp = float(b["crash_point"])
        target = float(b["target"])
        amount = int(b["bet"])
        # هنوز پرواز شروع نشده
        if now < liftoff:
            continue
        # هنوز به نقطه سقوط نرسیده و هدف هم نرسیده — صبر
        t_target = elapsed_for_mult(target)
        reach_at = liftoff + t_target
        if is_win(cp, target):
            # برنده وقتی ضریب به هدف برسد
            if now < reach_at:
                continue
            pay = payout(amount, target)
            if not finish_bet(session, int(b["id"]), "cashed", target, pay, now):
                continue
            # واریز روب‌پوینت + ستاره
            session.execute(text("""
                UPDATE users SET fox_points = COALESCE(fox_points,0) + :p
                WHERE telegram_id = :u
            """), {"p": pay, "u": int(b["user_id"])})
            stars = max(0, int(math.floor(target + 1e-9))) * STARS_PER_MULT
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


def recent_crashes(session, now: float, limit: int = 12) -> list:
    rows = session.execute(text("""
        SELECT crash_point FROM rocket_rounds
        WHERE crash_at <= :n
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
