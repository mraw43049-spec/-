"""
منطق سطح‌بندی کاربر و بازی‌هایی که در هر سطح باز میشن.
"""

# ایموجی هر بازی مطابق با API تلگرام (sendDice)
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

# هر سطح: حداقل پوینت لازم + بازی‌ای که در همون سطح آزاد میشه (اگه باشه)
LEVELS = [
    {"level": 1, "min_points": 0, "unlocks": None},
    {"level": 2, "min_points": 50, "unlocks": "dice"},
    {"level": 3, "min_points": 150, "unlocks": "darts"},
    {"level": 4, "min_points": 300, "unlocks": "bowling"},
    {"level": 5, "min_points": 500, "unlocks": "football"},
]


def get_level_for_points(points: int) -> int:
    level = 1
    for entry in LEVELS:
        if points >= entry["min_points"]:
            level = entry["level"]
    return level


def get_unlocked_games(level: int) -> list[str]:
    return [
        entry["unlocks"]
        for entry in LEVELS
        if entry["level"] <= level and entry["unlocks"] is not None
    ]


def get_newly_unlocked_game(old_level: int, new_level: int) -> str | None:
    """اگه بین دو سطح، بازی جدیدی آزاد شده باشه اسمشو برمیگردونه."""
    for entry in LEVELS:
        if old_level < entry["level"] <= new_level and entry["unlocks"]:
            return entry["unlocks"]
    return None


def points_to_next_level(points: int) -> tuple[int | None, int]:
    """(سطح بعدی، پوینت باقی‌مونده) - اگه سطح آخر باشه سطح بعدی None میشه."""
    current_level = get_level_for_points(points)
    for entry in LEVELS:
        if entry["level"] == current_level + 1:
            return entry["level"], entry["min_points"] - points
    return None, 0
