#!/usr/bin/env python3
"""Find the door panels of every wrap template and write tools/layout.json.

Every template in this repo is a flat UV layout of the car body. For the
non-Cybertruck models the two flanks are unwrapped as vertical strips along the
left and right edges, so the door skins can be found automatically:

  1. build a mask of "this pixel is part of the body" - the alpha channel for
     the silhouette-style templates, a flood fill from the corners for the two
     line-art ones (model3, modelx-2021);
  2. for each row, keep the longest horizontal run of body pixels inside the
     left (or right) third of the texture - that run is the door skin;
  3. keep the tallest band of rows where that run stays wide, tolerating the
     few rows lost to the seam between the front and rear doors;
  4. mirror the better of the two sides onto the other so both flanks get
     identical artwork.

The Cybertruck layout is different (flanks are horizontal bands) and is
specified by hand.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

# Cybertruck: flanks are horizontal bands, the bottom one upright and the top
# one flipped vertically. The band sits between the two wheel arch cut-outs.
CYBERTRUCK = {
    "kind": "cybertruck",
    "size": [1024, 768],
    "bands": {"bottom": [200, 590, 725, 752], "top": [200, 16, 725, 178]},
}


def panel_mask(path: Path) -> np.ndarray:
    im = Image.open(path).convert("RGBA")
    alpha = np.array(im)[..., 3]
    if (alpha < 250).mean() > 0.02:
        return alpha > 128
    grey = im.convert("L").copy()
    for corner in ((0, 0), (grey.width - 1, 0), (0, grey.height - 1), (grey.width - 1, grey.height - 1)):
        if grey.getpixel(corner) > 200:
            ImageDraw.floodfill(grey, corner, 128, thresh=60)
    return np.array(grey) > 200


def longest_runs(mask: np.ndarray, x0: int, x1: int):
    sub = mask[:, x0:x1]
    out = []
    for row in sub:
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        if edges.size == 0:
            out.append((0, 0, 0))
            continue
        starts, ends = edges[::2], edges[1::2]
        k = int(np.argmax(ends - starts))
        out.append((int(ends[k] - starts[k]), int(starts[k]), int(ends[k])))
    return out


def flank(mask: np.ndarray, x0: int, x1: int, gap: int = 34):
    runs = longest_runs(mask, x0, x1)
    widths = np.array([r[0] for r in runs], dtype=float)
    height = len(runs)
    widths[: int(0.12 * height)] = 0
    widths[int(0.92 * height):] = 0
    keep = widths >= 0.62 * widths.max()

    segments, start, last = [], None, None
    for y in range(height):
        if keep[y]:
            start = y if start is None else start
            last = y
        elif start is not None and y - last > gap:
            segments.append((start, last + 1))
            start = None
    if start is not None:
        segments.append((start, last + 1))

    y0, y1 = max(segments, key=lambda s: widths[s[0]:s[1]].sum())
    rows = range(y0, y1)
    starts = np.array([runs[y][1] for y in rows])
    ends = np.array([runs[y][2] for y in rows])
    return [int(np.percentile(starts, 55)) + x0, y0, int(np.percentile(ends, 45)) + x0, y1]


def main():
    layout = {"cybertruck": CYBERTRUCK}
    for template in sorted(glob.glob(str(ROOT / "*" / "template.png"))):
        model = Path(template).parent.name
        if model == "cybertruck":
            continue
        mask = panel_mask(Path(template))
        h, w = mask.shape
        left = flank(mask, 0, int(0.36 * w))
        right = flank(mask, int(0.64 * w), w)
        # the UV is symmetric: mirror whichever side was detected more fully
        if (left[3] - left[1]) >= (right[3] - right[1]):
            right = [w - left[2], left[1], w - left[0], left[3]]
        else:
            left = [w - right[2], right[1], w - right[0], right[3]]
        layout[model] = {"size": [w, h], "left": left, "right": right}
        print(f"  {model:26s} left={left} right={right}")

    out = Path(__file__).with_name("layout.json")
    out.write_text(json.dumps(layout, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
