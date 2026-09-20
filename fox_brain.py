"""
مغز قانون‌محور روباهیو 🦊 — بدون هیچ API و سرویس خارجی، رایگان و کاملاً روی سرور خود ربات.

چهار کار انجام می‌دهد:
  ۱) chat_reply    : گفتگوی شخصیت‌دار (سلام، احوال‌پرسی، جوک، دلداری، ...)
  ۲) guide_answer  : جواب سوال درباره‌ی ربات با جستجو در «راهنما» (امتیازدهی کلمه‌های کلیدی)
  ۳) moderate      : ناظر گروه (فحش/توهین واضح، تبلیغ لینک دعوت/کانال، اسپم تکراری)
  ۴) city_news     : خبر شهر از روی عددهای واقعی (قالب‌های تصادفی)

هیچ وابستگی‌ای به bot.py یا تلگرام ندارد (قابل تست مستقل).

تنظیمات محیطی (همه اختیاری):
  FOX_BRAIN=0                 خاموش کردن کامل
  MOD_EXTRA_WORDS=کلمه1,کلمه2 کلمه‌های اضافه برای حذف (جداشده با ویرگول)
  MOD_WHITELIST_WORDS=...     کلمه‌هایی که نباید حذف بشن (مثلاً اگه گروهتون «عوضی» رو شوخی می‌گه)
"""
import os
import random
import re
import time
from collections import deque

ENABLED = os.getenv('FOX_BRAIN', '1').strip().lower() not in ('0', 'false', 'no', 'off')

# ───────────────────────── نرمال‌سازی متن فارسی ─────────────────────────
_CHAR_MAP = str.maketrans({
    'ي': 'ی', 'ى': 'ی', 'ئ': 'ی', 'ك': 'ک', 'ة': 'ه', 'ۀ': 'ه', 'أ': 'ا', 'إ': 'ا', 'ؤ': 'و', 'آ': 'ا',
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
})
_DIACRITICS = re.compile('[\u064b-\u065f\u0670\u0640]')      # اعراب و کشیده
_INVISIBLE = re.compile('[\u200d\u200e\u200f\u202a-\u202e\u2063\u2064\ufeff]')
_REPEAT = re.compile(r'([^\W\d_])\1{2,}')                       # سلاااام → سلام
_PUNCT = re.compile(r'[^\w\s]|_')


def normalize(text):
    """متن را برای مقایسه یکدست می‌کند: حروف عربی→فارسی، حذف اعراب/نیم‌فاصله/علائم، کوتاه‌کردن کشیده‌ها."""
    t = (text or '').lower().translate(_CHAR_MAP)
    t = _DIACRITICS.sub('', t)
    t = t.replace('\u200c', ' ')
    t = _INVISIBLE.sub('', t)
    t = _REPEAT.sub(r'\1', t)
    t = _PUNCT.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _has_phrase(norm, phrase):
    return f' {phrase} ' in f' {norm} '


class _SafeDict(dict):
    def __missing__(self, key):
        return ''


def _fmt(template, ctx):
    try:
        return template.format_map(_SafeDict(ctx or {}))
    except (ValueError, KeyError, IndexError):
        return template


# ───────────────────────── محدودیت پیام (ضدسیل) ─────────────────────────
_last_call = {}
BRAIN_COOLDOWN = 3


def gate(uid):
    """کولداون ۳ ثانیه‌ای برای هر کاربر؛ چون هزینه‌ای ندارد فقط برای جلوگیری از اسپم است."""
    now = time.time()
    if now - _last_call.get(uid, 0) < BRAIN_COOLDOWN:
        return False
    _last_call[uid] = now
    if len(_last_call) > 5000:
        for k in sorted(_last_call, key=_last_call.get)[:2000]:
            _last_call.pop(k, None)
    return True


# ═════════════════════════ پاسخ‌های دستی (ادمین یاد می‌دهد) ═════════════════════════
_CUSTOM = []      # هر آیتم: {'id','kws':[normalized...],'answer','media_type','file_id'}


def set_custom(entries):
    """entries: لیست dict با id, keywords (لیست)، answer و (اختیاری) media_type + file_id.
    bot.py موقع شروع و بعد از هر تغییر صدا می‌زند. آیتم مدیا ممکنه answer (کپشن) نداشته باشه."""
    global _CUSTOM
    _CUSTOM = []
    for e in entries:
        kws = [normalize(k) for k in e.get('keywords', [])]
        kws = [k for k in kws if k]
        is_media = bool(e.get('file_id') and e.get('media_type'))
        if kws and (e.get('answer') or is_media):
            _CUSTOM.append({'id': e.get('id'), 'kws': kws, 'answer': e.get('answer') or '',
                            'media_type': e.get('media_type') if is_media else None,
                            'file_id': e.get('file_id') if is_media else None})


