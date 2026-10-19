# -*- coding: utf-8 -*-
"""پت‌های روبی: هر کاربر فقط یک پت داره.
ترتیب: همستر (رایگان) ← گربه ← خرگوش ← سگ پامرانین. خرید پت بعدی، جایگزین پت فعلی می‌شه.
غذا و نوازش سیری/حال رو عوض می‌کنن، تجربه لول می‌ده. عکس‌ها (pet_<key>.png) توی ریپو کنار همین فایل‌ان."""
import json
import math
import os
import random
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PETS = {
    'hamster': {'emoji': '🐹', 'name': 'همستر',   'price': 0,          'image': 'pet_hamster.png',
                'about': 'کوچولوی بامزه‌ی روبی؛ پت اولته و رایگانه!'},
    'cat':     {'emoji': '🐱', 'name': 'گربه',    'price': 300_000,  'image': 'pet_cat.png',
                'about': 'گربه‌ی نارنجی و شیطون که همه‌جا دنبالته.'},
    'rabbit':  {'emoji': '🐰', 'name': 'خرگوش',   'price': 700_000,  'image': 'pet_rabbit.png',
                'about': 'خرگوش سفید و گوش‌دراز که عاشق هویجه.'},
    'dog':     {'emoji': '🐶', 'name': 'سگ پامرانین', 'price': 1_200_000, 'image': 'pet_dog.png',
                'about': 'سگ پامرانین پرپشمِ بامزه؛ بهترین رفیق روباه!'},
}
PET_ORDER = list(PETS.keys())

MAX_PET_LEVEL = 30
SAT_DECAY_PER_H = 3.0      # هر ۲۰ دقیقه ۱٪ سیری کم می‌شود
MOOD_DECAY_PER_H = 6.0    # هر ۱۰ دقیقه ۱٪ حال کم می‌شود
PLAY_COOLDOWN = 20 * 60    # نوازش هر ۲۰ دقیقه
# تنظیمات اقتصادی/زمانی قابلیت‌های پت (تغییر از همین‌جا)
PET_FEED_XP = {'hamster': 1.0, 'cat': 1.5, 'rabbit': 2.0, 'dog': 2.5}
PET_FEED_MOOD = 3
PET_FEED_COOLDOWN = {'hamster': 50*60, 'cat': 40*60, 'rabbit': 30*60, 'dog': 20*60}
PET_FEED_PRICE = {'hamster': 5_000, 'cat': 10_000, 'rabbit': 15_000, 'dog': 25_000}
PET_DAILY_POINTS_MIN = 500
PET_DAILY_POINTS_MAX = 2_000
PET_PLAY_XP = 2
PET_REMINDER_THRESHOLD = 30
PET_REMINDER_COOLDOWN = 4 * 3600
PET_DAILY_POINTS_BASE = 1_000
PET_DAILY_XP_BASE = 5
PET_DAILY_STREAK_BONUS_POINTS = 1_000
PET_DAILY_STREAK_BONUS_XP = 1
PET_DAILY_STREAK_MAX = 7
PET_TAP_MOOD = 2
PET_TAP_DAILY_LIMIT = 5
PET_TAP_XP = 0
PET_BATH_COOLDOWN = 12 * 3600  # پت هر ۱۲ ساعت یک‌بار باید حمام کند
PET_BATH_MOOD = 3
PET_SLEEP_START_HOUR = 23
PET_SLEEP_END_HOUR = 7
FAVORITE_FOODS = {'hamster': 'sunflower', 'cat': 'milk', 'rabbit': 'carrot', 'dog': 'meat'}
FOODS = {
    'sunflower': {'emoji': '🌻', 'name': 'تخمه آفتاب‌گردان', 'sat': 15},
    'milk': {'emoji': '🥛', 'name': 'شیر', 'sat': 15},
    'carrot': {'emoji': '🥕', 'name': 'هویج', 'sat': 15},
    'meat': {'emoji': '🥩', 'name': 'گوشت', 'sat': 15},
}

