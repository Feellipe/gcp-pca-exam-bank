#!/usr/bin/env python3
"""Locate the green-highlighted text lines in a question slide and crop each one
out, so the text can be read back unambiguously.

Colour *perception* by a vision model is unreliable; reading cropped text is not.
Use this to verify which answer options are actually marked correct.

Usage: green_bands.py IMAGE [IMAGE ...] [--out DIR] [--pad 12]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gs import green_mask  # noqa: E402  (re-exported for scan_window.py)


def find_bands(mask, min_rows=2):
    """Contiguous row ranges (image coords) containing green text."""
    rows = mask.sum(axis=1)
    thresh = max(3, 0.005 * mask.shape[1])
    dense = rows > thresh
    bands = []
    cur = None
    for y, d in enumerate(dense):
        if d and cur is None:
            cur = [y, y]
        elif d:
            cur[1] = y
        elif cur is not None:
            if cur[1] - cur[0] + 1 >= min_rows:
                bands.append(tuple(cur))
            cur = None
    if cur is not None and cur[1] - cur[0] + 1 >= min_rows:
        bands.append(tuple(cur))
    return bands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default="work/bands")
    ap.add_argument("--pad", type=int, default=10)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for arg in args.images:
        p = Path(arg)
        if not p.exists():
            print(f"{p.name}: MISSING")
            continue
        im = Image.open(p).convert("RGB")
        a = np.asarray(im)
        mask = green_mask(a)
        bands = find_bands(mask)
        total = int(mask.sum())
        print(f"\n{p.name}  {im.width}x{im.height}  green_px={total} "
              f"({total / (im.width * im.height):.3%})  bands={len(bands)}")
        for i, (y0, y1) in enumerate(bands, 1):
            npx = int(mask[y0:y1 + 1].sum())
            # Column extent of the green text in this band.
            cols = np.where(mask[y0:y1 + 1].any(axis=0))[0]
            x0, x1 = (int(cols.min()), int(cols.max())) if len(cols) else (0, im.width - 1)
            top = max(0, y0 - args.pad)
            bot = min(im.height, y1 + args.pad + 1)
            left = max(0, x0 - args.pad)
            right = min(im.width, x1 + args.pad + 1)
            crop = im.crop((left, top, right, bot))
            name = f"{p.stem}_band{i}_y{y0}-{y1}.png"
            crop.save(outdir / name)
            print(f"  band{i}: y={y0}-{y1} ({y0 / im.height:.1%}-{y1 / im.height:.1%} of height) "
                  f"x={x0}-{x1} green_px={npx} -> {outdir / name}")


if __name__ == "__main__":
    sys.exit(main())
