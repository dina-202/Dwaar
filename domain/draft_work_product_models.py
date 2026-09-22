"""Durable draft-work-product contracts for Dwaar Phase 3K."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


DRAFT_VERSION_SCHEMA_VERSION = 1


class DraftReviewStatus(Enum):
    WORKING = "working"
    REVIEWED = "reviewed"
    APPROVED = "approved"


@dataclass(frozen=True)
class DraftVersionRef:
    """SQLite-safe metadata for one immutable encrypted draft version."""

    draft_version_id: str
    case_id: str
    source_snapshot_id: str
    parent_draft_version_id: Optional[str]
    version_number: int
    generated_baseline: bool
    content_sha256: str
    byte_size: int
    sha256_hex: str
    storage_key: str
    review_status: DraftReviewStatus
    created_at: datetime
    created_by: str
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


@dataclass(frozen=True)
class LoadedDraftVersion:
    """Verified encrypted professional draft payload plus metadata."""

    metadata: DraftVersionRef
    payload: Dict[str, object]
