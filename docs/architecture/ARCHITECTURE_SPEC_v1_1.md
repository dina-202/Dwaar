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
- The authoritative Fact Engine contract is defined in §17 (finalized by Phase 2 Step 6A).

### Step 7 — Preflight + Arithmetic Engine

- Pure Python checks where deterministic.
- Arithmetic consistency.
- Completeness signals.
- Identifier/authenticity status from extracted RFN/DIN signals via `CommunicationIdentifierStatus` (no unsupported invalidity conclusion).
- This step defines the full `ArithmeticResult` contract (§6.7); Step 2.5 adds only the `ArithmeticStatus` enum.

The authoritative Preflight + Arithmetic contract is defined in §18 (finalized by Phase 2 Step 7A).

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
- The specialist drafting LLM call is gated by `ValidationEngineResult.draft_eligibility`; `BLOCKED` forbids the call. The authoritative Step-9 gate is defined in §19.53 (Phase 2 Step 8A).

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

## 17. Fact Engine Contract (Phase 2 Step 6A — authoritative)

This section finalizes the deterministic Step 6 contract. It resolves the
Step 6 pre-implementation review gaps: input/output shape, Python-owned
status and draft permissions, provenance enforcement, malformed-output
handling, deduplication, derived-fact scope, workflow-required-fact
decoupling, and absence representation.

The Fact Engine is a high-risk boundary: a focused LLM extraction of
untrusted candidate facts, followed by deterministic Python normalization
and safety enforcement. The LLM is advisory for extraction; Python is
authoritative for structure, status, draft permission, provenance and IDs.

### 17.1 `FactType` — machine-readable fact category

New domain enum `FactType` (implemented additively in Step 6.1) with
exactly these members, using the repository enum-value convention
(lowercase member name):

```text
NOTICE_REFERENCE = "notice_reference"
NOTICE_DATE = "notice_date"
TAXPAYER_NAME = "taxpayer_name"
GSTIN = "gstin"

AUTHORITY_NAME = "authority_name"
AUTHORITY_DESIGNATION = "authority_designation"
AUTHORITY_OFFICE = "authority_office"
JURISDICTION_TEXT = "jurisdiction_text"

RFN = "rfn"
DIN = "din"

STATUTORY_SECTION = "statutory_section"
STATUTORY_RULE = "statutory_rule"
STATUTORY_NOTIFICATION = "statutory_notification"

TAX_PERIOD = "tax_period"

STATED_DUE_DATE = "stated_due_date"
HEARING_DETAILS = "hearing_details"

STATED_AMOUNT = "stated_amount"

DEPARTMENT_ALLEGATION = "department_allegation"

REQUESTED_DOCUMENT = "requested_document"
REFERENCED_ANNEXURE = "referenced_annexure"

DOCUMENT_DETAIL = "document_detail"

OTHER_NOTICE_FACT = "other_notice_fact"
```

`FactType` identifies WHAT KIND of information was extracted. It does NOT
decide whether the underlying legal proposition is true.

`DOCUMENT_DETAIL` is added by Phase 2 Step 8A; its authoritative definition
and `FactStatus` mapping are in §19.1 / §19.6. Step 8A also introduces the
closed `FactRole` semantic-role vocabulary (§19.2) and the additive
`ExtractedFact.fact_role` field (§19.3).

### 17.2 `ExtractedFact` additive change

Add fields, each with a default, so existing Step-1 constructors remain
backward compatible:

```text
fact_type: FactType = FactType.OTHER_NOTICE_FACT
fact_role: FactRole = FactRole.NONE          # added by Phase 2 Step 8A (§19.3)
```

Final conceptual contract:

```text
fact_id
claim
status
source_text
source_page
allowed_in_draft
fact_type
fact_role
```

No existing `ExtractedFact` field is removed or renamed. The implementation
places the additive fields last (`fact_type`, then `fact_role`) so
positional and keyword construction from Step 1 continues to work
unchanged. `FactRole` is authorized by §19.2.

### 17.3 Fact Engine input contract

```text
extract_facts(
    raw_text: str,
    classification: NoticeClassification
) -> List[ExtractedFact]
```

Step 6 receives the raw notice text plus the validated
`NoticeClassification`. It does NOT receive `WorkflowDefinition`.

Fact extraction is document-native and generic. Workflow requirements are
evaluated later against extracted facts (§17.14).

The same Fact Engine is used for `DEEP_WORKFLOW`, `TRIAGE_ONLY` and
`UNKNOWN`. A `UNKNOWN` classification does NOT prevent safe factual
extraction: the system may still preserve document-native facts from an
unclassified notice.

The Fact Engine must not promote support level and must not choose
workflows.

### 17.4 Fact Engine output contract

Step 6 returns:

```text
List[ExtractedFact]
```

No result wrapper is introduced in Step 6. Do NOT create
`FactEngineResult`, `PreflightResult` or `ArithmeticResult` in Step 6.

**Additive outcome channel (Phase 2 Step 7A):** the output contract above
remains the backward-compatible primary API. Step 7A adds an additive
outcome channel without changing `extract_facts`: a `FactExtractionStatus`
enum, a `FactExtractionResult` dataclass and a companion function
`extract_facts_with_status` (authoritative contract in §18.1–18.2). The
status channel exists so downstream preflight can distinguish successful
extraction (including a genuinely empty facts list) from partial or failed
extraction before drawing absence-based conclusions (§18.3).

### 17.5 LLM candidate contract

The focused extraction LLM call returns STRICT JSON only:

```json
{
  "facts": [
    {
      "fact_type": "notice_reference",
      "fact_role": "none",
      "claim": "Notice reference is ...",
      "source_text": "exact text copied from the notice",
      "source_page": 1
    }
  ]
}
```

Candidate fields are exactly:

```text
fact_type
fact_role
claim
source_text
source_page
```

Phase 2 Step 8A amends this candidate from four to five fields (§19.4):
`fact_role` uses the closed `FactRole` vocabulary (§19.2); `"none"` is the
default for facts whose role is not workflow-relevant.

The LLM must NOT output or control `fact_id`, `status` or
`allowed_in_draft` — those are Python-owned.

Python validates `fact_role` as a closed enum: an invalid role rejects the
candidate item. Role is never inferred later from claim text.

The LLM must NOT create:

- `INFERRED` calculations;
- `UNKNOWN` placeholder facts;
- legal conclusions;
- taxpayer-favourable assumptions.

### 17.6 Python owns `FactStatus`

The final `FactStatus` is assigned deterministically by Python from
`FactType`. The LLM may not supply or override it.

For these `FactType` members, final status is `FactStatus.CONFIRMED`
(meaning: the notice explicitly contains/states that information —
`CONFIRMED` does NOT mean the underlying legal allegation is correct):

```text
NOTICE_REFERENCE
NOTICE_DATE
TAXPAYER_NAME
GSTIN
AUTHORITY_NAME
AUTHORITY_DESIGNATION
AUTHORITY_OFFICE
JURISDICTION_TEXT
RFN
DIN
STATUTORY_SECTION
STATUTORY_RULE
STATUTORY_NOTIFICATION
TAX_PERIOD
STATED_DUE_DATE
HEARING_DETAILS
STATED_AMOUNT
REQUESTED_DOCUMENT
REFERENCED_ANNEXURE
DOCUMENT_DETAIL
```

Example: if a notice prints `"Penalty proposed: ₹5,00,000"`, the
document-native fact `"Notice proposes penalty of ₹5,00,000"` may be
`CONFIRMED`. It does NOT mean `"Taxpayer legally owes ₹5,00,000."`

For `DEPARTMENT_ALLEGATION`, final status is `FactStatus.ALLEGED`.
Examples: alleged ineligible ITC, fraud allegation, suppression allegation,
alleged unpaid tax, alleged short payment, alleged wrongful refund.
Departmental allegations must never become `CONFIRMED` taxpayer facts
merely because they appear in an official notice.

For `OTHER_NOTICE_FACT`, final status is
`FactStatus.REQUIRES_VERIFICATION` — a conservative fallback. Python must
never convert `OTHER_NOTICE_FACT` directly into `CONFIRMED`.

For `DOCUMENT_DETAIL` (added by Phase 2 Step 8A; authoritative definition
in §19.1), final status is `FactStatus.CONFIRMED`: the notice explicitly
states the detail, and that says nothing about whether the underlying
legal proposition is correct.

### 17.7 Status values NOT created by Step 6

Step 6 does NOT generate `FactStatus.UNKNOWN` or `FactStatus.INFERRED`.

- `UNKNOWN` represents facts not available / not established and is
  handled later when workflow completeness is evaluated (§17.14).
- `INFERRED` is reserved for deterministic downstream derivation,
  especially the Arithmetic Engine (§17.13).

Step 6 performs no arithmetic.

### 17.8 DraftPermission mapping

Approve the deterministic Python mapping:

```text
CONFIRMED              → DraftPermission.YES
ALLEGED                → DraftPermission.CONDITIONAL
REQUIRES_VERIFICATION  → DraftPermission.NO
UNKNOWN                → DraftPermission.NO
INFERRED               → DraftPermission.CONDITIONAL
```

Python owns this mapping. The LLM must never supply or override
`allowed_in_draft`. The later Validation Engine tests this mapping again
before drafting.

`DraftPermission.YES` only means the fact may be used in a correctly framed
draft. For example, the `CONFIRMED` fact `"The notice proposes ₹5,00,000"`
may be used; it does NOT authorize transformation into `"The taxpayer owes
₹5,00,000."`

### 17.9 Provenance contract

Every fact accepted by Step 6 MUST have non-empty `source_text`.

`source_text` must correspond to text actually present in `raw_text`.
Python must reject an extracted candidate whose `source_text` cannot be
found in the supplied notice text.

The initial Phase-2 implementation may use exact substring matching. Do not
build fuzzy matching or NLP provenance recovery in Step 6.

`source_page: Optional[int]`:

- `None` is valid when page information is unavailable.
- If supplied, it must be an integer >= 1.
- Step 6 does not invent a page number.
- Page numbering is document-page numbering beginning at 1 when the
  extraction pipeline provides page context.

Step 8 may perform additional provenance validation, but Step 6 must not
accept source-less facts.

### 17.10 Fact ID contract

Python creates IDs; the LLM does not. Use deterministic sequential IDs:

```text
F-001
F-002
F-003
...
```

IDs are assigned only to accepted facts, in accepted extraction order. Do
not introduce UUIDs.

### 17.11 Malformed output contract

Fact extraction must fail safely.

If the overall LLM response is malformed JSON, provider error text, missing
the top-level facts list, or structurally unusable: return `[]`. Do not
crash. Do not invent replacement facts.

For an otherwise valid response containing some invalid fact items: reject
only the invalid items; preserve valid items.

Reject an individual item when:

- `fact_type` is invalid;
- `claim` is missing/empty/non-string;
- `source_text` is missing/empty/non-string;
- `source_text` is not found in `raw_text`;
- `source_page` is neither `None` nor an integer >= 1.

Do not expose API keys or provider internals.

### 17.12 Duplicate facts

Step 6 performs NO semantic deduplication. Preserve all individually valid
extracted facts. Premature merging may destroy provenance. Deduplication /
consolidation is deferred to the later validation/integration layer.

### 17.13 Derived / INFERRED facts

Step 6 performs ZERO arithmetic or deterministic derivation.

Example: if the notice contains `GSTR-3B ITC = ₹10,00,000` and
`GSTR-2B ITC = ₹8,50,000`, Step 6 extracts the two source amounts. It does
NOT create `Difference = ₹1,50,000`. The future deterministic Arithmetic
Engine creates the `INFERRED` result.

### 17.14 Workflow `required_facts`

Step 6 does NOT create `UNKNOWN` placeholder facts merely because a
workflow requires a fact. Step 6 does NOT create `EvidenceGap` objects from
workflow `required_facts`. Step 6 does NOT receive `WorkflowDefinition`.

Later workflow completeness / validation compares
`WorkflowDefinition.required_facts` against extracted + derived facts and
creates missing-fact/evidence signals. This keeps document extraction
separate from workflow completeness.

### 17.15 Absence representation

Step 6 is presence-oriented.

- If RFN is present: extract `FactType.RFN`.
- If DIN is present: extract `FactType.DIN`.
- If neither is found: Step 6 does NOT fabricate `"DIN absent"` /
  `"RFN absent"` facts. `CommunicationIdentifierStatus.NEITHER_FOUND` is
  derived by Step 7 preflight from the absence of RFN/DIN facts.

Similarly, if a notice references Annexure A, extract
`REFERENCED_ANNEXURE`. Whether the annexure was actually supplied is
determined later by comparing document references against available
uploaded documents. Step 6 does not create an `EvidenceGap` solely from
absence in raw notice text.

