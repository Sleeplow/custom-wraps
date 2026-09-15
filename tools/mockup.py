#!/usr/bin/env python3
"""Draw a side-on mock-up of each Sleeplow look on a Model 3 style profile.

The wrap files themselves are flat UV layouts and are impossible to judge by
eye, so this renders a stylised side view - body filled with the theme's paint
running nose to tail, the real flank artwork on the doors - and writes a
comparison sheet.

It is an illustration, not a Tesla render: the proportions are approximate and
the car's own lighting will change how the paint reads.

Usage:
    python3 tools/mockup.py                  # sleeplow/model3/mockups.png
    python3 tools/mockup.py --theme acid
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sleeplow_wrap import OUT_DIR, base_paint, font, gradient, side_art, tint  # noqa: E402
from themes import ORDER, THEMES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

W, H = 1600, 660
SS = 2  # supersampling

# Model 3 style fastback profile, clockwise from the nose. Laid out from the
# published proportions: wheelbase 0.61 of the length, front overhang 0.18,
# rear 0.21, height 0.31 - which is what keeps it from drifting into generic
# coupe territory.
BODY = [
    (92, 396), (80, 350), (86, 318), (130, 300), (215, 288), (330, 278),
    (440, 268), (510, 260), (585, 196), (650, 148), (720, 112), (810, 90),
    (910, 82), (1010, 88), (1110, 112), (1210, 152), (1300, 200),
    (1362, 246), (1428, 258), (1468, 270), (1488, 302), (1484, 374),
    (1466, 436), (1392, 476), (1282, 492), (1150, 500), (950, 504),
    (700, 504), (520, 498), (380, 490), (230, 476), (140, 444), (102, 414),
]
GLASS = [
    (528, 262), (598, 198), (662, 152), (732, 118), (818, 98), (912, 92),
    (1008, 98), (1104, 122), (1198, 160), (1300, 238),
]
FRONT_WHEEL = (345, 452, 106)   # cx, cy, tyre radius
REAR_WHEEL = (1245, 452, 106)
ARCH = 126
DOOR = (570, 285, 1210, 475)    # where the flank artwork goes


def scaled(points, k):
    return [(x * k, y * k) for x, y in points]


def wheel(canvas: Image.Image, cx, cy, r, k):
    d = ImageDraw.Draw(canvas)
    cx, cy, r = cx * k, cy * k, r * k
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(14, 14, 16, 255))
    rim = r * 0.63
    d.ellipse((cx - rim, cy - rim, cx + rim, cy + rim), fill=(188, 192, 198, 255))
    d.ellipse((cx - rim, cy - rim, cx + rim, cy + rim), outline=(120, 124, 130, 255), width=int(3 * k))
    for i in range(5):
        a = i * 1.2566 + 0.3
        import math
        x1, y1 = cx + math.cos(a) * rim * 0.22, cy + math.sin(a) * rim * 0.22
        x2, y2 = cx + math.cos(a) * rim * 0.92, cy + math.sin(a) * rim * 0.92
        d.line((x1, y1, x2, y2), fill=(138, 143, 150, 255), width=int(11 * k))
    hub = r * 0.17
    d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=(96, 100, 106, 255))


def render(theme: dict) -> Image.Image:
    k = SS
    # --- body silhouette -------------------------------------------------
    body_mask = Image.new("L", (W * k, H * k), 0)
    bd = ImageDraw.Draw(body_mask)
    bd.polygon(scaled(BODY, k), fill=255)
    for cx, cy, _ in (FRONT_WHEEL, REAR_WHEEL):  # cut the wheel arches
        bd.ellipse(
            ((cx - ARCH) * k, (cy - ARCH) * k, (cx + ARCH) * k, (cy + ARCH) * k),
            fill=0,
        )

    # paint: the theme gradient runs nose -> tail, as it does on the real wrap
    paint = gradient((W * k, H * k), theme["sky"], horizontal=True).convert("RGBA")

    # borrow the decorated texture so stars / grain / splatter show up too.
    # rotate(90) puts the texture's top edge - the nose of the car in UV space -
    # on the left, which is where the nose is in this view
    texture = base_paint((1024, 1024), theme).rotate(90, expand=True)
    texture = texture.resize((W * k, H * k), Image.LANCZOS)
    paint.alpha_composite(texture.filter(ImageFilter.GaussianBlur(k * 0.4)))

    body = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    body.paste(paint, (0, 0), body_mask)

    # --- flank artwork on the doors ---------------------------------------
    x0, y0, x1, y1 = DOOR
    art = side_art((x1 - x0) * k, (y1 - y0) * k, theme, ss=2)
    layer = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    layer.alpha_composite(art, (x0 * k, y0 * k))
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", body_mask.size, 0), body_mask))
    body.alpha_composite(layer)

    # --- shading: darker sills, a highlight along the shoulder ------------
    shade = gradient(
        (W * k, H * k),
        [(0.0, (70, 70, 70)), (0.32, (0, 0, 0)), (0.62, (44, 44, 44)), (1.0, (205, 205, 205))],
    ).convert("L")
    body.alpha_composite(tint(shade, (0, 0, 0), 0.30))
    shoulder = Image.new("L", (W * k, H * k), 0)
    ImageDraw.Draw(shoulder).line(scaled(BODY[:20], k), fill=120, width=int(9 * k), joint="curve")
    body.alpha_composite(tint(shoulder.filter(ImageFilter.GaussianBlur(k * 5)), (255, 255, 255), 0.5))
    body.putalpha(Image.composite(body.getchannel("A"), Image.new("L", body_mask.size, 0), body_mask))

    # --- glass, wheels, ground -------------------------------------------
    glass = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    poly = scaled(GLASS, k)
    gd.polygon(poly, fill=(22, 26, 32, 240))
    gd.line(poly + [poly[0]], fill=(8, 9, 12, 255), width=int(7 * k), joint="curve")
    for x0, y0, y1 in ((706, 114, 256), (1046, 100, 246)):  # B and C pillars
        gd.line((x0 * k, y0 * k, (x0 + 10) * k, y1 * k), fill=(10, 11, 14, 255), width=int(8 * k))
    sheen = Image.new("L", (W * k, H * k), 0)
    ImageDraw.Draw(sheen).polygon(
        scaled([(544, 260), (616, 194), (712, 132), (776, 124), (656, 194), (588, 260)], k), fill=90
    )
    glass.alpha_composite(tint(sheen.filter(ImageFilter.GaussianBlur(k * 3)), (190, 220, 255)))

    out = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    ground = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    ImageDraw.Draw(ground).ellipse((130 * k, 508 * k, 1480 * k, 586 * k), fill=(0, 0, 0, 130))
    out.alpha_composite(ground.filter(ImageFilter.GaussianBlur(k * 16)))
    for cx, cy, r in (FRONT_WHEEL, REAR_WHEEL):
        wheel(out, cx, cy, r, k)
    out.alpha_composite(body)
    out.alpha_composite(glass)

    # a thin outline so the car reads against any backdrop
    edge = body_mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(k * 0.8))
    out.alpha_composite(tint(edge, (0, 0, 0), 0.35))

    return out.resize((W, H), Image.LANCZOS)


def sheet(themes) -> Image.Image:
    rows = []
    for name in themes:
        theme = THEMES[name]
        rows.append((theme, render(theme)))

    pad, head = 26, 62
    img = Image.new("RGB", (W, len(rows) * (H + head) + pad), (18, 19, 24))
    d = ImageDraw.Draw(img)
    title_f, sub_f = font("label", 34), font("label", 19)
    y = pad
    for theme, car in rows:
        d.text((40, y), theme["title"], font=title_f, fill=(236, 242, 250))
        d.text((40, y + 40), f"{theme['file']}.png  -  {theme['blurb']}", font=sub_f, fill=(150, 162, 180))
        panel = Image.new("RGB", (W, H), (26, 28, 34))
        panel.paste(car, (0, 0), car)
        img.paste(panel, (0, y + head))
        y += H + head
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", action="append", choices=ORDER)
    ap.add_argument("--out", default=str(OUT_DIR / "model3" / "mockups.png"))
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet(args.theme or ORDER).save(out, optimize=True)
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"  wrote {shown}  {out.stat().st_size/1024:.1f} KB")


if __name__ == "__main__":
    main()
