# Phase 3N.11 — Full-Period Legal Applicability Safety

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.10 backward-readable legal brief v2

## Problem

A tax-period fact is an interval, not merely its last day.

Earlier Phase 3N work preserved both `period_start` and `period_end`, but the legal resolver selected tax-period-dependent law using `period_end` as a point date.

That is unsafe when a legal rule changes inside the period.

Example:

- source fact: `FY 2021-22`;
- period: 1 April 2021 through 31 March 2022;
- a legal condition changes on 1 January 2022.

Selecting the 31 March 2022 rule and applying it to the whole FY would silently project the later legal version backward over nine earlier months.

## New interval query

Phase 3N.11 adds `LegalKnowledgeIntervalQuery`:

- period start;
- period end;
- proceeding type;
- legal topics.

The interval resolver returns a source-verified rule only when one version of that rule covers the **entire** requested interval.

A rule does not qualify when:

- it starts after the source period begins;
- it ends before the source period ends.

## No stitched legal versions

Two adjacent versions of the same rule key are **not** automatically stitched together to satisfy one broad source period.

If an FY crosses a legal amendment boundary, the topic remains unresolved.

The case must instead provide a narrower source-grounded period (for example a month/date range) before Dwaar can select the corresponding legal version safely.

This is intentional. Automatic period splitting would create new factual periods not stated in the source case record.

## Workflow integration

Legal research requirements using `TAX_PERIOD_END` now use the full provenance-bearing tax interval whenever `period_start` and `period_end` are present.

Point-date topics remain unchanged:

- notice-date questions use point resolution;
- detention/seizure-date questions use point resolution.

## Existing Section 74 behavior

The verified Section 74 scope rule through FY 2023-24 covers the complete 1 April 2023–31 March 2024 interval, so that research remains available.

A source period extending beyond 31 March 2024 does not receive that rule.

## Why this precedes ITC authority expansion

Several ITC rules and reporting conditions changed inside financial years.

Phase 3N.11 ensures that adding historically versioned ITC authorities cannot cause a later version to be selected for an earlier portion of an FY merely because the FY-end date falls after the amendment.

## Safety invariant

> A legal rule selected for a source tax period must cover that entire source period, unless the source itself provides a narrower provenance-bearing sub-period.

Dwaar does not manufacture sub-period facts in order to make legal research resolve.