PERSONALITY = {
    'hamster': {'title': 'شیطون و پرخور', 'msg': {
        'greet':   ["هی {u}! 🐹 امروز چه خبر؟", "{n} اینجاست، آماده‌ی ماجراجویی!"],
        'hungry':  ["شکمم داره قارقار می‌کنه! 🥺 یه چیزی بده بخورم", "گشنمه گشنمه گشنمه!"],
        'sad':     ["کسی نیست با من بازی کنه... 😢", "دلم گرفته، یکم نازم کن"],
        'happy':   ["من خوشحال‌ترین همستر دنیام! 🥰", "بیا یه دور بدو بدو کنیم!"],
        'fed':     ["نوش جان! گونه‌هام پر شد 😋", "آخیش، دمت گرم!"],
        'played':  ["قلقلکم میاد هی‌هی‌هی 😆", "بازم! بازم!"],
    }},
    'cat': {'title': 'مغرور و ناز', 'msg': {
        'greet':   ["میو~ 🐱 بالاخره اومدی {u}", "{n} تشریف آورد."],
        'hungry':  ["میو! وقت غذاست، من منتظر نمی‌مونم 😾", "یه چیز درست‌حسابی بیار، نه هر چیزی!"],
        'sad':     ["هیچکس منو ناز نمی‌کنه... 😿", "بی‌حوصله‌ام، بغلم کن"],
        'happy':   ["خرخر خرخر... 😻 امروز مهربونم", "می‌تونی نازم کنی... فقط امروز!"],
        'fed':     ["بد نبود. می‌تونی تکرار کنی 😼", "میو~ قابل قبول بود"],
        'played':  ["خرخر... ادامه بده 😽", "یه دقیقه دیگه... فقط یه دقیقه"],
    }},
    'rabbit': {'title': 'خجالتی و مهربون', 'msg': {
        'greet':   ["سلام {u}... 🐰 خوشحالم دیدمت", "{n} یواش اومد کنارت~"],
        'hungry':  ["ببخشید... یه هویج دارید؟ 🥕", "شکمم یکم خالیه، اگه زحمتی نیست..."],
        'sad':     ["یکم غمگینم... کنارم میشینی؟ 🥺", "حس می‌کنم تنهام"],
        'happy':   ["دلم گرمه، ممنونم که هستی 🥰", "می‌خوام بپرم از خوشحالی!"],
        'fed':     ["اوم‌اوم، خیلی خوشمزه بود، مرسی 🥕", "ممنونم! دلم قرص شد"],
        'played':  ["هی... خجالت می‌کشم 🙈 ولی خوشم اومد", "گوشام داغ شد 🥰"],
    }},
    'dog': {'title': 'وفادار و پرانرژی', 'msg': {
        'greet':   ["هاپ هاپ! {u}! 🐶 دلم برات تنگ شده بود!", "{n} دمش رو تکون می‌ده!"],
        'hungry':  ["هاپ! شکمم خالیه رفیق! 🍖", "بوی غذا میاد؟ هاپ هاپ!"],
        'sad':     ["بدون بازی دلم می‌گیره... 😢", "کی منو میبره پارک؟"],
        'happy':   ["هاپ! بهترین روز عمرمه! 🥳", "من و تو بهترین تیم دنیاییم!"],
        'fed':     ["هاپ هاپ! عاشقتم! 😋", "دمم داره می‌چرخه از خوشحالی!"],
        'played':  ["بازم! بازم! 🎾", "هاپ! بریم دنبال توپ!"],
    }},
}


def _is_sleeping():
    # ساعت ایران، مستقل از timezone سرور
    import datetime
    from datetime import timezone, timedelta
    hour = datetime.datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30))).hour
    return hour >= PET_SLEEP_START_HOUR or hour < PET_SLEEP_END_HOUR


def _evolution_title(key, level):
    titles = {10: 'قهرمان', 20: 'افسانه‌ای', 30: 'سلطان'}
    tier = max((n for n in titles if level >= n), default=0)
    return (PETS[key]['name'] + ' ' + titles[tier]) if tier else PETS[key]['name']


