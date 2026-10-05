#!/usr/bin/env python3
"""Assemble the exam-question SQLite bank.

Joins three sources per question:
  * the extracted screenshot  (work/state/*.json -> Questions/auto/<label>.jpg)
  * OCR of that screenshot    (stem, options, which options are green)
  * the video captions        (explanation, and when each option is discussed)

Tables
------
videos          one row per playlist video
questions       one row per exam question: image, text, timestamps, explanation
options         one row per answer option, with its green flag and mention time
transcript      the full caption stream per video

Rebuilt from scratch on every run, so it is always consistent with the files.
"""
import argparse
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gs  # noqa: E402
from slide_ocr import parse_slide  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OPTION_MENTION = re.compile(r"\boption\s+([A-E])\b", re.I)
CORRECT_HINTS = re.compile(
    r"\b(?:correct answer|the answer is|best (?:answer|option|choice)|answers? (?:are|is))\b"
    r"[^.]{0,80}", re.I)

SCHEMA = """
DROP TABLE IF EXISTS options;
DROP TABLE IF EXISTS questions;
DROP TABLE IF EXISTS transcript;
DROP TABLE IF EXISTS videos;

CREATE TABLE videos (
    video_id     TEXT PRIMARY KEY,
    playlist_pos INTEGER,
    part         INTEGER,
    title        TEXT,
    url          TEXT,
    duration     REAL,
    numbering    TEXT,
    has_captions INTEGER,
    range_lo     INTEGER,
    range_hi     INTEGER
);

CREATE TABLE questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL REFERENCES videos(video_id),
    number        INTEGER,
    label         TEXT UNIQUE,
    image         TEXT,
    ocr_question  INTEGER,
    stem          TEXT,
    choose        INTEGER,
    correct       TEXT,
    t_question    REAL,
    t_answer      REAL,
    t_next        REAL,
    watch_url     TEXT,
    duplicate_of  INTEGER REFERENCES questions(id),
    green_frac    REAL,
    source        TEXT,
    answer_source TEXT,
    notes         TEXT,
    explanation   TEXT,
    options_json  TEXT
);

CREATE TABLE options (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id   INTEGER NOT NULL REFERENCES questions(id),
    letter        TEXT,
    text          TEXT,
    is_correct    INTEGER,
    green_px      INTEGER,
    t_mentioned   REAL
);

CREATE TABLE transcript (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL REFERENCES videos(video_id),
    t             REAL,
    text          TEXT
);

CREATE INDEX idx_questions_video ON questions(video_id);
CREATE INDEX idx_questions_number ON questions(number);
CREATE INDEX idx_options_question ON options(question_id);
CREATE INDEX idx_transcript_video ON transcript(video_id, t);
"""


def ocr_cached(image_path, cache_dir, green_min_px):
    """OCR with an on-disk cache: re-running the build must not re-OCR 250 images."""
    cache = cache_dir / f"{image_path.stem}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    res = parse_slide(image_path, green_min_px=green_min_px)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


# The presenter says "Question N" out loud before reading a question, and that
# announcement is the true start of its walkthrough: it lands 82-219 s (median
# ~131 s) BEFORE the answer highlight begins, because the stem and the options are
# read out first. Slicing captions between consecutive announcements therefore
# gives one question's walkthrough and none of its neighbour's. Slicing between
# answer windows instead (the original approach) drags in the whole of the next
# question's stem, options and opening reasoning, which is what made 304 of 320
# explanations end with "Question N+1. <next question's text>".
QUESTION_ANNOUNCE = re.compile(r"[Qq]uestion\s+(\d{1,3})\b")
# Sign-off phrases only. Deliberately does NOT match "subscribe" alone: Pub/Sub
# questions legitimately say "subscribe to the topic".
OUTRO = re.compile(r"\b(?:thanks?\s+for\s+watching|see\s+you\s+in\s+the\s+next"
                   r"|please\s+like|happy\s+learning)\b", re.I)


