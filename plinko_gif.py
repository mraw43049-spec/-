"""ساخت گیف انیمیشن پلینکو (توپ از میخ‌ها می‌افته و تو خانه‌ی نتیجه می‌شینه) با Pillow."""
import io
import math

from PIL import Image, ImageDraw, ImageFont

LW, LH = 360, 500          # مختصات منطقی
OUT = 1.5                  # ضریب بزرگ‌نمایی خروجی
OW, OH = int(LW * OUT), int(LH * OUT)   # اندازه‌ی نهایی گیف (۵۴۰×۷۵۰)
SS = 2                     # سوپرسمپل برای لبه‌های صاف
ROWS = 14


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow قدیمی
        return ImageFont.load_default()


def _bucket_colors(m):
    if m >= 10:
        return (232, 72, 150), (150, 36, 108)
    if m >= 4:
        return (200, 84, 214), (120, 48, 150)
    if m >= 1.5:
        return (150, 100, 232), (88, 62, 160)
    if m >= 1:
        return (62, 190, 190), (30, 112, 124)
    if m > 0:
        return (88, 120, 150), (50, 70, 96)
    return (70, 78, 104), (38, 42, 62)


def _fmt(m):
    return f"{m:g}x"


class _Geom:
    def __init__(self, rows):
        self.rows = rows
        self.s = (LW - 22) / (rows + 1)
        self.top = 66
        self.dy = 23.5
        self.pr = 3.6
        self.br = 9.2
        self.b_top = self.top + (rows - 1) * self.dy + 16
        self.b_h = 34

    def peg(self, n, k):
        return (LW / 2 + (k - n / 2) * self.s, self.top + n * self.dy)

    def slot_x(self, k):
        return LW / 2 + (k - self.rows / 2) * self.s


def _background(g, mult):
    img = Image.new("RGB", (LW * SS, LH * SS), (10, 13, 30))
    d = ImageDraw.Draw(img)
    # گرادیان عمودی + هاله‌ی مرکزی
    for y in range(LH * SS):
        t = y / (LH * SS)
        d.line([(0, y), (LW * SS, y)], fill=(int(12 + 10 * t), int(14 + 6 * t), int(36 - 8 * t)))
    halo = Image.new("RGBA", (LW * SS, LH * SS), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    cx, cy = LW * SS / 2, (g.top + 6 * g.dy) * SS
    for i in range(14, 0, -1):
        rr = i * 15 * SS
        hd.ellipse([cx - rr * 0.9, cy - rr * 1.15, cx + rr * 0.9, cy + rr * 1.0], fill=(70, 60, 150, 5))
    img = Image.alpha_composite(img.convert("RGBA"), halo)
    d = ImageDraw.Draw(img)
    # عنوان
    d.text((LW * SS / 2, 26 * SS), "PLINKO", font=_font(30 * SS), fill=(255, 214, 102), anchor="mm")
    for n in range(g.rows):
        for k in range(n + 1):
            x, y = g.peg(n, k)
            _peg(d, x, y, g, 0.0)
    for k in range(g.rows + 1):
        _bucket(d, g, k, mult[k], False)
    return img


def _peg(d, x, y, g, glow):
    r = g.pr * SS
    x *= SS; y *= SS
    if glow > 0:
        for i in range(5, 0, -1):
            a = int(60 * glow * (6 - i) / 5)
            rr = r + i * 2.2 * SS * glow
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 220, 130, a))
    col = (255, 238, 190) if glow > 0.3 else (176, 150, 255)
    d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    d.ellipse([x - r * 0.55, y - r * 0.6, x + r * 0.1, y - r * 0.05], fill=(255, 255, 255))


