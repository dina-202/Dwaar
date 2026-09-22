"""Encrypted payload format for snapshot-bound evidence reviews."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional

from domain.evidence_review_models import EVIDENCE_REVIEW_SCHEMA_VERSION
from domain.models import EvidenceCandidate, EvidenceReviewStatus


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "binding",
        "candidate",
        "decision",
        "reviewer_note",
        "reviewed_at",
        "reviewed_by",
    }
)


def source_text_sha256(source_text: str) -> str:
    if not isinstance(source_text, str) or not source_text:
        raise ValueError("source_text must be non-empty")
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def candidate_fingerprint(
    *,
    snapshot_id: str,
    evidence_id: str,
    document_id: str,
    source_page: int,
    source_text_hash: str,
) -> str:
    values = (snapshot_id, evidence_id, document_id)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("candidate binding identifiers must be non-empty")
    if not isinstance(source_page, int) or isinstance(source_page, bool):
        raise TypeError("source_page must be an integer")
    if source_page < 1:
        raise ValueError("source_page must be positive")
    if not isinstance(source_text_hash, str) or len(source_text_hash) != 64:
        raise ValueError("source_text_hash must contain 64 hex chars")
    try:
        int(source_text_hash, 16)
    except ValueError as error:
        raise ValueError(
            "source_text_hash must contain 64 hex chars"
        ) from error

    digest = hashlib.sha256()
    digest.update(b"DWAAR-EVIDENCE-REVIEW-CANDIDATE-V1\0")
    for value in (
        snapshot_id,
        evidence_id,
        document_id,
        str(source_page),
        source_text_hash.lower(),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def build_review_payload(
    candidate: EvidenceCandidate,
    *,
    case_id: str,
    snapshot_id: str,
    decision: EvidenceReviewStatus,
    reviewer_note: Optional[str],
    reviewed_at: datetime,
    reviewed_by: str,
) -> Dict[str, object]:
    if not isinstance(candidate, EvidenceCandidate):
        raise TypeError("candidate must be an EvidenceCandidate")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    if decision not in (
        EvidenceReviewStatus.CONFIRMED,
        EvidenceReviewStatus.REJECTED,
    ):
        raise ValueError("decision must be CONFIRMED or REJECTED")
    if reviewer_note is not None and not isinstance(reviewer_note, str):
        raise TypeError("reviewer_note must be a string or None")
    if not isinstance(reviewed_at, datetime) or reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must be timezone-aware")
    if not isinstance(reviewed_by, str) or not reviewed_by:
        raise ValueError("reviewed_by must be non-empty")

    note = (
        reviewer_note.strip()
        if isinstance(reviewer_note, str) and reviewer_note.strip()
        else None
    )
    quote_hash = source_text_sha256(candidate.source_text)
    fingerprint = candidate_fingerprint(
        snapshot_id=snapshot_id,
        evidence_id=candidate.evidence_id,
        document_id=candidate.document_id,
        source_page=candidate.source_page,
        source_text_hash=quote_hash,
    )

    return {
        "schema_version": EVIDENCE_REVIEW_SCHEMA_VERSION,
        "binding": {
            "case_id": case_id,
            "snapshot_id": snapshot_id,
            "evidence_id": candidate.evidence_id,
            "document_id": candidate.document_id,
            "source_page": candidate.source_page,
            "source_text_sha256": quote_hash,
            "candidate_fingerprint": fingerprint,
        },
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "source_text": candidate.source_text,
            "source_origin": candidate.source_origin.value,
            "source_verification": candidate.source_verification.value,
        },
        "decision": decision.value,
        "reviewer_note": note,
        "reviewed_at": reviewed_at.isoformat(),
        "reviewed_by": reviewed_by,
    }


def validate_review_payload(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("review payload must be a JSON object")
    if set(payload) != _TOP_LEVEL_KEYS:
        raise ValueError("review payload top-level schema is invalid")
    if payload.get("schema_version") != EVIDENCE_REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported review schema version")

    binding = payload.get("binding")
    if not isinstance(binding, dict) or set(binding) != {
        "case_id",
        "snapshot_id",
        "evidence_id",
        "document_id",
        "source_page",
        "source_text_sha256",
        "candidate_fingerprint",
    }:
        raise ValueError("review binding is invalid")

    for key in ("case_id", "snapshot_id", "evidence_id", "document_id"):
        if not isinstance(binding.get(key), str) or not binding.get(key):
            raise ValueError(f"review binding {key} is invalid")
    page = binding.get("source_page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("review binding source_page is invalid")
    for key in ("source_text_sha256", "candidate_fingerprint"):
        value = binding.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"review binding {key} is invalid")
        try:
            int(value, 16)
        except ValueError as error:
            raise ValueError(
                f"review binding {key} is invalid"
            ) from error

    candidate = payload.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != {
        "candidate_id",
        "source_text",
        "source_origin",
        "source_verification",
    }:
        raise ValueError("review candidate is invalid")
    if (
        not isinstance(candidate.get("candidate_id"), str)
        or not candidate.get("candidate_id")
        or not isinstance(candidate.get("source_text"), str)
        or not candidate.get("source_text")
        or not isinstance(candidate.get("source_origin"), str)
        or not candidate.get("source_origin")
        or not isinstance(candidate.get("source_verification"), str)
        or not candidate.get("source_verification")
    ):
        raise ValueError("review candidate fields are invalid")

    if (
        source_text_sha256(candidate["source_text"]).lower()
        != binding["source_text_sha256"].lower()
    ):
        raise ValueError("review source quote hash is inconsistent")
    expected_fingerprint = candidate_fingerprint(
        snapshot_id=binding["snapshot_id"],
        evidence_id=binding["evidence_id"],
        document_id=binding["document_id"],
        source_page=binding["source_page"],
        source_text_hash=binding["source_text_sha256"],
    )
    if expected_fingerprint != binding["candidate_fingerprint"].lower():
        raise ValueError("review candidate fingerprint is inconsistent")

    if payload.get("decision") not in {
        EvidenceReviewStatus.CONFIRMED.value,
        EvidenceReviewStatus.REJECTED.value,
    }:
        raise ValueError("review decision is invalid")
    if payload.get("reviewer_note") is not None and not isinstance(
        payload.get("reviewer_note"), str
    ):
        raise ValueError("reviewer_note is invalid")
    reviewed_at = payload.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at:
        raise ValueError("reviewed_at is invalid")
    try:
        parsed = datetime.fromisoformat(reviewed_at)
    except ValueError as error:
        raise ValueError("reviewed_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at must be timezone-aware")
    if not isinstance(payload.get("reviewed_by"), str) or not payload.get(
        "reviewed_by"
    ):
        raise ValueError("reviewed_by is invalid")
    return payload


def encode_review_payload(payload: Dict[str, object]) -> bytes:
    validate_review_payload(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_review_payload(encoded: bytes) -> Dict[str, object]:
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError("review bytes must be non-empty")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("review is not valid UTF-8 JSON") from error
    return validate_review_payload(payload)