def pet_daily_gift_available(user):
    """True when the daily pet gift has not been claimed today (Iran time)."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30)))
    return (getattr(user, 'pet_daily_date', '') or '') != now.date().isoformat()


def pet_daily_gift(user):
    """هدیه‌ی روزانه‌ی idempotent؛ استریک بر اساس روزهای تقویمی ایران."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30)))
    today = now.date().isoformat()
    last = getattr(user, 'pet_daily_date', '') or ''
    if last == today:
        return False, '🎁 هدیه‌ی امروزت رو گرفتی؛ فردا دوباره بیا!'
    streak = int(getattr(user, 'pet_streak', 0) or 0)
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    streak = min(PET_DAILY_STREAK_MAX, streak + 1) if last == yesterday else 1
    user.pet_streak = streak
    user.pet_daily_date = today
    key = pet_active(user)
    xp = PET_DAILY_XP_BASE + max(0, streak - 1) * PET_DAILY_STREAK_BONUS_XP
    points = random.randint(min(PET_DAILY_POINTS_MAX, PET_DAILY_POINTS_MIN + (streak - 1) * 200), PET_DAILY_POINTS_MAX)
    if key:
        data = _load(user); p = _get(data, key, _now()); _gain_xp(p, xp); _save(user, data)
    else:
        points = points  # هدیه بدون پت هم قابل دریافت است
    user.fox_points = int(getattr(user, 'fox_points', 0) or 0) + points
    return True, (f"🎁 پتت یه هدیه برات آورده!\n💰 +{points:,} روب‌پوینت\n⭐ +{xp} تجربه" + (f"\n🔥 استریک: {streak} روز" if streak > 1 else "\n🌱 استریکت شروع شد!"))


def pet_toggle_reminders(user):
    user.pet_hunger_reminders = 0 if int(getattr(user, 'pet_hunger_reminders', 1) or 0) else 1
    return bool(user.pet_hunger_reminders)


def pet_tap(user):
    key = pet_active(user)
    if not key: return False, 'اول یه پت بگیر.'
    if _is_sleeping(): return False, '😴 پتت خوابه؛ صبح بیا نوازشش کن.'
    from datetime import datetime, timezone, timedelta
    now_dt = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30)))
    day = now_dt.date().isoformat(); now = _now(); data = _load(user); p = _get(data, key, now)
    if p.get('tap_day') != day: p['tap_day'], p['tap_count'] = day, 0
    if int(p.get('tap_count', 0)) >= PET_TAP_DAILY_LIMIT:
        return False, '🐾 سهم لمس امروزت تموم شده؛ فردا دوباره بیا!'
    p['tap_count'] = int(p.get('tap_count', 0)) + 1
    p['mood'] = min(100.0, p['mood'] + PET_TAP_MOOD); _save(user, data)
    return True, f"{PETS[key]['emoji']} پتت ذوق کرد! 💖 حالش +{PET_TAP_MOOD}٪ شد. ({p['tap_count']}/{PET_TAP_DAILY_LIMIT})"


def pet_image_path(key):
    info = PETS.get(key)
    return os.path.join(BASE_DIR, info['image']) if info else None


# ---------------------------------------------------------------- مالکیت (فقط یک پت)
def pet_active(user):
    """پت فعلی کاربر ('' اگه هنوز پتی نگرفته)."""
    key = (getattr(user, 'pet_active', '') or '').strip()
    return key if key in PETS else ''


def pet_next_to_buy(user):
    """پت بعدی که می‌تونه بگیره: بدون پت → همستر؛ وگرنه بعدیِ پت فعلی؛ سگ آخرینه."""
    cur = pet_active(user)
    if not cur:
        return PET_ORDER[0]
    i = PET_ORDER.index(cur)
    return PET_ORDER[i + 1] if i + 1 < len(PET_ORDER) else None


def pet_can_buy(user, key):
    if key not in PETS:
        return False, "این پت وجود نداره."
    nxt = pet_next_to_buy(user)
    if nxt is None:
        return False, "تو بهترین پت رو داری 🐶"
    if key != nxt:
        return False, f"پت بعدیت {PETS[nxt]['emoji']} {PETS[nxt]['name']} هست."
    price = PETS[key]['price']
    if int(getattr(user, 'fox_points', 0) or 0) < price:
        return False, f"روب‌پوینت کافی نیست. {price:,} لازم داری."
    return True, ""


