# Phase 3I — Client Workspace and Notice History

**Status:** Pilot client-centric case navigation  
**Date:** 22 September 2026  
**Depends on:** Phase 3H explicit client reuse

## 1. Purpose

Phase 3I makes client reuse visible and operationally useful.

A professional with CASE_READ can select one client and see:

- the client master record;
- all saved tax registrations for that client;
- all saved notice cases for that client;
- case status/proceeding/form/deadline metadata;
- a navigation action that focuses one historical case in the existing Saved cases workflow.

This phase is read-only.

## 2. Typed projection

Dwaar adds a framework-independent `ClientWorkspace` aggregate:

- `client: Client`
- `registrations: List[TaxRegistration]`
- `cases: List[CaseRecord]`

The projection contains structured metadata only.

It does not include:

- decrypted document bytes;
- raw notice text;
- analysis payloads;
- evidence quotes;
- reviewer notes;
- secrets.

## 3. Repository support

CaseRepository adds:

`list_cases_for_client(client_id)`

The SQLite implementation returns only cases linked to that client, ordered by:

1. opened_at descending;
2. case_id ascending.

No schema migration is required because `cases.client_id` already exists.

## 4. Authorized service boundary

`AuthorizedCaseService.get_client_workspace()` requires:

`CASE_READ`

Before building the projection, the service verifies the selected client belongs to the active firm.

Only then does it load:

- registrations for that client;
- cases for that client.

A client ID from another firm returns no workspace and cannot be used to enumerate registrations/cases.

## 5. UI behavior

The main workspace now renders:

1. Client workspace;
2. Saved cases;
3. New notice intake, when CASE_CREATE is present.

Inside Client workspace, the professional can select a client and view:

### Tax registrations

- registration ID;
- jurisdiction;
- identifier type;
- identifier value.

### Notice history

- case ID;
- title;
- status;
- notice form;
- proceeding type;
- opened timestamp;
- response deadline;
- linked registration ID.

## 6. Case focus instead of duplicate open logic

Phase 3I does not add a second document decryption/reanalysis implementation.

The user may choose a historical client case and click:

**Focus this case in Saved cases**

Dwaar stores only the focused case ID in Streamlit session state.

The existing Saved cases list then moves that case to the first position.

Opening/decrypting/reanalyzing still occurs exclusively through the existing:

**Open saved case**

path.

This preserves one security/integrity boundary for document access.

## 7. Permissions

The entire Client workspace requires CASE_READ.

A CASE_CREATE-only user does not receive client master/history data.

Read-only CASE_READ users can still use the client workspace even if they cannot:

- create cases;
- read documents;
- update cases.

If DOCUMENT_READ is absent, the existing Saved cases workflow still prevents opening encrypted notice documents.

## 8. No mutation side effects

Viewing Client workspace does not:

- modify client names;
- add/remove registrations;
- change case status;
- assign/reassign cases;
- save analysis snapshots;
- generate evidence candidates;
- confirm/reject evidence;
- alter deadlines;
- decrypt notices;
- rerun analysis.

It is a metadata projection plus navigation focus only.

## 9. Session focus

`_dwaar_focused_case_id` is navigation state only.

It is:

- cleared when the notice/firm workspace resets;
- not persisted to SQLite;
- not written to audit events;
- not treated as an assignment or professional decision.

## 10. Failure disclosure

Client-history failures render generic messages.

Internal SQLite/service details are not shown.

A stale/deleted selected client produces a controlled “no longer available” message.

## 11. Exit criteria

- ClientWorkspace typed projection exists;
- client-case query is deterministic and scoped;
- CASE_READ gates projection access;
- cross-firm client IDs fail closed;
- registrations and cases are composed under one client;
- read-only users can view client history;
- client history is shown before saved cases;
- a historical case can focus the existing Saved cases selector;
- only the pre-existing secure open/reanalysis path decrypts documents;
- client workspace has no mutation side effects;
- no schema migration is introduced;
- full regression suite passes.
