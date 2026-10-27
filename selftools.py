# -*- coding: utf-8 -*-
"""ابزارهای روزمرهٔ سلف: ماشین‌حساب، تاریخ، قیمت، اوقات شرعی، کوتاه‌کنندهٔ لینک و ذخیرهٔ استوری.

این فایل مستقل از پنل است و فقط توابع خالص/شبکه‌ای دارد؛ اتصال به دستورها و پنل در extras.py انجام می‌شود.
منبع‌های بیرونی (همه بدون کلید API):
  • قیمت ارز/طلا/سکه : tgju.org (غیررسمی؛ ممکن است ساختارش عوض شود)  ← متغیر اختیاری PRICE_API_URL
  • قیمت ارز دیجیتال : CoinGecko
  • اوقات شرعی        : Aladhan (روش ۷ = مؤسسهٔ ژئوفیزیک دانشگاه تهران)
  • کوتاه‌کنندهٔ لینک  : is.gd و در صورت خطا TinyURL
"""
import ast
import asyncio
import io
import json
import math
import mimetypes
import operator
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # noqa: BLE001
    TEHRAN = timezone(timedelta(hours=3, minutes=30))

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa2en(s):
    return (s or "").translate(_FA_DIGITS)


def to_fa(s):
    return str(s).translate(_TO_FA)


def _key(s):
    """نرمال‌سازی کلید جست‌وجو: حروف عربی→فارسی، حذف نیم‌فاصله/فاصله، کوچک‌کردن."""
    s = (s or "").replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"[\u200c\u200d\ufe0f\s_\-]+", "", s).lower()


# ---------------------------------------------------------------- HTTP
def _http_get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(6_000_000).decode("utf-8", "replace")


async def http_get(url, timeout=12):
    return await asyncio.to_thread(_http_get, url, timeout)


async def http_json(url, timeout=12):
    return json.loads(await http_get(url, timeout))


# ---------------------------------------------------------------- ماشین‌حساب
class CalcError(ValueError):
    pass


def _safe_pow(a, b):
    if abs(b) > 1000:
        raise CalcError("توان خیلی بزرگ است")
    if isinstance(a, int) and isinstance(b, int) and b > 0 and abs(a) > 1 and math.log10(abs(a)) * b > 300:
        raise CalcError("عدد خیلی بزرگ می‌شود")
    return operator.pow(a, b)


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: _safe_pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
          "log": math.log10, "ln": math.log, "exp": math.exp}
_CONSTS = {"pi": math.pi, "e": math.e}
_FUNC_FA = {"جذر": "sqrt", "ریشه": "sqrt", "قدرمطلق": "abs", "گرد": "round", "لگاریتم": "log"}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = _FUNC_FA.get(node.func.id, node.func.id)
        fn = _FUNCS.get(name)
        if fn and 1 <= len(node.args) <= (2 if name == "round" else 1):
            return fn(*[_eval(a) for a in node.args])
    raise CalcError("عبارت نامعتبر")


def _prep_expr(expr):
    s = fa2en(expr or "").strip()
    s = s.replace("٫", ".").replace("٬", "").replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    s = s.replace("√", "sqrt").replace("π", "pi")
    s = re.sub(r"(?<=\d)\s*[xX]\s*(?=[\d(.])", "*", s)          # 2x3 → 2*3
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)                 # 1,000 → 1000
    s = re.sub(r"[\u200c\u200d]", "", s)
    return s


def fmt_num(v):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise CalcError("نتیجه نامعتبر")
        if v == int(v) and abs(v) < 1e15:
            v = int(v)
        else:
            return format(v, ",.10g")
    return f"{v:,}"


def calc(expr):
    """عبارت ریاضی را امن حساب می‌کند → (عبارت تمیز، نتیجهٔ قالب‌بندی‌شده). خطا: CalcError."""
    s = _prep_expr(expr)
    if not s:
        raise CalcError("عبارتی ننوشتی")
    if len(s) > 200:
        raise CalcError("عبارت خیلی طولانی است")
    try:
        tree = ast.parse(s, mode="eval")
        val = _eval(tree)
    except CalcError:
        raise
    except ZeroDivisionError:
        raise CalcError("تقسیم بر صفر")
    except (SyntaxError, RecursionError, ValueError, TypeError, OverflowError, MemoryError):
        raise CalcError("عبارت نامعتبر")
    return s, fmt_num(val)


