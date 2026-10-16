"""ساخت گیف انیمیشن موشک 🚀 برای کازینوی ربات با Pillow.
صحنه (پس‌زمینه + موشک روباهی) دقیقاً همون تصویری‌ه که تو مینی‌اپ هست (rocket_assets.py).
شمارنده از −۱٫۵ شروع می‌شه، بالا می‌ره و (اگه به ضریب هدف برسه) «TARGET HIT» می‌گیره؛ آخرش موشک تو نقطه‌ی سقوط می‌ترکه.
متن‌های داخل گیف انگلیسیه (فونت پیش‌فرض Pillow حروف فارسی نداره)؛ توضیحات فارسی تو کپشن تلگرام میاد."""
import io
import math
import random

from PIL import Image, ImageDraw, ImageFont

import rocket_assets

try:
    from rocket_core import START as _START
except Exception:  # noqa: BLE001
    _START = -1.5

LW, LH = 360, 295              # مختصات منطقی (هم‌نسبت با تصویر صحنه: ۸۸۲×۷۲۲)
OUT = 1.2                      # ضریب بزرگ‌نمایی خروجی
OW, OH = int(LW * OUT), int(LH * OUT)   # ۴۳۲×۳۵۴
SS = 2                         # سوپرسمپل برای لبه‌های صاف
ART_K = LW / 882.0             # مقیاس تصویر صحنه نسبت به مختصات منطقی
PAD_Y = 123                    # مرکز موشک روی سکو (دقیقاً مثل تصویر)
LOCK_Y = 123                   # موشک سر جاش می‌مونه و دوربین (پس‌زمینه) پایین می‌ره؛ بالای صحنه برای نوشته‌ها خالی می‌مونه
NOZZLE = 68.5                  # فاصله‌ی ته نازل تا مرکز موشک
CLIMB = 95                     # پیکسل منطقی به‌ازای هر واحد ارتفاع
FRAME_MS = 62

_ASSETS = {}


def _assets():
    """پس‌زمینه، موشک و آسمونِ بالای صحنه رو یک‌بار می‌سازه (کش می‌شه)."""
    if _ASSETS:
        return _ASSETS
    W, H = LW * SS, LH * SS
    bg = Image.open(io.BytesIO(rocket_assets.bg_bytes())).convert("RGB").resize((W, H), Image.LANCZOS)
    ship = Image.open(io.BytesIO(rocket_assets.ship_bytes())).convert("RGBA")
    sw, sh = int(round(212 * ART_K * SS)), int(round(356 * ART_K * SS))
    ship = ship.resize((sw, sh), Image.LANCZOS)
    # آسمون بالای تصویر: میانگینِ نوار بالایی، به‌صورت گرادیان نرم، رو به تیره‌تر شدن (فضا)
    ext_h = H + 40
    strip = bg.crop((0, 0, W, 16)).resize((12, 1), Image.BOX).resize((W, ext_h), Image.BICUBIC)
    fade = Image.linear_gradient("L").resize((W, ext_h))          # بالا=۰ ، پایین=۲۵۵
    fade = fade.point(lambda v: int(215 * (1 - v / 255.0)))      # بالا تیره‌تر
    ext = Image.composite(Image.new("RGB", (W, ext_h), (3, 5, 18)), strip, fade)
    _ASSETS.update({"bg": bg, "ship": ship, "ext": ext})
    return _ASSETS


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow قدیمی
        return ImageFont.load_default()


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _pose(alt):
    climb = alt * CLIMB
    y = max(LOCK_Y, PAD_Y - climb)
    cam = max(0.0, climb - (PAD_Y - LOCK_Y))
    return LW / 2, y, cam


def _tear(w, length, y0=31):
    pts = []
    for i in range(0, 13):
        t = i / 12
        x = -w * (1 - t) ** 2 * 1.0 - w * 0.9 * 2 * t * (1 - t) * 0
        # منحنی بزیه‌ی درجه‌ی دو: (-w,y0) → کنترل (-0.9w, y0+0.55L) → (0, y0+L)
        bx = (1 - t) ** 2 * (-w) + 2 * (1 - t) * t * (-0.9 * w) + t * t * 0
        by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * (y0 + 0.55 * length) + t * t * (y0 + length)
        pts.append((bx, by))
    for i in range(12, -1, -1):
        bx, by = pts[i]
        pts.append((-bx, by))
    return pts


def _poly(d, cx, cy, pts, fill, outline=None):
    d.polygon([((cx + x) * SS, (cy + y) * SS) for x, y in pts], fill=fill, outline=outline)


def _circle(d, x, y, r, fill):
    d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=fill)


_BLOB = {}