def pet_buy(user, key):
    """گرفتن/خرید پت بعدی؛ جایگزین پت فعلی می‌شه. فراخوان باید commit کنه."""
    ok, msg = pet_can_buy(user, key)
    if not ok:
        return False, msg
    old = pet_active(user)
    user.fox_points = int(user.fox_points or 0) - PETS[key]['price']
    user.pet_active = key
    user.pets_owned = key
    data = _load(user)
    if old:
        data.pop(old, None)          # پت قبلی رفت؛ فقط یک پت داریم
    data[key] = _blank(_now())
    _save(user, data)
    p = PETS[key]
    if old:
        return True, f"{p['emoji']} {p['name']} جای {PETS[old]['emoji']} {PETS[old]['name']} اومد!"
    return True, f"{p['emoji']} {p['name']} مال تو شد!"


def pet_next_payload(user):
    """برای مینی‌اپ: پت بعدی که می‌شه گرفت (یا None)."""
    nxt = pet_next_to_buy(user)
    if not nxt:
        return None
    p = PETS[nxt]
    return {'key': nxt, 'emoji': p['emoji'], 'name': p['name'], 'price': p['price'], 'image': '/pet-image/' + nxt, 'about': p['about'],
            'first': not pet_active(user), 'affordable': int(getattr(user, 'fox_points', 0) or 0) >= p['price']}


# ---------------------------------------------------------------- وضعیت ذخیره‌شده (JSON)
def _now():
    return int(time.time())


def _load(user):
    try:
        d = json.loads(getattr(user, 'pets_data', '') or '{}')
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(user, data):
    user.pets_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def _blank(now):
    return {'n': '', 'xp': 0, 'sat': 80.0, 'mood': 80.0, 't': now, 'pt': 0, 'feed_at': 0, 'tap_day': '', 'tap_count': 0, 'bath_at': now}


def _decay(p, now):
    dt = max(0.0, now - int(p.get('t', now)))
    p['sat'] = max(0.0, float(p.get('sat', 80)) - SAT_DECAY_PER_H * dt / 3600.0)
    p['mood'] = max(0.0, float(p.get('mood', 80)) - MOOD_DECAY_PER_H * dt / 3600.0)
    p['t'] = now


def _get(data, key, now):
    p = data.get(key)
    if not isinstance(p, dict):
        p = _blank(now)
        data[key] = p
    # داده‌های قدیمی: اگر هنوز رکورد حمام ندارند، حمام را در اولین نمایش نیازمند در نظر بگیر.
    if 'bath_at' not in p:
        p['bath_at'] = now - PET_BATH_COOLDOWN
    _decay(p, now)
    return p


def pet_level(xp):
    return max(1, min(MAX_PET_LEVEL, int(math.sqrt(max(0, xp) / 60.0)) + 1))


def _xp_for_level(lvl):
    return 60 * (lvl - 1) ** 2


def pet_xp_progress(xp):
    """(لول، کسر پیشرفت تا لول بعد، تجربه‌ی فعلی توی لول، تجربه‌ی لازم برای لول بعد)"""
    lvl = pet_level(xp)
    if lvl >= MAX_PET_LEVEL:
        return lvl, 1.0, 0, 0
    lo, hi = _xp_for_level(lvl), _xp_for_level(lvl + 1)
    return lvl, (xp - lo) / float(hi - lo), xp - lo, hi - lo


def pet_state_kind(p):
    if p['sat'] < 30:
        return 'hungry'
    if p['mood'] < 30:
        return 'sad'
    if p['sat'] >= 60 and p['mood'] >= 60:
        return 'happy'
    return 'greet'


_STATE_LABEL = {'hungry': 'گرسنه 😫', 'sad': 'ناراحت 😢', 'happy': 'خوشحال و سرحال 🥰', 'greet': 'معمولی 🙂'}


def pet_say(key, kind, name='', user_name=''):
    msgs = PERSONALITY.get(key, {}).get('msg', {}).get(kind) or PERSONALITY['hamster']['msg']['greet']
    return random.choice(msgs).format(n=name or PETS[key]['name'], u=user_name or 'رفیق')


