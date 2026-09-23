# Phase 3N.6 — Verified Section 74 Period Scope

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.5 provenance-bearing legal applicability dates

## Official authority

The current India Code consolidation of the Central Goods and Services Tax Act, 2017 states that section 74 concerns the fraud / wilful-misstatement / suppression route for periods up to Financial Year 2023-24, while section 74A applies to Financial Year 2024-25 onward.

Phase 3N.6 records that narrow proposition against the existing source-verified India Code authority.

## Catalog version

The curated catalog moves from:

`gst-legal.v1.2026-09-23`

to:

`gst-legal.v2.2026-09-23`

Historical saved legal briefs keep their original catalog version and payload.

## Applicability

The Section 74 scope rule is queryable only for:

- `GST_SEC74_FRAUD`;
- topic `FRAUD_SUPPRESSION_SCOPE`;
- tax-period-end dates from 1 July 2017 through 31 March 2024.

For FY 2024-25, the v2 Section 74 rule does not match.

The current deep-workflow taxonomy does not yet add a Section 74A workflow. Dwaar therefore leaves that legal topic unresolved rather than silently treating a Section 74 workflow as Section 74A.

## Deliberate non-expansion

Phase 3N.6 does not yet mark ITC or RCM applicability resolved.

Section 16 has version-sensitive conditions and amendments that can change within broader financial-year periods. RCM also depends on notified categories/supplies and may require a supply-level applicability date and notification set.

Those topics remain unresolved until the date/fact contracts are precise enough for the corresponding authority pack.

## Safety invariant

> Adding more law must never reduce date or fact precision.

A smaller verified catalog is preferred to a larger catalog that can select the wrong statutory version.
