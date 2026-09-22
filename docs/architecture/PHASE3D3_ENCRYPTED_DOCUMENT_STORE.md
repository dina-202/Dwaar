# Phase 3D.3 — Authenticated Encrypted Local Document Store

**Status:** Pilot backend  
**Date:** 22 September 2026  
**Depends on:** Phase 3D.1 DocumentStore port

## 1. Decision

The local pilot may persist raw document bytes only through an authenticated-encryption store.

The implementation uses AES-256-GCM through PyCA `cryptography.AESGCM`.

The master key is supplied by the caller. It is never written to:
- source control;
- SQLite;
- object files;
- audit events.

## 2. Why authenticated encryption

Confidentiality alone is insufficient for tax records. Dwaar must also detect ciphertext tampering.

AES-GCM provides authenticated encryption with associated data (AEAD). NIST SP 800-38D specifies GCM as an authenticated-encryption mode. PyCA recommends its high-level AESGCM API for messages that fit into memory.

## 3. Nonce rule

Every stored object receives a fresh random 96-bit nonce from `os.urandom`.

Nonce reuse under the same GCM key is prohibited. NIST guidance emphasizes that GCM security depends strongly on non-repeating IVs/nonces.

No deterministic nonce derivation is used.

## 4. Associated data

The opaque Dwaar storage key is authenticated as AEAD associated data.

Therefore a ciphertext copied or renamed under a different storage key cannot be successfully decrypted.

This binds:

```text
ciphertext <-> storage_key
```

without exposing the storage key as secret material.

## 5. Storage keys

Valid keys have exactly this application-owned shape:

```text
objects/<32 lowercase hex UUID characters>
```

User filenames are never accepted as storage keys.

`generate_storage_key()` creates the key.

This construction makes path traversal impossible by the document-store API.

## 6. On-disk envelope

Pilot envelope:

```text
magic/version | 12-byte nonce | AES-GCM ciphertext+tag
```

The original filename, case ID, GSTIN, taxpayer name and media type are not embedded in the encrypted filename.

Physical filenames are opaque UUID-based `.dwaar` objects.

## 7. Atomic publication / overwrite rule

Encrypted bytes are first written to a private temporary file in the storage directory and fsynced.

Publication uses an atomic hard-link operation. If the destination already exists, publication fails. Existing objects are never overwritten by `put`.

## 8. File permissions

Where POSIX modes are available:
- storage root is restricted to owner access;
- ciphertext objects are restricted to owner read/write.

These filesystem permissions are defense-in-depth, not a substitute for encryption or application authorization.

## 9. Size limits

The store has a configured maximum plaintext byte size and rejects oversized payloads before encryption/write.

The pilot default is 20 MiB.

Higher-level upload validation must still enforce:
- allowed PDF types;
- actual file signature/type checks;
- parser safety;
- authorization;
- malware/CDR policy when deployed to real users.

## 10. Key management boundary

Phase 3D.3 deliberately does not decide where a production master key lives.

Production key management should use a secret manager/KMS/HSM-appropriate mechanism and support:
- access auditing;
- key rotation;
- separation from application/database backups;
- revocation/recovery planning.

A plaintext key committed to `.env`, Git, SQLite or logs is not an acceptable production setup.

A later configuration unit may load a key from process environment or a secret provider, but the document store itself only accepts raw key bytes.

## 11. Delete behavior

`delete` removes the encrypted object.

Case/product retention logic must decide *whether* deletion is authorized. The low-level DocumentStore does not make retention/legal decisions.

## 12. Exit criteria

- AES-256-GCM round-trip succeeds;
- plaintext is absent from ciphertext files;
- fresh objects produce distinct encrypted envelopes;
- tampering fails authentication;
- wrong master key fails authentication;
- storage-key reassignment fails authentication;
- path traversal keys are impossible;
- objects cannot be silently overwritten;
- size limit is enforced;
- delete/get missing errors are controlled;
- POSIX permissions are restrictive where supported;
- full regression suite passes.
