"""GST deep-workflow registry (ARCHITECTURE_SPEC_v1_1 §10, §13 Step 5).

Deterministic static registry mapping an approved ProceedingType to its
WorkflowDefinition. Exactly five entries:

- GST_SEC73_ITC
- GST_SEC73_GENERAL
- GST_SEC73_RCM
- GST_SEC74_FRAUD
- GST_SEC129_ENFORCE

ProceedingType.UNKNOWN has no workflow and resolves to None — there is no
fallback or general workflow.

This registry is distinct from the notice-form taxonomy registry
(NoticeForm -> family / initial support level); the two are separate
layers. No LLM calls, no classification, no deadline or arithmetic logic.
"""

from typing import Dict, Optional

from domain.models import ProceedingType

from .base import WorkflowDefinition
from .sec129_enforcement import SEC129_ENFORCEMENT_WORKFLOW
from .sec73_general import SEC73_GENERAL_WORKFLOW
from .sec73_itc import SEC73_ITC_WORKFLOW
from .sec73_rcm import SEC73_RCM_WORKFLOW
from .sec74_fraud import SEC74_FRAUD_WORKFLOW

GST_WORKFLOW_REGISTRY: Dict[ProceedingType, WorkflowDefinition] = {
    ProceedingType.GST_SEC73_ITC: SEC73_ITC_WORKFLOW,
    ProceedingType.GST_SEC73_GENERAL: SEC73_GENERAL_WORKFLOW,
    ProceedingType.GST_SEC73_RCM: SEC73_RCM_WORKFLOW,
    ProceedingType.GST_SEC74_FRAUD: SEC74_FRAUD_WORKFLOW,
    ProceedingType.GST_SEC129_ENFORCE: SEC129_ENFORCEMENT_WORKFLOW,
}


def get_workflow(
    proceeding_type: ProceedingType,
) -> Optional[WorkflowDefinition]:
    """Return the WorkflowDefinition for an approved deep ProceedingType.

    Returns None for ProceedingType.UNKNOWN and any other unsupported type:
    no fallback workflow, no defaulting to the Section 73 general workflow.
    """
    return GST_WORKFLOW_REGISTRY.get(proceeding_type)
