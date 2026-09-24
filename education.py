# -*- coding: utf-8 -*-
"""روباهیو درس: پنج موضوع، سؤال‌های سه‌گزینه‌ای، زمان ۱۵ ثانیه و فاصله ۲۵ دقیقه‌ای و مدارک."""
import json, random, logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Text
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import Base, User, get_session
from config import ADMIN_IDS

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

class EduUserQuestion(Base):
    """سؤال طراحی‌شده‌ی کاربر: بعد از تأیید پشتیبانی وارد چرخه‌ی سؤال‌های همان موضوع می‌شود."""
    __tablename__ = "edu_user_questions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(BigInteger, nullable=False, index=True)
    topic = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    correct_opt = Column(String, nullable=False)
    wrong1 = Column(String, nullable=False)
    wrong2 = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")   # pending / approved / rejected
    day_key = Column(String, nullable=False)                      # روزِ ثبت (به وقت ایران) برای سقف روزانه
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(BigInteger, nullable=True)
    admin_msgs = Column(Text, nullable=False, default="[]")       # [[chat_id, message_id], ...] پیام‌های ارسال‌شده به پشتیبان‌ها

USER_Q_OFFSET = 1_000_000     # شناسه‌ی سؤال کاربر در callback_data: OFFSET + id ردیف (سؤال‌های داخلی زیر OFFSET هستند)
USER_Q_DAILY_LIMIT = 3        # حداکثر سؤال در روز برای هر موضوع
USER_Q_REWARD = 1500          # جایزه‌ی هر سؤالِ تأییدشده (روب‌پوینت)
mention_hook = None           # bot.py آن را با user_mention (لینک آبی اسم) جایگزین می‌کند

def _author_name(u):
    if u is None: return "کاربر"
    if mention_hook:
        try: return mention_hook(u)
        except Exception: pass
    return u.first_name or u.username or str(u.telegram_id)

def _day_key():
    return (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d")   # روز به وقت ایران

def _now(): return datetime.now(timezone.utc)
def _aware(d): return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d
# تعداد کل پاسخ‌های درستِ لازم برای هر مدرک (تجمعی، نه فقط برای همون مرحله):
# شروع از ۱۰ و ۱۵ و ۲۵ و بعد رشدِ ملایم و پیوسته تا مدرک آخر (پونزدهم) که ۷۵۰ می‌شود.
_CERT_THRESHOLDS = [10, 15, 25, 40, 63, 95, 135, 183, 239, 304, 377, 458, 547, 645, 750]
def _threshold(certificates): return _CERT_THRESHOLDS[min(certificates, len(_CERT_THRESHOLDS)-1)]
def _tuition(certificates): return 50000 + (20000 * certificates)
def _reward(certificates): return 150000 + (50000 * certificates)
def _name(n):
    names=["دانش‌آموز","دانش‌یار","پژوهشگر","دانش‌پژوه","فرهیخته","استاد کوچک","استاد دانا","متفکر","دانشمند","نابغه","حکیم","پروفسور","استاد بزرگ","خردمند","دانای روباهیو"]
    return names[min(n, len(names)-1)]
def _kb(topic, qid, options):
    # options: لیست متن‌ها یا لیست (شماره‌ی اصلی گزینه، متن)؛ شماره‌ی اصلی داخل callback می‌رود تا ترتیب نمایش می‌تواند بُر بخورد.
    pairs = [o if isinstance(o, tuple) else (i, o) for i, o in enumerate(options)]
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{pos+1}) {v}", callback_data=f"edu:{topic}:{qid}:{i}")] for pos,(i,v) in enumerate(pairs)])
def _confirm_unlock(topic):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ بله، خرید", callback_data=f"eduunlock:yes:{topic}"), InlineKeyboardButton("❌ خیر", callback_data="eduunlock:no:general")]])
def _confirm_certificate():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ بله، پرداخت و دریافت مدرک", callback_data="educert:yes"), InlineKeyboardButton("❌ خیر", callback_data="educert:no")]])