def split_cues(cues):
    """Cues split at every spoken heading, so a heading never sits inside a piece.

    Returns (pieces, announcements). One caption cue often carries the tail of the
    previous question *and* the next question's heading ("production environment.
    Question 75."), so slicing on cue boundaries alone truncates one question's
    last words and hands them to its neighbour. Splitting the cue fixes both: the
    text before the heading is nudged just before it so it belongs to the previous
    question, and the text after is nudged just past it so it belongs to the next.
    """
    pieces, ann = [], []
    for t, txt in cues:
        m = QUESTION_ANNOUNCE.search(txt)
        if not m:
            pieces.append((t, txt))
            continue
        before = txt[:m.start()].strip()
        after = txt[m.end():].strip()
        if before:
            pieces.append((t - 0.001, before))
        if after:
            pieces.append((t + 0.001, after))
        ann.append((t, int(m.group(1))))
    return pieces, ann


def explanation_for(cues, ann, num, t_question, t_next, duration=None):
    """Caption text belonging to one question's walkthrough.

    Starts at the question's own announcement and stops at the next one, so a
    question never inherits its neighbour's text. Falls back to the answer window
    when the announcement was not transcribed (58 of 340 questions, 20 of which
    are in the part whose captions were never fetchable).
    """
    if not cues:
        return ""
    start = None
    for t, n in ann:
        if num is not None and n == num and (start is None or t > start):
            start = t                      # each number is spoken exactly once
    if start is None:
        start = t_question if t_question is not None else cues[0][0]
    later = [t for t, _ in ann if t > start]
    end = later[0] if later else None
    if t_next is not None:
        end = t_next if end is None else min(end, t_next)
    if end is None:
        end = duration or (cues[-1][0] + 60)
    text = " ".join(txt for t, txt in cues if start <= t < end)
    text = OUTRO.split(text)[0]
    text = QUESTION_ANNOUNCE.sub("", text, count=1)    # drop the spoken heading
    return " ".join(text.lstrip(" .;:,-").split())


def answer_text(options_json: str, correct: str) -> str:
    """Text of the correct option(s), for comparing duplicate copies.

    Copies of the same question can have their options SHUFFLED - Q181 and Q186
    are the same question whose answer is B in one and C in the other - so
    comparing letters reports a false conflict. Compare the option text instead.
    """
    if not correct:
        return ""
    try:
        opts = {o.get("letter"): " ".join((o.get("text") or "").split()).lower()
                for o in json.loads(options_json or "[]")}
    except (ValueError, TypeError):
        return ""
    return " | ".join(opts.get(l.strip(), "") for l in correct.split(","))


