# Phase 3O.5 — Attention-Enriched Case Work Queue

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3O.4 attention workspace routing

## Goal

Bring deterministic professional-attention state into the existing firm work queue without replacing its deadline ordering or creating an AI priority score.

## Ordering rule

The existing authorized case work queue remains authoritative for row order.

Professional attention is an overlay only.

The overlay must not:

- move a case ahead of another case;
- create or remove queue cases;
- convert attention count into urgency;
- infer legal merit;
- infer professional priority.

## Overlay fields

Each queue row may show:

- attention count;
- ordered attention codes;
- deduplicated owning workspaces.

The underlying case-work fields remain unchanged:

- deadline status;
- response deadline;
- days remaining;
- assignee;
- reviewer;
- operational case status.

## Exact case coverage

The professional queue builder requires exactly one attention projection for every case in the existing work queue.

It fails closed when:

- a queue case has no attention projection;
- the same case has duplicate attention projections;
- attention attempts to introduce a case that is not in the queue.

## Authorization

The UI reads the overlay through the authorized professional workbench service.

Case mutations still use the authorized case service.

This means adding professional read context does not create a second path for changing:

- case status;
- response deadline;
- assignee;
- reviewer.

Evidence-derived attention remains permission-aware through the underlying cockpit service.

## UI language

The work queue explicitly states:

> Deadline ordering is preserved from the case work queue. Attention shows deterministic unresolved workflow state and its owning workspace; it is not a priority score or legal verdict.

This wording is intentional.

## Safety invariant

> Operational attention may explain unresolved work, but it must not silently become a ranking system.