def custom_count():
    return len(_CUSTOM)


def format_answer(template, ctx=None):
    """جایگزینی {name} {level} {fox} تو کپشن/جواب."""
    return _fmt(template, ctx)


def _lookup(text, media, exact=False):
    """media=False → فقط جواب‌های متنی؛ media=True → فقط جواب‌های مدیا (آهنگ/ویدیو/گیف/استیکر/...).
    exact=True → کل پیام باید دقیقاً خودِ کلید باشه (برای واکنش مستقیم تو گروه بدون صدا زدن روباه)."""
    norm = normalize(text)
    if not norm or not _CUSTOM:
        return None
    padded = f' {norm} '
    best = []; best_len = 0
    for e in _CUSTOM:
        if bool(e.get('file_id')) != media:
            continue
        for kw in e['kws']:
            if exact:
                hit = (kw == norm)
            else:
                hit = (f' {kw} ' in padded) if len(kw) < 3 else (kw in norm)
            if not hit:
                continue
            if len(kw) > best_len:
                best, best_len = [e], len(kw)
            elif len(kw) == best_len and e not in best:
                best.append(e)          # چند جواب برای یک کلید → یکی به‌صورت تصادفی (مثلاً چند جوک / چند آهنگ)
    return random.choice(best) if best else None


def custom_lookup(text):
    """اگه یکی از کلیدهای دستیِ «متنی» تو پیام بود، آیتم اختصاصی‌ترین کلید (طولانی‌ترین) را برمی‌گرداند؛ اگه چند آیتم هم‌اندازه بودن یکی تصادفی."""
    return _lookup(text, media=False)


def media_lookup(text, exact=False):
    """مثل custom_lookup ولی برای آیتم‌های مدیا. پیام‌های نگران‌کننده هیچ‌وقت مدیا نمی‌گیرن (جواب همدلانه‌ی متنی اولویت داره)."""
    e = _lookup(text, media=True, exact=exact)
    if e and 'distress' in _match_intents(normalize(text)):
        return None
    return e


# ═════════════════════════ ۱) گفتگوی شخصیت‌دار ═════════════════════════
_JOKES = [
    "چرا روباه تو قایم‌موشک همیشه می‌بازه؟ چون هر بار دمش لو می‌ده! 🦊😂",
    "معلم پرسید: ۲ + ۲ چند می‌شه؟ روباهه گفت: اول بگین جواب به نفع کیه، بعد بهتون می‌گم 😏",
    "روباهه رفت بانک گفت: سود می‌خوام! کارمند گفت: سود بعد از ۱۲ ساعت میاد. گفت: پس تا اون موقع من همین‌جا می‌خوابم 😴",
    "دو تا روباه تو کازینو بودن. یکی گفت: شانس آوردم! اون یکی گفت: شانس چیه؟ من دمم رو بستم به میز، ۷۷۷ اومد 🎰",
    "به روباهه گفتن: چرا اینقدر باهوشی؟ گفت: نیستم؛ فقط همیشه یه راه فرار پشت لونه‌م دارم 🏃‍♂️",
    "خرگوشه به روباهه گفت: قول می‌دی منو نخوری؟ روباهه گفت: قول می‌دم... ولی فقط تا وقتی گرسنه نشدم 🐇😅",
    "روباهه رفت شکار، دست خالی برگشت. گفتن: چی شد؟ گفت: شکار فرار کرد؛ من که نمی‌تونستم بهش بگم وایسا 🏹",
    "روباهه به دوستش گفت: من هر روز صبح ورزش می‌کنم. گفت: چی کار می‌کنی؟ گفت: از تخت می‌پرم پایین... بعد برمی‌گردم توش 🛏",
]

_FACTS = [
    "مردمک چشم روباه قرمز مثل گربه شکاف عمودیه و تو نور کم عالی می‌بینه 👀",
    "گوش‌های بزرگ روباه فنک (روباه صحرا) هم برای شنیدن طعمه‌ست و هم به خنک شدن بدنش تو گرما کمک می‌کنه 🏜",
    "پوست روباه قطبی با تغییر فصل رنگ عوض می‌کنه؛ تو زمستون سفید می‌شه ❄️",
    "به بچه‌ی روباه «کیت» (kit) می‌گن 🍼",
    "روباه‌ها همه‌چیزخوارن؛ از موش و پرنده و حشره گرفته تا میوه و توت 🍇",
    "روباه قرمز یکی از پراکنده‌ترین گوشت‌خوارهای دنیاست؛ تقریباً تو همه‌ی قاره‌های نیمکره‌ی شمالی پیداش می‌شه 🌍",
]

