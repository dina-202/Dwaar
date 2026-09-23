# Phase 3N.5 — Provenance-Bearing Legal Applicability Dates

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.4 legal applicability date basis

## Goal

Turn legal date-basis requirements into deterministic dates without letting an LLM, UI field, or convenient unrelated date choose a legal version.

## New date-anchor contract

A `LegalDateAnchor` records:

- date basis;
- effective date used for legal version selection;
- optional period start/end;
- source fact ID;
- source page;
- exact source text;
- source fact type;
- source fact role.

A `LegalDateContext` contains only unambiguous anchors.

## Trust boundary

An anchor can be derived only from an `ExtractedFact` that is:

- `CONFIRMED`;
- source-verification `VERIFIED`;
- non-empty;
- structurally appropriate for the requested basis.

OCR text still marked `REQUIRES_VERIFICATION` cannot become a legal date anchor.

Department allegations cannot become legal date anchors.

Multiple candidate facts for the same date basis fail closed.

## Deterministic tax-period parsing

Supported initially:

- explicit `FY YYYY-YY`;
- explicit `F.Y. YYYY-YY`;
- explicit `Financial Year YYYY-YY`;
- exactly two numeric dd/mm/yyyy-style dates forming an ordered range.

For an explicit financial year, Dwaar deterministically maps:

`FY 2021-22 -> 01-04-2021 through 31-03-2022`

The legal selector uses the period end while retaining both period boundaries.

Dwaar deliberately does not yet infer:

- a financial year from bare `2021-22`;
- quarters from prose;
- month names;
- return periods;
- tax periods from surrounding context.

## Section 129 event date

A detention/seizure anchor requires:

- `FactType.DOCUMENT_DETAIL`;
- `FactRole.DETENTION_OR_SEIZURE_DATE`;
- one and only one deterministic numeric date in the exact source text.

A generic procedural date is not accepted.

## Context-aware legal resolution

GST legal research can now resolve each topic against the date basis declared by its research requirement.

Examples:

- hearing right -> verified notice-date anchor;
- ITC eligibility -> verified tax-period-end anchor;
- Section 129 timeline/hearing -> verified detention/seizure-date anchor.

A missing anchor leaves that topic unresolved.

A source-verified rule whose effective interval does not include the correct anchor date also remains unresolved.

## Historical legal briefs

When a legal brief is saved for an analysis snapshot, Dwaar reconstructs the legal date context from the immutable snapshot's preserved facts.

The UI does not choose the dates.

The brief remains bound to the same snapshot and catalog version.

The existing `as_of_date` metadata remains the verified notice date for backward compatibility; topic-specific date selection is performed from the preserved legal date context.

## UI

The live Verified legal sources panel now shows the legal date anchors before the matched authorities, including source fact, page and exact source text.

This makes the legal-version selection inspectable by a CA.

## Safety invariant

> A legal proposition is trusted only when both its source and its applicability date are traceable.

Authentic law selected with the wrong date is not treated as verified law for the case.
