"""Snapshot-bound professional fact-review contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable


FACT_REVIEW_SCHEMA_VERSION = 1
FACT_REVIEW_NOTE_MAX_CHARS = 4000


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



def latest_fact_reviews(
    reviews: Iterable[FactReviewRef],
) -> Dict[str, FactReviewRef]:
    """Return the latest immutable professional decision for each fact.

    History remains append-only. Operational state is selected by
    (reviewed_at, review_id) so equal timestamps still resolve
    deterministically.
    """
    latest: Dict[str, FactReviewRef] = {}
    for review in reviews:
        if not isinstance(review, FactReviewRef):
            raise TypeError("reviews must contain only FactReviewRef values")
        current = latest.get(review.fact_id)
        if current is None or (
            review.reviewed_at,
            review.review_id,
        ) > (
            current.reviewed_at,
            current.review_id,
        ):
            latest[review.fact_id] = review
    return latest
