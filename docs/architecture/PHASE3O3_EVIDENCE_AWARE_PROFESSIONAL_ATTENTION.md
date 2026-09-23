# Phase 3O.3 — Evidence-Aware Professional Attention

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.14 ITC legal evidence readiness and Phase 3O.2 authorized case cockpit

## Goal

Surface legal-evidence work that still needs professional attention without turning evidence readiness into a legal conclusion or a drafting gate.

## New attention codes

The professional case-attention model adds:

- `LEGAL_EVIDENCE_INCOMPLETE`
- `LEGAL_EVIDENCE_CONTRACT_DRIFT`

### LEGAL_EVIDENCE_INCOMPLETE

Emitted when the authorized legal-evidence readiness projection exists for the latest saved analysis snapshot and at least one closed legal question does not yet have its required human-confirmed evidence set.

The related ID is the stable legal question ID.

This means evidence review work remains.

It does not mean the taxpayer fails the legal condition.

### LEGAL_EVIDENCE_CONTRACT_DRIFT

Emitted when the caller is authorized to inspect evidence-review state but the latest historical snapshot does not contain the current closed legal-evidence requirement IDs.

This is an architecture/history compatibility signal.

It does not reinterpret the historical snapshot.

## Permission boundary

The general case cockpit remains readable through its existing case-read path.

Legal evidence review state remains protected by the existing `EVIDENCE_REVIEW` authorization boundary.

The workbench asks the authorized evidence-review service for the latest snapshot's evidence readiness.

If that service denies access:

- the cockpit continues to work;
- no evidence review metadata is exposed;
- no evidence-derived attention item is emitted.

Absence of an evidence attention item for a user without evidence-review permission must not be interpreted as evidence completeness.

## Latest-snapshot rule

Evidence attention is computed only for the latest saved analysis snapshot, matching the cockpit's existing legal-brief rule.

Evidence reviews bound only to an older snapshot do not make the current case appear evidence-ready.

## Relationship to other attention

Multiple attention items may coexist.

For example a case can simultaneously have:

- unresolved legal research;
- incomplete legal evidence;
- a draft awaiting review.

Dwaar does not collapse these into one score or choose a legal strategy.

## Drafting boundary

Neither new attention code changes Phase-2 `DraftEligibility`.

Neither code automatically blocks, approves or alters an existing draft.

They are read-only professional attention facts.

## Safety invariant

> Evidence incompleteness is a workflow fact, not a legal verdict.

The cockpit can tell a CA where work remains without deciding what the evidence proves.