# (اسم، عبارت‌ها، جواب‌ها) — عبارت‌ها بعد از normalize مقایسه می‌شوند؛ جواب‌ها می‌توانند {name} {level} {fox} داشته باشند.
_INTENTS = [
    ('distress', ["میخوام بمیرم", "می خوام بمیرم", "خودکشی", "خودکشی کنم", "دیگه نمیخوام زندگی کنم", "دلم میخواد بمیرم", "خودمو بکشم", "خودم رو بکشم"], [
        "🫂 {name}، خیلی دلم می‌خواد کنارت باشم. این حرفی که زدی مهمه و تنها نیستی.\n"
        "لطفاً همین الان با یه آدم مورد اعتمادت (دوست، فامیل یا یه مشاور) حرف بزن و بهش بگو چه حالی داری. "
        "اگه حس می‌کنی ممکنه به خودت آسیب بزنی یا در خطری، فوراً به اورژانس (۱۱۵) یا نزدیک‌ترین آدم زنگ بزن. "
        "من یه ربات بازیم و جای کمک واقعی رو نمی‌گیرم، ولی برات اینجام که حرف بزنی 💛"]),
    ('sad', ["ناراحتم", "غمگینم", "دلم گرفته", "افسرده ام", "افسردم", "حالم بده", "حالم خوب نیست", "تنهام", "دلم تنگ شده", "گریه ام گرفته"], [
        "🫂 ای وای {name}! بیا بغلم... روباه‌ها بغل‌های گرمی دارن. اگه دوست داری بگو چی شده؛ گوش می‌دم 🦊",
        "💛 غصه نخور {name}؛ روزای بد هم تموم می‌شن. یه نفس عمیق بکش، یه چیز خوب بخور، بعد اگه خواستی یه دست بازی کنیم تا حالت عوض شه.",
        "🦊 من اینجام {name}. یادت باشه با یه دوست یا آدم مورد اعتماد حرف زدن واقعاً کمک می‌کنه؛ ولی تا اون موقع من همراهتم."]),
    ('greet_morning', ["صبح بخیر", "صبحت بخیر", "صبح شما بخیر"], [
        "صبح تو هم بخیر {name}! ☀️ امروز چند تا روب روب می‌زنیم؟ 🦊", "صبح بخیر! ☀️ قهوه‌ت رو بخور، بعد بریم شکار!"]),
    ('greet_night', ["شب بخیر", "شبت بخیر", "شب شما بخیر", "برم بخوابم", "میرم بخوابم", "خوابم میاد"], [
        "شب بخیر {name}! 🌙 خواب‌های قشنگ ببینی؛ من نگهبان لونه می‌شم 🦊", "🌙 شبت بخیر! فردا دوباره می‌بینمت؛ روب روبت رو یادت نره!"]),
    ('greet', ["سلام", "سلام علیکم", "درود", "های", "هلو", "hi", "hello", "hey", "سلمممم", "وقت بخیر", "عصر بخیر", "ظهر بخیر"], [
        "سلام {name}! 🦊 چه خبر؟", "به به! سلام {name} عزیز 😄 امروز چیکار کنیم؟",
        "سلاام! روباهیو اینجاست 🦊 بگو ببینم چی می‌خوای.", "هی {name}! خوش اومدی 🦊✨"]),
    ('how_are_you', ["چطوری", "چطور هستی", "حالت چطوره", "حالت چطور", "خوبی", "چه خبر", "چخبر", "احوالت", "حال و احوال", "چه طوری", "خوبین", "چطورین"], [
        "من عالی‌ام! 🦊 چون دمم پفکیه و لونه‌م گرمه. تو چطوری {name}؟", "خوبم خوب! فقط یکم گرسنه‌ام 😋 تو چطوری؟",
        "همیشه سرحال! 😄 تو چه خبر؟", "عالیم {name}! امروز حس می‌کنم شانس اسلاتم زیاده 🎰"]),
    ('thanks', ["مرسی", "ممنون", "تشکر", "مچکر", "مچکرم", "دمت گرم", "دستت درد نکنه", "thanks", "thx", "سپاس", "ممنونم"], [
        "قابلی نداشت {name}! 🦊", "خواهش می‌کنم 😊", "وظیفه‌ست! 🫡 هر وقت خواستی بگو", "دمت گرم که هستی 💛"]),
    ('bye', ["خداحافظ", "بای", "فعلا", "خدانگهدار", "بدرود", "bye", "برم دیگه", "تا بعد", "میرم"], [
        "خداحافظ {name}! 🦊 زود برگرد، لونه بدون تو خالیه", "فعلاً! 👋 روب روبت رو فراموش نکنی", "برو به سلامت! من همین‌جا وایمیستم 🦊"]),
    ('who_are_you', ["تو کی هستی", "تو کی", "کی هستی", "کی هستین", "اسمت چیه", "اسمت چیست", "چی هستی", "خودتو معرفی کن", "معرفی کن"], [
        "من «روباهیو»ام؛ روباه شیطون و مهربون این ربات بازی 🦊 با من می‌تونی روب‌پوینت جمع کنی، شکار بری، بازی کنی و لول بگیری!"]),
    ('what_can_you_do', ["چیکار میتونی", "چه کار میتونی", "چه کارایی بلدی", "چه کاری بلدی", "چیکارا بلدی", "چی بلدی", "کمک", "کمکم کن", "راهنمایی", "کمک میخوام", "کمک می خوام", "چی کار کنم", "راهنما"], [
        "من می‌تونم باهات گپ بزنم، جوک بگم، و درباره‌ی بخش‌های ربات راهنماییت کنم 🦊\n"
        "مثلاً بنویس «راهنما بانک» یا «راهنما کازینو» یا فقط «راهنما» تا لیست رو ببینی."]),
    ('joke', ["جوک", "جوک بگو", "یه جوک", "بخندون", "بخندونم", "چیز خنده دار", "لطیفه"], _JOKES),
    ('fact', ["فکت", "یه چیز جالب", "چیز جالب", "اطلاعات جالب", "یه اطلاعات", "درباره روباه", "درباره ی روباه", "روباه ها چی", "روباه چی میخوره"], _FACTS),
    ('bored', ["حوصلم سر رفته", "حوصله ندارم", "بیکارم", "کسلم", "خسته شدم", "حوصلم سر رفت", "کسل شدم", "بی حوصله ام", "بیحوصله ام"], [
        "حوصله‌ت سر رفته {name}؟ 🥱 برو یه شکار بزن یا یه میز تاس بساز؛ حال می‌کنی! 🎲",
        "بیا سرگرمت کنم! 😄 «راهنما بازی» بنویس ببین چه بازی‌هایی داریم، یا «جوک» بگو تا بخندونمت.",
        "یه دست اسلات چطوره؟ 🎰 (اگه لول ۵ باشی)"]),
    ('love', ["دوستت دارم", "دوست دارم", "عاشقتم", "عاشقتم روباه", "love you", "قربونت", "فدات", "عشقی"], [
        "🥺 وای شرمنده شدم {name}! منم دوستت دارم... مخصوصاً وقتی روب روب می‌زنی 🦊💛", "دل روباه رو آب کردی! 😳💛 ولی من فقط یه ربات بازیم ها!"]),
    ('insult_bot', ["احمق", "خنگ", "گاو", "الاغ", "بی مصرف", "بیمصرف", "مزخرف", "مزخرفی", "بدرد نخور", "به درد نخور", "خفه شو", "بی عرضه", "بیعرضه"], [
        "اوه اوه! 🥺 روباه هم دل داره‌ها! ولی باشه، بخشیدمت؛ بیا یه بازی کنیم صلح کنیم 🦊",
        "🦊 من که کاری نکردم! دمم رو بردم لونه قهر کنم... ولی زود آشتی می‌کنم 😅",
        "خب خب، منم بلدم بازی کنم و برنده بشم! 😏 ولی مؤدب باشیم {name}."]),
    ('points_request', ["روب پوینت بده", "پوینت بده", "پول بده", "سکه بده", "امتیاز بده", "به من روب پوینت بده", "یه مقدار پوینت بده", "بهم پوینت بده", "بهم پول بده", "پوینت میخوام", "پوینت می خوام"], [
        "😅 من بانک نیستم {name}! ولی می‌تونی با «روب روب» و «شکار» پوینت جمع کنی؛ ضمناً «کد هدیه» هم چک کن ببین کدی هست؟ 🎁",
        "🦊 روب‌پوینت رو فقط با زحمت می‌شه گرفت! «روب روب» بزن، شکار برو، یا از کدهای هدیه‌ی کانال استفاده کن 🎁"]),
    ('hungry', ["گرسنمه", "گشنمه", "گرسنه ام", "گشنه ام", "گرسنه م", "گشنه م"], [
        "🍗 منم گرسنه‌ام {name}! ولی اول بنویس «روباه» ببین روباه خودت گرسنه‌ست یا نه 🦊",
        "😋 یه چیز خوشمزه بخور! و روباهت رو هم فراموش نکن؛ اونم دلش غذا می‌خواد."]),
    ('who_am_i', ["من کی هستم", "من کیم", "من کی ام", "اسم من چیه", "اسمم چیه", "لول من", "سطح من", "لول من چنده", "سطح من چنده", "من چه لولی"], [
        "تو «{name}» هستی، لول {level} 🎖 و روباهت اسمش «{fox}»ه 🦊"]),
    ('laugh', ["ههه", "هه", "ها ها", "لول", "lol", "خخخ", "خخ", "جیگر", "بخند"], ["😄", "😂 خنده‌ت قشنگه!", "🦊😆"]),
    ('ok', ["باشه", "اوکی", "ok", "okay", "آره", "اره", "بله", "چشم", "حله", "خب"], ["👌", "اوکی! 🦊", "باشه {name}! 😊"]),
    ('no', ["نه", "نمیخوام", "نخیر", "خیر"], ["باشه، هر جور راحتی 😊", "حله! هر وقت نظرت عوض شد بگو 🦊"]),
]

