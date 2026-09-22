# Phase 3E.4 — Streamlit OIDC and Firm Access Gate

**Status:** Pilot UI security boundary  
**Date:** 22 September 2026  
**Depends on:** Phase 3E.1–3E.3

## 1. Purpose

The existing Streamlit notice analyzer must not run for arbitrary visitors once Dwaar has persistent case/document infrastructure.

Phase 3E.4 gates the analyzer behind:

1. Streamlit OIDC authentication;
2. Dwaar persisted firm access;
3. the explicit CASE_CREATE permission.

The analyzer still operates as a temporary analysis workspace in this phase; durable case creation is not yet connected to the UI.

## 2. Login boundary

If `st.user.is_logged_in` is false:

- Dwaar shows a sign-in screen;
- the sign-in button invokes `st.login()`;
- no PDF uploader is rendered;
- no PDF parsing, LLM analysis or firm database lookup is performed.

If the Streamlit deployment does not expose the required authentication API, Dwaar fails closed.

## 3. Identity validation

For a logged-in Streamlit user, Dwaar calls the Phase 3E.3 adapter.

It requires:

- OIDC issuer;
- OIDC subject;
- non-expired identity token;
- valid optional not-before timestamp.

Expired/invalid identity does not reach the analyzer or firm lookup.

## 4. Firm provisioning

Authentication alone grants no Dwaar access.

The application resolves `DWAAR_DB_PATH`, loads persisted grants for the authenticated principal, and exposes only active firms where the grant explicitly includes:

`CASE_CREATE`

An authenticated user with no qualifying firm receives no analyzer access.

No email-domain auto-provisioning or implicit first-user admin exists.

## 5. Multi-firm users

If the principal has one eligible firm, it becomes the active firm directly.

If multiple eligible firms exist, Dwaar presents a firm selector.

Firm identity is displayed as:

`Display Name (firm_id)`

The firm ID remains the authoritative tenant identifier.

## 6. Session isolation

The existing Phase-2/evidence workspace uses Streamlit session state for temporary responsiveness.

When active firm changes, Dwaar clears:

- cached notice-analysis key/result/pages/raw text;
- evidence-workspace key/result;
- evidence review records.

This prevents in-memory work from Firm A appearing after switching to Firm B.

Logout also clears those workspace values and the active firm ID before calling `st.logout()`.

## 7. Analyzer authorization meaning

The current screen is a new-notice intake/analyzer flow.

Therefore access requires `CASE_CREATE`, not merely `CASE_READ`.

This does not yet persist a case automatically. It means the user is authorized to initiate new case intake in that firm.

A future case-list/open screen should use `CASE_READ`.

## 8. Runtime database configuration

Pilot firm access discovery reads:

`DWAAR_DB_PATH`

from the process environment.

The database path is not accepted from browser input, URL parameters or OIDC claims.

Missing configuration fails closed before analyzer access.

## 9. Streamlit version floor

Dwaar now requires:

`streamlit>=1.64,<2`

so the supported OIDC user API used by this gate is an explicit dependency rather than an accidental deployment assumption.

## 10. Error disclosure

Authentication/access configuration failures show generic operational messages.

Underlying database paths, repository exceptions, provider details and private infrastructure errors are not rendered to end users.

## 11. Remaining deployment requirements

Before a real CA pilot can use this gate, deployment still needs:

- valid Streamlit OIDC `[auth]` configuration;
- a persistent `DWAAR_DB_PATH`;
- initial Firm + access-grant provisioning;
- a stable externally supplied document encryption key before durable document UI activation.

## 12. Exit criteria

- logged-out visitor cannot reach uploader/LLM;
- login button invokes Streamlit OIDC;
- expired identity fails before firm lookup;
- authenticated but unprovisioned user cannot reach analyzer;
- CASE_CREATE is the exact required permission;
- multi-firm selection is supported;
- switching firms purges temporary analysis/evidence state;
- logout purges temporary state;
- config/consistency errors do not leak internals;
- full regression suite passes.
