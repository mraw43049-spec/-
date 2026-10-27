# -*- coding: utf-8 -*-
"""منو، عضویت اجباری، الماس، دعوت، انتقال و رسید پرداخت."""
import asyncio
import os
import re
import secrets
import time
from decimal import Decimal
from sqlalchemy import Column, BigInteger, String, Numeric, Integer, Boolean, inspect, text
from telegram import InlineKeyboardButton as _B, InlineKeyboardMarkup as KB
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from database import Base, get_session
import selfbot

CHANNELS = [('@selfsaz_iran', 'https://t.me/selfsaz_iran'), ('@fox_frenzy', 'https://t.me/fox_frenzy')]
SUPPORT = '@escotch'
CARD = '6219 8618 5116 0068'
OWNER = 'ظریفی'
ACTIVATE_COST = 5
# دورهٔ رایگان ۳ روزه به‌صورت پیش‌فرض خاموشه (بدون الماس سلف فعال نمی‌شه). برای روشن‌کردنش: SELF_TRIAL=1
TRIAL_ENABLED = os.environ.get('SELF_TRIAL', '').strip().lower() in ('1', 'true', 'yes')

_EMOJI_RE = __import__('re').compile("[\U0001F000-\U0001FFFF\u2190-\u21FF\u2300-\u23FF\u2600-\u27BF\uFE0F\u200d]")
def B(text, *args, **kwargs):
    text = _EMOJI_RE.sub("", text or "").strip()
    api = kwargs.pop("api_kwargs", {}) or {}
    api.setdefault("style", "danger" if any(x in text for x in ("رد", "لغو", "خاموش", "حذف")) else "success" if any(x in text for x in ("تأیید", "روشن", "عضو شدم")) else "primary")
    return _B(text, *args, api_kwargs=api, **kwargs)
class Wallet(Base):
    __tablename__ = 'diamond_wallets'
    user_id = Column(BigInteger, primary_key=True)
    balance = Column(Numeric(12, 1), nullable=False, default=Decimal('0.0'))
    referrer = Column(BigInteger, nullable=True)
    referred_awarded = Column(Boolean, default=False)
    last_charge = Column(Integer, default=0)
    self_started = Column(Boolean, default=False)
    trial_until = Column(Integer, nullable=True)
    trial_used = Column(Boolean, default=False)
class Payment(Base):
    __tablename__ = 'diamond_payments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    plan = Column(String(20), nullable=False)
    discount = Column(Integer, default=0)
    code = Column(String(32), nullable=True)
    file_id = Column(String(255), nullable=True)
    file_kind = Column(String(10), nullable=True)
    claimed_by = Column(BigInteger, nullable=True)
    claimed_name = Column(String(64), nullable=True)
    status = Column(String(20), default='pending')
    created = Column(Integer, default=lambda: int(time.time()))

class Ticket(Base):
    __tablename__ = 'support_tickets'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    status = Column(String(10), default='open')
    subject = Column(String(200), nullable=True)
    created = Column(Integer, default=lambda: int(time.time()))
    last = Column(Integer, default=lambda: int(time.time()))
class DiscountCode(Base):
    __tablename__ = 'discount_codes'
    code = Column(String(32), primary_key=True)
    percent = Column(Integer, nullable=False)
    max_uses = Column(Integer, nullable=False, default=1)
    used = Column(Integer, nullable=False, default=0)
    expires = Column(Integer, nullable=True)
    created = Column(Integer, default=lambda: int(time.time()))
