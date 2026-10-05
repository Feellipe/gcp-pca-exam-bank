---
title: The cost trap
created: 2026-09-28
updated: 2026-09-28
type: concept
tags: [trap, exam-topic, cost, high-frequency]
sources: [raw/corpus/transcripts.md]
questions: [101, 109, 131, 132, 139, 140, 165, 166, 167, 175, 176, 179, 180, 200, 201, 234, 263, 274, 285, 292, 332, 337, 338]
confidence: high
---

# The cost trap

**23 questions in this bank turn on cost.** It cuts both ways, which is what
makes it a trap rather than a rule.

## How it looks

Two shapes appear:

1. **Cost is stated in the question** ("minimise cost", "reduce spend") — then
   the cheapest option that still meets the requirements wins, and the
   fully-managed answer from [[operational-overhead]] is *not* automatically
   right.
2. **Cost is not mentioned** — then an option that is merely cheaper is usually a
   distractor, and picking it means answering a question that was not asked
   (see [[answer-the-question-asked]]).

> [ASR] Preemptable VMs as mentioned in options A and B are a much better option
> as they offer significant cost savings. — walkthrough for **Q109**

> [ASR] This is not the most cost-effective choice. — walkthrough for **Q109**

## Watched in the walkthroughs

`Preemptible VM` / `Spot VM`, `Committed Use Discount`, `Sustained Use
Discount`, storage classes, and `BigQuery` slot reservations are the levers this
bank expects you to know. GCP's own cost tooling is the billing export and
budget alerts.

## How to avoid it

1. Search the question text for a cost word before using cost as a tiebreaker.
2. If cost is stated, prefer the option that meets every other requirement AND
   is cheapest — cheap alone is still wrong.
3. If cost is absent, treat "cheaper" as a distractor signal.
