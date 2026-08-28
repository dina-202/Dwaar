# CA Notice AI — Architecture Specification v1.1

**Purpose:** Real-world GST notice taxonomy + practical CA preflight layer.

**Status:** FINAL — AUTHORITATIVE for all Phase 2 work from Step 2.5 onward (approved by Dina, 2026-08-28). It supersedes `docs/architecture/ARCHITECTURE_SPEC_v1.md`, which is retained unmodified as the historical record (a small superseded notice has been added at its top). Completed Phase 2 Steps 1 and 2 (domain models + deterministic deadline engine) were built under v1 and remain valid; their contracts carry forward unchanged except where this document explicitly says otherwise.

---

## 0. Why v1.1 Exists

Phase 2 v1.0 proved the core engineering direction: deterministic work belongs in Python; language/reasoning belongs in the LLM. Steps 1 and 2 (domain models + deterministic deadline engine) are complete.

Real-world review now adds two requirements:

1. The system must recognize a much broader universe of GST notices/forms than the five deep workflows currently implemented/planned.
2. Before legal reasoning or drafting, the system must perform a practical CA-style preflight: identify authority, communication identifier/authenticity path, form, sections/rules, reason, deadlines, arithmetic, evidence, annexures and filing trail.

**Do not throw away the existing five workflows.** They remain the first five deep-analysis workflows. The broader taxonomy is a recognition/triage layer above them.

---

## 1. Core Product Rule

> **Recognize broadly. Analyze deeply only where a verified workflow exists.**

The tool must never generate a specialist filing-ready reply merely because it recognizes a GST form.

Every classified notice gets one of these support levels:

- `DEEP_WORKFLOW` — a tested workflow exists; structured analysis + reviewable draft may be produced.
- `TRIAGE_ONLY` — form/proceeding is recognized, but no deep workflow exists yet; produce identification, deadline/preflight checks, evidence checklist, risks, and CA escalation only.
- `UNKNOWN` — classification is uncertain; do not guess a workflow or reply form.

---

## 2. Revised High-Level Architecture

```text
GST PDF / Document
        ↓
Document Extraction
        ↓
Focused Notice Classification (LLM — one focused call)
        ↓
Python Taxonomy Validation (final NoticeClassification;
                             authoritative SupportLevel)
        ↓
Practical Preflight (authority / identifiers / dates / hearing /
                     attachments / arithmetic signals — EVERY notice)
        ↓
SUPPORT GATE
   ┌─────────────────────────┬───────────────────────────────────┐
   │ DEEP_WORKFLOW           │ TRIAGE_ONLY                       │
   ↓                         ↓                                   │
Workflow Registry           Fact Extraction / Preflight          │
   ↓                         (incl. deadline + arithmetic checks) │
Fact Engine                 ↓                                   │
   ↓                        Deterministic Triage Renderer        │
Deadline / Arithmetic       (structured classification + facts   │
(Python engines)             + templates — NO LLM drafting)      │
   ↓                         ↓                                   │
Reasoning / Drafting (LLM)                                       │
   ↓                                                             │
Validation Engine (Python)                                       │
   │                                                             │
   └─────────────────────────┬───────────────────────────────────┘
                             ↓
                    CA Review / Edit / Approve
                             ↓
        Filing Record + Acknowledgement (future case lifecycle)
```

Rules of this diagram:

- There is exactly ONE classification stage pair: the focused LLM classification call followed by Python taxonomy validation. There is no second, undefined proceeding classifier after the support gate.
- Deadline/preflight capability is NOT exclusive to `DEEP_WORKFLOW`: Practical Preflight runs for every notice before the support gate, and the `TRIAGE_ONLY` path includes deadline and arithmetic checks plus preflight fact extraction.
- The `TRIAGE_ONLY` path renders deterministically from structured data; it introduces no specialist free-form LLM drafting call.

**Phase 2 LLM call surfaces (complete list):** every Phase 2 LLM call goes through `modules/llm_client.py` and the existing LLM router. The only expected surfaces are:

1. notice classification (one focused call)
2. structured fact extraction
3. deep-workflow reasoning/drafting

`TRIAGE_ONLY` rendering adds NO additional free-form LLM drafting call.

---

## 3. GST Notice Taxonomy v1

This is a **product taxonomy**, not a claim that GST has exactly 15 notice types. Forms and portal workflows change over time. The taxonomy must be versioned and extensible.

### 3.1 Return / Return-Compliance

- `GSTR-3A` — non-filer / return-default communication.
- `DRC-01B` — automated liability mismatch between GSTR-1/IFF and GSTR-3B/3BQ.
- `DRC-01C` — automated ITC mismatch between GSTR-2B/2BQ and GSTR-3B/3BQ.

### 3.2 Registration

- `REG-03` — request for clarification/additional information/documents in registration/amendment/cancellation application context.
- `REG-17` — show-cause notice for proposed cancellation of registration.
- `REG-23` — notice relating to proposed rejection of revocation application.

### 3.3 Composition

- `CMP-05` — composition eligibility/show-cause proceeding.

### 3.4 GST Practitioner

- `PCT-03` — GST practitioner misconduct / disqualification-related proceeding.

### 3.5 Refund

