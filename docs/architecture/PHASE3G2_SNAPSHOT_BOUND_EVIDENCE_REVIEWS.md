# Phase 3G.2 — Snapshot-Bound Durable Evidence Reviews

**Status:** Pilot durable professional review history  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.4 analysis snapshots, Phase 3G.1 durable supporting evidence

## 1. Purpose

Phase 3G.2 makes human Confirm/Reject decisions over supporting-evidence candidates durable.

A durable decision answers:

> What did this authenticated professional decide about this exact source-grounded evidence candidate, against this exact saved analysis/checklist version?

It does not answer:

> Is the taxpayer fact legally proven, is the evidence requirement automatically satisfied, or may Dwaar file/draft without further review?

Those are separate future contracts.

## 2. Why reviews are bound to an analysis snapshot

Evidence requirement IDs and checklist wording belong to an analysis/workflow contract.

A later engine version may:

- add requirements;
- remove requirements;
- rename/reframe requirements;
- change evidence-checklist composition.

Therefore a durable review must never float against only the current live analysis.

Every review is bound to:

- case ID;
- saved analysis snapshot ID;
- evidence requirement ID from that snapshot;
- persisted supporting document ID;
- physical source page;
- SHA-256 of the exact source quote;
- a stable candidate fingerprint.

The selected historical snapshot is the authoritative review context.

## 3. Transient candidate IDs are not durable identity

EvidenceCandidate IDs such as:

`EC-001`

are generated from candidate order and may change after reanalysis.

They are stored inside the encrypted historical payload for user/audit context only.

They are not used as the durable uniqueness key.

## 4. Stable candidate fingerprint

The durable fingerprint is SHA-256 over the namespaced tuple:

```text
DWAAR-EVIDENCE-REVIEW-CANDIDATE-V1
snapshot_id
evidence_id
document_id
source_page
source_text_sha256
```

The database enforces:

`UNIQUE(snapshot_id, candidate_fingerprint)`

This means the same grounded candidate cannot receive two competing durable terminal decisions for the same analysis snapshot merely because a future matching run gives it a different `EC-...` label.

A future change/reversal workflow must be explicit and append-only; Phase 3G.2 does not overwrite prior review history.

## 5. SQLite schema v3

The shared metadata database moves from schema version 2 to version 3.

Version 3 adds:

`evidence_reviews`

Metadata fields:

- review_id;
- case_id;
- snapshot_id;
- evidence_id;
- document_id;
- source_page;
- source_text_sha256;
- candidate_fingerprint;
- decision;
- encrypted payload byte size;
- encrypted plaintext SHA-256;
- opaque storage key;
- reviewed_at;
- reviewed_by.

Foreign keys bind reviews to:

- CaseRecord;
- AnalysisSnapshotRef;
- StoredDocumentRef.

The repository additionally verifies that the referenced document is `SUPPORTING_EVIDENCE`.

Existing schema-v1 or schema-v2 pilot databases migrate idempotently to v3.

Unknown schema versions still fail closed.

## 6. Sensitive content split

The exact evidence quote and reviewer note are confidential professional/client data.

They are not stored as plain SQLite columns.

They are not stored in CaseEvent payload JSON.

SQLite stores only controlled metadata and cryptographic hashes.

The encrypted review payload stores:

- schema version;
- case/snapshot/evidence/document/page binding;
- source quote hash;
- candidate fingerprint;
- transient candidate ID;
- exact source quote;
- source origin;
- source verification status;
- Confirmed/Rejected decision;
- optional reviewer note;
- reviewed timestamp;
- authenticated reviewer ID.

The payload is deterministic UTF-8 JSON and is stored only through the AES-256-GCM DocumentStore.

## 7. No native object deserialization

Evidence-review payloads do not use:

- pickle;
- marshal;
- shelve;
- jsonpickle;
- YAML object construction;
- object_hook class reconstruction.

Load returns validated plain JSON-compatible data plus typed metadata.

## 8. Save authorization and provenance verification

Saving a durable review requires:

`EVIDENCE_REVIEW`

The normal authorized case/snapshot/document boundaries additionally require the relevant case/document read permissions.

Before persistence, Dwaar verifies:

1. the case belongs to the selected firm;
2. the selected analysis snapshot belongs to that case;
3. the candidate `evidence_id` exists in that selected snapshot's evidence checklist;
4. the candidate document belongs to the case;
5. the candidate document is persisted `SUPPORTING_EVIDENCE`;
6. the encrypted document decrypts and passes size/SHA-256 integrity checks;
7. the PDF can be reparsed;
8. the exact candidate source quote occurs on the claimed physical page;
9. the reparsed page source-origin channel equals the candidate source origin;
10. the reparsed page verification state equals the candidate source verification state.

