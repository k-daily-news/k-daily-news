#!/usr/bin/env python3
"""K.Daily.News profile image, 1:1, text kept inside the circular crop."""
import math, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT = sys.argv[1]
OUT = sys.argv[2]
S = 2160                      # supersampled; saved at 1080
LINES = ["K.", "Daily.", "News."]
BG_TOP, BG_BOT = (34, 88, 196), (16, 46, 132)
ACCENT = (255, 222, 80)
WHITE = (255, 255, 255)
SAFE = 0.80                   # text must sit within 80% of the circle radius

def block(size):
    f = ImageFont.truetype(FONT, size)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lh = int(size * 0.98)
    boxes = [d.textbbox((0, i * lh), t, font=f) for i, t in enumerate(LINES)]
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
    return f, lh, boxes, (x0, y0, x1, y1)

def fits(size):
    f, lh, boxes, (x0, y0, x1, y1) = block(size)
    ox, oy = S / 2 - (x0 + x1) / 2, S / 2 - (y0 + y1) / 2
    r = S / 2 * SAFE
    for b in boxes:
        for cx, cy in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])):
            if math.hypot(cx + ox - S / 2, cy + oy - S / 2) > r:
                return None
    return f, lh, ox, oy

lo, hi = 100, 1200
while hi - lo > 2:
    mid = (lo + hi) // 2
    if fits(mid): lo = mid
    else: hi = mid
f, lh, ox, oy = fits(lo)

img = Image.new("RGB", (S, S))
px = img.load()
for y in range(S):
    t = y / S
    c = tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3))
    for x in range(S):
        px[x, y] = c
glow = Image.new("RGB", (S, S), (0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((S * 0.15, S * 0.10, S * 0.95, S * 0.90), fill=(80, 145, 240))
glow = glow.filter(ImageFilter.GaussianBlur(S * 0.12))
img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.45)

d = ImageDraw.Draw(img)
for i, t in enumerate(LINES):
    word, dot = t[:-1], t[-1]
    x, y = ox, oy + i * lh
    d.text((x, y), word, font=f, fill=WHITE)
    d.text((x + d.textlength(word, font=f), y), dot, font=f, fill=ACCENT)

img.resize((1080, 1080), Image.LANCZOS).save(OUT)

# circle-crop preview to check nothing is clipped
prev = img.resize((540, 540), Image.LANCZOS)
mask = Image.new("L", (540, 540), 0)
ImageDraw.Draw(mask).ellipse((0, 0, 539, 539), fill=255)
canvas = Image.new("RGB", (540, 540), (240, 240, 240))
canvas.paste(prev, (0, 0), mask)
canvas.save(OUT.replace(".png", "_circle_preview.png"))
print("font size", lo // 2, "px at 1080")