def _blob(layer, cx, cy, r, color, strength=1.0):
    """درخشش نرمِ دایره‌ای (گرادیان شعاعی) روی لایه‌ی RGBA؛ مختصات منطقی."""
    rr = max(2, int(r * SS))
    key = rr
    if key not in _BLOB:
        g = Image.radial_gradient("L").resize((rr * 2, rr * 2), Image.BICUBIC)       # مرکز=۰ ، لبه=۲۵۵
        _BLOB[key] = g.point(lambda v: int(255 * (max(0.0, 1 - v / 255.0) ** 1.7)))
    m = _BLOB[key].point(lambda v: int(v * max(0.0, min(1.0, strength))))
    tile = Image.new("RGBA", (rr * 2, rr * 2), tuple(color) + (255,))
    tile.putalpha(m)
    layer.alpha_composite(tile, (int(round(cx * SS - rr)), int(round(cy * SS - rr))))


def _draw_flame(d, glow_img, cx, cy, flame, tick):
    """شعله‌ی موتور (سه لایه) زیر نازل؛ flame = طول شعله به پیکسل منطقی."""
    if flame <= 0:
        return
    ny = cy + NOZZLE - 3
    _blob(glow_img, cx, ny + 26, 78, (255, 140, 40), 0.55)
    _blob(glow_img, cx, ny + 6, 38, (255, 215, 120), 0.7)
    fl = flame * (0.9 + 0.2 * math.sin(tick * 1.9))
    _poly(d, cx, 0, _tear(14, fl, ny), (255, 96, 28, 235))
    _poly(d, cx, 0, _tear(9, fl * 0.74, ny), (255, 176, 48, 245))
    _poly(d, cx, 0, _tear(4.6, fl * 0.44, ny), (255, 252, 222, 255))


def _paste_ship(img, cx, cy):
    ship = _assets()["ship"]
    img.alpha_composite(ship, (int(round(cx * SS - ship.width / 2)), int(round(cy * SS - ship.height / 2))))


def _background(sp, cam, stars, tick):
    A = _assets()
    W, H = LW * SS, LH * SS
    img = Image.new("RGBA", (W, H), (3, 5, 18, 255))
    cs = int(round(cam * SS))
    if cs > 0:
        img.paste(A["ext"], (0, cs - A["ext"].height))
    img.paste(A["bg"], (0, cs))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, H], fill=(2, 3, 14, int(255 * min(0.6, sp * 0.62))))
    sa = max(0.0, (sp - 0.15) / 0.7)
    if sa > 0:
        for (sx, sy, sr, ss, sph) in stars:
            yy = (sy * LH + cam * 0.35 * ss) % LH
            a = int(255 * sa * (0.3 + ss * 0.5) * (0.75 + 0.25 * math.sin(tick * 0.5 + sph)))
            _circle(d, sx * LW, yy, sr, (255, 255, 255, a))
    return Image.alpha_composite(img, ov)


def _spawn(parts, kind, x, y, vx, vy, life, r, g=0.0, col=None, rot=0.0, vr=0.0):
    parts.append({"k": kind, "x": x, "y": y, "vx": vx, "vy": vy, "life": life, "max": life, "r": r, "g": g, "c": col, "rot": rot, "vr": vr})


def _step_parts(parts):
    for p in parts[:]:
        p["life"] -= 1
        if p["life"] <= 0:
            parts.remove(p)
            continue
        p["vy"] += p["g"]
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["rot"] += p["vr"]
        if p["k"] == "smoke":
            p["r"] += 0.55
            p["vx"] *= 0.94


def _draw_parts(d, parts, kinds):
    for p in parts:
        if p["k"] not in kinds:
            continue
        k = p["life"] / p["max"]
        if p["k"] == "smoke":
            _circle(d, p["x"], p["y"], p["r"], (206, 209, 220, int(120 * k)))
        elif p["k"] == "spark":
            _circle(d, p["x"], p["y"], p["r"] * (0.5 + 0.5 * k), (255, 226, 150, int(255 * k)) if k > 0.5 else (255, 122, 42, int(255 * k)))
        elif p["k"] == "debris":
            c, s, r = math.cos(p["rot"]), math.sin(p["rot"]), p["r"]
            pts = [(-r, -r * 0.6), (r, -r * 0.6), (r, r * 0.6), (-r, r * 0.6)]
            d.polygon([((p["x"] + x * c - y * s) * SS, (p["y"] + x * s + y * c) * SS) for x, y in pts], fill=p["c"] + (int(255 * min(1, k * 1.6)),))


def _counter_color(v):
    if v < 0:
        return (255, 132, 132)
    if v < 1.5:
        return (160, 232, 255)
    if v < 3:
        return (125, 255, 179)
    if v < 10:
        return (255, 224, 138)
    return (255, 154, 232)


