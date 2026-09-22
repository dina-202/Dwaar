# Phase 3E.3 — OIDC Runtime Identity and Secret Loading

**Status:** Authentication/runtime-security foundation  
**Date:** 22 September 2026  
**Depends on:** Phase 3E.1 authorization contracts, Phase 3E.2 persistent grants

## 1. Decision

Dwaar will use Streamlit's supported OpenID Connect authentication boundary rather than implement usernames/passwords.

Streamlit's current authentication API provides:

- `st.login()`;
- `st.user`;
- `st.logout()`.

OIDC proves identity. Dwaar's own firm-access grants remain the authorization source of truth.

## 2. Provider neutrality

The Dwaar domain does not import Streamlit and does not know Google, Microsoft, Okta, Auth0 or another provider.

`principal_from_streamlit_user()` is an adapter.

The underlying domain identity remains:

`AuthenticatedPrincipal(user_id=...)`

## 3. Stable internal identity

Dwaar must not authorize by email address.

Emails and display names can change.

The internal user ID is derived from the OIDC pair:

```text
issuer (iss) + subject (sub)
```

using SHA-256.

Result shape:

```text
OIDC-<64 lowercase hex chars>
```

The email/name claims are not part of the authorization identity.

## 4. Required claims

Dwaar requires:

- `iss`;
- `sub`;
- `exp`.

If `nbf` is present, it is enforced.

Malformed/missing claims fail closed.

## 5. Token time validity

Streamlit documents that identity-token issuance/expiration claims are available through user information but are not implicitly enforced for automatic session expiry.

Therefore Dwaar validates:

- `exp > current time`;
- optional `nbf <= current time`.

Expired/not-yet-valid identities do not produce an AuthenticatedPrincipal.

The Streamlit layer should log the user out or force a fresh login when this validation fails.

## 6. Document encryption key

The AES-256-GCM DocumentStore key must be supplied externally.

Dwaar's runtime helper accepts a base64 string and requires it to decode to exactly 32 bytes.

The key must not be:

- committed to Git;
- stored in SQLite;
- written into case events/logs;
- derived from a user password;
- generated afresh on every app restart.

Losing/rotating this key without a controlled migration can make stored documents unreadable.

## 7. Streamlit secrets

Streamlit supports local/project secrets through `.streamlit/secrets.toml` and deployment-specific secret management.

The repository already ignores:

`.streamlit/secrets.toml`

No real secret file or example containing live values is committed.

A production host may instead use environment variables or a dedicated secret manager/KMS.

## 8. Recommended secret names

The future app wiring should read values such as:

- OIDC settings from Streamlit's required `[auth]` configuration;
- `DWAAR_DOCUMENT_KEY_B64`;
- Dwaar database/object-store paths from non-secret configuration.

Exact deployment names may be adjusted later, but the document key should remain outside source control.

## 9. Security non-goals

This phase does not:

- implement password authentication;
- expose OIDC access tokens;
- use OIDC for authorization;
- create grants automatically for any logged-in user;
- grant access based on email domain;
- wire persistent storage into the Streamlit UI.

A successfully authenticated user with no active Dwaar firm grant must still receive no case access.

## 10. Exit criteria

- Streamlit user adapter exists without Streamlit dependency in domain code;
- issuer+subject produce stable opaque internal identity;
- email/name changes do not change authorization identity;
- issuer or subject changes do change identity;
- missing/malformed identity claims fail closed;
- expired identity fails closed;
- future `nbf` fails closed;
- document master key is strict external base64 -> 32 bytes;
- local secrets file remains gitignored;
- full regression suite passes.