def _progress_text(p):
    remaining=max(0,_threshold(p.certificates)-int(p.correct_answers or 0)) if p.certificates<15 else 0
    return f"🎓 پاسخ‌های درست: {int(p.correct_answers or 0)}\n🔹 واحدها: {int(p.correct or 0)}\n🏅 مدارک: {p.certificates}/۱۵\n📈 تا مدرک بعدی: {remaining} پاسخ درست"

def _edu_panel(s, u, p):
    """(متن، کیبورد) پنل اصلی درس؛ هم برای /روباهیو درس و هم برای برگشت از طرح سؤال."""
    unlocked=set((p.unlocked or "general").split(","))
    lines=["📚 روباهیو درس\n","موضوع‌ها:"]
    for k,(title,_) in TOPICS.items():
        status="✅ باز" if k in unlocked else "🔒 قفل — ۳۰٬۰۰۰ روب‌پوینت"
        lines.append(f"{title}: {status}")
    lines.append("\n"+_progress_text(p))
    if p.pending_certificate:
        lines.append(f"\n🎓 برای دریافت مدرک {_name(p.certificates+1)} باید { _tuition(p.certificates):,} روب‌پوینت شهریه پرداخت کنی.")
    ask_row=[InlineKeyboardButton("✍️ طرح سوال (۱٬۵۰۰ روب‌پوینت جایزه)",callback_data="eduq:menu")]
    if p.last_play_at and (_now()-_aware(p.last_play_at)).total_seconds()<1500:
        left=1500-int((_now()-_aware(p.last_play_at)).total_seconds())
        return "\n".join(lines)+f"\n\n⏳ سؤال بعدی تا {left//60} دقیقه دیگر.", InlineKeyboardMarkup([ask_row])
    rows=[[InlineKeyboardButton(TOPICS[k][0],callback_data=f"edutopic:{k}")] for k in TOPICS]+[ask_row]
    return "\n".join(lines)+"\n\nبرای شروع، موضوع را انتخاب کن:", InlineKeyboardMarkup(rows)

async def education_command(update, context):
    s=get_session()
    try:
        u=s.get(User, update.effective_user.id)
        if not u: return await update.message.reply_text("ابتدا با /start وارد شو.")
        p=s.get(EducationProgress,u.telegram_id)
        if not p: p=EducationProgress(user_id=u.telegram_id); s.add(p); s.commit()
        text,kb=_edu_panel(s,u,p)
        await update.message.reply_text(text, reply_markup=kb)
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
    # سؤال‌های طراحی‌شده‌ی کاربران (تأییدشده)؛ سؤال‌های خودِ کاربر به خودش داده نمی‌شود.
    user_qs={USER_Q_OFFSET+r.id: r for r in s.query(EduUserQuestion).filter(EduUserQuestion.topic==topic, EduUserQuestion.status=="approved", EduUserQuestion.author_id!=p.user_id).all()}
    all_ids=list(range(len(pool)))+list(user_qs.keys())
    available=[i for i in all_ids if i not in used]
    if not available:                    # همه‌ی سؤال‌های این موضوع دیده شد → دور از اول
        seen[topic]=[]; p.answered=json.dumps(seen); available=all_ids
    qid=random.choice(available)
    designer=""
    if qid>=USER_Q_OFFSET:
        r=user_qs[qid]; question=r.question
        opts=[(0,r.correct_opt),(1,r.wrong1),(2,r.wrong2)]; random.shuffle(opts)     # درست همیشه شماره‌ی اصلی ۰ است، ترتیب نمایش بُر می‌خورد
        designer=f"\n✍️ طراح: {_author_name(s.get(User,r.author_id))}"
    else:
        question,opts,correct=pool[qid]
    p.active_topic=topic; p.active_question=qid; p.active_expires=_now()+timedelta(seconds=15); p.last_play_at=_now(); s.commit()
    await q.answer(); await q.edit_message_text(f"{TOPICS[topic][0]}\n\n❓ {question}{designer}\n\n⏱ ۱۵ ثانیه فرصت داری.",reply_markup=_kb(topic,qid,opts))

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
        if qid>=USER_Q_OFFSET:
            r=s.get(EduUserQuestion,qid-USER_Q_OFFSET)
            if not r or r.status!="approved" or r.topic!=topic:
                p.active_topic=None; p.active_question=None; p.active_expires=None; s.commit()
                return await q.answer("این سؤال دیگر در دسترس نیست؛ دوباره تلاش کن.",show_alert=True)
            correct=0
        else:
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


