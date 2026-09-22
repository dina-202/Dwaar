"""Encrypted persistence for snapshot-bound evidence review decisions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import List, Optional

from domain.case_models import CaseEvent, CaseEventType
from domain.evidence_review_models import (
    EvidenceReviewRef,
    LoadedEvidenceReview,
)
from domain.models import EvidenceCandidate, EvidenceReviewStatus
from domain.persistence_ports import EvidenceReviewRepository, DocumentStore
from modules.encrypted_document_store import generate_storage_key
from modules.evidence_review_payload import (
    build_review_payload,
    decode_review_payload,
    encode_review_payload,
)


class EvidenceReviewPersistenceError(RuntimeError):
    """Review metadata failed and encrypted payload was rolled back."""


class EvidenceReviewConsistencyError(EvidenceReviewPersistenceError):
    """Review metadata failed and payload rollback also failed."""


class EvidenceReviewIntegrityError(RuntimeError):
    """Stored review metadata/payload binding is inconsistent."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def persist_evidence_review(
    repository: EvidenceReviewRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    snapshot_id: str,
    candidate: EvidenceCandidate,
    decision: EvidenceReviewStatus,
    reviewer_note: Optional[str],
    actor_id: str,
    reviewed_at: datetime,
) -> EvidenceReviewRef:
    """Persist one encrypted review plus metadata-only audit event."""
    payload = build_review_payload(
        candidate,
        case_id=case_id,
        snapshot_id=snapshot_id,
        decision=decision,
        reviewer_note=reviewer_note,
        reviewed_at=reviewed_at,
        reviewed_by=actor_id,
    )
    encoded = encode_review_payload(payload)
    payload_hash = hashlib.sha256(encoded).hexdigest()
    storage_key = generate_storage_key()
    binding = payload["binding"]

    review = EvidenceReviewRef(
        review_id=_id("EREV"),
        case_id=case_id,
        snapshot_id=snapshot_id,
        evidence_id=binding["evidence_id"],
        document_id=binding["document_id"],
        source_page=binding["source_page"],
        source_text_sha256=binding["source_text_sha256"],
        candidate_fingerprint=binding["candidate_fingerprint"],
        decision=decision,
        byte_size=len(encoded),
        sha256_hex=payload_hash,
        storage_key=storage_key,
        reviewed_at=reviewed_at,
        reviewed_by=actor_id,
    )
    event = CaseEvent(
        event_id=_id("EV"),
        case_id=case_id,
        event_type=CaseEventType.EVIDENCE_REVIEWED,
        occurred_at=reviewed_at,
        actor_id=actor_id,
        payload={
            "review_id": review.review_id,
            "snapshot_id": snapshot_id,
            "evidence_id": review.evidence_id,
            "document_id": review.document_id,
            "source_page": str(review.source_page),
            "source_text_sha256": review.source_text_sha256,
            "candidate_fingerprint": review.candidate_fingerprint,
            "decision": review.decision.value,
            "review_payload_sha256": payload_hash,
            "byte_size": str(len(encoded)),
        },
    )

    document_store.put(storage_key, encoded)
    try:
        repository.save_review(review, event)
    except Exception as persistence_error:
        try:
            document_store.delete(storage_key)
        except Exception as rollback_error:
            raise EvidenceReviewConsistencyError(
                "Evidence review metadata failed and encrypted payload "
                "rollback also failed."
            ) from rollback_error
        raise EvidenceReviewPersistenceError(
            "Evidence review metadata failed; encrypted payload was "
            "rolled back."
        ) from persistence_error

    return review


def load_evidence_review(
    repository: EvidenceReviewRepository,
    document_store: DocumentStore,
    *,
    review_id: str,
) -> LoadedEvidenceReview:
    if not isinstance(review_id, str) or not review_id:
        raise ValueError("review_id must be non-empty")

    review = repository.get_review_ref(review_id)
    if review is None:
        raise LookupError("evidence review does not exist")

    encoded = document_store.get(review.storage_key)
    if len(encoded) != review.byte_size:
        raise EvidenceReviewIntegrityError(
            "review byte size does not match metadata"
        )
    if hashlib.sha256(encoded).hexdigest() != review.sha256_hex:
        raise EvidenceReviewIntegrityError(
            "review payload hash does not match metadata"
        )
    try:
        payload = decode_review_payload(encoded)
    except ValueError as error:
        raise EvidenceReviewIntegrityError(
            "review payload is invalid"
        ) from error

    binding = payload["binding"]
    expected_pairs = (
        ("case_id", review.case_id),
        ("snapshot_id", review.snapshot_id),
        ("evidence_id", review.evidence_id),
        ("document_id", review.document_id),
        ("source_page", review.source_page),
        ("source_text_sha256", review.source_text_sha256),
        ("candidate_fingerprint", review.candidate_fingerprint),
    )
    hash_keys = {"source_text_sha256", "candidate_fingerprint"}
    for key, expected in expected_pairs:
        actual = binding[key]
        if key in hash_keys:
            if (
                not isinstance(actual, str)
                or actual.lower() != expected.lower()
            ):
                raise EvidenceReviewIntegrityError(
                    f"review payload {key} is inconsistent"
                )
        elif actual != expected:
            raise EvidenceReviewIntegrityError(
                f"review payload {key} is inconsistent"
            )

    if payload["decision"] != review.decision.value:
        raise EvidenceReviewIntegrityError(
            "review payload decision is inconsistent"
        )
    if payload["reviewed_by"] != review.reviewed_by:
        raise EvidenceReviewIntegrityError(
            "review payload reviewer is inconsistent"
        )
    if payload["reviewed_at"] != review.reviewed_at.isoformat():
        raise EvidenceReviewIntegrityError(
            "review payload timestamp is inconsistent"
        )

    return LoadedEvidenceReview(metadata=review, payload=payload)


def list_evidence_review_refs(
    repository: EvidenceReviewRepository,
    *,
    snapshot_id: str,
) -> List[EvidenceReviewRef]:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    return repository.list_review_refs(snapshot_id)
