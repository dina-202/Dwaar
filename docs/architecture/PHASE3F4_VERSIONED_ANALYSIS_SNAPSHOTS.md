# Phase 3F.4 — Versioned Encrypted Analysis Snapshots

**Status:** Historical analysis persistence boundary  
**Date:** 22 September 2026  
**Depends on:** Phase 3D encrypted persistence, Phase 3F.3 saved-case reopen

## 1. Purpose

Phase 3F.4 adds durable historical records of structured Dwaar analysis without treating arbitrary Python objects as persistent data.

A saved analysis snapshot answers:

> What structured result did this version of Dwaar produce from this exact persisted notice at this point in time?

It does not answer:

> What would the current engine produce now?

Those are separate product concepts.

## 2. Serialization decision

Dwaar snapshots use an explicit JSON schema.

They do not use:

- pickle;
- marshal;
- shelve;
- jsonpickle;
- YAML object construction;
- generic dataclass recursion;
- dynamic import/class reconstruction.

The serializer is a curated projection. New fields added to runtime dataclasses do not silently enter persisted history.

A snapshot schema change requires an explicit schema-version decision.

This follows secure-deserialization guidance favoring simple data formats and strict type/schema constraints over native object deserialization.

## 3. Versions

Initial constants:

- schema_version = 1
- engine_version = phase2-contract-2026.09.22.1

The engine version identifies the semantic analysis contract represented by the snapshot.

Future material changes to classification/extraction/calculation/validation/drafting semantics must deliberately bump the engine version before newly generated snapshots claim compatibility.

Historical snapshots with an unsupported schema/engine are not reconstructed as live domain objects.

## 4. Source binding

Every snapshot is bound to exactly one persisted source notice using:

- source_document_id;
- source_document_sha256.

The SQLite repository verifies at save time that:

- source document exists;
- source document belongs to the snapshot case;
- stored document SHA-256 equals the snapshot source SHA.

The encrypted JSON payload repeats the same source binding.

Load verifies relational metadata and decrypted payload binding again.

## 5. Snapshot contents

Schema v1 persists explicit projections of:

- classification;
- fact extraction status;
- extracted facts and exact provenance;
- source origin/source verification;
- deterministic deadline result;
- deterministic preflight result;
- arithmetic results;
- validation status/checks;
- workflow requirements;
- evidence checklist;
- review requirements;
- rendered specialist draft sections;
- post-draft validation;
- triage summary.

Dates are ISO-8601 strings.

Decimal/money values are decimal strings, not binary floats.

Enums are stable enum values.

## 6. Sensitive-data classification

Snapshot payloads are sensitive.

They may contain:

- exact notice quotes;
- taxpayer-related claims;
- amounts;
- professional review requirements;
- rendered draft text.

Therefore snapshot JSON is stored only through the same AES-256-GCM DocumentStore used for confidential documents.

SQLite stores snapshot metadata only.

Audit events store metadata only.

## 7. AnalysisSnapshotRef

Relational snapshot metadata contains:

- snapshot_id;
- case_id;
- source_document_id;
- source_document_sha256;
- schema_version;
- engine_version;
- encrypted plaintext byte size;
- snapshot JSON SHA-256;
- opaque encrypted storage key;
- created_at;
- created_by.

It contains no source quote, fact claim or rendered draft text.

## 8. Database schema migration

The Dwaar SQLite metadata schema moves from version 1 to version 2.

Version 2 adds:

- analysis_snapshots table;
- case/created index.

Existing version-1 databases are migrated idempotently by creating the new table/index and updating schema_meta to 2.

Unexpected versions still fail closed.

## 9. Save transaction

Snapshot JSON is:

1. explicitly projected;
2. deterministically UTF-8 JSON encoded;
3. SHA-256 hashed;
4. encrypted/stored through DocumentStore.

Then SQLite atomically:

1. inserts AnalysisSnapshotRef;
2. appends ANALYSIS_SAVED CaseEvent;
3. promotes CaseStatus from INTAKE to ANALYZED when and only when current status is INTAKE.

If SQLite fails, the encrypted snapshot object is deleted as compensating rollback.

If that deletion also fails, Dwaar raises a distinct consistency error for operational remediation.

## 10. Case-status semantics

A first successful durable snapshot allows:

INTAKE -> ANALYZED

Snapshot saving never demotes later workflow states.

For example, DRAFT_REVIEW remains DRAFT_REVIEW after an additional snapshot is saved.

## 11. Audit event

ANALYSIS_SAVED stores only controlled metadata:

- snapshot ID;
- source document ID/hash;
- schema version;
- engine version;
- snapshot JSON hash;
- byte size.

It does not contain:

- source_text;
- claims;
- taxpayer identifiers;
- rendered draft;
- snapshot JSON;
- encryption key.

## 12. Authorization

Snapshot history is case/tenant scoped.

### List snapshot metadata

Requires CASE_READ through the normal authorized case boundary.

### Load snapshot payload

Requires:

- CASE_READ;
- DOCUMENT_READ.

DOCUMENT_READ is required because the snapshot contains source quotes and notice-derived confidential content.

### Save snapshot

Requires:

- CASE_READ;
- DOCUMENT_READ;
- CASE_UPDATE.

The authenticated principal becomes created_by and the ANALYSIS_SAVED audit actor.

## 13. Load behavior

Load performs:

1. snapshot metadata lookup;
2. case/source-document relationship checks;
3. supported schema/engine check;
4. AES-GCM decrypt;
5. exact byte-size check;
6. snapshot JSON SHA-256 check;
7. strict UTF-8 JSON parsing;
8. top-level schema validation;
9. source binding validation inside decrypted payload.

The result is:

LoadedAnalysisSnapshot(metadata, payload)

where payload is plain JSON-compatible data.

Dwaar does not deserialize historical JSON into live Phase2AnalysisResult objects.

## 14. Historical versus current analysis

A historical snapshot is immutable evidence of prior system output.

It must not automatically drive a new filing/draft action after the engine has changed.

For current actions, Dwaar should:

- recompute from the encrypted source notice with the current engine; or
- later implement an explicit snapshot migration/revalidation contract.

The UI should eventually show both:

- Saved analysis — timestamp/version;
- Recompute with current engine.

## 15. Runtime configuration

Snapshots reuse the same:

- DWAAR_DB_PATH;
- DWAAR_OBJECT_ROOT;
- DWAAR_DOCUMENT_KEY_B64.

No second analysis database or encryption key is introduced.

## 16. Current UI scope

Phase 3F.4 establishes the backend/history boundary only.

A later UI unit should allow:

- saving the current recomputed analysis as a historical snapshot;
- listing snapshot history;
- viewing a selected historical snapshot as historical data;
- comparing it with a fresh recomputation.

It must not silently replace the current live analysis with historical JSON.

## 17. Exit criteria

- schema/engine versions are explicit;
- serializer uses curated JSON projection;
- no native Python object deserialization is used;
- source notice ID/hash are bound in DB metadata and JSON;
- snapshots are AES-GCM encrypted;
- plaintext source quotes/draft text are absent from object ciphertext;
- metadata/event surfaces exclude snapshot content;
- SQLite v1 databases migrate to v2;
- save metadata/event/status is one DB transaction;
- encrypted object rolls back on DB failure;
- load validates size/hash/schema/engine/source binding;
- loaded snapshot remains plain data;
- save/load authorization is tenant scoped;
- full regression suite passes.
