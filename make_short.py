#!/usr/bin/env python3
"""Fast-paced captioned vertical short (1080x1920) from a JSON script.
Usage: make_short.py script.json out.mp4

Scene fields: dur, text, sub (optional), big (bool), source (optional),
  type: "text" (default) | "stat" (uses num, a count-up number) | "list" (uses items[])
Wrap words in [brackets] to highlight them in the accent color.
"""
import json, sys, math, subprocess, os, tempfile, wave, struct, re, random
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
KR = 1

THEMES = {
    "tech": ((10, 14, 32), (40, 90, 230), (80, 210, 255)),
    "news": ((22, 12, 12), (190, 40, 40), (255, 205, 80)),
    "ent":  ((26, 8, 36), (200, 50, 170), (255, 140, 220)),
    "life": ((8, 26, 22), (28, 150, 100), (110, 232, 170)),
    "world": ((16, 14, 42), (110, 70, 225), (175, 155, 255)),
    "weather": ((8, 22, 42), (28, 128, 205), (120, 212, 255)),
    "brand": ((11, 17, 41), (40, 90, 230), (80, 210, 255)),
}
WEEK = "월화수목금토일"
_fc = {}
def font(path, size):
    k = (path, size)
    if k not in _fc:
        try: _fc[k] = ImageFont.truetype(path, size, index=KR)
        except Exception: _fc[k] = ImageFont.truetype(path, size)
    return _fc[k]

def ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3
def back(x):
    x = max(0.0, min(1.0, x)); c = 1.7; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2

def chunks(text):
    """-> paragraphs; each a list of space-separated chunks; each chunk a list of (segment, highlighted).
    Brackets may sit mid-chunk, e.g. "[독립 검증]은" -> highlight stops before the particle."""
    out = []
    for para in text.split("\n"):
        cur, hl = [], False
        for w in para.split(" "):
            segs, buf = [], ""
            for ch in w:
                if ch in "[]":
                    if buf: segs.append((buf, hl))
                    buf, hl = "", (ch == "[")
                else:
                    buf += ch
            if buf: segs.append((buf, hl))
            if segs: cur.append(segs)
        out.append(cur)
    return out

def layout(d, text, f, maxw):
    """-> lines; each a list of (segment, highlighted, width, glued_to_previous)."""
    sp = d.textlength(" ", font=f)
    lines = []
    for para in chunks(text):
        cur, curw = [], 0
        for ch in para:
            cw = sum(d.textlength(t, font=f) for t, _ in ch)
            if cur and curw + sp + cw > maxw:
                lines.append(cur); cur, curw = [], 0
            curw += (sp if cur else 0) + cw
            for k, (t, hl) in enumerate(ch):
                cur.append((t, hl, d.textlength(t, font=f), k > 0))
        lines.append(cur)
    return lines

def draw_words(d, lines, f, x0, y, lh, lt, start, accent, hlbox, stagger=0.035):
    sp = d.textlength(" ", font=f)
    # box is centered on the visual middle of the glyphs and never taller than the line pitch,
    # so it can't spill into the next line
    kb = d.textbbox((0, 0), "한글가TOP0", font=f)
    mid = (kb[1] + kb[3]) / 2
    padx, pady = int(f.size * 0.18), int(f.size * 0.12)
    half = min((lh - 14) / 2, (kb[3] - kb[1]) / 2 + pady)
    i = 0
    for ln in lines:
        xs, x = [], x0
        for n, (t, hl, ww, glue) in enumerate(ln):
            if n and not glue: x += sp
            xs.append(x); x += ww
        j = 0
        while j < len(ln):
            if not ln[j][1]:
                j += 1; continue
            s = j
            while j < len(ln) and ln[j][1]:
                j += 1
            wi = i + s
            p = max(0, min(1, (lt - start - wi * stagger) / 0.18))
            if p > 0:
                k = back((lt - start - wi * stagger) / 0.22)
                dy = int((1 - k) * 40)
                lpad = int(f.size * 0.04) if ln[s][3] else padx            # glued word before the run
                rpad = int(f.size * 0.04) if (j < len(ln) and ln[j][3]) else padx  # glued particle after
                bx0 = min(d.textbbox((xs[s], 0), ln[s][0], font=f)[0], xs[s]) - lpad
                bx1 = max(d.textbbox((xs[e], 0), ln[e][0], font=f)[2] for e in range(s, j)) + rpad
                bx1 = bx0 + (bx1 - bx0) * ease(p)
                d.rounded_rectangle((bx0, y + dy + mid - half, bx1, y + dy + mid + half), int(f.size * 0.16),
                                    fill=hlbox + (int(255 * min(1, p * 2)),))
        for n, (t, hl, ww, glue) in enumerate(ln):
            k = back((lt - start - i * stagger) / 0.22)
            a = int(255 * max(0, min(1, (lt - start - i * stagger) / 0.12)))
            dy = int((1 - k) * 40)
            d.text((xs[n], y + dy), t, font=f, fill=(255, 255, 255, a))
            i += 1
        y += lh
    return y, i

