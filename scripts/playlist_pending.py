#!/usr/bin/env python3
"""Cron MONITOR: print the videos in the playlist that still need processing.

Stdlib only - on purpose. This runs under the Hermes scheduler's own Python,
which has no numpy/Pillow, so it must not import the extraction pipeline.

Deterministic output by design: the scheduler compares this against the previous
tick and only wakes the agent when it changes, so there is no LLM cost while the
playlist is fully processed.

Because it reports *outstanding work* rather than the raw playlist, a run that
dies half-way leaves its videos listed and the next tick picks them up again.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYLIST = "https://www.youtube.com/playlist?list=PLB574eEmT4ofIr8LFjiKJfTjjg7StIAQm"
WORK = ROOT / "work"
OUTDIR = ROOT / "Questions" / "auto"


def ytdlp():
    found = shutil.which("yt-dlp")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "yt-dlp"
    if candidate.exists():
        return str(candidate)
    return None


def playlist_videos():
    exe = ytdlp()
    if not exe:
        raise RuntimeError("yt-dlp not found on PATH")
    r = subprocess.run(
        [exe, "--flat-playlist", "--no-warnings",
         "--print", "%(playlist_index)s\t%(id)s\t%(title)s", PLAYLIST],
        capture_output=True, text=True, check=True)
    out = []
    for line in r.stdout.splitlines():
        bits = line.split("\t")
        if len(bits) < 3 or bits[0] in ("", "NA"):
            continue
        out.append({"index": int(bits[0]), "id": bits[1], "title": "\t".join(bits[2:])})
    return sorted(out, key=lambda v: v["index"])


def main():
    try:
        vids = playlist_videos()
    except Exception as exc:
        # A fetch failure SHOULD wake the agent - print something non-empty.
        print(f"PLAYLIST-FETCH-FAILED {exc}")
        return 1

    lines = []
    for v in vids:
        sf = WORK / "state" / f"{v['id']}.json"
        tag = f"part={v['index']:>2} {v['id']} {v['title'][:58]}"
        if not sf.exists():
            lines.append(f"NEW       {tag}")
            continue
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            lines.append(f"UNREADABLE {tag}")
            continue
        if st.get("error"):
            lines.append(f"ERRORED   {tag}")
            continue
        qs = st.get("questions") or []
        if not qs:
            lines.append(f"NOQUESTION {tag}")
            continue
        missing = [q.get("question") for q in qs
                   if not q.get("file") or not (OUTDIR / q["file"]).exists()]
        if missing:
            lines.append(f"MISSING   {tag} -> {sorted(x for x in missing if x is not None)}")
        elif st.get("unverified"):
            lines.append(f"UNVERIFIED {tag} -> {st['unverified']}")

    print("\n".join(sorted(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
