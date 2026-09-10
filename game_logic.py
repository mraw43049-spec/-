# منطق سطح کاربر و روباه

GAME_EMOJIS = {
    "dice": "🎲",
    "darts": "🎯",
    "bowling": "🎳",
    "football": "⚽",
}
GAME_NAMES_FA = {
    "dice": "تاس",
    "darts": "دارت",
    "bowling": "بولینگ",
    "football": "فوتبال",
}

LEVELS = [
    {"level": 1, "min_points": 0, "unlocks": "dice"},
    {"level": 2, "min_points": 50, "unlocks": "dice"},
    {"level": 3, "min_points": 150, "unlocks": "darts"},
    {"level": 4, "min_points": 300, "unlocks": "bowling"},
    {"level": 5, "min_points": 500, "unlocks": "football"},
]

# از لول 5 به بعد هم سطح کاربر ادامه دارد تا قابلیت‌های آینده خراب نشوند.
# هر لول جدید 100 پوینت بیشتر از لول قبلی نیاز دارد.
def get_level_for_points(points: int) -> int:
    if points < 0:
        return 1
    if points < 50:
        return 1
    if points < 150:
        return 2
    if points < 300:
        return 3
    if points < 500:
        return 4
    return min(100, 5 + (points - 500) // 100)


def get_unlocked_games(level: int):
    return [e["unlocks"] for e in LEVELS if e["level"] <= level and e["unlocks"]]


def get_newly_unlocked_game(old_level: int, new_level: int):
    for e in LEVELS:
        if old_level < e["level"] <= new_level and e["unlocks"]:
            return e["unlocks"]
    return None


def points_to_next_level(points: int):
    current = get_level_for_points(points)
    if current >= 100:
        return None, 0
    if current == 1:
        target = 50
    elif current == 2:
        target = 150
    elif current == 3:
        target = 300
    elif current == 4:
        target = 500
    else:
        target = 500 + (current - 4) * 100
    return current + 1, max(0, target - points)


def points_needed_for_level(level: int):
    if level <= 1:
        return 0
    if level == 2:
        return 50
    if level == 3:
        return 150
    if level == 4:
        return 300
    if level == 5:
        return 500
    if level <= 100:
        return 500 + (level - 5) * 100
    return None


FOX_RANKS = [
    "روباه تازه‌کار", "روباه کوچک", "روباه چابک", "روباه جنگلی", "روباه زیرک",
    "روباه تیزبین", "روباه شکارچی", "روباه ماهر", "روباه زرنگ", "روباه باتجربه",
    "روباه سایه", "روباه شب‌گرد", "روباه رعد", "روباه آذرخش", "روباه سرخ",
    "روباه نقره‌ای", "روباه طلایی", "روباه اشرافی", "روباه سردار", "روباه فرمانده",
    "روباه بزرگ", "روباه کهن", "روباه افسانه‌ای", "روباه سلطنتی", "روباه شاهین‌دل",
    "روباه اسطوره‌ای", "روباه جاودان", "روباه اعظم", "روباه پادشاه", "روباه شاهنشاه",
    "روباه اژدها", "روباه کیهانی", "روباه بی‌رقیب", "روباه افسانه‌ساز", "روباه بزرگ‌مکار",
]

HUNT_ITEMS = {
    "🐇": {"name": "خرگوش", "nutrition": 3, "sell": 5000},
    "🐭": {"name": "موش", "nutrition": 1, "sell": 1000},
    "🦡": {"name": "راکون", "nutrition": 3, "sell": 5000},
    "🦆": {"name": "اردک", "nutrition": 2, "sell": 3000},
    "🐤": {"name": "جوجه", "nutrition": 1, "sell": 1000},
    "🐟": {"name": "ماهی", "nutrition": 1, "sell": 1000},
    "🥕": {"name": "هویج", "nutrition": 1, "sell": 1000},
    "🐿": {"name": "سنجاب", "nutrition": 2, "sell": 3000},
    "🦗": {"name": "ملخ", "nutrition": 1, "sell": 1000},
}


def fox_rank(level: int) -> str:
    level = max(1, min(35, int(level)))
    return FOX_RANKS[level - 1]


def fox_capacity(level: int) -> int:
    return 3 + max(0, level - 1) * 2


def fox_upgrade_cost(level: int) -> int:
    # لول 1 -> 2: 500، سپس هر بار 3000 تا بیشتر
    return 500 + max(0, level - 1) * 3000


def fox_production_per_second(level: int) -> float:
    # پایه 0.05 روب‌پوینت در ثانیه و هر ارتقا +0.05
    return round(0.05 * max(1, level), 2)


def fox_level_reward(level: int) -> int:
    # جایزه لول 2 = 250 و هر لول بعدی +100
    return 250 + max(0, level - 2) * 100
