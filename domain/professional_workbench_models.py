"""Professional case-attention contracts for Dwaar Phase 3O.1."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from domain.case_models import CaseStatus


class CaseAttentionCode(Enum):
    ANALYSIS_NOT_SAVED = "analysis_not_saved"
    LEGAL_BRIEF_NOT_SAVED = "legal_brief_not_saved"
    LEGAL_RESEARCH_UNRESOLVED = "legal_research_unresolved"
    LEGAL_EVIDENCE_INCOMPLETE = "legal_evidence_incomplete"
    LEGAL_EVIDENCE_CONTRACT_DRIFT = "legal_evidence_contract_drift"
    DRAFT_NOT_STARTED = "draft_not_started"
    DRAFT_AWAITING_REVIEW = "draft_awaiting_review"
    DRAFT_AWAITING_APPROVAL = "draft_awaiting_approval"
    APPROVED_DRAFT_NOT_FILED = "approved_draft_not_filed"
    FILING_ACKNOWLEDGEMENT_MISSING = "filing_acknowledgement_missing"


@dataclass(frozen=True)
class CaseAttentionItem:
    code: CaseAttentionCode
    message: str
    related_id: Optional[str] = None


@dataclass(frozen=True)
class ProfessionalCaseAttention:
    case_id: str
    case_status: CaseStatus
    latest_snapshot_id: Optional[str]
    latest_legal_brief_id: Optional[str]
    latest_draft_version_id: Optional[str]
    latest_filing_id: Optional[str]
    items: Tuple[CaseAttentionItem, ...]
