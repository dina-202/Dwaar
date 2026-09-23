# Phase 3O.1 — Professional Case Attention Model

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phases 3F–3N

## Goal

Begin the professional CA workbench with a deterministic operational projection rather than a cosmetic dashboard or an AI-generated recommendation.

A real case can need attention in several places at once. Dwaar therefore emits zero or more attention facts instead of forcing one universal "next action".

## Attention codes

Phase 3O.1 defines:

- `ANALYSIS_NOT_SAVED`
- `LEGAL_BRIEF_NOT_SAVED`
- `LEGAL_RESEARCH_UNRESOLVED`
- `DRAFT_NOT_STARTED`
- `DRAFT_AWAITING_REVIEW`
- `DRAFT_AWAITING_APPROVAL`
- `APPROVED_DRAFT_NOT_FILED`
- `FILING_ACKNOWLEDGEMENT_MISSING`

These describe durable workflow state only.

They do not decide legal merits, filing strategy, evidentiary sufficiency, or whether a CA should accept a legal proposition.

## Latest-artifact rule

The projection identifies the latest:

- analysis snapshot;
- legal brief for that latest snapshot;
- draft version;
- filing record.

A legal brief attached only to an older snapshot does not satisfy the latest-snapshot legal-history condition.

## Legal research is not a draft gate

An unresolved legal topic is surfaced as professional attention.

It does not automatically block an existing draft or overwrite Phase-2 `DraftEligibility`.

This preserves the separation between:

- deterministic legal-research completeness;
- Phase-2 drafting safety;
- professional CA judgment.

## Closed cases

Closed cases produce no operational attention items from this projection.

Their history remains available elsewhere through the immutable case timeline and artifacts.

## Scope boundary

3O.1 is a pure read projection.

It does not:

- mutate case status;
- create tasks;
- send notifications;
- rank CAs or cases;
- generate legal advice;
- infer urgency beyond existing deterministic state;
- change work-queue ordering.

Later 3O slices can place this projection into the authorized case workspace and work queue.
