# Phase 3F.2 — Save-as-Intake Streamlit Workflow

**Status:** Pilot UI activation  
**Date:** 22 September 2026  
**Depends on:** Phase 3F.1 durable case intake

## 1. Purpose

Phase 3F.2 exposes the Phase 3F.1 durable intake path in the authenticated Streamlit analyzer.

The workflow is intentionally explicit:

1. upload notice;
2. run structured analysis;
3. review output;
4. enter intake metadata;
5. click **Save as intake**.

Analysis does not automatically create a durable case.

## 2. Saved data

A successful save persists:

- new Client;
- optional structurally valid GSTIN registration;
- CaseRecord with status INTAKE;
- classified proceeding type;
- classified notice form;
- deterministic response deadline when available;
- encrypted original notice PDF;
- CASE_CREATED and DOCUMENT_ADDED audit events.

The authenticated principal is the audit actor.

## 3. Not saved yet

The current Phase-2 analysis result is not persisted in Phase 3F.2.

That includes:

- extracted fact objects;
- validation results;
- arithmetic results;
- evidence candidate/review session state;
- specialist draft;
- raw extracted notice text cache.

The UI states that analysis will be recomputed when the case is reopened until a versioned encrypted analysis-snapshot contract exists.

## 4. Runtime persistence configuration

Saving requires all three server-side values:

- DWAAR_DB_PATH
- DWAAR_OBJECT_ROOT
- DWAAR_DOCUMENT_KEY_B64

The runtime factory constructs:

- LocalSQLiteCaseRepository;
- LocalSQLiteAccessGrantRepository;
- EncryptedLocalDocumentStore;
- AuthorizedCaseService.

The UI does not construct keys or repositories directly.

Missing/invalid persistence configuration produces a generic user-facing error and does not expose secret/path details.

## 5. Intake fields

The professional supplies:

- Client name;
- optional GSTIN;
- Case title.

Case title defaults from structured classification:

`<human-readable notice form> — <proceeding type>`

For example:

`DRC-01 — gst_sec73_itc`

The title is editable before save.

## 6. Structured values are authoritative

The save action does not ask the user to retype or choose:

- proceeding type;
- notice form;
- computed response deadline.

Those values are taken directly from the current structured analysis result.

This reduces accidental divergence between displayed analysis and persisted case metadata.

## 7. Duplicate-save suppression

Streamlit reruns can repeatedly execute UI code.

The session therefore records a successful saved case using a key bound to:

- active firm ID;
- SHA-256-based exact notice analysis key.

For the same notice+firm in the current session:

- the Save button is replaced by the saved case ID/status;
- persistence is not called again.

This is a UI duplicate guard, not a database-wide deduplication rule.

A future durable idempotency key can provide stronger cross-session protection.

## 8. Tenant/session isolation

The successful-save session map is cleared when:

- active firm changes;
- user logs out.

It is therefore not carried across tenant switches.

## 9. Evidence boundary

The supporting-evidence workspace remains session-only in this phase.

Saving the intake case persists only the original notice.

Evidence PDFs and review records require their own durable, authorized workflow before they may be attached to the case.

## 10. Error behavior

- invalid user-entered intake fields may show the controlled validation message;
- authorization loss shows a generic permission message;
- runtime persistence misconfiguration shows a generic configuration message;
- unexpected persistence failures show a generic save failure.

Internal key/database/object-store details are not rendered.

## 11. Exit criteria

- ordinary analysis does not persist automatically;
- Save as intake requires an explicit click;
- client/GSTIN/title flow into authorized intake service;
- proceeding/form/deadline come from structured analysis;
- encrypted persistence factory is created only on save;
- successful save records case ID in session;
- same notice+firm rerun does not duplicate-save;
- firm switch/logout clears saved-case session marker;
- missing persistence config does not leak internals;
- full regression suite passes.
