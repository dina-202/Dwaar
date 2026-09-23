# Phase 3P.5 — Document Key Identity and Rotation Readiness

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.4 operator health and backup posture

## Goal

Give Dwaar an explicit non-secret identity for each document-master-key generation so operators can reason about backups and future rotations without exposing or fingerprinting the key material itself.

This phase does **not** rotate or re-encrypt live data.

It establishes the identity and compatibility contracts required before a safe rotation mechanism can exist.

## Runtime configuration

Production-like runtime configuration now includes:

- `DWAAR_DOCUMENT_KEY_B64` — secret 32-byte AES-256 master key;
- `DWAAR_DOCUMENT_KEY_ID` — non-secret opaque generation identifier.

Key IDs use the closed format:

`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`

Example:

`doc-key-2026-a`

The key ID must not contain:

- key bytes;
- hashes/fingerprints of the key;
- passwords;
- client names;
- case identifiers;
- other secrets.

## Trust rule

The key ID is operational metadata only.

Cryptographic authentication still depends exclusively on the real 32-byte key.

Therefore:

- matching key IDs do not prove matching key material;
- mismatching key IDs block rotation-ready operator health;
- a wrong key with a correct ID still fails AES-GCM authentication;
- a correct key with the wrong ID can decrypt legacy data but is considered operationally misconfigured.

## Runtime preflight

Phase 3P.1 gains a seventh check:

`document_key_id_configuration`

The production preflight is blocked when the key ID is missing or malformed.

The check output does not print the ID.

## Backup manifest v2

The current backup write schema becomes manifest v2.

v2 adds:

`document_key_id`

The ID is also included in the encrypted database associated data (AAD), so changing a v2 manifest's key ID invalidates database authentication.

The v2 AAD binds:

- backup cryptographic context;
- manifest generation;
- backup ID;
- document key ID.

## Backward compatibility

Manifest v1 remains supported.

A v1 backup:

- has no document key ID;
- remains cryptographically verifiable with the original key;
- remains clean-target recoverable;
- cannot satisfy an expected key-identity check;
- is not considered rotation-ready by operator health.

No existing v1 backup must be rewritten merely to add metadata.

## Library compatibility

The low-level backup API remains backward-compatible:

- callers that omit `document_key_id` create v1 backups;
- callers that supply a valid `document_key_id` create v2 backups.

This keeps existing integrations and historical tests valid while allowing production operator tooling to move to v2.

## Operator backup CLI

New backups created by:

`python scripts/runtime_backup.py create`

require:

- `DWAAR_DOCUMENT_KEY_B64`;
- `DWAAR_DOCUMENT_KEY_ID`.

The CLI creates v2 manifests.

Normal v2 verify/restore operations require the configured key ID to match the backup.

Legacy v1 verify/restore requires the explicit flag:

`--allow-legacy-key-id`

This prevents a v1 backup from silently being treated as if it had modern rotation metadata.

## Operator health

Phase 3P.4 gains:

`backup_key_identity`

Healthy production posture now requires:

1. runtime preflight passes;
2. backup cryptographic verification passes;
3. backup key identity matches the configured runtime key ID;
4. backup freshness passes the explicit age policy.

A cryptographically valid v1 backup therefore remains recoverable but blocks rotation-ready health.

## Why key fingerprinting is intentionally absent

Dwaar does not publish or log a hash/fingerprint of the document master key.

A key ID is chosen independently of key material and is safe to record in operational metadata.

This avoids turning logs/manifests into a long-lived key-correlation surface.

## Rotation boundary

Phase 3P.5 does **not**:

- decrypt/re-encrypt all live objects;
- change the live master key;
- rewrite historical backups;
- delete old key generations;
- automate key retirement;
- decide how long old keys must be retained.

A future rotation phase must account for:

- all live encrypted objects;
- encrypted database backups;
- historical backup recovery;
- atomic switchover;
- rollback on partial failure;
- old-key retention until every required backup expires or is migrated.

## Safety invariants

> Key identity is bookkeeping, not cryptographic proof.

> Historical v1 backups remain recoverable, but missing identity metadata must not be mistaken for rotation readiness.

> A future key rotation must never make historical professional work product unrecoverable by accident.
