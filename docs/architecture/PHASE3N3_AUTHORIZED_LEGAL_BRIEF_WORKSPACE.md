# Phase 3N.3 — Authorized Legal Brief Workspace

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.2 snapshot-bound legal briefs

## Goal

Expose durable verified legal research through the same authenticated, firm-scoped case workspace used by analysis history.

## Authorization

No new permission is introduced.

- listing/loading a legal brief inherits the existing case-read boundary;
- saving a new durable legal brief additionally requires `CASE_UPDATE`.

This keeps the permission model small and avoids inventing a legal-specific role before pilot evidence shows one is needed.

## Snapshot-derived legal binding

The UI does not supply an arbitrary legal date or proceeding type.

When a user saves a legal brief for a selected analysis snapshot, the authorized service loads that exact historical snapshot and reads:

- `deadline.notice_date`;
- `classification.proceeding_type`.

The service then runs the closed GST legal-research profile using those preserved values and persists the result against that same snapshot.

If the historical snapshot has no notice date, saving fails closed.

This keeps the current Phase 3N notice-date research basis explicit and prevents a UI field from silently changing historical law selection.

## Workspace

The existing Analysis history area gains a Legal research history subsection.

For the selected analysis snapshot, an authorized user can:

- see saved legal-brief metadata;
- save the current verified legal brief when `CASE_UPDATE` is granted;
- reopen the preserved matched rule/source records;
- see unresolved topics that still required CA legal research.

Historical briefs are labelled as preserved audit/history and do not refresh themselves against the current catalog.

## Scope boundary

Phase 3N.3 still does not:

- inject legal propositions into specialist draft text;
- infer tax-period-sensitive substantive-law dates;
- add a new legal permission;
- perform live network retrieval;
- overwrite historical legal briefs.
