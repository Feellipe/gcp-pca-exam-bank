#!/usr/bin/env python3
"""Assemble the single-file practice exam from exam.db.

The output is ONE self-contained HTML file (no external CSS, JS, fonts or
images) so it can be sent to a phone and opened offline. CSS and JS live as
separate components in `exam-app/assets/` and are inlined here, so the app can
be restyled without touching the exported artifact.

Usage:
    python scripts/export_exam_app.py [--out exam-app/pca-exam.html]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
APP = ROOT / "exam-app"

# 50 questions = 120 minutes, the real exam's ratio.
SECONDS_PER_QUESTION = 120 * 60 // 50      # 144

# Concept-category slug -> the label the phone shows.
CAT_LABELS = {
    "compute": "Compute", "storage": "Storage", "database": "Database",
    "data": "Data", "ai": "AI", "network": "Network", "security": "Security",
    "ops": "Ops", "devops": "DevOps", "hybrid": "Hybrid", "cost": "Cost",
}


# --------------------------------------------------------------------- markdown
# Trap pages link to each other ([[slug]]) and also to entity pages that only
# exist in the wiki. The offline app carries just the trap pages, so the renderer
# has to know which targets are bundled; the rest become plain references.
_TRAP_SLUGS: set[str] = set()


def _inline(s: str) -> str:
    """Escape, then apply the small markdown subset the trap pages use."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    def link(m: re.Match) -> str:
        target = m.group(1) or m.group(3)
        text = m.group(2) or target
        if target in _TRAP_SLUGS:
            return ('<a class="tl" data-act="trapnav" data-slug="' + target + '">'
                    + text + "</a>")
        return '<span class="xref">' + text + "</span>"

    return re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]", link, s)


def md_to_html(md: str) -> str:
    """Render the markdown subset used by the hand-written trap pages.

    Deliberately small: headings, bullet lists, blockquotes, paragraphs. The
    trap pages are the only markdown the app carries.
    """
    out: list[str] = []
    ul = quote = False

    def close() -> None:
        nonlocal ul, quote
        if ul:
            out.append("</ul>")
            ul = False
        if quote:
            out.append("</blockquote>")
            quote = False

    for raw in md.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            close()
            continue
        head = re.match(r"^(#{1,4})\s+(.*)$", line)
        if head:
            close()
            lvl = min(len(head.group(1)) + 1, 5)     # '# x' -> h2, '## x' -> h3
            out.append(f"<h{lvl}>{_inline(head.group(2).strip())}</h{lvl}>")
            continue
        if line.startswith("> "):
            if ul:
                out.append("</ul>")
                ul = False
            if not quote:
                out.append("<blockquote>")
                quote = True
            else:
                out.append("<br>")
            out.append(_inline(line[2:].strip()))
            continue
        if re.match(r"^[-*]\s+", line):
            if quote:
                out.append("</blockquote>")
                quote = False
            if not ul:
                out.append("<ul>")
                ul = True
            item = re.sub(r"^[-*]\s+", "", line)
            out.append("<li>" + _inline(item) + "</li>")
            continue
        close()
        out.append(f"<p>{_inline(line)}</p>")

    close()
    return "\n".join(out)


# ------------------------------------------------------------------- trap pages
def read_traps(number_to_label: dict[int, str]) -> tuple[dict, dict, list]:
    """Hand-written trap pages -> (pages, label -> [traps], warnings)."""
    pages: dict[str, dict] = {}
    by_label: dict[str, list] = collections.defaultdict(list)
    problems: list[str] = []
    tdir = WIKI / "concepts"
    files = sorted(tdir.glob("*.md")) if tdir.exists() else []
    global _TRAP_SLUGS
    _TRAP_SLUGS = {p.stem for p in files}
    for path in files:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        if not m:
            problems.append(f"{path.name}: no frontmatter, skipped")
            continue
        fm, body = m.group(1), m.group(2)
        tm = re.search(r"^title:\s*(.+)$", fm, re.M)
        title = tm.group(1).strip() if tm else path.stem.replace("-", " ").title()
        slug = path.stem
        pages[slug] = {"title": title, "html": md_to_html(body)}
        qm = re.search(r"^questions:\s*\[(.*?)\]", fm, re.M | re.S)
        nums = [int(x) for x in re.findall(r"\d+", qm.group(1))] if qm else []
        for num in nums:
            label = number_to_label.get(num)
            if label:
                by_label[label].append({"slug": slug, "title": title})
            else:
                problems.append(f"{slug}: question number {num} is not in the bank")
    return pages, by_label, problems


