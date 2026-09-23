# Phase 3P.6 — Live Encrypted Storage Consistency Audit

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.5 document key identity and rotation readiness

## Goal

Prove that the live SQLite metadata reference set and the encrypted object directory agree before backup, recovery, or any future key rotation.

The audit is intentionally independent of case/legal logic.

## Dynamic storage inventory

Dwaar no longer relies on a hard-coded list of persistence tables for encrypted-object discovery.

The inventory inspects the live SQLite schema and discovers every user table that contains an exact `storage_key` column.

This inventory is shared by:

- live storage audit;
- runtime backup reference capture.

Therefore a future persistence table with a `storage_key` column becomes part of backup coverage automatically.

## Closed consistency dimensions

The sanitized report contains counts only:

- storage tables discovered;
- referenced encrypted objects;
- canonical encrypted object files;
- missing referenced objects;
- orphan object files;
- invalid database storage references;
- invalid object-directory entries;
- encrypted-object authentication failures.

The report never returns:

- storage keys;
- filenames;
- filesystem paths;
- decrypted payloads;
- client/case identifiers;
- exception text.

## Missing object

A database storage reference whose canonical encrypted object file is absent is inconsistent.

This blocks operator health.

## Orphan object

A canonical encrypted object file that is not referenced by the current database is inconsistent.

Even though an orphan is not part of the active case graph, it can represent:

- failed rollback residue;
- incomplete deletion;
- unexpected storage drift;
- unnecessary encrypted-data retention.

It therefore blocks rotation-ready health until reviewed.

## Invalid database reference

Malformed or duplicate storage references make the reference set untrustworthy.

When the reference set is invalid, Dwaar deliberately does **not** infer missing/orphan classifications from it.

The audit reports the invalid-reference condition instead.

## Invalid object entry

Files/directories that do not match the canonical Dwaar encrypted-object shape are reported as invalid entries.

Canonical file shape:

`<32 lowercase hex>.dwaar`

This includes stale temporary or unexpected files that should not be treated as committed objects.

## Authentication

Every referenced object that exists is authenticated through the normal `EncryptedLocalDocumentStore` using the configured document master key.

The audit may decrypt payloads transiently in memory for AES-GCM authentication, but it never writes decrypted professional data or includes it in output.

A wrong key therefore produces authentication failures even when filenames and database references look correct.

## Backup integration

Phase 3P.2 backup reference discovery now consumes the same dynamic inventory.

This closes a production risk where a newly introduced persistence table could otherwise be omitted from backups because a hard-coded storage-table tuple was not updated.

Backup creation still fails closed on malformed/duplicate references.

## Operator health

Phase 3P.4 gains:

`live_storage_consistency`

Healthy operator posture now requires:

1. runtime preflight;
2. live storage consistency;
3. backup verification;
4. backup key identity;
5. backup freshness.

The live audit and backup verification are intentionally separate.

A valid historical backup does not hide current live storage drift.

## Operator command

Run:

`python scripts/runtime_storage_audit.py`

Required environment:

- `DWAAR_DB_PATH`
- `DWAAR_OBJECT_ROOT`
- `DWAAR_DOCUMENT_KEY_B64`

Exit codes:

- `0` — live storage consistent;
- `1` — audit completed but inconsistencies exist, or audit failed;
- `2` — required configuration is missing/invalid.

Output is one sanitized JSON object containing counts only.

## Key-rotation prerequisite

Any future document-key rotation must require a clean storage audit before re-encryption begins.

Otherwise a rotation could:

- omit a referenced object;
- preserve an orphan accidentally;
- re-encrypt under an incomplete reference set;
- mask existing corruption as a rotation failure.

## Scope boundary

Phase 3P.6 does not:

- delete orphan files;
- repair missing objects;
- mutate database references;
- re-encrypt objects;
- rotate keys;
- expose object identities in operator output.

Repair/remediation remains an explicit operator action.

## Safety invariant

> Dwaar must know exactly which encrypted objects are live and authentic before it can claim backup completeness, recovery readiness, or safe key rotation.
