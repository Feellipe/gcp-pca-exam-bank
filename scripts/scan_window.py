#!/usr/bin/env python3
"""Scan a time window of a video and report, per sample, how much green text is
on screen and how many distinct green text lines there are.

Use this to find the exact moment a slide reaches its fully-revealed state,
including questions with two or three correct answers.

Usage: scan_window.py VIDEO START END [--step 1.0]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import gs  # noqa: E402
from green_bands import find_bands, green_mask  # noqa: E402

FFMPEG = "ffmpeg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--scale-w", type=int, default=1280)
    args = ap.parse_args()

    w, h = gs.probe_dims(args.video)
    out_h = int(round(args.scale_w * h / w / 2)) * 2
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-ss", str(args.start),
           "-i", args.video, "-t", str(args.end - args.start),
           "-vf", f"fps=1/{args.step},scale={args.scale_w}:{out_h}",
           "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    framesize = args.scale_w * out_h * 3
    idx = 0
    print(f"# {Path(args.video).name}  window {args.start}-{args.end}s  step={args.step}")
    print(f"# {'t':>8}  {'green%':>8}  lines  band-y-ranges")
    while True:
        buf = proc.stdout.read(framesize)
        if len(buf) < framesize:
            break
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(out_h, args.scale_w, 3)
        t = args.start + idx * args.step
        frac = gs.green_frac(frame)
        mask = green_mask(frame)
        bands = find_bands(mask)
        ys = ", ".join(f"{y0}-{y1}" for y0, y1 in bands)
        print(f"  {t:8.1f}  {frac:8.3%}  {len(bands):5d}  {ys}")
        idx += 1
    proc.stdout.close()
    proc.wait()


if __name__ == "__main__":
    sys.exit(main())
