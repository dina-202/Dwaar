"""WorkflowDefinition contract (ARCHITECTURE_SPEC_v1_1 §10).

A WorkflowDefinition is static case-handling configuration for one approved
deep proceeding type: the facts to seek, the evidence to collect, the issues
to investigate, the output structure, and declarative safety rules.

Workflow content is a case-handling requirement set, not a legal conclusion
(§10.2). No LLM calls, no deadline or arithmetic logic, no network access.
"""

from dataclasses import dataclass
from typing import List

from domain.models import IssueSeverity, ProceedingType


@dataclass
class WorkflowDefinition:
    proceeding_type: ProceedingType
    required_facts: List[str]
    evidence_requirements: List[str]
    issue_types: List[str]
    default_severity: IssueSeverity
    output_structure: List[str]
    special_rules: List[str]
