# Phase 3N.2 — Snapshot-Bound Legal Briefs

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N verified legal knowledge and Phase 3F.4 analysis snapshots

## Goal

Freeze the exact legal-research result used with a saved analysis without changing or invalidating the existing analysis-snapshot schema.

A legal brief is therefore a separate immutable artifact linked to:

- one case;
- one saved analysis snapshot;
- one explicit legal `as_of_date`;
- one proceeding type;
- one exact legal catalog version.

## Why it is separate from analysis snapshot v1

Existing analysis snapshots are immutable historical artifacts. Bumping their schema merely to attach new legal metadata would make older snapshots harder to replay and would couple legal-catalog evolution to the core analysis schema.

Phase 3N.2 keeps snapshot schema v1 intact and adds a child artifact instead.

## Persistence model

SQLite schema v6 adds `legal_briefs`.

The row stores metadata only. The complete legal brief payload goes through the existing encrypted `DocumentStore` boundary.

The payload contains:

- exact catalog version;
- explicit legal as-of date;
- proceeding type;
- exact matched rule IDs/keys;
- source title/version/official URL;
- proposition recorded at save time;
- effective interval;
- verification date;
- unresolved legal topics.

This means a historical legal brief does not change when the current catalog later changes.

## Audit

Saving a brief appends `LEGAL_BRIEF_SAVED` to the case event stream.

The event contains metadata only:

- legal brief ID;
- snapshot ID;
- catalog version;
- as-of date;
- proceeding type;
- payload hash.

It does not contain legal propositions or client data.

The unified case timeline renders this event under the existing Analysis category.

## Integrity

Load fails closed if:

- legal brief ID does not exist;
- case/snapshot relationship differs;
- schema version differs;
- ciphertext size/hash differs from metadata;
- JSON payload is malformed;
- payload snapshot/catalog/date/proceeding binding differs from metadata.

A catalog-invalid result cannot be persisted as a trusted legal brief.

## Transaction / rollback rule

Encrypted bytes are written before metadata.

If metadata/audit persistence fails, the encrypted object is deleted.

If both metadata persistence and encrypted-object rollback fail, a distinct consistency error is raised.

## Scope boundary

This phase does **not**:

- change the Phase-2 draft renderer;
- make legal propositions filing-ready automatically;
- infer the correct substantive-law date for tax-period-sensitive questions;
- overwrite old legal briefs after catalog updates;
- add live network retrieval.

It establishes durable legal-research provenance first.
