"""GST_SEC74_FRAUD deep workflow definition
(ARCHITECTURE_SPEC_v1_1 §10.3 Contract 4).

Static deterministic case-handling configuration for the Section 74
fraud / wilful-misstatement / suppression demand workflow: required facts,
evidence requirements, issue types, output structure and safety rules —
verbatim from the authoritative spec.

Fraud, wilful misstatement and suppression remain departmental allegations
in this definition; nothing here establishes them as fact. This workflow
applies only where the notice expressly invokes Section 74 and must not be
used as a substitute for Section 74A.

No classification, no LLM calls, no deadline or arithmetic logic.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition

SEC74_FRAUD_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC74_FRAUD,
    required_facts=[
        "Basis of fraud / wilful-misstatement / suppression allegation",
        "Turnover, tax, refund or ITC amount alleged by the department (ALLEGED unless independently established)",
        "FY / tax period",
        "Penalty proposed in the notice (ALLEGED)",
        "Limitation / extended-period basis invoked in the notice",
    ],
    evidence_requirements=[
        "Books of accounts for the relevant period",
        "Relevant bank statements",
        "Filed GST returns for the relevant period",
        "Correspondence with the department",
        "Underlying third-party / RERA / external-source documents where relied upon by the department",
    ],
    issue_types=[
        "FRAUD_ALLEGATION",
        "SUPPRESSION",
        "PENALTY_COMPUTATION",
        "LIMITATION",
    ],
    default_severity=IssueSeverity.CRITICAL,
    output_structure=[
        "Urgent working paper",
        "Senior-review / escalation note",
        "Conditional reviewable DRC-06 draft",
    ],
    special_rules=[
        "Fraud, wilful misstatement and suppression must remain departmental allegations unless established by evidence.",
        "Never state that fraud is present or absent as an established fact without evidentiary support.",
        "Preserve the provenance of third-party or external data relied upon by the department.",
        "Mandatory senior CA / advocate review is required before filing.",
        "This workflow applies only where the notice expressly invokes Section 74; it must not be used as a substitute for Section 74A.",
    ],
)
