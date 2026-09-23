# Phase 3P.4 — Operator Health and Backup Posture

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.3 clean-target runtime restore

## Goal

Give an operator one sanitized answer to a practical production question:

> Is the current Dwaar runtime usable, and is the nominated disaster-recovery backup both valid and recent enough for the deployment's own backup policy?

This layer is operational only. It does not expose professional case content.

## Inputs

Operator health requires:

- the normal Dwaar runtime environment;
- one nominated backup directory;
- an explicit maximum acceptable backup age;
- the current time.

The maximum backup age is not hardcoded by Dwaar.

Different deployments can choose different policies based on their operational requirements.

## Closed checks

The report contains exactly three high-level checks:

1. `runtime_preflight`
2. `backup_verification`
3. `backup_freshness`

### Runtime preflight

Reuses Phase 3P.1.

The runtime must pass:

- configuration validation;
- SQLite open/migration;
- SQLite integrity;
- encrypted object-store round trip.

### Backup verification

Reuses the Phase 3P.2 cryptographic/integrity verifier.

The nominated backup must pass:

- manifest validation;
- encrypted database hash/authentication;
- SQLite integrity/foreign keys;
- exact database/object reference binding;
- encrypted object hash/size verification;
- encrypted object authentication with the configured master key.

### Backup freshness

Freshness is evaluated only after backup verification succeeds.

The backup manifest timestamp is compared with the explicit operator policy:

`backup_age <= max_backup_age_hours`

A future-dated backup fails closed rather than producing a negative age.

## Wrong-key behavior

A wrong but syntactically valid document key can still pass the runtime's empty probe because that probe writes and reads its own new object.

The backup verification check exists partly to catch this class of operational mistake.

A backup encrypted under the correct historical key will fail authentication under the wrong key.

Therefore:

> runtime probe success alone does not prove disaster-recovery key custody.

## Sanitization

The report may contain:

- check code;
- pass/blocked state;
- fixed safe message;
- numeric backup age.

It must not contain:

- database path;
- object-store path;
- backup path;
- backup ID;
- encryption key;
- key fingerprint;
- client names;
- case titles;
- GSTINs;
- document text;
- underlying exception strings.

## Operator command

Run:

`python scripts/operator_health.py <backup-directory> --max-backup-age-hours <hours>`

Exit codes:

- `0` — runtime, backup verification and freshness all pass;
- `1` — health is blocked;
- `2` — command/policy inputs are invalid.

Output is one JSON object suitable for deployment or monitoring scripts.

## No implicit backup selection

The command intentionally checks one nominated backup.

It does not guess the "latest" backup from filenames, directory modification times or custom backup IDs.

Those values are not trustworthy substitutes for a verified manifest.

A later backup scheduler/catalog may nominate a backup explicitly.

## Scope boundary

Phase 3P.4 does not:

- expose application logs;
- collect client usage analytics;
- send alerts;
- schedule backups;
- choose backup retention policy;
- perform recovery automatically;
- assign operational severity scores.

It provides a deterministic health primitive that external deployment tooling can call.

## Safety invariant

> Production health may describe runtime and recovery posture, but it must not turn operational diagnostics into another channel for professional data leakage.
