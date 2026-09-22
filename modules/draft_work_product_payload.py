"""Encrypted draft-version payload format for Dwaar Phase 3K."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional

from domain.draft_work_product_models import DRAFT_VERSION_SCHEMA_VERSION


_KEYS = frozenset(
    {
        "schema_version",
        "case_id",
        "source_snapshot_id",
        "parent_draft_version_id",
        "version_number",
        "generated_baseline",
        "draft_text",
        "created_at",
        "created_by",
    }
)


def draft_content_sha256(draft_text: str) -> str:
    if not isinstance(draft_text, str) or not draft_text.strip():
        raise ValueError("draft_text must be non-empty")
    return hashlib.sha256(draft_text.encode("utf-8")).hexdigest()


def build_draft_payload(
    *,
    case_id: str,
    source_snapshot_id: str,
    parent_draft_version_id: Optional[str],
    version_number: int,
    generated_baseline: bool,
    draft_text: str,
    created_at: datetime,
    created_by: str,
) -> Dict[str, object]:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise ValueError("source_snapshot_id must be non-empty")
    if parent_draft_version_id is not None and (
        not isinstance(parent_draft_version_id, str)
        or not parent_draft_version_id
    ):
        raise ValueError(
            "parent_draft_version_id must be non-empty or None"
        )
    if (
        not isinstance(version_number, int)
        or isinstance(version_number, bool)
        or version_number < 1
    ):
        raise ValueError("version_number must be a positive integer")
    if not isinstance(generated_baseline, bool):
        raise TypeError("generated_baseline must be bool")
    if not isinstance(draft_text, str) or not draft_text.strip():
        raise ValueError("draft_text must be non-empty")
    if len(draft_text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("draft_text exceeds pilot size limit")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    if not isinstance(created_by, str) or not created_by:
        raise ValueError("created_by must be non-empty")

    return {
        "schema_version": DRAFT_VERSION_SCHEMA_VERSION,
        "case_id": case_id,
        "source_snapshot_id": source_snapshot_id,
        "parent_draft_version_id": parent_draft_version_id,
        "version_number": version_number,
        "generated_baseline": generated_baseline,
        "draft_text": draft_text,
        "created_at": created_at.isoformat(),
        "created_by": created_by,
    }


def validate_draft_payload(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _KEYS:
        raise ValueError("draft payload schema is invalid")
    if payload.get("schema_version") != DRAFT_VERSION_SCHEMA_VERSION:
        raise ValueError("unsupported draft payload schema version")

    for key in ("case_id", "source_snapshot_id", "created_by"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"draft payload {key} is invalid")

    parent = payload.get("parent_draft_version_id")
    if parent is not None and (
        not isinstance(parent, str) or not parent
    ):
        raise ValueError("draft parent identity is invalid")

    version_number = payload.get("version_number")
    if (
        not isinstance(version_number, int)
        or isinstance(version_number, bool)
        or version_number < 1
    ):
        raise ValueError("draft version number is invalid")

    if not isinstance(payload.get("generated_baseline"), bool):
        raise ValueError("draft generated_baseline is invalid")

    draft_text = payload.get("draft_text")
    if not isinstance(draft_text, str) or not draft_text.strip():
        raise ValueError("draft text is invalid")
    if len(draft_text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("draft text exceeds pilot size limit")

    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("draft created_at is invalid")
    try:
        parsed = datetime.fromisoformat(created_at)
    except ValueError as error:
        raise ValueError("draft created_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("draft created_at must be timezone-aware")
    return payload


def encode_draft_payload(payload: Dict[str, object]) -> bytes:
    validate_draft_payload(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_draft_payload(encoded: bytes) -> Dict[str, object]:
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError("draft bytes must be non-empty")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("draft is not valid UTF-8 JSON") from error
    return validate_draft_payload(payload)