# ---------------------------------------------------------------- تاریخ
J_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
G_MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
            "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
H_MONTHS = ["محرم", "صفر", "ربیع‌الاول", "ربیع‌الثانی", "جمادی‌الاول", "جمادی‌الثانی",
            "رجب", "شعبان", "رمضان", "شوال", "ذیقعده", "ذیحجه"]
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]   # date.weekday(): دوشنبه = 0


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + (days // 31), 1 + (days % 31)
    else:
        jm, jd = 7 + ((days - 186) // 30), 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = (-355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
            + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186))
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    sal = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal[gm]:
        gd -= sal[gm]
        gm += 1
    return gy, gm, gd


def gregorian_to_hijri(gy, gm, gd):
    """قمری به روش جدولی (تقریبی؛ با رؤیت هلال در ایران ممکن است ۱–۲ روز فرق کند)."""
    a = (gm - 14) // 12
    jd = (1461 * (gy + 4800 + a)) // 4 + (367 * (gm - 2 - 12 * a)) // 12 - (3 * ((gy + 4900 + a) // 100)) // 4 + gd - 32075
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    m = (24 * l) // 709
    d = l - (709 * m) // 24
    y = 30 * n + j - 30
    return y, m, d


def _jalali_valid(jy, jm, jd):
    if not (1 <= jm <= 12 and 1 <= jd <= 31 and 1 <= jy <= 3000):
        return False
    try:
        return gregorian_to_jalali(*jalali_to_gregorian(jy, jm, jd)) == (jy, jm, jd)
    except Exception:  # noqa: BLE001
        return False


def _fmt_g(d):
    return to_fa(f"{d.day} {G_MONTHS[d.month - 1]} {d.year}")


def _fmt_j(j):
    return to_fa(f"{j[2]} {J_MONTHS[j[1] - 1]} {j[0]}")


def _fmt_h(h):
    return to_fa(f"{h[2]} {H_MONTHS[(h[1] - 1) % 12]} {h[0]}")


def date_text(arg="", now=None):
    """بدون آرگومان: تاریخ امروز. با آرگومان 1405/8/5 یا 2026-10-27: تبدیل تاریخ."""
    arg = fa2en(arg or "").strip()
    if arg:
        m = re.match(r"^(\d{3,4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})$", arg)
        if not m:
            return "📅 مثل: .تاریخ   |   .تاریخ 1405/8/5   |   .تاریخ 2026-10-27"
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y >= 1700:
            try:
                g = date(y, mo, d)
            except ValueError:
                return "❌ تاریخ میلادی نامعتبر است."
            j = gregorian_to_jalali(g.year, g.month, g.day)
            return (f"📅 {_fmt_g(g)} میلادی\n= {WEEKDAYS[g.weekday()]} {_fmt_j(j)} شمسی")
        if not _jalali_valid(y, mo, d):
            return "❌ تاریخ شمسی نامعتبر است."
        g = date(*jalali_to_gregorian(y, mo, d))
        return (f"📅 {to_fa(f'{d} {J_MONTHS[mo - 1]} {y}')} شمسی\n= {WEEKDAYS[g.weekday()]} {_fmt_g(g)} میلادی")
    now = now or datetime.now(TEHRAN)
    g = now.date()
    j = gregorian_to_jalali(g.year, g.month, g.day)
    h = gregorian_to_hijri(g.year, g.month, g.day)
    return (f"📅 امروز: {WEEKDAYS[g.weekday()]} {_fmt_j(j)}\n"
            f"🗓 میلادی: {_fmt_g(g)}\n"
            f"🌙 قمری (تقریبی): {_fmt_h(h)}\n"
            f"🕒 ساعت: {to_fa(now.strftime('%H:%M'))} (به وقت تهران)")


# ---------------------------------------------------------------- قیمت
RIAL_TO_TOMAN = 10        # فید tgju قیمت‌ها را به ریال می‌دهد؛ نمایش به تومان
_TGJU_URLS = [u for u in (os.environ.get("PRICE_API_URL", "").strip(),
                          "https://call4.tgju.org/ajax.json", "https://call3.tgju.org/ajax.json") if u]
_TGJU = {"ts": 0.0, "data": None}
_COINS = {}

