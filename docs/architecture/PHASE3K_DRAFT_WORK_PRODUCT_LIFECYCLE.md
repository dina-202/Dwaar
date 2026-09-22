# Phase 3K — Durable Draft Work-Product Lifecycle

**Status:** Pilot professional draft versioning/review/export  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.4 analysis snapshots, Phase 3J case operations

## 1. Purpose

Phase 3K turns Dwaar's validated generated draft into durable professional work product.

A CA may now:

1. select a saved analysis snapshot;
2. create one generated baseline from that snapshot;
3. edit the professional text;
4. save each edit as a new immutable encrypted version;
5. review a specific immutable version;
6. approve that same immutable version;
7. export REVIEWED/APPROVED work product as DOCX.

Approval does not record filing.

## 2. Core distinction: generated baseline vs professional edits

A generated baseline is the only draft version that may claim direct origin from the validated Dwaar drafting engine.

It is created only from a saved analysis snapshot whose draft:

- has status SUCCESS;
- has a non-null post-validation result;
- has post-validation overall status PASS;
- contains at least one valid rendered section.

The generated baseline is rendered into editable professional text using the historical snapshot's validated draft sections.

Any later CA edit creates a new child version with:

`generated_baseline = false`

Human-edited text is professional work product and is not re-labelled as machine-provenance-controlled draft output.

## 3. SQLite schema v4

The shared database moves from schema version 3 to version 4.

Version 4 adds:

`draft_versions`

Metadata fields:

- draft_version_id;
- case_id;
- source_snapshot_id;
- parent_draft_version_id;
- version_number;
- generated_baseline;
- content_sha256;
- encrypted payload byte size;
- encrypted plaintext SHA-256;
- opaque storage key;
- review status;
- created timestamp / actor;
- reviewed timestamp / actor;
- approved timestamp / actor.

The actual draft text is not stored in SQLite.

Existing schema v1, v2 and v3 pilot databases migrate idempotently to v4.

Unknown future/unsupported schema versions still fail closed.

## 4. Immutable content versions

Each draft content version is append-only.

Draft content/version identity includes:

- case;
- source snapshot;
- parent draft version;
- version number;
- generated-baseline flag;
- content hash;
- encrypted payload hash/storage key;
- creation actor/time.

Review transitions may update only review metadata.

They cannot rewrite:

- draft text;
- source snapshot;
- parent lineage;
- version number;
- content hashes;
- encrypted storage identity;
- creation metadata.

## 5. Version numbering and lineage

Version numbers increase monotonically per case.

The first version is normally:

`v1 generated baseline`

A child edit must:

- reference the latest case draft version;
- use the same source snapshot as its parent;
- use the next case version number;
- set generated_baseline to false.

This prevents silent branching of professional text history.

A later saved analysis snapshot may start a new generated-baseline root.

That new baseline:

- has no parent draft version;
- uses the next global version number for the case;
- preserves all older draft lineages/history.

Only one generated baseline may be created from a given analysis snapshot.

## 6. Encrypted payload

Each immutable content version is encoded as deterministic UTF-8 JSON containing:

- schema version;
- case ID;
- source snapshot ID;
- parent draft version ID;
- version number;
- generated-baseline flag;
- draft text;
- creation timestamp;
- creator ID.

The payload is encrypted using the existing AES-256-GCM DocumentStore.

Plain professional draft text is not stored in SQLite.

## 7. No native object deserialization

Draft payload loading does not use:

- pickle;
- marshal;
- shelve;
- jsonpickle;
- YAML object construction;
- custom object hooks.

Loaded payloads remain validated plain JSON-compatible data plus typed metadata.

## 8. Cross-store consistency

To create a version:

1. build/validate payload;
2. deterministically encode it;
3. compute content SHA-256;
4. compute full payload SHA-256;
5. write encrypted payload;
6. atomically insert SQLite version metadata + DRAFT_CREATED audit event.

If SQLite fails after encrypted storage succeeds, Dwaar deletes the encrypted object as compensating rollback.

If rollback also fails, a distinct consistency exception is raised.

## 9. Load-time integrity

Loading a version verifies:

- metadata record exists;
- encrypted object decrypts;
- byte size matches metadata;
- payload SHA-256 matches metadata;
- JSON/schema is valid;
- case binding matches;
- source snapshot matches;
- parent identity matches;
- version number matches;
- generated-baseline flag matches;
- creation actor/time match;
- draft text recomputes to content_sha256.

Metadata/payload mismatch fails closed.

## 10. Review lifecycle

Review state is closed to:

- WORKING;
- REVIEWED;
- APPROVED.

Allowed transitions:

`WORKING -> REVIEWED -> APPROVED`

No skip, reverse or in-place edit is permitted.