def pet_status(user, user_name=''):
    """وضعیت پت فعلی برای نمایش (بدون تغییر دیتابیس). None اگه پت نداره."""
    key = pet_active(user)
    if not key:
        return None
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    lvl, frac, cur, need = pet_xp_progress(float(p.get('xp', 0)))
    kind = pet_state_kind(p)
    return {
        'key': key, 'emoji': PETS[key]['emoji'], 'image': '/pet-image/' + key, 'type_name': PETS[key]['name'],
        'name': p.get('n') or PETS[key]['name'], 'title': PERSONALITY[key]['title'], 'evolution_title': _evolution_title(key, pet_level(float(p.get('xp', 0)))), 'reminders': bool(getattr(user, 'pet_hunger_reminders', 1)), 'sleeping': _is_sleeping(), 'favorite_food': FAVORITE_FOODS.get(key, 'meal'),
        'level': lvl, 'max_level': MAX_PET_LEVEL, 'xp': float(p.get('xp', 0)), 'xp_frac': round(frac, 3),
        'xp_cur': float(cur), 'xp_need': int(need),
        'satiety': int(round(p['sat'])), 'mood': int(round(p['mood'])),
        'state': kind, 'state_label': _STATE_LABEL[kind], 'say': pet_say(key, kind, p.get('n'), user_name),
        'play_wait': max(0, PLAY_COOLDOWN - (now - int(p.get('pt', 0)))),
        'bath_wait': max(0, PET_BATH_COOLDOWN - (now - int(p.get('bath_at', now - PET_BATH_COOLDOWN)))),
        'bath_due': (now - int(p.get('bath_at', now - PET_BATH_COOLDOWN))) >= PET_BATH_COOLDOWN,
        'foods': [{'key': FAVORITE_FOODS[key], 'emoji': FOODS[FAVORITE_FOODS[key]]['emoji'], 'name': FOODS[FAVORITE_FOODS[key]]['name'], 'price': PET_FEED_PRICE[key], 'cooldown': PET_FEED_COOLDOWN[key], 'wait': max(0, PET_FEED_COOLDOWN[key] - (now - int(p.get('feed_at', 0))))}],
    }


def _gain_xp(p, amount):
    old = pet_level(p.get('xp', 0))
    p['xp'] = float(p.get('xp', 0)) + float(amount)
    new = pet_level(p['xp'])
    return new if new > old else 0


def _delta_line(icon, label, before, after):
    b, a = int(round(before)), int(round(after))
    d = a - b
    sign = f"+{d}" if d >= 0 else str(d)
    return f"{icon} {label}: {b}٪ ← {a}٪  ({sign}٪)"


# ---------------------------------------------------------------- اکشن‌ها
def pet_rename(user, name):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت بگیر."
    name = " ".join((name or "").split())
    if not name:
        return False, "اسم نمی‌تونه خالی باشه."
    if len(name) > 12:
        return False, "اسم حداکثر ۱۲ کاراکتر می‌تونه باشه."
    data = _load(user)
    p = _get(data, key, _now())
    p['n'] = name
    _save(user, data)
    return True, f"اسم پتت شد «{name}» {PETS[key]['emoji']}"