class DiscountUse(Base):
    __tablename__ = 'discount_uses'
    code = Column(String(32), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    ts = Column(Integer, default=lambda: int(time.time()))
class GiftCode(Base):
    __tablename__ = 'gift_codes'
    code = Column(String(32), primary_key=True)
    amount = Column(Numeric(12, 1), nullable=False)
    max_uses = Column(Integer, nullable=False, default=1)
    used = Column(Integer, nullable=False, default=0)
    expires = Column(Integer, nullable=True)
    created = Column(Integer, default=lambda: int(time.time()))
    creator = Column(BigInteger, nullable=True)
class GiftRedeem(Base):
    __tablename__ = 'gift_redeems'
    code = Column(String(32), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    ts = Column(Integer, default=lambda: int(time.time()))

def _migrate_wallet():
    # create_all does not add columns to existing SQLite/Postgres tables.
    try:
        insp = inspect(__import__('database').engine)
        if 'diamond_wallets' not in insp.get_table_names():
            return
        cols = {c['name'] for c in insp.get_columns('diamond_wallets')}
        dialect = __import__('database').engine.dialect.name
        with __import__('database').engine.begin() as conn:
            if 'trial_until' not in cols:
                conn.execute(text('ALTER TABLE diamond_wallets ADD COLUMN trial_until INTEGER'))
            if 'trial_used' not in cols:
                conn.execute(text('ALTER TABLE diamond_wallets ADD COLUMN trial_used BOOLEAN DEFAULT FALSE'))
        if 'diamond_payments' in insp.get_table_names():
            pcols = {c['name'] for c in insp.get_columns('diamond_payments')}
            with __import__('database').engine.begin() as conn:
                if 'discount' not in pcols:
                    conn.execute(text('ALTER TABLE diamond_payments ADD COLUMN discount INTEGER DEFAULT 0'))
                if 'code' not in pcols:
                    conn.execute(text('ALTER TABLE diamond_payments ADD COLUMN code VARCHAR(32)'))
                for col, ddl in (('file_id', 'VARCHAR(255)'), ('file_kind', 'VARCHAR(10)'), ('claimed_by', 'BIGINT'), ('claimed_name', 'VARCHAR(64)')):
                    if col not in pcols:
                        conn.execute(text(f'ALTER TABLE diamond_payments ADD COLUMN {col} {ddl}'))
    except Exception:
        import logging; logging.getLogger(__name__).exception('wallet migration failed')

def start_trial(uid):
    """Start the 72-hour trial once, only after required-channel membership is verified."""
    now = int(time.time())
    s = get_session()
    try:
        w = s.get(Wallet, uid)
        if not w:
            w = Wallet(user_id=uid, balance=Decimal('0.0'), last_charge=now)
            s.add(w)
        if not w.trial_used:
            w.trial_used = True
            w.trial_until = now + 3 * 24 * 60 * 60
            s.commit()
            selfbot.save_row(uid, enabled=True)
            return w.trial_until, True
        return w.trial_until, False
    finally:
        s.close()

def wallet(uid, ref=None):
    s=get_session()
    try:
        w=s.get(Wallet,uid)
        if not w:
            w=Wallet(user_id=uid,balance=Decimal('0.0'),last_charge=int(time.time()))
            if ref and ref != uid and s.get(Wallet,ref): w.referrer=ref
            s.add(w); s.commit()
        return {'balance': Decimal(w.balance or 0), 'referrer':w.referrer,'self_started':bool(w.self_started),'last_charge':w.last_charge or int(time.time()), 'trial_until':getattr(w,'trial_until',None), 'trial_used':bool(getattr(w,'trial_used',False))}
    finally:s.close()
def change(uid, amount):
    s=get_session()
    try:
        w=s.get(Wallet,uid)
        if not w: w=Wallet(user_id=uid,balance=Decimal('0.0'),last_charge=int(time.time())); s.add(w)
        w.balance=Decimal(w.balance or 0)+Decimal(str(amount)); s.commit(); return Decimal(w.balance)
    finally:s.close()

def award_referral(uid):
    s=get_session()
    try:
        w=s.get(Wallet,uid)
        if not w or not w.referrer or w.referred_awarded: return False
        ref=s.get(Wallet,w.referrer)
        if ref:
            w.balance=Decimal(w.balance or 0)+Decimal('50.0')
            ref.balance=Decimal(ref.balance or 0)+Decimal('50.0')
            w.referred_awarded=True
            s.commit()
            return True
        return False
    finally:s.close()

def btn(text, data=None, url=None, style="primary"):
    kw = {"api_kwargs": {"style": style}}
    if url:
        return B(text, url=url, **kw)
    return B(text, callback_data=data, **kw)

def home_kb():
    return KB([
        [btn('ساخت سلف', 'shop:create', style='success')],
        [btn('خرید الماس', 'shop:buy')],
        [btn('دعوت دوستان', 'shop:invite'), btn('انتقال الماس', 'shop:transfer')],
        [btn('کد هدیه', 'shop:code', style='success')],
        [btn('آموزش استفاده', 'shop:help'), btn('درباره سلف', 'shop:about')],
        [btn('تیکت پشتیبانی', 'shop:ticket', style='success')],
        [btn('حساب کاربری', 'shop:dash')],
    ])
def join_kb():
    rows=[[B('عضویت در '+ch, url=url)] for ch,url in CHANNELS]
    rows.append([B('✅ عضو شدم',callback_data='shop:check')]); return KB(rows)
async def is_member(bot,uid):
    for ch,_ in CHANNELS:
        try:
            m=await bot.get_chat_member(ch,uid)
            if m.status in ('left','kicked'): return False
        except Exception:
            return False
    return True
PRICES = {'1': 75000, '2': 120000}
DIAMONDS = {'1': 1000, '2': 1800}
_warn_level = {}   # uid -> سطح هشدار کمبود الماس (۱: کمتر از ۲۴ ساعت، ۲: کمتر از ۳ ساعت)

def money(n):
    return f'{int(n):,}'.replace(',', '٬')

def _pct(context):
    d = context.user_data.get('disc')
    return int(d['pct']) if d else 0

def buy_text(pct=0):
    def line(plan, label):
        base = PRICES[plan]
        if pct:
            return f'{label} — {DIAMONDS[plan]} الماس — {money(base)} ← {money(base * (100 - pct) // 100)} تومان ({pct}٪ تخفیف 🏷)'
        return f'{label} — {DIAMONDS[plan]} الماس — {money(base)} تومان'
    return ('💎 خرید الماس\n\n' + line('1', '۱ ماه') + '\n' + line('2', '۲ ماه') + '\n\n'
            + (f'🏷 کد تخفیف فعاله: {pct}٪\n\n' if pct else 'کد تخفیف داری؟ دکمهٔ «کد تخفیف» رو بزن.\n\n')
            + f'شماره کارت: {CARD}\nبه نام: {OWNER}\nبعد از واریز، رسید رو همین‌جا ارسال کن؛ رسید و توضیحات برای پشتیبانی فرستاده می‌شه.')

def buy_kb():
    return KB([[B('خرید ۱ ماهه',callback_data='shop:pay:1')],[B('خرید ۲ ماهه',callback_data='shop:pay:2')],[B('کد تخفیف',callback_data='shop:disc')],[B('منوی اصلی',callback_data='shop:home')]])

def make_discount(percent, max_uses, hours=None):
    s = get_session()
    try:
        for _ in range(10):
            code = 'OFF-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
            if not s.get(DiscountCode, code):
                break
        exp = int(time.time()) + int(hours) * 3600 if hours else None
        s.add(DiscountCode(code=code, percent=int(percent), max_uses=int(max_uses), used=0, expires=exp))
        s.commit()
        return code
    finally:
        s.close()

def check_discount(uid, code):
    """('ok', درصد) یا (علت, None)."""
    code = (code or '').strip().upper()
    s = get_session()
    try:
        d = s.get(DiscountCode, code)
        if not d:
            return ('invalid', None)
        if d.expires and int(time.time()) > d.expires:
            return ('expired', None)
        if (d.used or 0) >= d.max_uses:
            return ('finished', None)
        if s.get(DiscountUse, (code, uid)):
            return ('already', None)
        return ('ok', int(d.percent))
    finally:
        s.close()

def consume_discount(uid, code):
    """ثبت مصرف کد هنگام ارسال رسید؛ درصد یا ۰ برمی‌گردونه."""
    code = (code or '').strip().upper()
    s = get_session()
    try:
        d = s.query(DiscountCode).filter(DiscountCode.code == code).with_for_update().one_or_none()
        if (not d or (d.expires and int(time.time()) > d.expires) or (d.used or 0) >= d.max_uses
                or s.get(DiscountUse, (code, uid))):
            return 0
        d.used = (d.used or 0) + 1
        s.add(DiscountUse(code=code, user_id=uid))
        s.commit()
        return int(d.percent)
    except Exception:
        s.rollback()
        return 0
    finally:
        s.close()

def release_discount(uid, code):
    if not code:
        return
    s = get_session()
    try:
        d = s.get(DiscountCode, code)
        u = s.get(DiscountUse, (code, uid))
        if d and u:
            d.used = max(0, (d.used or 0) - 1)
            s.delete(u)
            s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()

def stats_text():
    import json as _json
    s = get_session()
    try:
        users = s.query(Wallet).count()
        bal = sum((Decimal(w.balance or 0) for w in s.query(Wallet).all()), Decimal('0'))
        started = s.query(Wallet).filter(Wallet.self_started.is_(True)).count()
        pays = s.query(Payment).all()
        ok = [p for p in pays if p.status == 'approved']
        pend = len([p for p in pays if p.status == 'pending'])
        rev = sum(PRICES.get(p.plan, 0) * (100 - int(p.discount or 0)) // 100 for p in ok)
        sold = sum(DIAMONDS.get(p.plan, 0) for p in ok)
        enabled = s.query(selfbot.SelfAccess).filter(selfbot.SelfAccess.enabled.is_(True)).count()
        gifts = s.query(GiftRedeem).count()
        disc_used = s.query(DiscountUse).count()
        labels = {'always_online': 'همیشه آنلاین', 'typing_mode': 'تایپینگ', 'clock_on': 'ساعت زنده', 'ar_on': 'پاسخ خودکار',
                  'del_on': 'حذف/ویرایش', 'ttl_on': 'مدیای تایمردار', 'mn_on': 'منشن‌گیر', 'wl_on': 'ناظر'}
        cnt = {k: 0 for k in labels}
        for r in s.query(selfbot.SelfProfile).all():
            try:
                d = _json.loads(r.data or '{}')
            except Exception:
                continue
            for k in labels:
                if d.get(k):
                    cnt[k] += 1
        slot_users = 0
        for r in s.query(selfbot.SelfAccess).all():
            if any(x.get('word') for x in selfbot.slots_of(r)):
                slot_users += 1
        cnt_txt = '\n'.join(f'• {labels[k]}: {v}' for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]))
        return ('📊 آمار ربات\n\n'
                f'👥 کاربران: {users}\n🔌 سلف روشن (خریداری‌شده): {started}\n✅ دسترسی فعال: {enabled}\n🟢 اتصال زنده الان: {len(selfbot._clients)}\n'
                f'🎮 کاربران با اسلات بازی: {slot_users}\n\n'
                f'💎 مجموع الماس موجود در حساب‌ها: {fmt_bal(bal)}\n'
                f'💰 فروش تأییدشده: {len(ok)} پرداخت | {sold} الماس | {money(rev)} تومان\n⏳ رسید در انتظار: {pend}\n'
                f'🎁 کد هدیه استفاده‌شده: {gifts} | 🏷 کد تخفیف استفاده‌شده: {disc_used}\n\n'
                f'🔥 پرمصرف‌ترین قابلیت‌ها (تعداد کاربر روشن‌کننده):\n{cnt_txt}')
    finally:
        s.close()

def broadcast_ids(audience):
    s = get_session()
    try:
        if audience == 'self':
            return [r.user_id for r in s.query(selfbot.SelfAccess).filter(selfbot.SelfAccess.enabled.is_(True)).all()]
        return [w.user_id for w in s.query(Wallet).all()]
    finally:
        s.close()

def _bc_kb():
    n_all=len(broadcast_ids('all')); n_self=len(broadcast_ids('self'))
    return KB([[B('ارسال به همه کاربران ('+str(n_all)+')',callback_data='adm:bcall')],
               [B('ارسال به کاربران سلف فعال ('+str(n_self)+')',callback_data='adm:bcself')],
               [B('➕ افزودن دکمهٔ لینک',callback_data='adm:bclink')],
               [B('لغو',callback_data='adm:bccancel')]])

async def _broadcast(bot, admin_id, from_chat, msg_id, ids, buttons=None):
    markup = KB([[B(t_, url=u_)] for t_, u_ in (buttons or [])]) if buttons else None
    ok = fail = 0
    for i in ids:
        try:
            await bot.copy_message(chat_id=i, from_chat_id=from_chat, message_id=msg_id, reply_markup=markup)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)
    for rid in {admin_id} | set(selfbot.ADMIN_IDS):
        try:
            await bot.send_message(rid, f'📢 ارسال همگانی تموم شد' + ('' if rid == admin_id else f' (فرستنده: {admin_id})') + f'.\n✅ موفق: {ok}\n❌ ناموفق (ربات رو بلاک کرده یا دسترسی نیست): {fail}')
        except Exception:
            pass

_CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