_INTENT_INDEX = [(name, [normalize(p) for p in phrases], replies) for name, phrases, replies in _INTENTS]

_FALLBACKS = [
    "🦊 اینو نفهمیدم {name}! ولی اگه درباره‌ی ربات سوال داری بنویس «راهنما <سوالت>» تا کمکت کنم.",
    "😅 هنوز خیلی چیزا رو بلد نیستم! امتحان کن «راهنما» یا «جوک» یا «فکت».",
    "🦊 گیج شدم! بنویس «راهنما» تا ببینی درباره‌ی چی می‌تونم کمکت کنم.",
]


_WEAK_INTENTS = {'ok', 'no', 'laugh'}
_QUESTION_WORDS = [normalize(w) for w in ('چیه', 'چیست', 'چی هست', 'چطور', 'چطوری', 'چجوری', 'چگونه', 'چه جوری', 'کجاست', 'کجا', 'چند', 'چرا', 'چه', 'کی', 'چقدر', 'یعنی چی', 'چیکار', 'چی کار')]


def _match_intents(norm):
    """همه‌ی intent های مچ‌شده را با طول بلندترین عبارت برمی‌گرداند."""
    found = {}
    for name, phrases, _ in _INTENT_INDEX:
        best = 0
        for p in phrases:
            if p and _has_phrase(norm, p):
                best = max(best, len(p))
        if best:
            found[name] = best
    return found


