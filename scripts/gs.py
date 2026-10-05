#!/usr/bin/env python3
"""Core helpers: green-highlight scanning + YouTube caption parsing.

Shared by green_timeline.py and extract_questions.py.
"""
import re
import subprocess

import numpy as np

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def probe_dims(video):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = (int(x) for x in out.split(","))
    return w, h


def probe_duration(video):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def green_mask(frame, min_sat=0.25, min_val=0.25, min_grey_margin=25):
    """Boolean mask of pixels that look like the green 'correct answer' highlight.

    Single source of truth for this colour test - the slide OCR, the timeline
    scan and the image validator all use it.
    """
    a = frame.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    diff = mx - mn
    sat = np.where(mx > 0, diff / np.maximum(mx, 1e-6), 0.0)
    val = mx / 255.0
    nz = diff > 1e-6
    rr = np.where(nz, (mx - r) / np.maximum(diff, 1e-6), 0)
    gg = np.where(nz, (mx - g) / np.maximum(diff, 1e-6), 0)
    bb = np.where(nz, (mx - b) / np.maximum(diff, 1e-6), 0)
    hue = np.where(mx == r, bb - gg, np.where(mx == g, 2.0 + rr - bb, 4.0 + gg - rr))
    hue = (hue / 6.0) % 1.0
    return ((hue >= 0.20) & (hue <= 0.45) & (sat >= min_sat) & (val >= min_val)
            & (g > r + min_grey_margin) & (g > b + min_grey_margin))


def green_frac(frame, **kwargs):
    """Fraction of pixels that look like the green 'correct answer' highlight."""
    return float(green_mask(frame, **kwargs).mean())


def scan_green(video, interval=1.0, scale_w=640, start=0.0, dur=None, quiet=True):
    """Yield (t, green_fraction) for frames sampled every `interval` seconds."""
    src_w, src_h = probe_dims(video)
    out_h = int(round(scale_w * src_h / src_w / 2)) * 2
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", video]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-vf", f"fps=1/{interval},scale={scale_w}:{out_h}",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    framesize = scale_w * out_h * 3
    idx = 0
    samples = []
    try:
        while True:
            buf = proc.stdout.read(framesize)
            if len(buf) < framesize:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(out_h, scale_w, 3)
            samples.append((start + idx * interval, green_frac(frame)))
            idx += 1
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace").strip()
        proc.wait()
        if err and not quiet:
            print(f"# ffmpeg stderr: {err[:400]}")
    return samples


def runs_from(samples, thresh=0.0002, min_len=8.0, interval=1.0, open_at_end=False):
    """Group samples above `thresh` into (start, end) windows.

    The threshold is deliberately low: a "Question 34"-style slide whose options
    are bare numbers leaves only a few hundred green pixels on screen, and a
    higher cut-off silently skips those questions.
    """
    runs = []
    on = None
    for t, f in samples:
        if f > thresh and on is None:
            on = t
        elif f <= thresh and on is not None:
            if (t - on) >= min_len:
                runs.append((on, t))
            on = None
    if on is not None and samples:
        end = samples[-1][0] + interval
        if open_at_end:
            runs.append((on, end))
        elif (end - on) >= min_len:
            runs.append((on, end))
    return runs


def split_runs_at(runs, cut_times, min_len=8.0):
    """Split green windows wherever the slide cuts, so one question's answer
    window can never bleed into the next slide (e.g. a green end card)."""
    cuts = sorted(cut_times)
    out = []
    for s, e in runs:
        prev = s
        for c in cuts:
            if s < c < e:
                if (c - prev) >= min_len:
                    out.append((prev, c))
                prev = c
        if (e - prev) >= min_len:
            out.append((prev, e))
    return out


SCENE_RE = re.compile(r"pts_time:([0-9.]+)")


def scan_scenes(video, threshold=0.02, scale_w=320, quiet=True):
    """Return timestamps where the slide visibly cuts.

    Decoded at low resolution on purpose - only the *positions* of cuts matter,
    not image quality, and downscaling makes the pass much cheaper.
    """
    cmd = [FFMPEG, "-v", "info", "-nostdin", "-i", video,
           "-filter:v", f"scale={scale_w}:-2,select='gt(scene,{threshold})',showinfo",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    times = [float(x) for x in SCENE_RE.findall(r.stderr or "")]
    if not quiet:
        print(f"# {len(times)} scene cuts")
    return times


TS_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*")
TAG_RE = re.compile(r"<[^>]+>")


def parse_vtt(path):
    """YouTube auto-captions -> list of (seconds, text), rolling dupes collapsed."""
    cues = []
    cur_t, cur_lines = None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw_lines = fh.read().splitlines()

    def flush():
        if cur_t is not None and cur_lines:
            cues.append((cur_t, " ".join(cur_lines).strip()))

    for raw in raw_lines:
        line = raw.rstrip("\n")
        m = TS_RE.match(line)
        if m:
            flush()
            h, mi, s, ms = m.groups()
            cur_t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000.0
            cur_lines = []
            continue
        if not line.strip():
            flush()
            cur_lines = []
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        line = TAG_RE.sub("", line).strip()
        if line:
            cur_lines.append(line)
    flush()

    # Collapse YouTube's rolling captions. Each cue repeats most of the previous
    # one, and the overlap is not always a clean prefix - the window can slide by
    # a word or two - so find the largest suffix/prefix overlap and keep only the
    # genuinely new tail. A strict prefix check leaves duplicated phrases in the
    # transcript ("...provides fine grained access control using IM. So you
    # grained access control using IM. So you...").
    out = []
    prev_words = []
    for t, text in cues:
        words = text.split()
        k = 0
        for cand in range(min(len(prev_words), len(words)), 0, -1):
            if prev_words[-cand:] == words[:cand]:
                k = cand
                break
        new = words[k:]
        if new:
            out.append((t, " ".join(new)))
        prev_words = words
    return out


Q_ANNOUNCE = re.compile(r"\bquestion\s+(?:number\s+)?(\d{1,3})\b", re.I)


def question_announcements(cues, lo=None, hi=None):
    """Map question number -> earliest appearance time in the captions.

    Matching runs over the *joined* caption text, not cue by cue: auto-captions
    wrap mid-phrase, so "Question 28" routinely ends one cue with the number
    starting the next, and per-cue matching misses those announcements.

    Only the earliest mention of each number is kept; mentions outside [lo, hi]
    are ignored when a range is supplied.
    """
    import bisect

    parts, spans, pos = [], [], 0
    for t, text in cues:
        parts.append(text)
        spans.append((pos, pos + len(text), t))
        pos += len(text) + 1
    full = " ".join(parts)
    starts = [s[0] for s in spans]

    found = {}
    for m in Q_ANNOUNCE.finditer(full):
        n = int(m.group(1))
        if lo is not None and n < lo:
            continue
        if hi is not None and n > hi:
            continue
        i = max(0, bisect.bisect_right(starts, m.start()) - 1)
        t = spans[i][2]
        if n not in found or t < found[n]:
            found[n] = t
    return found


RANGE_RE = re.compile(r"\bQ(?:uestions?)?\s*(\d{1,3})\s*-\s*(\d{1,3})\b", re.I)


def expected_range(title):
    """'Part 2 (Questions 21- 40)' -> (21, 40); None when the title has no range."""
    m = RANGE_RE.search(title or "")
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return (lo, hi) if hi >= lo else None