def _bucket(d, g, k, m, hot):
    top, bot = _bucket_colors(m)
    w = (g.s - 2.6) * SS
    cx = g.slot_x(k) * SS
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = g.b_top * SS, (g.b_top + g.b_h) * SS
    if hot:
        for i in range(6, 0, -1):
            d.rounded_rectangle([x0 - i * 2 * SS, y0 - i * 2 * SS, x1 + i * 2 * SS, y1 + i * 2 * SS],
                                radius=8 * SS, fill=(255, 255, 255, 18))
    steps = 12
    for i in range(steps):
        t = i / (steps - 1)
        c = tuple(int(top[j] * (1 - t) + bot[j] * t) for j in range(3))
        d.rounded_rectangle([x0, y0 + (y1 - y0) * i / steps, x1, y0 + (y1 - y0) * (i + 1) / steps + 1], radius=0, fill=c) if 0 < i < steps - 1 else None
    d.rounded_rectangle([x0, y0, x1, y1], radius=7 * SS, outline=(255, 255, 255) if hot else tuple(min(255, c + 40) for c in top), width=(2 if hot else 1) * SS)
    # پرکردن بدنه با گرادیان داخل گوشه‌های گرد
    body = Image.new("RGBA", (int(x1 - x0) + 2, int(y1 - y0) + 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    h = int(y1 - y0)
    for yy in range(h):
        t = yy / max(1, h - 1)
        bd.line([(0, yy), (body.width, yy)], fill=tuple(int(top[j] * (1 - t) + bot[j] * t) for j in range(3)) + (255,))
    mask = Image.new("L", body.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, body.width - 2, h], radius=7 * SS, fill=255)
    d._image.paste(body, (int(x0), int(y0)), mask)
    d.rounded_rectangle([x0, y0, x1, y1], radius=7 * SS, outline=(255, 255, 255) if hot else tuple(min(255, c + 50) for c in top), width=(2 if hot else 1) * SS)
    fs = 9.5 if len(_fmt(m)) <= 3 else (8.3 if len(_fmt(m)) == 4 else 7.2)
    d.text((cx, (y0 + y1) / 2), _fmt(m), font=_font(int(fs * SS)), fill=(255, 255, 255), anchor="mm")


def _ball(img, x, y, g, trail):
    d = ImageDraw.Draw(img)
    r = g.br * SS
    for i, (tx, ty) in enumerate(trail):
        a = int(70 * (i + 1) / (len(trail) + 1))
        rr = r * (0.45 + 0.4 * (i + 1) / (len(trail) + 1))
        d.ellipse([tx * SS - rr, ty * SS - rr, tx * SS + rr, ty * SS + rr], fill=(255, 190, 70, a))
    X, Y = x * SS, y * SS
    for i in range(5, 0, -1):
        rr = r + i * 2.4 * SS
        d.ellipse([X - rr, Y - rr, X + rr, Y + rr], fill=(255, 190, 60, 16))
    d.ellipse([X - r, Y - r, X + r, Y + r], fill=(235, 140, 20))
    d.ellipse([X - r * 0.9, Y - r * 0.9, X + r * 0.7, Y + r * 0.7], fill=(255, 190, 50))
    d.ellipse([X - r * 0.62, Y - r * 0.7, X - r * 0.05, Y - r * 0.15], fill=(255, 245, 200))


def build_gif(path, mult_table, amount, payout, rows=ROWS):
    """path: لیست ۰/۱ به طول rows ؛ خروجی: bytes گیف."""
    g = _Geom(rows)
    slot = sum(path)
    mult = mult_table
    bg = _background(g, mult)
    # نقاط تماس
    pts = []
    k = 0
    for i in range(rows):
        x, y = g.peg(i, k)
        pts.append((x, y - (g.pr + g.br - 1), i))
        k += path[i]
    waypoints = [(LW / 2, g.top - 40, None)] + pts
    last = (g.slot_x(slot), g.b_top + g.b_h * 0.52, None)
    waypoints.append(last)

    frames, durations = [], []
    trail = []
    flash = {}

    def emit(x, y, dur, hot=False, banner=False):
        im = bg.copy()
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for (n, kk), gl in list(flash.items()):
            px, py = g.peg(n, kk)
            _peg(od, px, py, g, gl)
        if hot:
            _bucket(od, g, slot, mult[slot], True)
        _ball(ov, x, y, g, trail)
        if banner:
            _banner(od, mult[slot], amount, payout)
        im = Image.alpha_composite(im, ov).convert("RGB").resize((OW, OH), Image.LANCZOS)
        frames.append(im)
        durations.append(dur)
        trail.append((x, y))
        if len(trail) > 4:
            trail.pop(0)
        for key in list(flash):
            flash[key] -= 0.34
            if flash[key] <= 0:
                del flash[key]

    pk = 0
    for si in range(len(waypoints) - 1):
        x0, y0, _ = waypoints[si]
        x1, y1, pidx = waypoints[si + 1]
        nf = 7 if si == 0 else (5 if si < len(waypoints) - 2 else 8)
        hop = 5 if 0 < si < len(waypoints) - 2 else 0
        for f in range(1, nf + 1):
            t = f / nf
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t * t - hop * 4 * t * (1 - t)
            emit(x, y, 38)
        if pidx is not None:
            n = pidx
            kk = sum(path[:pidx])
            flash[(n, kk)] = 1.0
    x, y, _ = waypoints[-1]
    for _ in range(3):
        emit(x, y, 90, hot=True)
    emit(x, y, 3000, hot=True, banner=True)

    # پالت مشترک برای همه‌ی فریم‌ها: بدون دیتر، ثابت و تمیز؛ ضمناً Pillow فقط ناحیه‌ی تغییرکرده رو ذخیره می‌کنه
    n = len(frames)
    sample = [frames[i] for i in sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})]
    mosaic = Image.new("RGB", (OW, OH * len(sample)))
    for i, fr in enumerate(sample):
        mosaic.paste(fr, (0, i * OH))
    pal = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    qframes = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
    buf = io.BytesIO()
    qframes[0].save(buf, format="GIF", save_all=True, append_images=qframes[1:], duration=durations, loop=0, optimize=False, disposal=1)
    return buf.getvalue()


def _banner(d, m, amount, pay):
    W, H = LW * SS, LH * SS
    y = (LH - 38) * SS
    d.rounded_rectangle([20 * SS, y - 22 * SS, W - 20 * SS, y + 26 * SS], radius=14 * SS, fill=(8, 10, 24, 225), outline=(255, 214, 102, 255), width=2 * SS)
    d.text((W / 2, y - 6 * SS), f"x{m:g}", font=_font(26 * SS), fill=(255, 214, 102), anchor="mm")
    d.text((W / 2, y + 14 * SS), f"{pay:,}", font=_font(14 * SS), fill=(255, 255, 255), anchor="mm")