### 17.16 Authority handling

Step 6 may extract `AUTHORITY_NAME`, `AUTHORITY_DESIGNATION`,
`AUTHORITY_OFFICE` and `JURISDICTION_TEXT` as document-native `CONFIRMED`
facts when explicitly printed.

It must NOT conclude:

- officer is legally competent;
- officer lacks jurisdiction;
- notice is valid/invalid.

Those belong to later verified legal/preflight checks.

### 17.17 DIN / RFN handling

DIN/RFN values explicitly printed are document-native facts; their presence
may be `CONFIRMED`.

Step 6 must NEVER conclude `missing DIN = invalid notice` or
`presence of DIN/RFN = legally valid notice`. Authentication / portal
verification is Step 7+ behavior.

### 17.18 Notice-stated due date

An explicitly printed due date is:

```text
FactType.STATED_DUE_DATE
FactStatus.CONFIRMED
DraftPermission.YES
```

with source provenance.

It is document data only. It is NOT inserted into `DeadlineResult` as a
calculated deadline and is NOT recalculated by Step 6. Future presentation
may compare the notice-stated due date against the independently calculated
deadline and warn when they conflict (§6.5).

### 17.19 Sections / rules / notifications

Use one `ExtractedFact` per explicit citation:

```text
FactType.STATUTORY_SECTION
FactType.STATUTORY_RULE
FactType.STATUTORY_NOTIFICATION
```

Only citations appearing in the notice are extracted. Step 6 does NOT add
external legal authorities from model knowledge. It does NOT verify whether
the cited provision is legally correct/current — that belongs to the future
Legal Knowledge / Validation layers.

### 17.20 Departmental allegation rule

The extraction prompt must instruct the LLM to categorize departmental
claims of wrongdoing/liability as `FactType.DEPARTMENT_ALLEGATION`. Python
then forces `FactStatus.ALLEGED` and `DraftPermission.CONDITIONAL`. The LLM
cannot upgrade it.

Examples include: fraud, suppression, wilful misstatement, ineligible ITC,
alleged unpaid tax, alleged short payment, wrongful refund, other asserted
contraventions/liability.

Do NOT build a large homemade allegation-NLP engine in Step 6. Safety is
layered:

1. focused extraction prompt;
2. closed `FactType` contract;
3. Python-owned status;
4. provenance requirement;
5. workflow special rules;
6. later Validation Engine;
7. CA review.

### 17.21 Claim framing rule

The extraction prompt must distinguish document-native facts
(`"The notice states/proposes/shows X"`) from liability conclusions
(`"The taxpayer owes X"`).

For `DEPARTMENT_ALLEGATION` candidates, claims should preserve attribution,
for example: `"Department alleges ineligible ITC of ₹5,00,000."` Do not
rewrite an allegation into an established taxpayer fact.

Python need not implement general natural-language rewriting in Step 6. The
structured `FactStatus` remains authoritative.

### 17.22 TRIAGE_ONLY / UNKNOWN

Use the same Fact Engine for `DEEP_WORKFLOW`, `TRIAGE_ONLY` and `UNKNOWN`.
There is no second fact-extraction LLM surface.

For `TRIAGE_ONLY` and `UNKNOWN`, the Fact Engine may preserve
document-native information such as: notice reference; form-related facts
if present in text; authority; GSTIN / taxpayer; sections/rules/
notifications; dates; stated due date; hearing details; amounts;
departmental allegations; requested documents; referenced annexures;
RFN/DIN.

It does not create specialist legal defences or workflow requirements.

### 17.23 LLM routing / prompt safety

Exactly ONE focused fact-extraction LLM call per extraction request. All
calls must go through `modules/llm_client.py` and the existing router — no
direct Gemini SDK use.

Raw notice text must be delimited as untrusted DATA. Instructions appearing
inside notice text must be ignored as instructions.

The LLM call performs extraction only. It must not:

- calculate;
- classify the proceeding again;
- change `SupportLevel`;
- perform legal research;
- draft replies;
- propose defences;
- decide jurisdiction;
- decide notice validity;
- determine taxpayer liability.

### 17.24 Step 6 file plan

After this spec-only amendment, implementation is split into two controlled
pieces:

**Step 6.1 — additive `FactType` model contract**

Modify:

```text
domain/models.py
tests/test_taxonomy_models.py or a dedicated fact-model test file
```

Add:

```text
FactType enum
ExtractedFact.fact_type with backward-compatible default
```

No fact engine yet.

**Step 6.2 — Fact Engine**

Create:

```text
domain/fact_engine.py
tests/test_fact_engine.py
```

No other files.

This split preserves one architectural unit per commit.

### 17.25 Validation responsibility

Step 6 performs basic structural and provenance validation described above
(§17.9, §17.11).

Step 8 remains responsible for deeper validation such as:

- workflow completeness;
- fact conflicts;
- semantic duplication/consolidation;
- ensuring `special_rules` are enforced;
- checking final draft use;
- evidence-gap generation;
- cross-layer consistency.

---

## 18. Preflight + Arithmetic Contract (Phase 2 Step 7A — authoritative)

This section is the authoritative contract for Phase 2 Step 7 (deterministic
preflight) and the deterministic arithmetic layer. It also introduces the
additive fact-extraction outcome channel (implemented in Step 6.3) without
changing the backward-compatible `extract_facts` API (§17.4). It resolves,
decisively, every contract question identified by the Phase 2 Step 7
pre-implementation review.

### 18.1 `FactExtractionStatus` — additive extraction outcome channel

Approve an additive enum `FactExtractionStatus` with exactly four members:

```text
SUCCESS = "success"
PARTIAL = "partial"
FAILED = "failed"
NO_INPUT = "no_input"
```

- **`SUCCESS`** — the LLM returned a structurally usable top-level `facts`
  list and every candidate item was processed without any candidate
  rejection. `SUCCESS` may contain zero facts: a valid response
  `{"facts": []}` is `SUCCESS`.
- **`PARTIAL`** — the overall LLM response was structurally usable, but one
  or more candidate items were rejected by deterministic validation.
  `PARTIAL` may contain zero or more accepted facts.
- **`FAILED`** — the LLM call failed, returned unusable overall output,
  malformed JSON, a non-object root, a missing/non-list `facts` field, or
  another overall extraction failure.
- **`NO_INPUT`** — `raw_text` was missing, non-string, empty, or
  whitespace-only and no LLM extraction was attempted.

### 18.2 `FactExtractionResult` + `extract_facts_with_status`

Approve an additive dataclass `FactExtractionResult` with exactly:

```text
facts: List[ExtractedFact]
status: FactExtractionStatus
rejected_item_count: int = 0
```

No provider exception strings. No API internals. No raw API error object.

Approve the new companion public API:

```text
extract_facts_with_status(
    raw_text: str,
    classification: NoticeClassification
) -> FactExtractionResult
```

The existing `extract_facts(...)` remains backward-compatible and returns:

```text
extract_facts_with_status(...).facts
```

There must still be exactly ONE LLM extraction call. Extraction is never
run twice.

### 18.3 Absence-based preflight safety

Absence-based conclusions may be made ONLY when
`FactExtractionStatus.SUCCESS`.

Therefore, if extraction status is `PARTIAL`, `FAILED` or `NO_INPUT`,
preflight must NOT conclude merely from absence that RFN is absent, DIN is
absent, or authority details are missing. Those absence-derived statuses
become `UNKNOWN`.

Validated positive `ExtractedFact` objects remain available to later
layers, but completeness/absence statuses stay conservative whenever
extraction was not `SUCCESS`.

### 18.4 Preflight input contract

```text
run_preflight(
    extraction_result: FactExtractionResult,
    classification: NoticeClassification,
    deadline_result: Optional[DeadlineResult] = None
) -> PreflightResult
```

Preflight does NOT receive:

- `raw_text`
- `WorkflowDefinition`
- uploaded-document metadata

It does NOT call an LLM. It does NOT call the deadline engine itself.
`DeadlineResult`, when available, is supplied by integration as an already
calculated deterministic result.

This keeps `domain/deadline_engine.py` frozen and prevents generic prose
parsing from entering the Deadline Engine.

### 18.5 Communication identifier mapping

When `extraction_result.status == SUCCESS`, derive from validated
`FactType`s:

| Extracted | Derived status |
|---|---|
| RFN + DIN present | `CommunicationIdentifierStatus.BOTH_PRESENT` |
| RFN present only | `CommunicationIdentifierStatus.RFN_PRESENT` |
| DIN present only | `CommunicationIdentifierStatus.DIN_PRESENT` |
| neither present | `CommunicationIdentifierStatus.NEITHER_FOUND` |

When extraction status is `PARTIAL`, `FAILED` or `NO_INPUT`, derive
`CommunicationIdentifierStatus.UNKNOWN`.

Do not infer absence from a non-successful extraction.

### 18.6 Portal verification flag

For Phase 2:

```text
portal_verification_required = True
```

always.

Reason: Phase 2 extracts RFN/DIN presence only. It does not authenticate
either identifier against the GST portal. Therefore even `BOTH_PRESENT`
does not mean portal authenticity has been established.

This flag must remain separate from
`DeadlineResult.portal_verification_required`. Do not merge those concepts.

### 18.7 Authority details mapping

Core authority fields:

```text
AUTHORITY_DESIGNATION
AUTHORITY_OFFICE
```

Supplementary fields:

```text
AUTHORITY_NAME
JURISDICTION_TEXT
```

When `extraction_result.status == SUCCESS`, derive:

- **`PRESENT`** — `AUTHORITY_DESIGNATION` and `AUTHORITY_OFFICE` are both
  present.
- **`PARTIAL`** — at least one authority-related fact exists, but both core
  fields are not present.
- **`MISSING`** — no authority-related `FactType` is present.

When extraction status is `PARTIAL`, `FAILED` or `NO_INPUT`, derive
`AuthorityDetailsStatus.UNKNOWN`.

`PRESENT` means only: sufficient authority-identification details were
extracted. It does NOT mean legal competence established, jurisdiction
established, or notice valid.

### 18.8 Authority verification flag

For Phase 2:

```text
authority_verification_required = True
```

always.

Reason: Phase 2 does not yet contain the verified legal/jurisdiction rule
layer needed to establish officer competence. Even
`AuthorityDetailsStatus.PRESENT` still requires CA/legal verification
before a competence conclusion.

### 18.9 `DeadlineConflictStatus`

Approve enum `DeadlineConflictStatus` with exactly:

```text
MATCH = "match"
CONFLICT = "conflict"
CANNOT_COMPARE = "cannot_compare"
```

No `VALID` / `INVALID` member. This enum compares dates only. It does not
decide legal validity.

### 18.10 Stated due date parsing

Preflight may deterministically parse `STATED_DUE_DATE` facts.

Supported date representations in Phase 2:

```text
DD-MM-YYYY
DD/MM/YYYY
YYYY-MM-DD
DD Month YYYY
DD Mon YYYY
```

English month names/abbreviations only. Slash-form dates use the Indian
day-first convention `DD/MM/YYYY`. Two-digit years are not supported.
Unsupported formats are not silently guessed.

For each `STATED_DUE_DATE` fact:

- preserve the original `ExtractedFact`;
- attempt deterministic date parsing from `source_text`;
- if exactly one supported date can be safely parsed, record that date;
- if zero supported dates are found, mark that fact as unparsed;
- if multiple distinct supported dates occur in one due-date fact, mark
  that fact as unparsed for comparison purposes.

Do not use an LLM for date parsing.

### 18.11 Multiple stated due dates

Preserve all `STATED_DUE_DATE` fact IDs.

For deadline comparison:

- If all successfully parsed due-date facts resolve to exactly one unique
  date, that date may be compared to the calculated deadline.
- If more than one distinct parsed stated due date exists:
  `DeadlineConflictStatus.CANNOT_COMPARE`.
- If no stated due date is safely parseable:
  `DeadlineConflictStatus.CANNOT_COMPARE`.

Do not arbitrarily choose one date.

### 18.12 Deadline comparison

If:

- exactly one unique safely parsed stated due date exists
  AND
- `deadline_result` contains a calculated response deadline

then:

- same date → `MATCH`
- different date → `CONFLICT`

Otherwise: `CANNOT_COMPARE`.

Preflight does NOT change `DeadlineResult`. It does NOT replace the
notice-stated date. It does NOT decide which date is legally correct.

Later presentation must show both dates when both exist and surface the
`CONFLICT` warning.

### 18.13 `PreflightResult`

Approve additive dataclass `PreflightResult` with exactly:

```text
fact_extraction_status: FactExtractionStatus

communication_identifier_status: CommunicationIdentifierStatus
portal_verification_required: bool

authority_details_status: AuthorityDetailsStatus
authority_verification_required: bool

stated_due_date_fact_ids: List[str]
parsed_stated_due_dates: List[date]
unparsed_stated_due_date_fact_ids: List[str]

deadline_conflict_status: DeadlineConflictStatus

hearing_fact_ids: List[str]
requested_document_fact_ids: List[str]
referenced_annexure_fact_ids: List[str]
```

Do NOT include legal-validity fields. Do NOT create:

```text
notice_valid
notice_invalid
jurisdiction_valid
officer_competent
```

### 18.14 Preflight pass-through fact indexing

Preflight deterministically records IDs of:

```text
HEARING_DETAILS
REQUESTED_DOCUMENT
REFERENCED_ANNEXURE
```

It does NOT create `EvidenceGap` objects. It does NOT determine whether a
referenced annexure was uploaded. Uploaded-document comparison belongs to
Step 8/integration once document metadata exists.

### 18.15 Deadline Engine ownership

Step 7 does NOT build `DeadlineResult` from raw notice facts. There is NO
generic Fact → Deadline Engine adapter in Phase 2 Step 7.

The existing deterministic Deadline Engine continues to accept its existing
structured input contract. The integration layer later supplies structured
inputs:

```text
notice date
service date
response period/basis
hearing date
today/current date
```

when those values are independently available.

Do NOT add `SERVICE_DATE` or `RESPONSE_PERIOD` `FactType`s merely for
Step 7. Do NOT modify `domain/deadline_engine.py`.

### 18.16 Arithmetic design principle

The Arithmetic Engine must NOT infer operand roles from arbitrary natural
language. It must NOT scan all extracted facts and guess:

```text
which amount is GSTR-3B
which amount is GSTR-2B
which amount is GSTR-1
which amount is penalty
```

Instead it receives an explicit calculation request referring to exact
source facts and exact amount text.

### 18.17 `ArithmeticCalculationType`

Approve enum `ArithmeticCalculationType` with exactly:

```text
ITC_DIFFERENCE = "itc_difference"
OUTPUT_TAX_DIFFERENCE = "output_tax_difference"
```

No Section-129 penalty calculation type yet. No RCM statutory calculation
type. No Section-74 penalty calculation type. No interest calculation type
yet.

### 18.18 `ArithmeticOperand`

Approve dataclass `ArithmeticOperand` with exactly:

```text
source_fact_id: str
value_text: str
```

`value_text` must be an exact substring of the referenced fact's
`source_text`.

Purpose: the arithmetic layer does not need to guess which numeric token
inside a long notice sentence/table row should be used. The caller selects
the exact text fragment to calculate from. The Arithmetic Engine validates
the provenance relationship.

### 18.19 `ArithmeticRequest`

Approve dataclass `ArithmeticRequest` with exactly:

```text
calculation_type: ArithmeticCalculationType
left_operand: ArithmeticOperand
right_operand: ArithmeticOperand
```

Operand ordering is authoritative:

```text
ITC_DIFFERENCE:
    left  = GSTR-3B ITC
    right = GSTR-2B ITC

OUTPUT_TAX_DIFFERENCE:
    left  = GSTR-1 liability
    right = GSTR-3B liability
```

Result:

```text
left - right
```

The Arithmetic Engine itself does not infer these semantic roles. The
caller constructing the request is responsible for selecting the
appropriate sourced facts. Workflow/integration validation later checks
that role selection is correct.

### 18.20 Numeric representation

Use `decimal.Decimal` for all monetary arithmetic. Never use binary float.

Currency for current approved calculations:

```text
INR
```

The Phase-2 deterministic amount parser may accept:

- optional leading minus sign;
- optional `₹`;
- optional `INR`;
- optional `Rs` / `Rs.`;
- digits without grouping;
- standard 3-digit comma grouping;
- Indian lakh/crore grouping;
- optional decimal fraction of one or two digits.

Examples intended to be parseable:

```text
150000
150000.50
1,50,000
10,00,000.25
150,000
₹1,50,000
Rs. 1,50,000.00
INR 150000
```

Malformed/inconsistent grouping must be rejected rather than guessed.

Do not parse word forms such as:

```text
one lakh
five crore
```

in Phase 2.

### 18.21 `ArithmeticResult`

Approve dataclass `ArithmeticResult` with exactly:

```text
calculation_type: ArithmeticCalculationType
status: ArithmeticStatus

source_fact_ids: List[str]
operand_values: List[Decimal]

result: Optional[Decimal]
formula: str

currency: str = "INR"

allowed_in_draft: DraftPermission = DraftPermission.CONDITIONAL
```

`ArithmeticResult` is a deterministic derived result. It is semantically
`INFERRED` but it is NOT an `ExtractedFact`.

Do NOT fabricate a new `ExtractedFact` merely to represent arithmetic
output. Do NOT assign F-xxx fact IDs to `ArithmeticResult`.

### 18.22 Arithmetic status

For the two approved difference calculations:

If either operand:

- cannot be linked to an existing source fact;
- `value_text` is not inside that source fact's `source_text`;
- cannot be parsed deterministically;

return:

```text
ArithmeticStatus.INSUFFICIENT_DATA
result = None
```

If calculation succeeds:

```text
result = left - right
```

If:

```text
result == Decimal("0")
```

status:

```text
ArithmeticStatus.PASS
```

Otherwise:

```text
ArithmeticStatus.MISMATCH
```

No tolerance is introduced in Phase 2 for these two reconciliation
differences. Do not silently round operands/results.

### 18.23 Approved arithmetic whitelist

Phase 2 Step 7 authorizes exactly:

1. `GST_SEC73_ITC` reconciliation: GSTR-3B ITC − GSTR-2B ITC.
2. `GST_SEC73_GENERAL` reconciliation: GSTR-1 liability − GSTR-3B
   liability.

No other statutory calculations are authorized yet. Specifically NOT
authorized:

- Section 129 statutory penalty computation;
- Section 74 penalty computation;
- Section 74A computation;
- RCM statutory liability computation;
- statutory interest computation.

Those require future verified/versioned legal-rule contracts.

### 18.24 Section 129 safety

Reaffirm: Step 7 MUST NOT hardcode a 100% penalty, a 200% penalty, or any
other Section-129 statutory penalty formula. The notice-displayed proposed
penalty remains an extracted fact. Statutory penalty verification remains
deferred until a verified, versioned legal-rule subsystem is implemented.
Do not reintroduce historical MOV assumptions.

### 18.25 Inferred representation

`ArithmeticResult` is the Phase-2 representation of deterministic derived
numeric information. It is not an `ExtractedFact`. Therefore Step 7 creates
no `FactStatus.INFERRED` `ExtractedFact`.

The semantic rule is:

```text
successful ArithmeticResult = deterministic derived/inferred information
```

and:

```text
allowed_in_draft = DraftPermission.CONDITIONAL
```

Later Validation Engine controls its use in drafting.

### 18.26 Workflow completeness ownership

Step 7 "completeness signals" means ONLY deterministic preflight-level
completeness such as:

```text
identifier completeness
authority-information completeness
arithmetic input sufficiency
date comparison availability
```

Step 7 does NOT compare `WorkflowDefinition.required_facts` or
`WorkflowDefinition.evidence_requirements`. That is Step 8 Validation /
Workflow Completeness.

### 18.27 Evidence gap ownership

Step 7 does NOT create `EvidenceGap` objects.

Step 8/integration owns:

- workflow evidence requirements;
- missing invoices;
- missing returns;
- missing bank records;
- referenced-but-not-uploaded annexures;
- uploaded document matching;

until a concrete uploaded-document metadata contract exists.

### 18.28 Pure Python boundary

Step 7 adds ZERO LLM calls. Preflight and arithmetic are deterministic
Python only.

They must not import:

```text
modules.llm_client
Gemini / Google SDK
workflows for inference
web/network libraries
```

The only Phase-2 LLM surfaces remain:

```text
proceeding classification
fact extraction
later controlled deep reasoning/drafting
```

### 18.29 Implementation split

After this Step 7A spec amendment, implementation proceeds as:

```text
Step 6.3
    Add FactExtractionStatus
    Add FactExtractionResult
    Add extract_facts_with_status()
    Preserve extract_facts() compatibility

Step 7.1
    Add:
        DeadlineConflictStatus
        PreflightResult
        ArithmeticCalculationType
        ArithmeticOperand
        ArithmeticRequest
        ArithmeticResult

Step 7.2
    Implement deterministic preflight engine

Step 7.3
    Implement deterministic arithmetic engine
```

Each is a separate commit.

### 18.30 No Step-8 leakage

Do NOT move into Step 7:

- workflow completeness;
- evidence-gap generation;
- legal knowledge retrieval;
- case-law validation;
- legal validity conclusions;
- workflow special-rule validation;
- drafting permissions beyond the deterministic arithmetic default;
- final draft validation.

Those remain later phases.

---

## 19. Validation + Workflow Completeness Contract (Phase 2 Step 8A — authoritative)

This section finalizes the deterministic Step 8 contract. It resolves the
Step 8 review finding that deterministic workflow completeness cannot be
implemented from `required_facts: List[str]` plus generic `FactType` values
alone, because multiple workflow requirements can share the same
`FactType`. Example: `GST_SEC73_ITC` requires the ITC claimed in GSTR-3B,
the ITC reflected in GSTR-2B and the interest proposed — all of which may
currently be `FactType.STATED_AMOUNT`. Step 8 MUST NOT inspect English
claim text or ask an LLM which amount is which.

This amendment therefore introduces `FactRole`, the closed machine-readable
semantic slot for extracted facts:

```text
FactType = WHAT kind of datum is this?
FactRole = WHAT ROLE does this datum play in workflow logic?
```

Example:

```text
fact_type = STATED_AMOUNT
fact_role = GSTR3B_ITC_CLAIMED_AMOUNT
```

Step 8 is pure deterministic Python: ZERO LLM calls, and no model semantic
matching over required facts, evidence, special rules, fact roles,
arithmetic roles or claim text. Every mapping in this section is a closed
deterministic contract.

### 19.1 Additive `FactType.DOCUMENT_DETAIL`

Approve one additive `FactType` member:

```text
DOCUMENT_DETAIL = "document_detail"
```

`DOCUMENT_DETAIL` is a document-native textual/date/status detail that is
explicitly printed in the notice but does not fit the existing specialized
`FactType`s. Examples:

```text
goods description
vehicle number
detention/seizure date
service-date information
limitation basis stated in notice
owner-came-forward status
enforcement/order status
```

Python status mapping:

```text
FactType.DOCUMENT_DETAIL → FactStatus.CONFIRMED
```

`CONFIRMED` means only: the notice explicitly states the detail. It does
NOT mean the underlying legal proposition is correct.

`OTHER_NOTICE_FACT → REQUIRES_VERIFICATION` remains unchanged.

### 19.2 `FactRole` — closed semantic role vocabulary

Approve enum `FactRole` with exactly these 22 members:

```text
NONE = "none"

GSTR3B_ITC_CLAIMED_AMOUNT = "gstr3b_itc_claimed_amount"
GSTR2B_ITC_REFLECTED_AMOUNT = "gstr2b_itc_reflected_amount"
INTEREST_PROPOSED_AMOUNT = "interest_proposed_amount"

GSTR1_LIABILITY_DECLARED_AMOUNT = "gstr1_liability_declared_amount"
GSTR3B_LIABILITY_DISCHARGED_AMOUNT = "gstr3b_liability_discharged_amount"

RCM_CATEGORY_ALLEGED = "rcm_category_alleged"
RCM_VALUE_ALLEGED_AMOUNT = "rcm_value_alleged_amount"
RCM_TAX_ALLEGED_AMOUNT = "rcm_tax_alleged_amount"

FRAUD_BASIS_ALLEGED = "fraud_basis_alleged"
DEPARTMENT_ALLEGED_AMOUNT = "department_alleged_amount"
FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT = "fraud_penalty_proposed_alleged_amount"
LIMITATION_BASIS = "limitation_basis"

GOODS_DESCRIPTION = "goods_description"
VEHICLE_NUMBER = "vehicle_number"
DETENTION_OR_SEIZURE_DATE = "detention_or_seizure_date"
SECTION129_NOTICE_OR_SERVICE_DATE = "section129_notice_or_service_date"
SEC129_PENALTY_PROPOSED_AMOUNT = "sec129_penalty_proposed_amount"
GOODS_VALUE_OR_TAX_PAYABLE = "goods_value_or_tax_payable"
OWNER_CAME_FORWARD_STATUS = "owner_came_forward_status"
EXPLICIT_PROCEDURAL_DATE = "explicit_procedural_date"
ORDER_DATE_OR_ENFORCEMENT_STATUS = "order_date_or_enforcement_status"
```

