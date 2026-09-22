# Phase 3F.3 — Saved Case Reopen and Reanalysis

**Status:** Pilot case workspace  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.1 durable case intake, Phase 3F.2 save-as-intake UI

## 1. Purpose

Phase 3F.3 makes durable intake cases useful after the original browser/session is gone.

A professional can:

1. list saved cases for the active firm;
2. select a case;
3. open its persisted notice;
4. decrypt and integrity-check the notice through the authorized service;
5. rerun the current structured analysis engine;
6. continue temporary evidence/review work from that recomputed result.

## 2. Permission split

Firm admission now considers either:

- CASE_CREATE; or
- CASE_READ.

The active firm record also carries the caller's exact persisted permission set.

The UI then gates capabilities independently:

### New notice intake

Requires:

- CASE_CREATE.

A read-only user does not see the new notice uploader.

### Saved case listing

Requires:

- CASE_READ.

A create-only user does not see saved case browsing.

### Opening persisted notice bytes

Requires:

- DOCUMENT_READ.

A user with CASE_READ but without DOCUMENT_READ may see case metadata but cannot open/decrypt the notice.

## 3. Tenant isolation

All saved-case operations are scoped to the active firm.

AuthorizedCaseService:

- lists cases only for the granted firm;
- treats cross-firm case IDs as unavailable;
- lists document metadata only after DOCUMENT_READ authorization;
- decrypts a document only after DOCUMENT_READ authorization and case ownership checks.

Knowing another firm's case/document ID is not sufficient to retrieve it.

## 4. Notice selection rule

A reopenable intake case must contain exactly one document with kind:

`NOTICE`

Zero NOTICE documents fail closed.

Multiple NOTICE documents also fail closed.

Dwaar does not guess which notice is authoritative.

Future multi-notice/amended-notice cases require an explicit version/authority contract rather than implicit selection.

## 5. Integrity boundary

The reopen path never reads encrypted files directly from Streamlit.

It calls AuthorizedCaseService.read_document(), which:

1. authorizes DOCUMENT_READ;
2. proves case/firm ownership;
3. loads/decrypts the AES-GCM object;
4. checks plaintext byte size against StoredDocumentRef;
5. checks plaintext SHA-256 against StoredDocumentRef.

Only verified plaintext proceeds to PDF parsing.

## 6. Reanalysis

After the verified notice PDF is loaded:

- page-aware extraction runs;
- OCR fallback rules remain active;
- current Phase-2 classification/extraction/deadline/arithmetic/validation/drafting logic runs.

The result is explicitly labelled:

`recomputed_from_encrypted_notice`

This is not presented as a previously persisted analysis.

## 7. Why recompute instead of loading old AI output

Dwaar still does not persist a versioned analysis snapshot.

Recomputation is safer than serializing arbitrary Python/LLM output because it avoids pretending an unversioned blob has stable semantics.

A future analysis snapshot must record at least:

- schema version;
- engine version;
- prompt/model routing metadata;
- source document identity/hash;
- fact/provenance contracts;
- deterministic calculation inputs/results;
- validation profile version;
- recompute/migration policy.

Until then, the encrypted notice remains the durable source of truth.

## 8. Session cache

Opening a saved case stores the reopened result in Streamlit session state for responsiveness.

The cached reopen state is bound to the selected case ID and is cleared when:

- the active firm changes;
- the user logs out;
- a different saved case is opened.

An unrelated rerun in the same session does not re-run analysis for the already-opened selected case.

This is only a temporary UI cache.

## 9. Error disclosure

The saved-case UI uses generic user-facing errors for:

- authorization loss;
- missing case;
- missing/multiple notice documents;
- decryption/integrity/parsing failures;
- unexpected persistence/runtime failures.

Internal object-store paths, keys, parser exceptions and database details are not rendered.

## 10. Current limitation

Case listing currently shows core case metadata only.

Client display name/GSTIN enrichment, filters/search, assignment/reviewer display, activity timeline and status transitions remain future case-workspace work.

## 11. Exit criteria

- CASE_READ users can list firm-scoped cases;
- create-only users do not gain case browsing;
- read-only users do not gain new-intake upload;
- DOCUMENT_READ is separately required to open notice bytes;
- exactly one NOTICE document is required;
- persisted notice is integrity-checked before parsing;
- current analysis is recomputed from encrypted notice;
- reopened result is session-cached without cross-firm leakage;
- controlled failures do not leak internals;
- full regression suite passes.