def background(theme, t, rnd):
    bg, c1, c2 = THEMES[theme]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img, "RGBA")
    for i, col in enumerate((c1, c2)):
        cx = W * (0.5 + 0.45 * math.sin(t * 1.1 + i * 2.1))
        cy = H * (0.5 + 0.4 * math.cos(t * 0.9 + i * 1.7))
        for r in range(760, 0, -60):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (int(16 * (1 - r / 760)),))
    # moving diagonal speed lines
    for j in range(7):
        y = (rnd[j] * H + t * 900 * (0.6 + rnd[j + 7])) % (H + 400) - 200
        d.line((0, y, W, y - 260), fill=(255, 255, 255, 14), width=3)
    return img

def ctext(d, text, f, cx, y, fill):
    d.text((cx - d.textlength(text, font=f) / 2, y), text, font=f, fill=fill)

def mtext(d, text, f, cx, cy, fill):
    """Draw text with its ink box centered exactly on (cx, cy)."""
    bb = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2), text, font=f, fill=fill)

def rtext(d, text, f, rx, y, fill):
    d.text((rx - d.textlength(text, font=f), y), text, font=f, fill=fill)

def wx_icon(d, kind, cx, cy, r, a):
    """Small weather glyphs: sun / partly / cloud / rain."""
    sun, cloud, drop = (255, 210, 80, a), (225, 232, 245, a), (110, 200, 255, a)
    def cl(x, y, s):
        d.ellipse((x - s * 1.0, y - s * 0.35, x + s * 0.1, y + s * 0.55), fill=cloud)
        d.ellipse((x - s * 0.45, y - s * 0.75, x + s * 0.55, y + s * 0.4), fill=cloud)
        d.ellipse((x + 0.0, y - s * 0.3, x + s * 1.0, y + s * 0.55), fill=cloud)
        d.rounded_rectangle((x - s * 0.8, y, x + s * 0.85, y + s * 0.55), int(s * 0.27), fill=cloud)
    if kind == "sun":
        d.ellipse((cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55), fill=sun)
        for k in range(8):
            ang = k * math.pi / 4
            d.line((cx + math.cos(ang) * r * 0.75, cy + math.sin(ang) * r * 0.75,
                    cx + math.cos(ang) * r * 1.0, cy + math.sin(ang) * r * 1.0), fill=sun, width=max(3, int(r * 0.12)))
    elif kind == "partly":
        d.ellipse((cx - r * 0.2, cy - r * 0.9, cx + r * 0.8, cy + r * 0.1), fill=sun)
        cl(cx - r * 0.05, cy + r * 0.15, r * 0.85)
    elif kind == "cloud":
        cl(cx, cy, r * 0.95)
    else:
        cl(cx, cy - r * 0.2, r * 0.9)
        for k in (-0.45, 0.0, 0.45):
            x = cx + k * r
            d.line((x, cy + r * 0.5, x - r * 0.12, cy + r * 0.85), fill=drop, width=max(3, int(r * 0.12)))

def wx_kind(txt):
    if "비" in txt or "눈" in txt: return "rain"
    if "흐림" in txt: return "cloud"
    if "구름" in txt: return "partly"
    return "sun"

def card(d, box, a=0.10):
    d.rounded_rectangle(box, 34, fill=(255, 255, 255, int(255 * a)))

