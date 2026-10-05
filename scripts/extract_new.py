#!/usr/bin/env python3
"""Cron SCRIPT: bring the exam-question screenshot bank up to date.

Stdlib only - it shells out to the project venv (which has numpy/Pillow) to do
the real work, then prints a compact summary for the agent to report on.

Videos that are already done are skipped via cached state, so a tick with no new
playlist videos is cheap.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)


def main():
    cmd = [str(PY), str(ROOT / "scripts" / "extract_questions.py"),
           "--out", "Questions/auto", "--work", "work"]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"# extraction FAILED (exit={r.returncode})")
        print("\n".join((r.stdout or "").strip().splitlines()[-25:]))
        print("--- stderr ---")
        print("\n".join((r.stderr or "").strip().splitlines()[-25:]))
        return r.returncode

    man = ROOT / "work" / "manifest.json"
    if not man.exists():
        print("# no manifest produced")
        return 1

    entries = json.loads(man.read_text(encoding="utf-8"))
    total = sum(1 for e in entries for q in e.get("questions", []) if q.get("file"))
    print(f"# videos tracked: {len(entries)}   question images: {total}")
    for e in sorted(entries, key=lambda x: x.get("index") or 0):
        qs = e.get("questions") or []
        found = sum(1 for q in qs if q.get("file"))
        note = []
        if e.get("error"):
            note.append(f"ERROR: {e['error'][:80]}")
        if e.get("missing"):
            note.append(f"missing={e['missing']}")
        if e.get("unverified"):
            note.append(f"unverified={e['unverified']}")
        print(f"  part={e.get('index')} range={e.get('expected_range')} "
              f"found={found}/{len(qs)} {' '.join(note)}".rstrip())

    imgs = sorted((ROOT / "Questions" / "auto").glob("*.jpg"))
    numbered = sorted(p.stem for p in imgs if p.stem.startswith("q"))
    print(f"# on disk: {len(imgs)} images in Questions/auto")
    if numbered:
        print(f"# numbered questions: {numbered[0]} .. {numbered[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
