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

Machine identifiers and implementation metadata remain preserved for support,
audit, and forensic use, but they are not part of the default CA surface.
Engineering diagnostics are enabled only when the deployment explicitly sets
`DWAAR_ENGINEERING_DIAGNOSTICS` to a truthy value. When enabled, Dwaar shows
a visible operator warning and exposes the existing **Technical details**
sections. The default is off.

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

Default case titles use professional proceeding labels. When a triage notice
has an unknown proceeding but a known notice family, the known family is used
as context (for example `ASMT-10 — Assessment / scrutiny`). Only a notice
whose proceeding and family are both unknown falls back to "Intake".

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

The technical surface is engineering-only by default, not removed from the
codebase or from the underlying audit/provenance model.
