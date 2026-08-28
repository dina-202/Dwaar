"""GST_SEC73_GENERAL deep workflow definition
(ARCHITECTURE_SPEC_v1_1 §10.3 Contract 2).

Static deterministic case-handling configuration for the Section 73
general tax short-payment / output-tax mismatch demand workflow: required
facts, evidence requirements, issue types, output structure and safety
rules — verbatim from the authoritative spec. No classification, no LLM
calls, no deadline or arithmetic logic.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition

SEC73_GENERAL_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC73_GENERAL,
    required_facts=[
        "Tax / liability declared in GSTR-1",
        "Tax / liability discharged in GSTR-3B",
        "Difference between GSTR-1 and GSTR-3B (INFERRED)",
        "FY / tax period",
        "Interest proposed",
    ],
    evidence_requirements=[
        "Monthly GSTR-1 and GSTR-3B for the relevant period",
        "GSTR-9 annual return where applicable/relevant",
        "Credit notes and amendments relevant to the mismatch",
    ],
    issue_types=[
        "SHORT_PAYMENT",
        "GSTR_MISMATCH",
        "INTEREST_COMPUTATION",
    ],
    default_severity=IssueSeverity.MEDIUM,
    output_structure=[
        "Working paper",
        "Month-wise GSTR-1 versus GSTR-3B reconciliation",
        "Reviewable DRC-06 draft",
    ],
    special_rules=[
        "A return mismatch is not by itself an admission of tax short-payment.",
        "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts.",
        "Credit notes, amendments, timing differences and other reconciliation items must be checked before reaching a liability conclusion.",
        "The workflow identifies reconciliation requirements; it does not itself establish legal liability.",
    ],
)