`FactRole` is deterministic vocabulary. It does NOT determine legal
liability.

### 19.3 `ExtractedFact.fact_role` additive change

Approve `fact_role` as the final additive field of `ExtractedFact`:

```text
fact_role: FactRole = FactRole.NONE
```

Preserve all prior constructor compatibility. Conceptual final fields:

```text
fact_id
claim
status
source_text
source_page
allowed_in_draft
fact_type
fact_role
```

No earlier field is removed or changed. The implementation places
`fact_role` last, after `fact_type`.

### 19.4 Fact Engine candidate contract amendment

Amend the §17.5 candidate JSON from four to exactly five fields:

```json
{
  "facts": [
    {
      "fact_type": "stated_amount",
      "fact_role": "gstr3b_itc_claimed_amount",
      "claim": "The notice states GSTR-3B ITC of ...",
      "source_text": "exact notice text",
      "source_page": 1
    }
  ]
}
```

Candidate fields exactly:

```text
fact_type
fact_role
claim
source_text
source_page
```

The LLM still must NOT control `fact_id`, `status` or `allowed_in_draft`.
Python validates `FactRole` as a closed enum: an invalid role rejects the
candidate item. Role is never inferred later from claim text.

### 19.5 FactRole compatibility

Approve the deterministic role → FactType compatibility table.

For these roles the allowed `FactType` is `STATED_AMOUNT`:

```text
GSTR3B_ITC_CLAIMED_AMOUNT
GSTR2B_ITC_REFLECTED_AMOUNT
INTEREST_PROPOSED_AMOUNT
GSTR1_LIABILITY_DECLARED_AMOUNT
GSTR3B_LIABILITY_DISCHARGED_AMOUNT
SEC129_PENALTY_PROPOSED_AMOUNT
```

For these roles the allowed `FactType` is `DEPARTMENT_ALLEGATION`:

```text
RCM_CATEGORY_ALLEGED
RCM_VALUE_ALLEGED_AMOUNT
RCM_TAX_ALLEGED_AMOUNT
FRAUD_BASIS_ALLEGED
DEPARTMENT_ALLEGED_AMOUNT
FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT
```

For these roles the allowed `FactType` is `DOCUMENT_DETAIL`:

```text
LIMITATION_BASIS
GOODS_DESCRIPTION
VEHICLE_NUMBER
DETENTION_OR_SEIZURE_DATE
SECTION129_NOTICE_OR_SERVICE_DATE
GOODS_VALUE_OR_TAX_PAYABLE
OWNER_CAME_FORWARD_STATUS
ORDER_DATE_OR_ENFORCEMENT_STATUS
```

For `EXPLICIT_PROCEDURAL_DATE` the allowed `FactType`s are:

```text
STATED_DUE_DATE
HEARING_DETAILS
DOCUMENT_DETAIL
```

`FactRole.NONE` is allowed with any `FactType`.

If a non-`NONE` role is incompatible with its `FactType`: reject the
candidate item. Do not silently change the role or the FactType.

### 19.6 Status remains FactType-owned

`FactRole` does NOT choose `FactStatus`. Python status remains determined
from `FactType` (§17.6):

```text
document-native FactTypes including DOCUMENT_DETAIL → CONFIRMED
DEPARTMENT_ALLEGATION                              → ALLEGED
OTHER_NOTICE_FACT                                  → REQUIRES_VERIFICATION
```

A role cannot upgrade an allegation into `CONFIRMED`.

### 19.7 Step 8 public input contract

```text
run_validation(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    deadline_result: Optional[DeadlineResult] = None
) -> ValidationEngineResult
```

Step 8 does NOT receive:

- a separate facts list — facts are accessed only through
  `extraction_result.facts`;
- `raw_text`;
- uploaded-document metadata in Phase 2 Step 8;
- `WorkflowDefinition` from the caller.

The Validation Engine deterministically obtains the `WorkflowDefinition`
and the `WorkflowValidationProfile` from
`classification.proceeding_type`. This prevents an inconsistent
caller-supplied workflow.

### 19.8 Zero LLM

Step 8 is pure deterministic Python. No LLM call. Step 8 must not import:

```text
modules.llm_client
Gemini / Google SDK
network libraries
```

The approved Phase-2 LLM surfaces remain:

```text
proceeding classification
fact extraction
later deep drafting/reasoning
```

### 19.9 `RequirementStatus`

Approve enum `RequirementStatus` with exactly:

```text
SATISFIED = "satisfied"
DERIVED = "derived"
REQUIRES_VERIFICATION = "requires_verification"
UNKNOWN = "unknown"
MISSING = "missing"
```

No `NOT_APPLICABLE` in Phase 2.

### 19.10 `RequirementKind`

Approve enum `RequirementKind` with exactly:

```text
FACT = "fact"
DERIVED = "derived"
```

### 19.11 `WorkflowRequirementSpec`

Approve dataclass `WorkflowRequirementSpec` with exactly eight fields:

```text
requirement_id: str
requirement_text: str
kind: RequirementKind

fact_type: Optional[FactType] = None
fact_role: Optional[FactRole] = None
calculation_type: Optional[ArithmeticCalculationType] = None

accepted_fact_statuses: Tuple[FactStatus, ...] = (FactStatus.CONFIRMED,)
absent_on_success: RequirementStatus = RequirementStatus.MISSING
```

Rules:

- A `FACT` requirement uses `fact_type` and/or `fact_role`.
- A `DERIVED` requirement uses `calculation_type`.
- No claim-text matching.
- `requirement_text` MUST equal the corresponding
  `workflow.required_facts` string verbatim.

### 19.12 `RequirementResult`

Approve dataclass `RequirementResult` with exactly:

```text
requirement_id: str
requirement_text: str
status: RequirementStatus
related_fact_ids: List[str]
calculation_type: Optional[ArithmeticCalculationType] = None
```

No free-form LLM explanation field.

### 19.13 FACT requirement resolution

For a `FACT` requirement, collect facts matching every selector supplied
by the spec — `fact_type` if not `None`, `fact_role` if not `None`. Then:

- If at least one matching fact has a `FactStatus` listed in
  `accepted_fact_statuses`: `SATISFIED`, and `related_fact_ids` contains
  all accepted matching fact IDs in extraction order.
- If matching facts exist but none has an accepted status:
  - if any has `REQUIRES_VERIFICATION`: `REQUIRES_VERIFICATION`;
  - otherwise: `UNKNOWN`.
- If no matching fact exists:
  - when `extraction_result.status == SUCCESS`: return
    `spec.absent_on_success`;
  - when extraction status is `PARTIAL`, `FAILED` or `NO_INPUT`: return
    `UNKNOWN`.

This extends the §18.3 absence-safety principle to workflow completeness:
do not call missing when extraction itself is incomplete or failed.

### 19.14 DERIVED requirement resolution

For a `DERIVED` requirement, find `ArithmeticResult` objects whose
`calculation_type` matches the spec:

- Exactly one matching result with `PASS` or `MISMATCH`: `DERIVED`.
  `MISMATCH` still means the difference was deterministically calculated;
  it separately generates a validation WARNING.
- Exactly one matching result with `INSUFFICIENT_DATA`: `UNKNOWN`.
- No matching result: `UNKNOWN`.
- Multiple results for the same required calculation type: `UNKNOWN` and a
  validation WARNING for ambiguous derived output. Do not arbitrarily
  select one.

### 19.15 Arithmetic role validation

Step 8 must validate the source roles of approved arithmetic.
`ArithmeticResult.source_fact_ids` is interpreted in operand order — left
operand first, right operand second (§18.19).

For `ITC_DIFFERENCE`:

```text
left  source fact must have FactRole.GSTR3B_ITC_CLAIMED_AMOUNT
right source fact must have FactRole.GSTR2B_ITC_REFLECTED_AMOUNT
```

For `OUTPUT_TAX_DIFFERENCE`:

```text
left  source fact must have FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT
right source fact must have FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT
```

If role provenance does not match: validation `FAIL`, the derived
requirement is `UNKNOWN`, and specialist drafting is `BLOCKED`. This is
how Step 8 verifies the caller selected the correct arithmetic operands
without inspecting natural-language claims.

### 19.16 Authoritative requirement mappings

The following are exact mapping contracts. Requirement IDs are stable
Phase-2 identifiers. `text` is the corresponding workflow `required_facts`
string verbatim. `accepted` is shorthand for `accepted_fact_statuses`; any
field not listed keeps its §19.11 default. The five proceeding prefixes
`sec73_itc`, `sec73_general`, `sec73_rcm`, `sec74_fraud`, `sec129` are also
the stable evidence-ID prefixes (§19.18).

**GST_SEC73_ITC**

```text
R1  id          = "sec73_itc.r1"
    text        = "ITC claimed in GSTR-3B (amount)"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = GSTR3B_ITC_CLAIMED_AMOUNT
    accepted    = CONFIRMED

R2  id          = "sec73_itc.r2"
    text        = "ITC reflected in GSTR-2B (amount)"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = GSTR2B_ITC_REFLECTED_AMOUNT
    accepted    = CONFIRMED

R3  id          = "sec73_itc.r3"
    text        = "Difference between GSTR-3B and GSTR-2B (INFERRED)"
    kind        = DERIVED
    calculation_type = ITC_DIFFERENCE

R4  id          = "sec73_itc.r4"
    text        = "FY / tax period"
    kind        = FACT
    fact_type   = TAX_PERIOD
    fact_role   = NONE
    accepted    = CONFIRMED

R5  id          = "sec73_itc.r5"
    text        = "Interest proposed"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = INTEREST_PROPOSED_AMOUNT
    accepted    = CONFIRMED
```

**GST_SEC73_GENERAL**

```text
R1  id          = "sec73_general.r1"
    text        = "Tax / liability declared in GSTR-1"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = GSTR1_LIABILITY_DECLARED_AMOUNT
    accepted    = CONFIRMED

R2  id          = "sec73_general.r2"
    text        = "Tax / liability discharged in GSTR-3B"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = GSTR3B_LIABILITY_DISCHARGED_AMOUNT
    accepted    = CONFIRMED

R3  id          = "sec73_general.r3"
    text        = "Difference between GSTR-1 and GSTR-3B (INFERRED)"
    kind        = DERIVED
    calculation_type = OUTPUT_TAX_DIFFERENCE

R4  id          = "sec73_general.r4"
    text        = "FY / tax period"
    kind        = FACT
    fact_type   = TAX_PERIOD
    fact_role   = NONE
    accepted    = CONFIRMED

R5  id          = "sec73_general.r5"
    text        = "Interest proposed"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = INTEREST_PROPOSED_AMOUNT
    accepted    = CONFIRMED
```

**GST_SEC73_RCM**

```text
R1  id          = "sec73_rcm.r1"
    text        = "Service / supply category alleged to attract RCM"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = RCM_CATEGORY_ALLEGED
    accepted    = ALLEGED

R2  id          = "sec73_rcm.r2"
    text        = "Value of services / supplies alleged to be subject to RCM"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = RCM_VALUE_ALLEGED_AMOUNT
    accepted    = ALLEGED

R3  id          = "sec73_rcm.r3"
    text        = "RCM tax alleged as unpaid or short-paid"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = RCM_TAX_ALLEGED_AMOUNT
    accepted    = ALLEGED

R4  id          = "sec73_rcm.r4"
    text        = "FY / tax period"
    kind        = FACT
    fact_type   = TAX_PERIOD
    fact_role   = NONE
    accepted    = CONFIRMED

R5  id          = "sec73_rcm.r5"
    text        = "Interest proposed"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = INTEREST_PROPOSED_AMOUNT
    accepted    = CONFIRMED
```

**GST_SEC74_FRAUD**

```text
R1  id          = "sec74_fraud.r1"
    text        = "Basis of fraud / wilful-misstatement / suppression allegation"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = FRAUD_BASIS_ALLEGED
    accepted    = ALLEGED

R2  id          = "sec74_fraud.r2"
    text        = "Turnover, tax, refund or ITC amount alleged by the department (ALLEGED unless independently established)"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = DEPARTMENT_ALLEGED_AMOUNT
    accepted    = ALLEGED

R3  id          = "sec74_fraud.r3"
    text        = "FY / tax period"
    kind        = FACT
    fact_type   = TAX_PERIOD
    fact_role   = NONE
    accepted    = CONFIRMED

R4  id          = "sec74_fraud.r4"
    text        = "Penalty proposed in the notice (ALLEGED)"
    kind        = FACT
    fact_type   = DEPARTMENT_ALLEGATION
    fact_role   = FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT
    accepted    = ALLEGED

R5  id          = "sec74_fraud.r5"
    text        = "Limitation / extended-period basis invoked in the notice"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = LIMITATION_BASIS
    accepted    = CONFIRMED
```

