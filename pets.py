# -*- coding: utf-8 -*-
"""پت‌های روبی: همستر (رایگان) ← گربه ← خرگوش ← سگ پامرانین.
هر پت فقط بعد از داشتن پت قبلی قابل خرید است. پت‌ها ظاهری هستند و روی اقتصاد بازی اثری ندارند.
عکس‌ها (pet_<key>.png) کنار همین فایل هستند؛ برای عوض کردن عکس کافیه فایل هم‌نام رو جایگزین کنی."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PETS = {
    'hamster': {'emoji': '🐹', 'name': 'همستر',   'price': 0,          'image': 'pet_hamster.png',
                'about': 'کوچولوی بامزه‌ی روبی؛ پت اولته و رایگانه!'},
    'cat':     {'emoji': '🐱', 'name': 'گربه',    'price': 2_000_000,  'image': 'pet_cat.png',
                'about': 'گربه‌ی نارنجی و شیطون که همه‌جا دنبالته.'},
    'rabbit':  {'emoji': '🐰', 'name': 'خرگوش',   'price': 5_000_000,  'image': 'pet_rabbit.png',
                'about': 'خرگوش سفید و گوش‌دراز که عاشق هویجه.'},
    'dog':     {'emoji': '🐶', 'name': 'سگ پامرانین', 'price': 12_000_000, 'image': 'pet_dog.png',
                'about': 'سگ پامرانین پرپشمِ بامزه؛ بهترین رفیق روباه!'},
}
PET_ORDER = list(PETS.keys())


def pet_image_path(key):
    info = PETS.get(key)
    return os.path.join(BASE_DIR, info['image']) if info else None


def pets_owned(user):
    """همستر همیشه مال کاربره؛ بقیه از ستون pets_owned خونده می‌شن (به ترتیب خرید)."""
    raw = [k.strip() for k in (getattr(user, 'pets_owned', '') or '').split(',') if k.strip()]
    owned = ['hamster'] + [k for k in PET_ORDER if k in raw and k != 'hamster']
    return owned


def pet_active(user):
    key = (getattr(user, 'pet_active', '') or '').strip()
    return key if key in PETS and key in pets_owned(user) else ''


def pet_next_to_buy(user):
    owned = pets_owned(user)
    for k in PET_ORDER:
        if k not in owned:
            return k
    return None


def pet_can_buy(user, key):
    """(ok, پیام) — خرید فقط به ترتیب و با روب‌پوینت کافی."""
    if key not in PETS:
        return False, "این پت وجود نداره."
    if key in pets_owned(user):
        return False, "این پت رو از قبل داری."
    nxt = pet_next_to_buy(user)
    if key != nxt:
        need = PETS[nxt]['name'] if nxt else ''
        return False, f"اول باید {PETS[nxt]['emoji']} {need} رو بخری." if nxt else "این پت وجود نداره."
    price = PETS[key]['price']
    if int(getattr(user, 'fox_points', 0) or 0) < price:
        return False, f"روب‌پوینت کافی نیست. {price:,} لازم داری."
    return True, ""


def pet_buy(user, key):
    """خرید + فعال‌کردن. فراخوان باید commit کنه. (ok, پیام)"""
    ok, msg = pet_can_buy(user, key)
    if not ok:
        return False, msg
    user.fox_points = int(user.fox_points or 0) - PETS[key]['price']
    owned = [k for k in pets_owned(user) if k != 'hamster'] + [key]
    user.pets_owned = ','.join(owned)
    user.pet_active = key
    return True, f"{PETS[key]['emoji']} {PETS[key]['name']} مال تو شد و فعال شد!"


def pet_select(user, key):
    """key='' یعنی غیرفعال کردن پت."""
    if key == '':
        user.pet_active = ''
        return True, "پت غیرفعال شد."
    if key not in PETS or key not in pets_owned(user):
        return False, "این پت رو نداری."
    user.pet_active = key
    return True, f"{PETS[key]['emoji']} {PETS[key]['name']} فعال شد."


def pets_payload(user):
    """برای مینی‌اپ."""
    owned = pets_owned(user)
    active = pet_active(user)
    nxt = pet_next_to_buy(user)
    out = []
    for k in PET_ORDER:
        p = PETS[k]
        out.append({
            'key': k, 'emoji': p['emoji'], 'name': p['name'], 'price': p['price'], 'about': p['about'],
            'owned': k in owned, 'active': k == active, 'can_buy': k == nxt,
            'locked': (k not in owned and k != nxt),
        })
    return out


# =====================================================================
#                      بازی پت: غذا، لول، نوازش، ماموریت، نبرد
# =====================================================================
import json
import math
import random
import time
from datetime import datetime, timezone

MAX_PET_LEVEL = 30
SAT_DECAY_PER_H = 4.0      # سیری از ۱۰۰ تا صفر در ~۲۵ ساعت
MOOD_DECAY_PER_H = 3.0
PLAY_COOLDOWN = 20 * 60    # نوازش هر ۲۰ دقیقه
BATTLES_PER_DAY = 8

FOODS = {
    'snack': {'emoji': '🍪', 'name': 'بیسکوییت', 'price': 10_000, 'sat': 25, 'xp': 10},
    'meal':  {'emoji': '🍖', 'name': 'غذای کامل', 'price': 40_000, 'sat': 70, 'xp': 40},
}

# ماموریت‌ها: ساعت → (پاداش پایه‌ی روب‌پوینت، تجربه)
MISSIONS = {
    1: {'name': 'گشت کوتاه',  'pts': 20_000,  'xp': 15},
    4: {'name': 'ماموریت جنگل', 'pts': 100_000, 'xp': 60},
    8: {'name': 'سفر بزرگ',   'pts': 260_000, 'xp': 150},
}
MISSION_SAT_COST = 20

# قدرت پایه‌ی هر پت در نبرد
BASE_POWER = {'hamster': 10, 'cat': 14, 'rabbit': 12, 'dog': 18}

PERSONALITY = {
    'hamster': {'title': 'شیطون و پرخور', 'msg': {
        'greet':   ["هی {u}! 🐹 امروز چه خبر؟", "{n} اینجاست، آماده‌ی ماجراجویی!"],
        'hungry':  ["شکمم داره قارقار می‌کنه! 🥺 یه چیزی بده بخورم", "گشنمه گشنمه گشنمه!"],
        'sad':     ["کسی نیست با من بازی کنه... 😢", "دلم گرفته، یکم نازم کن"],
        'happy':   ["من خوشحال‌ترین همستر دنیام! 🥰", "بیا یه دور بدو بدو کنیم!"],
        'fed':     ["نوش جان! گونه‌هام پر شد 😋", "آخیش، دمت گرم!"],
        'played':  ["قلقلکم میاد هی‌هی‌هی 😆", "بازم! بازم!"],
        'mission_go':   ["می‌رم دنبال دونه! 🌻", "تا برگردم تنقلات جمع کنم!"],
        'mission_back': ["برگشتم! کیسه‌م پر از گنجه 🎒", "ببین چی پیدا کردم!"],
        'win':     ["بردم! دمت گرم رفیق 🏆", "گونه‌هام رو باد کردم و بردم 😤"],
        'lose':    ["باختم... ولی دفعه‌ی بعد می‌زنمش 😤", "اوف... یه تنقلات بده خوب میشم"],
    }},
    'cat': {'title': 'مغرور و ناز', 'msg': {
        'greet':   ["میو~ 🐱 بالاخره اومدی {u}", "{n} تشریف آورد."],
        'hungry':  ["میو! وقت غذاست، من منتظر نمی‌مونم 😾", "یه چیز درست‌حسابی بیار، نه هر چیزی!"],
        'sad':     ["هیچکس منو ناز نمی‌کنه... 😿", "بی‌حوصله‌ام، بغلم کن"],
        'happy':   ["خرخر خرخر... 😻 امروز مهربونم", "می‌تونی نازم کنی... فقط امروز!"],
        'fed':     ["بد نبود. می‌تونی تکرار کنی 😼", "میو~ قابل قبول بود"],
        'played':  ["خرخر... ادامه بده 😽", "یه دقیقه دیگه... فقط یه دقیقه"],
        'mission_go':   ["می‌رم شکار. منتظرم نباش 😼", "پنهونی میرم، کسی نفهمه"],
        'mission_back': ["بفرما، هدیه‌ی گربه‌ای 🎁", "ببین چی آوردم. تشکر لازم نیست"],
        'win':     ["البته که بردم. من گربه‌ام 😼🏆", "پنجه‌هام بی‌رحمن 🐾"],
        'lose':    ["این بازی تقلبی بود! 😾", "فقط حواسم پرت شد، همین"],
    }},
    'rabbit': {'title': 'خجالتی و مهربون', 'msg': {
        'greet':   ["سلام {u}... 🐰 خوشحالم دیدمت", "{n} یواش اومد کنارت~"],
        'hungry':  ["ببخشید... یه هویج دارید؟ 🥕", "شکمم یکم خالیه، اگه زحمتی نیست..."],
        'sad':     ["یکم غمگینم... کنارم میشینی؟ 🥺", "حس می‌کنم تنهام"],
        'happy':   ["دلم گرمه، ممنونم که هستی 🥰", "می‌خوام بپرم از خوشحالی!"],
        'fed':     ["اوم‌اوم، خیلی خوشمزه بود، مرسی 🥕", "ممنونم! دلم قرص شد"],
        'played':  ["هی... خجالت می‌کشم 🙈 ولی خوشم اومد", "گوشام داغ شد 🥰"],
        'mission_go':   ["می‌رم دنبال هویج... کمی می‌ترسم 🥕", "زود برمی‌گردم، قول میدم"],
        'mission_back': ["برگشتم! امیدوارم خوشت بیاد 🎁", "یه چیزایی پیدا کردم برات~"],
        'win':     ["وای، بردم؟! باورم نمی‌شه 🏆", "تمام قدرتم رو جمع کردم... و بردم!"],
        'lose':    ["اشکالی نداره... دفعه‌ی بعد بهتر می‌شم 🥺", "ترسیدم... ولی تلاشم رو کردم"],
    }},
    'dog': {'title': 'وفادار و پرانرژی', 'msg': {
        'greet':   ["هاپ هاپ! {u}! 🐶 دلم برات تنگ شده بود!", "{n} دمش رو تکون می‌ده!"],
        'hungry':  ["هاپ! شکمم خالیه رفیق! 🍖", "بوی غذا میاد؟ هاپ هاپ!"],
        'sad':     ["بدون بازی دلم می‌گیره... 😢", "کی منو میبره پارک؟"],
        'happy':   ["هاپ! بهترین روز عمرمه! 🥳", "من و تو بهترین تیم دنیاییم!"],
        'fed':     ["هاپ هاپ! عاشقتم! 😋", "دمم داره می‌چرخه از خوشحالی!"],
        'played':  ["بازم! بازم! 🎾", "هاپ! بریم دنبال توپ!"],
        'mission_go':   ["نگهبانی بر عهده‌ی من! 🛡️", "می‌رم ببینم چی پیدا می‌کنم، هاپ!"],
        'mission_back': ["هاپ! ماموریت انجام شد قربان! 🫡", "با غنیمت برگشتم!"],
        'win':     ["هاپ هاپ! قهرمانم! 🏆", "تو بهترین صاحب دنیایی، من بردم!"],
        'lose':    ["هوووو... بدجور خوردم 😭", "باختم ولی دلم نمی‌شکنه، دوباره می‌جنگم!"],
    }},
}


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
    return {'n': '', 'xp': 0, 'sat': 80.0, 'mood': 80.0, 't': now, 'pt': 0, 'w': 0, 'l': 0, 'm': None}


def _decay(p, now):
    dt = max(0.0, (now - int(p.get('t', now))) / 3600.0)
    p['sat'] = max(0.0, float(p.get('sat', 80)) - SAT_DECAY_PER_H * dt)
    p['mood'] = max(0.0, float(p.get('mood', 80)) - MOOD_DECAY_PER_H * dt)
    p['t'] = now


def _get(data, key, now):
    p = data.get(key)
    if not isinstance(p, dict):
        p = _blank(now)
        data[key] = p
    _decay(p, now)
    return p


def pet_level(xp):
    return max(1, min(MAX_PET_LEVEL, int(math.sqrt(max(0, xp) / 60.0)) + 1))


def _xp_for_level(lvl):
    return 60 * (lvl - 1) ** 2


def pet_xp_progress(xp):
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


def pet_say(key, kind, name='', user_name=''):
    msgs = PERSONALITY.get(key, {}).get('msg', {}).get(kind) or PERSONALITY['hamster']['msg']['greet']
    return random.choice(msgs).format(n=name or PETS[key]['name'], u=user_name or 'رفیق')


def pet_power(key, p):
    lvl = pet_level(p.get('xp', 0))
    power = BASE_POWER.get(key, 10) + lvl * 4
    power += 8 if p['sat'] >= 30 else -6
    power += 8 if p['mood'] >= 30 else -6
    return max(5.0, power)


def pet_status(user, user_name=''):
    """وضعیت پت فعال برای نمایش (بدون تغییر دیتابیس). None اگر پت فعال نباشه."""
    key = pet_active(user)
    if not key:
        return None
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    lvl, frac, cur, need = pet_xp_progress(int(p.get('xp', 0)))
    m = p.get('m')
    mission = None
    if m:
        left = int(m['end']) - now
        mission = {'hours': m['h'], 'name': MISSIONS[m['h']]['name'], 'left': max(0, left), 'done': left <= 0}
    kind = pet_state_kind(p)
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bd = data.get('_bd') or {}
    battles_left = BATTLES_PER_DAY - (bd.get('n', 0) if bd.get('d') == day else 0)
    return {
        'key': key, 'emoji': PETS[key]['emoji'], 'type_name': PETS[key]['name'],
        'name': p.get('n') or PETS[key]['name'], 'title': PERSONALITY[key]['title'],
        'level': lvl, 'max_level': MAX_PET_LEVEL, 'xp': int(p.get('xp', 0)), 'xp_frac': round(frac, 3),
        'xp_cur': int(cur), 'xp_need': int(need),
        'satiety': int(round(p['sat'])), 'mood': int(round(p['mood'])),
        'state': kind, 'say': pet_say(key, kind, p.get('n'), user_name),
        'power': int(round(pet_power(key, p))), 'wins': int(p.get('w', 0)), 'losses': int(p.get('l', 0)),
        'play_wait': max(0, PLAY_COOLDOWN - (now - int(p.get('pt', 0)))),
        'mission': mission, 'battles_left': max(0, battles_left),
        'foods': [{'key': k, 'emoji': f['emoji'], 'name': f['name'], 'price': f['price']} for k, f in FOODS.items()],
        'missions': [{'hours': h, 'name': m_['name'], 'pts': m_['pts']} for h, m_ in MISSIONS.items()],
    }


def _gain_xp(p, amount):
    old = pet_level(p.get('xp', 0))
    p['xp'] = int(p.get('xp', 0)) + int(amount)
    new = pet_level(p['xp'])
    return new if new > old else 0


def pet_rename(user, name):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
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


def pet_feed(user, food_key, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
    f = FOODS.get(food_key)
    if not f:
        return False, "این غذا وجود نداره."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    if p['sat'] >= 98:
        return False, "پتت سیره، الان نمی‌خوره 😅"
    if int(user.fox_points or 0) < f['price']:
        return False, f"روب‌پوینت کافی نیست. {f['price']:,} لازم داری."
    user.fox_points = int(user.fox_points or 0) - f['price']
    p['sat'] = min(100.0, p['sat'] + f['sat'])
    p['mood'] = min(100.0, p['mood'] + 5)
    up = _gain_xp(p, f['xp'])
    _save(user, data)
    msg = f"{f['emoji']} {pet_say(key, 'fed', p.get('n'), user_name)}"
    if up:
        msg += f"\n⬆️ پتت رفت لول {up}!"
    return True, msg


def pet_play(user, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    wait = PLAY_COOLDOWN - (now - int(p.get('pt', 0)))
    if wait > 0:
        return False, f"پتت خسته‌ست؛ {int(math.ceil(wait / 60))} دقیقه‌ی دیگه بازم نازش کن 😴"
    if p['sat'] < 10:
        return False, "پتت خیلی گرسنه‌ست، اول غذا بده 🍪"
    p['pt'] = now
    p['mood'] = min(100.0, p['mood'] + 18)
    p['sat'] = max(0.0, p['sat'] - 3)
    up = _gain_xp(p, 4)
    _save(user, data)
    msg = f"🤗 {pet_say(key, 'played', p.get('n'), user_name)}"
    if up:
        msg += f"\n⬆️ پتت رفت لول {up}!"
    return True, msg


def pet_mission_start(user, hours, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
    if hours not in MISSIONS:
        return False, "این ماموریت وجود نداره."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    if p.get('m'):
        return False, "پتت الان توی ماموریته."
    if p['sat'] < MISSION_SAT_COST:
        return False, f"پتت گرسنه‌ست؛ برای ماموریت حداقل {MISSION_SAT_COST}٪ سیری لازمه 🍖"
    p['sat'] = max(0.0, p['sat'] - MISSION_SAT_COST)
    p['m'] = {'h': int(hours), 'end': now + int(hours) * 3600}
    _save(user, data)
    return True, f"🎒 {pet_say(key, 'mission_go', p.get('n'), user_name)}\n⏳ {MISSIONS[hours]['name']} — {hours} ساعت"


def pet_mission_collect(user, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    m = p.get('m')
    if not m:
        return False, "پتت توی ماموریت نیست."
    left = int(m['end']) - now
    if left > 0:
        return False, f"هنوز برنگشته؛ {left // 3600} ساعت و {(left % 3600) // 60} دقیقه‌ی دیگه."
    info = MISSIONS[m['h']]
    lvl = pet_level(p.get('xp', 0))
    mult = (1 + lvl * 0.08) * random.uniform(0.85, 1.2)
    if p['mood'] < 30:
        mult *= 0.6        # پت ناراحت کمتر پیدا می‌کنه
    pts = int(info['pts'] * mult)
    user.fox_points = int(user.fox_points or 0) + pts
    p['m'] = None
    p['mood'] = max(0.0, p['mood'] - 5)
    up = _gain_xp(p, info['xp'])
    _save(user, data)
    msg = f"🎁 {pet_say(key, 'mission_back', p.get('n'), user_name)}\n💰 +{pts:,} روب‌پوینت\n✨ +{info['xp']} تجربه"
    if up:
        msg += f"\n⬆️ پتت رفت لول {up}!"
    return True, msg


def pet_battle(session, user, user_name=''):
    """نبرد با پت یه بازیکن دیگه (یا یه پت وحشی اگه حریفی نبود). فراخوان commit می‌کنه."""
    from database import User
    from sqlalchemy import func
    key = pet_active(user)
    if not key:
        return False, "اول یه پت فعال کن."
    now = _now()
    data = _load(user)
    p = _get(data, key, now)
    if p.get('m'):
        return False, "پتت توی ماموریته؛ بعد از برگشتن بجنگه."
    if p['sat'] < 15:
        return False, "پتت گرسنه‌ست و جون جنگیدن نداره 🍖"
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bd = data.get('_bd') or {}
    if bd.get('d') != day:
        bd = {'d': day, 'n': 0}
    if bd['n'] >= BATTLES_PER_DAY:
        return False, f"امروز {BATTLES_PER_DAY} بار جنگیدی؛ فردا دوباره!"

    # حریف
    opp = session.query(User).filter(User.pet_active != '', User.telegram_id != user.telegram_id) \
        .order_by(func.random()).first()
    opp_name, opp_key, opp_pow, opp_emoji = None, None, None, None
    if opp is not None:
        od = _load(opp)
        ok = pet_active(opp)
        if ok:
            op = od.get(ok) if isinstance(od.get(ok), dict) else _blank(now)
            op = dict(op); _decay(op, now)
            opp_key = ok
            opp_pow = pet_power(ok, op)
            opp_emoji = PETS[ok]['emoji']
            opp_name = (op.get('n') or PETS[ok]['name']) + " (" + (opp.first_name or opp.username or "ناشناس") + ")"
    if opp_name is None:       # پت وحشی
        wk = random.choice(PET_ORDER)
        mylvl = pet_level(p.get('xp', 0))
        opp_key, opp_emoji = wk, PETS[wk]['emoji']
        opp_pow = BASE_POWER[wk] + max(1, mylvl + random.randint(-2, 2)) * 4 + random.randint(-4, 6)
        opp_name = f"{PETS[wk]['name']} وحشی"

    mine = pet_power(key, p)
    my_wins = 0
    lines = []
    for r in range(1, 4):
        a = mine * random.uniform(0.7, 1.3)
        b = opp_pow * random.uniform(0.7, 1.3)
        if a >= b:
            my_wins += 1
            lines.append(f"راند {r}: ✅ برنده شدی")
        else:
            lines.append(f"راند {r}: ❌ باختی")
    won = my_wins >= 2
    bd['n'] += 1
    data['_bd'] = bd
    p['sat'] = max(0.0, p['sat'] - 10)
    my_name = p.get('n') or PETS[key]['name']
    head = f"⚔️ {PETS[key]['emoji']} {my_name}  VS  {opp_emoji} {opp_name}\n" + "\n".join(lines) + "\n"
    if won:
        lvl = pet_level(p.get('xp', 0))
        pts = min(300_000, 30_000 + 5_000 * lvl)
        user.fox_points = int(user.fox_points or 0) + pts
        p['w'] = int(p.get('w', 0)) + 1
        p['mood'] = min(100.0, p['mood'] + 6)
        up = _gain_xp(p, 25)
        tail = f"\n🏆 {pet_say(key, 'win', p.get('n'), user_name)}\n💰 +{pts:,} روب‌پوینت\n✨ +25 تجربه"
    else:
        p['l'] = int(p.get('l', 0)) + 1
        p['mood'] = max(0.0, p['mood'] - 10)
        up = _gain_xp(p, 8)
        tail = f"\n💔 {pet_say(key, 'lose', p.get('n'), user_name)}\n✨ +8 تجربه"
    if up:
        tail += f"\n⬆️ پتت رفت لول {up}!"
    _save(user, data)
    return True, head + tail
