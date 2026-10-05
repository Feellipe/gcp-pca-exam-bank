#!/usr/bin/env python3
"""Turn a YouTube playlist of GCP exam walkthroughs into one screenshot per
exam question, showing the question text with the green correct answers.

Per video:
  1. download the video-only stream at 720p + auto captions   (yt-dlp)
  2. find "Question N" announcements in the captions          -> numbers
  3. scan the video for green-highlighted text windows        -> answer reveals
  4. map each answer window to the question announced before it
  5. grab the frame a few seconds before each window ends
  6. validate every question in the title's range is present

Resumable: per-video state is cached in <work>/state/<id>.json.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import gs  # noqa: E402

PLAYLIST = "https://www.youtube.com/playlist?list=PLB574eEmT4ofIr8LFjiKJfTjjg7StIAQm"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
YTDLP = shutil.which("yt-dlp") or str(Path.home() / ".local/bin/yt-dlp")

PART_RE = re.compile(r"\bPart\s+(\d+)\b", re.I)


def log(*a):
    print(*a, flush=True)


def ytdlp(*args, check=True):
    cmd = [YTDLP, "--no-warnings", "--no-playlist", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def playlist_videos(url):
    r = None
    for i in range(3):
        r = subprocess.run(
            [YTDLP, "--flat-playlist", "--no-warnings",
             "--print", "%(playlist_index)s\t%(id)s\t%(duration)s\t%(title)s", url],
            capture_output=True, text=True, check=False)
        if r.returncode == 0:
            break
        time.sleep(5 * (i + 1))
    if r is None or r.returncode != 0:
        tail = ((r.stderr or r.stdout) if r else "").strip().splitlines()[-2:]
        raise RuntimeError("playlist listing failed: " + " | ".join(tail))
    vids = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[0] in ("", "NA"):
            continue
        idx, vid, dur, title = parts[0], parts[1], parts[2], "\t".join(parts[3:])
        try:
            idx_i = int(idx)
        except ValueError:
            continue
        try:
            dur_f = float(dur)
        except ValueError:
            dur_f = 0.0
        vids.append({"index": idx_i, "id": vid, "duration": dur_f, "title": title})
    return sorted(vids, key=lambda v: v["index"])


def _attempt(args, attempts=5, base_delay=20.0, label="yt-dlp"):
    """Run yt-dlp, retrying transient failures.

    YouTube rate-limits (HTTP 429) after a burst of requests, which kills a
    straight 16-video run. Backing off and retrying is what makes the batch
    survive; the video and its captions are fetched separately so a throttled
    caption request never throws away an already-downloaded video.
    """
    r = None
    for i in range(attempts):
        r = ytdlp(*args, check=False)
        if r.returncode == 0:
            return r
        blob = f"{r.stderr or ''}\n{r.stdout or ''}"
        errs = [ln.strip() for ln in blob.splitlines() if "ERROR" in ln]
        if errs:
            last = errs[-1]
        else:
            last = next((ln.strip() for ln in reversed(blob.splitlines()) if ln.strip()), "")
        if i < attempts - 1:
            delay = base_delay * (2 ** i)
            log(f"    {label} attempt {i + 1}/{attempts} failed: {last[:110]}")
            log(f"    retrying in {delay:.0f}s")
            time.sleep(delay)
        else:
            log(f"    {label} gave up after {attempts} attempts: {last[:160]}")
    return r


def fetch(vid_id, work, quality, force=False):
    """Download video-only stream + auto captions. Returns (video_path, vtt_path)."""
    vdir = work / "videos"
    vdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(vdir.glob(f"{vid_id}.*"))
    video = next((p for p in existing if p.suffix in (".mp4", ".webm", ".mkv")), None)
    vtt = next((p for p in existing if p.suffix == ".vtt"), None)
    out_tpl = str(vdir / "%(id)s.%(ext)s")
    url = f"https://www.youtube.com/watch?v={vid_id}"

    have_video = video is not None
    if force or video is None:
        # Video FIRST, alone. yt-dlp resolves subtitle URLs during setup, so a
        # throttled caption request (HTTP 429) aborts the invocation before the
        # video is ever written - asking for both in one call is what lost three
        # whole videos. The video is the one essential artefact, so it gets the
        # long backoff and nothing else in the request.
        _attempt(["-f", (f"bv*[height<={quality}][vcodec^=avc1]"
                         f"/bv*[height<={quality}][protocol=https]"
                         f"/bv*[height<={quality}]"),
                  "-o", out_tpl, url],
                 attempts=6, base_delay=30.0, label="video")
        existing = sorted(vdir.glob(f"{vid_id}.*"))
        video = next((p for p in existing if p.suffix in (".mp4", ".webm", ".mkv")), None)

    if force or vtt is None:
        # Captions are optional: short retries, and `--captions-only` can backfill
        # them later, slowly, once the throttling clears.
        _attempt(["--skip-download", "--write-auto-subs", "--sub-langs", "en.*",
                  "--sub-format", "vtt", "-o", out_tpl, url],
                 attempts=(2 if have_video else 3), base_delay=20.0, label="captions")
        existing = sorted(vdir.glob(f"{vid_id}.*"))
        vtt = next((p for p in existing if p.suffix == ".vtt"), None)

    return video, vtt


def extract_frame(video, t, out_path, quality=2):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [FFMPEG, "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", str(quality), "-y", str(out_path)],
        capture_output=True, text=True, check=False)
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg frame extract failed at {t}: {r.stderr.strip()[:200]}")
    return out_path


def _ahash(path, size=16):
    """Average-hash of an image, for detecting duplicated screenshots."""
    im = Image.open(path).convert("L").resize((size, size), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32)
    return np.packbits((a > a.mean()).flatten()).tobytes().hex()


def _trim_runs(runs, expected, samples):
    """Reduce the green windows to exactly `expected` questions.

    The weakest candidates go first: a window whose peak green coverage barely
    clears the threshold is far more likely to be a stray green element than a
    real answered slide.
    """
    out = list(runs)

    def peak(run):
        s, e = run
        vals = [f for t, f in samples if s - 1 <= t <= e]
        return max(vals) if vals else 0.0

    while len(out) > expected:
        i = min(range(len(out)), key=lambda k: (peak(out[k]), out[k][1] - out[k][0]))
        out.pop(i)
    return out


def process_video(v, work, outdir, quality, lead_out, interval, min_run,
                  scene_threshold=0.02, force=False):
    sid = v["id"]
    state_dir = work / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{sid}.json"
    if state_file.exists() and not force:
        st = json.loads(state_file.read_text(encoding="utf-8"))
        # Only honour the cache if the images it claims to have produced are
        # still on disk; a deleted frame must be regenerated.
        files = [q.get("file") for q in st.get("questions", []) if q.get("file")]
        if files and all((outdir / f).exists() for f in files):
            st["cached"] = True
            return st

    t0 = time.time()
    video, vtt = fetch(sid, work, quality, force=force)
    if video is None:
        raise RuntimeError("no video file after download")

    lo_hi = gs.expected_range(v["title"])
    if vtt is not None:
        cues = gs.parse_vtt(vtt)
        ann = gs.question_announcements(cues)
    else:
        # Captions are a convenience, not a requirement. The numbered videos
        # declare their question range in the title, so answered slides can be
        # numbered by order instead - and YouTube rate-limits captions hard.
        log("    no captions (rate-limited?) - will number by slide order")
        cues, ann = [], {}
    if lo_hi:
        lo, hi = lo_hi
        ann_in = {n: t for n, t in ann.items() if lo <= n <= hi}
    else:
        # No declared range in the title (the case-study / topic videos). Do not
        # derive one from min/max caption mentions - passing references to other
        # question numbers would stretch it into a bogus 100-question range.
        # These videos are numbered sequentially from their answered slides.
        lo, hi = None, None
        ann_in = dict(ann)

    samples = gs.scan_green(video, interval=interval, scale_w=640, quiet=False)
    runs = gs.runs_from(samples, min_len=min_run, interval=interval)
    # A green window must not span a slide cut, otherwise a question's answer
    # window merges with whatever follows (e.g. a green end card).
    cuts = gs.scan_scenes(video, threshold=scene_threshold, quiet=False)
    runs = gs.split_runs_at(runs, cuts, min_len=min_run)
    duration = gs.probe_duration(video)

    # An end card runs to the end of the video; a real answer window is always
    # followed by another slide. Drop a trailing window that touches the end.
    if runs and (duration - runs[-1][1]) <= 3.0:
        runs = runs[:-1]

    # Likewise at the start: a green window covering the opening seconds and
    # ending at the first slide cut is the video's title card, not a question.
    if runs and runs[0][0] <= interval and (not cuts or runs[0][1] <= cuts[0] + 1.0):
        runs = runs[1:]

    # Reconcile the window count with the range the title declares.
    if lo is not None and len(runs) > (hi - lo + 1):
        before = len(runs)
        runs = _trim_runs(runs, hi - lo + 1, samples)
        log(f"    trimmed {before - len(runs)} stray green window(s) to match range")

    # Assign each green window to the question announced most recently before it.
    def last_ann_before(t):
        best = None
        for n, at in ann_in.items():
            if at <= t and (best is None or at > ann_in[best]):
                best = n
        return best

    def next_cut_after(t):
        for c in cuts:
            if c > t + min_run:
                return c
        return None

    # Numbering strategy. When the count of answered slides matches the range the
    # title declares, slide order is the most reliable mapping - every window IS
    # a question - and the captions get demoted to a cross-check. Otherwise fall
    # back to matching each window to the question announced before it.
    numbering = "captions"
    assign = {}
    if lo is not None and len(runs) == (hi - lo + 1):
        numbering = "slide-order"
        assign = {lo + i: [r] for i, r in enumerate(runs)}
        if ann_in:
            mism = [(lo + i, last_ann_before(r[0])) for i, r in enumerate(runs)]
            mism = [(n, a) for n, a in mism if a is not None and a != n]
            if mism:
                log(f"    note: captions disagree with slide order at {mism[:6]}")
    else:
        for s, e in runs:
            n = last_ann_before(s)
            if n is not None:
                assign.setdefault(n, []).append((s, e))

    part = (PART_RE.search(v["title"]).group(1) if PART_RE.search(v["title"]) else None)
    questions = []
    if lo is not None:
        for n in range(lo, hi + 1):
            cands = assign.get(n)
            if cands:
                s, e = cands[0]
                t_shot = e - lead_out
                source = "green-window"
                if len(cands) > 1:
                    source = f"green-window(first of {len(cands)})"
            elif n + 1 in ann_in:
                # The next question's announcement lands ~1s after this slide
                # flips, so a few seconds before it is still this question,
                # answered. Only sound because a real announcement anchored it.
                t_shot = ann_in[n + 1] - lead_out
                source = "fallback(next-announcement)"
            elif n in ann_in:
                nc = next_cut_after(ann_in[n])
                if nc is None:
                    questions.append({"question": n, "stem": f"q{n:03d}", "time": None,
                                      "file": None, "source": "MISSING"})
                    continue
                t_shot = nc - lead_out
                source = "fallback(next-scene-cut)"
            else:
                # No captions and no matching green window: there is nothing to
                # anchor a timestamp to. Never guess from the video start - that
                # silently pointed every question at the same slide.
                questions.append({"question": n, "stem": f"q{n:03d}", "time": None,
                                  "file": None, "source": "MISSING",
                                  "note": "no caption and no matching green window"})
                continue
            questions.append({"question": n, "stem": f"q{n:03d}", "time": round(t_shot, 3),
                              "file": None, "source": source,
                              "window": [round(s, 1), round(e, 1)] if cands else None})
    else:
        # No declared range: one item per answered slide, numbered sequentially.
        # Files are named per part so they cannot collide with the real question
        # numbers produced by the numbered videos.
        seq = 0
        prev = None
        for s, e in runs:
            anchored = last_ann_before(s)
            n = anchored
            if n is None or (prev is not None and n <= prev):
                n = (prev + 1) if prev is not None else (n or 1)
            prev = n
            seq += 1
            stem = f"p{int(part):02d}s{seq:02d}" if part else f"s{seq:02d}"
            questions.append({"question": n, "seq": seq, "stem": stem,
                              "anchored": anchored is not None,
                              "time": round(e - lead_out, 3), "file": None,
                              "source": "green-window",
                              "window": [round(s, 1), round(e, 1)]})

        # A video regularly opens on a question slide before the presenter says
        # its number, so the first slide(s) have no announcement to anchor them.
        # Number those backwards from the first anchored slide instead of letting
        # them default to 1 (which collided with question 1 of part 1).
        first_anchor = next((i for i, q in enumerate(questions) if q.get("anchored")), None)
        if first_anchor not in (None, 0):
            base = questions[first_anchor]["question"]
            for i in range(first_anchor - 1, -1, -1):
                questions[i]["question"] = base - (first_anchor - i)

    out_vdir = outdir
    for q in questions:
        if q["time"] is None:
            continue
        out_path = out_vdir / f"{q['stem']}.jpg"
        extract_frame(video, q["time"], out_path)
        q["file"] = out_path.name

    # Self-check: a valid question screenshot must actually contain green
    # (the revealed answer). Anything without it is reported, not silently kept.
    for q in questions:
        if not q["file"]:
            continue
        q["green_frac"] = round(gs.green_frac(np.asarray(
            Image.open(out_vdir / q["file"]).convert("RGB"))), 6)
    unverified = [q["question"] for q in questions
                  if q["file"] and q.get("green_frac", 0) <= 0.0002]

    # Duplicate guard: distinct questions must yield distinct images. Without
    # this, a bad fallback can point every question at one slide and still pass
    # the green check.
    by_hash = {}
    for q in questions:
        if not q["file"]:
            continue
        h = _ahash(out_vdir / q["file"])
        q["ahash"] = h
        by_hash.setdefault(h, []).append(q["question"])
    duplicates = sorted(sorted(v) for v in by_hash.values() if len(v) > 1)

    st = {
        "video_id": sid,
        "index": v["index"],
        "part": (PART_RE.search(v["title"]).group(1) if PART_RE.search(v["title"]) else None),
        "title": v["title"],
        "duration": round(duration, 2),
        "expected_range": list(lo_hi) if lo_hi else None,
        "announcements": {str(k): round(val, 2) for k, val in sorted(ann_in.items())},
        "numbering": numbering,
        "has_captions": vtt is not None,
        "green_runs": [[round(s, 1), round(e, 1)] for s, e in runs],
        "scene_cuts": [round(c, 1) for c in cuts],
        "questions": questions,
        "found": sum(1 for q in questions if q["file"]),
        "missing": [q["question"] for q in questions if q["file"] is None],
        "unverified": unverified,
        "duplicates": duplicates,
        "elapsed_s": round(time.time() - t0, 1),
        "cached": False,
    }
    state_file.write_text(json.dumps(st, indent=2), encoding="utf-8")
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default=PLAYLIST)
    ap.add_argument("--videos", help="comma-separated video ids (overrides --playlist)")
    ap.add_argument("--only", help="comma-separated playlist indexes to process")
    ap.add_argument("--out", default="Questions/auto")
    ap.add_argument("--work", default="work")
    ap.add_argument("--quality", type=int, default=720, help="max video height")
    ap.add_argument("--lead-out", type=float, default=3.0,
                    help="seconds before the answer window ends to screenshot")
    ap.add_argument("--interval", type=float, default=1.0, help="green scan sampling step")
    ap.add_argument("--min-run", type=float, default=8.0,
                    help="ignore green windows shorter than this (title cards, outros)")
    ap.add_argument("--scene-threshold", type=float, default=0.02,
                    help="ffmpeg scene score above which the slide counts as cut")
    ap.add_argument("--pause", type=float, default=6.0,
                    help="seconds to wait between videos, to avoid HTTP 429")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="process only shard I of N (0-based); lets several workers "
                         "split the playlist without touching each other's videos")
    ap.add_argument("--retry-pause", type=float, default=120.0,
                    help="cooling-off seconds before the retry pass over failures "
                         "(0 disables the retry pass)")
    ap.add_argument("--captions-only", action="store_true",
                    help="only fetch missing captions (no frame work); used to "
                         "backfill transcripts after YouTube rate-limits clear")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="ignore cached state")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    work = (root / args.work) if not Path(args.work).is_absolute() else Path(args.work)
    outdir = (root / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.videos:
        vids = [{"index": 0, "id": x.strip(), "duration": 0.0, "title": ""}
                for x in args.videos.split(",") if x.strip()]
        for v in vids:
            r = ytdlp("--print", "%(title)s", f"https://www.youtube.com/watch?v={v['id']}",
                      check=False)
            if r.returncode == 0:
                v["title"] = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    else:
        log(f"# fetching playlist listing: {args.playlist}")
        vids = playlist_videos(args.playlist)

    if args.only:
        wanted = {x.strip() for x in str(args.only).split(",") if x.strip()}
        vids = [v for v in vids if str(v["index"]) in wanted]

    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        vids = [v for v in vids if (v["index"] - 1) % n == i]
        log(f"# shard {i}/{n}")

    log(f"# {len(vids)} video(s) to process")

    if args.captions_only:
        missing = 0
        for vi, v in enumerate(vids):
            if vi:
                time.sleep(args.pause)
            vdir = work / "videos"
            if list(vdir.glob(f"{v['id']}.*.vtt")):
                continue
            log(f"\n=== [{v['index']}] {v['id']} fetching captions")
            _attempt(["--skip-download", "--write-auto-subs", "--sub-langs", "en.*",
                      "--sub-format", "vtt", "-o", str(vdir / "%(id)s.%(ext)s"),
                      f"https://www.youtube.com/watch?v={v['id']}"],
                     attempts=3, base_delay=45.0, label="captions")
            if list(vdir.glob(f"{v['id']}.*.vtt")):
                log("    ok")
            else:
                log("    still unavailable")
                missing += 1
        log(f"\n# captions backfill done, {missing} still missing")
        return

    results = {}

    def handle(v):
        log(f"\n=== [{v['index']}] {v['id']}  {v['title'][:70]}")
        try:
            st = process_video(v, work, outdir, args.quality, args.lead_out,
                               args.interval, args.min_run,
                               scene_threshold=args.scene_threshold,
                               force=args.force or args.no_cache)
        except Exception as exc:  # keep going; report at the end
            log(f"    FAILED: {exc}")
            results[v["id"]] = {"video_id": v["id"], "index": v["index"],
                                "title": v["title"], "error": str(exc)}
            return False
        tag = "cached" if st.get("cached") else f"{st['elapsed_s']}s"
        log(f"    range={st['expected_range']} numbering={st.get('numbering')} "
            f"found={st['found']} missing={st['missing']} "
            f"unverified={st.get('unverified', [])} duplicates={st.get('duplicates', [])} ({tag})")
        for q in st["questions"]:
            log(f"      {q['file']}: Q{q['question']} t={q['time']} {q['source']}")
        results[v["id"]] = st
        return True

    failed = []
    for vi, v in enumerate(vids):
        if vi:
            time.sleep(args.pause)
        if not handle(v):
            failed.append(v)

    # Rate limits are usually transient, so retry the failures once after a
    # cooling-off pause: one run then gets as far as possible instead of leaving
    # a dozen videos for the next scheduled tick.
    if failed and args.retry_pause > 0:
        log(f"\n# cooling off {args.retry_pause:.0f}s, then retrying {len(failed)} video(s)")
        time.sleep(args.retry_pause)
        still = []
        for v in failed:
            time.sleep(args.pause)
            if not handle(v):
                still.append(v)
        log(f"# retry pass: recovered {len(failed) - len(still)}, still failing {len(still)}")

    results = list(results.values())

    # The manifest is derived from the per-video state files, not accumulated in
    # memory, so concurrent shard workers cannot lose each other's entries.
    man_path = work / "manifest.json"
    merged = {}
    for sf in sorted((work / "state").glob("*.json")):
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if st.get("video_id"):
            merged[st["video_id"]] = st
    man_path.write_text(json.dumps(sorted(merged.values(),
                                          key=lambda x: x.get("index") or 0),
                                   indent=2), encoding="utf-8")
    log(f"\n# manifest: {man_path} ({len(merged)} videos)")

    total = sum(1 for st in results for q in st.get("questions", []) if q.get("file"))
    missing = [f"Q{q['question']}" for st in results for q in st.get("questions", [])
               if not q["file"]]
    log(f"# this run wrote {total} question screenshots to {outdir}")
    if missing:
        log(f"# MISSING: {', '.join(missing)}")
    if failed:
        log(f"# FAILED videos: {[v['id'] for v in failed]}")


if __name__ == "__main__":
    main()
