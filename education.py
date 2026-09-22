# -*- coding: utf-8 -*-
"""روباهیو درس: آموزش پنج موضوع با سؤال‌های سه‌گزینه‌ای."""
import json, random
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, BigInteger, Integer, String, DateTime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import Base, User, get_session

TOPICS = {
    "general": ("📚 اطلاعات عمومی", [
        ("کدام سیاره به سیاره سرخ معروف است؟", ["مریخ","زهره","مشتری"], 0),
        ("بزرگ‌ترین اقیانوس جهان کدام است؟", ["اطلس","آرام","هند"], 1),
        ("آب در فشار معمولی در چند درجه می‌جوشد؟", ["۹۰","۱۰۰","۱۲۰"], 1),
        ("پایتخت ژاپن چیست؟", ["توکیو","سئول","پکن"], 0),
        ("کدام گاز بیشترین سهم جو زمین را دارد؟", ["اکسیژن","نیتروژن","هیدروژن"], 1),
    ]),
    "religion": ("🕌 مذهبی", [
        ("نمازهای واجب روزانه چند نماز است؟", ["۳","۵","۷"], 1),
        ("ماه روزه‌داری مسلمانان کدام است؟", ["رمضان","رجب","شوال"], 0),
        ("قبله مسلمانان کدام مکان است؟", ["مسجدالنبی","کعبه","مسجدالاقصی"], 1),
        ("کتاب مقدس اسلام چیست؟", ["تورات","انجیل","قرآن"], 2),
    ]),
    "history_geo": ("🌍 تاریخ و جغرافیا", [
        ("بلندترین قله جهان چیست؟", ["دماوند","اورست","آرارات"], 1),
        ("تمدن هخامنشی با کدام پادشاه آغاز شد؟", ["کوروش بزرگ","داریوش سوم","خشایارشا"], 0),
        ("مصر در کدام قاره قرار دارد؟", ["آسیا","آفریقا","اروپا"], 1),
        ("رود نیل به کدام دریا می‌ریزد؟", ["مدیترانه","سرخ","سیاه"], 0),
    ]),
    "literature": ("📖 ادبیات", [
        ("سراینده شاهنامه کیست؟", ["حافظ","فردوسی","سعدی"], 1),
        ("غزل بیشتر با کدام شاعر شناخته می‌شود؟", ["حافظ","خیام","نظامی"], 0),
        ("نویسنده گلستان کیست؟", ["سعدی","مولوی","عطار"], 0),
        ("مثنوی معنوی اثر کیست؟", ["حافظ","مولوی","فردوسی"], 1),
    ]),
    "math_iq": ("🧠 ریاضی و هوش", [
        ("حاصل ۱۲×۸ چیست؟", ["۸۶","۹۶","۱۰۸"], 1),
        ("عدد بعدی: ۲، ۴، ۸، ۱۶، ؟", ["۲۴","۳۰","۳۲"], 2),
        ("اگر ۳ مداد ۱۵ واحد باشد، یک مداد چند است؟", ["۳","۵","۷"], 1),
        ("کدام عدد اول است؟", ["۲۱","۲۹","۳۹"], 1),
    ]),
}
class EducationProgress(Base):
    __tablename__ = "education_progress"
    user_id = Column(BigInteger, primary_key=True)
    correct = Column(Integer, nullable=False, default=0)
    certificates = Column(Integer, nullable=False, default=0)
    unlocked = Column(String, nullable=False, default="general")
    answered = Column(String, nullable=False, default="{}")
    last_play_at = Column(DateTime(timezone=True), nullable=True)
    active_topic = Column(String, nullable=True)
    active_question = Column(Integer, nullable=True)
    active_expires = Column(DateTime(timezone=True), nullable=True)

def _now(): return datetime.now(timezone.utc)
def _aware(d): return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d
def _threshold(certificates):
    n = 50
    for _ in range(certificates): n *= 3
    return n
def _name(n):
    names=["دانش‌آموز","دانش‌یار","پژوهشگر","دانش‌پژوه","فرهیخته","استاد کوچک","استاد دانا","متفکر","دانشمند","نابغه","حکیم","پروفسور","استاد بزرگ","خردمند","دانای روباهیو"]
    return names[min(n, len(names)-1)]
def _kb(topic, qid, options):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{i+1}) {v}", callback_data=f"edu:{topic}:{qid}:{i}")] for i,v in enumerate(options)])

