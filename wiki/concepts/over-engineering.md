---
title: Over-engineering and added complexity
created: 2026-09-28
updated: 2026-09-28
type: concept
tags: [trap, exam-topic]
sources: [raw/corpus/transcripts.md]
questions: [30, 48, 121, 307]
confidence: medium
---

# Over-engineering and added complexity

**4 questions in this bank explicitly reject an option for adding complexity.**
The smallest count of the traps recorded here, hence `confidence: medium` — the
pattern is real but thinly attested.

## How it looks

The distractor works, but costs more moving parts than the problem justifies: a
dedicated server or service to run a small script, an extra layer of access
control where a simpler mechanism suffices, a heavier pipeline for a simple
transform.

> [ASR] It requires you to manage a server or service just to run the script,
> which adds complexity and cost. — walkthrough for **Q30**

> [ASR] Providing secure limited access is also more complex than the
> alternative. — walkthrough for **Q48**

## How to avoid it

1. Count the components each option introduces; prefer the one with fewer.
2. Prefer serverless for small, occasional work (`Cloud Functions`,
   `Cloud Scheduler`) over a standing server — this overlaps heavily with
   [[operational-overhead]].
3. Beware the reverse trap too: "fewer parts" does not beat a requirement. Read
   [[answer-the-question-asked]] before simplifying away a stated constraint.
