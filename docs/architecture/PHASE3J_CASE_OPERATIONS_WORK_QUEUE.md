# Phase 3J — Case Operations Work Queue

**Status:** Pilot firm operations workflow  
**Date:** 22 September 2026  
**Depends on:** Phase 3I client workspace/history

## 1. Purpose

Phase 3J turns persisted cases into an actionable CA-firm work queue.

A professional with CASE_READ can see every case prioritized by response-deadline urgency.

A professional with CASE_UPDATE can additionally make controlled operational changes to:

- case status;
- response deadline;
- assignee;
- reviewer.

Operational changes are validated, authorized and audited atomically.

## 2. Work queue projection

Dwaar adds the typed `CaseWorkItem` projection containing:

- case ID;
- client ID;
- client display name;
- case title;
- CaseStatus;
- response deadline;
- days remaining;
- WorkQueueDeadlineStatus;
- assignee;
- reviewer.

The work queue joins CaseRecord and Client metadata only.

It does not decrypt notice documents or load analysis/evidence payloads.

## 3. Deadline priority

WorkQueueDeadlineStatus is closed to:

- OVERDUE;
- DUE_TODAY;
- DUE_SOON;
- UPCOMING;
- NO_DEADLINE;
- CLOSED.

For non-closed cases with a response deadline:

`days_remaining = response_deadline - today`

Buckets are:

- < 0: OVERDUE;
- = 0: DUE_TODAY;
- 1–7: DUE_SOON;
- > 7: UPCOMING.

Cases without a deadline are NO_DEADLINE.

CLOSED cases are always CLOSED regardless of any historical deadline.

## 4. Queue ordering

The deterministic priority order is:

1. OVERDUE;
2. DUE_TODAY;
3. DUE_SOON;
4. UPCOMING;
5. NO_DEADLINE;
6. CLOSED.

Within a bucket, ordering uses:

- response deadline;
- client name, case-insensitive;
- case ID.

A case referencing an unavailable client fails the queue projection closed rather than displaying fabricated client data.

## 5. Status transition graph

Phase 3J does not permit arbitrary CaseStatus jumps.

Allowed transitions are:

### INTAKE
- ANALYZED
- EVIDENCE_COLLECTION
- CLOSED

### ANALYZED
- EVIDENCE_COLLECTION
- DRAFT_REVIEW
- CLOSED

### EVIDENCE_COLLECTION
- ANALYZED
- DRAFT_REVIEW
- CLOSED

### DRAFT_REVIEW
- EVIDENCE_COLLECTION
- FILED
- CLOSED

### FILED
- HEARING
- ORDER_RECEIVED
- CLOSED

### HEARING
- FILED
- ORDER_RECEIVED
- CLOSED

### ORDER_RECEIVED
- CLOSED

### CLOSED
- no further transitions

Keeping the same status is allowed when another operational field changes.

CLOSED is terminal.

## 6. Closed-case invariant

Repository persistence enforces:

- CaseStatus.CLOSED requires a non-null `closed_at`;
- every non-CLOSED status requires `closed_at is None`.

The authorized operations service sets `closed_at` to the authenticated update timestamp when a case is closed.

Closed cases cannot receive further operational edits.

## 7. Authorization

Viewing the work queue requires:

`CASE_READ`

Mutating operational fields requires:

`CASE_UPDATE`

UI visibility does not replace service authorization.

Every update re-resolves the case within the active firm before mutation.

## 8. Assignment/reviewer safety

Assignee and reviewer are not free-text professional identities.

The UI loads candidates from persistent active firm-access grants.

An assignable/reviewable user must:

- have an active grant for the same firm;
- have CASE_READ.

The backend revalidates the selected user ID on every save.

A user ID from another firm, inactive grant, or grant without CASE_READ is rejected.

The current pilot UI displays authenticated opaque user IDs because Dwaar does not yet have a separate staff-profile/name directory.

## 9. Firm-member discovery

AccessGrantRepository adds:

`list_grants_for_firm(firm_id)`

The SQLite implementation:

- is firm-scoped;
- returns grants ordered by user ID;
- preserves the grant's active state and full permission set.

This is an authorization-data lookup, not a public employee directory.

## 10. Operational update contract