def scene_date(d, sc, lt, c1, c2):
    y0 = 640
    f1, f2, f3 = font(FONT_R, 76), font(FONT_B, 170), font(FONT_B, 72)
    k = ease(lt / 0.3)
    ctext(d, sc["year"], f1, W / 2, y0 + int((1 - k) * 30), (255, 255, 255, int(220 * k)))
    lines = layout(d, sc["md"], f2, W)
    lw = sum(ww for _, _, ww, _ in lines[0]) + d.textlength(" ", font=f2) * sum(1 for t in lines[0][1:] if not t[3])
    draw_words(d, lines, f2, W / 2 - lw / 2, y0 + 120, 200, lt, 0.12, c2, c1, stagger=0.06)
    k3 = ease((lt - 0.45) / 0.3)
    ctext(d, sc["dow"], f3, W / 2, y0 + 360 + int((1 - k3) * 20), c2 + (int(255 * k3),))
    k4 = ease((lt - 0.7) / 0.3)
    ctext(d, sc.get("tag", ""), font(FONT_R, 44), W / 2, y0 + 500, (255, 255, 255, int(150 * k4)))
    return y0 + 560

def scene_top5(d, sc, lt, c1, c2):
    f = font(FONT_B, 92)
    y, _ = draw_words(d, layout(d, sc["text"], f, W - 180), f, 90, 340, 120, lt, 0, c2, c1)
    y += 30
    fh, fo, fn = font(FONT_B, 50), font(FONT_R, 32), font(FONT_B, 46)
    for j, it in enumerate(sc["items"]):
        st = 0.22 + j * 0.14
        k = back((lt - st) / 0.28)
        a = int(255 * max(0, min(1, (lt - st) / 0.14)))
        dx = int((1 - k) * 140)
        lines = layout(d, it["h"], fh, W - 330)[:2]
        hh = 66 * len(lines) + 46
        if j == 0:
            card(d, (70 + dx, y - 14, W - 70 + dx, y + hh + 6), 0.13 * a / 255)
        # rank badge
        bx, by = 100 + dx, y + 2
        if j == 0:
            d.ellipse((bx, by, bx + 72, by + 72), fill=c2 + (a,))
            mtext(d, "1", fn, bx + 36, by + 36, (10, 14, 30, a))
        else:
            d.ellipse((bx, by, bx + 72, by + 72), outline=(255, 255, 255, int(a * 0.7)), width=4)
            mtext(d, str(j + 1), fn, bx + 36, by + 36, (255, 255, 255, a))
        draw_words(d, lines, fh, 210 + dx, y, 66, lt, st + 0.05, c2, c1, stagger=0.012)
        d.text((210 + dx, y + 66 * len(lines) + 4), it["src"], font=fo, fill=(255, 255, 255, int(a * 0.55)))
        y += hh + 34
    return y

def scene_detail(d, sc, lt, c1, c2, img):
    top = 330
    f = font(FONT_B, 76)
    lines = layout(d, sc["text"], f, W - 240)
    # measure card height first
    fs = font(FONT_R, 50)
    bl = [layout(d, b, fs, W - 300) for b in sc["bullets"][:3]]
    media_h = 0
    media = None
    if sc.get("media") and os.path.exists(sc["media"]):
        media = Image.open(sc["media"]).convert("RGB")
        mw = W - 240
        media_h = int(min(560, mw * media.height / media.width))
    h = 60 + len(lines) * 102 + 30 + (media_h + 40 if media else 0) + sum(len(b) * 70 + 26 for b in bl) + 110
    card(d, (70, top, W - 70, top + h), 0.09)
    y, _ = draw_words(d, lines, f, 120, top + 50, 102, lt, 0, c2, c1)
    y += 30
    if media:
        k = ease((lt - 0.3) / 0.35)
        mw = W - 240
        m = media.resize((mw, int(mw * media.height / media.width)), Image.LANCZOS)
        if m.height > media_h:
            off = (m.height - media_h) // 2
            m = m.crop((0, off, mw, off + media_h))
        mask = Image.new("L", m.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, m.width - 1, m.height - 1), 24, fill=int(255 * k))
        img.paste(m, (120, int(y + (1 - k) * 30)), mask)
        y += media_h + 40
    for j, b in enumerate(bl):
        st = 0.45 + j * 0.3
        k = ease((lt - st) / 0.3)
        a = int(255 * k)
        d.ellipse((124, y + 26, 142, y + 44), fill=c2 + (a,))
        for ln in b:
            txt = "".join(("" if (g or n == 0) else " ") + w for n, (w, _, _, g) in enumerate(ln))
            d.text((170 + int((1 - k) * 40), y), txt, font=fs, fill=(255, 255, 255, a))
            y += 70
        y += 26
    k = ease((lt - 1.2) / 0.3)
    rtext(d, "출처: " + sc["src"], font(FONT_R, 34), W - 120, top + h - 70, (255, 255, 255, int(160 * k)))
    return top + h

