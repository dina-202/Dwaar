# Phase 3F.5 — Analysis History UI

**Status:** Pilot historical-analysis workspace  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.3 saved-case reopen, Phase 3F.4 versioned snapshots

## 1. Purpose

Phase 3F.5 exposes versioned analysis history in the saved-case Streamlit workspace without confusing historical system output with the current analysis engine.

The user may:

- view snapshot metadata;
- load a historical encrypted snapshot as read-only data;
- open/recompute the current analysis from the encrypted notice;
- save the current recomputation as a new historical snapshot when authorized.

## 2. Historical versus current analysis

The UI presents two separate actions:

### Open / recompute current analysis

- decrypts and integrity-checks the persisted notice;
- runs the current Phase-2 engine;
- produces a live Phase2AnalysisResult for the current session.

### Historical analysis snapshot

- loads encrypted historical JSON;
- displays it as historical data;
- does not create Phase2AnalysisResult;
- does not feed drafting, validation, evidence or filing engines.

Historical snapshots therefore cannot silently become live state.

## 3. Permission model

### Snapshot metadata

Requires CASE_READ.

A case reader can see:

- snapshot ID;
- timestamp;
- schema version;
- engine version;
- source document ID;
- snapshot SHA.

This metadata contains no source quote or rendered draft content.

### Snapshot payload

Requires DOCUMENT_READ in addition to CASE_READ.

The loaded payload may contain:

- exact source quotes;
- taxpayer-related facts;
- amounts;
- historical rendered draft text.

### Save current snapshot

Requires:

- CASE_READ;
- DOCUMENT_READ;
- CASE_UPDATE.

The current recomputation must exist in session before the Save current analysis snapshot action appears.

## 4. Independent history access

Snapshot history does not require the user to recompute current analysis first.

A user may select a case and inspect/load historical analysis directly when permissions allow.

This avoids unnecessary LLM calls when the professional only wants to review prior system output.

## 5. Historical renderer

Historical JSON uses a dedicated renderer.

It shows:

- snapshot metadata;
- historical classification;
- historical deadline data;
- validation summary;
- stored facts;
- arithmetic data;
- historical rendered draft sections.

It is labelled:

> Historical record only.

The renderer does not call the live Phase-2 result renderer.

## 6. Save behavior

When a case is currently recomputed and the user has CASE_UPDATE:

`Save current analysis snapshot`

creates a new immutable historical record.

Multiple snapshots for the same case/source notice are allowed. They form analysis history rather than overwriting an earlier result.

The save records:

- current snapshot schema version;
- current engine version;
- source notice binding;
- authenticated principal as creator/audit actor.

## 7. Case status

The first successfully saved snapshot may promote:

INTAKE -> ANALYZED

through the Phase 3F.4 repository transaction.

The UI does not manually change case status.

Later workflow statuses are not demoted by snapshot save.

## 8. Session caching

A loaded historical snapshot is cached temporarily in Streamlit session state using:

- selected snapshot ID;
- LoadedAnalysisSnapshot object.

The historical snapshot cache is cleared when:

- active firm changes;
- user logs out;
- a different saved case is opened.

It is not durable application state.

## 9. Current recomputation cache

The existing reopened current analysis remains separately cached by case ID.

Historical snapshot load does not overwrite:

- opened current case ID;
- current recomputed Phase2AnalysisResult;
- evidence workspace;
- current draft state.

## 10. Error disclosure

Snapshot initialization/save/list/load failures use generic user-facing messages.

Internal details such as:

- database paths;
- encrypted object keys;
- encryption exceptions;
- ciphertext details;
- parser failures;

are not rendered.

## 11. Product meaning

Dwaar can now answer both:

> What does the current engine think about this notice?

and:

> What did Dwaar produce when this case was analyzed previously?

without conflating the two.

This is necessary for professional auditability when prompts/models/engines evolve.

## 12. Exit criteria

- snapshot metadata is visible with CASE_READ;
- payload content remains hidden without DOCUMENT_READ;
- history can be viewed without recomputing current analysis;
- historical JSON uses a dedicated read-only renderer;
- historical load does not invoke current Phase-2 analysis;
- current recomputation can be saved only with CASE_UPDATE;
- saved snapshot is a new history record, not overwrite;
- historical/current session caches remain separate;
- firm switch/logout clears historical snapshot cache;
- failures do not leak persistence/encryption details;
- full regression suite passes.
