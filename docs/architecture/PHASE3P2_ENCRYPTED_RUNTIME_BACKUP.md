# Phase 3P.2 — Encrypted Runtime Backup Integrity

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.1 runtime readiness preflight

## Goal

Create a consistent, verifiable backup of Dwaar's current single-node runtime without publishing professional metadata or document content in plaintext.

The runtime consists of:

- SQLite structured metadata;
- AES-GCM encrypted object files.

Both layers are protected in the published backup.

## Backup order

The backup process is intentionally ordered:

1. open the live SQLite database read-only;
2. verify SQLite integrity and foreign keys;
3. create an online SQLite snapshot using the SQLite backup API;
4. derive the exact encrypted object keys referenced by that snapshot;
5. encrypt the SQLite snapshot;
6. copy only the referenced encrypted object files;
7. hash the encrypted database and every encrypted object;
8. write a sanitized manifest;
9. verify the complete temporary backup;
10. atomically rename the temporary directory into its final backup ID.

A failed step removes the unpublished temporary directory.

## Why database first

Committed Dwaar binary objects are immutable and are persisted before their metadata row is committed.

Taking the SQLite snapshot first therefore gives a stable reference set.

Objects copied afterward may coexist with newer live objects, but the backup copies only the keys referenced by the captured database snapshot.

The verifier rejects:

- missing referenced objects;
- extra object files in the backup;
- duplicate storage keys;
- malformed storage keys;
- unsupported schema versions;
- SQLite corruption;
- foreign-key corruption;
- hash/size mismatches.

## Database encryption

The published database file is:

`dwaar.sqlite3.enc`

The plaintext SQLite snapshot exists only as a temporary local file while the backup is being assembled and is deleted before publication.

The encrypted database uses AES-256-GCM with a backup-specific key derived from the existing Dwaar document master key through HKDF-SHA256.

Derivation context:

`DWAAR-RUNTIME-BACKUP-DB-V1`

This separates backup-database cryptographic use from normal document-object encryption without introducing a second long-lived secret.

The backup ID is included in the database encryption associated data, so changing the manifest/directory backup identity invalidates database authentication.

## Encrypted objects

Live encrypted `.dwaar` object bytes are copied without decrypting them.

Verification performs both:

- manifest ciphertext size/hash checks;
- AES-GCM authentication/decryption through the existing document store using the supplied document master key.

No decrypted professional data is written into the published backup directory.

## Manifest

The manifest contains only operational metadata:

- manifest version;
- backup ID;
- backup timestamp;
- source schema version;
- encrypted database byte size/hash;
- opaque storage keys;
- encrypted object byte sizes/hashes.

It does not contain:

- client names;
- GSTINs;
- case titles;
- notice text;
- evidence text;
- draft text;
- filesystem source paths;
- encryption keys.

## Key custody

A backup cannot be fully verified or recovered without the same Dwaar document master key.

Therefore disaster recovery requires **two independent assets**:

1. the backup directory;
2. the externally managed document master key.

Losing either one makes the protected professional data unavailable.

The document master key must not be copied into the backup directory or manifest.

## Operator command

Create:

`python scripts/runtime_backup.py create`

Required environment:

- `DWAAR_DB_PATH`
- `DWAAR_OBJECT_ROOT`
- `DWAAR_BACKUP_ROOT`
- `DWAAR_DOCUMENT_KEY_B64`

Optional:

`--backup-id <safe-id>`

Verify:

`python scripts/runtime_backup.py verify <backup-directory>`

Verification also requires `DWAAR_DOCUMENT_KEY_B64`.

The CLI returns one sanitized JSON line and uses non-zero exit codes for configuration, backup, or verification failures.

## Scope boundary

Phase 3P.2 creates and verifies backups.

It does not yet overwrite a live runtime from a backup.

A restore operation needs a separate, stricter safety contract because restoring is destructive to the target runtime.

## Safety invariant

> A backup is not considered valid merely because files were copied. The database, manifest, encrypted objects, schema binding, object-reference set, hashes, and encryption authentication must all agree.
