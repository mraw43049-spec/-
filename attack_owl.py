# -*- coding: utf-8 -*-
"""
حمله با جغد‌محافظ.

- ۲٪ از روب‌پوینت‌های هدف دزدیده می‌شه.
- اگه هدف حداقل ۱ جغد داشته باشه، ۳۰ دقیقه فرصت داره تصمیم بگیره:
    «🦉 بله از من محافظت کن» → ۱ جغد کم می‌شه و حمله خنثی می‌شه
    «⚔️ نه بذار حمله بشه»    → حمله دقیقاً اجرا می‌شه
    «🔄 بروزرسانی»           → فقط زمان باقی‌مانده بروز می‌شه
- اگه تا ۳۰ دقیقه تصمیم نگیره، حمله اجرا می‌شه.

این ماژول هم توسط bot.py و هم main.py (مینی‌اپ) استفاده می‌شه؛ هر تغییر وضعیت با یک UPDATE اتمیک
(status: pending → resolving) انجام می‌شه تا حتی با دو پروسس هم دوبار اجرا نشه.
"""
import html
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from database import PendingAttack, User, get_session

logger = logging.getLogger(__name__)

ATTACK_STEAL_RATE = 0.02            # ۲ درصد
OWL_DECISION_SECONDS = 30 * 60      # ۳۰ دقیقه
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    try:
        from config import BOT_TOKEN as _CFG_TOKEN
        BOT_TOKEN = str(_CFG_TOKEN or "").strip()
    except Exception:  # noqa: BLE001
        BOT_TOKEN = ""


def now_utc():
    return datetime.now(timezone.utc)


def aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def left_seconds(att) -> int:
    return max(0, int((aware(att.expires_at) - now_utc()).total_seconds()))


def fmt_left(sec: int) -> str:
    m, s = divmod(max(0, int(sec)), 60)
    return f"{m} دقیقه و {s} ثانیه" if m else f"{s} ثانیه"


def _name(u) -> str:
    if not u:
        return "؟"
    base = u.username or u.first_name or str(u.telegram_id)
    return f"{(u.name_emoji or '')} {(u.name_flag or '')} {base}".strip()


def mention_html(u) -> str:
    # RLM قبل و بعد از اسم تا خط، راست‌به‌چپ بمونه (حتی با اسم انگلیسی)
    return f'\u200f<a href="tg://user?id={u.telegram_id}">{html.escape(_name(u))}</a>\u200f'


# ---------------------------------------------------------------------------
# ارسال پیام با Bot API (از هر دو پروسس کار می‌کنه)
# ---------------------------------------------------------------------------
def tg_call(method: str, **params):
    if not BOT_TOKEN:
        return None
    try:
        with httpx.Client(timeout=10) as c:
            r = c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=params).json()
        if not r.get("ok"):
            logger.info("telegram %s failed: %s", method, r.get("description"))
            return None
        return r.get("result")
    except Exception as e:  # noqa: BLE001
        logger.info("telegram %s error: %s", method, e)
        return None


def decision_keyboard(att_id: int):
    return {"inline_keyboard": [
        [{"text": "🦉 بله، از من محافظت کن", "callback_data": f"atk:protect:{att_id}"}],
        [{"text": "⚔️ نه، بذار حمله بشه", "callback_data": f"atk:allow:{att_id}"}],
        [{"text": "🔄 بروزرسانی", "callback_data": f"atk:refresh:{att_id}"}],
    ]}


def decision_text(att, attacker, target, owls: int) -> str:
    return (
        f"⚔️ {mention_html(attacker)} به {mention_html(target)} حمله کرد!\n\n"
        f"💰 مبلغ حمله: {att.amount:,} روب‌پوینت (۲٪ دارایی)\n"
        f"🦉 {mention_html(target)} تو {owls:,} جغد داری و می‌تونی یکی‌شونو خرج محافظت کنی.\n\n"
        f"⏳ زمان تصمیم‌گیری: {fmt_left(left_seconds(att))}\n"
        f"اگه تصمیم نگیری بعد از اتمام زمان حمله اجرا می‌شه."
    )


