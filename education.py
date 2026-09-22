# -*- coding: utf-8 -*-
"""روباهیو درس: پنج موضوع، سؤال‌های سه‌گزینه‌ای، زمان ۱۵ ثانیه و فاصله ۲۵ دقیقه‌ای و مدارک."""
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
        ("واحد اندازه‌گیری شدت جریان برق چیست؟", ["ولت","آمپر","وات"], 1),
        ("کدام فلز نماد شیمیایی Au دارد؟", ["نقره","آهن","طلا"], 2),
        ("نور خورشید تقریباً چند دقیقه تا زمین می‌رسد؟", ["۸ دقیقه","۸۰ دقیقه","۱ ثانیه"], 0),
        ("کدام اندام اکسیژن را وارد خون می‌کند؟", ["کبد","ریه","معده"], 1),
        ("بزرگ‌ترین سیاره منظومه شمسی کدام است؟", ["زحل","مریخ","مشتری"], 2),
    ]),
    "religion": ("🕌 مذهبی", [
        ("نمازهای واجب روزانه چند نماز است؟", ["۳","۵","۷"], 1),
        ("ماه روزه‌داری مسلمانان کدام است؟", ["رمضان","رجب","شوال"], 0),
        ("قبله مسلمانان کدام مکان است؟", ["مسجدالنبی","کعبه","مسجدالاقصی"], 1),
        ("کتاب مقدس اسلام چیست؟", ["تورات","انجیل","قرآن"], 2),
        ("کدام پیامبر به ساخت کشتی مشهور است؟", ["نوح(ع)","یوسف(ع)","یونس(ع)"], 0),
        ("زکات و نماز در کدام دسته قرار می‌گیرند؟", ["احکام عبادی","ورزش‌ها","علوم طبیعی"], 0),
        ("سوره‌ای که با «الحمدلله رب العالمین» آغاز می‌شود کدام است؟", ["ناس","حمد","کوثر"], 1),
        ("عید فطر پس از پایان کدام ماه می‌آید؟", ["محرم","رمضان","ذی‌الحجه"], 1),
        ("کدام نماز در روز جمعه اهمیت ویژه دارد؟", ["نماز جمعه","نماز وتر","نماز میت"], 0),
        ("کعبه در کدام شهر قرار دارد؟", ["مدینه","مکه","نجف"], 1),
    ]),
    "history_geo": ("🌍 تاریخ و جغرافیا", [
        ("بلندترین قله جهان چیست؟", ["دماوند","اورست","آرارات"], 1),
        ("تمدن هخامنشی با کدام پادشاه آغاز شد؟", ["کوروش بزرگ","داریوش سوم","خشایارشا"], 0),
        ("مصر در کدام قاره قرار دارد؟", ["آسیا","آفریقا","اروپا"], 1),
        ("رود نیل به کدام دریا می‌ریزد؟", ["مدیترانه","سرخ","سیاه"], 0),
        ("پایتخت امپراتوری هخامنشی در دوره‌ای کدام بود؟", ["تخت‌جمشید","رم","آتن"], 0),
        ("کشور برزیل در کدام قاره است؟", ["آفریقا","آمریکای جنوبی","اروپا"], 1),
        ("کدام شهر تاریخی در ایتالیا قرار دارد؟", ["رم","کیپ‌تاون","دهلی"], 0),
        ("تنگه هرمز کدام دو پهنه آبی را به هم مرتبط می‌کند؟", ["خلیج فارس و دریای عمان","دریای سیاه و سرخ","مدیترانه و اطلس"], 0),
        ("انقلاب صنعتی نخست در کدام کشور آغاز شد؟", ["بریتانیا","ژاپن","مصر"], 0),
        ("خط استوا زمین را به کدام دو نیم‌کره تقسیم می‌کند؟", ["شرقی و غربی","شمالی و جنوبی","خشکی و آبی"], 1),
    ]),
    "literature": ("📖 ادبیات", [
        ("سراینده شاهنامه کیست؟", ["حافظ","فردوسی","سعدی"], 1),
        ("غزل بیشتر با کدام شاعر شناخته می‌شود؟", ["حافظ","خیام","نظامی"], 0),
        ("نویسنده گلستان کیست؟", ["سعدی","مولوی","عطار"], 0),
        ("مثنوی معنوی اثر کیست؟", ["حافظ","مولوی","فردوسی"], 1),
        ("رباعی بیشتر با نام کدام شاعر پیوند دارد؟", ["خیام","نظامی","پروین"], 0),
        ("شاهنامه بیشتر درباره چیست؟", ["تاریخ و اسطوره ایران","گیاه‌شناسی","نجوم مدرن"], 0),
        ("کدام اثر از سعدی است؟", ["بوستان","منطق‌الطیر","منظومه حیدربابایه سلام"], 0),
        ("آرایه تشبیه بر پایه چه چیزی شکل می‌گیرد؟", ["همانندی","تضاد عددی","قافیه‌زدایی"], 0),
        ("کدام گزینه قالب شعری است؟", ["غزل","فصل‌نامه","گزارش"], 0),
        ("نویسنده «بوف کور» کیست؟", ["صادق هدایت","جلال آل‌احمد","نیما یوشیج"], 0),
    ]),
    "math_iq": ("🧠 ریاضی و هوش", [
        ("حاصل ۱۲×۸ چیست؟", ["۸۶","۹۶","۱۰۸"], 1),
        ("عدد بعدی: ۲، ۴، ۸، ۱۶، ؟", ["۲۴","۳۰","۳۲"], 2),
        ("اگر ۳ مداد ۱۵ واحد باشد، یک مداد چند است؟", ["۳","۵","۷"], 1),
        ("کدام عدد اول است؟", ["۲۱","۲۹","۳۹"], 1),
        ("حاصل ۱۵² چیست؟", ["۲۲۵","۲۱۵","۲۵۰"], 0),
        ("اگر همه گربه‌ها پستاندار باشند و میلو گربه باشد، میلو چیست؟", ["پرنده","پستاندار","خزنده"], 1),
        ("عدد بعدی: ۳، ۶، ۱۲، ۲۴، ؟", ["۳۶","۴۸","۵۴"], 1),
        ("یک‌چهارم ۱۰۰ چند است؟", ["۲۰","۲۵","۴۰"], 1),
        ("محیط مربع با ضلع ۷ چند است؟", ["۱۴","۲۸","۴۹"], 1),
        ("اگر امروز دوشنبه باشد، ۱۰ روز بعد چه روزی است؟", ["چهارشنبه","پنجشنبه","جمعه"], 1),
    ]),
}

