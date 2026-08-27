# CA Notice AI — Architecture Specification v1.0

Status: Draft for implementation
Date: 27-August-2026
Primary scope: Indian GST notice/proceeding analysis and CA review workflow
Current prototype: Streamlit + DeepSeek V4 Pro via Claude Code integration

## 1. Product definition

CA Notice AI is an AI-assisted case-management and notice-analysis system for Chartered Accountants. The first product is not an autonomous legal adviser. It is a CA copilot that converts a GST proceeding into:

- structured case facts
- procedural/deadline status
- department allegations
- evidence gaps
- issue analysis
- legal-research requirements
- reviewable draft submissions
- client communication

The system must preserve source provenance and must never turn missing/favourable assumptions into confirmed taxpayer facts.

## 2. First-release scope

IN SCOPE
- GST notices and related proceedings
- document ingestion
- proceeding classification
- fact/evidence extraction
- procedural deadline analysis
- issue identification
- workflow execution
- CA working paper generation
- conditional draft response generation
- client message generation
- regression testing

OUT OF SCOPE FOR MVP
- autonomous filing
- autonomous legal advice
- full Income Tax coverage
- unsourced case-law recommendations
- automatic portal actions
- automatic acceptance of factual assertions from the LLM

## 3. Core domain model

Client
  -> Case
      -> TaxRegistration
      -> Proceeding
          -> Documents
          -> Facts
          -> Evidence
          -> Issues
          -> Deadlines
          -> WorkflowRuns
          -> LegalReferences
          -> Tasks
          -> Drafts
          -> Reviews

### 3.1 Case

Minimum fields:
- case_id
- client_id
- created_at
- status
- assigned_user
- jurisdiction
- tax_type
- priority

### 3.2 Proceeding

Minimum fields:
- proceeding_id
- case_id
- authority
- form
- section_list
- proceeding_family
- proceeding_type
- notice_date
- service_date
- hearing_date
- response_period
- current_status
- classification_confidence

### 3.3 Document

Minimum fields:
- document_id
- case_id
- filename
- document_type
- source
- uploaded_at
- page_count
- extraction_status
- hash

### 3.4 Fact

Minimum fields:
- fact_id
- case_id
- claim
- status
- source_document_id
- source_page
- source_excerpt
- provenance_type
- confidence
- draft_permission

Allowed statuses:
- CONFIRMED
- ALLEGED_BY_DEPARTMENT
- NOT_AVAILABLE
- REQUIRES_VERIFICATION
- INFERRED

An ALLEGED_BY_DEPARTMENT item is not a confirmed taxpayer fact.

### 3.5 Evidence

Minimum fields:
- evidence_id
- case_id
- evidence_type
- requested_reason
- status
- source_document_id
- related_fact_ids

Statuses:
- PRESENT
- MISSING
- REQUESTED
- VERIFIED
- REJECTED

### 3.6 Issue

Minimum fields:
- issue_id
- case_id
- issue_type
- severity
- facts_required
- evidence_required
- legal_basis_refs
- assessment_status

### 3.7 Workflow

Minimum fields:
- workflow_id
- version
- family
- triggers
- required_facts
- required_evidence
- issue_modules
- calculations
- outputs
- validation_rules

### 3.8 Legal reference

Minimum fields:
- legal_ref_id
- authority_type
- title
- provision
- effective_from
- effective_to
- jurisdiction
- source_url_or_document
- verification_status
- retrieved_at

The system must distinguish verified authority from a suggestion requiring CA legal research.

## 4. Architecture layers

### Layer A — UI

Current Streamlit UI is retained initially.

Responsibilities:
- upload documents
- show processing state
- show working paper
- show evidence gaps
- show deadlines
- show draft
- collect CA feedback

### Layer B — Case Manager

Owns case lifecycle and links all artifacts to a case.

### Layer C — Document Intelligence

Pipeline:
PDF -> extraction -> tables -> metadata -> page/source mapping -> document classification.

LLM may assist extraction, but extracted factual data must enter the Fact model before downstream drafting.

### Layer D — Proceeding Classifier

Determine:
- tax type
- form
- section
- proceeding family
- proceeding type
- applicable workflow

Must support explicit unknown/ambiguous classification.

### Layer E — Deterministic Engines

The following must be code-driven, not LLM-driven:
- arithmetic
- tax calculations where inputs are known
- date calculations
- day counts
- deadline calculations
- status transitions
- validation of required fields
- source/provenance linking

### Layer F — Fact / Evidence Engine

Central control point for factual assertions.
No draft generator may access raw LLM extraction directly. It must consume the Fact/Evidence model.

### Layer G — Issue Engine

Maps proceeding facts to reusable issues.

Initial reusable issue modules:
- SERVICE_DATE
- DEADLINE
- ITC_MISMATCH
- RCM
- TAXABILITY
- INTEREST_COMPUTATION
- PENALTY_COMPUTATION
- LIMITATION
- EWAY_BILL
- DETENTION
- SUPPLIER_DEFAULT
- DOCUMENT_SUFFICIENCY
- TURNOVER_RECONCILIATION
- FRAUD_SUPPRESSION

### Layer H — Workflow Engine

Selects and executes workflows based on classification.

### Layer I — Legal Knowledge

