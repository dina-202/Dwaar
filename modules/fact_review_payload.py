"""Encrypted payload format for snapshot-bound professional fact reviews."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional

from domain.fact_review_models import (
    FACT_REVIEW_SCHEMA_VERSION,
    FactReviewDecision,
)


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "binding",
        "fact",
        "decision",
        "reviewer_note",
        "reviewed_at",
        "reviewed_by",
    }
)

_FACT_KEYS = frozenset(
    {
        "fact_id",
        "fact_type",
        "fact_role",
        "status",
        "source_text",
        "source_page",
        "source_origin",
        "source_verification",
        "allowed_in_draft",
    }
)


def source_text_sha256(source_text: str) -> str:
    if not isinstance(source_text, str) or not source_text:
        raise ValueError("source_text must be non-empty")
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def fact_fingerprint(
    *,
    snapshot_id: str,
    fact_id: str,
    source_text_hash: str,
    fact_type: str,
    fact_role: str,
    status: str,
) -> str:
    values = (
        snapshot_id,
        fact_id,
        source_text_hash,
        fact_type,
        fact_role,
        status,
    )
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("fact fingerprint values must be non-empty strings")
    if len(source_text_hash) != 64:
        raise ValueError("source_text_hash must contain 64 hex chars")
    try:
        int(source_text_hash, 16)
    except ValueError as error:
        raise ValueError(
            "source_text_hash must contain 64 hex chars"
        ) from error

    digest = hashlib.sha256()
    digest.update(b"DWAAR-FACT-REVIEW-V1\0")
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_fact_row(fact: object) -> Dict[str, object]:
    if not isinstance(fact, dict) or set(fact) != _FACT_KEYS:
        raise ValueError("fact review source fact is invalid")
    for key in (
        "fact_id",
        "fact_type",
        "fact_role",
        "status",
        "source_text",
        "source_origin",
        "source_verification",
        "allowed_in_draft",
    ):
        if not isinstance(fact.get(key), str) or not fact.get(key):
            raise ValueError(f"fact review source {key} is invalid")
    page = fact.get("source_page")
    if page is not None and (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
    ):
        raise ValueError("fact review source_page is invalid")
    return fact


def build_fact_review_payload(
    fact: Dict[str, object],
    *,
    case_id: str,
    snapshot_id: str,
    decision: FactReviewDecision,
    reviewer_note: Optional[str],
    reviewed_at: datetime,
    reviewed_by: str,
) -> Dict[str, object]:
    fact = _validate_fact_row(dict(fact))
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    if decision not in (
        FactReviewDecision.CONFIRMED,
        FactReviewDecision.REJECTED,
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
    quote_hash = source_text_sha256(fact["source_text"])
    fingerprint = fact_fingerprint(
        snapshot_id=snapshot_id,
        fact_id=fact["fact_id"],
        source_text_hash=quote_hash,
        fact_type=fact["fact_type"],
        fact_role=fact["fact_role"],
        status=fact["status"],
    )
    return {
        "schema_version": FACT_REVIEW_SCHEMA_VERSION,
        "binding": {
            "case_id": case_id,
            "snapshot_id": snapshot_id,
            "fact_id": fact["fact_id"],
            "source_text_sha256": quote_hash,
            "fact_fingerprint": fingerprint,
        },
        "fact": fact,
        "decision": decision.value,
        "reviewer_note": note,
        "reviewed_at": reviewed_at.isoformat(),
        "reviewed_by": reviewed_by,
    }


def validate_fact_review_payload(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise ValueError("fact review payload schema is invalid")
    if payload.get("schema_version") != FACT_REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported fact review schema version")

    binding = payload.get("binding")
    if not isinstance(binding, dict) or set(binding) != {
        "case_id",
        "snapshot_id",
        "fact_id",
        "source_text_sha256",
        "fact_fingerprint",
    }:
        raise ValueError("fact review binding is invalid")
    for key in ("case_id", "snapshot_id", "fact_id"):
        if not isinstance(binding.get(key), str) or not binding.get(key):
            raise ValueError(f"fact review binding {key} is invalid")
    for key in ("source_text_sha256", "fact_fingerprint"):
        value = binding.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"fact review binding {key} is invalid")
        try:
            int(value, 16)
        except ValueError as error:
            raise ValueError(
                f"fact review binding {key} is invalid"
            ) from error

    fact = _validate_fact_row(payload.get("fact"))
    quote_hash = source_text_sha256(fact["source_text"])
    if quote_hash.lower() != binding["source_text_sha256"].lower():
        raise ValueError("fact review source quote hash is inconsistent")
    expected = fact_fingerprint(
        snapshot_id=binding["snapshot_id"],
        fact_id=fact["fact_id"],
        source_text_hash=quote_hash,
        fact_type=fact["fact_type"],
        fact_role=fact["fact_role"],
        status=fact["status"],
    )
    if expected != binding["fact_fingerprint"].lower():
        raise ValueError("fact review fingerprint is inconsistent")
    if fact["fact_id"] != binding["fact_id"]:
        raise ValueError("fact review fact_id is inconsistent")

    if payload.get("decision") not in {
        FactReviewDecision.CONFIRMED.value,
        FactReviewDecision.REJECTED.value,
    }:
        raise ValueError("fact review decision is invalid")
    note = payload.get("reviewer_note")
    if note is not None and not isinstance(note, str):
        raise ValueError("fact review reviewer_note is invalid")
    reviewed_at = payload.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at:
        raise ValueError("fact review reviewed_at is invalid")
    try:
        parsed = datetime.fromisoformat(reviewed_at)
    except ValueError as error:
        raise ValueError("fact review reviewed_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("fact review reviewed_at must be timezone-aware")
    if not isinstance(payload.get("reviewed_by"), str) or not payload.get(
        "reviewed_by"
    ):
        raise ValueError("fact review reviewed_by is invalid")
    return payload


def encode_fact_review_payload(payload: Dict[str, object]) -> bytes:
    validate_fact_review_payload(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_fact_review_payload(encoded: bytes) -> Dict[str, object]:
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError("fact review bytes must be non-empty")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("fact review is not valid UTF-8 JSON") from error
    return validate_fact_review_payload(payload)