def scene_weather(d, sc, lt, c1, c2):
    f = font(FONT_B, 88)
    y, _ = draw_words(d, layout(d, sc["text"], f, W - 180), f, 90, 330, 116, lt, 0, c2, c1)
    k = ease((lt - 0.2) / 0.3)
    d.text((90, y + 22), sc["subtitle"], font=font(FONT_R, 44), fill=c2 + (int(255 * k),))
    y += 110
    cols = [(90, "도시", "l"), (330, "날씨", "c"), (530, sc["tlabel"], "c"), (690, "강수확률", "c"), (W - 90, "강수량", "r")]
    fh = font(FONT_R, 34)
    for x, t, al in cols:
        (ctext if al == "c" else rtext if al == "r" else (lambda d_, t_, f_, x_, y_, c_: d_.text((x_, y_), t_, font=f_, fill=c_)))(
            d, t, fh, x, y, (255, 255, 255, int(150 * k)))
    y += 56
    d.line((90, y, W - 90, y), fill=(255, 255, 255, int(70 * k)), width=2)
    y += 14
    fc, fv = font(FONT_B, 50), font(FONT_B, 44)
    rh = 78
    for j, r in enumerate(sc["rows"]):
        st = 0.3 + j * 0.05
        kk = back((lt - st) / 0.25)
        a = int(255 * max(0, min(1, (lt - st) / 0.12)))
        dy = int((1 - kk) * 30)
        yy = y + j * rh + dy
        if j % 2 == 0:
            d.rounded_rectangle((76, yy - 6, W - 76, yy + rh - 10), 18, fill=(255, 255, 255, int(a * 0.05)))
        d.text((90, yy + 4), r["city"], font=fc, fill=(255, 255, 255, a))
        wx_icon(d, wx_kind(r["wx"]), 262, yy + 34, 26, a)
        d.text((300, yy + 16), r["wx"], font=font(FONT_R, 32), fill=(255, 255, 255, int(a * 0.85)))
        ctext(d, f'{r["t"]}°', fv, 530, yy + 6, (255, 255, 255, a))
        wet = r["pop"] >= 60
        ctext(d, f'{r["pop"]}%', fv, 690, yy + 6, (c2 if wet else (255, 255, 255)) + (a,))
        rtext(d, r["rain"], fv, W - 90, yy + 6, (c2 if r["rain"] != "-" else (255, 255, 255)) + (a if r["rain"] != "-" else int(a * 0.5),))
    y += len(sc["rows"]) * rh + 20
    k = ease((lt - 1.0) / 0.3)
    rtext(d, "출처: " + sc["src"], font(FONT_R, 32), W - 90, y, (255, 255, 255, int(160 * k)))
    if sc.get("note"):
        rtext(d, sc["note"], font(FONT_R, 28), W - 90, y + 46, (255, 255, 255, int(120 * k)))
    return y

