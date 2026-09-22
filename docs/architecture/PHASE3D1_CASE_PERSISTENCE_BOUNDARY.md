# Phase 3D.1 — Persistent Case and Storage Boundary

**Status:** Architecture amendment  
**Date:** 22 September 2026

## 1. Decision

Dwaar now needs durable case continuity, but persistence must not couple the domain to one database or treat sensitive tax documents as ordinary application blobs.

Phase 3D.1 therefore defines two independent ports:

1. **CaseRepository** — relational/business metadata and append-only case events.
2. **DocumentStore** — raw binary payloads addressed only by application-generated storage keys.

No concrete database or blob-store implementation is activated in this phase.

## 2. Why documents and metadata are separated

Tax notices and supporting records may contain personal, financial and government identifiers.

OWASP file-upload guidance recommends:
- allowlisting business-required file types;
- validating type rather than trusting the HTTP content-type header;
- generated storage names;
- file-size limits;
- authorization;
- storage outside the webroot / segregated storage;
- malware/CDR controls where appropriate.

OWASP also notes that storing upload blobs directly in a relational database introduces storage, backup and performance trade-offs.

Accordingly, Dwaar's relational record stores only a **StoredDocumentRef**. Document bytes belong behind the separate DocumentStore boundary.

## 3. Data protection direction

The notified Digital Personal Data Protection Rules, 2025 include reasonable-security-safeguard requirements such as encryption, access controls, monitoring, backups, and breach detection/response/logging.

Dwaar should therefore assume that production client documents require:
- encryption in transit and at rest;
- tenant/firm authorization before document access;
- key-management separation;
- retention/deletion controls;
- protected audit logs;
- breach-response capability.

This architecture amendment is a technical design decision, not a legal-compliance opinion.

## 4. Case hierarchy

Initial persistent product hierarchy:

```text
Firm
  -> Client
      -> TaxRegistration
          -> Case
              -> StoredDocumentRef[]
              -> CaseEvent[]
```

A Case can temporarily have no TaxRegistration when intake information is incomplete.

## 5. Case status

CaseStatus is operational workflow state only:

- INTAKE
- ANALYZED
- EVIDENCE_COLLECTION
- DRAFT_REVIEW
- FILED
- HEARING
- ORDER_RECEIVED
- CLOSED

No status represents legal merits, likelihood of success, authority validity or filing approval.

## 6. Document kinds

The closed initial vocabulary is:

- NOTICE
- ANNEXURE
- SUPPORTING_EVIDENCE
- DRAFT
- FILED_RESPONSE
- ACKNOWLEDGEMENT
- HEARING_DOCUMENT
- ORDER
- OTHER

The original user filename is metadata only. It must never become the physical/object storage key.

## 7. Audit events

CaseEvent is append-oriented metadata. Initial event vocabulary:

- CASE_CREATED
- CASE_STATUS_CHANGED
- DOCUMENT_ADDED
- DOCUMENT_REMOVED
- ANALYSIS_SAVED
- EVIDENCE_CANDIDATES_GENERATED
- EVIDENCE_REVIEWED
- DRAFT_CREATED
- DRAFT_REVIEWED
- FILING_RECORDED
- HEARING_RECORDED
- ORDER_RECORDED

Event payloads must not contain:
- raw notice/evidence text;
- document bytes;
- access tokens;
- passwords;
- database connection strings;
- encryption keys.

OWASP logging guidance specifically recommends recording meaningful security/business events while excluding or masking secrets and sensitive personal data.

## 8. Immutability

Persistent domain records in this phase are frozen dataclasses.

Updates occur by creating a replacement CaseRecord plus a CaseEvent, rather than mutating a shared in-memory object in place.

The future concrete repository must update both transactionally where supported.

## 9. Database direction

The concrete implementation is intentionally deferred one unit.

Current research:
- SQLAlchemy 2.0 supports both SQLite and PostgreSQL through the same higher-level toolkit.
- SQLite is appropriate for a local/single-process pilot backend.
- PostgreSQL is the likely multi-user SaaS backend.

Phase 3D.2 should therefore evaluate a repository implementation behind the existing port rather than exposing SQLAlchemy objects throughout domain code.

The domain must remain database-agnostic.

## 10. Binary storage direction

The DocumentStore implementation must satisfy, before production activation:

- generated opaque storage keys;
- path traversal impossible by construction;
- bytes stored outside application web/static roots;
- exact content SHA-256 recorded;
- maximum-size enforcement before parsing/storage;
- PDF signature/type validation;
- per-firm/case authorization above the low-level store;
- encryption-at-rest strategy;
- deletion/retention semantics;
- no raw-document body in application logs.

A local pilot implementation may exist only when these boundaries are explicit.

## 11. Exit criteria

Phase 3D.1 is complete when:

- Firm/Client/TaxRegistration/Case contracts exist;
- case/document/event enums are closed and tested;
- raw bytes are absent from relational document metadata contracts;
- CaseRepository is a replaceable Protocol;
- DocumentStore is a separate replaceable Protocol;
- audit-event payload rules are documented;
- no production persistence is silently activated;
- full regression suite passes.
