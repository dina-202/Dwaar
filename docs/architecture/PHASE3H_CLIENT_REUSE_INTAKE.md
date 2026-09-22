# Phase 3H — Explicit Client Reuse During Intake

**Status:** Pilot client continuity workflow  
**Date:** 22 September 2026  
**Depends on:** Phase 3F durable cases/authentication

## 1. Purpose

Phase 3H prevents a CA firm from creating a new client record every time an existing taxpayer receives another notice.

A professional may now explicitly choose:

- **New client** — current intake behavior; or
- **Existing client** — reuse a previously saved client and optionally one of that client's tax registrations.

The default remains **New client**.

Dwaar does not silently merge or reuse clients based on similar names, extracted notice text, or GSTIN.

## 2. Why reuse is explicit

Client identity is professional master data.

Automatic linking can corrupt history when:

- client names are similar;
- trade/legal names differ;
- a notice contains an incorrect identifier;
- registrations change;
- one firm manages related entities with similar names.

Therefore AI/extraction may assist future search, but it must not silently decide client identity.

The professional selects the existing client.

## 3. Repository contract

CaseRepository now supports:

- `list_clients(firm_id)`;
- `list_registrations(client_id)`;
- `create_existing_client_case_intake(case, document, events)`.

The existing-client intake transaction creates only:

- the new CaseRecord;
- the new encrypted notice metadata;
- CASE_CREATED event;
- DOCUMENT_ADDED event.

It does not insert a new Client or TaxRegistration.

## 4. Tenant boundaries

Client discovery is firm-scoped.

`list_clients(firm_id)` returns only clients for the selected firm.

Registration discovery is client-scoped.

The authorized service rechecks:

- the client exists;
- the client belongs to the active firm;
- a selected registration exists;
- the selected registration belongs to that client.

UI values are not trusted as authorization.

## 5. Permissions

Browsing reusable clients/registrations requires:

`CASE_READ`

Creating either a new-client or existing-client intake requires:

`CASE_CREATE`

A create-only principal can still create a new client/case, but does not receive existing-client browsing data.

## 6. Existing-client intake validation order

Before encrypted notice bytes are written, Dwaar verifies:

1. firm ID is valid;
2. selected firm exists;
3. selected client exists in that firm;
4. selected registration, if any, belongs to that client;
5. proceeding type and notice form are typed values;
6. response deadline type is valid;
7. actor identity is present;
8. opened_at is timezone-aware;
9. case title and filename are valid;
10. notice payload is a readable PDF.

Cross-firm or wrong-registration selection therefore fails before object storage.

## 7. Encryption and rollback

Notice bytes continue to use the existing AES-256-GCM DocumentStore.

For existing-client intake:

1. encrypted notice is written;
2. SQLite atomically writes case + document metadata + events;
3. if SQLite fails, encrypted notice is deleted as compensating rollback;
4. rollback failure raises the existing distinct consistency error.

## 8. Audit behavior

CASE_CREATED records the selected client ID but not the client display name or GSTIN.

DOCUMENT_ADDED records controlled notice metadata and SHA-256.

Client names and GST registration values are not copied into event payloads.

## 9. Intake UI

When CASE_READ is available, Dwaar loads the active firm's clients.

If at least one exists, the professional sees:

**Client handling**

with:

- New client;
- Existing client.

### New client

The current fields remain:

- Client name;
- optional GSTIN;
- Case title.

### Existing client

The professional explicitly selects:

- an existing client;
- one of that client's registrations, or **No registration**;
- Case title.

The UI displays the selected opaque client/registration IDs before save.

## 10. No automatic matching

Phase 3H deliberately does not:

- infer the client from notice text;
- auto-select by GSTIN;
- merge clients with similar names;
- merge duplicate registrations;
- modify an existing client's name;
- create a new registration under an existing client.

Those actions require separate master-data contracts and explicit professional control.

## 11. Stable ordering

Client lists use deterministic ordering by:

1. display name, case-insensitive;
2. creation time;
3. client ID.

Registration lists use deterministic ordering by:

1. identifier type;
2. identifier value;
3. creation time;
4. registration ID.

This keeps Streamlit selection behavior stable across reruns.

## 12. Failure disclosure

Configuration/internal persistence failures remain generic in the UI.

A stale client or registration selection produces a controlled message that the selected record is no longer available.

Internal database/object-store details are not rendered.

## 13. Exit criteria

- firm-scoped client discovery exists;
- client-scoped registration discovery exists;
- CASE_READ gates browsing;
- CASE_CREATE gates intake;
- new-client path remains default;
- existing-client reuse is always explicit;
- second notice can reuse client/registration without duplicate master records;
- no-registration reuse is supported;
- cross-firm client selection fails before encrypted write;
- wrong-client registration fails before encrypted write;
- case/notice/events persist atomically;
- encrypted object rolls back on metadata failure;
- no silent name/GSTIN merging exists;
- full regression suite passes.
