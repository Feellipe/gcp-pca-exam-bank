#!/usr/bin/env python3
"""Audit the extracted question bank: OCR coverage and internal consistency.

Run after extract_questions.py / build_exam_db.py to see, at a glance, how much
of the bank is usable and where the weak spots are.

Usage: audit_ocr.py [--images Questions/auto] [--ocr work/ocr] [--db exam/exam.db]
"""
import argparse
import collections
import glob
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="Questions/auto")
    ap.add_argument("--ocr", default="work/ocr")
    ap.add_argument("--db", default="exam/exam.db")
    ap.add_argument("--detail", action="store_true",
                    help="print the slides flagged by each check")
    args = ap.parse_args()

    imgs = ROOT / args.images
    labels = sorted(p.stem for p in imgs.glob("*.jpg"))
    print(f"# images on disk: {len(labels)}  "
          f"(q..={sum(1 for l in labels if l.startswith('q'))}, "
          f"p..={sum(1 for l in labels if l.startswith('p'))})")

    ocr_dir = ROOT / args.ocr
    results = {}
    for f in sorted(ocr_dir.glob("*.json")):
        try:
            results[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    print(f"# ocr cached: {len(results)}")

    missing_ocr = [l for l in labels if l not in results]
    no_stem = [l for l, d in results.items() if not d.get("stem")]
    no_green = [l for l, d in results.items() if not d.get("correct")]
    no_qnum = [l for l, d in results.items() if d.get("question_number") is None]
    optcounts = collections.Counter(len(d.get("options") or []) for d in results.values())
    chooses = [(l, d["choose"], len(d.get("correct") or []))
               for l, d in results.items() if d.get("choose")]
    mismatch = [c for c in chooses if c[2] != c[1]]

    print(f"# not OCR'd yet      : {len(missing_ocr)} {missing_ocr[:8]}")
    print(f"# no stem extracted  : {len(no_stem)} {no_stem[:8]}")
    print(f"# no green answer    : {len(no_green)} {no_green[:8]}")
    print(f"# no 'Question N'    : {len(no_qnum)} {no_qnum[:8]}")
    print(f"# options per slide  : {dict(sorted(optcounts.items()))}")
    print(f"# multi-answer (choose N): {len(chooses)}, "
          f"green count disagrees: {len(mismatch)} {mismatch[:8]}")

    # The slide's own printed number is advisory only: tesseract misreads the
    # digit 7 in this font ("Question 17" -> "Question Lf"/"Question 16"), so a
    # disagreement is reported as information, not as a defect. The assigned
    # number comes from the title range + slide order, which is count-verified.
    disagree = []
    for label, d in results.items():
        qn = d.get("question_number")
        if qn is not None and label.startswith("q") and label[1:].isdigit():
            if abs(int(label[1:]) - qn) > 1:
                disagree.append((label, qn))
    print(f"# label vs slide number disagree (informational): {len(disagree)} "
          f"{disagree[:8]}")

    flagged_notes = [(l, d.get("notes")) for l, d in results.items() if d.get("notes")]
    print(f"# slides with parse notes: {len(flagged_notes)}")
    for label, notes in flagged_notes[:12]:
        print(f"    {label}: {'; '.join(notes)}")

    if args.detail:
        flagged = set(no_green) | {l for l, c in disagree} | {l for l, _, _ in mismatch}
        flagged |= {l for l, d in results.items() if len(d.get("options") or []) < 4}
        flagged |= set(no_qnum)
        for label in sorted(flagged):
            d = results.get(label)
            if not d:
                continue
            opts = ", ".join(f"{o['letter']}={o.get('green_px')}px" for o in d.get("options") or [])
            print(f"\n  [{label}] slide_q={d.get('question_number')} choose={d.get('choose')} "
                  f"correct={d.get('correct')}")
            print(f"    stem: {(d.get('stem') or '')[:180]}")
            print(f"    opts: {opts}")

    db = ROOT / args.db
    if db.exists():
        # Read-only: the DB may be being rebuilt by another process right now.
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        q = "SELECT COUNT(*), SUM(stem != ''), SUM(correct != ''), SUM(explanation != '') FROM questions"
        total, stems, greens, expl = conn.execute(q).fetchone()
        print(f"# DB: {total} questions, {stems} with stem, {greens} with answers, "
              f"{expl} with explanation text")
        rows = conn.execute(
            """SELECT v.part, v.video_id, COUNT(*) FROM questions q
               JOIN videos v ON v.video_id = q.video_id
               GROUP BY v.video_id ORDER BY v.playlist_pos""").fetchall()
        for part, vid, n in rows:
            print(f"    part={part:>2} {vid}  {n} questions")
        conn.close()
    else:
        print(f"# no database at {db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
