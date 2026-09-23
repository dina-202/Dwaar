# Phase 3N.8 — Deterministic Legal Question Plans

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.7 closed legal rule bundles

## Goal

Bridge Dwaar's verified legal-source subsystem with the factual state of a real case.

A law library can know valid authorities while a case still lacks enough source-grounded facts to usefully research or apply them. Phase 3N.8 therefore introduces deterministic legal questions that distinguish factual readiness from legal-source readiness.

## Important boundary

A question marked `SOURCE_VERIFIED_RESEARCH_READY` means:

> Dwaar has the required source-grounded case inputs, the correct legal applicability date basis, and the closed source-verified authority bundle for this research question.

It does **not** mean:

- the taxpayer satisfies the provision;
- the department is wrong;
- a defence succeeds;
- liability is established;
- the question has been professionally decided.

Case-specific legal application still requires CA / advocate judgment unless a later deterministic rule explicitly models it.

## Status model

Each legal question has exactly one deterministic status:

- `MISSING_FACTS` — one or more required source-verified fact selectors are absent or ambiguous;
- `MISSING_DATE` — the question's required provenance-bearing applicability date is unavailable;
- `AUTHORITY_UNCURATED` — facts/date are ready but Dwaar does not yet have a complete closed verified authority bundle;
- `SOURCE_VERIFIED_RESEARCH_READY` — facts, date, and verified authority bundle are all available.

These states intentionally avoid labels such as "valid", "invalid", "eligible", "ineligible", "wins", or "loses".

## Fact requirements

Question prerequisites use the existing closed fact model:

- FactType;
- FactRole;
- accepted FactStatus values;
- SourceVerificationStatus.VERIFIED;
- non-empty exact source text.

One selector must match exactly one fact.

Zero matches means missing.

Multiple matches are treated as ambiguous and also fail closed.

No claim text, regex, fuzzy matching, or LLM inference is used to satisfy a legal-question prerequisite.

## Initial question plans

### Section 73 general

- hearing protection;
- adjudicated demand scope.

### Section 73 ITC

- hearing protection;
- adjudicated demand scope;
- applicable ITC eligibility rules for the relevant tax period.

The ITC question also requires:

- tax period;
- GSTR-3B ITC claimed amount;
- GSTR-2B ITC reflected amount.

The authority bundle intentionally remains uncurated in 3N.8.

### Section 73 RCM

- hearing protection;
- adjudicated demand scope;
- authorities governing the alleged RCM supply category and period.

The RCM question requires:

- tax period;
- source-grounded departmental allegation identifying the RCM category.

The authority bundle intentionally remains uncurated.

### Section 74 fraud/suppression

- hearing protection;
- adjudicated demand scope;
- period-specific Section 74 / Section 74A scope research.

The period question requires:

- tax period;
- source-grounded fraud / wilful-misstatement / suppression allegation.

For FY through 2023-24, the current verified Section 74 scope authority can make the research question ready.

For FY 2024-25 onward, it remains uncurated under the current deep-workflow taxonomy.

### Section 129

- detention/seizure-based statutory timeline;
- hearing protection before penalty determination.

Both require the verified detention/seizure date fact and use that date for version selection.

## Why this precedes broader ITC / RCM packs

ITC and RCM legal research cannot safely be reduced to one generic citation.

Before expanding those authority packs, Dwaar now has a deterministic way to answer:

1. Do we have the case facts needed to frame the question?
2. Do we have the correct applicability date?
3. Has the required authority bundle been curated and verified?
4. Which exact verified rule records support the research brief?

This prevents a large legal catalog from creating the appearance of completeness where the case record is not ready.

## Safety invariant

> Dwaar must explain *why legal research is not ready* without pretending that missing facts, missing dates, and missing law are the same problem.
