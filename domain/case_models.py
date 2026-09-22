"""Persistent-case domain contracts for Dwaar Phase 3D.

Pure standard-library data contracts only. No database, filesystem,
framework, encryption, network, or LLM dependency belongs in this module.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from domain.models import NoticeForm, ProceedingType


class CaseStatus(Enum):
    """Operational case state; never a legal merits conclusion."""

    INTAKE = "intake"
    ANALYZED = "analyzed"
    EVIDENCE_COLLECTION = "evidence_collection"
    DRAFT_REVIEW = "draft_review"
    FILED = "filed"
    HEARING = "hearing"
    ORDER_RECEIVED = "order_received"
    CLOSED = "closed"


class CaseDocumentKind(Enum):
    NOTICE = "notice"
    ANNEXURE = "annexure"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    DRAFT = "draft"
    FILED_RESPONSE = "filed_response"
    ACKNOWLEDGEMENT = "acknowledgement"
    HEARING_DOCUMENT = "hearing_document"
    ORDER = "order"
    OTHER = "other"


class CaseEventType(Enum):
    CASE_CREATED = "case_created"
    CASE_STATUS_CHANGED = "case_status_changed"
    CASE_OPERATIONS_UPDATED = "case_operations_updated"
    DOCUMENT_ADDED = "document_added"
    DOCUMENT_REMOVED = "document_removed"
    ANALYSIS_SAVED = "analysis_saved"
    LEGAL_BRIEF_SAVED = "legal_brief_saved"
    EVIDENCE_CANDIDATES_GENERATED = "evidence_candidates_generated"
    EVIDENCE_REVIEWED = "evidence_reviewed"
    DRAFT_CREATED = "draft_created"
    DRAFT_REVIEWED = "draft_reviewed"
    FILING_RECORDED = "filing_recorded"
    FILING_ACKNOWLEDGEMENT_RECORDED = "filing_acknowledgement_recorded"
    HEARING_RECORDED = "hearing_recorded"
    ORDER_RECORDED = "order_recorded"


@dataclass(frozen=True)
class Firm:
    firm_id: str
    display_name: str
    created_at: datetime


@dataclass(frozen=True)
class Client:
    client_id: str
    firm_id: str
    display_name: str
    created_at: datetime


@dataclass(frozen=True)
class TaxRegistration:
    registration_id: str
    client_id: str
    jurisdiction: str
    identifier_type: str
    identifier_value: str
    created_at: datetime


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    firm_id: str
    client_id: str
    registration_id: Optional[str]
    title: str
    status: CaseStatus
    proceeding_type: ProceedingType
    notice_form: NoticeForm
    opened_at: datetime
    response_deadline: Optional[date] = None
    assigned_to: Optional[str] = None
    reviewer_id: Optional[str] = None
    closed_at: Optional[datetime] = None


@dataclass(frozen=True)
class StoredDocumentRef:
    """Metadata reference only; contains no client document bytes."""

    document_id: str
    case_id: str
    kind: CaseDocumentKind
    original_filename: str
    media_type: str
    byte_size: int
    sha256_hex: str
    storage_key: str
    created_at: datetime


@dataclass(frozen=True)
class CaseEvent:
    """Append-only audit event metadata.

    payload is deliberately structured metadata only. Raw notice/evidence
    text, access tokens, secrets, and document bytes do not belong here.
    """

    event_id: str
    case_id: str
    event_type: CaseEventType
    occurred_at: datetime
    actor_id: Optional[str]
    payload: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseSnapshot:
    """Convenience aggregate for case-workspace reads."""

    case: CaseRecord
    documents: List[StoredDocumentRef]
    events: List[CaseEvent]


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persistence/audit call sites."""
    return datetime.now(timezone.utc)