def pet_feed(user, food_key, user_name='', paid=False):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت بگیر."
    expected = FAVORITE_FOODS[key]
    if food_key != expected:
        return False, f"غذای مخصوص {PETS[key]['name']} {FOODS[expected]['emoji']} {FOODS[expected]['name']}ـه."
    now = _now(); data = _load(user); p = _get(data, key, now)
    wait = PET_FEED_COOLDOWN[key] - (now - int(p.get('feed_at', 0)))
    price = PET_FEED_PRICE[key]
    if wait > 0 and not paid:
        return False, f"⏳ برای غذای بعدی {int(math.ceil(wait/60))} دقیقه صبر کن یا با {price:,} روب‌پوینت همین الان غذا بده."
    if p['sat'] >= 98:
        return False, "پتت سیره، الان غذا نمی‌خواد 😅"
    if paid and int(user.fox_points or 0) < price:
        return False, f"روب‌پوینت کافی نیست؛ {price:,} روب‌پوینت لازم داری."
    sat0, mood0 = p['sat'], p['mood']
    if paid:
        user.fox_points = int(user.fox_points or 0) - price
    p['feed_at'] = now
    p['sat'] = min(100.0, p['sat'] + FOODS[food_key]['sat'])
    favorite = True
    p['mood'] = min(100.0, p['mood'] + PET_FEED_MOOD)
    xp_gain = PET_FEED_XP[key]
    up = _gain_xp(p, xp_gain)
    _save(user, data)
    name = p.get('n') or PETS[key]['name']; kind = pet_state_kind(p); f = FOODS[food_key]
    lines = [f"{f['emoji']} {pet_say(key, 'fed', p.get('n'), user_name)}", (f"💚 وای، غذای موردعلاقه‌م بود!" if favorite else ""), f"🍽 {f['name']} دادی به {name}" + (f" (-{price:,} روب‌پوینت)" if paid else " (رایگان)"), _delta_line("🍖", "سیری", sat0, p['sat']), _delta_line("💖", "حال", mood0, p['mood']), f"⭐ +{xp_gain:g} تجربه", f"🙂 حال {name} الان: {_STATE_LABEL[kind]}"]
    if up:
        lines.append(f"🎉 {name} رفت لول {up}!")
        if up in (10, 20, 30): lines.append(f"🌟 تکامل جدید! لقبش شد «{_evolution_title(key, up)}»! تبریک! 🎊")
    return True, "\n".join(lines)


def pet_bath(user):
    """حمام پت از مینی‌اپ؛ زمان و پاداش سمت سرور ثبت می‌شوند."""
    key = pet_active(user)
    if not key:
        return False, "اول یه پت بگیر."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    wait = PET_BATH_COOLDOWN - (now - int(p.get('bath_at', now - PET_BATH_COOLDOWN)))
    if wait > 0:
        hours = int(wait // 3600)
        minutes = int((wait % 3600 + 59) // 60)
        return False, f"🫧 پتت تمیزه! حمام بعدی {hours} ساعت و {minutes} دقیقه دیگه لازمه."
    before = int(round(p['mood']))
    p['mood'] = min(100.0, p['mood'] + PET_BATH_MOOD)
    p['bath_at'] = now
    _save(user, data)
    name = p.get('n') or PETS[key]['name']
    after = int(round(p['mood']))
    return True, f"🧼 حمام تموم شد! {name} تمیز و خوشبو شد.\n💖 حال: {before}٪ ← {after}٪ (+{after-before}٪)\n🫧 حمام بعدی ۱۲ ساعت دیگه لازمه."


def pet_play(user, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت بگیر."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    wait = PLAY_COOLDOWN - (now - int(p.get('pt', 0)))
    if wait > 0:
        return False, f"پتت خسته‌ست؛ {int(math.ceil(wait / 60))} دقیقه‌ی دیگه بازم نازش کن 😴"
    if _is_sleeping():
        return False, "😴 پتت خوابه؛ بعد از ساعت ۷ صبح بیدار می‌شه."
    if p['sat'] < 10:
        return False, "پتت خیلی گرسنه‌ست، اول غذا بده 🍪"
    sat0, mood0 = p['sat'], p['mood']
    p['pt'] = now
    p['mood'] = min(100.0, p['mood'] + 18)
    p['sat'] = max(0.0, p['sat'] - 3)
    up = _gain_xp(p, PET_PLAY_XP)
    _save(user, data)
    name = p.get('n') or PETS[key]['name']
    kind = pet_state_kind(p)
    lines = [
        f"🤗 {pet_say(key, 'played', p.get('n'), user_name)}", "",
        f"🤗 {name} رو نازش کردی",
        _delta_line("💖", "حال", mood0, p['mood']),
        _delta_line("🍖", "سیری", sat0, p['sat']),
        f"⭐ +{PET_PLAY_XP} تجربه",
        f"🙂 حال {name} الان: {_STATE_LABEL[kind]}",
    ]
    if up:
        lines.append(f"🎉 {name} رفت لول {up}!")
        if up in (10, 20, 30): lines.append(f"🌟 تکامل جدید! از این به بعد لقبش «{_evolution_title(key, up)}»ـه! تبریک! 🎊")
    return True, "\n".join(lines)