# نام فارسی/انگلیسی → (کلید tgju, عنوان)
_FIAT = {}
for _names, _k, _title in (
    (("دلار", "usd", "dollar"), "price_dollar_rl", "💵 دلار آمریکا"),
    (("یورو", "eur", "euro"), "price_eur", "💶 یورو"),
    (("پوند", "gbp"), "price_gbp", "💷 پوند انگلیس"),
    (("درهم", "aed"), "price_aed", "🇦🇪 درهم امارات"),
    (("لیر", "try"), "price_try", "🇹🇷 لیر ترکیه"),
    (("طلا", "طلای18", "طلا18", "گرم", "gold"), "geram18", "🥇 طلای ۱۸ عیار (هر گرم)"),
    (("سکه", "سکهامامی", "sekee", "coin"), "sekee", "🪙 سکهٔ امامی"),
):
    for _n in _names:
        _FIAT[_key(_n)] = (_k, _title)

# نام → (id در CoinGecko, عنوان)
_CRYPTO = {}
for _names, _cid, _title in (
    (("بیتکوین", "بیتکوین", "btc", "bitcoin"), "bitcoin", "₿ بیت‌کوین"),
    (("اتریوم", "eth", "ethereum"), "ethereum", "Ξ اتریوم"),
    (("تتر", "usdt", "tether"), "tether", "💲 تتر"),
    (("تون", "ton", "تونکوین"), "the-open-network", "💎 تون‌کوین"),
    (("ریپل", "xrp"), "ripple", "💧 ریپل"),
    (("سولانا", "sol", "solana"), "solana", "◎ سولانا"),
    (("دوج", "doge", "dogecoin", "دوجکوین"), "dogecoin", "🐶 دوج‌کوین"),
    (("ترون", "trx", "tron"), "tron", "🔺 ترون"),
    (("بایننس", "bnb"), "binancecoin", "🔶 بایننس‌کوین"),
):
    for _n in _names:
        _CRYPTO[_key(_n)] = (_cid, _title)

SUMMARY_FIAT = ("price_dollar_rl", "price_eur", "geram18", "sekee")
PRICE_HELP = ("💱 مثل: .قیمت   |   .قیمت دلار   |   .قیمت طلا\n"
              "ارز: دلار، یورو، پوند، درهم، لیر\nطلا: طلا، سکه\n"
              "دیجیتال: بیتکوین، اتریوم، تتر، تون، ریپل، سولانا، دوج، ترون، بایننس")


def _num(x):
    if x is None:
        return None
    s = re.sub(r"[^\d.]", "", fa2en(str(x)))
    if not s or s == ".":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return int(v) if v == int(v) else v


async def _tgju():
    now = time.time()
    if _TGJU["data"] and now - _TGJU["ts"] < 60:
        return _TGJU["data"]
    for url in _TGJU_URLS:
        try:
            j = await http_json(url, 12)
            cur = j.get("current") if isinstance(j, dict) else None
            if isinstance(cur, dict) and cur:
                _TGJU.update(ts=now, data=cur)
                return cur
        except Exception:  # noqa: BLE001
            continue
    if _TGJU["data"] and now - _TGJU["ts"] < 1800:      # اگه منبع قطع شد، تا نیم‌ساعت از آخرین نتیجه استفاده کن
        return _TGJU["data"]
    raise RuntimeError("tgju unavailable")


def _tgju_row(cur, key):
    r = cur.get(key)
    if not isinstance(r, dict):
        return None
    p = _num(r.get("p"))
    if p is None:
        p = _num(r.get("h"))
    if p is None:
        return None
    return {"p": p, "dp": _num(r.get("dp")), "dt": r.get("dt")}


def _arrow(dt, dp):
    if dp is None:
        return ""
    return (" 🔼" if dt == "high" else " 🔽" if dt == "low" else " ") + f"{dp:g}٪"


def _fmt_toman(rial):
    v = rial / RIAL_TO_TOMAN
    return f"{int(round(v)):,}"


async def _coins(ids):
    ids = [i for i in dict.fromkeys(ids) if i]
    url = ("https://api.coingecko.com/api/v3/simple/price?ids=" + ",".join(ids)
           + "&vs_currencies=usd&include_24hr_change=true")
    j = await http_json(url, 12)
    return j if isinstance(j, dict) else {}