If a reviewed or approved draft needs changes, the professional creates a new WORKING child version.

The prior reviewed/approved version remains immutable history.

## 11. Review authorization

Creating generated/edited draft versions requires:

`CASE_UPDATE`

Reading decrypted draft text requires:

`DOCUMENT_READ`

Reviewing/approving requires:

`DRAFT_REVIEW`

and verified document-read access.

The backend re-resolves the case and version within the active firm before action.

## 12. Review integrity

Before review/approval, Dwaar loads and integrity-verifies the encrypted immutable draft payload.

Review never applies only to unverified SQLite metadata.

Review metadata records:

- reviewed_at/by;
- approved_at/by.

The audit actor is always the authenticated principal.

## 13. Audit events

New draft content emits:

`DRAFT_CREATED`

with controlled metadata such as:

- version ID;
- source snapshot ID;
- parent version ID;
- version number;
- generated-baseline flag;
- content SHA-256;
- encrypted payload SHA-256;
- byte size.

Review transitions emit:

`DRAFT_REVIEWED`

with:

- version ID;
- version number;
- from status;
- to status;
- content SHA-256.

Plain draft text is never included in CaseEvent payloads.

The global event validator explicitly prohibits the `draft_text` key.

## 14. Professional editing semantics

The UI never overwrites an immutable version.

When a CA edits the selected latest version and clicks:

**Save edited draft as new version**

Dwaar calls the child-version persistence path.

Historical versions display read-only.

Only the latest version may seed a new textual edit.

## 15. Snapshot baseline UI

For a saved case, CASE_UPDATE users can select a saved analysis snapshot.

If that snapshot has not already seeded a baseline, they may click:

**Create generated draft baseline**

Snapshots without a successful post-validated draft fail safely and cannot seed professional work product.

If no analysis snapshot exists, Dwaar requires the professional to save one first.

## 16. Review UI

Users with DRAFT_REVIEW see a single valid next action:

- WORKING -> **Mark draft reviewed**
- REVIEWED -> **Approve draft**
- APPROVED -> no further review action

The UI does not present illegal review transitions.

## 17. DOCX export

Phase 3K adds deterministic semantic DOCX export using `python-docx`.

Export is permitted only for:

- REVIEWED;
- APPROVED.

WORKING draft versions cannot be exported through the professional export service.

The DOCX contains:

- case title;
- Dwaar version number;
- REVIEWED/APPROVED status;
- semantic headings parsed from the work-product text;
- professional draft text;
- source analysis snapshot ID;
- explicit note that approval does not record filing.

DOCX export does not:

- change CaseStatus;
- create a filed-document record;
- create an ARN;
- create a filing timestamp;
- claim portal submission.

## 18. Export surface safety

The Streamlit app contains one draft download surface:

**Download reviewed draft DOCX**

That surface is rendered only when the selected immutable version has REVIEWED or APPROVED status.

Raw live generated drafts and WORKING professional versions are not directly downloadable from this professional export path.

## 19. Sensitive-content boundary

The following remain encrypted:

- draft text;
- all immutable draft payload content.

SQLite stores only metadata, lineage, hashes and review-state timestamps/actors.

The audit table does not store draft text.

## 20. Runtime configuration

Draft work-product storage reuses:

- DWAAR_DB_PATH;
- DWAAR_OBJECT_ROOT;
- DWAAR_DOCUMENT_KEY_B64.

No separate encryption key or object store is introduced.

## 21. Current non-goals

Phase 3K does not yet implement:

- filing/submission;
- ARN/portal acknowledgement;
- filed-document immutability contract;
- electronic signatures;
- collaborative simultaneous editing;
- rich Word track-changes;
- automatic legal citation verification;
- automatic evidence-to-fact promotion.

These belong to later phases.

## 22. Exit criteria

- SQLite schema v4 migration is deterministic;
- draft text never appears in SQLite metadata/audit events;
- immutable draft payloads are encrypted;
- payload schema is explicit/versioned JSON;
- generated baseline requires successful post-validated snapshot draft;
- one baseline per source snapshot;
- later snapshots may start new baseline lineages;
- case version numbers are monotonic;
- edits create child versions instead of overwriting;
- child lineage cannot cross source snapshots;
- only latest version may be edited forward;
- WORKING -> REVIEWED -> APPROVED is one-way;
- review state does not mutate content identity;
- CASE_UPDATE gates version creation;
- DOCUMENT_READ gates decrypted content;
- DRAFT_REVIEW gates professional review/approval;
- tampering is detected on load;
- DB failure rolls encrypted payload back;
- WORKING drafts cannot export;
- reviewed/approved versions export deterministic DOCX;
- export does not imply filing;
- saved-case UI exposes full lifecycle;
- full offline regression suite passes.