def make_gift(creator, amount, max_uses, hours=None):
    s = get_session()
    try:
        for _ in range(10):
            code = 'RUBI-' + ''.join(secrets.choice(_CODE_CHARS) for _ in range(8))
            if not s.get(GiftCode, code):
                break
        exp = int(time.time()) + int(hours) * 3600 if hours else None
        s.add(GiftCode(code=code, amount=Decimal(str(amount)), max_uses=int(max_uses), used=0, expires=exp, creator=creator))
        s.commit()
        return code
    finally:
        s.close()

def redeem_gift(uid, code):
    """('ok', amount, balance) یا (علت, None, None)."""
    code = (code or '').strip().upper()
    s = get_session()
    try:
        g = s.query(GiftCode).filter(GiftCode.code == code).with_for_update().one_or_none()
        if not g:
            return ('invalid', None, None)
        now = int(time.time())
        if g.expires and now > g.expires:
            return ('expired', None, None)
        if (g.used or 0) >= g.max_uses:
            return ('finished', None, None)
        if s.get(GiftRedeem, (code, uid)):
            return ('already', None, None)
        w = s.get(Wallet, uid)
        if not w:
            w = Wallet(user_id=uid, balance=Decimal('0.0'), last_charge=now)
            s.add(w)
        w.balance = Decimal(w.balance or 0) + Decimal(g.amount)
        g.used = (g.used or 0) + 1
        s.add(GiftRedeem(code=code, user_id=uid))
        s.commit()
        return ('ok', Decimal(g.amount), Decimal(w.balance))
    except Exception:
        s.rollback()
        return ('invalid', None, None)
    finally:
        s.close()

def fmt_bal(x):
    d = Decimal(x or 0).quantize(Decimal('0.1'))
    t = format(d, 'f')
    return t[:-2] if t.endswith('.0') else t

def welcome_text(name, balance):
    lines = [
        f'سلام {name} 👋',
        'به «سلف‌ساز روباهیو» خوش اومدی ⚡️',
        '',
        'اکانت تلگرام خودت رو تبدیل کن به یه دستیار خودکار و حرفه‌ای:',
        '🤖 بازی‌ها رو خودش انجام می‌ده؛ کلمه می‌گه، تایمر می‌ذاره و دکمه می‌زنه',
        '🕒 ساعت زنده کنار اسمت',
        '🪞 کپی پروفایل فقط با یه ریپلای',
        '🟢 همیشه آنلاین  •  ⌨️ تایپینگ  •  🔤 حالت متن  •  🌐 ترجمه  •  🏷 تگ اعضا',
        '🎛 همه‌چیز از یه پنل شیک؛ کافیه توی هر چتی بنویسی «.پنل»',
        '',
        f'💎 سلف با الماس کار می‌کنه: فعال‌سازی {ACTIVATE_COST} الماس، بعدش ساعتی ۲ الماس (روشن) یا ۰٫۲ الماس (خاموش).',
        '🔒 بدون الماس سلف فعال نمی‌شه.',
        '',
        f'💰 موجودی تو: {fmt_bal(balance)} الماس',
    ]
    if Decimal(balance or 0) < ACTIVATE_COST:
        lines.append(f'⚠️ برای فعال‌سازی حداقل {ACTIVATE_COST} الماس لازمه؛ از «خرید الماس» شارژ کن یا دوستات رو دعوت کن (هر دعوت ۵۰ الماس برای هر دو نفر).')
    else:
        lines.append('✅ الماس کافی داری؛ «ساخت سلف» رو بزن و شروع کن.')
    lines.append('')
    lines.append('💬 فرستادن «موجودی» توی هر چت، موجودیت رو نشون می‌ده.')
    return '\n'.join(lines)

async def start(update,context):
    u=update.effective_user
    if context.args and context.args[0]=='panel':
        await selfbot.cmd_self(update,context); return
    ref=None
    if context.args:
        try: ref=int(context.args[0].replace('ref',''))
        except: pass
    wallet(u.id,ref)
    if not await is_member(context.bot,u.id):
        await update.effective_message.reply_text('برای استفاده از ربات، اول عضو هر دو کانال شو و بعد «عضو شدم» رو بزن.',reply_markup=join_kb()); return
    until, trial_new = start_trial(u.id) if TRIAL_ENABLED else (None, False)
    awarded = award_referral(u.id)
    if awarded:
        wref = wallet(u.id)['referrer']
        try:
            await context.bot.send_message(u.id, 'با لینک دعوت وارد شدی؛ ۵۰ الماس پاداش گرفتی.')
            if wref:
                await context.bot.send_message(wref, f'{u.first_name} با لینک دعوت تو وارد شد؛ هر دو ۵۰ الماس گرفتید.')
        except Exception:
            pass
    trial_msg = '\n🎁 دورهٔ رایگان سلفت به مدت ۳ روز شروع شد.' if trial_new else ''
    await update.effective_message.reply_text(welcome_text(u.first_name or '', wallet(u.id)['balance']) + trial_msg, reply_markup=home_kb())
async def show_panel(q, text, **kwargs):
    try:
        await q.edit_message_text(text, **kwargs)
    except Exception:
        await q.message.reply_text(text, **kwargs)

