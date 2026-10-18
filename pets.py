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
    'cat':     {'emoji': '🐱', 'name': 'گربه',    'price': 2_000_000,  'image': 'pet_cat.png',
                'about': 'گربه‌ی نارنجی و شیطون که همه‌جا دنبالته.'},
    'rabbit':  {'emoji': '🐰', 'name': 'خرگوش',   'price': 5_000_000,  'image': 'pet_rabbit.png',
                'about': 'خرگوش سفید و گوش‌دراز که عاشق هویجه.'},
    'dog':     {'emoji': '🐶', 'name': 'سگ پامرانین', 'price': 12_000_000, 'image': 'pet_dog.png',
                'about': 'سگ پامرانین پرپشمِ بامزه؛ بهترین رفیق روباه!'},
}
PET_ORDER = list(PETS.keys())

MAX_PET_LEVEL = 30
SAT_DECAY_PER_H = 4.0      # سیری از ۱۰۰ تا صفر در ~۲۵ ساعت
MOOD_DECAY_PER_H = 3.0
PLAY_COOLDOWN = 20 * 60    # نوازش هر ۲۰ دقیقه

FOODS = {
    'snack': {'emoji': '🍪', 'name': 'بیسکوییت', 'price': 10_000, 'sat': 25, 'xp': 10},
    'meal':  {'emoji': '🍖', 'name': 'غذای کامل', 'price': 40_000, 'sat': 70, 'xp': 40},
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
    return {'key': nxt, 'emoji': p['emoji'], 'name': p['name'], 'price': p['price'], 'about': p['about'],
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
    return {'n': '', 'xp': 0, 'sat': 80.0, 'mood': 80.0, 't': now, 'pt': 0}


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
    lvl, frac, cur, need = pet_xp_progress(int(p.get('xp', 0)))
    kind = pet_state_kind(p)
    return {
        'key': key, 'emoji': PETS[key]['emoji'], 'type_name': PETS[key]['name'],
        'name': p.get('n') or PETS[key]['name'], 'title': PERSONALITY[key]['title'],
        'level': lvl, 'max_level': MAX_PET_LEVEL, 'xp': int(p.get('xp', 0)), 'xp_frac': round(frac, 3),
        'xp_cur': int(cur), 'xp_need': int(need),
        'satiety': int(round(p['sat'])), 'mood': int(round(p['mood'])),
        'state': kind, 'state_label': _STATE_LABEL[kind], 'say': pet_say(key, kind, p.get('n'), user_name),
        'play_wait': max(0, PLAY_COOLDOWN - (now - int(p.get('pt', 0)))),
        'foods': [{'key': k, 'emoji': f['emoji'], 'name': f['name'], 'price': f['price']} for k, f in FOODS.items()],
    }


def _gain_xp(p, amount):
    old = pet_level(p.get('xp', 0))
    p['xp'] = int(p.get('xp', 0)) + int(amount)
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


def pet_feed(user, food_key, user_name=''):
    key = pet_active(user)
    if not key:
        return False, "اول یه پت بگیر."
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
    sat0, mood0 = p['sat'], p['mood']
    user.fox_points = int(user.fox_points or 0) - f['price']
    p['sat'] = min(100.0, p['sat'] + f['sat'])
    p['mood'] = min(100.0, p['mood'] + 5)
    up = _gain_xp(p, f['xp'])
    _save(user, data)
    name = p.get('n') or PETS[key]['name']
    kind = pet_state_kind(p)
    lines = [
        f"{f['emoji']} {pet_say(key, 'fed', p.get('n'), user_name)}", "",
        f"{f['emoji']} {f['name']} دادی به {name}  (-{f['price']:,} روب‌پوینت)",
        _delta_line("🍖", "سیری", sat0, p['sat']),
        _delta_line("💖", "حال", mood0, p['mood']),
        f"⭐ +{f['xp']} تجربه",
        f"🙂 حال {name} الان: {_STATE_LABEL[kind]}",
    ]
    if up:
        lines.append(f"🎉 {name} رفت لول {up}!")
    return True, "\n".join(lines)


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
    if p['sat'] < 10:
        return False, "پتت خیلی گرسنه‌ست، اول غذا بده 🍪"
    sat0, mood0 = p['sat'], p['mood']
    p['pt'] = now
    p['mood'] = min(100.0, p['mood'] + 18)
    p['sat'] = max(0.0, p['sat'] - 3)
    up = _gain_xp(p, 4)
    _save(user, data)
    name = p.get('n') or PETS[key]['name']
    kind = pet_state_kind(p)
    lines = [
        f"🤗 {pet_say(key, 'played', p.get('n'), user_name)}", "",
        f"🤗 {name} رو نازش کردی",
        _delta_line("💖", "حال", mood0, p['mood']),
        _delta_line("🍖", "سیری", sat0, p['sat']),
        "⭐ +4 تجربه",
        f"🙂 حال {name} الان: {_STATE_LABEL[kind]}",
    ]
    if up:
        lines.append(f"🎉 {name} رفت لول {up}!")
    return True, "\n".join(lines)