def _coin_line(title, row, usd_rial):
    usd = row.get("usd")
    if usd is None:
        return None
    ch = row.get("usd_24h_change")
    s = f"{title}: ${usd:,.2f}" if usd >= 1 else f"{title}: ${usd:,.6g}"
    if usd_rial:
        s += f" ≈ {_fmt_toman(usd * usd_rial)} تومان"
    if isinstance(ch, (int, float)):
        s += f" {'🔼' if ch >= 0 else '🔽'}{abs(ch):.1f}٪"
    return s


async def price_text(arg=""):
    """.قیمت [دلار|طلا|بیتکوین|...] → متن آمادهٔ ارسال. خطا: RuntimeError."""
    q = _key(arg)
    now_s = to_fa(datetime.now(TEHRAN).strftime("%H:%M"))
    foot = f"\n🕒 {now_s} · منبع: tgju و CoinGecko"
    if q and q not in _FIAT and q not in _CRYPTO:
        return PRICE_HELP

    if not q:                                           # خلاصه
        res = await asyncio.gather(_tgju(), _coins(["bitcoin"]), return_exceptions=True)
        cur = res[0] if isinstance(res[0], dict) else None
        coins = res[1] if isinstance(res[1], dict) else {}
        if cur is None and not coins:
            raise RuntimeError("no price source")
        titles = {v[0]: v[1] for v in _FIAT.values()}
        lines = ["💱 قیمت‌های لحظه‌ای", ""]
        usd_rial = None
        if cur:
            r = _tgju_row(cur, "price_dollar_rl")
            usd_rial = r["p"] if r else None
            for k in SUMMARY_FIAT:
                row = _tgju_row(cur, k)
                if row:
                    lines.append(f"{titles[k]}: {_fmt_toman(row['p'])} تومان{_arrow(row['dt'], row['dp'])}")
        else:
            lines.append("⚠️ منبع قیمت ارز/طلا در دسترس نیست.")
        if coins.get("bitcoin"):
            ln = _coin_line("₿ بیت‌کوین", coins["bitcoin"], usd_rial)
            if ln:
                lines.append(ln)
        return "\n".join(lines) + foot

    if q in _FIAT:                                      # ارز/طلا/سکه
        k, title = _FIAT[q]
        cur = await _tgju()
        row = _tgju_row(cur, k)
        if not row:
            raise RuntimeError("item missing")
        return f"{title}\n💰 {_fmt_toman(row['p'])} تومان{_arrow(row['dt'], row['dp'])}" + foot

    cid, title = _CRYPTO[q]                             # ارز دیجیتال
    res = await asyncio.gather(_coins([cid]), _tgju(), return_exceptions=True)
    if isinstance(res[0], Exception) or not res[0].get(cid):
        raise RuntimeError("coin source")
    usd_rial = None
    if isinstance(res[1], dict):
        r = _tgju_row(res[1], "price_dollar_rl")
        usd_rial = r["p"] if r else None
    ln = _coin_line(title, res[0][cid], usd_rial)
    if not ln:
        raise RuntimeError("coin row")
    return ln + (foot if usd_rial else f"\n🕒 {now_s} · منبع: CoinGecko")


# ---------------------------------------------------------------- اوقات شرعی
# نام فارسی → (نام انگلیسی, عرض, طول)
CITIES = {
    "تهران": ("Tehran", 35.6892, 51.3890), "مشهد": ("Mashhad", 36.2605, 59.6168),
    "اصفهان": ("Isfahan", 32.6546, 51.6680), "شیراز": ("Shiraz", 29.5918, 52.5837),
    "تبریز": ("Tabriz", 38.0962, 46.2738), "کرج": ("Karaj", 35.8400, 50.9391),
    "قم": ("Qom", 34.6399, 50.8759), "اهواز": ("Ahvaz", 31.3183, 48.6706),
    "کرمانشاه": ("Kermanshah", 34.3142, 47.0650), "ارومیه": ("Urmia", 37.5527, 45.0761),
    "رشت": ("Rasht", 37.2808, 49.5832), "زاهدان": ("Zahedan", 29.4963, 60.8629),
    "همدان": ("Hamedan", 34.7983, 48.5148), "کرمان": ("Kerman", 30.2839, 57.0834),
    "یزد": ("Yazd", 31.8974, 54.3569), "اردبیل": ("Ardabil", 38.2498, 48.2933),
    "بندرعباس": ("Bandar Abbas", 27.1865, 56.2808), "اراک": ("Arak", 34.0954, 49.6892),
    "ساری": ("Sari", 36.5659, 53.0586), "گرگان": ("Gorgan", 36.8427, 54.4439),
    "زنجان": ("Zanjan", 36.6736, 48.4787), "سنندج": ("Sanandaj", 35.3219, 46.9862),
    "خرم‌آباد": ("Khorramabad", 33.4878, 48.3558), "بوشهر": ("Bushehr", 28.9234, 50.8203),
    "بیرجند": ("Birjand", 32.8649, 59.2262), "سمنان": ("Semnan", 35.5769, 53.3920),
    "ایلام": ("Ilam", 33.6374, 46.4227), "یاسوج": ("Yasuj", 30.6682, 51.5880),
    "شهرکرد": ("Shahrekord", 32.3256, 50.8644), "قزوین": ("Qazvin", 36.2688, 50.0041),
    "بجنورد": ("Bojnord", 37.4747, 57.3290),
}
CITY_NAMES = list(CITIES)
_CITY_IDX = {}
for _fa, (_en, _la, _lo) in CITIES.items():
    _CITY_IDX[_key(_fa)] = _fa
    _CITY_IDX[_key(_en)] = _fa