async def callback(update,context):
    q=update.callback_query; uid=q.from_user.id; data=q.data or ''; await q.answer()
    if data=='shop:check':
        if not await is_member(context.bot,uid): await show_panel(q, 'هنوز عضویت هر دو کانال تأیید نشده؛ بعد از عضویت دوباره بزن.',reply_markup=join_kb()); return
        until, trial_new = start_trial(uid) if TRIAL_ENABLED else (None, False)
        awarded = award_referral(uid)
        if awarded:
            wref = wallet(uid)['referrer']
            try:
                await context.bot.send_message(uid, 'با لینک دعوت وارد شدی؛ ۵۰ الماس پاداش گرفتی.')
                if wref:
                    await context.bot.send_message(wref, f'{q.from_user.first_name} با لینک دعوت تو وارد شد؛ هر دو ۵۰ الماس گرفتید.')
            except Exception:
                pass
        note = '\n🎁 دورهٔ رایگان ۳ روزه شروع شد.' if trial_new else ''
        await show_panel(q, '✅ عضویتت تأیید شد!\n\n' + welcome_text(q.from_user.first_name or '', wallet(uid)['balance']) + note,reply_markup=home_kb()); return
    if not await is_member(context.bot,uid):
        await show_panel(q, 'برای ادامه باید عضو هر دو کانال باشی.',reply_markup=join_kb()); return
    w=wallet(uid)
    if data=='shop:home': await show_panel(q, 'منوی اصلی',reply_markup=home_kb())
    elif data=='shop:create':
        await show_panel(q, ('⚠️ الماس کافی نداری؛ بدون الماس سلف فعال نمی‌شه. اول از «خرید الماس» شارژ کن.\n\n' if w['balance'] < ACTIVATE_COST and not (w.get('trial_until') and int(w['trial_until']) > int(time.time())) else '') + f'💎 موجودی فعلی: {w["balance"]}\nهر بار روشن‌کردن: ۵ الماس\nهزینه‌ی ساعتی در حالت روشن: ۲ الماس؛ در حالت خاموش: ۰٫۲ الماس.',reply_markup=KB([[B('▶️ روشن کردن',callback_data='shop:on')],[B('⏹ خاموش کردن',callback_data='shop:off')],[B('👤 حساب کاربری',callback_data='shop:dash')],[B('منوی اصلی',callback_data='shop:home')]]))
    elif data=='shop:on':
        if w['self_started']:
            await show_panel(q, 'سلفت از قبل روشنه. برای دیدن تنظیمات، دکمه‌ی اتصال اکانت یا دستور «پنل» رو استفاده کن.',reply_markup=KB([[B('🔗 اتصال اکانت',callback_data='self:conn')],[B('⏹ خاموش کردن',callback_data='shop:off')],[B('منوی اصلی',callback_data='shop:home')]])); return
        trial_active = bool(w.get('trial_until') and int(w['trial_until']) > int(time.time()))
        if w['balance'] < ACTIVATE_COST and not trial_active:
            await show_panel(q, f'❌ الماس کافی نداری.\n\n💎 موجودی تو: {fmt_bal(w["balance"])} الماس\n🔒 برای فعال‌سازی سلف حداقل {ACTIVATE_COST} الماس لازمه.\nاز «خرید الماس» شارژ کن یا با دعوت دوستان الماس بگیر.',reply_markup=KB([[B('خرید الماس',callback_data='shop:buy')],[B('دعوت دوستان',callback_data='shop:invite')],[B('منوی اصلی',callback_data='shop:home')]])); return
        if not trial_active:
            change(uid,-5)
        s=get_session()
        try:
            x=s.get(Wallet,uid); x.self_started=True; x.last_charge=int(time.time()); s.commit()
        finally:s.close()
        # Enable self access and present existing safe account connection flow
        selfbot.save_row(uid,enabled=True)
        await show_panel(q, ('دورهٔ رایگان فعاله؛ الماسی کسر نشد. حالا شمارهٔ اکانتی که می‌خوای وصل کنی رو با دکمهٔ اتصال اکانت وارد کن. هرگز کد ورودت رو برای هیچ‌کس نفرست.' if trial_active else '۵ الماس کسر شد. حالا شمارهٔ اکانتی که می‌خوای وصل کنی رو با دکمهٔ اتصال اکانت وارد کن. هرگز کد ورودت رو برای هیچ‌کس نفرست.'),reply_markup=KB([[B('🔗 اتصال اکانت',callback_data='self:conn')],[B('👤 حساب کاربری',callback_data='shop:dash')],[B('منوی اصلی',callback_data='shop:home')]]))
    elif data=='shop:off':
        s=get_session()
        try: x=s.get(Wallet,uid); x.self_started=False; x.last_charge=int(time.time()); s.commit()
        finally:s.close()
        selfbot.save_row(uid, enabled=False)
        if uid in selfbot._clients: await selfbot.stop_client(uid,restore=True)
        await show_panel(q, '⏹ سلف خاموش شد. هزینه‌ی حالت خاموش ۰٫۲ الماس در ساعت است.',reply_markup=home_kb())
    elif data=='shop:dash': await show_panel(q, f'👤 حساب کاربری\n🆔 آیدی: {uid}\n💎 موجودی: {w["balance"]} الماس\n🔌 وضعیت سلف: {"روشن" if w["self_started"] else "خاموش"}',reply_markup=KB([[B('خرید الماس',callback_data='shop:buy')],[B('منوی اصلی',callback_data='shop:home')]]))
    elif data=='shop:about': await show_panel(q, 'سلف ابزاریه که از اکانت تلگرام خودت، طبق تنظیماتی که انجام می‌دی، کارهای خودکار انجام می‌ده. استفاده از اکانت شخصی ریسک محدودیت تلگرام رو داره. اگه نفهمیدی یا کمکی خواستی با پشتیبانی تماس بگیر: @escotch',reply_markup=KB([[B('پشتیبانی',url='https://t.me/escotch')],[B('منوی اصلی',callback_data='shop:home')]]))
    elif data=='shop:help': await show_panel(q, 'برای شروع «ساخت سلف» و سپس «روشن کردن» رو بزن. بعد اتصال اکانت رو انجام بده و در چت‌های تلگرام خودت دستور «پنل» رو بنویس. پشتیبانی: @escotch',reply_markup=home_kb())
    elif data=='shop:buy': await show_panel(q, buy_text(_pct(context)), reply_markup=buy_kb())
    elif data=='shop:disc':
        context.user_data['gift_step']='disc'; await show_panel(q, '🏷 کد تخفیفت رو بفرست (مثل OFF-XXXXXX). برای لغو بنویس «لغو».')
    elif data.startswith('shop:pay:'):
        plan=data.rsplit(':',1)[1]; context.user_data['payment_plan']=plan
        pct=_pct(context); final=PRICES.get(plan,0)*(100-pct)//100
        await show_panel(q, f'💳 مبلغ قابل پرداخت: {money(final)} تومان'+(f' (با {pct}٪ تخفیف)' if pct else '')+f'\nشماره کارت: {CARD}\nبه نام: {OWNER}\n\nحالا عکس یا فایل رسید پرداخت رو ارسال کن. برای لغو بنویس «لغو».')
    elif data=='shop:invite':
        me=await context.bot.get_me(); link=f'https://t.me/{me.username}?start=ref{uid}'
        await show_panel(q, f'🔗 لینک اختصاصی دعوتت:\n{link}\nهر کاربر جدیدی که با لینک تو وارد بشه و عضویت کانال‌هاش تأیید بشه، ۵۰ الماس می‌گیره و برای تو هم ۵۰ الماس ثبت می‌شه.',reply_markup=KB([[B('منوی اصلی',callback_data='shop:home')]]))
    elif data=='shop:ticket':
        context.user_data['tk_step']='new'; context.user_data.pop('tk_id',None)
        await show_panel(q, '🎫 تیکت پشتیبانی\n\nمشکل یا سؤالت رو بفرست؛ متن، عکس، ویس، ویدیو یا فایل، هرچی که لازم داری. برای لغو بنویس «لغو».')
    elif data=='shop:code':
        context.user_data['gift_step']='redeem'; await show_panel(q, '🎁 کد هدیه‌ات رو بفرست (مثل RUBI-XXXXXXXX). برای لغو بنویس «لغو».')
    elif data=='shop:transfer':
        context.user_data['transfer_step']='recipient'; await show_panel(q, 'آیدی عددی گیرنده یا @شناسه کاربری رو بفرست:')
_pay_msgs = {}   # pid -> [(chat_id, message_id)] پیام‌های رسید پیش پشتیبان‌ها

def pay_caption(pid, uid, username, plan, pct, code, claimed_name=None):
    final = PRICES.get(plan, 0) * (100 - int(pct or 0)) // 100
    t = (f'رسید خرید الماس\nکاربر: {uid} (@{username or "ندارد"})\n'
         f'پلن: {"۱ ماهه / ۱۰۰۰ الماس" if plan == "1" else "۲ ماهه / ۱۸۰۰ الماس"}\n'
         f'💳 مبلغ باید پرداخت‌شده باشد: {money(final)} تومان' + (f' (با کد {code} — {pct}٪ تخفیف)' if pct else '') +
         f'\nشناسه پیگیری: {pid}')
    if claimed_name:
        t += f'\n🙋 در حال بررسی: {claimed_name}'
    return t[:1000]

def pay_kb(pid, viewer, claimer, claimer_name):
    ok_row = [B('تأیید و واریز الماس', callback_data=f'pay:approve:{pid}', style='success'), B('رد درخواست', callback_data=f'pay:reject:{pid}', style='danger')]
    is_admin = viewer in selfbot.ADMIN_IDS
    if claimer is None:
        rows = [[B('🙋 من بررسی می‌کنم', callback_data=f'pay:claim:{pid}', style='primary')]]
        if is_admin:
            rows.append(ok_row)
    elif claimer == viewer:
        rows = [ok_row]
    else:
        rows = [[B(f'🔒 {claimer_name or "یک پشتیبان"} در حال بررسی', callback_data=f'pay:info:{pid}', style='primary')]]
        if is_admin:
            rows.append(ok_row)
    return KB(rows)

async def send_receipt(bot, chat, text, file_id, kind, kb):
    try:
        if file_id and kind == 'photo':
            return await bot.send_photo(chat, file_id, caption=text, reply_markup=kb)
        if file_id and kind == 'document':
            return await bot.send_document(chat, file_id, caption=text, reply_markup=kb)
    except Exception:
        pass
    return await bot.send_message(chat, text, reply_markup=kb)

async def _pay_refresh(bot, pid, claimer, claimer_name, done=False):
    for chat, mid in list(_pay_msgs.get(pid, [])):
        try:
            await bot.edit_message_reply_markup(chat_id=chat, message_id=mid, reply_markup=None if done else pay_kb(pid, chat, claimer, claimer_name))
        except Exception:
            pass
    if done:
        _pay_msgs.pop(pid, None)

