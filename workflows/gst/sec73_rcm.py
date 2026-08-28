"""GST_SEC73_RCM deep workflow definition
(ARCHITECTURE_SPEC_v1_1 §10.3 Contract 3).

Static deterministic case-handling configuration for the Section 73
reverse-charge demand workflow: required facts, evidence requirements,
issue types, output structure and safety rules — verbatim from the
authoritative spec. No classification, no LLM calls, no deadline or
arithmetic logic.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition

SEC73_RCM_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC73_RCM,
    required_facts=[
        "Service / supply category alleged to attract RCM",
        "Value of services / supplies alleged to be subject to RCM",
        "RCM tax alleged as unpaid or short-paid",
        "FY / tax period",
        "Interest proposed",
    ],
    evidence_requirements=[
        "Invoices / engagement documents for suppliers alleged to be RCM-covered",
        "Form 26AS / TDS data where the department relies on it",
        "GSTR-3B table 3.1(d) for the relevant period",
        "Vendor-wise ledger / service-category reconciliation where required",
    ],
    issue_types=[
        "RCM_LIABILITY",
        "ITC_REVERSAL",
        "INTEREST_COMPUTATION",
    ],
    default_severity=IssueSeverity.MEDIUM,
    output_structure=[
        "Working paper",
        "RCM supplier / service-category reconciliation",
        "Reviewable DRC-06 draft with conditional RCM submissions",
    ],
    special_rules=[
        "Do not assume that every payment appearing under a TDS or professional-services category is subject to GST reverse charge.",
        "Service category and RCM applicability require verification from underlying documents and current legal sources.",
        "Form 26AS or TDS data may be evidentiary input but is not by itself conclusive proof of GST RCM liability.",
        "Do not assume ITC availability, revenue neutrality, or entitlement without verifying the taxpayer's facts and applicable law.",
    ],
)