- `RFD-08` — notice proposing rejection of refund claim; reply workflow uses the corresponding refund-reply mechanism.

### 3.6 Assessment / Scrutiny

- `ASMT-02` — additional information/clarification/documents for provisional assessment.
- `ASMT-10` — discrepancy notice after scrutiny of return.
- `ASMT-14` — show-cause notice for best-judgment assessment of an unregistered taxable person.

### 3.7 Audit

- `ADT-01` — departmental audit notice under the audit framework.

### 3.8 Demand / Adjudication

- `DRC-01A` — pre-show-cause / pre-demand intimation where applicable.
- `DRC-01` — formal demand/show-cause summary/process; issue family must be classified separately (ITC, RCM, output tax, fraud/suppression, valuation, classification, etc.).

### 3.9 Enforcement / Movement of Goods

- MOV-series / Section 129 detention-related communications.
- Section 130 confiscation-related notices/orders are recognized but remain outside the initial five deep workflows unless explicitly added to the spec.

**Section 130 modeling rule (Phase 2):** Section 130 is NOT a `NoticeForm` registry entry. A Section-130-only proceeding in Phase 2 classifies as:

```text
NoticeForm      = UNKNOWN
NoticeFamily    = ENFORCEMENT
ProceedingType  = UNKNOWN
SupportLevel    = TRIAGE_ONLY
```

Section 130 itself is captured later as a cited section with provenance in fact extraction — never as a fabricated form identifier.

### 3.10 Revision

- `RVN-01` — revision proceeding form/category (recognized taxonomy item; deep workflow deferred until officially mapped and tested).

---

## 4. Current Deep-Workflow Scope (unchanged)

The following five remain Phase 2 deep workflows:

1. `GST_SEC73_ITC`
2. `GST_SEC73_GENERAL`
3. `GST_SEC73_RCM`
4. `GST_SEC74_FRAUD`
5. `GST_SEC129_ENFORCE`

Everything else in Taxonomy v1 is initially `TRIAGE_ONLY` until a workflow is specified, tested, and promoted to `DEEP_WORKFLOW`.

This prevents false confidence while allowing the product to understand real-world notice diversity.

---

## 5. New Classification Concepts

Add the following architecture concepts before workflow code.

### 5.1 `NoticeFamily`

Suggested values:

- `RETURN_COMPLIANCE`
- `REGISTRATION`
- `COMPOSITION`
- `GST_PRACTITIONER`
- `REFUND`
- `ASSESSMENT_SCRUTINY`
- `AUDIT`
- `DEMAND_ADJUDICATION`
- `ENFORCEMENT`
- `REVISION`
- `UNKNOWN`

### 5.2 `NoticeForm`

Recognized values for Taxonomy v1:

- `GSTR_3A`
- `CMP_05`
- `REG_03`
- `REG_17`
- `REG_23`
- `PCT_03`
- `RFD_08`
- `ASMT_02`
- `ASMT_10`
- `ASMT_14`
- `ADT_01`
- `RVN_01`
- `DRC_01A`
- `DRC_01`
- `DRC_01B`
- `DRC_01C`
- `MOV_SERIES`
- `UNKNOWN`

Do not encode every GST form in this enum in Phase 2. Add forms by versioned spec update.

Section 130 is intentionally NOT a value of this enum — see §3.9.

### 5.3 `SupportLevel`

- `DEEP_WORKFLOW`
- `TRIAGE_ONLY`
- `UNKNOWN`

### 5.4 `NoticeClassification`

Final contract — fields:

- `notice_family: NoticeFamily`
- `notice_form: NoticeForm`
- `proceeding_type: ProceedingType` (existing deep-workflow enum; `UNKNOWN` when no deep workflow exists)
- `support_level: SupportLevel`
- `confidence: ClassificationConfidence`
- `classification_reasons: List[str]`

`sections_cited` and `rules_cited` are deliberately NOT fields of `NoticeClassification`. Cited sections/rules belong to structured fact extraction with provenance (Step 6), not to classification.

`classification_reasons` exists for audit/debug/explainability and contains concise, marker-based reasons (e.g. `'form marker "DRC-01" found'`, `'ITC marker "16(2)(aa)" found'`).

Important: **Form recognition and deep-workflow classification are separate.** `SupportLevel` is assigned by Python taxonomy validation (§9), never by the LLM alone.

Example:

```text
NoticeForm = ASMT_10
NoticeFamily = ASSESSMENT_SCRUTINY
ProceedingType = UNKNOWN
SupportLevel = TRIAGE_ONLY
```

That is a valid result and must not trigger a DRC-06 draft.

### 5.5 `ClassificationConfidence`

Qualitative only — numeric/percentage confidence is NOT used:

- `HIGH`
- `MEDIUM`
- `LOW`
- `UNKNOWN`

---

## 6. Practical CA Preflight Layer

Before workflow reasoning, every notice should be checked for the following.

### 6.1 Notice Identity

Extract:

- form / communication type
- reference number / case ID
- RFN if present
- DIN if present
- notice date
- issuing office
- issuing officer name/designation
- taxpayer name
- GSTIN
- tax period / FY
- sections and rules cited

### 6.2 Communication Identifier / Authenticity Signal

Do **not** implement the simplistic rule `DIN missing = invalid`.

