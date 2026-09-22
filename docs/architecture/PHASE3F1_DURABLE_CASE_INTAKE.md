# Phase 3F.1 — Durable New Case Intake

**Status:** Pilot case-intake backend  
**Date:** 22 September 2026  
**Depends on:** Phase 3D persistence, Phase 3E authorization/bootstrap

## 1. Purpose

Phase 3F.1 creates the first durable professional work object from a new GST notice.

A successful intake persists:

- new Client;
- optional GST TaxRegistration;
- CaseRecord;
- encrypted notice PDF;
- notice metadata;
- CASE_CREATED audit event;
- DOCUMENT_ADDED audit event.

The operation is available through AuthorizedCaseService and requires CASE_CREATE.

## 2. Case status

New durable cases are persisted as:

`CaseStatus.INTAKE`

even when an in-memory Phase-2 analysis has already been performed.

Reason: Dwaar does not yet persist a versioned analysis snapshot. Marking a case ANALYZED would imply that the analysis state is durably reconstructible without rerunning the notice.

Until Phase 3F.2 introduces an analysis snapshot contract, reopening an intake case may re-run analysis from the encrypted notice.

## 3. Database transaction

CaseRepository gains:

`create_case_intake(client, registration, case, document, events)`

The SQLite implementation commits in one transaction:

1. Client;
2. optional TaxRegistration;
3. CaseRecord;
4. notice StoredDocumentRef;
5. all intake CaseEvents.

Any relational failure rolls all five categories back.

## 4. Cross-store consistency

The encrypted notice is written before the SQLite intake transaction.

If SQLite fails, the encrypted object is deleted as compensating rollback.

If that deletion also fails, Dwaar raises a distinct `CaseIntakeConsistencyError` because an orphaned encrypted object may remain and needs operational remediation.

## 5. Client and registration

This first intake path creates a new Client.

Client IDs are opaque application-generated identifiers.

GSTIN is optional.

When supplied, it is normalized to uppercase and must match the standard structural GSTIN pattern. This is syntactic validation only; Phase 3F.1 does not claim portal verification, registration validity, legal status or checksum verification.

The TaxRegistration metadata uses:

- jurisdiction: IN-GST
- identifier_type: GSTIN

## 6. Case metadata

The intake CaseRecord stores:

- firm;
- new client;
- optional registration;
- case title;
- INTAKE status;
- proceeding type from the structured classifier;
- notice form;
- opened timestamp;
- deterministic response deadline when available.

No raw notice text or LLM response is stored in the CaseRecord.

## 7. Notice persistence

The uploaded notice must be:

- bytes;
- non-empty;
- PDF-signature prefixed;
- parseable by PyMuPDF;
- at least one page;
- not password protected.

Filename is display metadata only and must be a plain `.pdf` filename without path separators.

Binary bytes are persisted only through DocumentStore.

## 8. Audit content

CASE_CREATED records only controlled metadata:

- intake status;
- opaque client ID;
- proceeding type;
- notice form.

DOCUMENT_ADDED records:

- opaque document ID;
- document kind;
- byte size;
- SHA-256.

Audit events intentionally exclude:

- client display name;
- GSTIN;
- original filename;
- raw notice text;
- document bytes;
- LLM output.

## 9. Authorization

`AuthorizedCaseService.create_case_intake()` requires CASE_CREATE for the selected firm.

The actor ID supplied to the audit events comes from the authenticated principal.

The UI/caller cannot provide a different actor ID through the authorized service.

## 10. Current client-model limitation

Phase 3F.1 always creates a new Client.

A later client workspace should support selecting an existing client/registration to avoid duplicate client records for repeat matters.

This limitation should be resolved before broad multi-case production use.

## 11. Analysis persistence is intentionally deferred

The current analysis result contains rich structured facts, validation, evidence requirements and controlled draft data.

Persisting that result safely requires:

- a versioned schema;
- model/prompt/engine version metadata;
- provenance preservation;
- explicit migration/recompute rules;
- separation of source facts from derived outputs.

Phase 3F.1 does not serialize Python objects or arbitrary JSON blobs as a shortcut.

## 12. Exit criteria

- full new-client intake succeeds with optional GSTIN;
- case persists as INTAKE;
- notice bytes are encrypted;
- relational intake is one transaction;
- relational failure rolls back client/registration/case/doc/event rows;
- encrypted object is compensated on relational failure;
- invalid PDF/GSTIN fails before binary storage;
- authorized service requires CASE_CREATE;
- authenticated principal becomes audit actor;
- full regression suite passes.
