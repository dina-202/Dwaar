# Phase 3E.2 — Persistent Access Grants and Authorized Case Services

**Status:** Pilot authorization infrastructure  
**Date:** 22 September 2026  
**Depends on:** Phase 3E.1 firm authorization boundary

## 1. Purpose

Phase 3E.2 makes firm authorization operational around persistent case/document access.

It adds:

- a persistent AccessGrantRepository port;
- a SQLite access-grant implementation;
- an AuthorizedCaseService application boundary.

The Streamlit UI is still not wired to persistence.

## 2. Persistent grant model

A persisted grant is identified by:

```text
(user_id, firm_id)
```

and stores:

- explicit permission set;
- active flag.

Permissions are serialized as a deterministic sorted JSON list.

Unknown or malformed persisted permissions fail closed on read.

## 3. Firm foreign key

SQLite access grants reference the existing `firms` table.

A grant cannot be persisted for a non-existent firm.

This prevents authorization state from referring to a tenant that does not exist in the case database.

## 4. Grant replacement

`save_grant()` replaces the permission set and active state for the same user/firm pair.

There is no additive merge of stale permissions.

Revocation can therefore be represented by:

- saving an inactive grant; or
- replacing the grant with a reduced explicit permission set.

A later administrative service should control who may perform that change.

## 5. Authorized application service

The UI and future APIs should call `AuthorizedCaseService`, not the raw repositories.

Current protected operations:

- list cases;
- get case;
- create case;
- update case;
- add PDF document;
- read document.

Each method resolves the caller's persisted firm grant and requires the exact permission.

## 6. Cross-tenant behavior

A caller authorized for Firm A cannot operate on a CaseRecord owned by Firm B.

For case/document lookup operations, a cross-firm case ID is treated as unavailable rather than returned to the caller.

This avoids using a known case ID as a bypass around firm scoping.

## 7. Document add

Adding a document requires `DOCUMENT_ADD`.

The authorized service:

1. proves the caller's firm grant;
2. proves the case belongs to that firm;
3. calls the Phase 3D.4 persistence service;
4. uses the authenticated principal's user ID as the audit actor.

The caller cannot supply a different audit actor through this service.

## 8. Document read

Reading a document requires `DOCUMENT_READ`.

The service proves:

- caller grant;
- case tenant;
- document belongs to that case.

After AES-GCM decryption it also compares the plaintext to relational metadata:

- exact byte size;
- SHA-256.

A mismatch raises `StoredDocumentConsistencyError`.

This catches metadata/object divergence even if either store remains individually readable.

## 9. Raw repositories

CaseRepository, AccessGrantRepository and DocumentStore remain infrastructure ports.

They are not authorization boundaries by themselves.

Application/UI code must not expose raw repository methods directly to authenticated users.

## 10. Authentication still deferred

Phase 3E.2 does not implement login or identity proof.

An authentication provider is still required to create a trustworthy `AuthenticatedPrincipal`.

The user ID must come from authenticated server-side state, not a text field or query parameter.

## 11. Administrative boundary

This phase does not expose grant administration to end users.

A later firm-administration service must require an appropriate administrative permission before:

- inviting users;
- creating grants;
- changing permissions;
- deactivating access.

## 12. Exit criteria

- access grants persist across process/repository recreation;
- grants are firm foreign-key constrained;
- unknown permission values fail closed;
- case lists are firm scoped;
- cross-firm case access is unavailable;
- document add requires DOCUMENT_ADD;
- document read requires DOCUMENT_READ;
- audit actor comes from authenticated principal;
- decrypted document bytes are rechecked against metadata SHA/size;
- full regression suite passes.