Presence signals are modeled separately from verification actions. The presence signal is:

`CommunicationIdentifierStatus` (Phase 2 Step 2.5 enum):

- `RFN_PRESENT`
- `DIN_PRESENT`
- `BOTH_PRESENT`
- `NEITHER_FOUND`
- `UNKNOWN`

Portal verification is a separate boolean/result, never a member of this status:

- `portal_verification_required: bool`

This preflight boolean is identifier-driven and is distinct from the deadline-driven `DeadlineResult.portal_verification_required` built in Step 2, which remains unchanged (§6.5).

For common-portal-generated communications carrying a verifiable RFN, absence of a separate DIN must not automatically invalidate the communication.

The tool may say:

> "RFN/DIN authenticity path requires verification."

It must not declare a notice legally invalid unless an authoritative rule engine supports that conclusion.

### 6.3 Authority / Jurisdiction Check

Extract:

- officer name
- designation
- office/commissionerate
- jurisdiction stated in notice

`AuthorityDetailsStatus` (Phase 2 Step 2.5 enum):

- `PRESENT`
- `PARTIAL`
- `MISSING`
- `UNKNOWN`

Legal competence verification remains a separate boolean/result:

- `authority_verification_required: bool`

Phase 2 does not contain a legal knowledge database capable of conclusively deciding officer jurisdiction/competence. Phase 2 extracts authority information; it does not conclusively decide competence. The tool flags the issue for CA verification rather than inventing legal validity.

### 6.4 Statutory Basis

Extract every cited:

- section
- sub-section
- rule
- notification/circular expressly cited in the notice

Do not add external legal authorities at this stage unless retrieved from a verified legal source.

### 6.5 Procedural Dates

Capture separately:

- notice date
- service date
- response period text
- explicitly stated due date (if printed)
- hearing date/time

The existing deterministic deadline engine remains responsible for date arithmetic and is NOT modified: `domain/deadline_engine.py` and `DeadlineResult` keep their Step 2 signatures. The engine continues to calculate deadlines only from structured date inputs (notice date, service date, response period text).

**Stated-due-date rule:** an explicitly printed due date is an `ExtractedFact` / preflight datum. It is NOT collapsed into a calculated deadline and NOT fed into the engine as a substitute for structured inputs.

Future presentation must support:

- `NOTICE_STATED_DUE_DATE` — the date the notice itself prints
- `CALCULATED_DEADLINE` — the engine's independently calculated deadline
- both, when both are available
- a warning when both are available and conflict
- `DEADLINE_NOT_CONFIRMABLE` when neither can be safely established

### 6.6 Attachments / Annexures

Record whether the notice references:

- annexures
- reconciliation statements
- inspection reports
- relied-upon documents
- worksheets/calculation sheets

If referenced but absent from uploaded documents → evidence gap.

### 6.7 Arithmetic / Computation Check

Create a deterministic arithmetic layer later in Phase 2.

Examples:

- tax + interest + penalty = stated total
- CGST + SGST = total tax
- percentage calculations
- GSTR-3B minus GSTR-2B mismatch

Output statuses — `ArithmeticStatus` enum (Phase 2 Step 2.5):

- `PASS`
- `MISMATCH`
- `INSUFFICIENT_DATA`

The LLM must never be the final authority for arithmetic.

The full `ArithmeticResult` model is NOT created in Step 2.5 — that contract belongs to the Arithmetic Engine step (Step 7).

---

## 7. Practical CA Handling Sequence

The system's working-paper flow should mirror professional handling:

1. Identify form / proceeding.
2. Check communication identifier/authenticity signals (RFN/DIN/portal verification).
3. Extract issuing authority and flag jurisdiction/competence for verification where needed.
4. Extract sections/rules and departmental allegations.
5. Identify reason(s) for notice.
6. Calculate/verify deadline deterministically.
7. Check arithmetic and demand computation.
8. Identify required evidence and missing documents.
9. Identify required reconciliations/annexures.
10. Retrieve verified legal material when that subsystem exists; until then mark `CA LEGAL RESEARCH REQUIRED`.
11. Generate working paper.
12. Generate conditional/reviewable draft only for supported deep workflows.
13. Python validation before display.
14. CA edits/approves.
15. Record filing date, portal acknowledgement/reference and final submitted documents when case-management persistence is introduced.

---

## 8. Case/File Lifecycle (future-ready, not fully implemented in Phase 2)

The architecture must anticipate:

```text
Notice Received
→ Analysis
→ Evidence Requested
→ Evidence Added
→ Draft Prepared
→ CA Reviewed
→ Reply Filed
→ Acknowledgement Saved
→ Hearing / Order
→ Further Action
```

Phase 2 remains stateless in the UI, but future persistent Case models must store:

- original notice
- supporting evidence
- draft versions
- final filed reply
- annexures
- filing timestamp
- acknowledgement / ARN / portal reference
- hearing/order events

Do not build the database in Phase 2.

---

## 9. Revised Classifier Contract

Classification is one stage with two parts and one final output: `NoticeClassification`.

**Part A — Focused LLM classification call (exactly one LLM call, routed through `modules/llm_client.py` and the existing LLM router):**

The LLM identifies:

1. apparent `NoticeForm`
2. apparent `NoticeFamily`
3. a deep-workflow `ProceedingType` candidate — only if supported by markers (e.g. "DRC-01" + "16(2)(aa)" → `GST_SEC73_ITC` candidate)
4. `classification_reasons` (concise, marker-based)
5. `confidence` (`ClassificationConfidence`)

The LLM MUST NOT independently decide whether an unsupported notice has a `DEEP_WORKFLOW`, and must never force an unsupported notice into one of the five deep workflows.

**Part B — Python taxonomy validation / registry (deterministic):**

- Validates the apparent form/family against Taxonomy v1 and the registry.
- Is authoritative for `SupportLevel`: `DEEP_WORKFLOW` only when the validated form/proceeding maps to a registered, production-ready workflow (§10 guardrail); otherwise `TRIAGE_ONLY`; classification uncertainty → `UNKNOWN`.
- Produces the final `NoticeClassification`.

The final `NoticeClassification` object exists only after Part B completes.

Examples:

```text
DRC-01 + Section 73 + 16(2)(aa)/Rule 36(4)
→ DRC_01 / DEMAND_ADJUDICATION / GST_SEC73_ITC / DEEP_WORKFLOW
  (confidence HIGH; reasons: marker "DRC-01", marker "16(2)(aa)")

DRC-01 + Section 73 + RCM/9(3)
→ DRC_01 / DEMAND_ADJUDICATION / GST_SEC73_RCM / DEEP_WORKFLOW
  (confidence HIGH; reasons: marker "DRC-01", marker "9(3)")

ASMT-10
→ ASMT_10 / ASSESSMENT_SCRUTINY / UNKNOWN / TRIAGE_ONLY

REG-17
→ REG_17 / REGISTRATION / UNKNOWN / TRIAGE_ONLY

Section 130 only (no Section 129/MOV markers)
→ UNKNOWN / ENFORCEMENT / UNKNOWN / TRIAGE_ONLY
```

---

## 10. Revised Workflow Registry Contract

The five deep workflows remain deterministic Python definitions.

`WorkflowDefinition` fields:

- `proceeding_type: ProceedingType`
- `required_facts: List[str]`
- `evidence_requirements: List[str]`
- `issue_types: List[str]`
- `default_severity: IssueSeverity`
- `output_structure: List[str]`
- `special_rules: List[str]`

Default severities:

- GST_SEC73_ITC → MEDIUM
- GST_SEC73_GENERAL → MEDIUM
- GST_SEC73_RCM → MEDIUM
- GST_SEC74_FRAUD → CRITICAL
- GST_SEC129_ENFORCE → HIGH

Severity escalation:

Workflow default severity and deadline urgency are computed independently. Overall attention becomes `CRITICAL` when:

- the workflow default severity is `CRITICAL`; OR
- the deadline status is `CRITICAL`; OR
- the deadline status is `PASSED`.

Consequence: a Section 129 notice may correctly show workflow severity `HIGH`, deadline urgency `CRITICAL`, and overall attention `CRITICAL` when its deadline is within the 7-day CRITICAL window or has passed. This is the expected NOTICE_3 outcome and is not a contradiction.

Special rules guardrail:

`special_rules` is a declarative `List[str]` — never decorative prompt text. A workflow cannot be considered production-ready `DEEP_WORKFLOW` until every safety-critical special rule has either:

- (a) a corresponding deterministic Validation Engine check, or
- (b) an explicit mandatory CA-review gate.

Registry contains exactly five entries in Phase 2. `UNKNOWN` has no workflow.

### 10.1 Current-Law Safety Decisions Governing the Five Workflows

Recorded architectural decisions (August 2026):

**1. Section 73 / Section 74 temporal scope.**

Current CGST Sections 73 and 74 apply to determination pertaining to periods up to Financial Year 2023-24. The existing five Phase-2 workflows remain valid for notices that expressly invoke Sections 73 or 74. They must NOT be treated as substitutes for Section 74A.

For a DRC-01 expressly invoking Section 74A:

```text
NoticeForm      = DRC_01
NoticeFamily    = DEMAND_ADJUDICATION
ProceedingType  = UNKNOWN
SupportLevel    = TRIAGE_ONLY
```

until a dedicated Section-74A workflow is specified and tested.

**Guardrail:** NEVER silently map Section 74A to `GST_SEC73_*` or `GST_SEC74_FRAUD`.

**2. Section 129 penalty.**

Remove the historical assumption "Penalty = 100% of tax" from workflow facts/issues/special rules. The workflow must extract the penalty proposed in the notice as a fact. Any statutory penalty computation belongs to the future deterministic arithmetic/legal-rule layer. Do not hardcode a penalty percentage into `WorkflowDefinition`.

**3. Section 129 seven-day rule.**

Do NOT define "taxpayer reply deadline = 7 days from service" as a universal workflow rule. The architecture must distinguish:

- statutory officer notice/order timelines;
- statutory payment/conclusion windows;
- an explicitly stated taxpayer response/hearing date.

The Deadline Engine receives only structured date inputs. A taxpayer reply deadline may be shown only when it is explicitly stated or safely calculated under an approved deadline contract.

**4. MOV-09.**

