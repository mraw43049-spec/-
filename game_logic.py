
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
# بازی‌ها با سطح باز می‌شوند.
LEVELS = [
    {"level": 1, "min_points": 0, "unlocks": "dice"},
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

def get_unlocked_games(level: int):
    return [e["unlocks"] for e in LEVELS if e["level"] <= level and e["unlocks"]]

def get_newly_unlocked_game(old_level: int, new_level: int):
    for e in LEVELS:
        if old_level < e["level"] <= new_level and e["unlocks"]:
            return e["unlocks"]
    return None

def points_to_next_level(points: int):
    current = get_level_for_points(points)
    for e in LEVELS:
        if e["level"] == current + 1:
            return e["level"], max(0, e["min_points"] - points)
    return None, 0

def points_needed_for_level(level: int):
    for e in LEVELS:
        if e["level"] == level:
            return e["min_points"]
    return None
