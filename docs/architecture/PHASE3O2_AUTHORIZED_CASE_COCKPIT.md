# Phase 3O.2 — Authorized Case Cockpit

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3O.1 professional case attention

## Goal

Put the deterministic professional-attention projection into the authenticated saved-case workspace without creating a parallel authorization path.

## Authorization boundary

The cockpit reads case state only through existing authorized services:

- authorized case service;
- authorized analysis snapshot service;
- authorized legal brief service;
- authorized draft work-product service;
- authorized filing service.

It does not access SQLite repositories directly from the UI.

The existing permission checks of those services remain authoritative.

## Latest legal brief

The cockpit first selects the latest saved analysis snapshot.

Only legal briefs bound to that snapshot are considered current for the attention projection.

If multiple briefs exist for that snapshot, only the latest is decrypted and inspected for unresolved topics.

Historical legal briefs remain available in Analysis history but do not make the latest snapshot appear legally reviewed.

## Saved-case UI

An opened saved case now shows **Case attention** before the full case timeline and detailed workspaces.

The cockpit shows the latest IDs for:

- analysis snapshot;
- legal brief;
- draft version;
- filing.

It then shows zero or more deterministic attention items.

The detailed Analysis, Evidence, Draft, Filing and Timeline workspaces remain the source for actions and history.

## Non-goals

The cockpit does not:

- mutate a case;
- create tasks automatically;
- rank or score cases;
- provide legal advice;
- replace deadline priority;
- hide unresolved legal research;
- infer that no attention item means the legal merits are complete.

"No operational attention item" means only that this projection found none of its closed workflow conditions.