Record explicitly: MOV-09 is an order issued by the department in the enforcement sequence. It must NEVER be represented as "taxpayer reply in MOV-09". A Section-129 workflow output must therefore say "reviewable enforcement response/submission appropriate to the actual notice/form" and must not hardcode MOV-09 as a taxpayer reply form.

### 10.2 Workflow Contract Rules

1. `WorkflowDefinition` content is a CASE-HANDLING REQUIREMENT set, not a legal conclusion.
2. `required_facts` means facts the downstream system should seek/extract. It does NOT mean the fact is true.
3. `evidence_requirements` means evidence the CA may need to collect/review. Presence is not assumed.
4. `issue_types` identify questions to investigate. They do NOT state the taxpayer is liable.
5. `special_rules` are safety invariants. Every safety-critical special rule must later map to deterministic validation OR a mandatory CA-review gate.
6. No legal proposition in a workflow may be treated as permanently current law merely because it appears in `WorkflowDefinition`.
7. Time-sensitive legal rules/rates/limits belong eventually in the verified, versioned Legal Knowledge / Rule subsystem.

### 10.3 Authoritative Five-Workflow Contracts (Phase 2 Step 5)

The following five contracts are the AUTHORITATIVE content for Phase 2 Step 5. Implement each `WorkflowDefinition` verbatim from these lists. Do not invent, add, drop, or reinterpret content.

**Contract 1 — `GST_SEC73_ITC`**

- `proceeding_type`: `GST_SEC73_ITC`
- `default_severity`: `MEDIUM`

`required_facts`:

1. "ITC claimed in GSTR-3B (amount)"
2. "ITC reflected in GSTR-2B (amount)"
3. "Difference between GSTR-3B and GSTR-2B (INFERRED)"
4. "FY / tax period"
5. "Interest proposed"

`evidence_requirements`:

1. "GSTR-2B for all months in the relevant period"
2. "GSTR-3B ITC tables for the relevant period"
3. "Invoice-level ITC reconciliation"
4. "Supplier GSTR-1 filing status / supporting filing evidence where relevant"
5. "Payment proof to suppliers where relevant to the claimed ITC eligibility"

`issue_types`:

1. "ITC_MISMATCH"
2. "SUPPLIER_DEFAULT"
3. "INTEREST_COMPUTATION"

`output_structure`:

1. "Working paper"
2. "ITC reconciliation table"
3. "Reviewable DRC-06 draft"

`special_rules`:

1. "A GSTR-3B versus GSTR-2B mismatch is not by itself proof that the ITC is legally ineligible."
2. "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts."
3. "Never assume invoices, receipt of goods or services, supplier compliance, or payment to suppliers unless supported by evidence."
4. "Final ITC eligibility is a legal/factual conclusion requiring evidence and CA review."

**Contract 2 — `GST_SEC73_GENERAL`**

- `proceeding_type`: `GST_SEC73_GENERAL`
- `default_severity`: `MEDIUM`

`required_facts`:

1. "Tax / liability declared in GSTR-1"
2. "Tax / liability discharged in GSTR-3B"
3. "Difference between GSTR-1 and GSTR-3B (INFERRED)"
4. "FY / tax period"
5. "Interest proposed"

`evidence_requirements`:

1. "Monthly GSTR-1 and GSTR-3B for the relevant period"
2. "GSTR-9 annual return where applicable/relevant"
3. "Credit notes and amendments relevant to the mismatch"

`issue_types`:

1. "SHORT_PAYMENT"
2. "GSTR_MISMATCH"
3. "INTEREST_COMPUTATION"

`output_structure`:

1. "Working paper"
2. "Month-wise GSTR-1 versus GSTR-3B reconciliation"
3. "Reviewable DRC-06 draft"

`special_rules`:

1. "A return mismatch is not by itself an admission of tax short-payment."
2. "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts."
3. "Credit notes, amendments, timing differences and other reconciliation items must be checked before reaching a liability conclusion."
4. "The workflow identifies reconciliation requirements; it does not itself establish legal liability."

**Contract 3 — `GST_SEC73_RCM`**

- `proceeding_type`: `GST_SEC73_RCM`
- `default_severity`: `MEDIUM`

`required_facts`:

1. "Service / supply category alleged to attract RCM"
2. "Value of services / supplies alleged to be subject to RCM"
3. "RCM tax alleged as unpaid or short-paid"
4. "FY / tax period"
5. "Interest proposed"

`evidence_requirements`:

1. "Invoices / engagement documents for suppliers alleged to be RCM-covered"
2. "Form 26AS / TDS data where the department relies on it"
3. "GSTR-3B table 3.1(d) for the relevant period"
4. "Vendor-wise ledger / service-category reconciliation where required"

`issue_types`:

1. "RCM_LIABILITY"
2. "ITC_REVERSAL"
3. "INTEREST_COMPUTATION"

`output_structure`:

1. "Working paper"
2. "RCM supplier / service-category reconciliation"
3. "Reviewable DRC-06 draft with conditional RCM submissions"

`special_rules`:

1. "Do not assume that every payment appearing under a TDS or professional-services category is subject to GST reverse charge."
2. "Service category and RCM applicability require verification from underlying documents and current legal sources."
3. "Form 26AS or TDS data may be evidentiary input but is not by itself conclusive proof of GST RCM liability."
4. "Do not assume ITC availability, revenue neutrality, or entitlement without verifying the taxpayer's facts and applicable law."

