"""Typed domain models for CA Notice AI (ARCHITECTURE_SPEC_V1.md §3).

Architecture Phase 1 artifact — pure data contracts only.

- Standard library only (dataclasses, enums, typing).
- No business logic, no LLM calls, no Streamlit.
- Not connected to the running application yet.
- Independently importable: this module imports nothing from the project.

Field lists follow the spec's minimum fields (§3.1–§3.8). Where the spec
gives no minimum field list (Deadline, Draft, ValidationResult), the fields
are the Phase 1 placeholder contract derived from the spec's layers
(§4 Layer E / Layer K) and IMPLEMENTATION_PLAN Step 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional


class FactStatus(str, Enum):
    """Allowed statuses for Fact (ARCHITECTURE_SPEC_V1.md §3.4).

    An ALLEGED_BY_DEPARTMENT item is not a confirmed taxpayer fact.
    """

    CONFIRMED = "CONFIRMED"
    ALLEGED_BY_DEPARTMENT = "ALLEGED_BY_DEPARTMENT"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    INFERRED = "INFERRED"


class EvidenceStatus(str, Enum):
    """Allowed statuses for Evidence (ARCHITECTURE_SPEC_V1.md §3.5)."""

    PRESENT = "PRESENT"
    MISSING = "MISSING"
    REQUESTED = "REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass
class Case:
    """Spec §3.1."""

    case_id: str
    client_id: str
    created_at: datetime
    status: str
    assigned_user: Optional[str] = None
    jurisdiction: Optional[str] = None
    tax_type: Optional[str] = None
    priority: Optional[str] = None


@dataclass
class Proceeding:
    """Spec §3.2."""

    proceeding_id: str
    case_id: str
    authority: Optional[str] = None
    form: Optional[str] = None
    section_list: List[str] = field(default_factory=list)
    proceeding_family: Optional[str] = None
    proceeding_type: Optional[str] = None
    notice_date: Optional[date] = None
    service_date: Optional[date] = None
    hearing_date: Optional[date] = None
    response_period: Optional[str] = None
    current_status: Optional[str] = None
    classification_confidence: Optional[float] = None


@dataclass
class Document:
    """Spec §3.3."""

    document_id: str
    case_id: str
    filename: str
    document_type: Optional[str] = None
    source: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    page_count: Optional[int] = None
    extraction_status: Optional[str] = None
    hash: Optional[str] = None  # spec field name "hash" — content hash of the document


@dataclass
class Fact:
    """Spec §3.4.

    An ALLEGED_BY_DEPARTMENT item is not a confirmed taxpayer fact.
    """

    fact_id: str
    case_id: str
    claim: str
    status: FactStatus
    source_document_id: Optional[str] = None
    source_page: Optional[int] = None
    source_excerpt: Optional[str] = None
    provenance_type: Optional[str] = None
    confidence: Optional[float] = None
    draft_permission: Optional[bool] = None


@dataclass
class Evidence:
    """Spec §3.5."""

    evidence_id: str
    case_id: str
    status: EvidenceStatus
    evidence_type: Optional[str] = None
    requested_reason: Optional[str] = None
    source_document_id: Optional[str] = None
    related_fact_ids: List[str] = field(default_factory=list)


@dataclass
class Issue:
    """Spec §3.6."""

    issue_id: str
    case_id: str
    issue_type: Optional[str] = None
    severity: Optional[str] = None
    facts_required: List[str] = field(default_factory=list)
    evidence_required: List[str] = field(default_factory=list)
    legal_basis_refs: List[str] = field(default_factory=list)
    assessment_status: Optional[str] = None


@dataclass
class Deadline:
    """Phase 1 contract (spec has no §3 minimum fields for Deadline).

    Inputs per IMPLEMENTATION_PLAN Step 4: notice date, service date,
    response period, hearing date, today. The engine must return explicit
    uncertainty when the service date is absent — that behaviour lives in
    the future Deadline Engine, not in this data model.
    """

    deadline_id: str
    case_id: str
    notice_date: Optional[date] = None
    service_date: Optional[date] = None
    response_period: Optional[str] = None
    hearing_date: Optional[date] = None
    computed_deadline: Optional[date] = None
    status: Optional[str] = None
    computed_on: Optional[date] = None  # the "today" used for the computation
    note: Optional[str] = None


@dataclass
class Workflow:
    """Spec §3.7."""

    workflow_id: str
    version: str
    family: str
    triggers: List[str] = field(default_factory=list)
    required_facts: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    issue_modules: List[str] = field(default_factory=list)
    calculations: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    validation_rules: List[str] = field(default_factory=list)


@dataclass
class LegalReference:
    """Spec §3.8.

    verification_status must distinguish verified authority from a
    suggestion requiring CA legal research (e.g. "VERIFIED" vs
    "CA_LEGAL_RESEARCH_REQUIRED").
    """

    legal_ref_id: str
    authority_type: Optional[str] = None
    title: Optional[str] = None
    provision: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    jurisdiction: Optional[str] = None
    source_url_or_document: Optional[str] = None
    verification_status: Optional[str] = None
    retrieved_at: Optional[datetime] = None


@dataclass
class Draft:
    """Phase 1 contract (spec lists Drafts in the domain tree, §3 gives no
    minimum fields). A Draft is always a reviewable submission — the CA
    remains the final reviewer and filing authority (INVARIANT-008)."""

    draft_id: str
    case_id: str
    kind: Optional[str] = None  # e.g. "DRC-06 reply", "MOV-09 reply", "client message"
    status: Optional[str] = None  # e.g. "DRAFT", "CA_REVIEW", "APPROVED"
    content: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


@dataclass
class ValidationResult:
    """Phase 1 contract (spec §4 Layer K — Output Validator)."""

    check_id: str
    check_name: str
    passed: bool
    severity: Optional[str] = None  # e.g. "ERROR", "WARNING"
    messages: List[str] = field(default_factory=list)
    checked_at: Optional[datetime] = None


__all__ = [
    "FactStatus",
    "EvidenceStatus",
    "Case",
    "Proceeding",
    "Document",
    "Fact",
    "Evidence",
    "Issue",
    "Deadline",
    "Workflow",
    "LegalReference",
    "Draft",
    "ValidationResult",
]