def _text(d, xy, s, size, fill, shadow=(0, 0, 0, 150)):
    x, y = xy
    d.text(((x + 1.5) * SS, (y + 1.5) * SS), s, font=_font(int(size * SS)), fill=shadow, anchor="mm")
    d.text((x * SS, y * SS), s, font=_font(int(size * SS)), fill=fill, anchor="mm")


def _hud(d, v, target, hit, boom_text=None):
    col = (255, 110, 110) if boom_text else _counter_color(v)
    _text(d, (LW / 2, 22), f"{v:.2f}x", 30, col)
    if hit:
        _text(d, (LW / 2, 42), f"TARGET x{target:.2f}  HIT!", 12, (125, 255, 179))
    else:
        _text(d, (LW / 2, 42), f"TARGET x{target:.2f}", 11.5, (235, 243, 255))
    if boom_text:
        _text(d, (LW / 2, 57), boom_text, 12, (255, 150, 150))


def _banner(d, win, target, cp, amount, pay, capped):
    W, H = LW * SS, LH * SS
    y = LH - 52
    edge = (125, 255, 179, 255) if win else (255, 120, 120, 255)
    d.rounded_rectangle([20 * SS, (y - 26) * SS, W - 20 * SS, (y + 28) * SS], radius=14 * SS, fill=(8, 10, 24, 230), outline=edge, width=2 * SS)
    if win:
        _text(d, (LW / 2, y - 8), f"WIN  +{pay - amount:,}", 22, (125, 255, 179), shadow=(0, 0, 0, 0))
        _text(d, (LW / 2, y + 14), f"x{target:.2f} reached  |  flew to x{cp:.2f}" if not capped else f"x{target:.2f} reached  |  MAX x{cp:g}", 11.5, (230, 238, 255), shadow=(0, 0, 0, 0))
    else:
        _text(d, (LW / 2, y - 8), f"CRASH  x{cp:.2f}", 22, (255, 130, 130), shadow=(0, 0, 0, 0))
        _text(d, (LW / 2, y + 14), f"-{amount:,}   (target x{target:.2f})", 11.5, (230, 238, 255), shadow=(0, 0, 0, 0))


