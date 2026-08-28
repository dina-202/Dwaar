"""GST_SEC73_ITC deep workflow definition
(ARCHITECTURE_SPEC_v1_1 §10.3 Contract 1).

Static deterministic case-handling configuration for the Section 73
ITC-mismatch demand workflow: required facts, evidence requirements, issue
types, output structure and safety rules — verbatim from the authoritative
spec. No classification, no LLM calls, no deadline or arithmetic logic.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition

SEC73_ITC_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    required_facts=[
        "ITC claimed in GSTR-3B (amount)",
        "ITC reflected in GSTR-2B (amount)",
        "Difference between GSTR-3B and GSTR-2B (INFERRED)",
        "FY / tax period",
        "Interest proposed",
    ],
    evidence_requirements=[
        "GSTR-2B for all months in the relevant period",
        "GSTR-3B ITC tables for the relevant period",
        "Invoice-level ITC reconciliation",
        "Supplier GSTR-1 filing status / supporting filing evidence where relevant",
        "Payment proof to suppliers where relevant to the claimed ITC eligibility",
    ],
    issue_types=[
        "ITC_MISMATCH",
        "SUPPLIER_DEFAULT",
        "INTEREST_COMPUTATION",
    ],
    default_severity=IssueSeverity.MEDIUM,
    output_structure=[
        "Working paper",
        "ITC reconciliation table",
        "Reviewable DRC-06 draft",
    ],
    special_rules=[
        "A GSTR-3B versus GSTR-2B mismatch is not by itself proof that the ITC is legally ineligible.",
        "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts.",
        "Never assume invoices, receipt of goods or services, supplier compliance, or payment to suppliers unless supported by evidence.",
        "Final ITC eligibility is a legal/factual conclusion requiring evidence and CA review.",
    ],
)