async def payment_review(update, context):
    q = update.callback_query
    uid = q.from_user.id
    if not is_staff(uid):
        await q.answer("دسترسی ندارید", show_alert=True)
        return
    parts = (q.data or "").split(":")
    if len(parts) != 3:
        await q.answer(); return
    action, pid = parts[1], parts[2]
    try:
        pid = int(pid)
    except ValueError:
        await q.answer(); return
    s = get_session()
    try:
        p = s.query(Payment).filter(Payment.id == pid).with_for_update().one_or_none()
        if not p:
            await q.answer()
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text("درخواست پرداخت پیدا نشد.")
            return
        if p.status != "pending":
            await q.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
            try: await q.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
            return
        who = q.from_user.first_name or ('@' + (q.from_user.username or str(uid)))
        if action == "info":
            await q.answer(f"{p.claimed_name or 'یک پشتیبان'} این رسید رو برداشته؛ تا اون تموم نکنه نمی‌تونی تأییدش کنی.", show_alert=True)
            return
        if action == "claim":
            if p.claimed_by and p.claimed_by != uid:
                await q.answer(f"قبلاً {p.claimed_name} این رسید رو برداشته.", show_alert=True)
                return
            p.claimed_by = uid; p.claimed_name = who[:60]
            s.commit()
            await q.answer("✅ رسید به نام تو ثبت شد.")
            _pay_msgs.setdefault(pid, [])
            if (q.message.chat_id, q.message.message_id) not in _pay_msgs[pid]:
                _pay_msgs[pid].append((q.message.chat_id, q.message.message_id))
            await _pay_refresh(context.bot, pid, uid, who[:60])
            return
        # تأیید/رد: فقط کسی که برداشته (یا ادمین)
        if uid not in selfbot.ADMIN_IDS and p.claimed_by != uid:
            await q.answer("اول دکمهٔ «من بررسی می‌کنم» رو بزن (و اگه کس دیگه‌ای برداشته، اون باید تموم کنه).", show_alert=True)
            return
        await q.answer()
        if action == "approve":
            amount = Decimal("1000") if p.plan == "1" else Decimal("1800")
            w = s.get(Wallet, p.user_id)
            if not w:
                w = Wallet(user_id=p.user_id, balance=Decimal("0"), last_charge=int(time.time()))
                s.add(w)
            w.balance = Decimal(w.balance or 0) + amount
            p.status = "approved"
            if not p.claimed_by:
                p.claimed_by = uid; p.claimed_name = who[:60]
            s.commit()
            await context.bot.send_message(p.user_id, f"پرداخت تأیید شد؛ {amount} الماس به حسابت اضافه شد.")
            await _pay_refresh(context.bot, pid, uid, who, done=True)
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text(f"تأیید شد. {amount} الماس به کاربر {p.user_id} اضافه شد.")
        elif action == "reject":
            p.status = "rejected"
            if not p.claimed_by:
                p.claimed_by = uid; p.claimed_name = who[:60]
            s.commit()
            try: release_discount(p.user_id, p.code)
            except Exception: pass
            await context.bot.send_message(p.user_id, "درخواست خرید الماس رد شد. برای بررسی بیشتر از «تیکت پشتیبانی» استفاده کن.")
            await _pay_refresh(context.bot, pid, uid, who, done=True)
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text(f"درخواست #{pid} رد شد.")
    finally:
        s.close()

def _tk_kb(tid):
    return KB([[B('💬 پاسخ', callback_data=f'sup:treply:{tid}', style='primary'), B('✅ بستن تیکت', callback_data=f'sup:tclose:{tid}', style='danger')]])

async def ticket_submit(m, context, u):
    """پیام کاربر → تیکت (جدید یا ادامهٔ تیکت باز) → کپی برای همهٔ پشتیبان‌ها."""
    ud = context.user_data
    tid = ud.get('tk_id')
    new = False
    s = get_session()
    try:
        t = s.get(Ticket, tid) if tid else None
        if not t or t.status != 'open' or t.user_id != u.id:
            t = s.query(Ticket).filter(Ticket.user_id == u.id, Ticket.status == 'open').order_by(Ticket.id.desc()).first()
        if not t:
            t = Ticket(user_id=u.id, status='open', subject=((m.text or m.caption or '')[:200] or None)); s.add(t); new = True
        t.last = int(time.time()); s.commit(); tid = t.id
    finally:
        s.close()
    ud.pop('tk_step', None); ud.pop('tk_id', None)
    head = (f'🎫 تیکت #{tid} | ' + ('جدید' if new else 'پیام جدید') + f'\nکاربر: {u.id} (@{u.username or "ندارد"}) {u.first_name or ""}')
    for staff in set(selfbot.ADMIN_IDS) | set(selfbot.SUPPORT_IDS):
        try:
            hm = await context.bot.send_message(staff, head, reply_markup=_tk_kb(tid))
            await context.bot.copy_message(staff, m.chat_id, m.message_id, reply_to_message_id=hm.message_id)
        except Exception:
            pass
    await m.reply_text(f'✅ پیامت برای پشتیبانی رفت (تیکت #{tid}). جواب همین‌جا برات می‌آد.', reply_markup=home_kb())

async def ticket_reply(m, context, tid):
    s = get_session()
    try:
        t = s.get(Ticket, tid)
        if not t:
            await m.reply_text('تیکت پیدا نشد.'); return
        if t.status != 'open':
            await m.reply_text('این تیکت بسته شده.'); return
        user_id = t.user_id; t.last = int(time.time()); s.commit()
    finally:
        s.close()
    try:
        await context.bot.send_message(user_id, f'💬 پاسخ پشتیبانی (تیکت #{tid}):')
        await context.bot.copy_message(user_id, m.chat_id, m.message_id, reply_markup=KB([[B('✍️ ادامه گفتگو', callback_data=f'tk:more:{tid}', style='primary')]]))
    except Exception:
        await m.reply_text('❌ ارسال نشد؛ احتمالاً کاربر ربات رو بلاک کرده.'); return
    await m.reply_text(f'✅ پاسخ برای تیکت #{tid} ارسال شد.', reply_markup=_tk_kb(tid))

async def tk_cb(update, context):
    q = update.callback_query
    parts = (q.data or '').split(':')
    await q.answer()
    if len(parts) < 3 or parts[1] != 'more':
        return
    try:
        tid = int(parts[2])
    except ValueError:
        return
    s = get_session()
    try:
        t = s.get(Ticket, tid)
        ok = bool(t and t.user_id == q.from_user.id and t.status == 'open')
    finally:
        s.close()
    if not ok:
        await q.message.reply_text('این تیکت بسته شده؛ از «تیکت پشتیبانی» توی منو یه تیکت جدید بساز.'); return
    context.user_data['tk_step'] = 'more'; context.user_data['tk_id'] = tid
    await q.message.reply_text(f'✍️ پیامت برای تیکت #{tid} رو بفرست (متن، عکس، ویس، ویدیو یا فایل). برای لغو بنویس «لغو».')

def is_staff(uid):
    return uid in selfbot.ADMIN_IDS or uid in selfbot.SUPPORT_IDS

def sup_kb():
    return KB([[B('📥 رسیدهای در انتظار',callback_data='sup:pending')],
               [B('🎫 تیکت‌های باز',callback_data='sup:tickets')],
               [B('🔎 بررسی کاربر',callback_data='sup:lookup')],
               [B('📢 پیام همگانی',callback_data='adm:bc')],
               [B('✖️ بستن',callback_data='sup:close')]])

async def support_panel(update, context):
    u = update.effective_user
    if not u or not is_staff(u.id) or update.effective_chat.type != 'private':
        return
    context.user_data.pop('sup_step', None)
    await update.effective_message.reply_text('🛟 پنل پشتیبانی\n\n📥 رسیدها با عکس رسید؛ اول «من بررسی می‌کنم» رو بزن تا کس دیگه‌ای همزمان تأییدش نکنه\n🎫 تیکت‌های کاربران؛ پاسخ با متن، عکس، ویس، ویدیو یا فایل\n🔎 بررسی کاربر با آیدی عددی\n📢 پیام همگانی با هر نوع مدیا', reply_markup=sup_kb())

