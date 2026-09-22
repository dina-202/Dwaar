# Phase 3M — Unified Case Timeline

**Status:** Pilot read-only professional history  
**Date:** 22 September 2026  
**Depends on:** Phase 3L filing and acknowledgement lifecycle

## 1. Purpose

Phase 3M gives a professional one chronological view of what happened in a case.

The timeline is derived from the existing append-only `CaseEvent` audit trail.

It does not introduce a second history database.

It does not decrypt notice, evidence, draft, filing or acknowledgement content.

It does not mutate case state.

## 2. Timeline item

The framework-independent `CaseTimelineItem` contains:

- event_id;
- CaseEventType;
- TimelineCategory;
- occurred_at;
- actor_id;
- human-readable title;
- human-readable summary.

The timeline is presentation-oriented structured metadata, not a new legal/factual source.

## 3. Closed categories

TimelineCategory is closed to:

- CASE;
- DOCUMENT;
- ANALYSIS;
- EVIDENCE;
- DRAFT;
- FILING;
- HEARING;
- ORDER.

Every current CaseEventType maps deterministically to one category.

A new CaseEventType must receive an explicit timeline mapping before it can appear in the unified history.

## 4. Current event coverage

Phase 3M projects:

- CASE_CREATED;
- CASE_STATUS_CHANGED;
- CASE_OPERATIONS_UPDATED;
- DOCUMENT_ADDED;
- DOCUMENT_REMOVED;
- ANALYSIS_SAVED;
- EVIDENCE_CANDIDATES_GENERATED;
- EVIDENCE_REVIEWED;
- DRAFT_CREATED;
- DRAFT_REVIEWED;
- FILING_RECORDED;
- FILING_ACKNOWLEDGEMENT_RECORDED;
- HEARING_RECORDED;
- ORDER_RECORDED.

## 5. Curated metadata only

The timeline renderer never displays an event's raw payload dictionary.

For each event type it reads only a closed set of known metadata keys.

Examples:

- CASE_STATUS_CHANGED may use `from_status` and `to_status`;
- DOCUMENT_ADDED may use `kind`;
- ANALYSIS_SAVED may use `snapshot_id`;
- EVIDENCE_REVIEWED may use `evidence_id` and `decision`;
- DRAFT_REVIEWED may use version/status metadata;
- FILING_RECORDED may use `filing_reference`.

Unknown payload keys are ignored.

This prevents future/internal metadata from surfacing automatically merely because it exists in an audit event.

## 6. Missing metadata

Historical or older audit events may not contain every metadata key expected by newer timeline wording.

Phase 3M uses truthful generic fallback language rather than fabricating details.

For example, an event with no snapshot ID may say that an analysis snapshot was recorded without inventing an identifier.

## 7. Protected-content boundary

The timeline does not read or display:

- raw notice text;
- evidence source quotes;
- reviewer notes;
- draft text;
- document bytes;
- encrypted payloads;
- tokens/secrets;
- internal object-storage keys.

Those remain behind their dedicated authorized encrypted-data workflows.

## 8. Authorization

Timeline access requires:

`CASE_READ`

The authorized service first verifies that the requested case belongs to the active firm.

Only after that check does it request the case's audit events.

A valid case ID from another tenant therefore cannot be used to enumerate events.

## 9. Deterministic ordering

Timeline items are ordered by:

1. `occurred_at` ascending;
2. `event_id` ascending as a stable tie-breaker.

The ordering reflects recorded event chronology.

It does not reinterpret legal chronology or attempt to infer missing events.

## 10. Actor identity

When available, the timeline displays the persisted audit actor ID.

The current pilot uses opaque internal/OIDC-derived user IDs because Dwaar does not yet have a staff-profile display-name directory.

An absent actor is displayed as unavailable rather than invented.

## 11. UI position

For a reopened case, Dwaar now displays:

1. opened-case metadata;
2. OCR warning when applicable;
3. **Case timeline**;
4. current live recomputed analysis;
5. analysis history;
6. evidence workspace;
7. draft work product;
8. filing/acknowledgement;
9. extracted notice text expander.

This placement intentionally separates:

- **what historically happened in the case**, from
- **what the current analysis engine says now**.

## 12. Read-only behavior

Viewing the timeline does not:

- change case status;
- update deadlines;
- decrypt files;
- rerun analysis;
- save snapshots;
- generate/review evidence;
- create/review drafts;
- record filings;
- append new events.

It is a pure projection/navigation surface.

## 13. No schema migration

Phase 3M reuses the existing `case_events` table.

No SQLite schema-version change is introduced.

No timeline-specific persistence is introduced.

## 14. Failure disclosure

Timeline loading errors are rendered generically.

Internal repository/database details are not displayed.

Cross-tenant or unavailable cases fail closed.

## 15. Exit criteria

- typed timeline item/category contracts exist;
- every current CaseEventType maps explicitly;
- timeline ordering is deterministic;
- CASE_READ gates access;
- case/firm relationship is checked before event read;
- unknown raw event payload keys never surface automatically;
- protected source/draft/document content is not loaded;
- missing metadata produces truthful fallback wording;
- UI shows historical timeline before current live analysis;
- timeline has no mutation side effects;
- no schema migration or second history store is introduced;
- full offline regression suite passes.
