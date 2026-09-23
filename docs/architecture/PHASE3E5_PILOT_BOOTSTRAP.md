# Phase 3E.5 — One-Time Pilot Firm Bootstrap

**Status:** Local pilot administration  
**Date:** 22 September 2026  
**Depends on:** Phase 3E.2 persistent grants, Phase 3E.4 Streamlit firm gate

## 1. Purpose

OIDC authentication and firm authorization create a deliberate first-tenant problem:

- a newly authenticated user has an internal OIDC account ID;
- no Firm exists yet;
- no FirmAccessGrant exists yet;
- the application correctly denies access.

Phase 3E.5 provides a one-time local administrative bootstrap for that first firm.

## 2. Bootstrap rule

The command is allowed only while the database contains no firm.

Once any firm exists, bootstrap refuses to run.

This prevents the bootstrap command from becoming a reusable mechanism for adding privileged firms/users after the product is initialized.

Later user/firm administration must go through an authenticated FIRM_ADMIN workflow.

## 3. Input

Bootstrap requires:

- SQLite database path;
- professional firm display name;
- opaque Dwaar OIDC user ID shown by the signed-in/unprovisioned screen.

The OIDC user ID must match:

`OIDC-<64 hex chars>`

It does not accept email address as authorization identity.

## 4. Initial permissions

The first user receives every permission in the current closed `AccessPermission` enum explicitly:

- CASE_READ
- CASE_CREATE
- CASE_UPDATE
- DOCUMENT_READ
- DOCUMENT_ADD
- EVIDENCE_REVIEW
- FACT_REVIEW
- DRAFT_REVIEW
- FILING_RECORD
- FIRM_ADMIN

This is not implicit role inheritance. The persisted grant contains the explicit permission set.

## 5. Firm identity

The created firm uses an opaque application-generated ID:

`FIRM-<32 lowercase hex chars>`

Firm name is display metadata only.

## 6. Transactional bootstrap

Firm creation and initial access grant are committed in one SQLite transaction.

If grant insertion fails, the firm insertion rolls back.

After commit, bootstrap reads both records back through Dwaar's public repository implementations and verifies they exactly match the intended records.

## 7. CLI

Run from the repository root:

```bash
python -m scripts.bootstrap_pilot \
  --firm-name "Example CA Firm" \
  --user-id "OIDC-<account-id-shown-by-Dwaar>"
```

The database path defaults to:

`DWAAR_DB_PATH`

or may be passed explicitly with `--db-path`.

The command prints only:

- created firm ID/name;
- opaque user ID;
- granted permission names.

It does not print tokens, OIDC claims, encryption keys or document contents.

## 8. Operational sequence

For a new pilot deployment:

1. configure Streamlit OIDC;
2. configure persistent `DWAAR_DB_PATH`;
3. user signs in once;
4. Dwaar shows the opaque Account ID because no firm grant exists;
5. administrator runs the bootstrap command locally/server-side;
6. user refreshes/signs in and now receives the provisioned firm;
7. the analyzer is available because the initial grant contains CASE_CREATE.

## 9. Security boundary

The bootstrap command must be treated as server/local administrative tooling.

Do not expose it:

- as a public HTTP route;
- as a Streamlit text field;
- through an LLM tool;
- through user-uploaded configuration.

Filesystem/database access to the command environment is itself privileged administration.

## 10. Non-goals

This phase does not implement:

- invitations;
- adding a second user;
- adding a second firm;
- permission editing;
- revocation UI;
- admin audit events;
- SSO group synchronization.

Those belong to a later FIRM_ADMIN service.

## 11. Exit criteria

- valid first bootstrap creates firm + grant;
- initial permission set is explicit and complete;
- second bootstrap refuses once any firm exists;
- invalid OIDC IDs fail before database creation;
- firm + grant write is transactional;
- failed grant insertion leaves no firm behind;
- persisted records verify through normal repositories;
- full regression suite passes.
