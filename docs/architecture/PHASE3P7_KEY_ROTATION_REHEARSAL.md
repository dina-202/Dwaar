# Phase 3P.7 — Clean-Target Document Key Rotation Rehearsal

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.5 document key identity and Phase 3P.6 live storage consistency

## Goal

Prove that the complete live encrypted-object runtime can move from document-key generation A to generation B without mutating the source runtime and without making historical key-A backups unusable.

This phase is a rehearsal mechanism, not an in-place live-key switch.

## Rotation model

The source runtime remains read-only.

The rehearsal:

1. validates source runtime storage consistency with the old key;
2. snapshots SQLite into a staging database;
3. discovers the exact referenced storage-key set from the staged database;
4. decrypts each referenced object with key A;
5. re-encrypts the same storage key and plaintext with key B;
6. authenticates each newly encrypted object;
7. runs a full storage-consistency audit on the staged target;
8. publishes the target object directory;
9. publishes the target database last;
10. runs a final audit with key B.

The target database is the completion marker.

## Identity rules

The rehearsal requires:

- old 32-byte document master key;
- old opaque document key ID;
- new 32-byte document master key;
- new opaque document key ID.

The new key bytes must differ from the old key bytes.

The new key ID must differ from the old key ID.

Key IDs remain bookkeeping only; cryptographic proof still comes from AES-GCM authentication.

## Storage-key stability

Object `storage_key` values do not change during rotation.

Only ciphertext changes.

This preserves all SQLite relationships and avoids rewriting every metadata row merely because encryption generation changed.

## Source safety

The source runtime is never modified.

Tests explicitly prove that after a successful rehearsal:

- source ciphertext is unchanged;
- source objects remain decryptable under key A;
- the source runtime still passes live-storage audit under key A;
- key B cannot authenticate source objects.

## Target safety

The rotated target:

- is readable with key B;
- fails authentication under key A;
- preserves the exact database schema and storage-reference set;
- can create and verify a new manifest-v2 backup labelled with the new key ID.

The rehearsal refuses:

- an existing target database;
- a non-empty target object directory;
- an inconsistent source runtime;
- same old/new key material;
- same old/new key IDs;
- malformed key IDs.

Partial failures remove staged/published target state where possible.

## Historical backups

This rehearsal does not rewrite historical backups.

A backup created under key generation A remains tied to key A and must remain recoverable with key A for as long as that backup is retained.

A successfully rotated runtime can begin producing new backups under key generation B.

Therefore a real operational rotation requires an explicit old-key retention policy aligned with backup retention.

## Operator command

Required source runtime environment:

- `DWAAR_DB_PATH`
- `DWAAR_OBJECT_ROOT`
- `DWAAR_DOCUMENT_KEY_B64`
- `DWAAR_DOCUMENT_KEY_ID`

Required next-generation environment:

- `DWAAR_NEW_DOCUMENT_KEY_B64`
- `DWAAR_NEW_DOCUMENT_KEY_ID`

Run:

`python scripts/runtime_key_rotation.py --target-db <clean-db-path> --target-objects <clean-object-dir>`

Success returns sanitized JSON containing:

- operation;
- old key ID;
- new key ID;
- object count;
- schema version.

It never prints:

- key bytes/base64;
- source or target paths;
- case/client/document data;
- underlying cryptographic errors.

## Production switchover boundary

3P.7 deliberately does not automate changing the live deployment from source runtime A to rotated target B.

The safe operational pattern is:

1. create fresh key-A backup;
2. verify backup + recovery;
3. quiesce writes;
4. rehearse/produce rotated clean target;
5. validate target under key B;
6. create and verify first key-B backup;
7. switch deployment configuration externally;
8. retain key A until all retained key-A backups expire or are deliberately migrated.

The external switchover should be reversible until key-B runtime health is confirmed.

## Safety invariant

> Key rotation must produce a fully validated new runtime before the old runtime or old key generation is retired.