# ---------------------------------------------------------------------------
# شروع حمله (از bot.py صدا زده می‌شه)
# ---------------------------------------------------------------------------
def create_pending(session, attacker, target, chat_id, reply_message_id):
    """ردیف حمله‌ی منتظر رو می‌سازه. مبلغ همین لحظه از روی دارایی هدف ثابت می‌شه."""
    amount = int(int(target.fox_points or 0) * ATTACK_STEAL_RATE)
    att = PendingAttack(
        attacker_id=attacker.telegram_id, target_id=target.telegram_id, amount=amount,
        chat_id=chat_id, reply_message_id=reply_message_id, status="pending",
        expires_at=now_utc() + timedelta(seconds=OWL_DECISION_SECONDS),
    )
    session.add(att)
    session.flush()
    return att


def send_decision_message(att_id: int):
    """پیام دکمه‌دار رو داخل گروه می‌فرسته و شناسه‌ش رو ذخیره می‌کنه."""
    session = get_session()
    try:
        att = session.get(PendingAttack, att_id)
        if not att or att.status != "pending" or not att.chat_id:
            return
        attacker, target = session.get(User, att.attacker_id), session.get(User, att.target_id)
        params = dict(chat_id=att.chat_id, text=decision_text(att, attacker, target, int(target.owl_catch_count or 0)),
                      parse_mode="HTML", reply_markup=decision_keyboard(att.id))
        if att.reply_message_id:
            params["reply_to_message_id"] = att.reply_message_id
            params["allow_sending_without_reply"] = True
        res = tg_call("sendMessage", **params)
        if res:
            att.decision_message_id = res.get("message_id")
            session.commit()
    finally:
        session.close()


def refresh_decision_message(att_id: int):
    """متن پیام گروه رو با زمان جدید بروز می‌کنه (دکمه‌ی بروزرسانی)."""
    session = get_session()
    try:
        att = session.get(PendingAttack, att_id)
        if not att or att.status != "pending" or not att.decision_message_id:
            return
        attacker, target = session.get(User, att.attacker_id), session.get(User, att.target_id)
        tg_call("editMessageText", chat_id=att.chat_id, message_id=att.decision_message_id,
                text=decision_text(att, attacker, target, int(target.owl_catch_count or 0)),
                parse_mode="HTML", reply_markup=decision_keyboard(att.id))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# تصمیم نهایی (اتمیک و idempotent)
