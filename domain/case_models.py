"""Persistent case/evidence domain contracts for Dwaar Phase 3C.

Pure data contracts only:
- standard library + domain.models enums;
- no database, ORM, Streamlit, network, filesystem or auth implementation;
- tenant_id is data scope, never authorization proof;
- document bytes live outside these records.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from domain.models import NoticeForm, ProceedingType


class CaseStatus(Enum):
    INTAKE = "intake"
    ANALYZING = "analyzing"
    EVIDENCE_PENDING = "evidence_pending"
    DRAFTING = "drafting"
    REVIEW = "review"
    READY_TO_FILE = "ready_to_file"
    FILED = "filed"
    POST_FILING = "post_filing"
    CLOSED = "closed"


class DocumentKind(Enum):
    NOTICE = "notice"
    NOTICE_ANNEXURE = "notice_annexure"
    TAXPAYER_EVIDENCE = "taxpayer_evidence"
    RECONCILIATION = "reconciliation"
    DRAFT_REPLY = "draft_reply"
    FINAL_REPLY = "final_reply"
    FILING_ACKNOWLEDGEMENT = "filing_acknowledgement"
    HEARING_DOCUMENT = "hearing_document"
    ORDER = "order"
    OTHER = "other"


class EvidenceReviewStatus(Enum):
    UNREVIEWED = "unreviewed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    CONFLICTING = "conflicting"


class AnalysisRunStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class CaseEventType(Enum):
    CASE_CREATED = "case_created"
    DOCUMENT_ADDED = "document_added"
    EVIDENCE_REQUESTED = "evidence_requested"
    EVIDENCE_REVIEWED = "evidence_reviewed"
    ANALYSIS_RUN = "analysis_run"
    DRAFT_CREATED = "draft_created"
    REVIEW_COMPLETED = "review_completed"
    REPLY_FILED = "reply_filed"
    ACKNOWLEDGEMENT_RECORDED = "acknowledgement_recorded"
    HEARING_RECORDED = "hearing_recorded"
    ORDER_RECORDED = "order_recorded"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"


@dataclass(frozen=True)
class ClientRecord:
    tenant_id: str
    client_id: str
    display_name: str
    created_at: datetime
    legal_name: Optional[str] = None
    pan: Optional[str] = None


@dataclass(frozen=True)
class TaxRegistrationRecord:
    tenant_id: str
    registration_id: str
    client_id: str
    gstin: str
    created_at: datetime
    legal_name: Optional[str] = None


@dataclass(frozen=True)
class CaseRecord:
    tenant_id: str
    case_id: str
    client_id: str
    title: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    registration_id: Optional[str] = None
    proceeding_type: ProceedingType = ProceedingType.UNKNOWN
    notice_form: NoticeForm = NoticeForm.UNKNOWN


@dataclass(frozen=True)
class CaseDocumentRecord:
    tenant_id: str
    document_id: str
    case_id: str
    kind: DocumentKind
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    storage_key: str
    uploaded_at: datetime


@dataclass(frozen=True)
class EvidenceLinkRecord:
    """Many-to-many link from case documents to workflow evidence requirements."""

    tenant_id: str
    evidence_link_id: str
    case_id: str
    document_id: str
    requirement_id: str
    review_status: EvidenceReviewStatus
    created_at: datetime
    reviewer_user_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None


@dataclass(frozen=True)
class AnalysisRunRecord:
    tenant_id: str
    analysis_run_id: str
    case_id: str
    notice_document_id: str
    engine_version: str
    status: AnalysisRunStatus
    created_at: datetime


@dataclass(frozen=True)
class DraftVersionRecord:
    tenant_id: str
    draft_id: str
    case_id: str
    analysis_run_id: str
    version: int
    document_id: str
    created_at: datetime
    created_by_user_id: Optional[str] = None


@dataclass(frozen=True)
class FilingRecord:
    tenant_id: str
    filing_id: str
    case_id: str
    final_reply_document_id: str
    filed_at: datetime
    portal_reference: Optional[str] = None
    acknowledgement_document_id: Optional[str] = None


@dataclass(frozen=True)
class CaseEventRecord:
    """Append-oriented case timeline event; mutation policy belongs to storage."""

    tenant_id: str
    event_id: str
    case_id: str
    event_type: CaseEventType
    occurred_at: datetime
    actor_user_id: Optional[str] = None
    related_document_id: Optional[str] = None
    external_reference: Optional[str] = None
    note: Optional[str] = None