**GST_SEC129_ENFORCE**

```text
R1  id          = "sec129.r1"
    text        = "Goods description"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = GOODS_DESCRIPTION
    accepted    = CONFIRMED

R2  id          = "sec129.r2"
    text        = "Vehicle / conveyance number"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = VEHICLE_NUMBER
    accepted    = CONFIRMED

R3  id          = "sec129.r3"
    text        = "Detention / seizure date"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = DETENTION_OR_SEIZURE_DATE
    accepted    = CONFIRMED

R4  id          = "sec129.r4"
    text        = "Section 129 notice date and service date where available"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = SECTION129_NOTICE_OR_SERVICE_DATE
    accepted    = CONFIRMED

R5  id          = "sec129.r5"
    text        = "Penalty amount proposed in the notice"
    kind        = FACT
    fact_type   = STATED_AMOUNT
    fact_role   = SEC129_PENALTY_PROPOSED_AMOUNT
    accepted    = CONFIRMED

R6  id          = "sec129.r6"
    text        = "Value of goods and tax payable on the goods where stated and relevant to penalty computation"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = GOODS_VALUE_OR_TAX_PAYABLE
    accepted    = CONFIRMED
    absent_on_success = REQUIRES_VERIFICATION

R7  id          = "sec129.r7"
    text        = "Whether the owner of the goods has come forward, where relevant and determinable"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = OWNER_CAME_FORWARD_STATUS
    accepted    = CONFIRMED
    absent_on_success = REQUIRES_VERIFICATION

R8  id          = "sec129.r8"
    text        = "Explicit hearing / payment / response date stated in the notice or order"
    kind        = FACT
    fact_type   = None
    fact_role   = EXPLICIT_PROCEDURAL_DATE
    accepted    = CONFIRMED

R9  id          = "sec129.r9"
    text        = "Order date / current enforcement status if an order has already been issued"
    kind        = FACT
    fact_type   = DOCUMENT_DETAIL
    fact_role   = ORDER_DATE_OR_ENFORCEMENT_STATUS
    accepted    = CONFIRMED
    absent_on_success = REQUIRES_VERIFICATION
```

Total: 5 + 5 + 5 + 5 + 9 = 29 requirement mappings. In order, they are the
complete verbatim `required_facts` lists of the five current workflows
(§10.3).

### 19.17 `EvidenceStatus`

Approve enum `EvidenceStatus` with exactly:

```text
UNKNOWN = "unknown"
PRESENT = "present"
MISSING = "missing"
REQUIRES_VERIFICATION = "requires_verification"
```

Phase-2 Step 8 has NO uploaded-document metadata input. Therefore Step 8
itself may emit ONLY `EvidenceStatus.UNKNOWN` for workflow evidence
requirements. `PRESENT` / `MISSING` are reserved for later integration when
concrete upload metadata exists. Do not infer `PRESENT` merely because a
notice references a document.

### 19.18 `EvidenceChecklistItem`

Approve dataclass `EvidenceChecklistItem` with exactly:

```text
evidence_id: str
requirement_text: str
status: EvidenceStatus
```

For each workflow `evidence_requirements` item, create one checklist item
using stable IDs `"<proceeding-prefix>.e1"`, `"<proceeding-prefix>.e2"`,
... `requirement_text` must equal the workflow string verbatim. During
current Phase 2 Step 8: `status = UNKNOWN` for all.

Step 8 creates NO `EvidenceGap` object from these `UNKNOWN` checklist
entries.

### 19.19 EvidenceGap deferral

`EvidenceGap` generation based on documents not uploaded — missing invoice,
missing return, missing bank record, referenced-but-not-uploaded annexure —
is explicitly DEFERRED until integration has an uploaded-document metadata
contract. Do not invent absence from notice text.

### 19.20 `ReviewLevel`

Approve enum `ReviewLevel` with exactly:

```text
CA_REVIEW = "ca_review"
SENIOR_CA_OR_ADVOCATE = "senior_ca_or_advocate"
URGENT_CA_REVIEW = "urgent_ca_review"
```

### 19.21 `ReviewRequirement`

Approve dataclass `ReviewRequirement` with exactly:

```text
review_id: str
level: ReviewLevel
reason: str
mandatory: bool = True
```

No filing decision field.

### 19.22 `DraftEligibility`

Approve enum `DraftEligibility` with exactly:

```text
ALLOWED = "allowed"
REVIEW_REQUIRED = "review_required"
BLOCKED = "blocked"
```

Meaning:

- `ALLOWED` — specialist AI draft generation may proceed.
- `REVIEW_REQUIRED` — specialist AI draft generation may proceed, but
  mandatory CA/senior/urgent review conditions must remain visible.
- `BLOCKED` — the specialist AI drafting LLM must NOT run.

None of these means: filing approved, legally valid, or CA review
unnecessary. Even `ALLOWED` output remains an AI working paper / CA-review
draft.

### 19.23 `ValidationItem`

Do NOT mutate the legacy `ValidationCheck` contract. Approve the new Step-8
dataclass `ValidationItem` with exactly:

```text
check_id: str
status: ValidationStatus
message: str
related_fact_ids: List[str]
related_calculation_types: List[ArithmeticCalculationType]
```

Status uses `ValidationStatus` (`PASS`, `WARNING`, `FAIL`). No LLM text
generation — messages are deterministic static templates.

`ValidationStatus.FAIL` semantics: `FAIL` means that a deterministic
validation, structural-safety, provenance, support, or drafting-gate check
failed. It does NOT mean:

```text
the GST notice is legally invalid
the department's allegation is false
the taxpayer is not liable
the officer lacks jurisdiction
the proceeding is void
```

`ValidationStatus` is product/workflow safety state, not a legal
conclusion. This applies to `ValidationItem.status` and to
`ValidationEngineResult.overall_status`.

### 19.24 `ValidationEngineResult`

Do NOT replace legacy `ValidationResult`. Approve the new:

```text
ValidationEngineResult
```

with exactly seven fields:

```text
overall_status: ValidationStatus
draft_eligibility: DraftEligibility
case_severity: Optional[IssueSeverity]

checks: List[ValidationItem]
requirements: List[RequirementResult]
evidence_checklist: List[EvidenceChecklistItem]
review_requirements: List[ReviewRequirement]
```

Do NOT include `PotentialDefence`. Do NOT include legal-validity fields.

### 19.25 Overall ValidationStatus aggregation

Deterministic dominance:

```text
any ValidationItem.status == FAIL      → overall_status = FAIL
else any ValidationItem.status == WARNING → overall_status = WARNING
else                                      → overall_status = PASS
```

Requirement/evidence/review conditions must create their corresponding
`ValidationItem` entries before aggregation. Overall status is never
calculated separately from the checks.

### 19.26 Draft eligibility aggregation

`BLOCKED` when ANY of these holds:

1. `classification.support_level != DEEP_WORKFLOW`
2. `classification.proceeding_type` has no registered `WorkflowDefinition`
3. `classification.proceeding_type` has no `WorkflowValidationProfile`
4. extraction status is `FAILED` or `NO_INPUT`
5. a structural safety invariant produces `ValidationStatus.FAIL`
6. arithmetic role provenance fails (§19.15)

Otherwise, if ANY of these holds:

- `overall_status == WARNING`
- extraction status == `PARTIAL`
- any requirement is `MISSING`, `UNKNOWN` or `REQUIRES_VERIFICATION`
- any evidence checklist item is `UNKNOWN`
- one or more `ReviewRequirement` objects exist

then `REVIEW_REQUIRED`. Else `ALLOWED`.

Specialist drafting may run for `ALLOWED` and `REVIEW_REQUIRED`. It must
NOT run for `BLOCKED`.

**Phase-2 ALLOWED reachability.** During the current Phase-2 contract,
`portal_verification_required = True` and
`authority_verification_required = True` are always produced by Preflight
(§18.6 / §18.8), and §19.30 maps each True verification requirement to
`ValidationStatus.WARNING`. Therefore, for a `DEEP_WORKFLOW` case that is
not `BLOCKED`, `DraftEligibility` will currently resolve to
`REVIEW_REQUIRED` rather than `ALLOWED`. This is intentional in Phase 2:
AI specialist drafting may still run, but mandatory human CA review
remains visible. `DraftEligibility.ALLOWED` is retained in the model for
future phases where verification state can be deterministically
resolved/cleared.

This does NOT weaken `portal_verification_required` or
`authority_verification_required` (they remain always True in Phase 2) and
does NOT remove `ALLOWED`.

### 19.27 Extraction health validation

```text
SUCCESS  → PASS extraction-health check
PARTIAL  → WARNING; positive validated facts remain usable;
           absence-based requirement conclusions remain UNKNOWN
FAILED   → FAIL; draft BLOCKED
NO_INPUT → FAIL; draft BLOCKED
```

### 19.28 Fact safety invariants

Step 8 re-checks, read-only:

1. `DEPARTMENT_ALLEGATION` must have `FactStatus.ALLEGED`.
2. `DEPARTMENT_ALLEGATION` must not have `DraftPermission.YES`.
3. `OTHER_NOTICE_FACT` must have `FactStatus.REQUIRES_VERIFICATION`.
4. `REQUIRES_VERIFICATION` must have `DraftPermission.NO`.
5. `CONFIRMED` must have `DraftPermission.YES`.
6. `ALLEGED` must have `DraftPermission.CONDITIONAL`.
7. every accepted fact: non-empty `fact_id`, non-empty `source_text`.
8. fact IDs must be unique.
9. `FactRole` compatibility from §19.5 must hold.

Violation: `ValidationStatus.FAIL` and draft `BLOCKED`. Step 8 does not
mutate facts to repair them.

### 19.29 Arithmetic safety invariants

Step 8 re-checks each supplied `ArithmeticResult`:

- calculation type belongs to the two-item whitelist (§18.23);
- `allowed_in_draft == CONDITIONAL`;
- `source_fact_ids` resolve uniquely;
- role provenance matches §19.15;
- result/status consistency:
  - `PASS` requires `result == 0`;
  - `MISMATCH` requires `result != 0`;
  - `INSUFFICIENT_DATA` requires `result is None`.

Violation: `FAIL`, `BLOCKED`.

Valid statuses map to `ValidationItem` status as:

```text
MISMATCH           → WARNING
INSUFFICIENT_DATA  → WARNING
PASS               → PASS
```

Step 8 does NOT recompute the arithmetic result.

### 19.30 Preflight validation mappings

```text
portal_verification_required == True  → WARNING
    "GST portal identifier/authenticity verification is required."

authority_verification_required == True → WARNING
    "Issuing-authority competence/jurisdiction requires CA/legal verification."

CommunicationIdentifierStatus.UNKNOWN → WARNING
AuthorityDetailsStatus.UNKNOWN        → WARNING
DeadlineConflictStatus.CONFLICT       → WARNING
DeadlineConflictStatus.CANNOT_COMPARE → WARNING only when
    stated_due_date_fact_ids is non-empty OR deadline_result is not None
```

Do not mark the notice invalid.

### 19.31 Deadline safety mapping

Step 8 never recalculates deadlines.

If `deadline_result` is None: no deadline-status `ValidationItem`.

If supplied:

```text
DeadlineStatus.PASSED   → WARNING; case_severity = CRITICAL;
                          mandatory ReviewRequirement level = URGENT_CA_REVIEW
DeadlineStatus.CRITICAL → WARNING; case_severity = CRITICAL;
                          mandatory ReviewRequirement level = URGENT_CA_REVIEW
DeadlineStatus.UPCOMING → PASS
DeadlineStatus.UNKNOWN  → WARNING
```

Hearing:

```text
HearingStatus.PASSED  → WARNING
HearingStatus.UPCOMING → PASS
```

Deadline status is never converted into legal validity.

### 19.32 Case severity

If a DEEP workflow exists: start with `workflow.default_severity`. If
deadline status is `CRITICAL` or `PASSED`:
`case_severity = IssueSeverity.CRITICAL`. Otherwise keep the workflow
default.

For `TRIAGE_ONLY` / `UNKNOWN` with no deep workflow: `case_severity =
CRITICAL` only if the supplied deadline status is `CRITICAL` or `PASSED`;
otherwise `case_severity = None`.