async def sup_cb(update, context):
    q = update.callback_query
    if not is_staff(q.from_user.id):
        await q.answer('این پنل فقط برای پشتیبانیه.', show_alert=True); return
    await q.answer()
    act = (q.data or '').split(':')[1]
    if act == 'pending':
        s = get_session()
        try:
            rows = s.query(Payment).filter(Payment.status == 'pending').order_by(Payment.id.asc()).limit(10).all()
            total = s.query(Payment).filter(Payment.status == 'pending').count()
            items = [(p.id, p.user_id, p.plan, int(p.discount or 0), p.code, p.file_id, p.file_kind, p.claimed_by, p.claimed_name) for p in rows]
        finally:
            s.close()
        if not items:
            await q.message.reply_text('✅ رسید در انتظاری نیست.'); return
        chat = q.message.chat_id
        for pid, uid_, plan, pc, code, fid, fkind, cb_, cn in items:
            cap = pay_caption(pid, uid_, None, plan, pc, code, cn)
            sm = await send_receipt(context.bot, chat, cap, fid, fkind, pay_kb(pid, q.from_user.id, cb_, cn))
            lst = _pay_msgs.setdefault(pid, [])
            if (chat, sm.message_id) not in lst:
                lst.append((chat, sm.message_id))
        if total > len(items):
            await q.message.reply_text(f'و {total - len(items)} رسید دیگه هم در انتظاره؛ بعد از بررسی این‌ها دوباره بزن.')
    elif act == 'tickets':
        s = get_session()
        try:
            rows = s.query(Ticket).filter(Ticket.status == 'open').order_by(Ticket.last.asc()).limit(10).all()
            total = s.query(Ticket).filter(Ticket.status == 'open').count()
            items = [(t.id, t.user_id, t.subject) for t in rows]
        finally:
            s.close()
        if not items:
            await q.message.reply_text('✅ تیکت بازی نیست.'); return
        for tid, uid_, subj in items:
            await q.message.reply_text(f'🎫 تیکت #{tid} | کاربر {uid_}\n💬 {subj or "[رسانه]"}', reply_markup=_tk_kb(tid))
        if total > len(items):
            await q.message.reply_text(f'و {total - len(items)} تیکت باز دیگه هم هست.')
    elif act == 'treply':
        context.user_data['sup_step'] = 'treply:' + (q.data.split(':')[2] if len(q.data.split(':')) > 2 else '0')
        await q.message.reply_text('💬 پاسخت رو بفرست؛ متن (با فرمت تلگرام)، عکس، ویس، ویدیو، فایل… هرچی بفرستی همون‌طور برای کاربر کپی می‌شه. برای لغو بنویس «لغو».')
    elif act == 'tclose':
        try:
            tid = int(q.data.split(':')[2])
        except Exception:
            return
        s = get_session()
        try:
            t = s.get(Ticket, tid)
            if not t or t.status != 'open':
                await q.message.reply_text('این تیکت قبلاً بسته شده.'); return
            t.status = 'closed'; s.commit(); user_id = t.user_id
        finally:
            s.close()
        try:
            await context.bot.send_message(user_id, f'✅ تیکت #{tid} بسته شد. اگه مشکلت ادامه داشت از «تیکت پشتیبانی» یه تیکت جدید بساز.')
        except Exception:
            pass
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await q.message.reply_text(f'✅ تیکت #{tid} بسته شد.')
    elif act == 'lookup':
        context.user_data['sup_step'] = 'lookup'
        await q.message.reply_text('🔎 آیدی عددی کاربر رو بفرست. برای لغو بنویس «لغو».')
    elif act == 'close':
        try:
            await q.message.delete()
        except Exception:
            pass

def user_info_text(uid):
    s = get_session()
    try:
        w = s.get(Wallet, uid)
        if not w:
            return f'کاربر {uid} توی ربات حساب ندارد.'
        row = selfbot.get_row(uid)
        pays = s.query(Payment).filter(Payment.user_id == uid).order_by(Payment.id.desc()).limit(3).all()
        stt = {'pending': '⏳ در انتظار', 'approved': '✅ تأیید', 'rejected': '❌ رد'}
        ptxt = '\n'.join(f'#{p.id} | پلن {p.plan} | {stt.get(p.status, p.status)}' for p in pays) or 'پرداختی ندارد.'
        return (f'👤 کاربر {uid}\n💎 موجودی: {fmt_bal(w.balance)} الماس\n🔌 سلف: {"روشن" if w.self_started else "خاموش"}'
                f'\n🔑 دسترسی: {"فعال" if row and row.enabled else "غیرفعال"} | اتصال: {"زنده" if uid in selfbot._clients else "—"}'
                f'\n\n🧾 آخرین پرداخت‌ها:\n{ptxt}')
    finally:
        s.close()

async def incoming(update,context):
    m=update.effective_message; u=update.effective_user
    if not m or not u or update.effective_chat.type!='private': return
    sst=context.user_data.get('sup_step') or ''
    if sst.startswith('treply:') and is_staff(u.id):
        if m.text and m.text.strip()=='لغو':
            context.user_data.pop('sup_step',None); await m.reply_text('لغو شد.'); return
        context.user_data.pop('sup_step',None)
        try: tid=int(sst.split(':')[1])
        except Exception: return
        await ticket_reply(m,context,tid); return
    if context.user_data.get('gift_step')=='bc_link' and is_staff(u.id) and m.text:
        t=m.text.strip(); context.user_data.pop('gift_step',None)
        btns=[]
        if t!='لغو':
            for ln in t.split('\n')[:3]:
                if '|' in ln:
                    a_,b_=ln.split('|',1); a_=a_.strip()[:40]; b_=b_.strip()
                    if a_ and b_.startswith(('http://','https://','tg://','https://t.me/')): btns.append((a_,b_))
        if btns:
            context.user_data['bc_btns']=btns
            await m.reply_text('✅ '+str(len(btns))+' دکمهٔ لینک اضافه شد.',reply_markup=_bc_kb())
        else:
            await m.reply_text('دکمه‌ای اضافه نشد (فرمت: متن دکمه | لینک).',reply_markup=_bc_kb())
        return
    if context.user_data.get('sup_step')=='lookup' and is_staff(u.id) and m.text:
        t=selfbot.fa2en(m.text).strip()
        context.user_data.pop('sup_step',None)
        if t=='لغو': await m.reply_text('لغو شد.'); return
        if not t.isdigit(): await m.reply_text('❗️ فقط آیدی عددی بفرست.'); context.user_data['sup_step']='lookup'; return
        await m.reply_text(user_info_text(int(t)),reply_markup=sup_kb()); return
    if context.user_data.get('gift_step')=='admin_new' and u.id in selfbot.ADMIN_IDS and m.text:
        t=m.text.strip()
        if t=='لغو':
            context.user_data.pop('gift_step',None); await m.reply_text('لغو شد.'); return
        await _gift_create(m, context, t); return
    gs=context.user_data.get('gift_step')
    if gs=='disc_new' and u.id in selfbot.ADMIN_IDS and m.text:
        t=m.text.strip()
        if t=='لغو':
            context.user_data.pop('gift_step',None); await m.reply_text('لغو شد.'); return
        parts=t.replace(',',' ').split()
        try:
            pc=int(parts[0]); uses=int(parts[1]) if len(parts)>1 else 1; hrs=int(parts[2]) if len(parts)>2 else None
            if not 1<=pc<=90 or not 1<=uses<=10000: raise ValueError
        except Exception:
            await m.reply_text('فرمت درست نیست. مثال: 20 10  (۲۰٪ تخفیف، ۱۰ نفر) یا 20 10 72 (با اعتبار ۷۲ ساعته). برای لغو بنویس «لغو».'); return
        code=make_discount(pc,uses,hrs); context.user_data.pop('gift_step',None)
        await m.reply_text(f'🏷 کد تخفیف ساخته شد:\n\n{code}\n\n{pc}٪ تخفیف | 👥 {uses} بار استفاده'+(f' | ⏳ {hrs} ساعت' if hrs else '')+'\nکاربر از «خرید الماس» ← «کد تخفیف» واردش می‌کنه.'); return
    if gs=='bc_wait' and is_staff(u.id):
        if m.text and m.text.strip()=='لغو':
            context.user_data.pop('gift_step',None); await m.reply_text('لغو شد.'); return
        context.user_data.pop('gift_step',None)
        context.user_data['bc_msg']=(m.chat_id,m.message_id); context.user_data.pop('bc_btns',None)
        await m.reply_text('👆 این پیام برای ارسال همگانی آماده‌ست؛ همون‌طور که هست (با فرمت و مدیا) کپی می‌شه. به کی بفرستم؟',reply_to_message_id=m.message_id,reply_markup=_bc_kb()); return
    if context.user_data.get('tk_step') in ('new','more'):
        if m.text and m.text.strip()=='لغو':
            context.user_data.pop('tk_step',None); context.user_data.pop('tk_id',None); await m.reply_text('لغو شد.',reply_markup=home_kb()); return
        await ticket_submit(m,context,u); return
    if not (m.text or m.photo or m.document): return
    if not await is_member(context.bot,u.id):
        await m.reply_text('برای استفاده باید عضو هر دو کانال باشی.',reply_markup=join_kb()); return
    if gs=='disc' and m.text:
        t=m.text.strip()
        if t=='لغو':
            context.user_data.pop('gift_step',None); await m.reply_text('لغو شد.',reply_markup=home_kb()); return
        res,pc=check_discount(u.id,t)
        if res=='ok':
            context.user_data.pop('gift_step',None); context.user_data['disc']={'code':t.upper(),'pct':pc}
            await m.reply_text(f'✅ کد تخفیف {pc}٪ اعمال شد!\n\n'+buy_text(pc),reply_markup=buy_kb()); return
        msgs={'invalid':'❌ کد معتبر نیست؛ دوباره بفرست یا «لغو» بنویس.','expired':'⌛ این کد تخفیف منقضی شده.','finished':'😕 ظرفیت این کد تموم شده.','already':'ℹ️ این کد رو قبلاً استفاده کردی.'}
        if res!='invalid': context.user_data.pop('gift_step',None)
        await m.reply_text(msgs.get(res,'❌ کد معتبر نیست.')); return
    if context.user_data.get('gift_step')=='redeem' and m.text:
        t=m.text.strip()
        if t=='لغو':
            context.user_data.pop('gift_step',None); await m.reply_text('لغو شد.',reply_markup=home_kb()); return
        now=time.time(); fails=[x for x in context.user_data.get('gift_fail',[]) if now-x<600]
        if len(fails)>=5:
            await m.reply_text('⛔ تلاش‌های اشتباه زیاد بود؛ ۱۰ دقیقه دیگه دوباره امتحان کن.'); return
        res,amt,bal=redeem_gift(u.id,t)
        if res=='ok':
            context.user_data.pop('gift_step',None); context.user_data.pop('gift_fail',None)
            await m.reply_text(f'🎉 کد هدیه ثبت شد!\n💎 {fmt_bal(amt)} الماس به حسابت اضافه شد.\n💰 موجودی جدید: {fmt_bal(bal)} الماس',reply_markup=home_kb()); return
        if res=='invalid':
            fails.append(now); context.user_data['gift_fail']=fails
        msgs={'invalid':'❌ کد معتبر نیست؛ دوباره بفرست یا «لغو» بنویس.','expired':'⌛ این کد منقضی شده.','finished':'😕 ظرفیت این کد تموم شده.','already':'ℹ️ این کد رو قبلاً استفاده کردی.'}
        if res!='invalid': context.user_data.pop('gift_step',None)
        await m.reply_text(msgs.get(res,'❌ کد معتبر نیست.')); return
    plan=context.user_data.get('payment_plan')
    if plan and (m.photo or m.document):
        fid=m.photo[-1].file_id if m.photo else m.document.file_id; fkind='photo' if m.photo else 'document'
        s=get_session()
        try:
            dd=context.user_data.get('disc'); pct=0; dcode=None
            if dd:
                pct=consume_discount(u.id,dd['code'])
                dcode=dd['code'] if pct else None
                context.user_data.pop('disc',None)
            p=Payment(user_id=u.id,plan=plan,status='pending',discount=pct,code=dcode,file_id=fid,file_kind=fkind); s.add(p); s.commit(); pid=p.id
        finally:s.close()
        context.user_data.pop('payment_plan',None)
        final=PRICES.get(plan,0)*(100-pct)//100
        recipients=set(selfbot.ADMIN_IDS)|set(selfbot.SUPPORT_IDS)
        cap=pay_caption(pid,u.id,u.username,plan,pct,dcode)
        for staff in recipients:
            try:
                sm=await send_receipt(context.bot,staff,cap,fid,fkind,pay_kb(pid,staff,None,None))
                _pay_msgs.setdefault(pid,[]).append((staff,sm.message_id))
            except Exception: pass
        await m.reply_text('✅ رسید برای پشتیبانی ارسال شد. بعد از بررسی، الماس‌ها به حسابت اضافه می‌شن.',reply_markup=home_kb()); return
    if context.user_data.get('transfer_step')=='recipient':
        val=m.text.strip() if m.text else ''
        target=None
        if val.startswith('@'):
            try: target=(await context.bot.get_chat(val)).id
            except Exception: pass
        else:
            try: target=int(val)
            except Exception: pass
        if not target or target==u.id: await m.reply_text('آیدی معتبر بفرست؛ نمی‌تونی به خودت انتقال بدی.'); return
        context.user_data['transfer_target']=target; context.user_data['transfer_step']='amount'; await m.reply_text('مقدار الماس رو بفرست (مثلاً 25 یا 10.5):'); return
    if context.user_data.get('transfer_step')=='amount':
        try: amount=Decimal(m.text.strip().replace(',','.'))
        except Exception: amount=Decimal('0')
        target=context.user_data.get('transfer_target'); bal=wallet(u.id)['balance']
        if amount<=0 or amount*10 != (amount*10).to_integral_value() or bal<amount:
            await m.reply_text(f'مقدار نامعتبره یا موجودی کافی نیست. موجودی: {bal}'); return
        # Debit and credit in a single DB transaction
        s=get_session()
        try:
            src=s.get(Wallet,u.id); dst=s.get(Wallet,target)
            if not dst: dst=Wallet(user_id=target,balance=Decimal('0.0'),last_charge=int(time.time())); s.add(dst)
            if Decimal(src.balance)<amount: await m.reply_text('موجودی کافی نیست.'); return
            src.balance=Decimal(src.balance)-amount; dst.balance=Decimal(dst.balance)+amount; s.commit()
        finally:s.close()
        context.user_data.pop('transfer_step',None); context.user_data.pop('transfer_target',None)
        await m.reply_text(f'✅ {amount} الماس به {target} منتقل شد.',reply_markup=home_kb())
        try: await context.bot.send_message(target,f'💎 شما {amount} الماس از کاربر {u.id} دریافت کردید.')
        except Exception: pass
        return
    if m.text and m.text.strip()=='لغو':
        context.user_data.pop('payment_plan',None); context.user_data.pop('transfer_step',None); await m.reply_text('لغو شد.',reply_markup=home_kb())