**Contract 4 — `GST_SEC74_FRAUD`**

- `proceeding_type`: `GST_SEC74_FRAUD`
- `default_severity`: `CRITICAL`

`required_facts`:

1. "Basis of fraud / wilful-misstatement / suppression allegation"
2. "Turnover, tax, refund or ITC amount alleged by the department (ALLEGED unless independently established)"
3. "FY / tax period"
4. "Penalty proposed in the notice (ALLEGED)"
5. "Limitation / extended-period basis invoked in the notice"

`evidence_requirements`:

1. "Books of accounts for the relevant period"
2. "Relevant bank statements"
3. "Filed GST returns for the relevant period"
4. "Correspondence with the department"
5. "Underlying third-party / RERA / external-source documents where relied upon by the department"

`issue_types`:

1. "FRAUD_ALLEGATION"
2. "SUPPRESSION"
3. "PENALTY_COMPUTATION"
4. "LIMITATION"

`output_structure`:

1. "Urgent working paper"
2. "Senior-review / escalation note"
3. "Conditional reviewable DRC-06 draft"

`special_rules`:

1. "Fraud, wilful misstatement and suppression must remain departmental allegations unless established by evidence."
2. "Never state that fraud is present or absent as an established fact without evidentiary support."
3. "Preserve the provenance of third-party or external data relied upon by the department."
4. "Mandatory senior CA / advocate review is required before filing."
5. "This workflow applies only where the notice expressly invokes Section 74; it must not be used as a substitute for Section 74A."

**Contract 5 — `GST_SEC129_ENFORCE`**

- `proceeding_type`: `GST_SEC129_ENFORCE`
- `default_severity`: `HIGH`

`required_facts`:

1. "Goods description"
2. "Vehicle / conveyance number"
3. "Detention / seizure date"
4. "Section 129 notice date and service date where available"
5. "Penalty amount proposed in the notice"
6. "Value of goods and tax payable on the goods where stated and relevant to penalty computation"
7. "Whether the owner of the goods has come forward, where relevant and determinable"
8. "Explicit hearing / payment / response date stated in the notice or order"
9. "Order date / current enforcement status if an order has already been issued"

`evidence_requirements`:

1. "Tax invoice for the goods"
2. "E-Way Bill, or evidence explaining its absence where available"
3. "Detention / seizure order, including MOV-06 where issued"
4. "Section 129 notice and any subsequent order / MOV documents actually issued"
5. "GR / LR / GRN / delivery or transport documents relevant to movement of goods"

`issue_types`:

1. "EWAY_BILL"
2. "DETENTION"
3. "PENALTY_COMPUTATION"
4. "PROCEDURAL_TIMELINE"
5. "SECTION_130_RISK"

`output_structure`:

1. "URGENT enforcement working paper"
2. "Enforcement chronology / deadline alert"
3. "Penalty computation verification checklist"
4. "Reviewable response / submission appropriate to the actual notice or proceeding"

`special_rules`:

1. "Never assume the tax invoice is valid; invoice validity remains REQUIRES_VERIFICATION until supported by evidence."
2. "Never invent a reason for a missing or defective E-Way Bill."
3. "Do not hardcode a 100% penalty assumption; extract the proposed penalty and defer statutory computation to the deterministic arithmetic/legal-rule layer."
4. "Do not treat the Section 129 seven-day statutory notice/order timeline as a universal taxpayer reply deadline."
5. "MOV-09 is a departmental order and must never be described as the taxpayer's reply form."
6. "A Section-130-only proceeding does not use this deep workflow and remains TRIAGE_ONLY until a separate workflow exists."
7. "Active detention/seizure requires urgent CA escalation, but deadline status must come from the deterministic Deadline Engine and explicit procedural dates."

---

## 11. Triage-Only Output Contract

A TRIAGE_ONLY result is produced from structured classification + extracted facts + deterministic preflight/template rendering. It does NOT use a specialist free-form legal drafting call, and introduces NO additional LLM surface.

It may display:

- notice/form identification
- authority details
- sections/rules explicitly extracted
- stated/calculated deadline information
- hearing information
- amounts
- departmental allegations
- documents explicitly requested/referenced by the notice
- missing attachments/annexures
- CA escalation message

It MUST NOT invent:

- additional evidence requirements
- legal defences
- reply forms
- filing-ready replies
- legal conclusions

---

## 12. Current Taxonomy-to-Deep-Workflow Mapping