async def education_command(update, context):
    s=get_session()
    try:
        u=s.get(User, update.effective_user.id)
        if not u: return await update.message.reply_text("ابتدا با /start وارد شو.")
        p=s.get(EducationProgress,u.telegram_id)
        if not p:
            p=EducationProgress(user_id=u.telegram_id); s.add(p); s.commit()
        unlocked=set((p.unlocked or "general").split(","))
        lines=["📚 روباهیو درس\n","موضوع‌ها:"]
        for k,(title,_) in TOPICS.items():
            status="✅ باز" if k in unlocked else "🔒 قفل — ۳۰٬۰۰۰ روب‌پوینت"
            lines.append(f"{title}: {status}")
        lines += [f"\n🎓 پاسخ‌های درست: {p.correct}",f"🏅 مدارک: {p.certificates}/۱۵",f"📈 تا مدرک بعدی: {max(0,_threshold(p.certificates)-p.correct)} پاسخ درست"]
        if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1800:
            left=1800-int((_now()-_aware(p.last_play_at)).total_seconds())
            return await update.message.reply_text("\n".join(lines)+f"\n\n⏳ سؤال بعدی تا {left//60} دقیقه دیگر.")
        await update.message.reply_text("\n".join(lines)+"\n\nبرای شروع، موضوع را انتخاب کن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TOPICS[k][0],callback_data=f"edutopic:{k}")] for k in TOPICS]))
    finally: s.close()

async def education_topic(update, context):
    q=update.callback_query; topic=q.data.split(":")[1]; s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id)
        if topic not in set((p.unlocked or "general").split(",")):
            u=s.get(User,q.from_user.id)
            if (u.points or 0)<30000: return await q.answer("برای بازکردن این موضوع ۳۰٬۰۰۰ روب‌پوینت لازم است.",show_alert=True)
            u.points-=30000; p.unlocked=(p.unlocked or "general")+","+topic; s.commit()
        if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1800: return await q.answer("هر ۳۰ دقیقه یک سؤال مجاز است.",show_alert=True)
        seen=json.loads(p.answered or "{}"); used=set(seen.get(topic,[])); pool=TOPICS[topic][1]
        available=[i for i in range(len(pool)) if i not in used]
        if not available:
            seen[topic]=[]; available=list(range(len(pool)))
        qid=random.choice(available); question,opts,correct=pool[qid]
        p.active_topic=topic; p.active_question=qid; p.active_expires=_now()+timedelta(seconds=15); p.last_play_at=_now(); s.commit()
        await q.answer(); await q.edit_message_text(f"{TOPICS[topic][0]}\n\n❓ {question}\n\n⏱ ۱۵ ثانیه فرصت داری.",reply_markup=_kb(topic,qid,opts))
    finally: s.close()

async def education_answer(update, context):
    q=update.callback_query
    _,topic,qid_s,choice_s=q.data.split(":"); qid=int(qid_s); choice=int(choice_s); s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id)
        if not p or p.active_topic!=topic or p.active_question!=qid or not p.active_expires or _now()>_aware(p.active_expires):
            return await q.answer("⏰ زمان سؤال تمام شده؛ بازی به پایان رسید.",show_alert=True)
        question,opts,correct=TOPICS[topic][1][qid]
        seen=json.loads(p.answered or "{}"); seen.setdefault(topic,[]).append(qid); p.answered=json.dumps(seen)
        p.active_topic=None; p.active_question=None; p.active_expires=None
        if choice!=correct:
            s.commit(); return await q.edit_message_text("❌ پاسخ اشتباه بود؛ این دور تمام شد. ۳۰ دقیقه بعد دوباره تلاش کن.")
        p.correct+=2
        msg=f"✅ درست! +۲ واحد\n📊 مجموع واحدها: {p.correct}"
        if p.certificates<15 and p.correct>=_threshold(p.certificates):
            p.certificates+=1; msg+=f"\n🏅 مدرک جدید: {_name(p.certificates)}\n🎓 مدارک: {p.certificates}/۱۵"
        s.commit(); await q.answer("آفرین! پاسخ درست بود 🎉"); await q.edit_message_text(msg+f"\n📈 تا مدرک بعدی: {max(0,_threshold(p.certificates)-p.correct)} پاسخ درست")
    finally: s.close()

def education_profile_line(session,user_id):
    p=session.get(EducationProgress,user_id)
    if not p: return "🎓 تحصیلات: هنوز مدرکی دریافت نکرده"
    return f"🎓 تحصیلات: {_name(p.certificates)}\n🏅 مدارک: {p.certificates}/۱۵\n📈 تا مدرک بعدی: {max(0,_threshold(p.certificates)-p.correct)} پاسخ درست"