async def charge_job(context):
    now=int(time.time()); s=get_session()
    try:
        for w in s.query(Wallet).all():
            trial_active = bool(getattr(w, 'trial_until', None) and now < w.trial_until)
            if getattr(w, 'trial_until', None) and now >= w.trial_until:
                w.trial_until = None
                w.self_started = False
                try:
                    selfbot.save_row(w.user_id, enabled=False)
                    context.application.create_task(selfbot.stop_client(w.user_id, restore=True))
                    context.application.create_task(context.bot.send_message(w.user_id, 'دورهٔ رایگان ۳ روزه تموم شد و سلف به‌صورت خودکار قطع شد. برای ادامه، الماس تهیه کن.'))
                except Exception:
                    pass
            # عضویت اجباری: اگر کاربر بعد از دریافت پاداش معرفی از کانال‌ها خارج شود، پاداش ۵۰ الماسی برگردانده می‌شود.
            try:
                member = await is_member(context.bot, w.user_id)
            except Exception:
                member = True
            if not member and w.referred_awarded:
                w.balance=max(Decimal('0.0'), Decimal(w.balance or 0)-Decimal('50.0'))
                if w.referrer:
                    rw=s.get(Wallet,w.referrer)
                    if rw: rw.balance=max(Decimal('0.0'),Decimal(rw.balance or 0)-Decimal('50.0'))
                w.referred_awarded=False
                try: context.application.create_task(context.bot.send_message(w.user_id,'⚠️ از یکی از کانال‌های عضویت اجباری خارج شدی؛ ۵۰ الماس پاداش دعوتت کسر شد. دوباره عضو شو.',reply_markup=join_kb()))
                except Exception: pass
            if trial_active:
                # No diamond deductions during the 72-hour free period.
                continue
            last=w.last_charge or now; hours=(now-last)//3600
            if hours<=0: continue
            rate=Decimal('2.0') if w.self_started else Decimal('0.2')
            cost=rate*hours; w.balance=max(Decimal('0.0'),Decimal(w.balance or 0)-cost); w.last_charge=last+hours*3600
            if w.self_started and Decimal(w.balance)<=0:
                w.self_started=False
                try: selfbot.save_row(w.user_id, enabled=False)
                except Exception: pass
                try: context.application.create_task(selfbot.stop_client(w.user_id,restore=True))
                except Exception: pass
                try: context.application.create_task(context.bot.send_message(w.user_id,'⚠️ الماس‌هات تموم شد و سلف خاموش شد. برای ادامه الماس بخر.'))
                except Exception: pass
            elif cost>0:
                try: context.application.create_task(context.bot.send_message(w.user_id,f'💎 هزینه‌ی {hours} ساعت: {cost} الماس. موجودی فعلی: {w.balance}'))
                except Exception: pass
            if w.self_started and Decimal(w.balance or 0)>0:
                left=Decimal(w.balance)/Decimal('2.0')
                lvl=2 if left<3 else 1 if left<24 else 0
                if lvl==0: _warn_level.pop(w.user_id,None)
                elif lvl>_warn_level.get(w.user_id,0):
                    _warn_level[w.user_id]=lvl
                    try: context.application.create_task(context.bot.send_message(w.user_id,f'⚠️ الماست داره تموم می‌شه!\n💎 موجودی: {fmt_bal(w.balance)} الماس — سلفت حدود {int(left)} ساعت دیگه کار می‌کنه و بعدش خودکار خاموش می‌شه.\nبرای جلوگیری از قطع شدن، شارژ کن 👇',reply_markup=KB([[B('خرید الماس',callback_data='shop:buy')],[B('دعوت دوستان (۵۰ الماس)',callback_data='shop:invite')]])))
                    except Exception: pass
        s.commit()
    finally:s.close()