# ------------------------------------------------------------------------ build
def build(out_path: Path) -> int:
    db = ROOT / "exam" / "exam.db"
    if not db.exists():
        print(f"# missing {db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    opts: dict[int, list] = collections.defaultdict(list)
    for r in conn.execute("SELECT * FROM options ORDER BY question_id, letter"):
        opts[r["question_id"]].append(r)

    concepts: dict[int, list] = collections.defaultdict(list)
    for r in conn.execute(
            "SELECT qc.question_id, c.name, c.category FROM question_concepts qc"
            " JOIN concepts c ON c.id = qc.concept_id ORDER BY c.category, c.name"):
        concepts[r["question_id"]].append({"name": r["name"], "cat": r["category"]})

    rows = [dict(r) for r in conn.execute("SELECT * FROM questions ORDER BY number")]
    number_to_label = {r["number"]: r["label"] for r in rows if r["number"] is not None}

    questions, skipped = [], []
    for q in rows:
        o = opts[q["id"]]
        letters = {x["letter"] for x in o}
        correct = (q["correct"] or "").strip()
        why = None
        if len(o) < 2:
            why = f"only {len(o)} option(s) parsed"
        elif not correct:
            why = "no correct answer identified"
        elif not all(p.strip() in letters for p in correct.split(",")):
            why = "answer letter not among its own options"
        if why:
            skipped.append((q["label"], q["number"], why))
            continue
        if q["duplicate_of"]:
            skipped.append((q["label"], q["number"], "repeat of an earlier question"))
            continue
        questions.append({
            "n": q["number"], "l": q["label"], "stem": q["stem"],
            "o": [{"l": x["letter"], "t": x["text"]} for x in o],
            "correct": ",".join(p.strip() for p in correct.split(",")),
            "concepts": concepts[q["id"]], "w": q["watch_url"],
            "e": q["explanation"] or "",
        })

    cat_counts = collections.Counter()
    for q in questions:
        for c in {c["cat"] for c in q["concepts"]}:
            cat_counts[c] += 1
    categories = [
        {"cat": c, "label": CAT_LABELS.get(c, c.title()), "n": n}
        for c, n in cat_counts.most_common()
    ]

    traps, q_traps, problems = read_traps(number_to_label)
    # A trap page may cite a question this app excludes (a duplicate, or one whose
    # slide never parsed). Drop those keys so the payload carries no dead pointers.
    in_app = {q["l"] for q in questions}
    q_traps = {k: v for k, v in q_traps.items() if k in in_app}
    data = {
        "generated": date.today().isoformat(),
        "source": "CertPro Deep Dive GCP Cloud Architect",
        "per_question_seconds": SECONDS_PER_QUESTION,
        "categories": categories,
        "questions": questions,
        "traps": traps,
        "q_traps": {k: v for k, v in q_traps.items()},
    }

    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")          # safe inside <script>
    template = (APP / "app.template.html").read_text(encoding="utf-8")
    css = (APP / "assets" / "exam.css").read_text(encoding="utf-8")
    js = (APP / "assets" / "exam.js").read_text(encoding="utf-8")
    for token in ("/*__EXAM_CSS__*/", "__EXAM_DATA__", "/*__EXAM_JS__*/"):
        if token not in template:
            print(f"# template is missing {token}", file=sys.stderr)
            return 1
    if "</script" in js.lower():
        print("# exam.js contains a closing script tag; that would break the page",
              file=sys.stderr)
        return 1
    html = (template.replace("/*__EXAM_CSS__*/", css)
                    .replace("__EXAM_DATA__", payload)
                    .replace("/*__EXAM_JS__*/", js))
    out_path.write_text(html, encoding="utf-8")

    print(f"# wrote {out_path}  ({len(html.encode('utf-8'))/1e6:.2f} MB)")
    print(f"# questions: {len(questions)} gradeable "
          f"(excluded {len(skipped)}: {len([s for s in skipped if s[2].startswith('repeat')])}"
          f" repeats + {len([s for s in skipped if not s[2].startswith('repeat')])} unparseable)")
    print(f"# categories: " + ", ".join(f"{c['label']}={c['n']}" for c in categories))
    print(f"# trap pages embedded: {len(traps)} -> "
          f"{sum(len(v) for v in q_traps.values())} question links")
    print(f"# payload: {len(payload.encode('utf-8'))/1e6:.2f} MB"
          f" | css {len(css)/1000:.0f} KB | js {len(js)/1000:.0f} KB")
    multi = [q for q in questions if len(q["correct"].split(",")) > 1]
    print(f"# multi-answer questions: {len(multi)} "
          f"| with explanation: {len([q for q in questions if q['e'].strip()])}")
    for label, num, why in skipped:
        print(f"#   excluded {label} (#{num}): {why}")
    for p in problems:
        print(f"#   WARNING trap frontmatter: {p}")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(APP / "pca-exam.html"))
    args = ap.parse_args()
    return build(Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