Future implementation; must use versioned, verified sources.

### Layer J — LLM Reasoning

DeepSeek V4 Pro is the reasoning/drafting worker, not the source of truth.

The LLM receives:
- structured confirmed facts
- allegations
- unknowns
- evidence gaps
- issues
- verified legal propositions
- workflow instructions

It must not independently invent missing facts or citations.

### Layer K — Output Validator

Before output reaches the CA, run checks for:
- unsupported factual assertions
- unsupported legal citations
- wrong form
- wrong proceeding type
- inconsistent dates
- incorrect arithmetic
- missing mandatory evidence items
- unlabelled inferred figures
- confirmed/alleged status violations

## 5. Initial GST workflow taxonomy

### P0 workflow families

1. GST Section 73 — general short payment/demand
2. GST Section 74 — fraud/wilful misstatement/suppression
3. GST RCM
4. GST ITC mismatch/reconciliation
5. GST enforcement / Section 129 / MOV

### P1 workflow families

6. Section 130 confiscation
7. Scrutiny / ASMT
8. Refund proceedings
9. Registration/cancellation
10. Demand/order/recovery

### P2 workflow families

11. Rectification
12. Appeals

This is a product taxonomy, not a claim that these are the only GST proceedings.

## 6. Current regression fixtures

Fixture 001 — NOTICE_1_ITC_Mismatch_DRC01
Tests:
- Section 73
- ITC mismatch
- service-date ambiguity
- passed hearing
- interest/utilisation evidence

Fixture 002 — NOTICE_2_Fraud_Sec74_DRC01
Tests:
- Section 74
- fraud/suppression allegation
- third-party data
- legal uncertainty
- penalty

Fixture 003 — NOTICE_3_EWayBill_Sec129_DRC01
Tests:
- Section 129
- MOV-09
- 7-day deadline
- detention
- Section 130 risk
- proceeding-specific form

Fixture 004 — NOTICE_4_RCM_Sec73_DRC01
Tests:
- RCM
- 26AS/TDS evidence
- Notification reference
- future deadline
- legal scope of RCM

## 7. Critical invariants

INVARIANT-001
A department allegation must never become a confirmed taxpayer fact merely because it is useful to the defence.

INVARIANT-002
An inferred/calculated number must be visibly labelled as inferred and show its calculation basis.

INVARIANT-003
A service-based deadline cannot be confirmed without service-date evidence.

INVARIANT-004
A legal citation must either be verified from an authoritative source or be marked CA LEGAL RESEARCH REQUIRED.

INVARIANT-005
The draft reply cannot use UNKNOWN/NOT_AVAILABLE facts as unconditional taxpayer facts.

INVARIANT-006
The proceeding form/workflow must be correct before draft generation.

INVARIANT-007
The model may draft arguments; it may not decide the truth of disputed facts.

INVARIANT-008
The CA remains the final reviewer and filing authority.

## 8. Prompt architecture after migration

Do not maintain one universal mega-prompt.

Use smaller prompt contracts:

1. extraction prompt
2. classification prompt
3. issue-identification prompt
4. legal-explanation prompt
5. working-paper prompt
6. draft-reply prompt
7. client-message prompt
8. validation prompt

Workflow-specific instructions live in workflow definitions, not in the universal prompt.

## 9. Migration plan from current prototype

Phase 1
- Preserve current Streamlit UI.
- Preserve current document extraction.
- Add internal JSON schema for Proceeding, Fact, Evidence, Issue, Deadline.

Phase 2
- Add deterministic Deadline Engine.
- Add Fact/Evidence store.
- Make Section 7 draft generation consume structured facts only.

Phase 3
- Add Proceeding Classifier.
- Add workflow registry.
- Convert the five P0 workflows into configuration/modules.

Phase 4
- Add Output Validator.
- Make all four notices mandatory regression tests.

Phase 5
- Add verified legal-source subsystem.

Phase 6
- Pilot with CA reviewers.

## 10. MVP acceptance criteria

The GST Notice MVP is ready for CA pilot only when:

- all four current notices classify correctly
- the correct form is selected for each notice
- no unsupported taxpayer facts appear unconditionally in drafts
- service-based deadlines remain explicitly uncertain without service evidence
- arithmetic is deterministic/validated
- legal citations are verified or flagged
- evidence gaps are actionable
- workflow-specific steps differ by proceeding type
- regression tests are automated
- CA feedback can be captured and traced to a workflow/rule/knowledge change

## 11. Future expansion

After GST notice MVP is stable:

- expand GST workflow coverage
- add orders/appeals/recovery
- add additional tax types
- add compliance workflows
- add multi-user CA firm workspace
- add analytics and review history

Income Tax should be treated as a separate domain model and workflow library, not simply another prompt branch.

## 12. Product positioning

Preferred:
"AI-generated GST notice analysis and draft reply for CA review."

Avoid:
"Ready-to-send legal reply"
"AI CA"
"Autonomous tax filing"
"Guaranteed legal answer"

## 13. Implementation principle

The system becomes more reliable by moving rules from prompts into:
- typed data models
- workflow definitions
- deterministic services
- legal-source records
- validators
- regression tests

The LLM is a replaceable reasoning component inside this architecture.