| Recognized form/proceeding | Support |
|---|---|
| DRC-01 + Sec 73 + ITC markers | DEEP → GST_SEC73_ITC |
| DRC-01 + Sec 73 + general short-payment markers | DEEP → GST_SEC73_GENERAL |
| DRC-01 + Sec 73 + RCM markers | DEEP → GST_SEC73_RCM |
| DRC-01 + Sec 74 fraud/suppression markers | DEEP → GST_SEC74_FRAUD |
| Section 129 / MOV detention | DEEP → GST_SEC129_ENFORCE |
| GSTR-3A | TRIAGE_ONLY |
| CMP-05 | TRIAGE_ONLY |
| REG-03 | TRIAGE_ONLY |
| REG-17 | TRIAGE_ONLY |
| REG-23 | TRIAGE_ONLY |
| PCT-03 | TRIAGE_ONLY |
| RFD-08 | TRIAGE_ONLY |
| ASMT-02 | TRIAGE_ONLY |
| ASMT-10 | TRIAGE_ONLY |
| ASMT-14 | TRIAGE_ONLY |
| ADT-01 | TRIAGE_ONLY |
| RVN-01 | TRIAGE_ONLY |
| DRC-01A | TRIAGE_ONLY until deep pre-SCN workflow exists |
| DRC-01B | TRIAGE_ONLY initially; likely future high-priority workflow |
| DRC-01C | TRIAGE_ONLY initially; likely future high-priority workflow |
| Section 130-only (NoticeForm `UNKNOWN`, family `ENFORCEMENT`, proceeding `UNKNOWN` — §3.9) | TRIAGE_ONLY |
| DRC-01 expressly invoking Section 74A | TRIAGE_ONLY — never mapped to `GST_SEC73_*` or `GST_SEC74_FRAUD` (§10.1) |

Section 130 appears in this table as a proceeding-marker combination only. It is NOT a `NoticeForm` registry entry (§3.9, §5.2) and no workflow treats it as one.

---

## 13. Revised Phase 2 Implementation Sequence

Completed:

- Step 1 — domain models ✅
- Step 2 — deadline engine ✅

**Pause old Step 3. Replace remaining sequence with:**

New Phase 2 components follow the v1 §6 folder conventions: pure-Python no-LLM components live in `domain/`; workflow definitions in `workflows/gst/`; prompts in `prompts/`; tests in `tests/`. Exact file names are assigned at each step.

### Step 2.5 — Contract update for taxonomy/classification

- Update `domain/models.py` (additive only) with the enums approved by this spec:
  - `NoticeFamily`
  - `NoticeForm`
  - `SupportLevel`
  - `ClassificationConfidence`
  - `CommunicationIdentifierStatus`
  - `AuthorityDetailsStatus`
  - `ArithmeticStatus`
- Add the `NoticeClassification` dataclass with exactly the §5.4 fields.
- Do NOT create `ArithmeticResult` in this step — that contract belongs to the Arithmetic Engine step (Step 7, §6.7).
- Do NOT modify `NoticeAnalysis` in this step — it is extended only during integration, once `NoticeClassification`, `PreflightResult` and `ArithmeticResult` contracts actually exist.
- Do NOT modify `domain/deadline_engine.py` or `DeadlineResult` (§6.5).
- No LLM, no app wiring.
- Add unit tests for enum/object construction.

### Step 3 — GST Taxonomy Registry

- Static mapping of recognized forms → family + authoritative support level.
- Exactly the Taxonomy v1 forms.
- No LLM.
- Tests verify coverage, that no unsupported form is marked deep, and that Section 130 is not a registry form entry.

### Step 4 — Notice Classifier

- One focused LLM call (routed through `modules/llm_client.py` and the LLM router) + Python validation, exactly per §9.
- The LLM returns the apparent classification; Python validation produces the final `NoticeClassification`.
- Must classify the four fixtures to their deep workflows.
- Must also be testable with synthetic ASMT-10 / REG-17 / DRC-01B / DRC-01C / Section-130-only text and return TRIAGE_ONLY rather than forcing a deep workflow.

**Step 4 follow-up (before Step 5 code):** add/verify an offline classifier safety test:

```text
DRC-01 + Section 74A
    → NoticeForm.DRC_01
    → NoticeFamily.DEMAND_ADJUDICATION
    → ProceedingType.UNKNOWN
    → SupportLevel.TRIAGE_ONLY
```

No Section-74A deep type may be invented in Phase 2.

### Step 5 — Deep Workflow Registry

- Implement exactly five `WorkflowDefinition` objects.
- The per-workflow content of `required_facts`, `evidence_requirements`, `issue_types`, `output_structure` and `special_rules` is defined authoritatively in §10.3. Implement those lists verbatim; do not invent content.
- Registry keyed by `ProceedingType`.
- No workflow for `UNKNOWN`.
- No LLM.
- Each workflow must satisfy the §10 special-rules guardrail before it is considered production-ready.

### Step 6 — Fact Engine

- Structured fact extraction with provenance and draft permissions.
- Preserve explicitly stated due dates, RFN/DIN, authority, sections/rules, amounts, hearing details and annexure references as facts.

### Step 7 — Preflight + Arithmetic Engine

- Pure Python checks where deterministic.
- Arithmetic consistency.
- Completeness signals.
- Identifier/authenticity status from extracted RFN/DIN signals via `CommunicationIdentifierStatus` (no unsupported invalidity conclusion).
- This step defines the full `ArithmeticResult` contract (§6.7); Step 2.5 adds only the `ArithmeticStatus` enum.

### Step 8 — Validation Engine

- Fact provenance rules.
- Deadline confidence.
- Arithmetic mismatch warnings.
- Supported-workflow gate.
- No specialist draft when support level != DEEP_WORKFLOW.

### Step 9 — Reasoning / Draft Pipeline

- Workflow-specific structured prompt (deep workflows only).
- LLM writes narrative and draft only after code supplies classification, facts, deadline, workflow, arithmetic and evidence requirements.
- TRIAGE_ONLY rendering has no LLM drafting call (§11).

