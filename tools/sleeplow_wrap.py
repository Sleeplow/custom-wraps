#!/usr/bin/env python3
"""Generate the "Sleeplow" custom wraps for the Tesla templates in this repo.

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
    python3 tools/sleeplow_wrap.py                      # everything
    python3 tools/sleeplow_wrap.py --model model3       # one model, all looks
    python3 tools/sleeplow_wrap.py --theme acid         # one look, all models
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from themes import ORDER, THEMES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sleeplow"
FONT_CACHE = ROOT / ".fontcache"

WORDMARK = "SLEEPLOW"

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
    strip = Image.new("RGB", (max(n, 1), 1))
    px = strip.load()
    for i in range(max(n, 1)):
        px[i, 0] = ramp(stops, i / max(n - 1, 1))
    strip = strip if horizontal else strip.rotate(-90, expand=True)
    return strip.resize((w, h), Image.BILINEAR)


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


def fit_font(kind: str, text: str, box_w: int, box_h: int, tracking: float = 0.0):
    """Largest font size whose rendered text fits in box_w x box_h."""
    lo, hi = 8, max(16, box_h * 4)
    best = font(kind, 8)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(kind, mid)
        w, h = measure(f, text, tracking)
        if w <= box_w and h <= box_h:
            best, lo = f, mid + 1
        else:
            hi = mid - 1
    return best


def draw_tracked(d: ImageDraw.ImageDraw, xy, text, f, fill, tracking: float = 0.0):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking * f.size


def text_mask(text: str, f: ImageFont.FreeTypeFont, tracking: float = 0.0):
    w, h = measure(f, text, tracking)
    img = Image.new("L", (w + f.size, h + f.size), 0)
    bb = f.getbbox(text)
    draw_tracked(ImageDraw.Draw(img), (-bb[0], -bb[1]), text, f, 255, tracking)
    return img.crop(img.getbbox() or (0, 0, 1, 1))


def dilate(mask: Image.Image, radius: int) -> Image.Image:
    out, step = mask, 5
    while radius > 0:
        k = min(step, radius * 2 + 1)
        k = k if k % 2 else k - 1
        out = out.filter(ImageFilter.MaxFilter(k))
        radius -= k // 2
    return out


def glow(mask: Image.Image, colour, radius: int, strength: float) -> Image.Image:
    blurred = mask.filter(ImageFilter.GaussianBlur(max(radius, 1)))
    blurred = blurred.point(lambda v: int(min(255, v * strength)))
    img = Image.new("RGBA", mask.size, tuple(colour) + (0,))
    img.putalpha(blurred)
    return img


def tint(mask: Image.Image, colour, alpha: float = 1.0) -> Image.Image:
    img = Image.new("RGBA", mask.size, tuple(colour) + (0,))
    img.putalpha(mask if alpha >= 1.0 else mask.point(lambda v: int(v * alpha)))
    return img


# --------------------------------------------------------------------------
# the side artwork
# --------------------------------------------------------------------------
def side_art(length: int, depth: int, theme: dict, ss: int = 3) -> Image.Image:
    """Horizontal artwork for one flank: `length` runs nose->tail, `depth` is
    the height of the panel. Returned upright and readable."""
    W, H = length * ss, depth * ss
    art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    accent, accent2 = theme["accent"], theme["accent2"]

    # --- lay the block out ----------------------------------------------
    tagline = theme["tagline"]
    scale = theme.get("block_scale", 1.0)
    f = fit_font("display", WORDMARK, int(W * 0.79 * scale), int(H * 0.52 * scale), tracking=0.012)
    word = text_mask(WORDMARK, f, tracking=0.012)

    bar_h = max(2, int(H * 0.034))
    gap_bar = int(H * 0.070)
    gap_tag = int(H * 0.055)
    tf = fit_font("label", tagline, int(W * 0.52), int(H * 0.10), tracking=0.34)
    tag = text_mask(tagline, tf, tracking=0.34)

    block_h = word.height + gap_bar + bar_h + gap_tag + tag.height
    wy = (H - block_h) // 2
    wx = (W - word.width) // 2

    canvas_word = Image.new("L", (W, H), 0)
    canvas_word.paste(word, (wx, wy))

    # --- racing stripe pack, above and below the whole block --------------
    if theme.get("side_stripes"):
        stripes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stripes)
        pack = ((accent, 0.050), (accent2, 0.026), (accent, 0.011))
        y = int(H * 0.025)
        for colour, thick in pack:
            h = max(2, int(H * thick))
            sd.rectangle((0, y, W, y + h), fill=tuple(colour) + (235,))
            y += h + int(H * 0.015)
        y = H - int(H * 0.025)
        for colour, thick in pack:
            h = max(2, int(H * thick))
            sd.rectangle((0, y - h, W, y), fill=tuple(colour) + (235,))
            y -= h + int(H * 0.015)
        fade = gradient(
            (W, H),
            [(0.0, (0, 0, 0)), (0.05, (255, 255, 255)), (0.95, (255, 255, 255)), (1.0, (0, 0, 0))],
            horizontal=True,
        ).convert("L")
        stripes.putalpha(Image.composite(stripes.getchannel("A"), Image.new("L", (W, H), 0), fade))
        art.alpha_composite(stripes)

    # --- retro sun bands under the lettering ------------------------------
    if "scanlines" in (theme.get("art_decor") or []):
        bands = Image.new("L", (W, H), 0)
        bd = ImageDraw.Draw(bands)
        y = int(H * 0.62)
        step, thick = int(H * 0.055), max(2, int(H * 0.010))
        while y < H:
            bd.rectangle((0, y, W, y + thick), fill=190)
            y += step + thick
            step = int(step * 0.86)
            thick = max(2, int(thick * 1.25))
        fade = gradient(
            (W, H),
            [(0.0, (0, 0, 0)), (0.12, (230, 230, 230)), (0.88, (230, 230, 230)), (1.0, (0, 0, 0))],
            horizontal=True,
        ).convert("L")
        bands = Image.composite(bands, Image.new("L", (W, H), 0), fade)
        art.alpha_composite(tint(bands, theme["scan_colour"], 0.55))

    # --- glow behind the letters -----------------------------------------
    for colour, radius, strength in theme.get("glow") or []:
        art.alpha_composite(glow(canvas_word, colour, int(H * radius), strength))

    # --- paint the lettering ---------------------------------------------
    mode = theme["ink_mode"]
    if mode == "outline":
        ring = dilate(canvas_word, max(2, int(H * 0.022)))
        hollow = Image.eval(canvas_word, lambda v: 255 - v)
        edge = Image.composite(ring, Image.new("L", (W, H), 0), hollow)
        art.alpha_composite(tint(canvas_word, theme["keyline"], 0.88))
        fill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fill.paste(gradient((word.width, word.height), theme["ink"]).convert("RGBA"), (wx, wy))
        fill.putalpha(edge)
        art.alpha_composite(fill)
    else:
        keyline = dilate(canvas_word, max(2, int(H * 0.018)))
        art.alpha_composite(tint(keyline, theme["keyline"], 0.94))
        if mode == "flat":
            art.alpha_composite(tint(canvas_word, theme["ink_flat"]))
        else:
            fill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            fill.paste(gradient((word.width, word.height), theme["ink"]).convert("RGBA"), (wx, wy))
            fill.putalpha(canvas_word)
            art.alpha_composite(fill)

    # paint dripping off the bottom of the glyphs
    if theme.get("drips"):
        drips = Image.new("L", (W, H), 0)
        dd = ImageDraw.Draw(drips)
        rnd = random.Random(7)
        px = canvas_word.load()
        for _ in range(7):
            x = rnd.randrange(wx, wx + word.width)
            bottom = None
            for y in range(wy + word.height - 1, wy, -1):
                if px[x, y] > 128:
                    bottom = y
                    break
            if bottom is None:
                continue
            w = max(3, int(H * rnd.uniform(0.020, 0.034)))
            run = int(H * rnd.uniform(0.08, 0.24))
            dd.rounded_rectangle((x, bottom - w, x + w, min(H - 1, bottom + run)), radius=w // 2, fill=255)
            dd.ellipse((x - w * 0.3, bottom + run - w, x + w * 1.3, bottom + run + w * 0.6), fill=255)
        art.alpha_composite(tint(drips, theme["ink"][1][1]))

    # bright band across the upper third of the glyphs
    if theme.get("sheen"):
        shape = gradient(
            (word.width, word.height),
            [(0.00, (255, 255, 255)), (0.26, (255, 255, 255)), (0.40, (0, 0, 0)), (1.00, (0, 0, 0))],
        ).convert("L")
        sheen = Image.new("L", (W, H), 0)
        sheen.paste(shape, (wx, wy))
        sheen = Image.composite(sheen, Image.new("L", (W, H), 0), canvas_word)
        art.alpha_composite(tint(sheen, (255, 255, 255), theme["sheen"]))

    # --- speed line, running the full length of the panel -----------------
    line_y = wy + word.height + gap_bar
    if theme.get("bar"):
        mid = tuple((a + b) // 2 for a, b in zip(accent, accent2))
        bar = gradient((W, bar_h), [(0.0, accent), (0.55, mid), (1.0, accent2)], horizontal=True).convert("RGBA")
        fade = gradient(
            (W, bar_h),
            [(0.0, (0, 0, 0)), (0.07, (255, 255, 255)), (0.92, (255, 255, 255)), (1.0, (0, 0, 0))],
            horizontal=True,
        ).convert("L")
        bar.putalpha(fade)
        art.alpha_composite(glow(bar.getchannel("A"), accent, int(H * 0.045), 1.5), (0, line_y))
        art.alpha_composite(bar, (0, line_y))

        thin_h = max(1, int(H * 0.011))
        t_fade = gradient(
            (W, thin_h),
            [(0.0, (0, 0, 0)), (0.22, (215, 215, 215)), (0.68, (80, 80, 80)), (1.0, (0, 0, 0))],
            horizontal=True,
        ).convert("L")
        art.alpha_composite(tint(t_fade, accent), (0, line_y + bar_h + int(H * 0.026)))

    # --- tagline -----------------------------------------------------------
    ty = line_y + bar_h + gap_tag
    art.alpha_composite(tint(tag, theme["tag_colour"], 0.9), ((W - tag.width) // 2, ty))

    # --- sleepy "zzz" drifting off the end of the wordmark ------------------
    if theme.get("zzz"):
        zx = wx + word.width + int(W * 0.014)
        zy = wy + int(word.height * 0.10)
        for mul in (0.46, 0.32, 0.22):
            zm = text_mask("z", font("display", max(8, int(word.height * mul))))
            if zx + zm.width > W - int(W * 0.005) or zy < 0:
                break
            art.alpha_composite(glow(zm, accent, max(2, int(H * 0.02)), 1.4), (zx, zy))
            art.alpha_composite(tint(zm, theme["zzz"], 0.85), (zx, zy))
            zx += zm.width + int(W * 0.005)
            zy -= int(zm.height * 0.5)

    return art.resize((length, depth), Image.LANCZOS)


# --------------------------------------------------------------------------
# base texture
# --------------------------------------------------------------------------
def base_paint(size, theme: dict) -> Image.Image:
    w, h = size
    base = gradient((w, h), theme["sky"]).convert("RGBA")
    decor = theme.get("decor") or []
    accent, accent2 = theme["accent"], theme["accent2"]
    rnd = random.Random(20260915)

    if "blooms" in decor:
        bloom = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bloom)
        bd.ellipse((-w * 0.25, h * 0.12, w * 0.55, h * 0.52), fill=tuple(accent) + (70,))
        bd.ellipse((w * 0.45, h * 0.55, w * 1.25, h * 0.98), fill=tuple(accent2) + (64,))
        base.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(w * 0.11)))

    if "stars" in decor:
        stars = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(stars)
        for _ in range(900):
            x, y = rnd.random() * w, rnd.random() * h
            r = rnd.choice((0.6, 0.8, 1.0, 1.0, 1.4, 2.0))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=int(70 + 185 * rnd.random() ** 2))
        base.alpha_composite(tint(stars, (226, 242, 255)))

    if "streaks" in decor:
        streaks = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        std = ImageDraw.Draw(streaks)
        for i, (x0, alpha, width) in enumerate(((0.10, 26, 3), (0.34, 18, 2), (0.62, 22, 3), (0.86, 16, 2))):
            colour = accent if i % 2 == 0 else accent2
            std.line((x0 * w, -h * 0.1, (x0 + 0.22) * w, h * 1.1), fill=tuple(colour) + (alpha,), width=width)
        base.alpha_composite(streaks.filter(ImageFilter.GaussianBlur(w * 0.006)))

    if "brushed" in decor:
        # drawn along the texture's y axis: that is the nose->tail direction on
        # every panel, so the grain runs along the car instead of across it
        grain = Image.new("L", (w, h), 0)
        gd = ImageDraw.Draw(grain)
        for _ in range(2600):
            y = rnd.randrange(h)
            x = rnd.randrange(w)
            gd.line((x, y, x, y + rnd.randrange(30, 260)), fill=rnd.randrange(8, 30))
        base.alpha_composite(tint(grain, (255, 255, 255)))
        sheen = gradient((w, h), [(0.0, (0, 0, 0)), (0.42, (46, 46, 52)), (0.5, (0, 0, 0)), (1.0, (0, 0, 0))]).convert("L")
        base.alpha_composite(tint(sheen, (210, 220, 235), 0.45))

    if "sun" in decor:
        sun = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sun).ellipse((w * 0.16, h * 0.62, w * 0.84, h * 1.22), fill=(255, 208, 120, 150))
        base.alpha_composite(sun.filter(ImageFilter.GaussianBlur(w * 0.05)))

    if "spray" in decor:
        spray = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(spray)
        for _ in range(5000):
            x, y = rnd.random() * w, rnd.random() * h
            r = rnd.uniform(0.5, 2.4)
            sd.ellipse((x - r, y - r, x + r, y + r), fill=rnd.randrange(6, 26))
        base.alpha_composite(tint(spray.filter(ImageFilter.GaussianBlur(0.6)), (150, 190, 120)))

    if "splatter" in decor:
        blobs = Image.new("L", (w, h), 0)
        bd = ImageDraw.Draw(blobs)
        for _ in range(26):
            cx, cy = rnd.random() * w, rnd.random() * h
            r = rnd.uniform(w * 0.004, w * 0.020)
            bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rnd.randrange(60, 150))
            for _ in range(rnd.randrange(3, 9)):
                a = rnd.uniform(0, 6.283)
                d = rnd.uniform(r, r * 5)
                rr = rnd.uniform(1.0, r * 0.45)
                sx, sy = cx + d * __import__("math").cos(a), cy + d * __import__("math").sin(a)
                bd.ellipse((sx - rr, sy - rr, sx + rr, sy + rr), fill=rnd.randrange(50, 130))
        base.alpha_composite(tint(blobs, accent, 0.5))

    if "frost" in decor:
        frost = Image.new("L", (w, h), 0)
        fd = ImageDraw.Draw(frost)
        for _ in range(240):
            x, y = rnd.random() * w, rnd.random() * h
            ln = rnd.uniform(w * 0.02, w * 0.12)
            a = rnd.choice((0.6, -0.6, 1.1, -1.1))
            fd.line((x, y, x + ln, y + ln * a), fill=rnd.randrange(20, 70), width=1)
        base.alpha_composite(tint(frost.filter(ImageFilter.GaussianBlur(0.8)), (255, 255, 255)))

    return base


def centre_stripe(size, cx: int, theme: dict) -> Image.Image:
    """Twin stripe down the roof/hood centre line of the UV layout."""
    if not theme.get("centre"):
        return Image.new("RGBA", size, (0, 0, 0, 0))
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    half = max(3, int(w * 0.017))
    alpha = theme.get("centre_alpha", 1.0)
    for offset in (-int(w * 0.030), int(w * 0.030)):
        strip = gradient((half * 2, h), theme["centre"]).convert("RGBA")
        fade = gradient(
            (half * 2, h),
            [(0.0, (0, 0, 0)), (0.12, (150, 150, 150)), (0.5, (110, 110, 110)), (0.88, (150, 150, 150)), (1.0, (0, 0, 0))],
        ).convert("L")
        strip.putalpha(fade.point(lambda v: int(v * alpha)))
        layer.alpha_composite(strip, (cx + offset - half, 0))
    return layer.filter(ImageFilter.GaussianBlur(0.6))


# --------------------------------------------------------------------------
# per-model composition
# --------------------------------------------------------------------------
def inset(box, fx: float, fy: float):
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * fx, (y1 - y0) * fy
    return (int(x0 + dx), int(y0 + dy), int(x1 - dx), int(y1 - dy))


def flank_box(spec: dict):
    """The rectangle the artwork fills on each flank, nose->tail x across."""
    return inset(spec["left"], 0.035, 0.115), inset(spec["right"], 0.035, 0.115)


def build_car(spec: dict, theme: dict) -> Image.Image:
    w, h = spec["size"]
    img = base_paint((w, h), theme)
    img.alpha_composite(centre_stripe((w, h), w // 2, theme))

    left, right = flank_box(spec)
    art = side_art(left[3] - left[1], left[2] - left[0], theme)

    # left strip: rotate clockwise so the artwork's left edge lands at the top
    img.alpha_composite(art.transpose(Image.ROTATE_270), (left[0], left[1]))
    # right strip: mirrored UV, so rotate the other way
    img.alpha_composite(art.transpose(Image.ROTATE_90), (right[0], right[1]))
    return img


def build_cybertruck(spec: dict, theme: dict) -> Image.Image:
    w, h = spec["size"]
    img = base_paint((w, h), theme)
    img.alpha_composite(centre_stripe((w, h), w // 2, theme))

    x0, y0, x1, y1 = spec["bands"]["bottom"]
    img.alpha_composite(side_art(x1 - x0, y1 - y0, theme), (x0, y0))

    tx0, ty0, tx1, ty1 = spec["bands"]["top"]
    top = side_art(tx1 - tx0, ty1 - ty0, theme).transpose(Image.FLIP_TOP_BOTTOM)
    img.alpha_composite(top, (tx0, ty0))
    return img


def build(spec: dict, theme: dict) -> Image.Image:
    if spec.get("kind") == "cybertruck":
        return build_cybertruck(spec, theme)
    return build_car(spec, theme)


def save(img: Image.Image, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = Image.new("RGB", img.size, (0, 0, 0))
    rgb.paste(img, mask=img.getchannel("A"))
    rgb.save(path, optimize=True)
    if path.stat().st_size > 1_000_000:  # Tesla caps wraps at 1 MB
        rgb.convert("P", palette=Image.ADAPTIVE, colors=256).save(path, optimize=True)
    return path.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", help="only build these models")
    ap.add_argument("--theme", action="append", choices=ORDER, help="only build these looks")
    ap.add_argument("--layout", default=str(Path(__file__).with_name("layout.json")))
    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    models = args.model or sorted(layout)
    names = args.theme or ORDER

    for model in models:
        for name in names:
            theme = THEMES[name]
            img = build(layout[model], theme)
            path = OUT_DIR / model / f"{theme['file']}.png"
            size = save(img, path)
            print(f"  {model:26s} {theme['file']:18s} {img.size[0]}x{img.size[1]}  {size/1024:6.1f} KB")


if __name__ == "__main__":
    main()