class EducationProgress(Base):
    __tablename__ = "education_progress"
    user_id = Column(BigInteger, primary_key=True)
    correct = Column(Integer, nullable=False, default=0)          # واحدها؛ هر پاسخ درست +۲
    correct_answers = Column(Integer, nullable=False, default=0)  # تعداد پاسخ‌های درست
    certificates = Column(Integer, nullable=False, default=0)
    unlocked = Column(String, nullable=False, default="general")
    answered = Column(String, nullable=False, default="{}")
    last_play_at = Column(DateTime(timezone=True), nullable=True)
    active_topic = Column(String, nullable=True)
    active_question = Column(Integer, nullable=True)
    active_expires = Column(DateTime(timezone=True), nullable=True)
    pending_certificate = Column(Integer, nullable=False, default=0)

def _now(): return datetime.now(timezone.utc)
def _aware(d): return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d
def _threshold(certificates): return 50 * (3 ** certificates)
def _tuition(certificates): return 50000 + (20000 * certificates)
def _reward(certificates): return 150000 + (50000 * certificates)
def _name(n):
    names=["دانش‌آموز","دانش‌یار","پژوهشگر","دانش‌پژوه","فرهیخته","استاد کوچک","استاد دانا","متفکر","دانشمند","نابغه","حکیم","پروفسور","استاد بزرگ","خردمند","دانای روباهیو"]
    return names[min(n, len(names)-1)]
def _kb(topic, qid, options):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{i+1}) {v}", callback_data=f"edu:{topic}:{qid}:{i}")] for i,v in enumerate(options)])
def _confirm_unlock(topic):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ بله، خرید", callback_data=f"eduunlock:yes:{topic}"), InlineKeyboardButton("❌ خیر", callback_data="eduunlock:no:general")]])
def _confirm_certificate():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ بله، پرداخت و دریافت مدرک", callback_data="educert:yes"), InlineKeyboardButton("❌ خیر", callback_data="educert:no")]])

