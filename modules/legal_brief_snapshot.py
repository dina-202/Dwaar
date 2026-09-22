"""Deterministic JSON projection for snapshot-bound legal briefs."""

from __future__ import annotations

import json
from datetime import date
from typing import Dict

from domain.legal_brief_models import LEGAL_BRIEF_SCHEMA_VERSION
from domain.legal_knowledge_models import LegalKnowledgeResult
from domain.models import ProceedingType


def build_legal_brief_payload(
    result: LegalKnowledgeResult,
    *,
    snapshot_id: str,
    as_of_date: date,
    proceeding_type: ProceedingType,
) -> Dict[str, object]:
    if not isinstance(result, LegalKnowledgeResult):
        raise TypeError("result must be a LegalKnowledgeResult")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be a date")
    if not isinstance(proceeding_type, ProceedingType):
        raise TypeError("proceeding_type must be a ProceedingType")
    if not result.catalog_valid:
        raise ValueError("invalid legal catalog cannot be snapshotted")
    if not isinstance(result.catalog_version, str) or not result.catalog_version:
        raise ValueError("catalog_version must be non-empty")

    return {
        "schema_version": LEGAL_BRIEF_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "catalog_version": result.catalog_version,
        "as_of_date": as_of_date.isoformat(),
        "proceeding_type": proceeding_type.value,
        "matches": [
            {
                "rule_id": match.rule.rule_id,
                "rule_key": match.rule.rule_key,
                "topic": match.rule.topic.value,
                "provision": match.rule.provision,
                "proposition": match.rule.proposition,
                "effective_from": match.rule.effective_from.isoformat(),
                "effective_to": (
                    None
                    if match.rule.effective_to is None
                    else match.rule.effective_to.isoformat()
                ),
                "jurisdiction": match.rule.jurisdiction,
                "source_id": match.source.source_id,
                "source_title": match.source.title,
                "official_url": match.source.official_url,
                "source_version_label": match.source.version_label,
                "rule_verified_at": match.rule.verified_at.isoformat(),
            }
            for match in result.matches
        ],
        "unresolved_topics": [
            topic.value for topic in result.unresolved_topics
        ],
    }


_TOP_LEVEL_KEYS = frozenset({
    "schema_version",
    "snapshot_id",
    "catalog_version",
    "as_of_date",
    "proceeding_type",
    "matches",
    "unresolved_topics",
})
_MATCH_KEYS = frozenset({
    "rule_id",
    "rule_key",
    "topic",
    "provision",
    "proposition",
    "effective_from",
    "effective_to",
    "jurisdiction",
    "source_id",
    "source_title",
    "official_url",
    "source_version_label",
    "rule_verified_at",
})


def validate_legal_brief_payload(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise ValueError("legal brief top-level schema is invalid")
    if payload.get("schema_version") != LEGAL_BRIEF_SCHEMA_VERSION:
        raise ValueError("unsupported legal brief schema version")

    for key in ("snapshot_id", "catalog_version", "as_of_date", "proceeding_type"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"legal brief {key} is invalid")

    try:
        date.fromisoformat(payload["as_of_date"])
        ProceedingType(payload["proceeding_type"])
    except (ValueError, TypeError) as error:
        raise ValueError("legal brief date/proceeding binding is invalid") from error

    matches = payload.get("matches")
    unresolved = payload.get("unresolved_topics")
    if not isinstance(matches, list) or not isinstance(unresolved, list):
        raise ValueError("legal brief result containers are invalid")

    seen_rule_ids = set()
    for item in matches:
        if not isinstance(item, dict) or set(item) != _MATCH_KEYS:
            raise ValueError("legal brief match schema is invalid")
        for key in (
            "rule_id", "rule_key", "topic", "provision", "proposition",
            "effective_from", "jurisdiction", "source_id", "source_title",
            "official_url", "source_version_label", "rule_verified_at",
        ):
            if not isinstance(item.get(key), str) or not item[key]:
                raise ValueError(f"legal brief match {key} is invalid")
        if item["rule_id"] in seen_rule_ids:
            raise ValueError("legal brief contains duplicate rule_id")
        seen_rule_ids.add(item["rule_id"])
        try:
            date.fromisoformat(item["effective_from"])
            date.fromisoformat(item["rule_verified_at"])
            if item["effective_to"] is not None:
                date.fromisoformat(item["effective_to"])
        except (ValueError, TypeError) as error:
            raise ValueError("legal brief match date is invalid") from error
        if not item["official_url"].startswith("https://"):
            raise ValueError("legal brief official_url is invalid")

    if any(not isinstance(value, str) or not value for value in unresolved):
        raise ValueError("legal brief unresolved topic is invalid")
    if len(unresolved) != len(set(unresolved)):
        raise ValueError("legal brief unresolved topics must be unique")
    return payload


def encode_legal_brief_payload(payload: Dict[str, object]) -> bytes:
    validate_legal_brief_payload(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_legal_brief_payload(encoded: bytes) -> Dict[str, object]:
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError("legal brief bytes must be non-empty")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("legal brief is not valid UTF-8 JSON") from error
    return validate_legal_brief_payload(payload)