def _finish(frames, durations):
    n = len(frames)
    sample = [frames[i] for i in sorted({0, n // 5, (2 * n) // 5, (3 * n) // 5, (4 * n) // 5, n - 1})]
    mosaic = Image.new("RGB", (OW, OH * len(sample)))
    for i, fr in enumerate(sample):
        mosaic.paste(fr, (0, i * OH))
    pal = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
    buf = io.BytesIO()
    q[0].save(buf, format="GIF", save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=False, disposal=1)
    return buf.getvalue()


def build_gif(cp, target, amount, pay, max_mult=10.0, edge_frames=None):
    """cp: نقطه‌ی سقوط ؛ target: ضریب هدف ؛ pay: پرداخت (۰ اگه باخت). برمی‌گردونه: (bytes گیف, مدت انیمیشن به ثانیه)."""
    cp, target = float(cp), float(target)
    capped = cp >= max_mult
    win = pay > 0
    top = min(cp, max_mult)
    rnd = random.Random(int(cp * 100) * 7 + int(target * 100))
    stars = [(rnd.random(), rnd.random(), rnd.uniform(0.6, 1.6), rnd.uniform(0.2, 1.0), rnd.uniform(0, 6.28)) for _ in range(60)]
    clouds = [(rnd.random(), rnd.uniform(120, 880), rnd.uniform(50, 110), rnd.uniform(0.35, 0.75)) for _ in range(9)]
    seq = []
    n_rise = 14
    for i in range(1, n_rise + 1):
        u = i / n_rise
        s = u * u * (3 - 2 * u)
        seq.append((_START + (1.0 - _START) * s, 0.25 * s, "rise"))
    n_climb = 4 if top <= 1.0001 else int(min(54, max(14, 14 * math.log(top) + 10)))
    for i in range(1, n_climb + 1):
        d = math.exp(math.log(max(top, 1.0)) * (i / n_climb))
        seq.append((d, 0.25 + math.log(d), "climb"))
    frames, durations, parts = [], [], []
    hit = False
    tick = 0

    def render(v, alt, phase, boom=None, banner=False, rocket=True, flame=True):
        nonlocal tick
        cx, cy, cam = _pose(alt)
        sp = min(1.0, alt / 1.7)
        img = _background(sp, cam, stars, tick)
        smoke = Image.new("RGBA", img.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(smoke)
        main = Image.new("RGBA", img.size, (0, 0, 0, 0)); md = ImageDraw.Draw(main)
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
        _draw_parts(sd, parts, ("smoke",))
        if rocket:
            fl = ((88 if phase == "rise" else 58 + min(48, alt * 16)) if flame else 0)
            _draw_flame(md, glow, cx, cy, fl, tick)
        if rocket:
            _paste_ship(main, cx, cy)
            md = ImageDraw.Draw(main)
        _draw_parts(md, parts, ("debris",)); _draw_parts(gd, parts, ("spark",))
        if boom is not None:
            age = boom
            if age < 7:
                fr_ = 22 + 70 * min(1, age / 3)
                fa_ = max(0, 1 - age / 7)
                _blob(glow, cx, cy, fr_ * 1.5, (255, 90, 30), 0.85 * fa_)
                _blob(glow, cx, cy, fr_ * 0.9, (255, 190, 80), 0.95 * fa_)
                _blob(glow, cx, cy, fr_ * 0.45, (255, 250, 225), fa_)
                gd.ellipse([(cx - 20 - 170 * min(1, age / 6)) * SS, (cy - 20 - 170 * min(1, age / 6)) * SS,
                            (cx + 20 + 170 * min(1, age / 6)) * SS, (cy + 20 + 170 * min(1, age / 6)) * SS],
                           outline=(255, 225, 175, int(200 * max(0, 1 - age / 6))), width=3 * SS)
        img = Image.alpha_composite(img, smoke)
        img = Image.alpha_composite(img, glow)
        img = Image.alpha_composite(img, main)
        hd = ImageDraw.Draw(img)
        _hud(hd, v, target, hit, boom_text=("CRASHED!" if boom is not None else None))
        if banner:
            bn = Image.new("RGBA", img.size, (0, 0, 0, 0))
            _banner(ImageDraw.Draw(bn), win, target, top, amount, pay, capped)
            img = Image.alpha_composite(img, bn)
        frames.append(img.convert("RGB").resize((OW, OH), Image.LANCZOS))
        durations.append(FRAME_MS)
        tick += 1

    for idx, (v, alt, phase) in enumerate(seq):
        cx, cy, cam = _pose(alt)
        # دود و آتش پشت موشک
        for _ in range(2):
            _spawn(parts, "smoke", cx + rnd.uniform(-5, 5), cy + NOZZLE + 4, rnd.uniform(-1.2, 1.2), rnd.uniform(2.2, 4.2), rnd.randint(9, 15), rnd.uniform(4, 7))
        if phase == "rise":
            gy = 282 + cam
            for _ in range(2):
                _spawn(parts, "smoke", cx + rnd.uniform(-14, 14), gy - 6, rnd.choice((-1, 1)) * rnd.uniform(1.6, 3.4), -rnd.uniform(0.1, 0.5), rnd.randint(12, 20), rnd.uniform(7, 12))
        if not hit and win and v >= target:
            hit = True
        _step_parts(parts)
        render(v, alt, phase)
    if capped:
        for _ in range(6):
            _step_parts(parts); render(top, 0.25 + math.log(top), "climb")
        render(top, 0.25 + math.log(top), "climb", banner=True)
        durations[-1] = 3500
    else:
        cx, cy, cam = _pose(0.25 + math.log(max(top, 1.0)))
        for _ in range(60):
            a = rnd.uniform(0, math.tau); sp_ = rnd.uniform(2.0, 9.0)
            _spawn(parts, "spark", cx, cy, math.cos(a) * sp_, math.sin(a) * sp_ - 1, rnd.randint(8, 16), rnd.uniform(1.4, 3.2), g=0.35)
        for i_ in range(18):
            a = rnd.uniform(0, math.tau); sp_ = rnd.uniform(2.0, 6.5)
            _spawn(parts, "debris", cx, cy, math.cos(a) * sp_, math.sin(a) * sp_ - 1.5, rnd.randint(14, 24), rnd.uniform(2, 4), g=0.4,
                   col=((232, 237, 247), (216, 52, 74), (127, 140, 168), (74, 82, 102))[i_ % 4], rot=rnd.uniform(0, 6), vr=rnd.uniform(-0.5, 0.5))
        for _ in range(14):
            a = rnd.uniform(0, math.tau); sp_ = rnd.uniform(0.5, 2.2)
            _spawn(parts, "smoke", cx, cy, math.cos(a) * sp_, math.sin(a) * sp_ - 0.6, rnd.randint(16, 26), rnd.uniform(12, 20))
        for age in range(12):
            _step_parts(parts)
            render(top, 0.25 + math.log(max(top, 1.0)), "boom", boom=age, rocket=False)
        render(top, 0.25 + math.log(max(top, 1.0)), "boom", boom=99, rocket=False, banner=True)
        durations[-1] = 3500
    anim_seconds = sum(durations[:-1]) / 1000.0
    return _finish(frames, durations), anim_seconds
