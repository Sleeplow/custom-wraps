#!/usr/bin/env python3
"""Generate the "Sleeplow" custom wrap for every Tesla template in this repo.

The Tesla wrap textures are UV layouts: the car body is unwrapped flat into a
single square PNG. For every model except the Cybertruck the layout is the same
family - the car runs vertically down the middle of the texture (hood at the
top, trunk at the bottom) and the two flanks are unwrapped as vertical strips
along the left and right edges of the image.

That means side lettering has to be drawn rotated 90 degrees, and the two sides
are mirrored relative to each other:

    left strip   -> artwork rotated clockwise  (texture top = front of the car)
    right strip  -> artwork rotated counter-cw (texture top = front of the car)

The Cybertruck uses a different layout: the two flanks are horizontal bands, the
bottom one upright and the top one flipped vertically.

Both conventions were derived from the wraps Tesla ships in this repo
(model3/example/Rudi.png and cybertruck/example/Graffiti_green.png).

Usage:
    python3 tools/sleeplow_wrap.py            # write sleeplow/<model>/Sleeplow.png
    python3 tools/sleeplow_wrap.py --model modely
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sleeplow"
FONT_CACHE = ROOT / ".fontcache"

WORDMARK = "SLEEPLOW"
TAGLINE = "NIGHT DIVISION"

FONTS = {
    "display": (
        "Kanit-BlackItalic.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/kanit/Kanit-BlackItalic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "label": (
        "ArchivoBlack-Regular.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
}

# Night-sky palette used for the whole texture.
SKY = [
    (0.00, (5, 6, 14)),
    (0.30, (10, 14, 38)),
    (0.55, (23, 16, 62)),
    (0.78, (44, 15, 70)),
    (1.00, (12, 10, 30)),
]
# Wordmark gradient, top (roof side) to bottom (sill side) of the lettering.
INK = [
    (0.00, (236, 253, 255)),
    (0.22, (125, 227, 252)),
    (0.48, (56, 160, 248)),
    (0.72, (129, 103, 241)),
    (1.00, (232, 74, 193)),
]
CYAN = (56, 208, 248)
MAGENTA = (226, 70, 190)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    name, url, fallback = FONTS[kind]
    path = FONT_CACHE / name
    if not path.exists():
        FONT_CACHE.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
            if len(data) < 10000:
                raise ValueError("suspiciously small font download")
            path.write_bytes(data)
        except Exception as exc:  # offline -> degrade instead of failing
            print(f"  ! could not fetch {name} ({exc}); using {fallback}", file=sys.stderr)
            return ImageFont.truetype(fallback, size)
    return ImageFont.truetype(str(path), size)


def ramp(stops, t: float):
    t = min(max(t, 0.0), 1.0)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            k = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
    return stops[-1][1]


def gradient(size, stops, horizontal=False) -> Image.Image:
    w, h = size
    n = w if horizontal else h
    strip = Image.new("RGB", (n, 1))
    px = strip.load()
    for i in range(n):
        px[i, 0] = ramp(stops, i / max(n - 1, 1))
    strip = strip if horizontal else strip.rotate(-90, expand=True)
    return strip.resize((w, h), Image.BILINEAR)


def fit_font(kind: str, text: str, box_w: int, box_h: int, tracking: float = 0.0):
    """Largest font size whose rendered text fits in box_w x box_h."""
    lo, hi = 8, max(16, box_h * 4)
    best = ImageFont.truetype(str(FONT_CACHE / FONTS[kind][0]), 8) if (FONT_CACHE / FONTS[kind][0]).exists() else font(kind, 8)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(kind, mid)
        w, h = measure(f, text, tracking)
        if w <= box_w and h <= box_h:
            best, lo = f, mid + 1
        else:
            hi = mid - 1
    return best


def measure(f: ImageFont.FreeTypeFont, text: str, tracking: float = 0.0):
    total = 0
    top, bottom = None, None
    for ch in text:
        bb = f.getbbox(ch)
        total += f.getlength(ch) + tracking * f.size
        if bb[3] > bb[1]:
            top = bb[1] if top is None else min(top, bb[1])
            bottom = bb[3] if bottom is None else max(bottom, bb[3])
    total -= tracking * f.size
    bb = f.getbbox(text)
    return int(max(total, bb[2] - bb[0])), int((bottom or bb[3]) - (top or bb[1]))


def draw_tracked(d: ImageDraw.ImageDraw, xy, text, f, fill, tracking: float = 0.0):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking * f.size


def text_mask(text: str, f: ImageFont.FreeTypeFont, tracking: float = 0.0, pad: int = 0):
    w, h = measure(f, text, tracking)
    img = Image.new("L", (w + 2 * pad + f.size, h + 2 * pad + f.size), 0)
    d = ImageDraw.Draw(img)
    bb = f.getbbox(text)
    draw_tracked(d, (pad - bb[0], pad - bb[1]), text, f, 255, tracking)
    return img.crop(img.getbbox() or (0, 0, 1, 1))


def dilate(mask: Image.Image, radius: int) -> Image.Image:
    out = mask
    step = 5
    while radius > 0:
        k = min(step, radius * 2 + 1)
        k = k if k % 2 else k - 1
        out = out.filter(ImageFilter.MaxFilter(k))
        radius -= k // 2
    return out


def glow(mask: Image.Image, colour, radius: int, strength: float) -> Image.Image:
    blurred = mask.filter(ImageFilter.GaussianBlur(radius))
    blurred = blurred.point(lambda v: int(min(255, v * strength)))
    img = Image.new("RGBA", mask.size, colour + (0,))
    img.putalpha(blurred)
    return img


# --------------------------------------------------------------------------
# the side artwork
# --------------------------------------------------------------------------
def side_art(length: int, depth: int, ss: int = 3) -> Image.Image:
    """Horizontal artwork for one flank: `length` runs nose->tail, `depth` is
    the height of the panel. Returned upright and readable."""
    W, H = length * ss, depth * ss
    art = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # --- lay the block out ---------------------------------------------
    f = fit_font("display", WORDMARK, int(W * 0.79), int(H * 0.52), tracking=0.012)
    word = text_mask(WORDMARK, f, tracking=0.012)

    bar_h = max(2, int(H * 0.034))
    gap_bar = int(H * 0.070)
    gap_tag = int(H * 0.055)
    tf = fit_font("label", TAGLINE, int(W * 0.52), int(H * 0.10), tracking=0.34)
    tag = text_mask(TAGLINE, tf, tracking=0.34)

    block_h = word.height + gap_bar + bar_h + gap_tag + tag.height
    top = (H - block_h) // 2
    wx = (W - word.width) // 2
    wy = top

    canvas_word = Image.new("L", (W, H), 0)
    canvas_word.paste(word, (wx, wy))

    # --- neon bloom behind the letters ----------------------------------
    art.alpha_composite(glow(canvas_word, MAGENTA, int(H * 0.090), 1.6))
    art.alpha_composite(glow(canvas_word, CYAN, int(H * 0.042), 1.8))

    # --- dark keyline so the lettering reads on any background ----------
    keyline = dilate(canvas_word, max(2, int(H * 0.018)))
    dark = Image.new("RGBA", (W, H), (7, 10, 28, 0))
    dark.putalpha(keyline.point(lambda v: int(v * 0.94)))
    art.alpha_composite(dark)

    # --- chrome gradient, mapped to the height of the lettering ---------
    fill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fill.paste(gradient((word.width, word.height), INK).convert("RGBA"), (wx, wy))
    fill.putalpha(canvas_word)
    art.alpha_composite(fill)

    # a bright band across the upper third of the glyphs
    sheen_shape = gradient(
        (word.width, word.height),
        [(0.00, (255, 255, 255)), (0.26, (255, 255, 255)), (0.40, (0, 0, 0)), (1.00, (0, 0, 0))],
    ).convert("L")
    sheen = Image.new("L", (W, H), 0)
    sheen.paste(sheen_shape, (wx, wy))
    sheen = Image.composite(sheen, Image.new("L", (W, H), 0), canvas_word)
    hi = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    hi.putalpha(sheen.point(lambda v: int(v * 0.42)))
    art.alpha_composite(hi)

    # --- speed line, running the full length of the panel ---------------
    line_y = wy + word.height + gap_bar
    bar = gradient((W, bar_h), [(0.0, CYAN), (0.55, (120, 130, 250)), (1.0, MAGENTA)], horizontal=True).convert("RGBA")
    fade = gradient(
        (W, bar_h),
        [(0.0, (0, 0, 0)), (0.07, (255, 255, 255)), (0.92, (255, 255, 255)), (1.0, (0, 0, 0))],
        horizontal=True,
    ).convert("L")
    bar.putalpha(fade)
    art.alpha_composite(glow(bar.getchannel("A"), CYAN, int(H * 0.045), 1.5), (0, line_y))
    art.alpha_composite(bar, (0, line_y))

    # thin second rule, offset like a racing stripe
    thin_h = max(1, int(H * 0.011))
    t_fade = gradient(
        (W, thin_h),
        [(0.0, (0, 0, 0)), (0.22, (215, 215, 215)), (0.68, (80, 80, 80)), (1.0, (0, 0, 0))],
        horizontal=True,
    ).convert("L")
    t_col = Image.new("RGBA", (W, thin_h), CYAN + (0,))
    t_col.putalpha(t_fade)
    art.alpha_composite(t_col, (0, line_y + bar_h + int(H * 0.026)))

    # --- tagline --------------------------------------------------------
    tag_img = Image.new("RGBA", tag.size, (198, 235, 255, 0))
    tag_img.putalpha(tag.point(lambda v: int(v * 0.9)))
    ty = line_y + bar_h + gap_tag
    art.alpha_composite(tag_img, ((W - tag.width) // 2, ty))

    # --- sleepy "zzz" drifting off the end of the wordmark ---------------
    zx = wx + word.width + int(W * 0.014)
    zy = wy + int(word.height * 0.10)
    for mul in (0.46, 0.32, 0.22):
        zm = text_mask("z", font("display", max(8, int(word.height * mul))))
        if zx + zm.width > W - int(W * 0.005) or zy < 0:
            break
        zi = Image.new("RGBA", zm.size, (206, 240, 255, 0))
        zi.putalpha(zm.point(lambda v: int(v * 0.85)))
        art.alpha_composite(glow(zm, CYAN, max(2, int(H * 0.02)), 1.4), (zx, zy))
        art.alpha_composite(zi, (zx, zy))
        zx += zm.width + int(W * 0.005)
        zy -= int(zm.height * 0.5)

    return art.resize((length, depth), Image.LANCZOS)


# --------------------------------------------------------------------------
# base texture
# --------------------------------------------------------------------------
def night_base(size) -> Image.Image:
    w, h = size
    base = gradient((w, h), SKY).convert("RGBA")

    # two soft blooms, like city light on the paint
    bloom = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bloom)
    bd.ellipse((-w * 0.25, h * 0.12, w * 0.55, h * 0.52), fill=CYAN + (70,))
    bd.ellipse((w * 0.45, h * 0.55, w * 1.25, h * 0.98), fill=MAGENTA + (64,))
    base.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(w * 0.11)))

    # stars
    stars = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(stars)
    rnd = __import__("random").Random(20260915)
    for _ in range(900):
        x, y = rnd.random(), rnd.random()
        r = rnd.choice((0.6, 0.8, 1.0, 1.0, 1.4, 2.0))
        v = int(70 + 185 * rnd.random() ** 2)
        sd.ellipse((x * w - r, y * h - r, x * w + r, y * h + r), fill=v)
    star_layer = Image.new("RGBA", (w, h), (226, 242, 255, 0))
    star_layer.putalpha(stars)
    base.alpha_composite(star_layer)

    # long diagonal light streaks
    streaks = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    std = ImageDraw.Draw(streaks)
    for i, (x0, alpha, width) in enumerate(((0.10, 26, 3), (0.34, 18, 2), (0.62, 22, 3), (0.86, 16, 2))):
        col = CYAN if i % 2 == 0 else MAGENTA
        std.line((x0 * w, -h * 0.1, (x0 + 0.22) * w, h * 1.1), fill=col + (alpha,), width=width)
    base.alpha_composite(streaks.filter(ImageFilter.GaussianBlur(w * 0.006)))
    return base


def centre_stripe(size, cx: int) -> Image.Image:
    """Twin stripe down the roof/hood centre line of the UV layout."""
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    half = max(3, int(w * 0.017))
    for offset in (-int(w * 0.030), int(w * 0.030)):
        strip = gradient((half * 2, h), [(0.0, CYAN), (0.45, (140, 120, 250)), (1.0, MAGENTA)]).convert("RGBA")
        fade = gradient((half * 2, h), [(0.0, (0, 0, 0)), (0.12, (150, 150, 150)), (0.5, (110, 110, 110)), (0.88, (150, 150, 150)), (1.0, (0, 0, 0))]).convert("L")
        strip.putalpha(fade)
        layer.alpha_composite(strip, (cx + offset - half, 0))
    return layer.filter(ImageFilter.GaussianBlur(0.6))


# --------------------------------------------------------------------------
# per-model composition
# --------------------------------------------------------------------------
def inset(box, fx: float, fy: float):
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * fx, (y1 - y0) * fy
    return (int(x0 + dx), int(y0 + dy), int(x1 - dx), int(y1 - dy))


def build_car(bands: dict) -> Image.Image:
    w, h = bands["size"]
    img = night_base((w, h))
    img.alpha_composite(centre_stripe((w, h), w // 2))

    left = inset(bands["left"], 0.035, 0.115)
    right = inset(bands["right"], 0.035, 0.115)

    # length of the artwork = the vertical extent of the strip (nose -> tail)
    length = left[3] - left[1]
    depth = left[2] - left[0]
    art = side_art(length, depth)

    # left strip: rotate clockwise so the artwork's left edge lands at the top
    img.alpha_composite(art.transpose(Image.ROTATE_270), (left[0], left[1]))
    # right strip: mirrored UV, so rotate the other way
    img.alpha_composite(art.transpose(Image.ROTATE_90), (right[0], right[1]))
    return img


def build_cybertruck(size, bands) -> Image.Image:
    w, h = size
    img = night_base((w, h))
    img.alpha_composite(centre_stripe((w, h), w // 2))

    x0, y0, x1, y1 = bands["bottom"]
    art = side_art(x1 - x0, y1 - y0)
    img.alpha_composite(art, (x0, y0))

    tx0, ty0, tx1, ty1 = bands["top"]
    top = side_art(tx1 - tx0, ty1 - ty0).transpose(Image.FLIP_TOP_BOTTOM)
    img.alpha_composite(top, (tx0, ty0))
    return img


def save(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = Image.new("RGB", img.size, (0, 0, 0))
    rgb.paste(img, mask=img.getchannel("A"))
    rgb.save(path, optimize=True)
    if path.stat().st_size > 1_000_000:  # Tesla caps wraps at 1 MB
        rgb.convert("P", palette=Image.ADAPTIVE, colors=256).save(path, optimize=True)
    return path.stat().st_size


def readable_flank(model: str, spec: dict) -> Image.Image:
    """The flank of a finished wrap, rotated back to how it reads on the car."""
    img = Image.open(OUT_DIR / model / "Sleeplow.png").convert("RGB")
    if spec.get("kind") == "cybertruck":
        return img.crop(tuple(spec["bands"]["bottom"]))
    return img.crop(tuple(spec["left"])).transpose(Image.ROTATE_90)


def build_preview(layout: dict, path: Path):
    models = sorted(layout)
    width, cols, thumb = 1200, 4, 290
    hero = readable_flank("model3", layout["model3"])
    hero = hero.resize((width, hero.height * width // hero.width), Image.LANCZOS)

    rows = (len(models) + cols - 1) // cols
    sheet = Image.new("RGB", (width, hero.height + 16 + rows * (thumb + 34)), (8, 9, 20))
    sheet.paste(hero, (0, 0))
    d = ImageDraw.Draw(sheet)
    label = font("label", 15)
    for i, model in enumerate(models):
        tile = Image.open(OUT_DIR / model / "Sleeplow.png").convert("RGB")
        tile = tile.resize((thumb, thumb * tile.height // tile.width), Image.LANCZOS)
        x = (i % cols) * (width // cols) + 6
        y = hero.height + 16 + (i // cols) * (thumb + 34)
        d.text((x, y), model, font=label, fill=(150, 205, 240))
        sheet.paste(tile, (x, y + 20))
    sheet.save(path, optimize=True)
    print(f"  preview                    {sheet.size[0]}x{sheet.size[1]}  {path.stat().st_size/1024:6.1f} KB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", help="only build these models")
    ap.add_argument("--layout", default=str(Path(__file__).with_name("layout.json")))
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    models = args.model or sorted(layout)
    for model in models:
        spec = layout[model]
        if spec.get("kind") == "cybertruck":
            img = build_cybertruck(spec["size"], spec["bands"])
        else:
            img = build_car(spec)
        size = save(img, OUT_DIR / model / "Sleeplow.png")
        print(f"  {model:26s} {img.size[0]}x{img.size[1]}  {size/1024:6.1f} KB")

    if not args.no_preview and not args.model:
        build_preview(layout, OUT_DIR / "preview.png")


if __name__ == "__main__":
    main()
