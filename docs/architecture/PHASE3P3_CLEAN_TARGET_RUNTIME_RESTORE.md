# Phase 3P.3 — Clean-Target Runtime Restore

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.2 encrypted runtime backup integrity

## Goal

Prove that a verified Dwaar runtime backup can be recovered into a clean target without overwriting an existing runtime and without publishing partially restored state.

## Restore contract

A restore requires:

- one previously verified runtime backup directory;
- the same external document master key used by the source runtime;
- a target database path that does not already exist;
- a target encrypted-object directory that is absent or empty.

The restore never overwrites an existing database and never restores into a non-empty object directory.

## Order of operations

The restore is intentionally staged:

1. fully verify the backup manifest, encrypted database and every encrypted object;
2. decrypt the backup database only into a private staging file;
3. copy encrypted object bytes into a private staging directory;
4. run SQLite integrity/foreign-key/schema checks on the staged database;
5. verify that staged database storage references exactly match the backup manifest;
6. authenticate every staged encrypted object with the supplied document key;
7. publish the validated object directory;
8. publish the database last.

The target database file is the completion marker.

## Why the database is published last

If object publication succeeds but database publication fails, the restore removes the published object directory during rollback.

A target runtime is not considered restored until its database has been published and a final integrity/authentication pass succeeds.

## Clean-target safety

The restore refuses to proceed when:

- target database already exists;
- target object path is a file;
- target object directory is non-empty;
- backup authentication fails;
- the wrong document master key is supplied;
- the backup database or object ciphertext is tampered;
- the schema/reference set is inconsistent.

This phase deliberately does not implement destructive in-place rollback of a live runtime.

A production recovery should restore to a clean path, validate it, and then use an external deployment/switchover process.

## Encryption behavior

The published backup database remains encrypted at rest in the backup.

During recovery it is decrypted only into a private staging SQLite file.

Professional object files are never decrypted to disk by the restore operation; their ciphertext bytes are copied exactly and authenticated through the existing encrypted document-store boundary.

## Operator command

Create or select a verified backup, then run:

`python scripts/runtime_backup.py restore <backup-directory> --target-db <path> --target-objects <directory>`

Required environment:

- `DWAAR_DOCUMENT_KEY_B64`

The restore command emits one sanitized JSON object.

Success exit code:

- `0`

Failure exit code:

- `1`

The output does not include:

- target paths;
- backup paths;
- document key values;
- client/case metadata;
- underlying exception details.

## Recovery drill

A valid recovery drill must demonstrate all of the following:

1. backup verifies with the intended master key;
2. restore succeeds only into a clean target;
3. restored SQLite can be opened through the normal repository;
4. expected case/client/document metadata is present;
5. encrypted objects decrypt through the normal document store using the same master key;
6. no restore staging files/directories remain;
7. source encrypted object bytes and restored encrypted object bytes match exactly.

## Scope boundary

3P.3 proves recoverability for the current single-node runtime.

It does not yet provide:

- live in-place rollback;
- automatic deployment switchover;
- point-in-time recovery between backups;
- multi-node coordinated recovery;
- remote/offsite backup transport;
- backup retention policies.

Those belong to later production-operations work.

## Safety invariant

> Recovery must prove a complete, authenticated runtime in a clean target before any restored state is considered usable.