_CITY_IDX[_key("خرمآباد")] = "خرم‌آباد"
_CITY_IDX[_key("بندر عباس")] = "بندرعباس"
_CITY_IDX[_key("شهر کرد")] = "شهرکرد"

_PRAYER_ROWS = (("Fajr", "🌌 اذان صبح"), ("Sunrise", "🌅 طلوع آفتاب"), ("Dhuhr", "☀️ اذان ظهر"),
                ("Sunset", "🌇 غروب آفتاب"), ("Maghrib", "🌆 اذان مغرب"), ("Midnight", "🌙 نیمه‌شب شرعی"))
_PRAYER_CACHE = {}


def find_city(text):
    return _CITY_IDX.get(_key(text))


async def prayer_text(city):
    """اوقات شرعی امروز برای یک شهر ایران. city باید نام معتبر فارسی باشد (find_city)."""
    fa = find_city(city)
    if not fa:
        raise KeyError(city)
    en, lat, lon = CITIES[fa]
    now = datetime.now(TEHRAN)
    ck = (fa, now.strftime("%Y-%m-%d"))
    data = _PRAYER_CACHE.get(ck)
    if data is None:
        url = (f"https://api.aladhan.com/v1/timings/{now.strftime('%d-%m-%Y')}"
               f"?latitude={lat}&longitude={lon}&method=7&timezonestring=Asia/Tehran")
        j = await http_json(url, 12)
        tm = ((j or {}).get("data") or {}).get("timings") or {}
        data = {}
        for k, _ in _PRAYER_ROWS:
            m = re.search(r"(\d{1,2}:\d{2})", str(tm.get(k, "")))
            if m:
                data[k] = m.group(1)
        if not data:
            raise RuntimeError("prayer source")
        if len(_PRAYER_CACHE) > 200:
            _PRAYER_CACHE.clear()
        _PRAYER_CACHE[ck] = data
    g = now.date()
    j = gregorian_to_jalali(g.year, g.month, g.day)
    lines = [f"🕌 اوقات شرعی {fa} — {WEEKDAYS[g.weekday()]} {_fmt_j(j)}", ""]
    lines += [f"{label}: {to_fa(data[k])}" for k, label in _PRAYER_ROWS if k in data]
    lines.append("\n(روش محاسبه: مؤسسهٔ ژئوفیزیک دانشگاه تهران)")
    return "\n".join(lines)


# ---------------------------------------------------------------- کوتاه‌کنندهٔ لینک
URL_RE = re.compile(r"https?://[^\s<>\"'«»]+", re.I)
SHORT_MAX = 3


def find_urls(text, entities=None):
    """لینک‌ها را از متن و (اختیاری) entityهای تلگرام درمی‌آورد؛ بدون تکرار، حداکثر SHORT_MAX."""
    out = []
    for m in URL_RE.finditer(text or ""):
        out.append(m.group(0).rstrip(".,;:!?)»”"))
    for e in entities or []:
        u = getattr(e, "url", None)
        if isinstance(u, str) and u.lower().startswith(("http://", "https://")):
            out.append(u)
    seen, res = set(), []
    for u in out:
        if u not in seen and len(u) <= 2000:
            seen.add(u)
            res.append(u)
    return res[:SHORT_MAX]