def render_frame(sc, theme, label, lt, gt, idx, total, rnd):
    theme = sc.get("theme", theme); label = sc.get("label", label)
    bg, c1, c2 = THEMES[theme]
    # punch-in zoom at scene start
    z = 1 + 0.06 * (1 - ease(lt / 0.25))
    img = background(theme, gt, rnd)
    d = ImageDraw.Draw(img, "RGBA")

    fl = font(FONT_R, 44)
    if sc.get("type") != "date":
      d.rounded_rectangle((70, 140, 70 + d.textlength(label, font=fl) + 60, 230), 45, fill=c1 + (235,))
      d.text((100, 152), label, font=fl, fill="white")
    seg = (W - 140) / total
    for i in range(total):
        x0 = 70 + i * seg
        fill = 230 if i < idx else 60
        d.rounded_rectangle((x0 + 3, 270, x0 + seg - 3, 280), 5, fill=(255, 255, 255, fill))
        if i == idx:
            p = min(1, lt / sc["dur"])
            d.rounded_rectangle((x0 + 3, 270, x0 + 3 + (seg - 6) * p, 280), 5, fill=(255, 255, 255, 230))

    typ = sc.get("type", "text")
    maxw = W - 180
    y = 0
    if typ == "stat":
        target = sc["num"]
        m = re.match(r"([^\d]*)([\d.,]+)(.*)", target)
        k = ease(lt / 0.7)
        if m:
            pre, num, post = m.groups()
            dec = len(num.split(".")[1]) if "." in num else 0
            val = float(num.replace(",", "")) * k
            shown = f"{pre}{val:,.{dec}f}{post}"
        else:
            shown = target
        fn = font(FONT_B, 230)
        tw = d.textlength(shown, font=fn)
        d.text(((W - tw) / 2, 600), shown, font=fn, fill=c2 + (255,))
        f = font(FONT_B, 76)
        lines = layout(d, sc["text"], f, maxw)
        y, _ = draw_words(d, lines, f, 90, 940, 104, lt, 0.15, c2, c1)
    elif typ == "date":
        y = scene_date(d, sc, lt, c1, c2)
    elif typ == "top5":
        y = scene_top5(d, sc, lt, c1, c2)
    elif typ == "detail":
        y = scene_detail(d, sc, lt, c1, c2, img)
    elif typ == "weather":
        y = scene_weather(d, sc, lt, c1, c2)
    elif typ == "list":
        f = font(FONT_B, 84)
        lines = layout(d, sc["text"], f, maxw)
        y, _ = draw_words(d, lines, f, 90, 480, 114, lt, 0, c2, c1)
        fi = font(FONT_R, 54)
        y += 50
        for j, it in enumerate(sc["items"]):
            st = 0.25 + j * 0.28
            k = back((lt - st) / 0.25)
            a = int(255 * max(0, min(1, (lt - st) / 0.12)))
            dx = int((1 - k) * 120)
            d.rounded_rectangle((90 + dx, y, W - 90 + dx, y + 110), 22, fill=(255, 255, 255, int(a * 0.10)))
            d.ellipse((120 + dx, y + 38, 154 + dx, y + 72), fill=c2 + (a,))
            d.text((180 + dx, y + 20), it, font=fi, fill=(255, 255, 255, a))
            y += 135
    else:
        size = 112 if sc.get("big") else 88
        f = font(FONT_B, size)
        lh = int(size * 1.32)
        lines = layout(d, sc["text"], f, maxw)
        y0 = (H - lh * len(lines)) // 2 - 120
        y, n = draw_words(d, lines, f, 90, y0, lh, lt, 0, c2, c1)
    if sc.get("sub"):
        fs = font(FONT_R, 52)
        y += 36
        lines = layout(d, sc["sub"], fs, maxw)
        start = 0.35 if typ != "list" else 0.25 + len(sc.get("items", [])) * 0.28
        k = ease((lt - start) / 0.25)
        for ln in lines:
            txt = "".join(("" if (g or n == 0) else " ") + w for n, (w, _, _, g) in enumerate(ln))
            d.text((90, y + int((1 - k) * 20)), txt, font=fs, fill=c2 + (int(255 * k),))
            y += 74
    if sc.get("source"):
        d.text((90, H - 250), "출처: " + sc["source"], font=font(FONT_R, 36), fill=(255, 255, 255, 150))

    # white flash on cut
    fa = 1 - lt / 0.08
    if fa > 0 and idx > 0:
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.35 * fa)
    if z > 1.001:
        nw, nh = int(W * z), int(H * z)
        img = img.resize((nw, nh), Image.BILINEAR).crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))
    return img