# ======================= طرح سؤال توسط کاربر =======================
# جریان: موضوع → متن سؤال → گزینه‌ی درست → دو گزینه‌ی نادرست → تأیید → ارسال برای پشتیبانی.
# همه‌ی مرحله‌ها روی همان پیامِ پنل ویرایش می‌شوند. پشتیبان تأیید کند: ۱۵۰۰ روب‌پوینت به طراح
# داده می‌شود و سؤال (با اسم طراح) وارد چرخه‌ی همان موضوع می‌شود.
_Q_PROMPTS = {
    "question": "❓ متن سؤال را بفرست (حداکثر ۲۰۰ کاراکتر).",
    "correct": "✅ حالا گزینه‌ی درست را بفرست.",
    "wrong1": "❌ حالا گزینه‌ی نادرست اول را بفرست.",
    "wrong2": "❌ حالا گزینه‌ی نادرست دوم را بفرست.",
}
_Q_ORDER = ["question", "correct", "wrong1", "wrong2"]
_Q_LIMITS = {"question": (5, 200), "correct": (1, 40), "wrong1": (1, 40), "wrong2": (1, 40)}

def _norm_opt(t): return " ".join((t or "").split()).casefold()

def _cancel_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="eduq:cancel")]])

def _draft_text(st, prompt=None):
    d = st["data"]; lines = [f"✍️ طرح سؤال — {TOPICS[st['topic']][0]}", ""]
    if "question" in d: lines.append(f"❓ {d['question']}")
    if "correct" in d: lines.append(f"✅ {d['correct']}")
    if "wrong1" in d: lines.append(f"❌ {d['wrong1']}")
    if "wrong2" in d: lines.append(f"❌ {d['wrong2']}")
    if prompt: lines += ["", prompt]
    return "\n".join(lines)

def _remaining(s, uid, topic):
    used = s.query(EduUserQuestion).filter(EduUserQuestion.author_id == uid, EduUserQuestion.topic == topic, EduUserQuestion.day_key == _day_key()).count()
    return max(0, USER_Q_DAILY_LIMIT - used)

async def _safe_edit_msg(message, text, markup=None):
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception as e:
        if "not modified" not in str(e).lower(): raise

async def eduq_button(update, context):
    q = update.callback_query; parts = (q.data or "").split(":"); action = parts[1] if len(parts) > 1 else ""
    uid = q.from_user.id
    if action == "cancel":
        context.user_data.pop("edu_q", None)
        action = "back"
    if action == "back":
        s = get_session()
        try:
            u = s.get(User, uid)
            if not u: return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
            p = s.get(EducationProgress, uid)
            if not p: p = EducationProgress(user_id=uid); s.add(p); s.commit()
            text, kb = _edu_panel(s, u, p)
        finally: s.close()
        await q.answer(); return await _safe_edit_msg(q.message, text, kb)
    if action == "menu":
        context.user_data.pop("edu_q", None)
        s = get_session()
        try:
            if not s.get(User, uid): return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
            rows = [[InlineKeyboardButton(f"{TOPICS[k][0]} — {_remaining(s, uid, k)}/{USER_Q_DAILY_LIMIT} باقی", callback_data=f"eduq:t:{k}")] for k in TOPICS]
        finally: s.close()
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="eduq:back")])
        await q.answer()
        return await _safe_edit_msg(q.message,
            "✍️ طرح سؤال\n\nموضوع سؤالت را انتخاب کن.\n"
            f"📌 روزی حداکثر {USER_Q_DAILY_LIMIT} سؤال برای هر موضوع.\n"
            f"🎁 هر سؤالی که پشتیبانی تأیید کند {USER_Q_REWARD:,} روب‌پوینت می‌گیری و سؤالت با اسم تو وارد چرخه‌ی درس می‌شود.",
            InlineKeyboardMarkup(rows))
    if action == "t" and len(parts) > 2 and parts[2] in TOPICS:
        topic = parts[2]; s = get_session()
        try:
            if not s.get(User, uid): return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
            left = _remaining(s, uid, topic)
        finally: s.close()
        if left <= 0: return await q.answer(f"⛔ امروز برای این موضوع {USER_Q_DAILY_LIMIT} سؤال فرستادی؛ فردا دوباره بیا.", show_alert=True)
        st = {"step": "question", "topic": topic, "ref": (q.message.chat_id, q.message.message_id), "data": {}}
        context.user_data["edu_q"] = st
        await q.answer()
        return await _safe_edit_msg(q.message, _draft_text(st, _Q_PROMPTS["question"]), _cancel_kb())
    if action == "send":
        st = context.user_data.get("edu_q")
        if not st or st.get("step") != "confirm":
            return await q.answer("درخواستی برای ارسال پیدا نشد؛ از اول شروع کن.", show_alert=True)
        return await _submit_question(q, context, st)
    await q.answer()

