---
title: Least privilege and separation of duties
created: 2026-09-28
updated: 2026-09-28
type: concept
tags: [trap, exam-topic, security]
sources: [raw/corpus/transcripts.md]
questions: [54, 169, 172, 198, 261, 300, 310]
confidence: high
---

# Least privilege and separation of duties

**7 questions in this bank turn on permissions.** Small in number, but the
reasoning is stated explicitly in the walkthroughs.

## How it looks

The wrong options are usually *more* generous than needed: a primitive role
(`Project Owner`, `Editor`) where a narrow one would do, a service account with
broad permissions, or one identity doing several jobs. The right answer grants
the smallest role that satisfies the task, often at a folder or project rather
than at the organization.

> [ASR] By implementing the principle of least privilege. — walkthrough for **Q54**

Q169's scenario states the requirement in the case-study text itself: a least
privilege model with separation of duties.

## Where this lives in GCP

`Cloud IAM` roles and bindings, `Service Account` design, the resource
hierarchy (organization → folder → project), `Organization Policy` for
constraints that must not be overridden, and `Cloud Audit Logs` to prove who did
what. See [[cloud-iam]], [[service-account]], [[resource-hierarchy]],
[[organization-policy]].

## How to avoid it

1. Prefer the narrowest predefined role that does the job over a primitive
   Owner/Editor role.
2. Prefer project- or folder-scoped grants over organization-wide ones.
3. If a question separates duties between teams, one shared identity is almost
   always the wrong answer.