async def _isgd(url):
    txt = (await http_get("https://is.gd/create.php?format=simple&url=" + urllib.parse.quote(url, safe=""), 12)).strip()
    if not txt.lower().startswith("http"):
        raise RuntimeError(txt[:80] or "is.gd error")
    return txt


async def _tinyurl(url):
    txt = (await http_get("https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe=""), 12)).strip()
    if not txt.lower().startswith("http"):
        raise RuntimeError(txt[:80] or "tinyurl error")
    return txt


async def shorten(url):
    last = None
    for fn in (_isgd, _tinyurl):
        try:
            return await fn(url)
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(str(last))


# ---------------------------------------------------------------- استوری
STORY_RE = re.compile(r"(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]{4,32})/s/(\d+)", re.I)
STORY_MAX_BYTES = 50 * 1024 * 1024


async def story_save(client, ev, arg):
    """.استوری ← ریپلای روی استوری/پیام حاوی لینک استوری، یا آرگومان t.me/user/s/123 → Saved Messages. متن نتیجه برمی‌گرداند."""
    from telethon import utils as tl_utils
    from telethon.tl import functions, types

    story, peer_inp, sid, uname = None, None, None, None
    texts = [arg or ""]
    r = None
    if ev.is_reply:
        r = await ev.get_reply_message()
        media = getattr(r, "media", None) if r else None
        if isinstance(media, getattr(types, "MessageMediaStory", ())):
            story = getattr(media, "story", None)
            sid = getattr(media, "id", None)
            try:
                peer_inp = await client.get_input_entity(media.peer)
            except Exception:  # noqa: BLE001
                peer_inp = None
        elif r is not None:
            texts.append(r.raw_text or "")
    if sid is None:
        for t in texts:
            m = STORY_RE.search(t)
            if m:
                uname, sid = m.group(1), int(m.group(2))
                try:
                    peer_inp = await client.get_input_entity(uname)
                except Exception:  # noqa: BLE001
                    return "❌ کاربر/کانال این لینک پیدا نشد."
                break
    if sid is None:
        return ("📖 روی پیام استوری ریپلای کن و بنویس .استوری\n"
                "یا لینکش رو بده: .استوری t.me/username/s/123")
    if not isinstance(story, getattr(types, "StoryItem", ())) or getattr(story, "media", None) is None:
        if peer_inp is None:
            return "❌ صاحب استوری پیدا نشد."
        try:
            res = await client(functions.stories.GetStoriesByIDRequest(peer=peer_inp, id=[sid]))
        except Exception:  # noqa: BLE001
            return "❌ استوری پیدا نشد؛ ممکنه منقضی/حذف شده باشه یا برای اکانتت قابل مشاهده نباشه."
        story = next((s for s in (getattr(res, "stories", None) or []) if isinstance(s, types.StoryItem)), None)
        if story is None:
            return "❌ این استوری دیگه در دسترس نیست (حذف یا منقضی شده)."
    if getattr(story, "noforwards", False):
        return "🔒 صاحب این استوری «محافظت از محتوا» رو روشن کرده؛ ذخیره‌اش ممکن نیست."
    med = story.media
    size = getattr(getattr(med, "document", None), "size", 0) or 0
    if size > STORY_MAX_BYTES:
        return "❌ حجم این استوری خیلی زیاده (بیشتر از ۵۰ مگابایت)."
    data = await client.download_media(med, file=bytes)
    if not data:
        return "❌ دانلود استوری انجام نشد."
    ext = ""
    try:
        ext = tl_utils.get_extension(med) or ""
    except Exception:  # noqa: BLE001
        pass
    if not ext:
        mime = getattr(getattr(med, "document", None), "mime_type", "") or ""
        ext = mimetypes.guess_extension(mime) or (".mp4" if getattr(med, "document", None) else ".jpg")
    bio = io.BytesIO(data)
    bio.name = "story" + ext
    cap = "📖 استوری ذخیره‌شده" + (f"\nاز: @{uname}" if uname else "")
    story_cap = getattr(story, "caption", None)
    if story_cap:
        cap += "\n" + story_cap
    await client.send_file("me", bio, caption=cap[:1000])
    return "✅ استوری توی Saved Messages ذخیره شد."
