# Phase 3P.1 — Runtime Readiness Preflight

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3O professional workbench

## Goal

Fail before serving professional traffic when Dwaar's local production runtime is not actually usable.

The preflight validates the pilot runtime boundary without exposing sensitive configuration values.

## Checks

The closed preflight emits exactly these checks:

1. database configuration;
2. object-store configuration;
3. document encryption-key configuration;
4. database open/schema initialization;
5. SQLite integrity;
6. encrypted object-store round trip.

A report is ready only when every check passes.

## Database probe

The database probe constructs the supported SQLite repository.

That intentionally exercises:

- file accessibility;
- schema creation for a fresh deployment;
- supported idempotent migration from known historical schema versions;
- refusal of unsupported schema versions.

After initialization, the preflight runs SQLite `PRAGMA quick_check` and verifies that Dwaar's schema metadata exists.

A configured database path whose parent directory cannot be opened fails closed.

## Encrypted object-store probe

The object-store probe:

1. creates the encrypted local store with the externally supplied AES-256 key;
2. generates one opaque temporary storage key;
3. writes a fixed non-user probe payload;
4. reads and authenticates it;
5. verifies the plaintext round trip;
6. deletes the probe object.

A failed cleanup makes the check fail.

The preflight never uses notice, evidence, draft, filing, or client data for this probe.

## Sanitization

Readiness output contains only:

- stable check code;
- `pass` or `blocked`;
- fixed operator-safe message.

It does not include:

- database path;
- object-store path;
- encryption key;
- key hash/fingerprint;
- underlying exception text;
- SQL error details;
- document contents.

This is intentional so the command can be used in deployment logs without turning logs into a secret/configuration inventory.

## Operator command

Run:

`python scripts/runtime_preflight.py`

The command prints one JSON object.

Exit code:

- `0` — runtime ready;
- `1` — one or more checks blocked.

The process should be used before starting the Streamlit application in production-like deployments.

## Scope boundary

3P.1 validates the current single-node runtime.

It does not claim that SQLite/local object storage is horizontally scalable or highly available.

Later 3P work should address:

- backup/recovery;
- deployment topology and portability;
- observability;
- secret rotation procedures;
- migration/rollback operations;
- production storage adapters where required.

## Safety invariant

> A deployment should prove that its configured persistence and encryption boundary works before a professional user relies on it.