async def _submit_question(q, context, st):
    uid = q.from_user.id; topic = st["topic"]; d = st["data"]; s = get_session()
    try:
        u = s.get(User, uid)
        if not u: return await q.answer("ابتدا ربات را استارت کن.", show_alert=True)
        if _remaining(s, uid, topic) <= 0:
            context.user_data.pop("edu_q", None)
            return await q.answer(f"⛔ سقف {USER_Q_DAILY_LIMIT} سؤال در روز برای این موضوع پر شده.", show_alert=True)
        row = EduUserQuestion(author_id=uid, topic=topic, question=d["question"], correct_opt=d["correct"],
                              wrong1=d["wrong1"], wrong2=d["wrong2"], status="pending", day_key=_day_key())
        s.add(row); s.commit()
        context.user_data.pop("edu_q", None)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ تأیید (+{USER_Q_REWARD:,})", callback_data=f"eduqa:ok:{row.id}"),
                                    InlineKeyboardButton("❌ رد", callback_data=f"eduqa:no:{row.id}")]])
        card = _admin_card(row, u, "⏳ در انتظار بررسی")
        refs = []
        for admin_id in ADMIN_IDS:
            try:
                m = await context.bot.send_message(admin_id, card, reply_markup=kb)
                refs.append([admin_id, m.message_id])
            except Exception as e:
                logging.getLogger(__name__).warning("edu question delivery failed for admin %s: %s", admin_id, e)
        row.admin_msgs = json.dumps(refs); s.commit()
    finally: s.close()
    await q.answer("✅ برای پشتیبانی ارسال شد.")
    await _safe_edit_msg(q.message,
        "✅ سؤالت برای پشتیبانی ارسال شد.\n"
        f"اگر تأیید شود {USER_Q_REWARD:,} روب‌پوینت می‌گیری و سؤالت با اسم تو وارد چرخه‌ی درس می‌شود.",
        InlineKeyboardMarkup([[InlineKeyboardButton("✍️ سؤال بعدی", callback_data="eduq:menu"), InlineKeyboardButton("🔙 بازگشت", callback_data="eduq:back")]]))

def _admin_card(row, author, status_line):
    return (f"📝 سؤال جدید برای روباهیو درس | Q{row.id}\n\n"
            f"📚 موضوع: {TOPICS.get(row.topic, (row.topic,))[0]}\n"
            f"👤 طراح: {_author_name(author)} | {row.author_id}\n\n"
            f"❓ {row.question}\n"
            f"✅ درست: {row.correct_opt}\n"
            f"❌ نادرست ۱: {row.wrong1}\n"
            f"❌ نادرست ۲: {row.wrong2}\n\n{status_line}")

