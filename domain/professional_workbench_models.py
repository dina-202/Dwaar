"""Professional case-attention contracts for Dwaar Phase 3O."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from domain.case_models import CaseStatus


class CaseWorkspace(Enum):
    ANALYSIS_HISTORY = "analysis_history"
    LEGAL_RESEARCH = "legal_research"
    EVIDENCE = "evidence"
    DRAFT = "draft"
    FILING = "filing"


class CaseAttentionCode(Enum):
    ANALYSIS_NOT_SAVED = "analysis_not_saved"
    FACT_REVIEW_REJECTED = "fact_review_rejected"
    LEGAL_BRIEF_NOT_SAVED = "legal_brief_not_saved"
    LEGAL_RESEARCH_UNRESOLVED = "legal_research_unresolved"
    LEGAL_EVIDENCE_INCOMPLETE = "legal_evidence_incomplete"
    LEGAL_EVIDENCE_CONTRACT_DRIFT = "legal_evidence_contract_drift"
    TRIAGE_EVIDENCE_REVIEW_PENDING = "triage_evidence_review_pending"
    NOTICE_EVIDENCE_REVIEW_PENDING = "notice_evidence_review_pending"
    DRAFT_NOT_STARTED = "draft_not_started"
    DRAFT_AWAITING_REVIEW = "draft_awaiting_review"
    DRAFT_AWAITING_APPROVAL = "draft_awaiting_approval"
    APPROVED_DRAFT_NOT_FILED = "approved_draft_not_filed"
    FILING_ACKNOWLEDGEMENT_MISSING = "filing_acknowledgement_missing"

    @property
    def workspace(self) -> CaseWorkspace:
        return _ATTENTION_WORKSPACE[self]


_ATTENTION_WORKSPACE = {
    CaseAttentionCode.ANALYSIS_NOT_SAVED: CaseWorkspace.ANALYSIS_HISTORY,
    CaseAttentionCode.FACT_REVIEW_REJECTED: CaseWorkspace.ANALYSIS_HISTORY,
    CaseAttentionCode.LEGAL_BRIEF_NOT_SAVED: CaseWorkspace.LEGAL_RESEARCH,
    CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED: CaseWorkspace.LEGAL_RESEARCH,
    CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE: CaseWorkspace.EVIDENCE,
    CaseAttentionCode.LEGAL_EVIDENCE_CONTRACT_DRIFT: CaseWorkspace.EVIDENCE,
    CaseAttentionCode.TRIAGE_EVIDENCE_REVIEW_PENDING: CaseWorkspace.EVIDENCE,
    CaseAttentionCode.NOTICE_EVIDENCE_REVIEW_PENDING: CaseWorkspace.EVIDENCE,
    CaseAttentionCode.DRAFT_NOT_STARTED: CaseWorkspace.DRAFT,
    CaseAttentionCode.DRAFT_AWAITING_REVIEW: CaseWorkspace.DRAFT,
    CaseAttentionCode.DRAFT_AWAITING_APPROVAL: CaseWorkspace.DRAFT,
    CaseAttentionCode.APPROVED_DRAFT_NOT_FILED: CaseWorkspace.FILING,
    CaseAttentionCode.FILING_ACKNOWLEDGEMENT_MISSING: CaseWorkspace.FILING,
}


if set(_ATTENTION_WORKSPACE) != set(CaseAttentionCode):
    raise RuntimeError(
        "every CaseAttentionCode must have exactly one owning workspace"
    )


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
