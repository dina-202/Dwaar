# Phase 3Q.3 — Section 61 / ASMT-10 Specialist Workflow

## Purpose

Phase 3Q.3 records the earned promotion of FORM GST ASMT-10 from
`TRIAGE_ONLY` into a dedicated specialist workflow,
`GST_SEC61_SCRUTINY`.

This is not a form-recognition shortcut. Promotion became acceptable only
after a real pilot intake exposed the limits of triage-only handling and the
required classification, fact, deadline, workflow, drafting, legal-source and
document-level regression boundaries were implemented.

The core rule remains unchanged:

> Recognize broadly. Analyze deeply only where a tested, deterministic support
> gate and professional-review workflow exist.

## 1. Deterministic promotion gate

ASMT-10 is promoted only when all of the following are true:

- `NoticeForm.ASMT_10`;
- the notice text explicitly contains `Section 61` or `Rule 99`; and
- the notice text explicitly contains a discrepancy marker.

Only then may Python assign:

```text
ProceedingType.GST_SEC61_SCRUTINY
SupportLevel.DEEP_WORKFLOW
```

If the marker set is incomplete, the recognized ASMT-10 remains
`TRIAGE_ONLY`. The LLM cannot grant deep support on its own.

Authoritative implementation:

- `domain/proceeding_classifier.py`
- `domain/models.py`

## 2. Workflow contract

The specialist workflow is intentionally discrepancy-agnostic. It does not
assume that an ASMT-10 concerns ITC, RCM, output tax, or any other particular
merits theory merely because one is common in practice.

Required workflow facts:

1. discrepancy / issue stated by the department in FORM GST ASMT-10;
2. FY / tax period under scrutiny;
3. response period stated in the notice, where stated.

Every separately stated ASMT-10 discrepancy must be extracted as a separate
`DEPARTMENT_ALLEGATION`. Notice wording never becomes a taxpayer admission.

Evidence requirements remain review requirements, not assertions that the
records exist:

- return(s) and statements under scrutiny;
- reconciliation/supporting records relevant to each discrepancy;
- documents explicitly requested by the notice;
- annexures or discrepancy computations referenced by the notice.

Approved output structure:

1. Scrutiny working paper
2. Discrepancy-by-discrepancy response matrix
3. Reviewable ASMT-11 explanation

Authoritative implementation:

- `workflows/gst/sec61_scrutiny.py`
- `workflows/gst/validation_profiles.py`
- `workflows/gst/drafting_profiles.py`
- `prompts/drafting/gst/sec61_scrutiny.txt`
- `prompts/drafting/provenance_v1/gst/sec61_scrutiny.txt`

## 3. Deadline boundary

The workflow does **not** own a generic statutory day count.

Dwaar may use a response period only when the notice itself supplies
source-grounded response-period wording. The deterministic deadline parser may
normalize explicit calendar-day wording such as numeric or English-number day
counts, but it must not treat unrelated identifiers such as `Section 61` or
`ASMT-10` as the period.

A calendar deadline is calculated only when the required service/receipt date
is independently verified. Notice date is never silently substituted for
service date.

Working/business-day periods remain unresolved until a verified calendar
subsystem exists.

Authoritative implementation:

- `domain/deadline_engine.py`
- `domain/phase2_orchestrator.py`

## 4. Verified legal-research boundary

The Section 61 legal pack is deliberately narrow. It contains the stable
scrutiny-process/form propositions required for the professional workspace:

- Section 61 scrutiny process;
- Rule 99 ASMT-10 / ASMT-11 / ASMT-12 form sequence.

The legal catalog intentionally contains no generic "15 days" or "30 days"
response-period proposition for this workflow. Timing therefore remains
notice-driven unless a later versioned legal rule resolves the authoritative
source and effective-date question.

Authoritative implementation:

- `domain/legal_knowledge_models.py`
- `workflows/gst/legal_knowledge.py`
- `workflows/gst/legal_research.py`
- `workflows/gst/legal_questions.py`

## 5. Validation and review behavior

The Section 61 validation profile has three workflow requirements and five
mapped special rules.

The workflow preserves these boundaries:

- department-stated discrepancies remain allegations;
- each discrepancy is reviewed separately;
- no generic deadline is injected;
- acceptance/payment/corrective action requires supporting evidence and
  professional confirmation;
- CA review is mandatory before ASMT-11 filing.

Missing or incomplete facts resolve to review/verification states rather than
being invented. Failed/no-input extraction still blocks specialist drafting.

Current registry totals after this promotion:

```text
deep workflows             = 6
validation profiles        = 6
drafting profiles          = 6
WorkflowRequirementSpecs   = 32
special-rule mappings      = 29
```

## 6. Document-level regression proof

Synthetic fixtures are used; no real taxpayer notice is committed:

- `data/sample_notices/NOTICE_5_ASMT10_Synthetic.pdf`
- `data/sample_notices/NOTICE_6_GSTR3A_Synthetic.pdf`

The ASMT-10 document rehearsal leaves production parsing and deterministic
engines active and stubs only the external model responses.

`tests/test_asmt10_document_rehearsal.py` proves the synthetic ASMT-10 can
flow through:

```text
PDF ingestion
→ validated Section 61 classification
→ provenance-aware fact extraction
→ notice-stated response-period parsing
→ preflight
→ workflow validation
→ controlled ASMT-11 drafting
→ verified Section 61 legal research
```

The rehearsal also pins that:

- Section 61 is not misread as a 61-day response period;
- the notice-stated "fifteen days" is parsed as 15;
- no calendar deadline is fabricated when service/receipt date is unknown;
- requested records and the referenced annexure survive into preflight;
- specialist drafting remains `REVIEW_REQUIRED`;
- the ASMT-11 draft path does not fall back to DRC-06 language;
- verified legal propositions do not inject a 15/30-day generic period.

Related regressions:

- `tests/test_deadline_engine.py`
- `tests/test_triage_pdf_fixtures.py`
- `tests/test_fact_engine.py`
- `tests/test_proceeding_classifier.py`
- `tests/test_workflows.py`
- `tests/test_workflow_validation_profiles.py`
- `tests/test_drafting_profiles.py`
- `tests/test_drafting_engine.py`
- `tests/test_validation_engine.py`
- `tests/test_phase2_orchestrator.py`
- `tests/test_legal_knowledge.py`
- `tests/test_gst_legal_research.py`
- `tests/test_legal_questions.py`

## 7. Non-goals

This phase does not:

- make every ASMT-family form deep-supported;
- infer that an ASMT-10 discrepancy is correct;
- create a generic statutory response-period default;
- decide whether an explanation should be accepted by the department;
- treat uploaded evidence as proof merely because a match candidate exists;
- remove CA review;
- promote other Taxonomy-v1 forms without their own earned workflow contract.

Fine-grained tracking of multiple individually requested records may be added
later if real evidence-review use demonstrates that the current checklist
granularity is insufficient. Do not invent a new evidence-completeness model
preemptively.

## 8. Historical relationship

`PHASE3Q1_PILOT_TRUTHFULNESS_UX.md` remains an accurate record of the earlier
pilot state in which ASMT-10 was triage-only. Its non-promotion statements are
historical constraints for that phase, not the current support contract.

`ARCHITECTURE_SPEC_v1_1.md` is the authoritative current architecture and
incorporates this sixth workflow.
