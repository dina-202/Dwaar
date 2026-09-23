# Phase 3Q.1 — Pilot Truthfulness & CA-facing Analysis Presentation

## Purpose

Phase 3Q.1 is the first correction slice derived from hands-on product use after
the Phase 3P product rehearsal gate.

The trigger was a real local ASMT-10 intake rehearsal. The first run occurred
without a usable Gemini configuration and Dwaar safely blocked downstream work,
but the UI presented the safe classifier fallback as if the notice itself were
substantively unknown. After Gemini was configured, the same notice was
correctly recognized as ASMT-10 / triage-only, while partial extraction caused
positive DIN and authority observations to be hidden behind UNKNOWN
completeness statuses. The primary UI also exposed internal enum/value
dictionaries directly to a professional user.

These are truthfulness and product-semantics issues, not decorative polish.

## Contracts

### 1. Classifier execution failure is not an unknown-notice conclusion

The existing NoticeClassification dataclass remains unchanged.

The focused classifier keeps its existing safe fallback. A private deterministic
helper identifies only the closed malformed/unavailable classifier fallback.
The Phase-2 orchestrator converts that signal into an explicit triage message:

> Notice classification could not be completed because the AI classification
> step did not return a usable result.

A legitimately unknown or unsupported notice remains a different outcome.

No provider exception, API key, quota message, or raw provider response is
exposed to the professional UI.

### 2. Partial extraction blocks absence conclusions, not positive observations

FactExtractionStatus.PARTIAL still means Dwaar must not infer absence from what
was not extracted.

However, a positively accepted structured fact remains a valid observation for
preflight display:

- accepted RFN -> RFN_PRESENT
- accepted DIN -> DIN_PRESENT
- accepted RFN + DIN -> BOTH_PRESENT
- accepted authority designation + office -> PRESENT
- any accepted authority fact -> PARTIAL

When a PARTIAL extraction contains no such positive fact, completeness remains
UNKNOWN. FAILED and NO_INPUT likewise cannot produce absence conclusions.

Portal and authority verification requirements remain unchanged.

### 3. Professional view first; machine detail remains auditable

The default CA-facing analysis surface uses human-readable statements and
professional tables for:

- notice identification and support
- extraction outcome
- source-grounded facts
- communication identifiers
- authority details
- deadline availability
- arithmetic
- validation
- unresolved requirements
- evidence checklist
- review requirements
- triage
- drafting availability

Machine enum values, internal IDs, fact roles, rule/check IDs, and raw diagnostic
state remain available in collapsed **Technical details** sections.

Model-authored fact claims are not promoted into the primary facts table.
Primary fact display remains grounded in accepted source text/provenance.

### 4. ASMT-10 deadline truthfulness

ASMT-10 triage must not inject a generic form-level reply period or calendar
deadline from memory, an unversioned web page, or a workflow default.

The professional view may surface:

- the response-period wording explicitly extracted from the notice;
- the deterministic number of days parsed from that wording, when available;
- a calculated calendar deadline only when the required structured
  service/receipt date is verified;
- a separately maintained operational deadline after professional/portal
  verification.

A notice-stated due date remains separate from a calculated deadline. If both
exist and disagree, the conflict is shown rather than silently resolved.

A future ASMT-10 verified legal pack must reconcile authoritative Section 61 /
Rule 99 materials and their effective-date applicability before Dwaar uses
external law to supply any form-level timing proposition.

### 5. Triage evidence continuity

A TRIAGE_ONLY notice may still contain source-grounded operational evidence
work even though specialist validation/drafting is unavailable.

Two notice relationships may create review-only evidence targets:

- records the department explicitly asks the taxpayer to furnish; and
- annexures or supporting documents the notice explicitly references.

The target text is built only from the exact accepted notice `source_text`.
Model-authored claims are never used as evidence requirements. Every target
starts as `EvidenceStatus.UNKNOWN`; its existence does not prove possession,
receipt, completeness, sufficiency, responsiveness, enclosure, or submission.

For a live intake session, the triage workspace may build these targets from
the deterministic preflight/triage-selected fact IDs.

For a saved case, the same targets must remain available after save/reopen.
The historical snapshot schema is not amended merely to duplicate a second
checklist. Instead, when the specialist draft evidence checklist is empty,
the authorized evidence-review service deterministically reconstructs the
triage targets from the saved:

- `classification.support_level`;
- `triage_summary.requested_document_fact_ids`;
- `triage_summary.referenced_annexure_fact_ids`; and
- source-grounded `extraction.facts`.

Historical reconstruction fails closed if a selected fact is absent,
ambiguous, wrong-type, non-confirmed, or lacks usable source text.

A human evidence review remains snapshot-bound. Only a `CONFIRMED` review
counts as a human-confirmed match for operational attention. A rejected
candidate does not silently satisfy the requested/referenced record.

### 6. Safety gates do not weaken

This phase does not:

- create a new deep workflow;
- promote ASMT-10 beyond TRIAGE_ONLY;
- assume service/receipt date from notice date;
- relax draft eligibility;
- change legal-source applicability rules;
- bypass professional review;
- expose raw provider output.

## Pilot implication

ASMT-10 is recognized by Taxonomy v1 but still intentionally lacks a deep
specialist workflow. A separate scoped phase may add Section 61 / Rule 99
scrutiny support only after its legal, fact, evidence, deadline, validation, and
drafting contracts are defined and verified.
