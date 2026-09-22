# Phase 3F.5 — Analysis Snapshot History UI

**Status:** Pilot historical-analysis UI  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.3 saved-case reopen, Phase 3F.4 versioned encrypted analysis snapshots

## 1. Purpose

Phase 3F.5 exposes the Phase 3F.4 historical snapshot backend in the authenticated saved-case workspace.

The UI now separates three concepts:

1. live recomputation from the encrypted notice using the current engine;
2. immutable historical analysis snapshots;
3. an explicit action to save the current recomputation as new history.

Historical JSON is never silently rehydrated into a live Phase2AnalysisResult.

## 2. Live saved-case analysis

Opening a saved case still:

- authorizes the case;
- decrypts and integrity-checks the persisted notice;
- parses the notice;
- runs the current Phase-2 engine;
- stores the live result in temporary session state.

The UI labels this:

`analysis_source = recomputed_from_encrypted_notice`

## 3. Explicit current-engine rerun

Once a case is open, the user may click:

**Re-run with current engine**

This forces a fresh authorized decrypt/parse/reanalysis even when the same case already has a session-cached result.

A successful rerun:

- replaces the cached live analysis;
- clears any opened historical snapshot;
- clears temporary evidence workspace state.

This makes comparison with historical snapshots deliberate rather than relying on accidental Streamlit reruns.

## 4. Snapshot history

For an opened case the UI builds the authorized analysis-snapshot service and lists durable snapshot metadata.

History rows show:

- snapshot ID;
- creation timestamp;
- schema version;
- engine version;
- source document ID.

Snapshot ciphertext remains behind the encrypted DocumentStore.

## 5. Save current analysis

The button:

**Save current analysis snapshot**

is rendered only when the active firm grant includes `CASE_UPDATE`.

Saving uses the current live recomputation.

The backend still independently enforces:

- CASE_READ;
- DOCUMENT_READ;
- CASE_UPDATE;
- source-document binding;
- tenant equality.

The authenticated principal remains the snapshot creator/audit actor.

After a successful save, the UI refreshes history. If refresh fails after the snapshot was already saved, Dwaar reports that distinction rather than implying the save itself failed.

## 6. Historical snapshot viewing

A user may select a snapshot and click:

**View historical snapshot**

The backend decrypts and verifies the selected snapshot through the Phase 3F.4 load path.

The UI displays it as:

**Historical analysis snapshot**

with a prominent warning that it is historical data and not a substitute for current-engine recomputation.

## 7. Historical payload boundary

Historical snapshots remain plain validated JSON-compatible data.

The UI reads only their curated schema sections for display.

It does not:

- convert historical JSON into Phase2AnalysisResult;
- pass it to drafting engines;
- pass it to evidence matching;
- use it to update current deadlines/arithmetic;
- use it to alter draft eligibility;
- allow it to drive filing actions.

## 8. Historical draft text

Snapshot schema v1 may contain rendered specialist draft sections.

When shown, they are prefixed/labeled as historical and accompanied by:

> Historical draft text below is preserved for audit/history only.

Historical draft prose is not rendered through the live-draft safety gate because it is not being presented as a newly generated current draft; it is an immutable record of prior system output.

Current professional action still requires a fresh live analysis/review path.

## 9. Permissions

### List history

Requires case visibility through CASE_READ.

### View historical payload

Requires the backend snapshot load path, which also resolves the notice through DOCUMENT_READ.

### Save current analysis

Requires CASE_UPDATE in addition to the existing read/document requirements.

A CASE_READ + DOCUMENT_READ user can view history but receives no Save current analysis snapshot button.

## 10. Session isolation

Opened historical snapshot state is stored only in temporary Streamlit session state.

It is cleared when:

- active firm changes;
- user logs out;
- a different saved case is opened;
- the current saved case is explicitly re-run with the current engine.

This prevents stale history from appearing under a different tenant/case/live recomputation.

## 11. Failure disclosure

Snapshot-history configuration, persistence, decrypt/integrity and lookup failures produce controlled generic UI errors.

Backend database paths, encryption details and ciphertext/internal exception text are not rendered.

A special post-save refresh failure states:

- the snapshot was saved;
- history refresh failed.

This avoids encouraging a duplicate retry when the durable save already succeeded.

## 12. Historical versus current product semantics

Dwaar now has a clear UI distinction:

```text
Saved notice
   |
   +--> Re-run with current engine --> Live analysis
   |                                  |
   |                                  +--> Save current analysis snapshot
   |
   +--> Historical snapshots --------> Read-only historical view
```

Historical snapshots are evidence of what Dwaar previously produced.

Live recomputation is what Dwaar currently produces.

Neither silently replaces the other.

## 13. Exit criteria

- opened case shows analysis history;
- read-only case users can list/view history;
- CASE_UPDATE controls the save button;
- current recomputation can be explicitly re-run;
- save creates durable history through the authorized snapshot service;
- selected history loads through encrypted/integrity-checked backend;
- historical data is clearly labeled;
- historical payload never enters live analysis/drafting code;
- firm/case/rerun changes clear stale historical session state;
- snapshot errors do not leak backend detail;
- full regression suite passes.