def music(path, dur, cuts):
    sr, bpm = 44100, 124
    beat = 60 / bpm
    roots = [110.0, 87.31, 130.81, 98.0]
    rng = random.Random(7)
    noise = [rng.uniform(-1, 1) for _ in range(4096)]
    out = bytearray()
    for n in range(int(sr * dur)):
        t = n / sr
        bar = int(t / (beat * 4)) % 4
        r = roots[bar]
        tb = t % beat
        kick = math.sin(2 * math.pi * (50 + 90 * math.exp(-30 * tb)) * tb) * math.exp(-9 * tb)
        th = t % (beat / 2)
        hat = noise[n % 4096] * math.exp(-60 * th) * (0.6 if int(t / (beat / 2)) % 2 else 0.3)
        bass_t = t % (beat / 2)
        bass = math.sin(2 * math.pi * r * t) * math.exp(-5 * bass_t)
        pad = sum(math.sin(2 * math.pi * r * m * 2 * t) for m in (1, 1.26, 1.5)) / 3
        whoosh = 0.0
        for c in cuts:
            dt = t - c + 0.12
            if 0 <= dt < 0.2:
                whoosh += noise[(n * 3) % 4096] * math.sin(math.pi * dt / 0.2) * 0.5
        env = min(1, t / 0.4, (dur - t) / 1.0)
        v = (0.45 * kick + 0.12 * hat + 0.22 * bass + 0.08 * pad + 0.25 * whoosh) * env
        out += struct.pack("<h", int(max(-1, min(1, v)) * 30000))
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(bytes(out))

OUTRO_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "outro_logo.png")
OUTRO_DUR = 2.6

def outro_base():
    """Square logo centered on a 9:16 canvas; top/bottom extended by continuing the logo's own gradient."""
    logo = Image.open(OUTRO_LOGO).convert("RGB").resize((W, W), Image.LANCZOS)
    top = [sum(logo.getpixel((x, 0))[i] for x in range(0, W, 8)) / len(range(0, W, 8)) for i in range(3)]
    bot = [sum(logo.getpixel((x, W - 1))[i] for x in range(0, W, 8)) / len(range(0, W, 8)) for i in range(3)]
    y0 = (H - W) // 2
    canvas = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(canvas)
    for y in range(H):
        t = (y - y0) / (W - 1)  # 0 at logo top, 1 at logo bottom; extrapolated outside
        c = tuple(int(round(max(0, min(255, top[i] + (bot[i] - top[i]) * t)))) for i in range(3))
        d.line((0, y, W, y), fill=c)
    # feathered paste so the seam is invisible
    mask = Image.new("L", (W, W), 255)
    md = ImageDraw.Draw(mask)
    fe = 40
    for i in range(fe):
        a = int(255 * (i + 1) / fe)
        md.line((0, i, W, i), fill=a); md.line((0, W - 1 - i, W, W - 1 - i), fill=a)
    canvas.paste(logo, (0, y0), mask)
    return canvas

def outro_frame(base, last, lt):
    k = ease(lt / 0.9)
    z = 1.05 - 0.05 * k                       # slow settle-in
    nw, nh = int(W * z), int(H * z)
    img = base.resize((nw, nh), Image.LANCZOS).crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))
    if lt < 0.45 and last is not None:        # crossfade from the last scene
        img = Image.blend(last, img, ease(lt / 0.45))
    return img

def main(src, out):
    spec = json.load(open(src, encoding="utf-8"))
    theme, label, scenes = spec["theme"], spec["label"], spec["scenes"]
    total = sum(s["dur"] for s in scenes)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(out)))
    rng = random.Random(3); rnd = [rng.random() for _ in range(14)]
    n, gt, cuts, last = 0, 0.0, [], None
    for i, sc in enumerate(scenes):
        if i: cuts.append(gt)
        for f in range(int(round(sc["dur"] * FPS))):
            lt = f / FPS
            last = render_frame(sc, theme, label, lt, gt + lt, i, len(scenes), rnd)
            last.save(f"{tmp}/{n:05d}.jpg", quality=90)
            n += 1
        gt += sc["dur"]
    if os.path.exists(OUTRO_LOGO):
        cuts.append(gt); base = outro_base()
        for f in range(int(round(OUTRO_DUR * FPS))):
            outro_frame(base, last, f / FPS).save(f"{tmp}/{n:05d}.jpg", quality=92)
            n += 1
        total += OUTRO_DUR
    music(f"{tmp}/m.wav", total, cuts)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{tmp}/%05d.jpg",
                    "-i", f"{tmp}/m.wav", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow",
                    "-crf", "27", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out], check=True)
    subprocess.run(["rm", "-rf", tmp])
    print(out, f"{total:.1f}s")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