def _progress_text(p):
    remaining=max(0,_threshold(p.certificates)-int(p.correct_answers or 0)) if p.certificates<15 else 0
    return f"🎓 پاسخ‌های درست: {int(p.correct_answers or 0)}\n🔹 واحدها: {int(p.correct or 0)}\n🏅 مدارک: {p.certificates}/۱۵\n📈 تا مدرک بعدی: {remaining} پاسخ درست"

async def education_command(update, context):
    s=get_session()
    try:
        u=s.get(User, update.effective_user.id)
        if not u: return await update.message.reply_text("ابتدا با /start وارد شو.")
        p=s.get(EducationProgress,u.telegram_id)
        if not p: p=EducationProgress(user_id=u.telegram_id); s.add(p); s.commit()
        unlocked=set((p.unlocked or "general").split(","))
        lines=["📚 روباهیو درس\n","موضوع‌ها:"]
        for k,(title,_) in TOPICS.items():
            status="✅ باز" if k in unlocked else "🔒 قفل — ۳۰٬۰۰۰ روب‌پوینت"
            lines.append(f"{title}: {status}")
        lines.append("\n"+_progress_text(p))
        if p.pending_certificate:
            lines.append(f"\n🎓 برای دریافت مدرک {_name(p.certificates+1)} باید { _tuition(p.certificates):,} روب‌پوینت شهریه پرداخت کنی.")
        if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1500:
            left=1500-int((_now()-_aware(p.last_play_at)).total_seconds())
            return await update.message.reply_text("\n".join(lines)+f"\n\n⏳ سؤال بعدی تا {left//60} دقیقه دیگر.")
        await update.message.reply_text("\n".join(lines)+"\n\nبرای شروع، موضوع را انتخاب کن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TOPICS[k][0],callback_data=f"edutopic:{k}")] for k in TOPICS]))
    finally: s.close()

async def education_topic(update, context):
    q=update.callback_query; topic=q.data.split(":")[1]; s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id); u=s.get(User,q.from_user.id)
        if not p or not u: return await q.answer("ابتدا ربات را استارت کن.",show_alert=True)
        if topic not in set((p.unlocked or "general").split(",")):
            return await q.edit_message_text(f"🔒 {TOPICS[topic][0]}\n\nبرای بازکردن این موضوع ۳۰٬۰۰۰ روب‌پوینت لازم است.\nآیا خرید را تأیید می‌کنی؟", reply_markup=_confirm_unlock(topic))
        if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1500: return await q.answer("هر ۲۵ دقیقه یک سؤال مجاز است.",show_alert=True)
        return await _start_question(q,s,p,topic)
    finally: s.close()

async def _start_question(q,s,p,topic):
    seen=json.loads(p.answered or "{}"); used=set(seen.get(topic,[])); pool=TOPICS[topic][1]
    available=[i for i in range(len(pool)) if i not in used]
    if not available:
        seen[topic]=[]; available=list(range(len(pool)))
    qid=random.choice(available); question,opts,correct=pool[qid]
    p.active_topic=topic; p.active_question=qid; p.active_expires=_now()+timedelta(seconds=15); p.last_play_at=_now(); s.commit()
    await q.answer(); await q.edit_message_text(f"{TOPICS[topic][0]}\n\n❓ {question}\n\n⏱ ۱۵ ثانیه فرصت داری.",reply_markup=_kb(topic,qid,opts))

async def education_unlock(update, context):
    q=update.callback_query; _,decision,topic=q.data.split(":"); s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id); u=s.get(User,q.from_user.id)
        if not p or not u: return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
        if decision=="no": await q.answer("خرید لغو شد."); return await q.edit_message_text("❌ خرید موضوع لغو شد.")
        if not u or (u.fox_points or 0)<30000: return await q.answer("روب‌پوینت کافی نیست.",show_alert=True)
        unlocked=set((p.unlocked or "general").split(","))
        if topic not in unlocked: unlocked.add(topic); p.unlocked=",".join(sorted(unlocked)); u.fox_points-=30000
        s.commit(); await q.answer("موضوع با موفقیت خریداری شد ✅")
        if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1500: return await q.edit_message_text("✅ موضوع باز شد. هر ۲۵ دقیقه یک سؤال مجاز است.")
        await _start_question(q,s,p,topic)
    finally: s.close()