# ---------------------------------------------------------------------------
def resolve(att_id: int, decision: str, by_user_id=None):
    """
    decision: 'protect' | 'allow' | 'timeout'
    خروجی: dict(ok, status, text, ...) یا dict(ok=False, error=...)
    """
    session = get_session()
    try:
        att = session.get(PendingAttack, att_id)
        if not att:
            return {"ok": False, "error": "این حمله پیدا نشد."}
        if by_user_id is not None and int(by_user_id) != int(att.target_id):
            return {"ok": False, "error": "این تصمیم مال تو نیست."}
        if att.status != "pending":
            return {"ok": False, "error": "این حمله قبلاً تموم شده.", "status": att.status}
        expired = aware(att.expires_at) <= now_utc()
        if expired and decision != "timeout":
            decision = "timeout"   # بعد از ۳۰ دقیقه دیگه انتخاب معنی نداره؛ حمله اجرا می‌شه
        # قفل اتمیک
        claimed = (session.query(PendingAttack)
                   .filter(PendingAttack.id == att_id, PendingAttack.status == "pending")
                   .update({"status": "resolving"}, synchronize_session=False))
        session.commit()
        if claimed != 1:
            return {"ok": False, "error": "این حمله قبلاً تموم شده."}

        att = session.get(PendingAttack, att_id)
        # قفل ردیف هر دو کاربر (به ترتیب شناسه تا deadlock نشه) تا موجودی‌ها وسط کار عوض نشن
        locked = {u.telegram_id: u for u in session.query(User)
                  .filter(User.telegram_id.in_([att.attacker_id, att.target_id]))
                  .order_by(User.telegram_id).with_for_update().all()}
        attacker, target = locked[att.attacker_id], locked[att.target_id]
        a_m, t_m = mention_html(attacker), mention_html(target)
        status, text, text_prefix = "executed", "", ""

        if decision == "protect":
            if int(target.owl_catch_count or 0) >= 1:
                target.owl_catch_count = int(target.owl_catch_count) - 1
                status = "protected"
                text = (f"🦉 {t_m} از یکی از جغدهاش استفاده کرد و حمله‌ی {a_m} خنثی شد!\n"
                        f"🦉 جغدهای باقی‌مانده: {int(target.owl_catch_count):,}")
            else:
                decision = "allow"   # جغدش رو بین راه از دست داده (مثلاً انتقال داده)
                text_prefix = f"🦉 {t_m} دیگه جغدی نداشت…\n\n"
        if status != "protected":
            stolen = min(int(att.amount or 0), int(target.fox_points or 0))
            if stolen > 0:
                target.fox_points = int(target.fox_points) - stolen
                attacker.fox_points = int(attacker.fox_points or 0) + stolen
            why = "⏰ مهلت تصمیم‌گیری تموم شد" if decision == "timeout" else "⚔️ تصمیم گرفته شد که حمله انجام بشه"
            pre = text_prefix
            if stolen > 0:
                text = (f"{pre}{why}.\n\n⚔️ {a_m} به {t_m} حمله کرد!\n\n"
                        f"💰 مبلغ برداشت‌شده: {stolen:,} روب‌پوینت\n"
                        f"🦊 موجودی حمله‌کننده: {int(attacker.fox_points):,} روب‌پوینت\n"
                        f"🎯 موجودی حمله‌خورده: {int(target.fox_points):,} روب‌پوینت")
            else:
                text = f"{pre}{why}.\n\n⚔️ {a_m} به {t_m} حمله کرد!\n\n❌ موجودی طرف مقابل خیلی کم بود و چیزی گرفته نشد."
            status = "timeout" if decision == "timeout" else "executed"

        att.status = status
        att.decided_at = now_utc()
        session.commit()
        result = {"ok": True, "status": status, "text": text, "chat_id": att.chat_id,
                  "reply_message_id": att.reply_message_id, "decision_message_id": att.decision_message_id,
                  "attacker_id": att.attacker_id, "target_id": att.target_id}
    finally:
        session.close()
    announce(result)
    return result


def announce(result: dict):
    """نتیجه رو توی گروه اعلام می‌کنه و پیام دکمه‌دار رو بی‌دکمه می‌کنه."""
    if not result.get("chat_id"):
        return
    anchor = result.get("decision_message_id") or result.get("reply_message_id")
    if result.get("decision_message_id"):
        tg_call("editMessageText", chat_id=result["chat_id"], message_id=result["decision_message_id"],
                text="🔒 این حمله تموم شد؛ نتیجه پایین‌تره.", reply_markup={"inline_keyboard": []})
    params = dict(chat_id=result["chat_id"], text=result["text"], parse_mode="HTML")
    if anchor:
        params.update(reply_to_message_id=anchor, allow_sending_without_reply=True)
    tg_call("sendMessage", **params)


def resolve_expired():
    """همه‌ی حمله‌های منقضی‌شده رو اجرا می‌کنه (job بات و مینی‌اپ صداش می‌زنن)."""
    session = get_session()
    try:
        ids = [r.id for r in session.query(PendingAttack.id)
               .filter(PendingAttack.status == "pending", PendingAttack.expires_at <= now_utc()).all()]
    finally:
        session.close()
    n = 0
    for i in ids:
        try:
            if resolve(i, "timeout").get("ok"):
                n += 1
        except Exception:  # noqa: BLE001
            logger.exception("resolve_expired failed for %s", i)
    return n


def pending_for_target(session, user_id: int):
    return (session.query(PendingAttack)
            .filter(PendingAttack.target_id == user_id, PendingAttack.status == "pending")
            .order_by(PendingAttack.created_at.asc()).all())