Severity does not override `DraftEligibility` rules.

### 19.33 `SpecialRuleHandling`

Approve enum `SpecialRuleHandling` with exactly:

```text
DETERMINISTIC_CHECK = "deterministic_check"
REVIEW_GATE = "review_gate"
UPSTREAM_INVARIANT = "upstream_invariant"
FUTURE_LEGAL_RULE = "future_legal_rule"
```

A workflow special rule may map to ONE OR MORE handling types. Every
safety-critical special rule must have at least one handling mapping. No
special rule may remain unmapped.

### 19.34 `WorkflowValidationProfile`

Approve dataclass `WorkflowValidationProfile` with exactly:

```text
proceeding_type: ProceedingType
requirement_specs: List[WorkflowRequirementSpec]
special_rule_handling: Dict[int, Tuple[SpecialRuleHandling, ...]]
review_rules: Dict[int, ReviewLevel]
```

Indices in `special_rule_handling` / `review_rules` are zero-based indices
into the workflow's exact `special_rules` list. Each current special rule
index must be mapped. The Phase-2 registry contains exactly five profiles,
one per deep workflow, keyed by `ProceedingType`.

In the mappings below, `REVIEW_GATE (LEVEL)` means
`special_rule_handling[index]` contains `REVIEW_GATE` and
`review_rules[index] = LEVEL`.

### 19.35 Special-rule mapping — GST_SEC73_ITC

```text
index 0 — REVIEW_GATE (CA_REVIEW)
    rule: "A GSTR-3B versus GSTR-2B mismatch is not by itself proof that the ITC is legally ineligible."

index 1 — DETERMINISTIC_CHECK
    rule: "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts."

index 2 — REVIEW_GATE (CA_REVIEW)
    rule: "Never assume invoices, receipt of goods or services, supplier compliance, or payment to suppliers unless supported by evidence."

index 3 — REVIEW_GATE (CA_REVIEW)
    rule: "Final ITC eligibility is a legal/factual conclusion requiring evidence and CA review."
```

### 19.36 Special-rule mapping — GST_SEC73_GENERAL

```text
index 0 — REVIEW_GATE (CA_REVIEW)
    rule: "A return mismatch is not by itself an admission of tax short-payment."

index 1 — DETERMINISTIC_CHECK
    rule: "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts."

index 2 — REVIEW_GATE (CA_REVIEW)
    rule: "Credit notes, amendments, timing differences and other reconciliation items must be checked before reaching a liability conclusion."

index 3 — REVIEW_GATE (CA_REVIEW)
    rule: "The workflow identifies reconciliation requirements; it does not itself establish legal liability."
```

### 19.37 Special-rule mapping — GST_SEC73_RCM

```text
index 0 — REVIEW_GATE (CA_REVIEW)
    rule: "Do not assume that every payment appearing under a TDS or professional-services category is subject to GST reverse charge."

index 1 — FUTURE_LEGAL_RULE + REVIEW_GATE (CA_REVIEW)
    rule: "Service category and RCM applicability require verification from underlying documents and current legal sources."

index 2 — REVIEW_GATE (CA_REVIEW)
    rule: "Form 26AS or TDS data may be evidentiary input but is not by itself conclusive proof of GST RCM liability."

index 3 — REVIEW_GATE (CA_REVIEW)
    rule: "Do not assume ITC availability, revenue neutrality, or entitlement without verifying the taxpayer's facts and applicable law."
```

### 19.38 Special-rule mapping — GST_SEC74_FRAUD

```text
index 0 — DETERMINISTIC_CHECK
    rule: "Fraud, wilful misstatement and suppression must remain departmental allegations unless established by evidence."

index 1 — REVIEW_GATE (SENIOR_CA_OR_ADVOCATE)
    rule: "Never state that fraud is present or absent as an established fact without evidentiary support."

index 2 — DETERMINISTIC_CHECK
    rule: "Preserve the provenance of third-party or external data relied upon by the department."

index 3 — REVIEW_GATE (SENIOR_CA_OR_ADVOCATE)
    rule: "Mandatory senior CA / advocate review is required before filing."

index 4 — UPSTREAM_INVARIANT
    rule: "This workflow applies only where the notice expressly invokes Section 74; it must not be used as a substitute for Section 74A."
```

At least one `SENIOR_CA_OR_ADVOCATE` `ReviewRequirement` is mandatory for
every `GST_SEC74_FRAUD` deep case.

### 19.39 Special-rule mapping — GST_SEC129_ENFORCE

```text
index 0 — REVIEW_GATE (CA_REVIEW)
    rule: "Never assume the tax invoice is valid; invoice validity remains REQUIRES_VERIFICATION until supported by evidence."

index 1 — REVIEW_GATE (CA_REVIEW)
    rule: "Never invent a reason for a missing or defective E-Way Bill."

index 2 — UPSTREAM_INVARIANT
    rule: "Do not hardcode a 100% penalty assumption; extract the proposed penalty and defer statutory computation to the deterministic arithmetic/legal-rule layer."

index 3 — UPSTREAM_INVARIANT
    rule: "Do not treat the Section 129 seven-day statutory notice/order timeline as a universal taxpayer reply deadline."

index 4 — REVIEW_GATE (CA_REVIEW)
    rule: "MOV-09 is a departmental order and must never be described as the taxpayer's reply form."

index 5 — UPSTREAM_INVARIANT
    rule: "A Section-130-only proceeding does not use this deep workflow and remains TRIAGE_ONLY until a separate workflow exists."

index 6 — DETERMINISTIC_CHECK + REVIEW_GATE (URGENT_CA_REVIEW)
    rule: "Active detention/seizure requires urgent CA escalation, but deadline status must come from the deterministic Deadline Engine and explicit procedural dates."
```

Every `GST_SEC129_ENFORCE` deep case therefore receives an
`URGENT_CA_REVIEW` `ReviewRequirement`.

The five mappings above cover all 24 current workflow special rules
(4 + 4 + 4 + 5 + 7); every rule index is mapped.

### 19.40 Special-rule execution policy

- `REVIEW_GATE`: create a `ReviewRequirement` using the `review_rules`
  mapping.
- `FUTURE_LEGAL_RULE`: create a deterministic WARNING:
  `"This workflow rule requires future verified legal-rule support and CA review."`
  It must also have `REVIEW_GATE` in the current five profiles.
- `UPSTREAM_INVARIANT`: re-check the applicable upstream invariant where a
  deterministic structured input exists. If the invariant cannot be
  rechecked without prohibited source-code introspection: emit a `PASS`
  informational check that names the upstream enforced boundary. Do NOT
  re-run classification or arithmetic.
- `DETERMINISTIC_CHECK`: execute only checks explicitly defined by the
  Step-8 contract (§19.41). Do NOT attempt to interpret free-text
  `special_rules` generically.

Profiles are authoritative mappings.

### 19.41 Deterministic special checks

Approved Step-8 deterministic checks:

A. Difference-derived rules: a requirement is marked `DERIVED` only from a
   valid `ArithmeticResult`.
B. Fraud allegation rule: `FRAUD_BASIS_ALLEGED` and
   `DEPARTMENT_ALLEGED_AMOUNT` facts must remain `FactStatus.ALLEGED`.
C. Fraud third-party provenance rule: all facts still require `source_text`;
   Step 8 re-checks provenance.
D. Section-74A exclusion: the `GST_SEC74_FRAUD` profile is valid only when
   `classification.proceeding_type == GST_SEC74_FRAUD`. The classifier's
   Section-74A hard block remains authoritative.
E. Section-130 exclusion: the `GST_SEC129_ENFORCE` profile is valid only
   when `classification.proceeding_type == GST_SEC129_ENFORCE`.
   Section-130-only classification must remain outside deep workflow.
F. Section-129 deadline source: Step 8 uses only the supplied
   `DeadlineResult` / `PreflightResult`. It invents no seven-day taxpayer
   reply rule.

No other legal check is authorized.

### 19.42 ReviewRequirement deduplication

Deduplicate `ReviewRequirement` objects by `(level, reason)` while
preserving first-occurrence order. Do not merge different review levels.

### 19.43 Evidence checklist effect

Because every current Phase-2 evidence checklist entry is `UNKNOWN`, deep
workflows will normally have `DraftEligibility.REVIEW_REQUIRED`. This is
intentional: it means an AI draft may be generated for CA review, not that
evidence is complete. Do not treat `UNKNOWN` evidence as `FAIL`.

### 19.44 TRIAGE_ONLY

For `SupportLevel.TRIAGE_ONLY`, run generic validation:

```text
extraction-health
fact invariants
preflight checks
deadline checks
arithmetic safety if results were supplied
```

Do NOT load a deep `WorkflowValidationProfile`, run `required_facts`
completeness, or invent evidence requirements.

Add support-gate FAIL:

```text
"Specialist deep-workflow drafting is unavailable for this recognized notice."
```

`DraftEligibility`: `BLOCKED`. Generic triage rendering remains allowed
outside the specialist drafting LLM.

### 19.45 UNKNOWN support / proceeding

For `SupportLevel.UNKNOWN` or `ProceedingType.UNKNOWN`: run generic
validation where structured data exists. No deep workflow/profile. Add the
same support-gate FAIL. `DraftEligibility`: `BLOCKED`. Do not invent a
workflow fallback.

### 19.46 Deep workflow supported-gate

For `SupportLevel.DEEP_WORKFLOW`, validation requires:

1. `get_workflow(classification.proceeding_type)` exists
2. a `WorkflowValidationProfile` exists
3. `workflow.proceeding_type` matches `classification.proceeding_type`
4. `profile.proceeding_type` matches `classification.proceeding_type`
5. number/order/text of `requirement_specs` exactly matches
   `workflow.required_facts`
6. every `special_rules` index has at least one handling mapping

Failure: `ValidationStatus.FAIL` and `DraftEligibility.BLOCKED`. No
fallback to `SEC73_GENERAL`.

### 19.47 issue_types

Step 8 does NOT create issue instances. `workflow.issue_types` remain
static metadata/questions for Step 9. No liability conclusion is derived
from them.

### 19.48 Default severity

Step 8 uses `workflow.default_severity` only for `case_severity` (§19.32).
It is not automatically copied onto every `ValidationItem`.

### 19.49 PotentialDefence

Step 8 creates ZERO `PotentialDefence` objects. `PotentialDefence` remains
a Step-9 deep reasoning/drafting artifact. Validation must not invent legal
defences.

### 19.50 Fact conflicts — explicitly deferred

General semantic fact-conflict detection is DEFERRED beyond the minimum
Phase-2 Step 8 implementation. Do NOT attempt generic conflict NLP.
Existing specialized deterministic conflict handling remains
`PreflightResult.deadline_conflict_status`. No new FactConflict model in
Step 8A.

### 19.51 Semantic deduplication — explicitly deferred

Step 8 does NOT merge semantically duplicate facts. Do not destroy
provenance. Fact ID uniqueness is checked as a safety invariant (§19.28).
General semantic consolidation is future integration work.

### 19.52 Legacy validation models

Do NOT modify or remove:

```text
ValidationCheck
ValidationResult
EvidenceGap
PotentialDefence
```

They remain compatibility artifacts. Step 8 uses the new Step-8-specific
models.

### 19.53 Step 9 gate

This subsection amends the Step-9 architecture contract (§13). Before a
specialist drafting LLM call, `ValidationEngineResult.draft_eligibility`
must be checked:

- `BLOCKED` — do NOT call the specialist drafting LLM.
- `REVIEW_REQUIRED` / `ALLOWED` — specialist drafting may run only for
  `SupportLevel.DEEP_WORKFLOW`.

Step 9 receives:

```text
classification
extraction_result / facts
preflight_result
arithmetic_results
workflow
ValidationEngineResult
```

For `REVIEW_REQUIRED` output: mandatory review requirements and unresolved
requirement/evidence states must be carried into the working paper / draft
context. No validation result means no specialist drafting call.

### 19.54 Implementation split

After Step 8A:

```text
Step 6.4
    Add DOCUMENT_DETAIL
    Add FactRole
    Add ExtractedFact.fact_role
    Update Fact Engine candidate contract / role compatibility
    Preserve prior APIs

Step 8.1
    Add Step-8 enums/dataclasses
    Add authoritative workflow validation-profile registry
    Contract tests only

Step 8.2
    Implement generic deterministic validation:
        support gate
        extraction health
        fact invariants
        preflight checks
        deadline checks
        arithmetic safety
        special review gates

Step 8.3
    Implement deterministic workflow requirement completeness
    and arithmetic-role mapping.

Step 8.4
    Add evidence checklist generation
    + final ValidationEngineResult aggregation / DraftEligibility.
```

