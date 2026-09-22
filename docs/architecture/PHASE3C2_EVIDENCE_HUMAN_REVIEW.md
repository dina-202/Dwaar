# Phase 3C.2 — Evidence Human Review Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026  
**Depends on:** Phase 3C.1 evidence candidate intake

## 1. Purpose

Phase 3C.2 defines the human decision boundary for evidence candidates.

An AI-generated `EvidenceCandidate` is immutable input. A professional decision creates a separate `EvidenceReviewRecord`; the candidate is not rewritten in place.

## 2. Decisions

Human review has exactly two terminal decisions:

- `CONFIRMED`
- `REJECTED`

`PENDING_REVIEW` is machine state and cannot be submitted as a human decision.

## 3. Audit behavior

A review record snapshots:

- review ID;
- candidate ID;
- evidence requirement ID;
- document ID;
- exact source text;
- source page;
- source origin;
- source verification;
- terminal decision;
- optional reviewer note.

A second review for the same candidate is rejected in this phase. Corrections/re-review require a future explicit supersession contract rather than silent overwrite.

## 4. Non-effects

Creating a review record does not:

- mutate the original candidate;
- mutate `EvidenceChecklistItem.status`;
- create or modify an `ExtractedFact`;
- alter deadline or arithmetic inputs;
- change draft eligibility;
- unlock filing-grade drafting.

This separation is intentional. Human confirmation of a document-to-requirement link is not automatically equivalent to confirming every taxpayer fact that might be inferred from that document.

## 5. OCR

A review record preserves the candidate's source-origin and source-verification state.

A human CONFIRMED decision over an OCR candidate does not silently rewrite the OCR source channel to VERIFIED. Visual OCR/source correction requires a separate source-verification workflow.

## 6. IDs

Review IDs are deterministic within an ordered review collection:

`ER-001`, `ER-002`, ...

Existing reviews determine the next ID. The future persistence layer will replace session-local ordering with persistent case-scoped identity while preserving stable record IDs.

## 7. Exit criteria

- confirm creates a separate review record;
- reject creates a separate review record;
- candidate remains unchanged;
- duplicate review is rejected;
- PENDING_REVIEW is not accepted as a human decision;
- source provenance is snapshotted;
- reviewer notes are normalized;
- no downstream case state changes automatically;
- full regression suite passes.
