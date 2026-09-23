# Phase 3N.14 — ITC Legal Evidence Readiness

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.13 post-2022 ITC mismatch regime

## Goal

Separate two questions that must not be collapsed:

1. Does Dwaar have a source-verified legal research basis?
2. Does the selected historical case snapshot have human-confirmed supporting evidence for the legal question?

Phase 3N.14 adds a deterministic evidence-readiness projection for the second question.

It does **not** decide ITC eligibility.

## Existing evidence trust boundary

Dwaar already persists evidence review decisions as immutable, encrypted, snapshot-bound records.

A durable review metadata record binds:

- case;
- analysis snapshot;
- workflow evidence ID;
- supporting document;
- source page / quote hash;
- human decision;
- reviewer;
- review timestamp.

Only a human `CONFIRMED` decision counts toward legal evidence readiness.

A machine-proposed candidate does not count.

A `REJECTED` review does not count.

A confirmed review from another snapshot does not count.

## ITC eligibility evidence set

The first closed legal-evidence requirement is attached to:

`gst_sec73_itc.eligibility`

It currently requires human-confirmed evidence for:

- `sec73_itc.e3` — invoice-level ITC reconciliation;
- `sec73_itc.e4` — supplier GSTR-1 filing status / supporting filing evidence where relevant;
- `sec73_itc.e5` — payment proof to suppliers where relevant to claimed ITC eligibility.

The first two workflow evidence items are deliberately not used as the legal-evidence readiness set:

- `sec73_itc.e1` — GSTR-2B for the relevant period;
- `sec73_itc.e2` — GSTR-3B ITC tables.

Those return statements are important mismatch/reconciliation inputs, but their presence does not establish the broader supporting evidence required for final entitlement review.

## Readiness states

The projection emits only evidence-process states:

- `NO_CONFIRMED_EVIDENCE`
- `PARTIAL_CONFIRMED_EVIDENCE`
- `REQUIRED_EVIDENCE_CONFIRMED`

It deliberately does not emit:

- eligible;
- ineligible;
- condition satisfied;
- claim valid;
- defence succeeds.

Even `REQUIRED_EVIDENCE_CONFIRMED` means only that the closed evidence set has confirmed review records.

It does not mean the contents of those documents prove every statutory condition.

## Historical contract safety

The authorized service verifies that every closed legal-evidence ID exists in the selected analysis snapshot's historical evidence checklist.

If a historical snapshot predates or conflicts with the current requirement set, Dwaar fails that readiness projection as contract drift.

It does not reinterpret the old snapshot using today's checklist.

## Workspace

The persisted supporting-evidence workspace now shows a **Legal evidence readiness** section for the selected snapshot.

It displays:

- legal question ID;
- readiness status;
- required evidence IDs;
- confirmed evidence IDs;
- missing evidence IDs;
- confirmed review IDs.

The UI explicitly states that this does not decide whether ITC or any legal condition is satisfied.

## Scope boundary

Phase 3N.14 does not:

- change the Phase-2 evidence checklist;
- create a new evidence candidate type;
- turn evidence into taxpayer facts;
- interpret evidence contents as satisfying Section 16;
- mark `ITC_ELIGIBILITY` source law as curated;
- inject eligibility claims into drafts;
- alter legal-brief schema v2.

This is intentionally a parallel evidence-readiness projection.

## Safety invariant

> Evidence availability, evidence meaning, and legal entitlement are three different layers.

Dwaar may confirm the first while leaving the other two for deterministic rules and professional judgment.