`update_case_operations()` accepts only:

- target CaseStatus;
- response deadline or None;
- assignee user ID or None;
- reviewer user ID or None;
- timezone-aware update timestamp.

It validates:

1. CASE_UPDATE permission;
2. case belongs to active firm;
3. update timestamp is timezone-aware;
4. typed status/deadline/identities;
5. status transition is allowed;
6. existing case is not CLOSED;
7. assignee is an active same-firm CASE_READ user;
8. reviewer is an active same-firm CASE_READ user;
9. at least one operational value actually changes.

A no-op update is rejected.

## 11. Atomic persistence

CaseRepository adds:

`update_case_with_events(case, events)`

SQLite performs in one transaction:

1. immutable case-identity validation;
2. closed_at invariant validation;
3. case row update;
4. insertion of all audit events.

If any audit-event insert fails, the case-row update rolls back.

This prevents operational state from changing without its audit history.

## 12. Audit events

Phase 3J adds:

`CASE_OPERATIONS_UPDATED`

A status change emits:

`CASE_STATUS_CHANGED`

with:

- from_status;
- to_status.

A deadline/assignment/reviewer change emits:

`CASE_OPERATIONS_UPDATED`

with before/after metadata for:

- response deadline;
- assignee;
- reviewer.

None values are represented by the controlled metadata string `none`.

All events use the authenticated principal as actor.

No notice text, evidence quote, reviewer note, document bytes, token or secret is placed in event metadata.

## 13. Operational bypass protection

The older generic `AuthorizedCaseService.update_case()` remains available for non-operational case metadata.

It is explicitly prohibited from changing:

- status;
- response deadline;
- assignee;
- reviewer;
- closed_at.

Any attempt to change those fields through the generic path fails and directs callers to `update_case_operations()`.

This ensures operational state cannot bypass the Phase 3J atomic audit path through the authorized service layer.

## 14. Work queue UI

The main app now renders:

1. Case work queue;
2. Client workspace;
3. Saved cases;
4. New notice intake, when permitted.

The work queue table shows:

- case/client/title;
- status;
- deadline bucket;
- response deadline;
- days remaining;
- assignee;
- reviewer.

A selected queue case can be focused into Saved cases without decrypting it.

The existing **Open saved case** path remains the only saved-notice decryption/reanalysis path.

## 15. Update UI

CASE_UPDATE users may select one queue case and edit:

- operational status from only allowed targets;
- response deadline using ISO `YYYY-MM-DD`;
- assignee from active eligible firm users;
- reviewer from active eligible firm users.

Blank deadline clears the operational response deadline.

“Unassigned” clears assignment/reviewer.

Closed cases display as terminal and do not render update controls.

## 16. Historical inactive identities

A persisted historical assignee/reviewer may later become inactive or lose CASE_READ.

Dwaar may still display the stored historical user ID.

The backend will not accept that identity on a new operational save unless it is currently eligible.

The professional must clear or replace an ineligible identity when making a new operational update.

## 17. No automatic legal effect

Changing an operational CaseStatus does not itself:

- prove facts;
- satisfy evidence requirements;
- change draft validation results;
- file a response;
- create an ARN/acknowledgement;
- record a hearing or order.

Those legal/work-product events remain separate contracts.

## 18. No schema migration

Phase 3J uses existing case columns and case_events storage.

`CASE_OPERATIONS_UPDATED` is a new controlled event-type value stored in the existing event table.

No SQLite schema-version change is required.

## 19. Exit criteria

- deterministic queue deadline buckets are implemented;
- queue ordering is deterministic;
- CASE_READ gates queue visibility;
- CASE_UPDATE gates operations mutation;
- status transitions use a closed graph;
- CLOSED is terminal;
- closed_at invariant is repository-enforced;
- assignee/reviewer must be active same-firm CASE_READ users;
- firm-member discovery is scoped and deterministic;
- case update + audit events are one transaction;
- failed event insert rolls back case state;
- status changes are audited;
- deadline/assignment/reviewer changes are audited;
- generic authorized update cannot bypass the operations audit path;
- queue focus reuses the existing Saved cases open path;
- invalid deadline input fails before mutation;
- internal errors are not rendered;
- full regression suite passes.
