# Phase 3C.1 — Persistent Case and Evidence Domain Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026  
**Scope:** Domain contracts only; no database/runtime persistence in this unit.

## Why this layer exists

Dwaar's Phase-2/3A engine analyzes one uploaded notice safely, but a commercial CA-firm product needs continuity:

```text
Notice Received
→ Analysis
→ Evidence Requested / Added
→ Draft Prepared
→ CA Review
→ Reply Filed
→ Acknowledgement
→ Hearing / Order
→ Further Action
```

The existing architecture already anticipated this lifecycle. Phase 3C makes it a first-class domain concept.

## Storage direction

Production persistence should target PostgreSQL behind a repository/data-access boundary.

Reasoning:
- multi-firm SaaS contains highly confidential tenant data;
- OWASP recommends enforceable tenant isolation rather than trusting a tenant identifier supplied by a request;
- PostgreSQL row-level security can provide a database-enforced second boundary;
- Streamlit can connect through SQLAlchemy, but Streamlit/SQLAlchemy must not become domain dependencies.

This unit deliberately does **not** add SQLAlchemy, Alembic, PostgreSQL drivers or Streamlit state.

## Tenant isolation rule

Every tenant-owned persistent record carries `tenant_id`.

That field is **not authorization proof**.

Future request handling must derive tenant context from server-verified identity/membership. The storage layer must enforce tenant ownership on every tenant-scoped access path. A client-supplied tenant ID may select a resource only after authorization; it may never establish authorization.

## Documents

Confidential document bytes must not be stored inside domain/database records.

`CaseDocumentRecord` stores:
- metadata;
- SHA-256 content hash;
- object-storage key;
- upload timestamp.

The future object store must use tenant-scoped authorization and short-lived signed access where appropriate.

SHA-256 proves byte identity/equality only. It does not prove legal authenticity.

## Core records

### ClientRecord
Firm-scoped client identity.

### TaxRegistrationRecord
Links a client to a GST registration.

### CaseRecord
Persistent matter/case identity and operational status.

### CaseDocumentRecord
Metadata for notice, annexure, evidence, drafts, final reply, acknowledgement, hearing document or order.

### EvidenceLinkRecord
Many-to-many bridge from uploaded documents to workflow evidence requirements.

One document may support several requirements; one requirement may require several documents.

Evidence review states:
- UNREVIEWED
- VERIFIED
- REJECTED
- CONFLICTING

"Uploaded" never means "verified."

### AnalysisRunRecord
Pins an analysis to:
- case;
- notice document;
- engine version;
- run timestamp/status.

This prevents later fact/draft review from pretending all analyses were produced by the same engine revision.

### DraftVersionRecord
Tracks a draft artifact and the analysis run it came from.

### FilingRecord
Records final filed reply, filing timestamp, portal reference and acknowledgement document.

### CaseEventRecord
Append-oriented case timeline record for lifecycle events.

## Status semantics

`CaseStatus` is operational workflow state, not a legal conclusion:

- INTAKE
- ANALYZING
- EVIDENCE_PENDING
- DRAFTING
- REVIEW
- READY_TO_FILE
- FILED
- POST_FILING
- CLOSED

No status means "legally valid", "won", "approved by authority" or similar.

## Security requirements for the future storage unit

The database/storage implementation must:

1. use PostgreSQL for the production shared-table design;
2. enable row-level security on every classified tenant-owned table;
3. use an ordinary application role that cannot bypass RLS;
4. establish tenant context from authenticated membership per transaction;
5. include negative cross-tenant tests for every tenant-owned table;
6. keep object-storage authorization tenant-aware;
7. never log client documents or raw confidential evidence;
8. keep database/object-store credentials outside source control;
9. use migrations rather than startup-time ad-hoc table creation;
10. define retention/deletion behavior before a production pilot.

## Explicit non-goals for this unit

- no authentication provider choice;
- no database schema/migration;
- no ORM;
- no object-store provider;
- no UI;
- no file upload persistence;
- no portal integration;
- no automatic evidence verification;
- no mutable in-memory case service.

Those follow after the contracts are stable.

## Exit criteria

- persistent lifecycle objects cover the architecture's original notice/evidence/draft/filing/acknowledgement/hearing-order requirements;
- every tenant-owned record is tenant-scoped;
- document bytes/raw text are absent from persistent record contracts;
- evidence upload and evidence verification are distinct;
- analysis/draft records are version-linked;
- domain file has no framework/database imports;
- full existing regression suite remains green.