def chat_reply(text, ctx=None, guide_threshold=4):
    """جواب گفتگوی عمومی. همیشه یک متن برمی‌گرداند."""
    ctx = ctx or {}
    norm = normalize(text)
    if not norm:
        return random.choice(_FALLBACKS).format_map(_SafeDict(ctx))
    n_tokens = len(norm.split())
    found = _match_intents(norm)
    # ۰) پیام‌های نگران‌کننده همیشه اولویت دارن، هر قدر هم طولانی باشن
    if 'distress' in found:
        return _fmt(random.choice(_reply_of('distress')), ctx)
    # ۰٫۵) پاسخ‌هایی که ادمین دستی یاد داده (بر بقیه اولویت دارن، جز پیام‌های نگران‌کننده)
    c = custom_lookup(text)
    if c:
        return _fmt(c['answer'], ctx)
    # ۱) مؤدب نبودن با روباه
    verdict = moderate_text(text)
    if verdict and verdict[0] == 'insult':
        return _fmt("🦊 بیا مؤدبانه حرف بزنیم {name}؛ من با احترام جواب می‌دم!", ctx)
    # ۲) intent های کوتاه (intent های ضعیف مثل «باشه/نه/هه» فقط وقتی پیام خیلی کوتاهه)
    if n_tokens <= 8:
        found = {k: v for k, v in found.items() if not (k in _WEAK_INTENTS and n_tokens > 2)}
        if found:
            greet = 'greet' in found
            others = {k: v for k, v in found.items() if k != 'greet'}
            if others:
                name = max(others, key=others.get)
                reply = _fmt(random.choice(_reply_of(name)), ctx)
                if greet and name in ('how_are_you', 'who_are_you'):
                    reply = _fmt(random.choice(['سلام {name}! ', 'هی {name}! ']), ctx) + reply
                return reply
            return _fmt(random.choice(_reply_of('greet')), ctx)
    # ۳) اگه سوال درباره‌ی ربات بود از راهنما جواب بده (برای جمله‌ی پرسشی یک کلمه‌ی کلیدی هم کافیه)
    g = guide_lookup(text)
    is_question = ('؟' in text or '?' in text or any(_has_phrase(norm, q) for q in _QUESTION_WORDS))
    if g and g['score'] >= (2 if is_question else guide_threshold):
        return g['answer']
    # ۴) نمی‌فهمم
    return _fmt(random.choice(_FALLBACKS), ctx)


