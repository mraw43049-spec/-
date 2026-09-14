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
HUNT_ITEMS={"🐇":{"name":"خرگوش","nutrition":4,"sell":7000},"🐭":{"name":"موش","nutrition":1,"sell":1000},"🦡":{"name":"راکون","nutrition":3,"sell":5000},"🦆":{"name":"اردک","nutrition":2,"sell":3000},"🐤":{"name":"جوجه","nutrition":1,"sell":1000},"🐟":{"name":"ماهی","nutrition":1,"sell":1000},"🥕":{"name":"هویج","nutrition":1,"sell":1000},"🐿":{"name":"سنجاب","nutrition":2,"sell":3000},"🦗":{"name":"ملخ","nutrition":1,"sell":1000},"🐓":{"name":"خروس","nutrition":4,"sell":7000},"🦌":{"name":"آهو","nutrition":5,"sell":9000}}
FOX_MAX_LEVEL = 25
FOX_MAX_BELLY_CAPACITY = 20
FOX_MAX_STORAGE_CAPACITY = 20

def fox_rank(level):
    # فقط 25 مقام رسمی؛ داده‌ی قدیمی کاربران کم/زیاد نمی‌شود.
    return FOX_RANKS[max(1, min(FOX_MAX_LEVEL, int(level or 1))) - 1]

def fox_capacity(level):
    # ظرفیت شکم غذا: از 3 شروع می‌شود و حداکثر به 20 می‌رسد.
    return min(FOX_MAX_BELLY_CAPACITY, 3 + max(0, int(level or 1) - 1))

def fox_storage_capacity(level):
    # ظرفیت روب‌پوینت تولیدشده: حداکثر 20.
    return min(FOX_MAX_STORAGE_CAPACITY, max(1, int(level or 1)))

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
