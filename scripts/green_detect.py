#!/usr/bin/env python3
"""Detect the green 'correct answer' highlight in a question slide (numpy).

Reports the fraction of green text pixels and the vertical bands (as a fraction
of image height) where they occur, so we can tell WHICH answer lines are marked
correct, and whether the answer has been revealed at all.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def green_stats(path, min_sat=0.25, min_val=0.25):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    diff = mx - mn
    sat = np.where(mx > 0, diff / np.maximum(mx, 1e-6), 0.0)
    val = mx / 255.0
    # hue in [0,1): green window 0.20-0.45
    hue = np.zeros_like(mx)
    nz = diff > 1e-6
    rr = np.where(nz, (mx - r) / np.maximum(diff, 1e-6), 0)
    gg = np.where(nz, (mx - g) / np.maximum(diff, 1e-6), 0)
    bb = np.where(nz, (mx - b) / np.maximum(diff, 1e-6), 0)
    hue = np.where(mx == r, bb - gg, np.where(mx == g, 2.0 + rr - bb, 4.0 + gg - rr))
    hue = (hue / 6.0) % 1.0
    mask = (
        (hue >= 0.20) & (hue <= 0.45) & (sat >= min_sat) & (val >= min_val)
        & (g > r + 25) & (g > b + 25)
    )
    n = int(mask.sum())
    frac = n / (w * h)
    rows = mask.sum(axis=1)
    dense = rows > 0.01 * w
    regs = []
    cur = None
    for y in range(h):
        if dense[y] and cur is None:
            cur = [y, y]
        elif dense[y] and cur:
            cur[1] = y
        elif not dense[y] and cur:
            regs.append((cur[0] / h, cur[1] / h))
            cur = None
    if cur:
        regs.append((cur[0] / h, cur[1] / h))
    rgb_avg = None
    if n:
        rgb_avg = tuple(int(round(v)) for v in a[mask].mean(axis=0))
        hsv_avg = (float(hue[mask].mean()), float(sat[mask].mean()), float(val[mask].mean()))
    else:
        hsv_avg = (0.0, 0.0, 0.0)
    return w, h, n, frac, regs, rgb_avg, hsv_avg


def fmt_regs(regs):
    return [(round(a, 3), round(b, 3)) for a, b in regs]


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"{p.name}: MISSING")
            continue
        w, h, n, frac, regs, rgb, hsv = green_stats(p)
        print(f"{p.name}  {w}x{h}  green_px={n}  frac={frac:.3%}  avgRGB={rgb}  avgHSV=({hsv[0]:.3f},{hsv[1]:.2f},{hsv[2]:.2f})")
        print(f"    bands(y-frac): {fmt_regs(regs)}")