def _reply_of(intent):
    for name, _, replies in _INTENT_INDEX:
        if name == intent:
            return replies
    return _FALLBACKS


# ═════════════════════════ ۲) راهنمای هوشمند ═════════════════════════
_GUIDE = []          # هر آیتم: {'title','answer','kws':[normalized...]}


def set_guide(entries):
    """entries: لیست dict با title, answer, keywords (لیست کلمه/عبارت). bot.py موقع شروع صدا می‌زند."""
    global _GUIDE
    _GUIDE = []
    for e in entries:
        kws = []
        for k in e.get('keywords', []):
            nk = normalize(k)
            if nk:
                kws.append(nk)
        _GUIDE.append({'title': e['title'], 'answer': e['answer'], 'kws': kws})


def guide_titles():
    return [g['title'] for g in _GUIDE]


def guide_lookup(text):
    """بهترین آیتم راهنما را برای یک سوال پیدا می‌کند: {'title','answer','score','others'} یا None."""
    norm = normalize(text)
    if not norm or not _GUIDE:
        return None
    padded = f' {norm} '
    scored = []
    for g in _GUIDE:
        score = 0
        for kw in g['kws']:
            if len(kw) < 3:
                hit = f' {kw} ' in padded
            else:
                hit = kw in norm            # زیررشته: «بانکی/بانکها» هم مچ شود
            if hit:
                score += 3 if ' ' in kw else 2
        if score:
            scored.append((score, g))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    others = [g['title'] for s, g in scored[1:3] if s >= max(2, best_score * 0.6)]
    return {'title': best['title'], 'answer': f"{best['title']}\n{best['answer']}", 'score': best_score, 'others': others}


def guide_answer(question):
    """جواب «راهنما <سوال>». اگه سوال خالی بود یا چیزی پیدا نشد، لیست موضوع‌ها را می‌دهد."""
    c = custom_lookup(question)
    if c:
        return _fmt(c['answer'], {})
    norm = normalize(question)
    titles = guide_titles()
    listing = "📚 می‌تونی درباره‌ی این‌ها بپرسی:\n" + "\n".join(f"• {t}" for t in titles) if titles else ""
    if not norm or norm in ('راهنما', 'لیست', 'فهرست', 'همه', 'چی', 'کمک'):
        return listing or "راهنما هنوز آماده نیست 🦊"
    g = guide_lookup(question)
    if not g:
        return "🦊 جوابش رو تو راهنما پیدا نکردم. \n\n" + listing
    text = g['answer']
    if g['others']:
        text += "\n\n🔎 شاید این‌ها هم به دردت بخوره: " + "، ".join(g['others'])
    return text


# ═════════════════════════ ۳) ناظر گروه ═════════════════════════
# لیست کلمه‌های «واضحاً توهین‌آمیز». مقایسه‌ی توکنی است (نه زیررشته) تا کلمه‌های بی‌گناه گرفته نشوند.
_BAD_WORDS = [
    'کیر', 'کیری', 'کص', 'کسکش', 'کسشر', 'کسخل', 'کوس', 'کون', 'کونی', 'کونده', 'جنده', 'جاکش', 'گاییدم', 'گایید', 'گاییدن',
    'بگام', 'بگاییدم', 'بکیرم', 'کیرم', 'کصکش', 'مادرجنده', 'ننهجنده', 'قحبه', 'حرومزاده', 'حرامزاده', 'پدرسگ',
    'عوضی', 'بیشرف', 'بیناموس', 'دیوث', 'فاحشه', 'خارکسه', 'خارکصه', 'کسکشا',
    'fuck', 'fucker', 'fucking', 'motherfucker', 'bitch', 'asshole', 'cunt', 'koskesh', 'kosnanat', 'jende', 'jendeh', 'kir', 'kiri', 'kooni',
]
# عبارت‌های دو کلمه‌ای (بعد از normalize)
_BAD_PHRASES = [
    r'\bکس (ننت|ننه|مادرت|خواهرت|عمت|خالت|ناموست)\b', r'\b(مادر|ننه) (جنده|قحبه)\b', r'\bپدر سگ\b', r'\bتخم (سگ|حرام)\b',
    r'\bبی (شرف|ناموس)\b', r'\b(حرام|حروم) زاده\b', r'\bخار (کسه|کصه|کسده)\b', r'\bکس (کش|شر|خل)\b',
    r'\bmadar (jende|jendeh)\b', r'\bkos (nane|nanat|madaret)\b',
]
_SUFFIXES = {'', 'م', 'ت', 'ش', 'ی', 'ه', 'ها', 'ا', 'ای', 'های', 'تو', 'مو', 'شو', 'تون', 'مون', 'شون', 'یه', 'اش', 'ات', 'ام', 'ان', 'ن', 'و', 'رو', 'ی'}
_SAFE_TOKENS = {'کیرمانی', 'کیرکوک', 'کیران', 'کیرا', 'کیرن', 'کونیا'}


