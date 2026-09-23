# Phase 3O.4 — Deterministic Attention Workspace Routing

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3O.3 evidence-aware professional attention

## Goal

Make professional attention operationally useful by identifying the Dwaar workspace that owns each deterministic attention item.

This is routing, not prioritization.

## Closed workspaces

The cockpit uses a closed `CaseWorkspace` enum:

- `ANALYSIS_HISTORY`
- `LEGAL_RESEARCH`
- `EVIDENCE`
- `DRAFT`
- `FILING`

Every `CaseAttentionCode` must map to exactly one workspace.

Module initialization fails if a future attention code is added without a route.

## Routing

### Analysis history

- analysis not saved

### Legal research

- legal brief not saved
- legal research unresolved

### Evidence

- legal evidence incomplete
- legal evidence contract drift

### Draft

- draft not started
- draft awaiting review
- draft awaiting approval

### Filing

- approved draft not filed
- filing acknowledgement missing

## UI

The Case attention table now includes a `workspace` column next to:

- attention code;
- message;
- related ID.

This gives the UI a stable machine route for later tabs or deep links without introducing brittle HTML navigation.

## Non-goals

Workspace routing does not:

- rank attention items;
- assign severity;
- choose what the CA should do first;
- create tasks;
- modify case state;
- perform legal analysis;
- infer urgency.

Deadline/work-queue priority remains a separate deterministic concern.

## Safety invariant

> Dwaar may identify where work belongs without deciding which professional judgment the CA should make there.
