# Phase 3E.1 — Firm-Scoped Authorization Boundary

**Status:** Architecture amendment  
**Date:** 22 September 2026

## 1. Purpose

Dwaar now has durable case/document persistence. Before any persistent data is exposed through the UI, every case/document operation needs an explicit tenant authorization boundary.

Phase 3E.1 introduces provider-neutral identity and firm-scoped permission contracts.

It does not implement login.

## 2. Authentication versus authorization

Authentication answers:

> Who is this user?

Authorization answers:

> What may this authenticated user do inside this firm/case?

Dwaar keeps these concerns separate.

An external authentication provider may later produce an `AuthenticatedPrincipal`.

Dwaar authorization consumes that principal plus a trusted `FirmAccessGrant`.

## 3. Principal

`AuthenticatedPrincipal` contains only:

- user_id

The domain does not depend on Google, Microsoft, password auth, magic links, Streamlit auth, JWT claims or any other provider-specific structure.

## 4. FirmAccessGrant

A grant contains:

- user_id;
- firm_id;
- explicit permission set;
- active flag.

The grant is firm-scoped. A grant for Firm A cannot authorize a CaseRecord owned by Firm B.

## 5. Explicit permission vocabulary

Initial permissions:

- CASE_READ
- CASE_CREATE
- CASE_UPDATE
- DOCUMENT_READ
- DOCUMENT_ADD
- EVIDENCE_REVIEW
- DRAFT_REVIEW
- FILING_RECORD
- FIRM_ADMIN

No role hierarchy is inferred in this phase.

In particular, FIRM_ADMIN does not automatically imply CASE_READ or any other permission unless the grant explicitly contains it.

A future product role such as Owner/Partner/CA/Staff may simply expand into a set of explicit permissions at provisioning time.

## 6. Fail-closed rules

Authorization fails when:

- grant is inactive;
- grant user does not equal authenticated principal;
- grant firm differs from requested firm;
- case belongs to another firm;
- required permission is absent;
- permission type is outside the closed enum.

No fallback, implicit tenant selection or cross-firm access exists.

## 7. Case authorization

`require_case_permission()` first proves:

```text
principal.user_id == grant.user_id
grant.active == true
grant.firm_id == case.firm_id
required_permission in grant.permissions
```

Only then does execution continue.

## 8. Security boundary

FirmAccessGrant must ultimately come from trusted persistent authorization state.

It must not be constructed directly from:

- user-submitted firm IDs;
- query parameters;
- uploaded documents;
- LLM output;
- arbitrary session-state values.

The authentication/provider layer must never trust a client-supplied permission list.

## 9. Next unit

Phase 3E.2 should add persistent user/firm grants and authorized application services that wrap:

- case reads/lists;
- case creation/update;
- document retrieval/addition;
- evidence review;
- draft review;
- filing record actions.

Only after those authorized services exist should persistent case functionality be connected to Streamlit.

## 10. Exit criteria

- provider-neutral principal contract exists;
- firm access grants are explicit and immutable;
- permission vocabulary is closed;
- inactive/wrong-user/wrong-firm/missing-permission checks fail closed;
- case access proves tenant equality;
- FIRM_ADMIN has no hidden permission expansion;
- no authentication provider dependency enters domain code;
- full regression suite passes.
