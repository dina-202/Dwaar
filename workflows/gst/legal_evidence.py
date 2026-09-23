"""Deterministic legal-question evidence readiness.

This module projects human-confirmed, snapshot-bound evidence review metadata
onto closed legal-question evidence requirements. It never decides whether a
legal condition is satisfied.
"""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

from domain.evidence_review_models import EvidenceReviewRef
from domain.legal_evidence_models import (
    LegalEvidenceReadiness,
    LegalEvidenceReadinessStatus,
    LegalEvidenceRequirement,
)
from domain.models import EvidenceReviewStatus, ProceedingType


GST_LEGAL_EVIDENCE_REQUIREMENTS: Dict[
    ProceedingType, Tuple[LegalEvidenceRequirement, ...]
] = {
    ProceedingType.GST_SEC73_ITC: (
        LegalEvidenceRequirement(
            question_id="gst_sec73_itc.eligibility",
            required_evidence_ids=(
                "sec73_itc.e3",
                "sec73_itc.e4",
                "sec73_itc.e5",
            ),
        ),
    ),
}


def build_legal_evidence_readiness(
    proceeding_type: ProceedingType,
    *,
    snapshot_id: str,
    reviews: Iterable[EvidenceReviewRef],
) -> Tuple[LegalEvidenceReadiness, ...]:
    """Project confirmed evidence-review metadata onto legal questions.

    Only CONFIRMED reviews bound to the requested snapshot count. A rejected
    review never satisfies an evidence requirement. Duplicate confirmed
    reviews for the same evidence ID are harmless and deduplicated.
    """
    if not isinstance(proceeding_type, ProceedingType):
        raise TypeError("proceeding_type must be a ProceedingType")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")

    review_list = tuple(reviews)
    if any(not isinstance(item, EvidenceReviewRef) for item in review_list):
        raise TypeError("reviews must contain only EvidenceReviewRef values")

    confirmed_by_evidence = {}
    for review in review_list:
        if review.snapshot_id != snapshot_id:
            continue
        if review.decision is not EvidenceReviewStatus.CONFIRMED:
            continue
        confirmed_by_evidence.setdefault(review.evidence_id, []).append(
            review.review_id
        )

    results = []
    for requirement in GST_LEGAL_EVIDENCE_REQUIREMENTS.get(
        proceeding_type, ()
    ):
        required = requirement.required_evidence_ids
        confirmed = tuple(
            evidence_id
            for evidence_id in required
            if evidence_id in confirmed_by_evidence
        )
        missing = tuple(
            evidence_id
            for evidence_id in required
            if evidence_id not in confirmed_by_evidence
        )
        review_ids = tuple(
            review_id
            for evidence_id in required
            for review_id in confirmed_by_evidence.get(evidence_id, ())
        )

        if not confirmed:
            status = LegalEvidenceReadinessStatus.NO_CONFIRMED_EVIDENCE
        elif missing:
            status = (
                LegalEvidenceReadinessStatus.PARTIAL_CONFIRMED_EVIDENCE
            )
        else:
            status = (
                LegalEvidenceReadinessStatus.REQUIRED_EVIDENCE_CONFIRMED
            )

        results.append(
            LegalEvidenceReadiness(
                question_id=requirement.question_id,
                status=status,
                required_evidence_ids=required,
                confirmed_evidence_ids=confirmed,
                missing_evidence_ids=missing,
                confirmed_review_ids=review_ids,
            )
        )
    return tuple(results)
