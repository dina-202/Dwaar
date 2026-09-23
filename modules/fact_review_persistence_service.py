"""Encrypted persistence for snapshot-bound professional fact reviews."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from domain.case_models import CaseEvent, CaseEventType
from domain.fact_review_models import (
    FactReviewDecision,
    FactReviewRef,
    LoadedFactReview,
)
from domain.persistence_ports import DocumentStore, FactReviewRepository
from modules.encrypted_document_store import generate_storage_key
from modules.fact_review_payload import (
    build_fact_review_payload,
    decode_fact_review_payload,
    encode_fact_review_payload,
)


class FactReviewPersistenceError(RuntimeError):
    """Fact-review metadata failed and encrypted payload was rolled back."""


class FactReviewConsistencyError(FactReviewPersistenceError):
    """Fact-review metadata failed and payload rollback also failed."""


class FactReviewIntegrityError(RuntimeError):
    """Stored fact-review metadata/payload binding is inconsistent."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def persist_fact_review(
    repository: FactReviewRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    snapshot_id: str,
    fact: Dict[str, object],
    decision: FactReviewDecision,
    reviewer_note: Optional[str],
    actor_id: str,
    reviewed_at: datetime,
) -> FactReviewRef:
    payload = build_fact_review_payload(
        fact,
        case_id=case_id,
        snapshot_id=snapshot_id,
        decision=decision,
        reviewer_note=reviewer_note,
        reviewed_at=reviewed_at,
        reviewed_by=actor_id,
    )
    encoded = encode_fact_review_payload(payload)
    payload_hash = hashlib.sha256(encoded).hexdigest()
    storage_key = generate_storage_key()
    binding = payload["binding"]

    review = FactReviewRef(
        review_id=_id("FREV"),
        case_id=case_id,
        snapshot_id=snapshot_id,
        fact_id=binding["fact_id"],
        fact_fingerprint=binding["fact_fingerprint"],
        source_text_sha256=binding["source_text_sha256"],
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
        event_type=CaseEventType.FACT_REVIEWED,
        occurred_at=reviewed_at,
        actor_id=actor_id,
        payload={
            "review_id": review.review_id,
            "snapshot_id": snapshot_id,
            "fact_id": review.fact_id,
            "fact_fingerprint": review.fact_fingerprint,
            "source_text_sha256": review.source_text_sha256,
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
            raise FactReviewConsistencyError(
                "Fact-review metadata failed and encrypted payload rollback "
                "also failed."
            ) from rollback_error
        raise FactReviewPersistenceError(
            "Fact-review metadata failed; encrypted payload was rolled back."
        ) from persistence_error
    return review


def load_fact_review(
    repository: FactReviewRepository,
    document_store: DocumentStore,
    *,
    review_id: str,
) -> LoadedFactReview:
    if not isinstance(review_id, str) or not review_id:
        raise ValueError("review_id must be non-empty")
    review = repository.get_review_ref(review_id)
    if review is None:
        raise LookupError("fact review does not exist")

    encoded = document_store.get(review.storage_key)
    if len(encoded) != review.byte_size:
        raise FactReviewIntegrityError(
            "fact-review byte size does not match metadata"
        )
    if hashlib.sha256(encoded).hexdigest() != review.sha256_hex:
        raise FactReviewIntegrityError(
            "fact-review payload hash does not match metadata"
        )
    try:
        payload = decode_fact_review_payload(encoded)
    except ValueError as error:
        raise FactReviewIntegrityError(
            "fact-review payload is invalid"
        ) from error

    binding = payload["binding"]
    expected = (
        ("case_id", review.case_id),
        ("snapshot_id", review.snapshot_id),
        ("fact_id", review.fact_id),
        ("fact_fingerprint", review.fact_fingerprint),
        ("source_text_sha256", review.source_text_sha256),
    )
    hash_keys = {"fact_fingerprint", "source_text_sha256"}
    for key, value in expected:
        actual = binding[key]
        if key in hash_keys:
            if not isinstance(actual, str) or actual.lower() != value.lower():
                raise FactReviewIntegrityError(
                    f"fact-review payload {key} is inconsistent"
                )
        elif actual != value:
            raise FactReviewIntegrityError(
                f"fact-review payload {key} is inconsistent"
            )
    if payload["decision"] != review.decision.value:
        raise FactReviewIntegrityError(
            "fact-review payload decision is inconsistent"
        )
    if payload["reviewed_by"] != review.reviewed_by:
        raise FactReviewIntegrityError(
            "fact-review payload reviewer is inconsistent"
        )
    if payload["reviewed_at"] != review.reviewed_at.isoformat():
        raise FactReviewIntegrityError(
            "fact-review payload timestamp is inconsistent"
        )
    return LoadedFactReview(metadata=review, payload=payload)


def list_fact_review_refs(
    repository: FactReviewRepository,
    *,
    snapshot_id: str,
) -> List[FactReviewRef]:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    return repository.list_review_refs(snapshot_id)
