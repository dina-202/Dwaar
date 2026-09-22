# Phase 3L — Filing and Acknowledgement Lifecycle

**Status:** Pilot filing record workflow  
**Date:** 22 September 2026  
**Depends on:** Phase 3K durable draft work product

## 1. Purpose

Phase 3L closes the gap between an APPROVED professional draft and an actual portal filing.

Dwaar now records:

- the exact APPROVED immutable draft version used as the filing basis;
- the actual PDF that was submitted;
- the portal / filing reference;
- the actual filing timestamp;
- the authenticated user who recorded the filing;
- the recording timestamp;
- an optional acknowledgement PDF;
- acknowledgement actor/time when added later.

APPROVED and FILED remain distinct states.

## 2. Filing basis versus filed artifact

The selected APPROVED DraftVersionRef is recorded as the professional filing basis.

The actual submitted PDF is persisted separately as:

`CaseDocumentKind.FILED_RESPONSE`

Dwaar does not claim that the submitted PDF is byte-for-byte or semantically identical to the approved draft.

That relationship is a professional filing assertion.

## 3. FilingRecord

Each durable filing contains:

- filing_id;
- case_id;
- approved_draft_version_id;
- filed_response_document_id;
- optional acknowledgement_document_id;
- filing_reference;
- filed_at;
- filed_by;
- recorded_at;
- optional acknowledgement_added_at;
- optional acknowledgement_added_by.

One case may have multiple FilingRecord values.

This supports supplementary submissions without overwriting earlier filing history.

## 4. SQLite schema v5

The shared SQLite schema moves from v4 to v5.

v5 adds:

`filing_records`

with foreign keys to:

- cases;
- draft_versions;
- case_documents for filed response;
- case_documents for acknowledgement.

The filing table stores metadata only.

Filed-response and acknowledgement bytes remain encrypted behind DocumentStore.

Existing v1-v4 pilot databases migrate idempotently to v5.

Unknown future schema versions fail closed.

## 5. Approved-draft requirement

A filing may reference only a DraftVersionRef whose:

`review_status == APPROVED`

The filing service additionally integrity-loads the encrypted immutable draft payload before linking it.

Therefore a stale/tampered draft metadata row is insufficient to create a filing record.

WORKING and REVIEWED versions cannot be filed.

## 6. Allowed case states

New filing records are accepted only when the current case status is:

- DRAFT_REVIEW;
- FILED;
- HEARING.

### First filing from DRAFT_REVIEW

The filing transaction changes:

`DRAFT_REVIEW -> FILED`

and emits CASE_STATUS_CHANGED.

### Additional filing while FILED

The case remains FILED.

### Additional filing while HEARING

The case remains HEARING.

This supports supplementary written submissions during proceedings without regressing operational state.

Other states, including ORDER_RECEIVED and CLOSED, reject new filing records.

## 7. Actual filed response

Every FilingRecord requires an actual filed-response PDF.

The file is validated using the same persistent PDF rules as other case documents:

- plain PDF filename;
- no path traversal;
- PDF signature;
- readable PDF structure;
- at least one page;
- no password protection.

The bytes are encrypted using the existing AES-256-GCM DocumentStore.

## 8. Filing reference

The portal / filing reference is:

- required;
- trimmed;
- max 200 characters;
- control-character-free.

Within one case, an exact duplicate filing reference is rejected before new filing artifacts are written.

This is an accidental duplicate-recording guard, not a legal assumption about portal-wide identifier uniqueness.

## 9. Filing timestamps

`filed_at` is the actual professional/portal filing time.

`recorded_at` is when Dwaar records the filing.

Both must be timezone-aware.

Dwaar requires:

`filed_at <= recorded_at`

This prevents a future filing timestamp from being recorded accidentally.

The Streamlit pilot UI accepts filed_at as ISO 8601 including timezone offset.

## 10. Acknowledgement

An acknowledgement may be:

- provided at filing time; or
- attached later.

Acknowledgement bytes are stored as:

`CaseDocumentKind.ACKNOWLEDGEMENT`

A filing may have at most one acknowledgement in Phase 3L.

Late acknowledgement attachment does not rewrite the core filing metadata.

It adds only:

- acknowledgement_document_id;
- acknowledgement_added_at;
- acknowledgement_added_by.

The core immutable filing basis/reference/filed-response/timestamps remain unchanged.

## 11. Authorization

Viewing filing history is case-read scoped.

Recording a filing or adding an acknowledgement requires:

- CASE_READ through case resolution;
- FILING_RECORD;
- DOCUMENT_ADD.

FILING_RECORD is purpose-specific and is not replaced by broad CASE_UPDATE.

The authenticated principal is always the filing/acknowledgement actor.

## 12. Atomic database transaction

For a filing, SQLite commits in one transaction:

1. FILED_RESPONSE document metadata;
2. optional ACKNOWLEDGEMENT metadata;
3. FilingRecord;
4. case status update when DRAFT_REVIEW -> FILED;
5. DOCUMENT_ADDED events;
6. optional CASE_STATUS_CHANGED event;
7. FILING_RECORDED event.

If any relational or audit insert fails, none of those database changes commit.

## 13. Cross-store consistency

Encrypted objects must be written before relational metadata references them.

For initial filing:

1. filed-response PDF is encrypted/stored;
2. optional acknowledgement PDF is encrypted/stored;
3. SQLite transaction commits all metadata/status/events.

If a later object write fails, already-written new objects are deleted.

If SQLite persistence fails, all new encrypted filing objects are deleted.

If compensating deletion itself fails, Dwaar raises a distinct FilingConsistencyError for operational remediation.

## 14. Audit events

The filing transaction uses existing/new controlled events:

### DOCUMENT_ADDED

For filed response and acknowledgement metadata.

Contains only:

- document ID;
- kind;
- SHA-256;
- byte size.

### CASE_STATUS_CHANGED

Only when first filing moves DRAFT_REVIEW to FILED.

### FILING_RECORDED

Contains:

- filing ID;
- approved draft version ID;
- filed-response document ID;
- acknowledgement document ID or `none`;
- filing reference;
- filed_at.

The repository requires exactly one FILING_RECORDED event and requires its actor to equal `filed_by`.

### FILING_ACKNOWLEDGEMENT_RECORDED

Used when acknowledgement is attached later.

Contains:

- filing ID;
- acknowledgement document ID.

The repository requires exactly one acknowledgement event and requires its actor to equal `acknowledgement_added_by`.

No draft text or document content appears in audit payloads.

## 15. Repository invariants

The SQLite FilingRepository independently verifies:

- filing case exists;
- approved draft exists;
- draft belongs to filing case;
- draft status is APPROVED;
- filed-response document belongs to the case;
- filed-response document kind is FILED_RESPONSE;
- acknowledgement, if present, belongs to the case;
- acknowledgement kind is ACKNOWLEDGEMENT;
- filing/event actor semantics match;
- later acknowledgement cannot replace an existing acknowledgement;
- acknowledgement cannot mutate core filing metadata.

## 16. Saved-case UI

A reopened case now includes:

**Filing & acknowledgement**

The history table shows:

- filing ID;
- portal/reference;
- approved draft version ID;
- filed-response document ID;
- acknowledgement document ID;
- filed_at;
- filed_by;
- recorded_at.

Read-only users can view metadata history.

## 17. Recording UI

Users with FILING_RECORD + DOCUMENT_ADD can:

1. select an APPROVED draft version;
2. enter portal / filing reference;
3. enter actual filed timestamp with timezone;
4. upload the actual filed-response PDF;
5. optionally upload acknowledgement PDF;
6. click **Record filing**.

The UI blocks submission if the filed-response PDF is missing.

If no APPROVED draft exists, recording is blocked.

## 18. Later acknowledgement UI

For filing records without an acknowledgement, authorized users may:

1. select the filing;
2. upload acknowledgement PDF;
3. click **Attach acknowledgement**.

The durable filing record is updated only with acknowledgement linkage/actor/time.

## 19. No automatic semantic equality claim

Phase 3L deliberately does not compare the actual filed-response PDF text to the approved draft and then declare them identical.

Reasons include:

- formatting changes;
- portal-generated wrappers;
- signatures/stamps;
- manual professional edits outside Dwaar;
- annexure packaging differences.

The selected approved draft remains a recorded filing basis, not an automated legal-equivalence assertion.

## 20. Current non-goals

Phase 3L does not:

- submit to the GST portal automatically;
- validate ARN/reference against the live portal;
- digitally sign documents;
- prove the filed PDF equals the approved draft;
- download portal acknowledgements automatically;
- create hearing/order records;
- close cases automatically.

Those belong to later workflow/integration phases.

## 21. Exit criteria

- SQLite schema v5 is deterministic and fail-closed;
- FilingRecord metadata is durable;
- actual filed-response PDF is mandatory and encrypted;
- only APPROVED immutable drafts can be filing bases;
- approved draft payload integrity is checked before filing;
- filing reference is required and duplicate-suppressed per case;
- filed_at and recorded_at are timezone-aware;
- first filing DRAFT_REVIEW -> FILED is atomic/audited;
- supplemental FILED/HEARING filings preserve case state;
- acknowledgement may be supplied initially or later;
- only one acknowledgement is attached per filing in this phase;
- filing/ack documents use controlled CaseDocumentKind values;
- FILING_RECORD + DOCUMENT_ADD gate mutation;
- filing DB metadata/status/events commit atomically;
- object-store writes compensate on DB failure;
- filing/ack audit actors are repository-enforced;
- saved-case UI exposes filing history and controls;
- approval is never treated as filing;
- full offline regression suite passes.