async def _gift_create(m, context, t):
    parts=t.replace(',',' ').split()
    try:
        amount=Decimal(parts[0]); uses=int(parts[1]) if len(parts)>1 else 1; hours=int(parts[2]) if len(parts)>2 else None
        if amount<=0 or amount>100000 or uses<1 or uses>10000 or (amount*10)!=(amount*10).to_integral_value(): raise ValueError
    except Exception:
        await m.reply_text('فرمت درست نیست. مثال: 100 5  (۱۰۰ الماس، ۵ نفر) یا 100 5 48 (با اعتبار ۴۸ ساعته). برای لغو بنویس «لغو».'); return
    code=make_gift(m.from_user.id, amount, uses, hours)
    context.user_data.pop('gift_step',None)
    await m.reply_text(f'🎁 کد هدیه ساخته شد:\n\n{code}\n\n💎 {fmt_bal(amount)} الماس | 👥 {uses} بار استفاده'+(f' | ⏳ {hours} ساعت' if hours else '')+'\nکاربر باید از «کد هدیه» توی منوی ربات واردش کنه.')

async def gift_cb(update, context):
    q=update.callback_query
    if q.from_user.id not in selfbot.ADMIN_IDS:
        await q.answer('دسترسی نداری.', show_alert=True); return
    await q.answer()
    act=(q.data or '').split(':')[1]
    if act=='new':
        context.user_data['gift_step']='admin_new'
        await q.message.reply_text('🎁 ساخت کد هدیه\n\nمقدار الماس و تعداد دفعات استفاده رو بفرست:\n100 5  ← ۱۰۰ الماس برای ۵ نفر\n100 5 48  ← با اعتبار ۴۸ ساعته\nبرای لغو بنویس «لغو».')
    elif act=='list':
        s=get_session()
        try:
            rows=s.query(GiftCode).order_by(GiftCode.created.desc()).limit(15).all()
            lines=[f'{g.code} | 💎 {fmt_bal(g.amount)} | {g.used}/{g.max_uses}'+(' | ⌛' if g.expires and g.expires<int(time.time()) else '') for g in rows]
        finally:
            s.close()
        await q.message.reply_text('🎟 آخرین کدهای هدیه (کد | الماس | استفاده):\n\n'+('\n'.join(lines) if lines else 'هنوز کدی ساخته نشده.'))

async def adm_cb(update, context):
    q=update.callback_query
    act=(q.data or '').split(':')[1]
    if act in ('bc','bcall','bcself','bccancel','bclink'):
        allowed=is_staff(q.from_user.id)
    else:
        allowed=q.from_user.id in selfbot.ADMIN_IDS
    if not allowed:
        await q.answer('دسترسی نداری.', show_alert=True); return
    await q.answer()
    if act=='stats':
        await q.message.reply_text(stats_text())
    elif act=='bc':
        context.user_data['gift_step']='bc_wait'
        await q.message.reply_text('📢 پیام همگانی\n\nپیامت رو بفرست؛ هر نوعی که باشه همون‌طور برای کاربران کپی می‌شه:\n• متن با فرمت تلگرام: بولد، ایتالیک، زیرخط، خط‌خورده، کد، اسپویلر، نقل‌قول و لینک\n• عکس، ویدیو، گیف، ویس، آهنگ، ویدیو مسیج، فایل یا استیکر (با کپشن)\nبعدش می‌تونی دکمهٔ لینک هم اضافه کنی. برای لغو بنویس «لغو».')
    elif act in ('bcall','bcself'):
        ref=context.user_data.pop('bc_msg',None)
        if not ref:
            await q.message.reply_text('پیامی برای ارسال نیست؛ دوباره از منوی ادمین شروع کن.'); return
        ids=broadcast_ids('all' if act=='bcall' else 'self')
        await q.message.reply_text(f'⏳ ارسال برای {len(ids)} نفر شروع شد؛ بعد از پایان گزارش می‌فرستم.')
        context.application.create_task(_broadcast(context.bot,q.from_user.id,ref[0],ref[1],ids,context.user_data.pop('bc_btns',None)))
    elif act=='bclink':
        if not context.user_data.get('bc_msg'):
            await q.message.reply_text('اول پیام همگانی رو بفرست.'); return
        context.user_data['gift_step']='bc_link'
        await q.message.reply_text('➕ دکمهٔ لینک رو این‌طوری بفرست (تا ۳ خط):\nمتن دکمه | https://example.com')
    elif act=='bccancel':
        context.user_data.pop('bc_msg',None); context.user_data.pop('bc_btns',None); await q.message.reply_text('ارسال همگانی لغو شد.')
    elif act=='dnew':
        context.user_data['gift_step']='disc_new'
        await q.message.reply_text('🏷 ساخت کد تخفیف\n\nدرصد و تعداد دفعات استفاده رو بفرست:\n20 10  ← ۲۰٪ تخفیف برای ۱۰ نفر\n20 10 72  ← با اعتبار ۷۲ ساعته\nبرای لغو بنویس «لغو».')
    elif act=='dlist':
        s=get_session()
        try:
            rows=s.query(DiscountCode).order_by(DiscountCode.created.desc()).limit(15).all()
            lines=[f'{d.code} | {d.percent}٪ | {d.used}/{d.max_uses}'+(' | ⌛' if d.expires and d.expires<int(time.time()) else '') for d in rows]
        finally:
            s.close()
        await q.message.reply_text('🏷 آخرین کدهای تخفیف (کد | درصد | استفاده):\n\n'+('\n'.join(lines) if lines else 'هنوز کدی ساخته نشده.'))

_BAL_RE = r'^\s*(موجودی|موجودی من|موجودی\s*من\s*چقدره|موجودیم)\s*[؟?!.]*\s*$'

def _bal_kb(uid, balance):
    return KB([[B('💎 ' + fmt_bal(balance) + ' الماس', callback_data=f'bal:{uid}')]])

async def balance_cmd(update, context):
    m = update.effective_message; u = update.effective_user
    if not m or not u or not m.text:
        return
    bal = wallet(u.id)['balance']
    try:
        await m.reply_text('💰 موجودی شما', reply_markup=_bal_kb(u.id, bal), reply_to_message_id=m.message_id)
    except Exception:
        pass
    if update.effective_chat.type == 'private':
        raise ApplicationHandlerStop

async def balance_cb(update, context):
    q = update.callback_query
    try:
        owner = int((q.data or '').split(':')[1])
    except Exception:
        await q.answer(); return
    if q.from_user.id != owner:
        await q.answer('این دکمه برای تو نیست؛ خودت بنویس «موجودی».', show_alert=True); return
    w = wallet(owner)
    state = 'روشن ✅' if w['self_started'] else 'خاموش ⏹'
    await q.answer(f'💎 موجودی شما: {fmt_bal(w["balance"])} الماس\n🔌 سلف: {state}', show_alert=True)
    try:
        await q.edit_message_reply_markup(reply_markup=_bal_kb(owner, w['balance']))
    except Exception:
        pass

def setup(app):
    Base.metadata.create_all(__import__('database').engine)
    _migrate_wallet()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(_BAL_RE), balance_cmd), group=-11)
    app.add_handler(CallbackQueryHandler(balance_cb, pattern=r'^bal:'), group=-11)
    app.add_handler(CallbackQueryHandler(gift_cb, pattern=r'^gift:'), group=-20)
    app.add_handler(CallbackQueryHandler(adm_cb, pattern=r'^adm:'), group=-20)
    app.add_handler(CallbackQueryHandler(sup_cb, pattern=r'^sup:'), group=-20)
    app.add_handler(CallbackQueryHandler(tk_cb, pattern=r'^tk:'), group=-20)
    app.add_handler(CommandHandler('start',start),group=-10)
    app.add_handler(CallbackQueryHandler(payment_review, pattern=r'^pay:(approve|reject|claim|info):'), group=-20)
    app.add_handler(CommandHandler('support', support_panel), group=-10)
    app.add_handler(CallbackQueryHandler(callback,pattern=r'^shop:'),group=-10)
    app.add_handler(MessageHandler((~filters.COMMAND)&filters.ChatType.PRIVATE, incoming),group=-10)
    app.job_queue.run_repeating(charge_job, interval=300, first=60, name='diamond-hourly-charges')
