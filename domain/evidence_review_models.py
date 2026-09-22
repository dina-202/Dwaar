"""Persistent evidence-review contracts for Dwaar Phase 3G.2."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from domain.models import EvidenceReviewStatus


EVIDENCE_REVIEW_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EvidenceReviewRef:
    """SQLite-safe metadata for one encrypted human evidence decision."""

    review_id: str
    case_id: str
    snapshot_id: str
    evidence_id: str
    document_id: str
    source_page: int
    source_text_sha256: str
    candidate_fingerprint: str
    decision: EvidenceReviewStatus
    byte_size: int
    sha256_hex: str
    storage_key: str
    reviewed_at: datetime
    reviewed_by: str


@dataclass(frozen=True)
class LoadedEvidenceReview:
    """Verified encrypted review payload plus its metadata."""

    metadata: EvidenceReviewRef
    payload: Dict[str, object]
