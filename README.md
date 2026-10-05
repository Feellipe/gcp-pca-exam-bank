# Google Cloud PCA — exam question bank

Turns the YouTube playlist ["Google Cloud Professional Architect | Full Course:
250+ Real Exam Questions"](https://www.youtube.com/playlist?list=PLB574eEmT4ofIr8LFjiKJfTjjg7StIAQm)
into a database of practice-exam questions: one screenshot per question, the
question text, the correct answers, the video timestamps, and the presenter's
spoken explanation — ready to drive a practice-exam front end.

## Why not a browser

Driving YouTube in a browser and screenshotting on a timer needs a full real-time
playback per video (16 h for this playlist) and captures player chrome. Instead
the video stream is downloaded once and the answered slides are found by **pixel
analysis**: every answer is highlighted green, so the green pixels *are* the index
of "answer revealed" moments. A 55-minute video takes ~25 s to download and
~2.5 min to scan.

## Pipeline

```
yt-dlp (1 request/video: 720p H.264 + auto captions)
   |
   +-- ffmpeg green scan (1 s samples)     -> windows where an answer is on screen
   +-- ffmpeg scene-cut scan (0.02, 320px) -> where slides change
   +-- caption parse                       -> "Question N" announcements
   |
   v
one screenshot per question, taken just before the answer window closes
   |
   v
tesseract OCR (+2x upscale) -> stem, options, and WHICH options are green
   |
   v
exam/exam.db (SQLite)
```

**Numbering.** When the answered-slide count matches the range the title declares
("Part 2 (Questions 21- 40)" → 20 slides), slide order is used and the captions
act as a cross-check — this survives YouTube throttling the caption endpoint.
Videos whose titles declare no range (the case-study parts) are numbered per part
as `p09s01`, `p09s02`, ... so they cannot collide with real question numbers.

## Layout

```
scripts/gs.py                   shared helpers: caption parsing, green mask, ffmpeg scans
scripts/extract_questions.py    the pipeline (download -> locate -> screenshot)
scripts/slide_ocr.py            one slide -> stem + options + green answers
scripts/build_exam_db.py        join screenshots + OCR + captions into SQLite
scripts/green_bands.py          crop the green text lines out of an image
scripts/green_detect.py         green coverage report for an image
scripts/scan_window.py          per-second green + line count for a time window
Questions/auto/                 q021.jpg = question 21, p09s03.jpg = part 9 slide 3
Questions/                      the hand-made screenshots from before this existed
exam/exam.db                    the study bank
work/state/<video>.json         per-video extraction record (the resume cache)
work/videos/                    downloaded videos + captions
work/ocr/<label>.json           OCR cache
```

## Usage

```bash
# full backfill, 4 parallel workers
for i in 0 1 2 3; do
  .venv/Scripts/python.exe scripts/extract_questions.py --shard $i/4 --out Questions/auto &
done; wait

# re-run for anything new or failed (finished videos are skipped via cache)
.venv/Scripts/python.exe scripts/extract_questions.py --out Questions/auto

# captions were rate-limited? backfill them later, slowly
.venv/Scripts/python.exe scripts/extract_questions.py --captions-only --pause 20

# rebuild the study bank
.venv/Scripts/python.exe scripts/build_exam_db.py

# inspect one slide
.venv/Scripts/python.exe scripts/slide_ocr.py Questions/auto/q021.jpg --json

# what went green in a time range of a video
.venv/Scripts/python.exe scripts/scan_window.py work/videos/<id>.mp4 208 240
```

`extract_questions.py` is resumable: per-video state lives in `work/state/`, and
a video is skipped once its images exist on disk. Deleting an image (or its state
file) makes the next run redo just that video.

## Database

`videos` — one row per playlist video (part, title, duration, numbering mode, range).

`questions` — one row per question:
| column | meaning |
|---|---|
| `label`, `image` | `q021` → `Questions/auto/q021.jpg` |
| `ocr_question` | the number printed on the slide |
| `stem` | OCR of the question text |
| `correct` | comma-separated correct letters, derived from the green highlight |
| `choose` | how many answers the question asks for, when it says so |
| `t_question`, `t_answer`, `t_next` | seconds: slide appears, answer revealed, next question |
| `watch_url` | `https://youtu.be/<id>?t=<t_answer>` — jump straight to the answer |
| `explanation` | the presenter's captions between this question and the next |
| `options_json` | the raw OCR option list with per-option green pixel counts |

`options` — one row per option (`is_correct`, `green_px`, `t_mentioned` = when the
presenter first says "option X" in the explanation).

`transcript` — the full caption stream per video.

### Integrity checks run by `build_exam_db.py`

* questions whose OCR produced no stem or no green answer
* questions where the slide's printed number disagrees with the assigned number
* multi-answer questions whose green count does not match the `choose N` instruction
* (in the extractor) images that contain no green, and duplicate images — two
  different questions must never produce the same screenshot

## Current state of this bank

16 videos processed → **340 screenshots covering questions Q1–339 with no gaps**.
Parts 1-8 declare their ranges in the title and are numbered by slide order
(verified: 20/20/20/20/20/20/20 then 18/18 for Q141-158, matching each declared
range exactly); the case-study parts are numbered from the presenter's
announcements and continue the same sequence (159-187, 188-210, 211-230,
231-250, 251-277, 278-304, 305-319, 319-339).

337 of 340 slides parsed cleanly. Three need a human look, all listed by the
build report:

| label | problem |
|---|---|
| `p10s02` | two-column layout (scenario left, code options right) - no options parsed |
| `p16s01` | the case-study *overview* slide, not a question - its `number` is released (NULL) so Q319 belongs solely to `p15s15` |
| `p16s16` | real question, but its options do not use "A./B./C." markers, so no green was attributed |

The build resolves duplicate numbers automatically: when two rows claim the same
number, the one with an identified answer keeps it and the other is set to NULL
with a note, so `questions.number` is a 1:1 key for 1..339.

## The wiki layer (concept index)

`exam.db` also carries a concept layer built by `scripts/build_concepts.py`:
`concepts` (107 rows) + `question_concepts` (1078 links from 320 questions).
`scripts/build_wiki.py` turns that into `wiki/` (see `wiki/SCHEMA.md`): 96
generated entity pages, 5 hand-written trap pages, and hash-pinned exports in
`wiki/raw/corpus/`.

Ask the DB, not the markdown, when generating an exam:

```sql
-- every question that prints Dataflow, with its walkthrough explanation
SELECT q.number, q.label, q.correct, q.watch_url, q.explanation
FROM questions q
JOIN question_concepts qc ON qc.question_id = q.id
JOIN concepts c ON c.id = qc.concept_id
WHERE c.name = 'Dataflow'
ORDER BY q.number;

-- concepts to test a user on after they miss question 23
SELECT c.name, COUNT(*) n FROM question_concepts a
JOIN question_concepts b ON b.question_id = a.question_id
JOIN concepts c ON c.id = b.concept_id
WHERE a.question_id = (SELECT id FROM questions WHERE number = 23)
GROUP BY c.name ORDER BY n DESC;
```

Two rules that matter when building anything on top of this:

* **Concept links come from the printed slide text, never the transcript.** The
  walkthrough names a printed concept only about half the time (273 of 578
  mentions) and mangles the name when it does, so a transcript-driven index both
  misses questions and mislabels them.
* **Treat `explanation` as ASR prose, not terminology.** It contains real
  mangling: `IAM` -> "IM", `microservice` -> "micros service", `Dataflow` ->
  "Dataf Flow", Cloud Run -> "DCloud Run", and once "boosted tree regressor" ->
  "boosted dinosaur dinosaur aggressor". Quote it, but quote the slide text when
  the exact name matters.
* **14 questions are asked twice** in the playlist (part 11/12 repeat parts 3-6).
  The later copies carry `duplicate_of`, so filter them out of an exam with
  `WHERE duplicate_of IS NULL`. Copies can have shuffled options, so compare the
  answer TEXT (loosely - the two copies are OCR'd from different frames), never
  the letter.

## The offline practice-exam app

`exam-app/pca-exam.html` is one self-contained file (**1.15 MB**) built by
`scripts/export_exam_app.py`. Send it to a phone and it opens offline — no server,
no install, no network. The only time it touches the network is if you tap a
`youtu.be` deep link.

- **323 gradeable questions** (17 excluded: 14 repeats + 3 whose slides never parsed)
- pick concept categories, choose up to 50 questions, timer at the real exam ratio
  (50 questions = 120 minutes, i.e. 144 s each)
- answer, then get the verdict, the walkthrough explanation, the concepts the
  question tests, and the trap pages that cite it
- multi-answer questions ("select 2") state how many to pick and grade all-or-nothing
- missed questions return as a review round; accuracy is broken down per category
- a run survives the phone backgrounding the browser (localStorage); "Reveal"
  counts as incorrect but is flagged as such in the summary

Sources live in `exam-app/assets/` (`exam.css`, `exam.js`) plus
`exam-app/app.template.html`; the exporter inlines them, so **restyle the assets
and re-run the exporter — never edit the 1.15 MB artifact.** Re-run it after any
`exam.db` rebuild.

```bash
# rebuild the artifact
.venv/Scripts/python.exe scripts/export_exam_app.py

# 77 checks: runs the SHIPPED exam.js against the JSON actually embedded in the
# exported file (catches escaping mistakes, dead trap links, grading bugs)
node tests/exam_harness.js

# real-browser session: clicks through 50 questions, opens a trap page, finishes,
# then reloads to prove an interrupted session resumes. Needs a Chrome listening
# on 9222 (the agent's browser backend wants its own build; this uses system Chrome):
#   chrome --headless=new --remote-debugging-port=9222 --user-data-dir=<tmp> about:blank
node scripts/cdp_eval.js exam-app/pca-exam.html \
  tests/exam_browser_test.js tests/exam_persist_probe.js

# phone-width layout: header pinning, action-bar reachability, 44px tap targets
node scripts/cdp_eval.js exam-app/pca-exam.html \
  tests/exam_mobile_probe2.js --emulate=390x844
```

`scripts/cdp_eval.js` is a ~100-line CDP driver (Node 22 has `fetch` and `WebSocket`
built in, so it needs no packages); it takes a path or a URL, evaluates a JS file in
a real page, and can reload and run a second file — which is how the resume path is
tested.

**Getting it onto the phone:** the single file opens from Files/Drive/mail with no
server. Progress is stored in `localStorage`, which was verified to work from a
`file://` page, so an interrupted exam survives closing the tab. The two ways to
move it are the Hermes download card or copying it over USB.

## Known limitations

* **Part 1 has no explanation text.** YouTube's caption endpoint ended up
  demanding sign-in ("Sign in to confirm you're not a bot") after the batch
  volume, so `BMr-po8LpM0` keeps its screenshots, answers and numbering but has an
  empty `explanation`. Backfill later with
  `--captions-only --only 1`; if it still refuses, add
  `--cookies-from-browser chrome` (needs you to be signed in to YouTube in
  Chrome, and it reads your browser cookies - only do this deliberately).
* **ASR text.** The explanation comes from auto-captions and is not cleaned up
  ("Vert.Ex AI" for "Vertex AI"), so treat it as a study aid, not a citable
  transcript. The question/option text comes from OCR of the slide, which is
  accurate.
* **720p is deliberate.** 480p introduced OCR errors ("fdsk" for "fdisk"); 1080p
  read no better than 720p. OCR runs on a 2x upscale.
* Trailing green windows that touch the end of a video are dropped as end cards,
  so a video that ended exactly on a revealed answer would lose that question.
