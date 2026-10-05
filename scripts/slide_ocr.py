#!/usr/bin/env python3
"""OCR a question slide into structured text.

Produces, per screenshot:
  - the "Question N" number
  - the question stem
  - each answer option (letter -> text)
  - WHICH options are highlighted green (the correct answers)

Mapping green -> option letters is done by geometry, not by guessing colours from
a vision model: OCR gives each text line a bounding box, and an option counts as
correct when its box contains the green highlight.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gs import green_mask  # noqa: E402

TESSERACT = (shutil.which("tesseract")
             or r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# An option marker must carry punctuation ("A.", "B)", "C:") - a bare letter
# would match a stem line that merely starts with the word "A" (e.g. "A
# development team has launched...").
OPT_WORD = re.compile(r"^([A-E])[.):]$")
QNUM_RE = re.compile(r"Question\s+(\d(?:\s?\d){0,2})", re.I)
CHOOSE_RE = re.compile(r"(?:Choose|Select|Pick)\s+(two|three|four|2|3|4)", re.I)
SPLIT_RE = re.compile(r"\b([A-E])[.)]\s+")

# Slide text is ~17px tall at 720p, which tesseract reads unreliably - it silently
# drops very short option lines like "A. 8". Upscaling 2x before OCR recovers
# them. Green pixel counts are normalised back to the original scale below.
OCR_SCALE = 2

# The "Question N" heading uses a large thin font in which tesseract renders the
# digit 7 as "/" ("Question 17" -> "Question Lf"), so the heading gets its own
# pass: crop the top-left corner, upscale, treat it as a single line and allow
# only digits through. That recovers 17/26/30/70/87 correctly.
HEADING_CROP = (0.0, 0.0, 0.45, 0.13)
HEADING_SCALE = 3


def read_heading_number(image_path):
    """Read the printed question number from the slide heading, digits only.

    Kept for reference, NOT used by parse_slide: measured against the labels of
    the ranged videos it agreed only ~50% of the time (73 disagreements out of
    153), because the crop also sweeps in digits from the stem's first line.
    Prefer the assigned number from the title range + slide order.
    """
    import tempfile

    im = Image.open(image_path).convert("L")
    w, h = im.size
    strip = im.crop((int(w * HEADING_CROP[0]), int(h * HEADING_CROP[1]),
                     int(w * HEADING_CROP[2]), int(h * HEADING_CROP[3])))
    strip = strip.resize((strip.width * HEADING_SCALE, strip.height * HEADING_SCALE),
                         Image.LANCZOS)
    tmp = Path(tempfile.gettempdir()) / f"hdr_{Path(image_path).stem}.png"
    strip.save(tmp)
    try:
        r = subprocess.run(
            [TESSERACT, str(tmp), "stdout", "--psm", "7",
             "-c", "tessedit_char_whitelist=0123456789"],
            capture_output=True, text=True, check=False)
    finally:
        tmp.unlink(missing_ok=True)
    m = re.search(r"\d{1,3}", r.stdout)
    return int(m.group(0)) if m else None


def tesseract_tsv(image_path, psm=4):
    """Run tesseract and return its word-level boxes."""
    r = subprocess.run([TESSERACT, str(image_path), "stdout", "tsv", "--psm", str(psm)],
                       capture_output=True, text=True, check=False)
    words = []
    for line in r.stdout.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12:
            continue
        try:
            left, top, w, h = (int(f[6]), int(f[7]), int(f[8]), int(f[9]))
            conf = float(f[10])
        except ValueError:
            continue
        text = f[11].strip()
        if not text or conf < 30:
            continue
        words.append({"blk": f[2], "par": f[3], "ln": f[4], "left": left, "top": top,
                      "w": w, "h": h, "text": text})
    return words


def group_lines(words):
    """Group words into text lines via the TSV block/paragraph/line ids."""
    groups = {}
    for w in words:
        groups.setdefault((w["blk"], w["par"], w["ln"]), []).append(w)
    lines = []
    for ws in groups.values():
        ws.sort(key=lambda x: x["left"])
        lines.append({
            "left": min(x["left"] for x in ws),
            "top": min(x["top"] for x in ws),
            "right": max(x["left"] + x["w"] for x in ws),
            "bottom": max(x["top"] + x["h"] for x in ws),
            "text": " ".join(x["text"] for x in ws),
        })
    lines.sort(key=lambda l: (l["top"], l["left"]))
    return lines


def _green_count(mask, box, pad=4):
    h, w = mask.shape
    y0 = max(0, box["top"] - pad)
    y1 = min(h, box["bottom"] + pad)
    x0 = max(0, box["left"] - pad)
    x1 = min(w, box["right"] + pad)
    if y1 <= y0 or x1 <= x0:
        return 0
    return int(mask[y0:y1, x0:x1].sum())


def parse_slide(image_path, green_min_px=120, psm=4, scale=OCR_SCALE):
    """OCR a slide and work out the stem, the options and the correct ones.

    `green_min_px` is expressed in ORIGINAL-resolution pixels; the OCR runs on an
    upscaled copy, so measured green counts are divided back down to match.
    """
    import tempfile

    im = Image.open(image_path).convert("RGB")
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    arr = np.asarray(im)
    mask = green_mask(arr)

    tmp = Path(tempfile.gettempdir()) / f"slide_ocr_{Path(image_path).stem}.png"
    im.save(tmp)
    try:
        lines = group_lines(tesseract_tsv(tmp, psm=psm))
    finally:
        tmp.unlink(missing_ok=True)

    if not lines:
        return {"ok": False, "reason": "no text recognised", "lines": [],
                "stem": "", "options": [], "correct": [],
                "answer_source": None, "notes": ["no text recognised"]}

    norm = float(scale * scale)  # green px -> original-resolution equivalents
    left_margin = min(l["left"] for l in lines)

    # Locate option-start lines: a lone "A."/"B)"/"C:" at the text margin, kept
    # only in strictly increasing letter order. Options always run A, B, C..., so
    # a repeat or a step backwards means a stem line was misread as an option.
    starts = []
    last = ""
    for i, ln in enumerate(lines):
        parts = ln["text"].split()
        if not parts:
            continue
        m = OPT_WORD.match(parts[0])
        if m and ln["left"] <= left_margin + 50 and m.group(1) > last:
            starts.append((i, m.group(1), parts))
            last = m.group(1)

    qnum = None
    # Read the number from the heading line only, preferring an unbroken digit run:
    # "Question 26" followed by stem text "2..." must not become 262, while a glyph
    # tesseract split as "Question 1 7" should still give 17.
    #
    # This value is ADVISORY. No cheap tesseract configuration reads this heading
    # reliably: in the large thin heading font the digit 7 comes out as "/", and a
    # dedicated crop+upscale+digit-whitelist pass agreed with the true number only
    # about half the time (it also catches digits from the stem below). The
    # authoritative number comes from the title's declared range plus slide order,
    # which is verified by exact count matching.
    m = re.match(r"\s*Question\s+(\d{1,3})(?:\s?(\d)\b)?", lines[0]["text"], re.I)
    if m:
        run, extra = m.group(1), m.group(2)
        if extra and len(run) == 1:
            run += extra
        qnum = int(run)

    stem, options = "", []
    if starts:
        first_opt = starts[0][0]
        head = lines[:first_opt]
        # Remove ONLY the "Question N" heading from the first line. Stripping with
        # a loose regex would also eat the stem's own leading digits
        # ("Question 26 2-factor authentication..." -> "factor authentication...").
        first_text = head[0]["text"]
        mh = re.match(r"\s*Question\s+\d{1,3}(?:\s?\d)?\s*", first_text, re.I)
        if mh:
            first_text = first_text[mh.end():]
        stem_parts = ([first_text] if first_text.strip() else []) + \
                     [l["text"] for l in head[1:]]
        stem = " ".join(stem_parts).strip()
        for k, (idx, letter, parts) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
            chunk = lines[idx:end]
            text_words = list(parts[1:])
            for extra in chunk[1:]:
                text_words.append(extra["text"])
            box = {
                "left": min(x["left"] for x in chunk),
                "top": min(x["top"] for x in chunk),
                "right": max(x["right"] for x in chunk),
                "bottom": max(x["bottom"] for x in chunk),
            }
            options.append({
                "letter": letter,
                "text": " ".join(text_words).strip(),
                "box": box,
                "green_px": round(_green_count(mask, box) / norm),
            })
    else:
        # Tesseract merged the options into the stem; split on "A. " / "B. " etc.
        joined = " ".join(l["text"] for l in lines)
        stem = re.sub(r"^\s*Question\s+\d{1,3}(?:\s?\d)?\s*", "", joined, flags=re.I).strip()
        found = list(SPLIT_RE.finditer(joined))
        if found:
            stem = re.sub(r"^\s*Question\s+\d{1,3}(?:\s?\d)?\s*", "",
                          joined[:found[0].start()], flags=re.I).strip()
            for k, f in enumerate(found):
                end = found[k + 1].start() if k + 1 < len(found) else len(joined)
                options.append({"letter": f.group(1),
                                "text": joined[f.end():end].strip(),
                                "box": None, "green_px": None})
        # Without line geometry the green lines cannot be attributed to options,
        # so fall back to hoisting the green text bands and matching them below.
        _match_green_by_text(arr, options, mask, lines)

    correct = [o["letter"] for o in options
               if (o.get("green_px") or 0) >= green_min_px]
    answer_source = "green" if correct else None
    if not correct:
        # A few slides mark the answer in text instead of green highlighting.
        correct = [o["letter"] for o in options
                   if re.search(r"=>\s*correct|\(correct\)|\u2713|\u2714",
                                o.get("text") or "", re.I)]
        if correct:
            answer_source = "text-marker"

    # Flag slides that look structurally different from the common layout, so a
    # human can review them instead of trusting a silently poor parse.
    notes = []
    if not options:
        notes.append("no options parsed (unusual layout, e.g. two columns)")
    elif len(options) < 3:
        notes.append(f"only {len(options)} option(s) parsed")
    if not correct:
        notes.append("no answer identified")
    if not qnum:
        notes.append("no 'Question N' heading found")

    m = CHOOSE_RE.search(stem)
    choose = {"two": 2, "three": 3, "four": 4}.get(m.group(1).lower(), None) if m else None
    if choose is None and m and m.group(1).isdigit():
        choose = int(m.group(1))

    return {
        "ok": True,
        "question_number": qnum,
        "stem": stem,
        "options": options,
        "correct": correct,
        "answer_source": answer_source,
        "notes": notes,
        "choose": choose,
        "lines": [(l["top"], l["bottom"], l["text"]) for l in lines],
        "green_min_px": green_min_px,
    }


def _match_green_by_text(arr, options, mask, lines):
    """Last resort: mark an option green if its own text is drawn in green.

    Used when OCR did not give usable option boxes. Compares the mean colour of
    each option's characters against the green mask colour by re-OCRing nothing -
    it simply checks whether green pixels fall in the vertical band of the text
    that contains the option's opening words.
    """
    green_rows = np.where(mask.any(axis=1))[0]
    if not len(green_rows):
        return
    for o in options:
        key = o["text"][:24].lower()
        if not key:
            continue
        for top, bottom, text in lines:
            if key[:12] in text.lower():
                band = mask[max(0, top - 2):bottom + 2]
                o["green_px"] = int(band.sum())
                break


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--green-min-px", type=int, default=120)
    ap.add_argument("--psm", type=int, default=4)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    for img in args.images:
        res = parse_slide(img, args.green_min_px, args.psm)
        if args.json:
            print(json.dumps({"file": Path(img).name, **res}, indent=1))
            continue
        print(f"\n=== {Path(img).name}  ok={res['ok']} "
              f"Q={res.get('question_number')} choose={res.get('choose')} "
              f"correct={res['correct']}")
        print(f"  stem: {res['stem'][:150]}")
        for o in res["options"]:
            px = o.get("green_px")
            flag = "GREEN" if (px or 0) >= args.green_min_px else "     "
            print(f"  {o['letter']}. [{flag} {px}px] {o['text'][:90]}")


if __name__ == "__main__":
    main()
