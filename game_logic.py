import random

GAME_EMOJIS={"dice":"🎲","darts":"🎯","bowling":"🎳","football":"⚽"}
GAME_NAMES_FA={"dice":"تاس","darts":"دارت","bowling":"بولینگ","football":"فوتبال"}
LEVELS=[{"level":1,"min_points":0,"unlocks":"dice"},{"level":2,"min_points":50,"unlocks":"dice"},{"level":3,"min_points":150,"unlocks":"darts"},{"level":4,"min_points":300,"unlocks":"bowling"},{"level":5,"min_points":500,"unlocks":"football"}]
def get_level_for_points(points):
    if points<50:return 1
    if points<150:return 2
    if points<300:return 3
    if points<500:return 4
    return min(100,5+(points-500)//100)
def get_unlocked_games(level):return [e["unlocks"] for e in LEVELS if e["level"]<=level and e["unlocks"]]
def get_newly_unlocked_game(old_level,new_level):
    for e in LEVELS:
        if old_level<e["level"]<=new_level and e["unlocks"]:return e["unlocks"]
    return None
def points_to_next_level(points):
    c=get_level_for_points(points)
    if c>=100:return None,0
    t=points_needed_for_level(c+1);return c+1,max(0,t-points)
def points_needed_for_level(level):
    if level<=1:return 0
    if level==2:return 50
    if level==3:return 150
    if level==4:return 300
    if level==5:return 500
    if level<=100:return 500+(level-5)*100
    return None
FOX_RANKS=["روباه تازه‌کار","روباه کوچک","روباه چابک","روباه جنگلی","روباه زیرک","روباه تیزبین","روباه شکارچی","روباه ماهر","روباه زرنگ","روباه باتجربه","روباه سایه","روباه شب‌گرد","روباه رعد","روباه آذرخش","روباه سرخ","روباه نقره‌ای","روباه طلایی","روباه اشرافی","روباه سردار","روباه فرمانده","روباه بزرگ","روباه کهن","روباه افسانه‌ای","روباه سلطنتی","روباه شاهین‌دل","روباه اسطوره‌ای","روباه جاودان","روباه اعظم","روباه پادشاه","روباه شاهنشاه","روباه اژدها","روباه کیهانی","روباه بی‌رقیب","روباه افسانه‌ساز","روباه بزرگ‌مکار"]

# رده‌ی کمیابی بر اساس ارزش غذایی خام هر حیوان تعیین می‌شود (فقط برای نمایش تو یخچال).
RARITY_BY_NUTRITION = {
    1: {"label": "معمولی", "emoji": "⚪️"},
    2: {"label": "غیرمعمولی", "emoji": "🟢"},
    3: {"label": "کمیاب", "emoji": "🔵"},
    4: {"label": "خیلی کمیاب", "emoji": "🟣"},
    5: {"label": "افسانه‌ای", "emoji": "🟡"},
}

def _rarity_of(nutrition):
    tier = RARITY_BY_NUTRITION.get(max(1, min(5, int(nutrition))), RARITY_BY_NUTRITION[1])
    return tier["label"], tier["emoji"]

# weight_min/weight_max: بازه‌ی وزن (کیلوگرم) که موقع شکار هر بار به‌صورت تصادفی رول می‌شود.
HUNT_ITEMS={
    "🐇":{"name":"خرگوش","nutrition":4,"sell":7000,"weight_min":1.5,"weight_max":2.5},
    "🐭":{"name":"موش","nutrition":1,"sell":1000,"weight_min":0.02,"weight_max":0.05},
    "🦡":{"name":"راکون","nutrition":3,"sell":5000,"weight_min":4.0,"weight_max":8.0},
    "🦆":{"name":"اردک","nutrition":2,"sell":3000,"weight_min":1.0,"weight_max":2.0},
    "🐤":{"name":"جوجه","nutrition":1,"sell":1000,"weight_min":0.3,"weight_max":0.6},
    "🐟":{"name":"ماهی","nutrition":1,"sell":1000,"weight_min":0.2,"weight_max":1.0},
    "🥕":{"name":"هویج","nutrition":1,"sell":1000,"weight_min":0.05,"weight_max":0.15},
    "🐿":{"name":"سنجاب","nutrition":2,"sell":3000,"weight_min":0.3,"weight_max":0.5},
    "🦗":{"name":"ملخ","nutrition":1,"sell":1000,"weight_min":0.005,"weight_max":0.01},
    "🐓":{"name":"خروس","nutrition":4,"sell":7000,"weight_min":2.0,"weight_max":3.5},
    "🦌":{"name":"آهو","nutrition":5,"sell":9000,"weight_min":30.0,"weight_max":70.0},
}
for _emoji, _item in HUNT_ITEMS.items():
    _label, _emo = _rarity_of(_item["nutrition"])
    _item["rarity"] = _label
    _item["rarity_emoji"] = _emo
del _emoji, _item, _label, _emo

FOX_MAX_LEVEL = 25
FOX_MAX_BELLY_CAPACITY = 20
FOX_MAX_STORAGE_CAPACITY = 5_000_000

def fox_rank(level):
    # فقط 25 مقام رسمی؛ داده‌ی قدیمی کاربران کم/زیاد نمی‌شود.
    return FOX_RANKS[max(1, min(FOX_MAX_LEVEL, int(level or 1))) - 1]

def fox_capacity(level):
    # ظرفیت شکم غذا: از 3 شروع می‌شود و حداکثر به 20 می‌رسد.
    return min(FOX_MAX_BELLY_CAPACITY, 3 + max(0, int(level or 1) - 1))

def fox_storage_capacity(level):
    # ظرفیت مخزن روب‌پوینت مثل سیستم اصلی: با هر ارتقا دو برابر می‌شود.
    # سقف 5,000,000 است. این با ظرفیت شکم روباه فرق دارد؛ شکم جداگانه حداکثر 20 است.
    return min(FOX_MAX_STORAGE_CAPACITY, 1000 * (2 ** max(0, int(level or 1) - 1)))

def fox_upgrade_cost(level):
    # هزینه‌ی ارتقا بدون تغییر نسبت به سیستم قبلی حفظ می‌شود.
    level = max(1, int(level or 1))
    old_capacity = min(5_000_000, 1000 * (2 ** max(0, level - 1)))
    return 3 * old_capacity

def fox_production_interval(level):
    # لول 1 = یک روب‌پوینت در ثانیه؛ لول 25 = بیست روب‌پوینت در ثانیه.
    # در لول‌های 20 تا 25 نرخ روی سقف 20 نگه داشته می‌شود.
    rate = min(20, max(1, int(level or 1)))
    return 1.0 / rate

def fox_production_per_second(level):
    # لول 1 -> 1/sec ... لول 20+ -> 20/sec.
    return float(min(20, max(1, int(level or 1))))

def fox_level_reward(level):return 50*max(1,int(level)-1)

# ---------- یخچال روبی ----------
FRIDGE_UNLOCK_LEVEL = 7
FRIDGE_BASE_CAPACITY = 1           # ظرفیت پایه (قبل از هر ارتقا)؛ یخچال باز که می‌شه فقط 1 جا داره.
FRIDGE_MAX_LEVEL = 6               # سطح 1 = پایه + 5 ارتقا = سطح 6 (آخرین سطح ممکن)
FRIDGE_SLOTS_PER_UPGRADE = 1       # هر ارتقا (طبق درخواست) 1 جای اضافه می‌دهد.
# کلید = سطحی که با این هزینه به آن می‌رسیم؛ ارتقای اول (رسیدن به سطح 2) رایگان است.
FRIDGE_UPGRADE_COSTS = {2: 0, 3: 250_000, 4: 375_000, 5: 500_000, 6: 750_000}

# زمان پخت بر اساس ارزش غذایی خام (ثانیه). عدد سطح 5 (آهو) در درخواست ذکر نشده بود؛
# فرض: با همون الگوی رشد بقیه‌ی سطوح (اختلاف هر پله تقریباً ۳ برابر پله قبلی) ادامه داده شد.
FRIDGE_COOK_SECONDS = {1: 230, 2: 240, 3: 270, 4: 360, 5: 630}

def fridge_capacity(level):
    level = max(1, min(FRIDGE_MAX_LEVEL, int(level or 1)))
    return FRIDGE_BASE_CAPACITY + (level - 1) * FRIDGE_SLOTS_PER_UPGRADE

def fridge_upgrade_cost(level):
    """هزینه‌ی ارتقا از سطح فعلی به سطح بعدی. اگر دیگه ارتقایی نمونده None برمی‌گرداند."""
    level = max(1, int(level or 1))
    return FRIDGE_UPGRADE_COSTS.get(level + 1)

def fridge_cook_seconds(nutrition):
    n = max(1, int(nutrition or 1))
    if n in FRIDGE_COOK_SECONDS:
        return FRIDGE_COOK_SECONDS[n]
    return FRIDGE_COOK_SECONDS[max(FRIDGE_COOK_SECONDS)]

# ---------- کارخونه روبی ----------
FACTORY_UNLOCK_LEVEL = 10
FACTORY_BUILD_COST = 150_000
FACTORY_BUILD_SECONDS = 3 * 60 * 60  # ۳ ساعت تا افتتاح کارخونه بعد از ساخت‌وساز

FACTORY_STORAGE_BASE = 25_000        # ظرفیت انبار در سطح ۱
FACTORY_STORAGE_STEP = 10_000        # هر ارتقا +۱۰ هزار جا
FACTORY_STORAGE_MAX_LEVEL = 6        # آخرین سطح انبار: 25k -> 35k -> 45k -> 55k -> 65k -> 75k

FACTORY_MACHINE_MAX_LEVEL = 15       # آخرین سطح کارخونه/دستگاه‌های تولید
FACTORY_BASE_HOURS_100 = 21          # زمان تولید یک بچ ۱۰۰٪ در سطح ۱ دستگاه‌ها (ساعت)
FACTORY_MIN_HOURS_100 = 7            # زمان تولید یک بچ ۱۰۰٪ در آخرین سطح دستگاه‌ها (ساعت)

FACTORY_WORKERS_MAX_LEVEL = 16       # حداکثر تعداد روباه‌کارگر = حداکثر تعداد تولید هم‌زمان

FACTORY_UPGRADE_BASE_COST = 75_000   # هزینه‌ی اولین ارتقای انبار/دستگاه‌ها/کارکنان (رسیدن به سطح ۲)
FACTORY_UPGRADE_STEP_COST = 50_000   # هر ارتقای بعدی نسبت به ارتقای قبلی ۵۰ هزار روب‌پوینت بیشتر می‌شود

# هر ردیف تولید: کلید، عنوان، حداقل «محصول تولیدشده‌ی کل» برای باز شدن، و آیتم‌هایش
# هر آیتم: (ایموجی, اسم, هزینه‌ی ساخت هر عدد به روب‌پوینت, بیشترین قیمت فروش هر عدد به روب‌پوینت)
FACTORY_TIERS = [
    {"key": "candy", "title": "تولید آبنبات 🍭", "unlock_produced": 0, "items": [
        ("🍬", "آبنبات", 1, 3),
        ("🍭", "آبنبات چوبی", 3, 5),
        ("🍫", "شکلات", 5, 8),
    ]},
    {"key": "watch", "title": "تولید ساعت ⌚", "unlock_produced": 75_000, "items": [
        ("⌚", "ساعت مچی", 8, 15),
        ("⏳", "ساعت شنی", 9, 18),
        ("⏰", "ساعت زنگ‌دار", 12, 25),
    ]},
    {"key": "sandwich", "title": "تولید ساندویچ 🍔", "unlock_produced": 120_000, "items": [
        ("🌭", "هات‌داگ", 16, 36),
        ("🥪", "ساندویچ", 18, 35),
        ("🍔", "همبرگر", 20, 38),
    ]},
    {"key": "music", "title": "ابزار موسیقی 🎻", "unlock_produced": 175_000, "items": [
        ("🎺", "ترومپت", 22, 42),
        ("🎸", "گیتار", 24, 45),
        ("🎻", "ویولن", 26, 48),
    ]},
    {"key": "satellite", "title": "تولید ماهواره 🛰", "unlock_produced": 230_000, "items": [
        ("🛰", "ماهواره", 28, 53),
        ("🛸", "بشقاب پرنده", 30, 58),
        ("🚀", "موشک", 32, 62),
    ]},
    {"key": "ship", "title": "تولید کشتی 🛳", "unlock_produced": 300_000, "items": [
        ("🛥", "قایق", 34, 65),
        ("🛳", "کشتی مسافربری", 36, 72),
        ("🚢", "کشتی باری", 40, 80),
    ]},
]

# ---------- بازار کارخونه (نوسان قیمت فروش محصولات) ----------
# محصول تولیدشده دیگه خودکار فروخته نمی‌شه؛ اول میره تو انبار، بعد کاربر با قیمت روز می‌فروشدش.
FACTORY_MARKET_UPDATE_SECONDS = 25 * 60   # هر ۲۵ دقیقه قیمت هر محصول یک بار عوض می‌شود.
FACTORY_MARKET_FLOOR_DROP = 10            # کف قیمت هر محصول = سقف قیمتش منهای ۱۰ روب‌پوینت.


def factory_market_floor(ceiling):
    """کف قیمت بازار برای یک محصول؛ سقف همون قیمتیه که قبلاً به‌عنوان «بیشترین قیمت فروش» تعریف شده بود.
    کف همیشه کمتر از سقفه (هیچ‌وقت باهاش برابر نمی‌شه) تا قیمت واقعاً نوسان داشته باشه."""
    ceiling = max(1, int(ceiling or 1))
    floor = ceiling - FACTORY_MARKET_FLOOR_DROP
    if floor >= ceiling:
        floor = ceiling - 1
    return max(1, floor)


def factory_market_roll_price(ceiling):
    """یک قیمت تصادفی جدید بین کف و سقف بازار برای این محصول برمی‌گرداند."""
    ceiling = max(1, int(ceiling or 1))
    floor = factory_market_floor(ceiling)
    if floor >= ceiling:
        return ceiling
    return random.randint(floor, ceiling)


FACTORY_TIERS_BY_KEY = {t["key"]: t for t in FACTORY_TIERS}

# نگاشت مستقیم ایموجی محصول -> (کلید ردیف، اسم، هزینه‌ی ساخت، سقف قیمت فروش)
FACTORY_ITEM_INDEX = {}
for _t in FACTORY_TIERS:
    for _emoji, _name, _cost, _sell in _t["items"]:
        FACTORY_ITEM_INDEX[_emoji] = {"tier": _t["key"], "name": _name, "cost": _cost, "sell": _sell}
del _t, _emoji, _name, _cost, _sell


def factory_storage_capacity(level):
    level = max(1, min(FACTORY_STORAGE_MAX_LEVEL, int(level or 1)))
    return FACTORY_STORAGE_BASE + (level - 1) * FACTORY_STORAGE_STEP


def factory_machine_hours_for_100(level):
    level = max(1, min(FACTORY_MACHINE_MAX_LEVEL, int(level or 1)))
    return max(FACTORY_MIN_HOURS_100, FACTORY_BASE_HOURS_100 - (level - 1))


def factory_workers_capacity(level):
    return max(1, min(FACTORY_WORKERS_MAX_LEVEL, int(level or 1)))


def factory_upgrade_cost(current_level, max_level):
    """هزینه‌ی ارتقا از سطح فعلی به سطح بعدی: اولین ارتقا ۷۵هزار، هر ارتقای بعدی ۵۰هزار بیشتر از قبلی."""
    current_level = max(1, int(current_level or 1))
    if current_level >= max_level:
        return None
    return FACTORY_UPGRADE_BASE_COST + FACTORY_UPGRADE_STEP_COST * (current_level - 1)


def factory_unlocked_tiers(produced_total):
    produced_total = int(produced_total or 0)
    return [t for t in FACTORY_TIERS if produced_total >= t["unlock_produced"]]


def factory_order_plan(item_key, percent, storage_level, machine_level):
    """محاسبه‌ی تعداد، هزینه، زمان و ارزش فروش یک سفارش تولید بر اساس درصد انتخابی."""
    info = FACTORY_ITEM_INDEX.get(item_key)
    if not info:
        return None
    percent = max(1, min(100, int(percent)))
    capacity = factory_storage_capacity(storage_level)
    quantity = max(1, round(capacity * percent / 100))
    cost = quantity * info["cost"]
    hours_100 = factory_machine_hours_for_100(machine_level)
    seconds = max(60, round(hours_100 * 3600 * percent / 100))
    sell_total = quantity * info["sell"]
    return {
        "quantity": quantity, "cost": cost, "seconds": seconds, "sell_total": sell_total,
        "name": info["name"], "tier": info["tier"], "unit_sell": info["sell"], "unit_cost": info["cost"],
    }
