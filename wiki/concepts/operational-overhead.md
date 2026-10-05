---
title: The operational-overhead trap
created: 2026-09-28
updated: 2026-09-28
type: concept
tags: [trap, exam-topic, high-frequency]
sources: [raw/corpus/transcripts.md]
questions: [22, 32, 33, 37, 39, 46, 102, 114, 130, 131, 143, 152, 159, 162, 173, 181, 208, 232, 234, 239, 251, 259, 263, 267, 272, 278, 281, 290, 297, 298, 303, 311, 312, 321, 324, 334, 336]
confidence: high
---

# The operational-overhead trap

**The most common trap in this bank: 37 of 320 questions with a transcript.**

The exam almost always prefers the option that leaves Google running the
infrastructure. An option that is technically correct but asks you to run,
patch, or babysit something is the wrong answer more often than not.

## How it looks

The distractor is plausible and even cheaper or faster — but it involves a
server, a script you host, a cluster you size, or a patch you apply. The right
answer is usually the managed service, even when the distractor would "work".

> [ASR] It requires you to manage your own infrastructure for logging, which is
> less scalable and more work than using the fully managed cloud logging service
> that Google provides. — walkthrough for **Q114**

> [ASR] This would create a huge amount of operational work which is the
> opposite of what the question asks for. — walkthrough for **Q32**

Note how Q22's walkthrough names the managed service, with the transcriber
doubling a letter:

> [ASR] Google Cloud Dataf Flow is a fully managed serverless service — **Q22**

## Why it matters here

`Dataflow`, `Pub/Sub`, `Cloud Run`, `Cloud Functions`, `App Engine` and the
managed databases all get chosen *because* they remove operational work. When
two options are functionally equivalent, compare who operates them.

See [[dataflow]], [[cloud-run]], [[cloud-functions]], [[pub-sub]] for the
services this trap pushes you toward, and [[cost-first]] for the trap that
pulls the other way.

## How to avoid it

1. Ask who patches, scales, and monitors the thing in the option.
2. If the answer involves "you install", "you create a script", or "you size the
   cluster", look for the managed alternative before picking it.
3. Do not pick the self-managed option just because it is cheaper — check
   [[cost-first]] to see when cost is genuinely the deciding constraint.