def _split_words(env_name):
    raw = os.getenv(env_name, '')
    return [normalize(w) for w in re.split(r'[,،\n]', raw) if normalize(w)]


_EXTRA_WORDS = _split_words('MOD_EXTRA_WORDS')
_WHITELIST = set(_split_words('MOD_WHITELIST_WORDS')) | _SAFE_TOKENS
_BAD_SET = {normalize(w) for w in _BAD_WORDS} | set(_EXTRA_WORDS)
_BAD_SET -= _WHITELIST
_BAD_RE = [re.compile(p) for p in _BAD_PHRASES]


def _tokens_for_profanity(norm):
    """توکن‌ها؛ حروف تک‌کاراکتری پشت‌سرهم («ک ی ر» یا «ک.ی.ر») به هم چسبانده می‌شوند."""
    raw = norm.split()
    out = []; run = []
    for tok in raw:
        if len(tok) == 1 and tok.isalpha():
            run.append(tok)
            continue
        if run:
            out.append(''.join(run)) if len(run) >= 3 else out.extend(run)
            run = []
        out.append(tok)
    if run:
        out.append(''.join(run)) if len(run) >= 3 else out.extend(run)
    return out


def _is_bad_token(tok):
    if tok in _WHITELIST:
        return False
    if tok in _BAD_SET:
        return True
    if len(tok) < 3:
        return False
    for w in _BAD_SET:
        if len(w) >= 3 and tok.startswith(w) and (tok[len(w):] in _SUFFIXES):
            return True
    return False


def has_profanity(text):
    norm = normalize(text)
    if not norm:
        return False
    if any(r.search(norm) for r in _BAD_RE):
        return True
    return any(_is_bad_token(t) for t in _tokens_for_profanity(norm))


_INVITE_LINK = re.compile(r'(?:t\.me|telegram\.me|telegram\.dog)/(?:\+|joinchat/)', re.I)
_TG_LINK = re.compile(r'(?:t\.me|telegram\.me|telegram\.dog)/[a-z0-9_]{4,}', re.I)
_AT_USER = re.compile(r'@[a-z0-9_]{4,}', re.I)
_PHONE = re.compile(r'(?:\+98|0098|0)?9\d{9}')
_PROMO_WORDS = ['عضو شو', 'عضو بشید', 'عضو شید', 'جوین', 'join', 'کانال', 'چنل', 'فروش', 'تخفیف', 'ارزان', 'ممبر', 'فالوور', 'فالو', 'تبلیغ',
                'کسب درآمد', 'درآمد دلاری', 'سرمایه گذاری', 'ارز دیجیتال', 'خرید', 'سفارش', 'واتساپ', 'هدیه رایگان', 'قرعه کشی', 'بدون سرمایه']
_PROMO_NORM = [normalize(w) for w in _PROMO_WORDS]


def _looks_promo(norm):
    return any(p in norm for p in _PROMO_NORM)


def moderate_text(text):
    """بررسی بدون حالت (stateless). خروجی: ('insult'|'ad'|'spam', دلیل) یا None."""
    if not text or len(text.strip()) < 3:
        return None
    if has_profanity(text):
        return 'insult', 'profanity'
    low = text.lower()
    norm = normalize(text)
    if _INVITE_LINK.search(low):
        return 'ad', 'invite-link'
    if _TG_LINK.search(low) and _looks_promo(norm):
        return 'ad', 'tg-link+promo'
    if _AT_USER.search(low) and any(w in norm for w in ('عضو شو', 'عضو بشید', 'عضو شید', 'جوین', 'join', 'فروش', 'تخفیف', 'فالو')):
        return 'ad', 'mention+promo'
    if _PHONE.search(norm.replace(' ', '')) and any(w in norm for w in ('فروش', 'خرید', 'سفارش', 'واتساپ', 'تخفیف')):
        return 'ad', 'phone+sale'
    if len(_AT_USER.findall(low)) >= 5:
        return 'spam', 'mass-mention'
    return None


