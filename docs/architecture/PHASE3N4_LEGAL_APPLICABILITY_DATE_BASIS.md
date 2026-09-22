# Phase 3N.4 — Legal Applicability Date Basis

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N verified legal knowledge

## Problem

A legal source can be authentic and source-verified but still be the wrong version for the factual period being analyzed.

The notice date is useful for some procedural propositions. It is not a safe universal substitute for:

- the tax period when deciding ITC eligibility;
- the tax period when deciding RCM applicability;
- the period relevant to fraud/suppression law;
- the detention/seizure date when selecting Section 129 versions.

Using one convenient date for every topic would create false legal certainty.

## Closed date-basis contract

Each GST legal-research topic now declares one of:

- `NOTICE_DATE`
- `TAX_PERIOD_END`
- `DETENTION_OR_SEIZURE_DATE`

Current mappings:

- hearing right → notice date;
- demand scope → notice date;
- ITC eligibility → tax-period end;
- RCM applicability → tax-period end;
- fraud/suppression scope → tax-period end;
- Section 129 timeline → detention/seizure date;
- Section 129 hearing → detention/seizure date.

## Current resolver boundary

The existing legal-brief call currently receives one verified date only: the notice date.

Therefore it resolves only topics explicitly mapped to `NOTICE_DATE`.

Every topic requiring another date basis remains visibly unresolved even if the legal catalog already contains a potentially matching rule.

This is deliberate.

For example, the catalog contains the post-1-January-2022 Section 129 timeline/hearing propositions, but Dwaar will not use the notice date to decide that those versions govern a detention event.

## Why this comes before more legal sources

The fact model can identify `TAX_PERIOD`, and Section 129 extraction has a detention/seizure semantic role, but the current analysis snapshot does not yet expose a deterministic provenance-bearing tax-period end or detention-date value for legal-version selection.

Phase 3N.4 therefore closes the unsafe shortcut first.

A later increment must add deterministic parsed date contracts with source provenance before these topics can move from unresolved to resolved.

## Safety invariant

> No legal topic may borrow a different topic's date merely because that date is available.

An unresolved legal topic is safer than a source-verified proposition selected using the wrong effective date.
