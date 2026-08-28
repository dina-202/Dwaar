"""GST Notice Taxonomy v1 registry (ARCHITECTURE_SPEC_v1_1 §3, §12, §13 Step 3).

Deterministic static registry mapping each recognized Taxonomy-v1 NoticeForm
to its NoticeFamily and initial SupportLevel.

- Pure Python, standard library + domain.models only.
- No text parsing, no LLM, no workflow selection, no network.
- Every recognized form is TRIAGE_ONLY: a recognized form alone MUST NOT
  unlock a DEEP_WORKFLOW (guardrail §15.1). Deep workflow promotion happens
  in Step 4 only after Python validates additional statutory/issue markers.
- NoticeForm.UNKNOWN is not a registry entry (§12) and resolves safely to
  (NoticeFamily.UNKNOWN, SupportLevel.UNKNOWN).
- Section 130 has no NoticeForm (§3.9) and never appears here.
"""

from typing import Dict, Tuple

from domain.models import NoticeFamily, NoticeForm, SupportLevel

TAXONOMY_VERSION = "v1"

# Recognized Taxonomy-v1 form -> (family, initial support level).
TAXONOMY_REGISTRY: Dict[NoticeForm, Tuple[NoticeFamily, SupportLevel]] = {
    # §3.1 Return / Return-Compliance
    NoticeForm.GSTR_3A: (NoticeFamily.RETURN_COMPLIANCE, SupportLevel.TRIAGE_ONLY),
    NoticeForm.DRC_01B: (NoticeFamily.RETURN_COMPLIANCE, SupportLevel.TRIAGE_ONLY),
    NoticeForm.DRC_01C: (NoticeFamily.RETURN_COMPLIANCE, SupportLevel.TRIAGE_ONLY),
    # §3.2 Registration
    NoticeForm.REG_03: (NoticeFamily.REGISTRATION, SupportLevel.TRIAGE_ONLY),
    NoticeForm.REG_17: (NoticeFamily.REGISTRATION, SupportLevel.TRIAGE_ONLY),
    NoticeForm.REG_23: (NoticeFamily.REGISTRATION, SupportLevel.TRIAGE_ONLY),
    # §3.3 Composition
    NoticeForm.CMP_05: (NoticeFamily.COMPOSITION, SupportLevel.TRIAGE_ONLY),
    # §3.4 GST Practitioner
    NoticeForm.PCT_03: (NoticeFamily.GST_PRACTITIONER, SupportLevel.TRIAGE_ONLY),
    # §3.5 Refund
    NoticeForm.RFD_08: (NoticeFamily.REFUND, SupportLevel.TRIAGE_ONLY),
    # §3.6 Assessment / Scrutiny
    NoticeForm.ASMT_02: (NoticeFamily.ASSESSMENT_SCRUTINY, SupportLevel.TRIAGE_ONLY),
    NoticeForm.ASMT_10: (NoticeFamily.ASSESSMENT_SCRUTINY, SupportLevel.TRIAGE_ONLY),
    NoticeForm.ASMT_14: (NoticeFamily.ASSESSMENT_SCRUTINY, SupportLevel.TRIAGE_ONLY),
    # §3.7 Audit
    NoticeForm.ADT_01: (NoticeFamily.AUDIT, SupportLevel.TRIAGE_ONLY),
    # §3.8 Demand / Adjudication
    NoticeForm.DRC_01A: (NoticeFamily.DEMAND_ADJUDICATION, SupportLevel.TRIAGE_ONLY),
    NoticeForm.DRC_01: (NoticeFamily.DEMAND_ADJUDICATION, SupportLevel.TRIAGE_ONLY),
    # §3.9 Enforcement / Movement of Goods
    NoticeForm.MOV_SERIES: (NoticeFamily.ENFORCEMENT, SupportLevel.TRIAGE_ONLY),
    # §3.10 Revision
    NoticeForm.RVN_01: (NoticeFamily.REVISION, SupportLevel.TRIAGE_ONLY),
}


def lookup_notice_form(
    notice_form: NoticeForm,
) -> Tuple[NoticeFamily, SupportLevel]:
    """Resolve a NoticeForm to its Taxonomy-v1 family and initial support level.

    Recognized forms return their registry entry. NoticeForm.UNKNOWN is not a
    registry entry and resolves safely to (NoticeFamily.UNKNOWN,
    SupportLevel.UNKNOWN) — no family is guessed for it. Accepts a
    NoticeForm, never raw notice text.
    """
    return TAXONOMY_REGISTRY.get(
        notice_form, (NoticeFamily.UNKNOWN, SupportLevel.UNKNOWN)
    )
