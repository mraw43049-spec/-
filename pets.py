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
