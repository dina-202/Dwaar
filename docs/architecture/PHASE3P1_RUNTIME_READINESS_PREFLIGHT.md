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
4. document key identity configuration;
5. scanned-PDF OCR runtime;
6. AI analysis configuration;
7. database open/schema initialization;
8. SQLite integrity;
9. encrypted object-store round trip.

A report is ready only when every check passes.

## OCR runtime probe

The preflight creates a tiny in-memory PDF page containing fixed probe text and
executes the same PyMuPDF/Tesseract OCR path used for scanned notice pages.

The probe:

- uses no taxpayer or uploaded document data;
- requires English OCR support because Dwaar's current scanned-notice path uses
  the `eng` language pack;
- emits only a fixed pass/blocked message;
- discards underlying OCR/Tesseract exception details.

A deployment with a working database and encrypted object store is still not
ready for professional traffic when the scanned-PDF OCR runtime cannot execute.

## AI analysis configuration probe

The preflight reuses the analysis client's own credential/router boundary and
checks only that:

- at least one analysis credential slot was configured at application startup;
- the configured model name is non-empty.

This check makes no provider API call, consumes no model quota and never emits:

- credential values;
- credential variable names;
- configured-key counts;
- provider exception text.

It is deliberately a configuration check, not a guarantee of external provider
uptime, quota or credential validity. Runtime provider failures remain handled
by the existing categorized router/failover path.

A pilot runtime with healthy storage and OCR but no configured analysis
credential is not ready for professional traffic.

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