def loose(text: str) -> str:
    """Strip everything but letters and digits.

    The two copies of a repeated question are OCR'd from different frames, so the
    same answer comes out as "traffic flow" in one and "traffic flow." in the
    other, or "on- premises" vs "on-premises". Those are the same answer.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def same_answer(ktext: str, atext: str) -> bool:
    """True when two copies describe the same correct answer."""
    if not ktext or not atext:
        return True                      # nothing to compare; do not cry conflict
    return difflib.SequenceMatcher(None, loose(ktext), loose(atext)).ratio() >= 0.90


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work")
    ap.add_argument("--images", default="Questions/auto")
    ap.add_argument("--db", default="exam/exam.db")
    ap.add_argument("--green-min-px", type=int, default=120)
    ap.add_argument("--no-ocr-cache", action="store_true")
    args = ap.parse_args()

    work = ROOT / args.work
    imgs = ROOT / args.images
    db_path = ROOT / args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = work / "ocr"
    if args.no_ocr_cache and cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            f.unlink()

    states = []
    for sf in sorted((work / "state").glob("*.json")):
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if st.get("questions"):
            states.append(st)
    states.sort(key=lambda s: s.get("index") or 0)
    if not states:
        print("no per-video state found - run extract_questions.py first")
        return 1

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    n_q = n_opt = n_tx = 0
    for st in states:
        vid = st["video_id"]
        rng = st.get("expected_range") or [None, None]
        cur.execute(
            "INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?)",
            (vid, st.get("index"), st.get("part"), st.get("title"),
             f"https://www.youtube.com/watch?v={vid}", st.get("duration"),
             st.get("numbering"), 1 if st.get("has_captions") else 0,
             rng[0], rng[1]))

        cues = []
        vtt = next(iter((work / "videos").glob(f"{vid}.*.vtt")), None)
        if vtt is not None:
            cues = gs.parse_vtt(vtt)
            cur.executemany("INSERT INTO transcript (video_id, t, text) VALUES (?,?,?)",
                            [(vid, t, txt) for t, txt in cues])
            n_tx += len(cues)

        qs = st["questions"]
        pieces, ann = split_cues(cues)
        for i, q in enumerate(qs):
            label = q.get("stem") or f"q{q['number']:03d}"
            image = q.get("file")
            t_answer = q.get("time")
            window = q.get("window")
            # Where the question's ANSWERED slide starts. The walkthrough itself
            # starts earlier, at the spoken announcement - see explanation_for.
            t_question = window[0] if window else t_answer
            nxt = qs[i + 1] if i + 1 < len(qs) else None
            t_next = None
            if nxt is not None:
                t_next = (nxt.get("window") or [nxt.get("time")])[0] or nxt.get("time")

            explanation = explanation_for(
                pieces, ann, q.get("number") or q.get("question"), t_question,
                t_next, st.get("duration"))

            res = {"ok": False, "stem": "", "options": [], "correct": [],
                   "question_number": None, "choose": None}
            if image and (imgs / image).exists():
                res = ocr_cached(imgs / image, cache_dir, args.green_min_px)

            correct = res.get("correct") or []
            watch = None
            if t_answer is not None:
                watch = f"https://youtu.be/{vid}?t={int(t_answer)}"

            cur.execute(
                """INSERT INTO questions
                   (video_id, number, label, image, ocr_question, stem, choose,
                    correct, t_question, t_answer, t_next, watch_url, green_frac,
                    source, answer_source, notes, explanation, options_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (vid, q.get("number") or q.get("question"), label, image,
                 res.get("question_number"),
                 res.get("stem") or "", res.get("choose"),
                 ",".join(correct), t_question, t_answer, t_next, watch,
                 q.get("green_frac"), q.get("source"), res.get("answer_source"),
                 "; ".join(res.get("notes") or []), explanation,
                 json.dumps(res.get("options") or [], ensure_ascii=False)))
            qid = cur.lastrowid
            n_q += 1

            for o in res.get("options") or []:
                letter = o.get("letter")
                t_men = None
                if explanation and letter:
                    for m in OPTION_MENTION.finditer(explanation):
                        if m.group(1).upper() == letter:
                            # Map the character offset back to a caption time.
                            offset = len(explanation[:m.start()])
                            acc = 0
                            for t, txt in (c for c in cues if t_question <= c[0] <
                                           (t_next if t_next is not None
                                            else st.get("duration") or 1e9)):
                                acc += len(txt) + 1
                                if acc >= offset:
                                    t_men = t
                                    break
                            break
                cur.execute(
                    """INSERT INTO options
                       (question_id, letter, text, is_correct, green_px, t_mentioned)
                       VALUES (?,?,?,?,?,?)""",
                    (qid, letter, o.get("text"), 1 if letter in correct else 0,
                     o.get("green_px"), t_men))
                n_opt += 1

    conn.commit()

    # Sanity report straight out of the database, not from the in-memory data.
    print(f"# db: {db_path}")
    print(f"# videos={cur.execute('SELECT COUNT(*) FROM videos').fetchone()[0]} "
          f"questions={cur.execute('SELECT COUNT(*) FROM questions').fetchone()[0]} "
          f"options={cur.execute('SELECT COUNT(*) FROM options').fetchone()[0]} "
          f"transcript_cues={cur.execute('SELECT COUNT(*) FROM transcript').fetchone()[0]}")
    for row in cur.execute(
            """SELECT COUNT(*), SUM(stem != ''), SUM(correct != ''),
                      SUM(explanation != '')
               FROM questions"""):
        print(f"# questions with OCR stem={row[1]}, with correct letters={row[2]}, "
              f"with explanation text={row[3]} of {row[0]}")
    bad = cur.execute(
        """SELECT number, label, ocr_question FROM questions
           WHERE stem = '' OR correct = '' ORDER BY video_id, number LIMIT 25""").fetchall()
    if bad:
        print(f"# {len(bad)} question(s) lacking OCR text or a green answer, e.g.: {bad[:12]}")
    mismatch = cur.execute(
        """SELECT number, ocr_question, label FROM questions
           WHERE ocr_question IS NOT NULL AND number IS NOT NULL AND ocr_question != number
           LIMIT 20""").fetchall()
    if mismatch:
        print(f"# WARNING: {len(mismatch)} question number(s) disagree with the slide's "
              f"own numbering, e.g. {mismatch[:10]}")
    mult = cur.execute(
        """SELECT COUNT(*) FROM questions WHERE choose IS NOT NULL
           AND correct != '' AND (LENGTH(correct) - LENGTH(REPLACE(correct, ',', '')) + 1)
           NOT BETWEEN 2 AND choose""").fetchone()[0]
    if mult:
        print(f"# WARNING: {mult} multi-answer question(s) whose green count does not "
              f"match the 'choose N' instruction")
    dupes = cur.execute(
        """SELECT number, GROUP_CONCAT(label) FROM questions
           WHERE number IS NOT NULL GROUP BY number HAVING COUNT(*) > 1
           ORDER BY number LIMIT 20""").fetchall()
    if dupes:
        # A number can only belong to one question. When two rows claim it, the
        # one with an identified answer is the real occupant; the other (usually
        # an intro/overview slide that was numbered backwards into the previous
        # video's range) keeps its image but gives up the number.
        resolved = []
        for number, labels in dupes:
            rows = cur.execute(
                """SELECT id, label, correct, options_json FROM questions
                   WHERE number = ? ORDER BY (correct != '') DESC,
                            json_array_length(options_json) DESC, id""",
                (number,)).fetchall()
            keeper = rows[0]
            for qid, label, correct, opts in rows[1:]:
                note = ("number released: it shares this number with "
                        f"{keeper[1]}, which has an identified answer")
                cur.execute(
                    "UPDATE questions SET number = NULL, "
                    "notes = COALESCE(notes || '; ', '') || ? WHERE id = ?",
                    (note, qid))
                resolved.append((number, label, "-> NULL"))
        conn.commit()
        print(f"# resolved {len(resolved)} duplicated number(s): {resolved}")
        print(f"#   kept: {[(d[0], d[1].split(',')[0]) for d in dupes]}")
    else:
        print("# no duplicated question numbers")
    # The playlist repeats some questions across parts (14 of them). Mark the
    # later copy so a generated exam cannot ask the same question twice, and so a
    # concept page does not list it as two separate questions. Copies can have
    # shuffled options, so agreement is judged on the ANSWER TEXT, not the letter.
    groups: dict[str, list] = {}
    for qid, label, number, stem, correct, oj in cur.execute(
            "SELECT id, label, number, stem, correct, options_json FROM questions"):
        if not stem:
            continue
        key = re.sub(r"[^a-z0-9]", "", stem.lower())[:120]
        groups.setdefault(key, []).append((qid, label, number, correct, oj))
    dup_groups = dup_rows = 0
    conflicts = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (r[2] is None, r[2] or 0))
        keeper = rows[0]
        ktext = answer_text(keeper[4], keeper[3])
        for qid, label, number, correct, oj in rows[1:]:
            atext = answer_text(oj, correct)
            if not same_answer(ktext, atext):
                conflicts.append((number, label, correct, keeper[1]))
                cur.execute(
                    "UPDATE questions SET notes = COALESCE(notes || '; ', '') || ?"
                    " WHERE id = ?",
                    (f"same question text as {keeper[1]} but the answer text differs -"
                     " check which key is right", qid))
            else:
                cur.execute("UPDATE questions SET duplicate_of = ? WHERE id = ?",
                            (keeper[0], qid))
                dup_rows += 1
        dup_groups += 1
    conn.commit()
    print(f"# duplicate questions: {dup_groups} repeated question(s), {dup_rows} later "
          f"copies flagged via duplicate_of")
    if conflicts:
        print(f"# WARNING: {len(conflicts)} repeated question(s) whose answer TEXT "
              f"disagrees: {conflicts}")

    # Rows that are not usable as exam questions, listed so they can be reviewed
    # rather than silently trusted or silently dropped.
    review = cur.execute(
        """SELECT number, label, notes FROM questions
           WHERE correct = '' OR json_array_length(options_json) = 0
           ORDER BY video_id, number""").fetchall()
    if review:
        print(f"# {len(review)} question(s) needing review: {review}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