### Step 10 — App Integration + Regression

- Preserve the legacy path during migration ONLY as a temporary fallback while the structured pipeline is being proven.
- Render structured results.
- Run all four existing fixtures.
- Add synthetic taxonomy recognition tests.
- **Legacy retirement:** after all four regression fixtures pass through the structured Phase 2 pipeline, the legacy raw-dict / mega-prompt path is retired in a dedicated cleanup step. Do not maintain two permanent architectures.

---

## 14. Near-Term Workflow Expansion Priority (after the five deep workflows are stable)

Recommended next deep workflows:

1. DRC-01C — ITC mismatch return-compliance response
2. DRC-01B — outward-liability mismatch response
3. ASMT-10 — scrutiny discrepancy + ASMT-11 response workflow
4. REG-17 — cancellation SCN response
5. RFD-08 — refund-rejection response
6. GSTR-3A — non-filer remediation
7. ADT-01 — audit readiness/evidence workflow

Do not implement this expansion until the Phase 2 architecture is stable and CA pilot feedback supports prioritization.

---

## 15. Architectural Guardrails

1. No notice form is automatically equivalent to a deep workflow.
2. No missing DIN alone may be treated as invalidity without considering RFN/common-portal context and current authoritative rules.
3. No unsupported notice may be forced into DRC-06 or another reply format.
4. All deadlines and arithmetic are code-controlled.
5. Every material fact needs provenance.
6. Allegation is not fact.
7. Unknown facts cannot become favourable taxpayer facts in drafting.
8. Legal authorities require verified sources; otherwise CA research is required.
9. Every deep workflow is versioned, tested and registered explicitly.
10. Filing/acknowledgement is part of the eventual case lifecycle, not an afterthought.
11. The classification stage is exactly one pair — focused LLM classification followed by Python taxonomy validation. There is no second, undefined proceeding classifier after the support gate.
12. Every Phase 2 LLM call goes through `modules/llm_client.py` and the existing LLM router. The only Phase 2 LLM surfaces are notice classification, structured fact extraction, and deep-workflow reasoning/drafting. TRIAGE_ONLY rendering adds no free-form LLM drafting call.
13. A workflow cannot be considered production-ready `DEEP_WORKFLOW` until every safety-critical special rule has a deterministic Validation Engine check or a mandatory CA-review gate.
14. A notice-stated due date is data, never a calculated deadline; stated and calculated dates are presented separately, and a conflict between them is surfaced as a warning.
15. Presence signals and verification actions are modeled separately (`CommunicationIdentifierStatus` vs `portal_verification_required`; `AuthorityDetailsStatus` vs `authority_verification_required`).
16. A notice expressly invoking Section 74A must never be silently mapped to `GST_SEC73_*` or `GST_SEC74_FRAUD`; it remains TRIAGE_ONLY until a dedicated Section-74A workflow is specified and tested (§10.1).

---

## 16. Current External Verification Notes (August 2026)

These notes informed v1.1 and should be re-verified when legal sources are versioned into the product:

- GST portal documentation confirms case-based notice/order viewing and reply handling rather than an isolated-PDF model.
- CBIC Circular 249/06/2025-GST clarifies that common-portal GST communications carrying verifiable RFN do not require separate DIN quotation merely to duplicate the same unique identity.
- Official GST portal materials document DRC-01B as liability mismatch (GSTR-1/IFF vs GSTR-3B/3BQ) and DRC-01C as ITC mismatch (GSTR-2B/2BQ vs GSTR-3B/3BQ).
- CBIC assessment/audit rules confirm distinct ASMT-02, ASMT-10, ASMT-14 and ADT-01 proceedings.
- CBIC refund rules confirm RFD-08 is a refund-rejection notice with a specific reply mechanism.

### 16.1 Current-Law Workflow Verification Notes (August 2026)

As verified in August 2026:

- Current CGST Sections 73 and 74 state that they apply to determination pertaining to periods up to FY 2023-24.
- Section 74A exists for later demand proceedings and is NOT yet a Phase-2 deep workflow.
- Current Section 129 no longer supports the historical static "100% penalty" assumption used in old v1.
- Current Section 129 contains statutory seven-day notice/order timing; this is not to be converted automatically into a taxpayer reply deadline.
- MOV-09 is treated as a departmental order, not a taxpayer reply form.
- Rule 142 continues to provide DRC-06 as the representation/reply mechanism for notices whose summary is uploaded in DRC-01, including current demand provisions.

These are architecture verification notes, NOT the future legal knowledge database. They must eventually come from versioned authoritative sources.

**This document does not itself become a legal knowledge database.** It defines architecture boundaries only.

---

*Document version: 1.1 — FINAL (2026-08-28), amended 2026-08-29 by Phase 2 Step 5A: authoritative five-workflow contracts added to §10 (§10.1 current-law safety decisions, §10.2 contract rules, §10.3 five contracts), Section-74A guardrail §15(16), current-law workflow verification notes §16.1, Step 4 Section-74A follow-up note and §12 mapping row. Authoritative for Phase 2 work from Step 2.5 onward. v1.0 remains historical and is not merged into this document.*