_recent = {}    # (chat_id, user_id) → deque[(متن نرمال، زمان)]


def moderate(text, chat_id=0, user_id=0):
    """بررسی کامل با حالت: قوانین بالا + تشخیص پیام تکراری پشت‌سرهم (اسپم)."""
    verdict = moderate_text(text)
    if verdict:
        return verdict
    norm = normalize(text)
    if len(norm) >= 6:
        now = time.time()
        dq = _recent.setdefault((chat_id, user_id), deque(maxlen=8))
        dq.append((norm, now))
        if sum(1 for t, ts in dq if t == norm and now - ts < 60) >= 4:
            dq.clear()
            return 'spam', 'repeat'
        if len(_recent) > 5000:
            for k in list(_recent)[:2000]:
                _recent.pop(k, None)
    return None


# ═════════════════════════ ۴) اخبار شهر ═════════════════════════
_NEWS_OPEN = [
    "📢 آهای اهالی «{title}»! خبرنگار روباهیو از آخرین اوضاع شهر گزارش می‌ده:",
    "🗞 تازه‌ترین خبرهای شهر «{title}» رسید:",
    "🦊 خبرنگار روباهیو از میدان شهر «{title}» گزارش می‌ده:",
    "📰 ویژه‌نامه‌ی امروز شهر «{title}»:",
]
_NEWS_CLOSE = [
    "به امید شهری بزرگ‌تر! 🏙", "دست‌مریزاد به همه‌ی اهالی! 👏", "ادامه بدید، روباه‌ها هوای شهر رو دارن 🦊", "این خبر رو به بچه‌ها برسونید! 📣",
]
_LEVELUP_TEXTS = [
    "📰 خبر فوری! شهر «{title}» با افتخار به سطح {level} رسید! خیابون‌ها رو چراغانی کنید، روباه‌ها جشن گرفتن 🎉🦊",
    "🎊 خبر داغ: «{title}» یه پله بالاتر رفت و شد سطح {level}! اهالی دست‌مریزاد 👏",
    "🏙 شهر «{title}» رشد کرد! سطح {level} رسماً افتتاح شد؛ نوبت تلاش برای سطح بعدیه 🚀",
]


def levelup_news(title, level):
    return random.choice(_LEVELUP_TEXTS).format(title=title, level=level)


def city_news(facts):
    """facts: title, level, max_level, claims, rescued, hunts, treasury, mayor, donors[(name,total)], need{}|None."""
    f = facts
    lines = [random.choice(_NEWS_OPEN).format(title=f['title']), '']
    lines.append(f"🏙 شهر الان سطح {f['level']} از {f.get('max_level', 10)} رو داره.")
    stat_lines = [
        f"🐾 تا امروز {f['claims']:,} بار روب روب زده شده.",
        f"🦊 {f['rescued']:,} روباه زخمی نجات پیدا کرده.",
        f"⚔️ اهالی تا حالا {f['hunts']:,} شکار انجام دادن.",
        f"🏦 خزانه‌ی شهر {f['treasury']:,} روب‌پوینت موجودی داره.",
    ]
    random.shuffle(stat_lines)
    lines += stat_lines[:3]
    if f.get('donors'):
        name, total = f['donors'][0]
        lines.append(random.choice([
            f"💰 قهرمان دونیت: {name} با {total:,} روب‌پوینت! 👑",
            f"👑 بزرگ‌ترین کمک‌کننده به خزانه {name} بوده ({total:,} روب‌پوینت).",
        ]))
    if f.get('mayor'):
        lines.append(f"🗳 رهبر شهر: {f['mayor']}")
    need = f.get('need')
    if need is None:
        lines.append("🌟 شهر به بالاترین سطح رسیده؛ افسانه‌ست!")
    else:
        left = {k: v for k, v in need.items() if v > 0}
        if not left:
            lines.append("✅ همه‌ی شرط‌های ارتقا کامله؛ به‌زودی سطح بعد!")
        else:
            k = random.choice(list(left))
            lines.append(f"📈 برای رسیدن به سطح بعد هنوز {left[k]:,} تا «{k}» لازمه.")
    lines += ['', random.choice(_NEWS_CLOSE)]
    return '\n'.join(lines)


# ═════════════════════════ API اصلی برای bot.py ═════════════════════════
def reply(mode, text, ctx=None):
    """mode: 'guide' یا 'chat'."""
    if mode == 'guide':
        return guide_answer(text)
    return chat_reply(text, ctx)
