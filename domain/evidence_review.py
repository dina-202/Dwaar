"""Deterministic human-review transitions for evidence candidates."""

from typing import List, Optional

from domain.models import (
    EvidenceCandidate,
    EvidenceReviewRecord,
    EvidenceReviewStatus,
)


def create_evidence_review(
    candidate: EvidenceCandidate,
    decision: EvidenceReviewStatus,
    existing_reviews: List[EvidenceReviewRecord],
    reviewer_note: Optional[str] = None,
) -> EvidenceReviewRecord:
    """Create an auditable review record without mutating the candidate.

    Only terminal human decisions are accepted. PENDING_REVIEW is the
    machine-created candidate state and cannot be used as a human review
    decision.
    """
    if not isinstance(candidate, EvidenceCandidate):
        raise TypeError("candidate must be an EvidenceCandidate")
    if decision not in (
        EvidenceReviewStatus.CONFIRMED,
        EvidenceReviewStatus.REJECTED,
    ):
        raise ValueError("decision must be CONFIRMED or REJECTED")
    if any(
        review.candidate_id == candidate.candidate_id
        for review in existing_reviews
    ):
        raise ValueError("candidate has already been reviewed")
    if reviewer_note is not None and not isinstance(reviewer_note, str):
        raise TypeError("reviewer_note must be a string or None")

    normalized_note = (
        reviewer_note.strip()
        if isinstance(reviewer_note, str) and reviewer_note.strip()
        else None
    )

    return EvidenceReviewRecord(
        review_id=f"ER-{len(existing_reviews) + 1:03d}",
        candidate_id=candidate.candidate_id,
        evidence_id=candidate.evidence_id,
        document_id=candidate.document_id,
        source_text=candidate.source_text,
        source_page=candidate.source_page,
        source_origin=candidate.source_origin,
        source_verification=candidate.source_verification,
        decision=decision,
        reviewer_note=normalized_note,
    )


def reviewed_candidate_ids(
    reviews: List[EvidenceReviewRecord],
) -> List[str]:
    """Return reviewed candidate IDs in review order, deduplicated."""
    seen = set()
    ordered = []
    for review in reviews:
        if review.candidate_id in seen:
            continue
        seen.add(review.candidate_id)
        ordered.append(review.candidate_id)
    return ordered
