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
- count of outstanding professional attention items

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

### Professional fact review — earned extension

The pilot now has an explicit professional decision layer over extracted facts.

Fact review is bound to one saved analysis version. A CA reviews the exact
source-grounded fact preserved in that analysis; the browser supplies only the
selected fact identity and cannot replace the source quote that is persisted.

The professional surface shows:

- fact type;
- exact source evidence;
- source page and verification state;
- the latest professional decision: Confirmed, Rejected, or Not reviewed.

**Confirmed** means only that the extracted item accurately reflects the source
notice. It is not an admission of a departmental allegation, a taxpayer
liability conclusion, legal acceptance, or filing approval.

**Rejected** means the extracted item/source mapping must not be relied on.
Draft approval for a draft derived from that saved analysis is blocked while
the latest professional decision for any source fact remains Rejected.

Review history is append-only. A later review does not overwrite an earlier
decision; the latest decision per fact is the operational state, selected
deterministically by review timestamp and review ID.

Reviewer notes and exact fact-review payloads are stored through the encrypted,
snapshot-bound review channel. Machine fact/review IDs and reviewer account IDs
remain audit/engineering data and are not part of the default CA surface.

Fact review never mutates the original extracted fact or silently converts a
department allegation into a taxpayer fact.

### Rejected fact attention

When the latest saved analysis has one or more extracted facts whose latest
professional review is **Rejected**, the case queue emits
`FACT_REVIEW_REJECTED` and routes it to **Analysis history**.

This attention means only that a source extraction/source mapping has been
professionally rejected and should be re-reviewed before the saved analysis is
relied on for draft approval. It is not a conclusion that the department's
allegation is false, that the taxpayer is not liable, or that any particular
reply should be filed.

The signal is permission-sensitive. A user who has CASE_READ but lacks
FACT_REVIEW does not receive or infer the rejected-fact state through the case
cockpit.

A later professional review can supersede the operational state while preserving
the earlier immutable review in history.

### Triage case attention

The professional queue must reflect what the saved analysis actually supports.

When the latest saved analysis is `TRIAGE_ONLY` or `UNKNOWN`, Dwaar does not
emit specialist-only actions such as:

- verified legal brief not saved; or
- specialist draft not started.

Those actions would direct the CA toward capabilities that are intentionally
unavailable for that matter.

Existing real artifacts remain authoritative: if a draft version or filing
already exists, its actual review/approval/filing state can still create the
normal operational attention.

For TRIAGE_ONLY cases with requested/referenced evidence targets, the queue may
instead emit `TRIAGE_EVIDENCE_REVIEW_PENDING`. It routes only to the Evidence
workspace and means only that one or more saved triage evidence targets do not
yet have a human-confirmed evidence match. It is not a conclusion that evidence
is legally missing, insufficient, inadmissible, or unresponsive.

A rejected evidence candidate does not clear this attention state. Only a
human-confirmed review for the target does.

### Audit identity display

Authentication/audit identifiers such as OIDC subject IDs remain preserved in
the audit record and engineering diagnostics. They are not shown as professional
names in ordinary draft, evidence-review, or filing-history tables.

Until Dwaar has an authorized firm-user display-name directory, it must not
invent or infer human names from those identifiers.

## Failure-detail boundary

The professional surface must not render raw backend exception text from notice
analysis, PDF parsing, evidence matching, provider calls, object storage,
database access, encryption/integrity checks, or other internal services.

Customer mode renders a controlled professional failure message only.

When `DWAAR_ENGINEERING_DIAGNOSTICS` is explicitly enabled, the same failure
may additionally expose its exception type and message inside a clearly
labelled **Technical details** expander for internal diagnosis. This does not
change the underlying fail-closed engine behavior.

Regression coverage must inject deliberately sensitive-looking error text
(provider tokens, storage/ciphertext details, database paths) and prove that it
does not appear in customer mode.

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
