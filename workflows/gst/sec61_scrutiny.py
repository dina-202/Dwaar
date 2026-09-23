"""GST Section 61 scrutiny deep workflow for FORM GST ASMT-10.

This workflow is intentionally discrepancy-agnostic. It structures the
professional response to an ASMT-10 without assuming that any discrepancy
stated by the department is correct or that one particular reconciliation
regime applies.

Deadline handling remains outside this workflow. Dwaar uses only the response
period/due date actually stated in the notice plus verified service/receipt
facts; this workflow does not hard-code a Rule 99 day count.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition


SEC61_SCRUTINY_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC61_SCRUTINY,
    required_facts=[
        "Discrepancy / issue stated by the department in FORM GST ASMT-10",
        "FY / tax period under scrutiny",
        "Response period stated in the notice, where stated",
    ],
    evidence_requirements=[
        "Return(s) and statements under scrutiny for the relevant period",
        "Reconciliation and supporting records relevant to each discrepancy stated in FORM GST ASMT-10",
        "Documents explicitly requested in FORM GST ASMT-10, where stated",
        "Annexures or discrepancy computations referenced by FORM GST ASMT-10, where stated",
    ],
    issue_types=[
        "RETURN_SCRUTINY_DISCREPANCY",
        "DISCREPANCY_RECONCILIATION",
        "RESPONSE_TIMELINE",
    ],
    default_severity=IssueSeverity.MEDIUM,
    output_structure=[
        "Scrutiny working paper",
        "Discrepancy-by-discrepancy response matrix",
        "Reviewable ASMT-11 explanation",
    ],
    special_rules=[
        "Every discrepancy stated in FORM GST ASMT-10 remains a departmental allegation unless independently supported by taxpayer evidence.",
        "Address each stated discrepancy separately; never treat the notice wording alone as an admission by the taxpayer.",
        "Do not inject a generic statutory reply period; use only the notice-stated response period or due date and verified service/receipt inputs.",
        "Any acceptance of a discrepancy, payment, or corrective action requires taxpayer evidence and professional confirmation.",
        "Mandatory CA review is required before any ASMT-11 response is filed.",
    ],
)
