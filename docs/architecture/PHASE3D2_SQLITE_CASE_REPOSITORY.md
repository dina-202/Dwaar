# Phase 3D.2 — Local SQLite Case Metadata Repository

**Status:** Pilot backend  
**Date:** 22 September 2026  
**Depends on:** Phase 3D.1 persistence ports

## 1. Scope

Phase 3D.2 implements the CaseRepository port with SQLite for a local/single-node pilot.

It stores structured case metadata only.

It does **not** store raw notice, annexure or evidence bytes.

## 2. Why SQLite here

The immediate need is durable case metadata for a pilot, not distributed database infrastructure.

Python ships with the `sqlite3` driver, so this backend adds no dependency and keeps deployment simple. Because callers depend on the CaseRepository port rather than SQLite directly, a PostgreSQL implementation can replace it later without changing the domain.

SQLAlchemy remains a reasonable future migration/tooling choice when Dwaar needs multiple production database backends, schema migrations and larger operational complexity. It is not required merely to prove the repository boundary.

## 3. Schema

Tables:

- schema_meta
- firms
- clients
- tax_registrations
- cases
- case_documents
- case_events

SQLite foreign keys are enabled on every connection.

## 4. Relationship invariants

Python validates before case creation that:

- firm exists;
- client exists;
- client belongs to firm;
- optional tax registration exists;
- registration belongs to the case client.

Database foreign keys provide an additional structural boundary.

## 5. Update boundary

Case identity and ownership are immutable after creation:

- firm_id
- client_id
- registration_id
- proceeding_type
- notice_form
- opened_at

Operational fields may change:

- title
- status
- response_deadline
- assigned_to
- reviewer_id
- closed_at

A product service should pair meaningful updates with a CaseEvent. Phase 3D.2 keeps the repository primitive separate rather than silently fabricating audit actors/events.

## 6. Document metadata

`case_documents` stores only:

- IDs and case relation;
- document kind;
- original filename as display metadata;
- media type;
- byte size;
- SHA-256;
- opaque storage key;
- created timestamp.

The storage key is unique.

No binary payload column exists.

## 7. Event safety

Events are append-only through the public repository API; no update/delete event methods exist.

Event payloads:
- must be a small string-to-string metadata dictionary;
- have field/value size limits;
- reject obvious raw-content/secret keys such as `raw_text`, `source_text`, tokens, passwords, secrets and API keys.

This does not replace higher-level data-classification review, but it prevents common accidental leakage into the audit table.

## 8. Timestamps

Persisted datetimes must be timezone-aware. Naive datetimes are rejected.

The SQLite backend stores ISO-8601 text and reconstructs aware datetime objects.

## 9. Production boundary

This repository is not yet wired into the Streamlit UI.

Before real multi-firm production use, Dwaar still needs:
- authentication;
- firm/tenant authorization;
- production database deployment/encryption/backups;
- encrypted document storage;
- retention/deletion policy;
- protected audit access;
- migrations/operational observability.

## 10. Exit criteria

- hierarchy round-trips through disk;
- records survive repository recreation;
- foreign/ownership conflicts fail closed;
- case list is firm-scoped;
- immutable case identity cannot be rewritten;
- document refs contain no raw bytes;
- append-only events round-trip in deterministic order;
- sensitive audit payload fields are rejected;
- snapshots combine case/doc/event metadata;
- full regression suite passes.
