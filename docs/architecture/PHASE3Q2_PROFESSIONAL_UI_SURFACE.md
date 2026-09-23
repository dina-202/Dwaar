# Phase 3Q.2 — Professional UI Surface

## Purpose

Phase 3Q.2 applies the pilot lesson from the notice-analysis screen to the
day-to-day CA workspace. Dwaar must remain deeply auditable without making a
professional user operate through storage IDs, enum values, hashes, or
machine-state dictionaries.

This phase is presentation-only unless explicitly stated. It does not alter
authorization, persistence, legal reasoning, validation, drafting, filing, or
workflow support.

## Product rule

The default professional surface answers four questions:

1. What matter am I looking at?
2. What is its current professional state?
3. What needs attention or action?
4. Where should I continue the work?

Machine identifiers and implementation metadata remain available under
collapsed **Technical details** sections for support, audit, and forensic use.

## Surfaces

### Case work queue

Primary:
- client
- matter title
- human-readable case/deadline state
- response deadline and days remaining
- assignee/reviewer
- count of deterministic attention items

Technical:
- case ID
- raw status/deadline enums
- attention codes/workspace codes

### Client workspace

Primary:
- client name
- registration/matter counts
- tax registration values
- matter history in professional labels

Technical:
- client, registration, and case IDs
- raw proceeding values

### Case attention

Primary:
- human-readable attention condition
- owning workspace
- deterministic explanation

Technical:
- projection IDs and raw attention/workspace codes

### Case timeline

Primary:
- time
- human-readable category
- activity
- summary

Technical:
- event ID
- raw event type
- actor ID

### Saved/opened cases and intake

Primary:
- matter title
- status
- notice form/proceeding label
- deadline
- clear save/open confirmations

Technical:
- case/client/registration IDs
- analysis-source marker

Default case titles use professional proceeding labels. An unknown triage
proceeding is labelled "Intake", not the raw word "unknown".

### Evidence review

Primary:
- evidence requirement
- exact source evidence
- page
- verification state
- professional review state

Technical:
- candidate/evidence/document/review IDs and source-channel enums

## Non-negotiable safety

Phase 3Q.2 does not:
- hide provenance;
- discard IDs or audit metadata;
- turn model-authored summaries into evidence;
- change deterministic attention ordering;
- weaken permission gates;
- change case state transitions;
- infer legal conclusions;
- change deep-workflow eligibility.

The technical surface is secondary, not removed.