async def eduq_admin_button(update, context):
    q = update.callback_query
    if not q or not q.from_user or q.from_user.id not in ADMIN_IDS:
        return await q.answer("⛔ فقط پشتیبان‌ها می‌توانند این سؤال را بررسی کنند.", show_alert=True)
    _, decision, id_s = q.data.split(":"); qid = int(id_s); s = get_session()
    try:
        row = s.query(EduUserQuestion).filter(EduUserQuestion.id == qid).with_for_update().first()
        if not row: return await q.answer("این سؤال پیدا نشد.", show_alert=True)
        if row.status != "pending":
            return await q.answer("این سؤال قبلاً بررسی شده.", show_alert=True)
        author = s.get(User, row.author_id)
        admin_name = q.from_user.first_name or str(q.from_user.id)
        title = TOPICS.get(row.topic, (row.topic,))[0]
        if decision == "ok":
            row.status = "approved"
            if author: author.fox_points = int(author.fox_points or 0) + USER_Q_REWARD
            status_line = f"✅ تأیید شد توسط {admin_name} — {USER_Q_REWARD:,} روب‌پوینت به طراح داده شد."
            author_msg = f"🎉 سؤالت در درس «{title}» تأیید شد و وارد چرخه‌ی سؤال‌ها شد!\n🎁 {USER_Q_REWARD:,} روب‌پوینت به حسابت اضافه شد."
        else:
            row.status = "rejected"
            status_line = f"❌ رد شد توسط {admin_name}."
            author_msg = f"❌ سؤالت در درس «{title}» توسط پشتیبانی تأیید نشد.\n❓ {row.question}"
        row.decided_at = _now(); row.decided_by = q.from_user.id
        s.commit()
        card = _admin_card(row, author, status_line)
        try: refs = json.loads(row.admin_msgs or "[]")
        except Exception: refs = []
        author_id = row.author_id
    finally: s.close()
    await q.answer("انجام شد.")
    # کارتِ همه‌ی پشتیبان‌ها به‌روز می‌شود تا دو نفر یک سؤال را دوباره بررسی نکنند.
    for chat_id, message_id in refs:
        try: await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=card)
        except Exception as e:
            if "not modified" not in str(e).lower(): logging.getLogger(__name__).warning("edu question card edit failed: %s", e)
    try: await context.bot.send_message(author_id, author_msg)
    except Exception: pass

async def handle_edu_question_text(update, context):
    """متن‌های مرحله‌ی طرح سؤال. True یعنی پیام مصرف شد."""
    st = context.user_data.get("edu_q")
    if not st or st.get("step") not in _Q_ORDER or not update.message or not update.message.text:
        return False
    ref = st.get("ref")
    if ref and update.effective_chat and update.effective_chat.id != ref[0]:
        return False
    text = " ".join(update.message.text.split())
    if text.startswith("/"): return False
    step = st["step"]; d = st["data"]; lo, hi = _Q_LIMITS[step]

    async def show(t, kb):
        if ref:
            try:
                await context.bot.edit_message_text(chat_id=ref[0], message_id=ref[1], text=t, reply_markup=kb); return
            except Exception as e:
                if "not modified" in str(e).lower(): return
                logging.getLogger(__name__).warning("edu question panel edit failed: %s", e)
        await update.message.reply_text(t, reply_markup=kb)

    if not (lo <= len(text) <= hi):
        await show(_draft_text(st, f"❌ طول متن باید بین {lo} تا {hi} کاراکتر باشد.\n{_Q_PROMPTS[step]}"), _cancel_kb()); return True
    if step != "question" and _norm_opt(text) in {_norm_opt(d[k]) for k in ("correct", "wrong1", "wrong2") if k in d}:
        await show(_draft_text(st, f"❌ گزینه‌ها نباید تکراری باشند.\n{_Q_PROMPTS[step]}"), _cancel_kb()); return True
    d[step] = text
    nxt = _Q_ORDER.index(step) + 1
    if nxt < len(_Q_ORDER):
        st["step"] = _Q_ORDER[nxt]
        await show(_draft_text(st, _Q_PROMPTS[st["step"]]), _cancel_kb())
    else:
        st["step"] = "confirm"
        await show(_draft_text(st, "آیا این سؤال برای پشتیبانی ارسال شود؟"),
                   InlineKeyboardMarkup([[InlineKeyboardButton("✅ ارسال برای پشتیبانی", callback_data="eduq:send")],
                                         [InlineKeyboardButton("❌ لغو", callback_data="eduq:cancel")]]))
    return True
