# Phase 3N.10 — Backward-Readable Legal Brief Schema v2

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.9 legal question workspace

## Goal

Preserve the exact legal-question state that existed when a verified legal brief was saved, without making any previously saved v1 legal brief unreadable.

## Schema evolution rule

The current write schema becomes legal-brief schema v2.

The reader explicitly supports:

- schema v1;
- schema v2.

A loader must never assume that the current write version is the only readable version.

## v1

v1 preserves:

- snapshot binding;
- legal catalog version;
- legal as-of date;
- proceeding type;
- matched verified legal rules;
- unresolved legal topics.

v1 contains no legal-question state.

When a v1 brief is reopened, Dwaar shows its original payload and explicitly states that the brief predates question-state preservation.

Dwaar does not reconstruct historical question state from the current catalog or current workflow definitions.

## v2

v2 keeps every v1 field and adds `questions`.

Each preserved question records:

- question ID;
- professional question text;
- legal topic;
- applicability date basis;
- deterministic question status;
- related source fact IDs;
- missing fact selectors;
- matched verified rule IDs.

Missing fact selectors contain only closed machine metadata:

- FactType;
- FactRole;
- accepted FactStatus values.

No raw notice text or LLM-generated legal conclusion is duplicated into the question section.

## Integrity

Legal brief metadata and encrypted payload must agree on the schema version.

The loader fails closed when:

- metadata schema is unsupported;
- payload schema is unsupported;
- payload schema differs from metadata schema;
- any existing snapshot/catalog/date/proceeding/hash binding fails.

## New-save behavior

The authorized legal-brief service now reconstructs the exact saved analysis facts, derives the legal date context, resolves the verified legal brief, builds the deterministic legal-question plan, and persists both into one immutable encrypted v2 artifact.

## Historical behavior

Existing v1 database rows need no migration.

Their metadata continues to say schema version 1 and their encrypted payload remains unchanged.

The v2 reader understands that historical shape directly.

## Safety invariant

> Schema evolution may add provenance, but it must never rewrite historical legal research or make old encrypted work product unreadable.