async def education_answer(update, context):
    q=update.callback_query; _,topic,qid_s,choice_s=q.data.split(":"); qid=int(qid_s); choice=int(choice_s); s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id)
        if not p or p.active_topic!=topic or p.active_question!=qid or not p.active_expires or _now()>_aware(p.active_expires):
            if p: p.active_topic=None; p.active_question=None; p.active_expires=None; s.commit()
            return await q.answer("⏰ زمان سؤال تمام شد؛ این دور پایان یافت.",show_alert=True)
        question,opts,correct=TOPICS[topic][1][qid]
        seen=json.loads(p.answered or "{}"); seen.setdefault(topic,[]).append(qid); p.answered=json.dumps(seen)
        p.active_topic=None; p.active_question=None; p.active_expires=None
        if choice!=correct:
            s.commit(); return await q.edit_message_text("❌ پاسخ اشتباه بود؛ بازی تمام شد. ۲۵ دقیقه بعد دوباره تلاش کن.")
        p.correct_answers=int(p.correct_answers or 0)+1; p.correct=int(p.correct or 0)+2
        msg=f"✅ درست! +۲ واحد\n📊 مجموع واحدها: {p.correct}\n🎯 پاسخ‌های درست: {p.correct_answers}"
        if p.certificates<15 and p.correct_answers>=_threshold(p.certificates):
            p.pending_certificate=1
            msg+=f"\n\n🎓 به حد نصاب مدرک {_name(p.certificates+1)} رسیدی!\n💳 شهریه: {_tuition(p.certificates):,} روب‌پوینت\n🎁 جایزه: {_reward(p.certificates):,} روب‌پوینت\nآیا پرداخت و دریافت مدرک را تأیید می‌کنی؟"
            s.commit(); await q.answer("به حد نصاب رسیدی 🎓"); return await q.edit_message_text(msg,reply_markup=_confirm_certificate())
        s.commit(); await q.answer("آفرین! پاسخ درست بود 🎉"); await q.edit_message_text(msg+f"\n📈 تا مدرک بعدی: {max(0,_threshold(p.certificates)-p.correct_answers) if p.certificates<15 else 0} پاسخ درست")
    finally: s.close()

async def education_certificate(update, context):
    q=update.callback_query; decision=q.data.split(":")[1]; s=get_session()
    try:
        p=s.get(EducationProgress,q.from_user.id); u=s.get(User,q.from_user.id)
        if not p or not u: return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
        if decision=="no": await q.answer("دریافت مدرک لغو شد."); return await q.edit_message_text("❌ دریافت مدرک فعلاً لغو شد؛ می‌توانی بعداً تأیید کنی.")
        if not p or not p.pending_certificate: return await q.answer("مدرک در انتظار تأیید وجود ندارد.",show_alert=True)
        cost=_tuition(p.certificates); reward=_reward(p.certificates)
        if not u or int(u.fox_points or 0)<cost: return await q.answer(f"روب‌پوینت کافی نیست؛ شهریه {cost:,} است.",show_alert=True)
        u.fox_points-=cost; u.fox_points+=reward; p.certificates+=1; p.pending_certificate=0; s.commit()
        await q.answer("مدرک صادر شد 🎓")
        await q.edit_message_text(f"🎉 مدرک جدید دریافت شد!\n🏅 {_name(p.certificates)}\n💳 شهریه پرداخت‌شده: {cost:,}\n🎁 جایزه دریافتی: {reward:,} روب‌پوینت\n💰 خالص تغییر موجودی: {reward-cost:+,}\n🏅 مدارک: {p.certificates}/۱۵\n📈 تا مدرک بعدی: {max(0,_threshold(p.certificates)-p.correct_answers) if p.certificates<15 else 0} پاسخ درست")
    finally: s.close()

def education_profile_line(session,user_id):
    p=session.get(EducationProgress,user_id)
    if not p: return "🎓 تحصیلات: هنوز مدرکی دریافت نکرده"
    return f"🎓 تحصیلات: {_name(p.certificates)}"
