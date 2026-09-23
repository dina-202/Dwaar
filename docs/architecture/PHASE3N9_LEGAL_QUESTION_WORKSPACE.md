# Phase 3N.9 — Legal Question Workspace

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.8 deterministic legal question plans

## Goal

Make the legal-question planner visible inside the normal CA analysis flow without creating a separate legal-research product surface.

## Placement

The existing **Verified legal sources** section now renders a **Legal research questions** subsection.

This keeps:

- legal date provenance;
- question readiness;
- verified authority matches;
- unresolved topics

in one professional research surface.

No new top-level navigation or persistence model is introduced.

## Question table

For each closed workflow question, Dwaar shows:

- stable question ID;
- professional research question;
- deterministic status;
- legal applicability date basis;
- related source fact IDs;
- missing fact selectors;
- exact verified rule IDs supporting a research-ready question.

## Status meaning

### MISSING_FACTS

Required source-grounded case facts are absent or ambiguous.

This does not mean the taxpayer lacks the underlying real-world facts. It means Dwaar does not yet have exactly one trusted fact matching the closed selector.

### MISSING_DATE

The legal question needs a provenance-bearing applicability date and Dwaar cannot derive one safely.

### AUTHORITY_UNCURATED

Case facts and date basis are ready, but Dwaar does not yet have a complete verified authority bundle for the question.

This is different from a missing-fact problem and should guide the CA/product team differently.

### SOURCE_VERIFIED_RESEARCH_READY

The required source-grounded facts, applicability date, and verified authority bundle are present.

This means the research basis is ready for professional legal application.

It does **not** mean:

- taxpayer eligibility is established;
- departmental allegation is disproved;
- legal validity is decided;
- a defence has succeeded;
- filing language is approved.

## UX rule

The UI explicitly states that "research ready" is not a case-specific legal conclusion.

This language is intentional and should not be weakened merely to make the product appear more decisive.

## Scope boundary

Phase 3N.9 does not:

- persist question-plan state separately;
- inject question conclusions into draft text;
- call an LLM to answer the legal questions;
- create new legal authorities;
- infer missing case facts;
- infer missing legal dates.

The table is a deterministic projection of the current analysis facts, legal-date context, and verified authority catalog.

## Safety invariant

> The professional workspace should make uncertainty more specific, not make it disappear.
