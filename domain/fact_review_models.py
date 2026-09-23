"""Snapshot-bound professional fact-review contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict


FACT_REVIEW_SCHEMA_VERSION = 1


class FactReviewDecision(Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class FactReviewRef:
    """SQLite-safe metadata for one encrypted professional fact decision."""

    review_id: str
    case_id: str
    snapshot_id: str
    fact_id: str
    fact_fingerprint: str
    source_text_sha256: str
    decision: FactReviewDecision
    byte_size: int
    sha256_hex: str
    storage_key: str
    reviewed_at: datetime
    reviewed_by: str


@dataclass(frozen=True)
class LoadedFactReview:
    """Verified encrypted fact-review payload plus its metadata."""

    metadata: FactReviewRef
    payload: Dict[str, object]