Only then may Confirm/Reject be persisted.

## 9. Snapshot checklist projection

The review service exposes the selected snapshot's evidence checklist as a closed list of:

- evidence_id;
- requirement_text;
- EvidenceStatus.

It does not reconstruct the historical snapshot into a live `Phase2AnalysisResult`.

Malformed, duplicate or unknown checklist values fail closed.

Evidence matching in the saved-case UI runs against this selected historical checklist, not whichever live checklist the current engine happens to produce.

## 10. Save transaction and cross-store rollback

The review JSON is:

1. explicitly built;
2. schema validated;
3. deterministically encoded;
4. SHA-256 hashed;
5. encrypted/stored through DocumentStore.

Then SQLite atomically:

1. inserts EvidenceReviewRef;
2. appends EVIDENCE_REVIEWED CaseEvent.

If SQLite fails, the encrypted review object is deleted as compensating rollback.

If deletion also fails, Dwaar raises a distinct consistency error for operational remediation.

## 11. Audit event

EVIDENCE_REVIEWED contains controlled metadata such as:

- review ID;
- snapshot ID;
- evidence ID;
- supporting document ID;
- source page;
- source quote SHA-256;
- candidate fingerprint;
- decision;
- encrypted review payload SHA-256;
- byte size.

It intentionally excludes:

- source quote;
- reviewer note;
- document bytes;
- snapshot JSON;
- secrets/tokens.

The generic CaseEvent validator now also prohibits a `reviewer_note` key, in addition to existing raw/source-text/secret prohibitions.

## 12. Load-time integrity

Loading a durable review verifies:

- metadata exists;
- encrypted object decrypts;
- byte size matches metadata;
- payload SHA-256 matches metadata;
- JSON/schema is valid;
- source quote SHA-256 recomputes correctly;
- candidate fingerprint recomputes correctly;
- case/snapshot/evidence/document/page binding matches metadata;
- decision matches metadata;
- reviewer identity matches metadata;
- timestamp matches metadata.

Identifiers are compared exactly/case-sensitively.

Cryptographic hashes are normalized only for hexadecimal case.

## 13. Saved-case UI

A professional with EVIDENCE_REVIEW now uses this flow:

1. open saved case;
2. attach encrypted supporting evidence if needed;
3. select a saved analysis snapshot;
4. Dwaar loads that snapshot's historical evidence checklist;
5. click **Analyze attached evidence for selected snapshot**;
6. inspect source-grounded candidates;
7. Confirm or Reject a candidate;
8. Dwaar persists the decision immediately as encrypted durable history;
9. durable review metadata appears under **Durable evidence review history**;
10. encrypted quote/reviewer-note details are decrypted only when the user explicitly clicks **View encrypted review details**.

If no analysis snapshot exists, durable review is blocked with a prompt to save an analysis snapshot first.

## 14. Historical independence from the live engine

Durable evidence review history is intentionally not gated by the current live analysis having an evidence checklist.

A future engine version may change the live checklist.

Past snapshot-bound review history must remain visible and auditable independently.

## 15. Current non-goals

A `CONFIRMED` durable review does **not** automatically:

- create or modify an ExtractedFact;
- change FactStatus;
- mark an EvidenceChecklistItem PRESENT;
- change RequirementStatus;
- alter arithmetic;
- change DraftEligibility;
- regenerate a draft;
- approve filing;
- establish legal truth.

Phase 3G.2 records a professional's decision over evidence provenance.

A future evidence-to-workpaper/fact-promotion contract must specify deterministic rules for how reviewed evidence can affect current analysis, with explicit CA control and provenance.

## 16. Runtime configuration

Evidence reviews reuse the existing:

- DWAAR_DB_PATH;
- DWAAR_OBJECT_ROOT;
- DWAAR_DOCUMENT_KEY_B64.

No second database or encryption key is introduced.

## 17. Exit criteria

- SQLite v3 migration is deterministic and fail-closed;
- review metadata excludes source quotes and notes;
- quote/note content is AES-GCM encrypted;
- review payload schema is explicit/versioned;
- candidate identity is stable without relying on EC- sequence IDs;
- duplicate terminal decision for one snapshot candidate is rejected;
- EVIDENCE_REVIEW is enforced server-side;
- snapshot evidence_id membership is verified;
- supporting-document kind/case identity are verified;
- quote/page/source-origin/source-verification are reverified before save;
- review metadata + audit event are one DB transaction;
- encrypted payload rolls back on DB failure;
- load detects metadata/payload tampering;
- saved-case UI uses selected snapshot checklist;
- durable history survives current live-checklist changes;
- Confirm/Reject does not automatically modify legal/factual/drafting state;
- full regression suite passes.