Each separate commit.

### 19.55 No Step-8 LLM

Reaffirm: Step 8 adds ZERO LLM calls. Do not use model semantic matching
for required facts, evidence, special rules, fact roles or arithmetic
roles. All mappings are closed deterministic contracts.

### 19.56 Step 8B machine-contract amendment — scope

Step 8.1 committed the Step-8 models and the five workflow validation
profiles. Before Step 8.2 may implement `run_validation`, the following
machine contracts must be closed:

- `ValidationItem.check_id` values are stable, architecture-owned machine
  identifiers with a general rule (§19.57) and a closed catalog
  (§19.58–§19.62);
- arithmetic checks use indexed templates, not free-form IDs
  (§19.64–§19.65);
- workflow special-rule checks use profile-anchored templates
  (§19.66–§19.71);
- `ReviewRequirement.review_id` / `reason` are deterministic (§19.63,
  §19.68);
- Step 8.2 behavior is staged while Steps 8.3/8.4 remain unfinished
  (§19.72–§19.75).

These IDs are externally testable/stable machine contracts. Step 8.2 MUST
NOT invent them. This amendment defines IDs/templates only; no model,
enum, profile or workflow mapping changes (§19.78).

### 19.57 `ValidationItem.check_id` general rule

`ValidationItem.check_id` is a stable architecture-owned machine
identifier. Rules:

- lowercase ASCII;
- dot-separated;
- no spaces;
- no user/notice text inside an ID;
- deterministic: the same validation rule always uses the same ID /
  template;
- human-readable wording belongs in `ValidationItem.message`;
- related facts and calculation types belong in their dedicated fields
  (`related_fact_ids`, `related_calculation_types`).

Do not generate random IDs.

### 19.58 Support-gate check IDs

Fixed support-gate IDs:

```text
support.level
support.workflow_registered
support.profile_registered
support.workflow_alignment
support.profile_alignment
support.requirement_alignment
support.special_rule_coverage
```

`support.level` validates `SupportLevel` / specialist-drafting
availability:

```text
TRIAGE_ONLY → FAIL
    "Specialist deep-workflow drafting is unavailable for this recognized notice."

SupportLevel.UNKNOWN OR ProceedingType.UNKNOWN → FAIL
    "Specialist deep-workflow drafting is unavailable because the notice classification is unsupported or unknown."

valid DEEP_WORKFLOW → PASS
    "Deep workflow support is available for the classified proceeding."
```

The remaining six support checks are emitted only when
`support_level == DEEP_WORKFLOW`. They implement §19.46 exactly:

```text
support.workflow_registered
    PASS: "A deep WorkflowDefinition is registered for the classified proceeding."
    FAIL: "No deep WorkflowDefinition is registered for the classified proceeding."

support.profile_registered
    PASS: "A WorkflowValidationProfile is registered for the classified proceeding."
    FAIL: "No WorkflowValidationProfile is registered for the classified proceeding."

support.workflow_alignment
    PASS: "WorkflowDefinition proceeding type matches the classification."
    FAIL: "WorkflowDefinition proceeding type does not match the classification."

support.profile_alignment
    PASS: "WorkflowValidationProfile proceeding type matches the classification."
    FAIL: "WorkflowValidationProfile proceeding type does not match the classification."

support.requirement_alignment
    PASS: "Workflow requirement profile matches the workflow required-facts contract."
    FAIL: "Workflow requirement profile does not match the workflow required-facts contract."

support.special_rule_coverage
    PASS: "Every workflow special rule has an authoritative validation/review handling mapping."
    FAIL: "One or more workflow special rules lack an authoritative handling mapping."
```

Any FAIL from these checks blocks specialist drafting. No fallback
workflow is permitted.

### 19.59 Extraction health check ID

Fixed ID:

```text
extraction.status
```

Exact mappings:

```text
SUCCESS → PASS
    "Fact extraction completed successfully."

PARTIAL → WARNING
    "Fact extraction was partial; validated positive facts remain usable but absence-based conclusions are not reliable."

FAILED → FAIL
    "Fact extraction failed; specialist drafting is blocked."

NO_INPUT → FAIL
    "No usable notice text was available for fact extraction; specialist drafting is blocked."
```

### 19.60 Fact-invariant check IDs

Fixed IDs:

```text
fact.department_allegation_status
fact.department_allegation_draft_permission
fact.other_notice_fact_status
fact.requires_verification_draft_permission
fact.confirmed_draft_permission
fact.alleged_draft_permission
fact.fact_id_present
fact.source_text_present
fact.fact_id_unique
fact.role_compatibility
```

One `ValidationItem` is produced per invariant (§19.28 checks 1–9).

`related_fact_ids`:

```text
PASS → []
FAIL → IDs of all offending facts in extraction order
```

Special rules:

- `fact.fact_id_present`: facts whose `fact_id` is empty cannot contribute
  a usable ID. `related_fact_ids` therefore contains the non-empty IDs of
  offending facts when any exist; the message must still report the
  failure even when the `related_fact_ids` list is empty.
- `fact.fact_id_unique`: `related_fact_ids` contains duplicated non-empty
  IDs once each, preserving first duplicate-detection order.

Message templates:

```text
PASS: "<invariant description> is satisfied."
FAIL: "<invariant description> failed."
```

Invariant descriptions:

```text
fact.department_allegation_status            "Department-allegation status invariant"
fact.department_allegation_draft_permission  "Department-allegation draft-permission invariant"
fact.other_notice_fact_status                "Other-notice-fact status invariant"
fact.requires_verification_draft_permission  "Requires-verification draft-permission invariant"
fact.confirmed_draft_permission              "Confirmed-fact draft-permission invariant"
fact.alleged_draft_permission                "Alleged-fact draft-permission invariant"
fact.fact_id_present                         "Fact-ID presence invariant"
fact.source_text_present                     "Fact source-text presence invariant"
fact.fact_id_unique                          "Fact-ID uniqueness invariant"
fact.role_compatibility                      "FactRole compatibility invariant"
```

Every violation is `ValidationStatus.FAIL` and
`DraftEligibility.BLOCKED`. No mutation/repair.

### 19.61 Preflight check IDs

Fixed IDs:

```text
preflight.portal_verification
preflight.authority_verification
preflight.communication_identifier
preflight.authority_details
preflight.deadline_conflict
```

```text
portal_verification_required == True → WARNING
    "GST portal identifier/authenticity verification is required."
portal_verification_required == False → PASS
    "GST portal identifier/authenticity verification is not currently flagged by preflight."

authority_verification_required == True → WARNING
    "Issuing-authority competence/jurisdiction requires CA/legal verification."
authority_verification_required == False → PASS
    "Issuing-authority verification is not currently flagged by preflight."

CommunicationIdentifierStatus.UNKNOWN → WARNING
    "Communication identifier status is UNKNOWN."
any other CommunicationIdentifierStatus value → PASS
    "Communication identifier status is available."

AuthorityDetailsStatus.UNKNOWN → WARNING
    "Authority details status is UNKNOWN."
any other AuthorityDetailsStatus value → PASS
    "Authority details status is available."

DeadlineConflictStatus.CONFLICT → WARNING
    "The notice-stated due date conflicts with the calculated response deadline."

DeadlineConflictStatus.CANNOT_COMPARE:
    if stated_due_date_fact_ids is non-empty OR deadline_result is not None → WARNING
        "The notice-stated due date and calculated response deadline cannot be reliably compared."
    otherwise → PASS
        "No deadline comparison is currently available or required."

DeadlineConflictStatus.MATCH → PASS
    "The notice-stated due date matches the calculated response deadline."
```

No legal-validity conclusion.

### 19.62 Deadline and hearing check IDs

If `deadline_result` is None: emit no `deadline.status` and no
`hearing.status`.

If supplied:

```text
deadline.status

    DeadlineStatus.UPCOMING → PASS
        "The calculated response deadline is upcoming."
    DeadlineStatus.CRITICAL → WARNING
        "The calculated response deadline is critical."
    DeadlineStatus.PASSED → WARNING
        "The calculated response deadline has passed."
    DeadlineStatus.UNKNOWN → WARNING
        "The calculated response deadline is unknown."

hearing.status

    HearingStatus.UPCOMING → PASS
        "The scheduled hearing is upcoming."
    HearingStatus.TODAY → WARNING
        "The scheduled hearing is today."
    HearingStatus.PASSED → WARNING
        "The scheduled hearing has passed."
    HearingStatus.NOT_SCHEDULED → PASS
        "No hearing is currently scheduled in the DeadlineResult."
```

Do NOT calculate dates.

### 19.63 Deadline urgent-review contract

```text
DeadlineStatus.CRITICAL →
    review_id = "deadline.urgent_review"
    level = ReviewLevel.URGENT_CA_REVIEW
    reason = "Deadline status is CRITICAL; urgent CA review is required."
    mandatory = True

DeadlineStatus.PASSED →
    review_id = "deadline.urgent_review"
    level = ReviewLevel.URGENT_CA_REVIEW
    reason = "Deadline status is PASSED; urgent CA review is required."
    mandatory = True
```

No deadline review for `UPCOMING` / `UNKNOWN`. Case severity behavior
remains exactly §19.32.

### 19.64 Arithmetic check-ID templates

For each `ArithmeticResult` in input order, use one-based index N:

```text
arithmetic.{N}.calculation_type
arithmetic.{N}.draft_permission
arithmetic.{N}.source_resolution
arithmetic.{N}.role_provenance
arithmetic.{N}.result_status_consistency
arithmetic.{N}.outcome
```

Examples:

```text
arithmetic.1.calculation_type
arithmetic.1.role_provenance
arithmetic.2.outcome
```

N is input-list position starting at 1. Do NOT derive N from calculation
type: duplicate calculation types are allowed as input and must be
detected later rather than collapsed.

`related_calculation_types`:

```text
result.calculation_type is a valid ArithmeticCalculationType → [result.calculation_type]
otherwise → []
```

`related_fact_ids`:

```text
source-resolution / role-provenance checks →
    result.source_fact_ids in stored order, restricted to valid non-empty strings
all other arithmetic checks → []
```

### 19.65 Arithmetic check semantics

```text
arithmetic.{N}.calculation_type
    valid approved ArithmeticCalculationType → PASS
        "Arithmetic calculation type is approved."
    otherwise → FAIL
        "Arithmetic calculation type is unsupported."

arithmetic.{N}.draft_permission
    CONDITIONAL → PASS
        "Arithmetic draft permission is CONDITIONAL."
    otherwise → FAIL
        "Arithmetic draft permission must be CONDITIONAL."

arithmetic.{N}.source_resolution
    all source_fact_ids resolve uniquely to extraction facts → PASS
        "Arithmetic source facts resolve uniquely."
    otherwise → FAIL
        "Arithmetic source facts do not resolve uniquely."

arithmetic.{N}.role_provenance
    roles match §19.15 exactly → PASS
        "Arithmetic operand FactRoles match the approved calculation contract."
    otherwise → FAIL
        "Arithmetic operand FactRoles do not match the approved calculation contract."

arithmetic.{N}.result_status_consistency
    PASS + result == Decimal("0")
    OR MISMATCH + result is not None and result != Decimal("0")
    OR INSUFFICIENT_DATA + result is None
        → PASS
        "Arithmetic status and result are internally consistent."
    otherwise → FAIL
        "Arithmetic status and result are internally inconsistent."

arithmetic.{N}.outcome
    ArithmeticStatus.PASS → PASS
        "Arithmetic result matches."
    ArithmeticStatus.MISMATCH → WARNING
        "Arithmetic result is a mismatch."
    ArithmeticStatus.INSUFFICIENT_DATA → WARNING
        "Arithmetic result has insufficient data."
```

Structural arithmetic FAIL always blocks drafting. Do not recompute the
result.

### 19.66 Workflow special-rule check-ID template

For a workflow special rule at zero-based index I and handling H:

```text
workflow.<PREFIX>.special_rule.<I>.<H>
```

PREFIX values are exactly:

```text
sec73_itc
sec73_general
sec73_rcm
sec74_fraud
sec129
```

H is exactly the `SpecialRuleHandling` enum value:

```text
deterministic_check
review_gate
upstream_invariant
future_legal_rule
```

Examples:

```text
workflow.sec74_fraud.special_rule.1.review_gate
workflow.sec73_rcm.special_rule.1.future_legal_rule
workflow.sec129.special_rule.6.review_gate
```

Indices remain zero-based because `WorkflowValidationProfile` mappings
are zero-based.

### 19.67 Review-gate validation items

For every `REVIEW_GATE` handling:

```text
status = WARNING
check_id = workflow.<PREFIX>.special_rule.<I>.review_gate
message = "Mandatory review gate applies: <SPECIAL_RULE_TEXT>"
related_fact_ids = []
related_calculation_types = []
```

`<SPECIAL_RULE_TEXT>` is the exact corresponding
`WorkflowDefinition.special_rules[I]` string.

This WARNING ensures review conditions participate in overall
aggregation.

### 19.68 ReviewRequirement ID / reason contract

For every `REVIEW_GATE`:

```text
review_id = workflow.<PREFIX>.special_rule.<I>.review
level = exact WorkflowValidationProfile.review_rules[I]
reason = exact WorkflowDefinition.special_rules[I]
mandatory = True
```

Do not paraphrase `reason`. This gives review requirements stable machine
IDs while preserving the authoritative workflow rule as the human reason.

### 19.69 FUTURE_LEGAL_RULE item

For `FUTURE_LEGAL_RULE`:

```text
check_id = workflow.<PREFIX>.special_rule.<I>.future_legal_rule
status = WARNING
message = "This workflow rule requires future verified legal-rule support and CA review."
```

No legal inference. The same rule currently also has `REVIEW_GATE`, so a
`ReviewRequirement` is created separately by the §19.68 review-gate
rules.

### 19.70 UPSTREAM_INVARIANT item

For `UPSTREAM_INVARIANT`:

```text
check_id = workflow.<PREFIX>.special_rule.<I>.upstream_invariant
```

If Step 8.2 has an explicitly authorized structured recheck: perform it.

If rechecking would require source-code introspection, natural-language
interpretation, legal inference, or re-running classifier/arithmetic:

```text
status = PASS
message = "This safety boundary is enforced by an authoritative upstream component and is not re-run by validation."
```

Do not inspect source files at runtime.

### 19.71 DETERMINISTIC_CHECK item

For `DETERMINISTIC_CHECK`:

```text
check_id = workflow.<PREFIX>.special_rule.<I>.deterministic_check
```

Step 8.2 may perform ONLY the deterministic special checks explicitly
authorized by §19.41. Do not interpret `special_rule` text generically.

Where a §19.41 check is already covered by another generic
`ValidationItem`, the special-rule item may report `PASS` only if that
corresponding generic check passed. If the corresponding generic check
failed: special-rule item = `FAIL`.

No duplicate re-calculation.

### 19.72 ReviewRequirement deduplication

Preserve §19.42: deduplicate by `(level, reason)`, preserving first
occurrence. When duplicates collapse, keep the `review_id` of the first
occurrence.

### 19.73 Staged Step-8.2 run_validation contract

Step 8.2 WILL introduce the architecture-approved public (§19.7):

```text
run_validation(
    classification,
    extraction_result,
    preflight_result,
    arithmetic_results,
    deadline_result=None
) -> ValidationEngineResult
```

Steps 8.3 and 8.4 remain unfinished. Therefore during Step 8.2 ONLY:

```text
requirements = []
evidence_checklist = []
```

This is an explicitly temporary staged implementation state.

Step 8.2 MUST implement:

- support gate
- extraction health
- fact invariants
- preflight checks
- deadline/hearing checks
- arithmetic safety
- special-rule handling/review gates
- ReviewRequirement dedup
- overall ValidationStatus aggregation
- case_severity
- DraftEligibility using only conditions currently available

Step 8.2 MUST NOT implement:

- WorkflowRequirementSpec resolution
- SATISFIED/MISSING/UNKNOWN requirement results
- evidence checklist generation
- EvidenceGap generation

Step 8.3 will populate `requirements`; Step 8.4 will populate
`evidence_checklist` and finalize the complete aggregation behavior.

### 19.74 Interim integration prohibition

Until Step 8.4 is complete, `domain/validation_engine.py` must NOT be
wired into:

```text
app.py
modules/notice_explainer.py
specialist Step-9 drafting
production rendering
```

The staged Step-8.2 `ValidationEngineResult` is testable architecture
work, not yet the final integrated validation surface. This prevents
empty requirements/evidence lists from being interpreted as "complete".

### 19.75 Interim Step-8.2 DraftEligibility

During Step 8.2: `BLOCKED` when any existing §19.26 blocking condition
that is currently implementable holds, including:

- support level != DEEP_WORKFLOW
- missing workflow/profile
- structural support-gate failure
- extraction FAILED / NO_INPUT
- fact invariant FAIL
- arithmetic structural FAIL

Otherwise: because preflight verification flags are always True in
current Phase 2, the result will normally be `REVIEW_REQUIRED`, as
already clarified by §19.26.

Do NOT artificially create `ALLOWED`. Do NOT use empty
requirements/evidence lists to infer completeness.

### 19.76 Overall status aggregation

Preserve §19.25 deterministic aggregation exactly:

```text
any FAIL        → FAIL
else any WARNING → WARNING
else             → PASS
```

Every review gate generates a WARNING item before aggregation.

### 19.77 FAIL semantics

Reaffirm §19.23: `ValidationStatus.FAIL` means the product/workflow/
drafting safety gate failed. It does NOT mean:

```text
notice legally invalid
department allegation false
taxpayer not liable
officer lacks jurisdiction
proceeding void
```

### 19.78 No new Step-8B model

Do NOT add or change:

- enums
- dataclasses
- FactRole
- WorkflowValidationProfile
- validation profiles
- workflow definitions

Step 8B defines IDs/templates only.

### 19.79 Zero LLM

Reaffirm: the Step 8.2 Validation Engine is pure deterministic Python.

No:

```text
modules.llm_client
Gemini
network
legal research
semantic matching
```

### 19.80 Contract counts preserved

Step 8B changes no mapping content:

```text
FactRole members = 22
workflow requirement mappings = 29
workflow special-rule mappings = 24
validation profiles = 5
```

### 19.81 Step-8.2 derived-rule deferral (SEC73 ITC / GENERAL)

Step 8.2 special-rule handling must process the workflow
`DETERMINISTIC_CHECK` mappings (§19.40, §19.71). Exactly five such
mappings exist today:

```text
GST_SEC73_ITC      index 1
GST_SEC73_GENERAL  index 1
GST_SEC74_FRAUD    index 0
GST_SEC74_FRAUD    index 2
GST_SEC129_ENFORCE index 6
```

Two of the five concern the workflow's DERIVED difference requirement,
whose resolution is owned by Step 8.3 (§19.73). Step 8.2 must NOT invent
completeness logic early for them.

During Step 8.2 ONLY, for `GST_SEC73_ITC` special rule index 1:

```text
check_id = workflow.sec73_itc.special_rule.1.deterministic_check
status = WARNING
message = "Derived workflow validation is deferred until Step 8.3 requirement resolution."
related_fact_ids = []
related_calculation_types = [ArithmeticCalculationType.ITC_DIFFERENCE]
```

During Step 8.2 ONLY, for `GST_SEC73_GENERAL` special rule index 1:

```text
check_id = workflow.sec73_general.special_rule.1.deterministic_check
status = WARNING
message = "Derived workflow validation is deferred until Step 8.3 requirement resolution."
related_fact_ids = []
related_calculation_types = [ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE]
```

Step 8.2 must NOT decide whether the workflow requirement is:

```text
DERIVED
UNKNOWN
MISSING
SATISFIED
```

Requirement resolution stays with Step 8.3.

### 19.82 Step-8.3 replacement rule

When Step 8.3 is implemented, the temporary WARNING behavior of §19.81
is REPLACED under the SAME stable check IDs:

```text
workflow.sec73_itc.special_rule.1.deterministic_check
workflow.sec73_general.special_rule.1.deterministic_check
```

Step 8.3 will use the authoritative requirement-resolution contract
(§19.16, §19.41-A) to determine the real PASS / FAIL / WARNING behavior
of the two derived checks.

The temporary warning must NOT survive after Step 8.3 implements those
derived requirements.

This patch does NOT define Step-8.3 implementation details.

### 19.83 Fraud rule 0 — status safety (GST_SEC74_FRAUD index 0)

During Step 8.2, for `GST_SEC74_FRAUD` special rule index 0, the
corresponding deterministic check is the already-emitted generic fact
invariant `fact.department_allegation_status` (§19.60). Do NOT re-run the
fact invariant.

```text
check_id = workflow.sec74_fraud.special_rule.0.deterministic_check

if fact.department_allegation_status == PASS:
    status = PASS
    message = "Fraud/suppression allegations remain departmental allegations."

if fact.department_allegation_status == FAIL:
    status = FAIL
    message = "Fraud/suppression allegation status safety failed."

related_fact_ids =
    same offending fact IDs as the corresponding generic check when FAIL,
    otherwise [].
related_calculation_types = []
```

### 19.84 Fraud rule 2 — provenance safety (GST_SEC74_FRAUD index 2)

During Step 8.2, for `GST_SEC74_FRAUD` special rule index 2, the
corresponding deterministic check is the already-emitted generic fact
invariant `fact.source_text_present` (§19.60). Do NOT re-run provenance
logic.

```text
check_id = workflow.sec74_fraud.special_rule.2.deterministic_check

if fact.source_text_present == PASS:
    status = PASS
    message = "Fraud-workflow fact provenance is present."

if fact.source_text_present == FAIL:
    status = FAIL
    message = "Fraud-workflow fact provenance safety failed."

related_fact_ids =
    same offending IDs as fact.source_text_present when FAIL,
    otherwise [].
related_calculation_types = []
```

### 19.85 Section-129 rule 6 — deadline-source boundary

During Step 8.2, for `GST_SEC129_ENFORCE` special rule index 6, the
deterministic check is an architectural-boundary assertion (§19.41-F):

```text
check_id = workflow.sec129.special_rule.6.deterministic_check
status = PASS
message = "Section-129 deadline handling uses only supplied preflight/deadline results; validation adds no statutory deadline calculation."
related_fact_ids = []
related_calculation_types = []
```

This rule does NOT authorize a new date calculation. The Validation
Engine must use ONLY:

```text
supplied PreflightResult
supplied optional DeadlineResult
```

for deadline/hearing validation. It must NOT:

```text
import deadline_engine
calculate a seven-day deadline
infer a statutory response period
derive a deadline from Section 129 text
inspect free-text special_rule content
```

The truth of this PASS must additionally be pinned by Step-8.2 purity
tests confirming that `validation_engine.py` does not import or call
`deadline_engine`.

The same special rule index also has `REVIEW_GATE`
(`URGENT_CA_REVIEW`, §19.39), so its separate review item
(`workflow.sec129.special_rule.6.review_gate`, §19.67) and
`ReviewRequirement` (§19.68) remain unchanged.

### 19.86 No other special-rule changes

This patch defines Step-8.2 execution semantics for the five current
`DETERMINISTIC_CHECK` mappings only. It does NOT change:

```text
special_rule_handling mappings
review_rules
workflow text
requirement mappings
check-ID templates
review-ID templates
```

### 19.87 Staged status clarification

The two derived-rule temporary warnings (§19.81) contribute to
`ValidationEngineResult.overall_status` normally (§19.25, §19.76).

They also reinforce `DraftEligibility.REVIEW_REQUIRED` during Step 8.2
(§19.75).

They are NOT structural failures and therefore do NOT themselves cause
`DraftEligibility.BLOCKED` (§19.75).

---

*Document version: 1.1 — FINAL (2026-08-28), amended 2026-08-29 by Phase 2 Step 5A: authoritative five-workflow contracts added to §10 (§10.1 current-law safety decisions, §10.2 contract rules, §10.3 five contracts), Section-74A guardrail §15(16), current-law workflow verification notes §16.1, Step 4 Section-74A follow-up note and §12 mapping row; amended 2026-08-29 by Phase 2 Step 6A: authoritative Fact Engine contract added as §17; amended 2026-08-29 by Phase 2 Step 7A: authoritative Preflight + Arithmetic contract added as §18, additive fact-extraction outcome channel introduced in §17.4; amended 2026-08-29 by Phase 2 Step 8A: authoritative Validation + Workflow Completeness contract added as §19, FactType.DOCUMENT_DETAIL and the five-field Fact Engine candidate JSON added to §17.1/§17.5/§17.6, ExtractedFact.fact_role added to §17.2, Step-9 gate pointer added to §13; amended 2026-08-29 by Phase 2 Step 8B: machine-contract check-ID / review-ID catalog and staged Step-8.2 behavior added to §19 (§19.56–§19.87), with the final staging consistency patch defining Step-8.2 execution semantics for the five deterministic special-check mappings (§19.81–§19.87). Authoritative for Phase 2 work from Step 2.5 onward. v1.0 remains historical and is not merged into this document.*
