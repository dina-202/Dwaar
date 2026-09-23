"""Deterministic JSON projection for snapshot-bound legal briefs."""

from __future__ import annotations

import json
from datetime import date
from typing import Dict, Optional

from domain.legal_brief_models import (
    LEGAL_BRIEF_SCHEMA_VERSION,
    SUPPORTED_LEGAL_BRIEF_SCHEMA_VERSIONS,
)
from domain.legal_date_models import LegalDateBasis
from domain.legal_knowledge_models import LegalKnowledgeResult, LegalTopic
from domain.legal_question_models import (
    LegalQuestionPlan,
    LegalQuestionStatus,
)
from domain.models import FactRole, FactStatus, FactType, ProceedingType


def _question_rows(
    question_plan: Optional[LegalQuestionPlan],
):
    if question_plan is None:
        return []
    return [
        {
            "question_id": item.question_id,
            "question_text": item.question_text,
            "topic": item.topic.value,
            "date_basis": item.date_basis.value,
            "status": item.status.value,
            "related_fact_ids": list(item.related_fact_ids),
            "missing_fact_selectors": [
                {
                    "fact_type": selector.fact_type.value,
                    "fact_role": selector.fact_role.value,
                    "accepted_statuses": [
                        value.value
                        for value in selector.accepted_statuses
                    ],
                }
                for selector in item.missing_fact_selectors
            ],
            "matched_rule_ids": list(item.matched_rule_ids),
        }
        for item in question_plan.questions
    ]


def build_legal_brief_payload(
    result: LegalKnowledgeResult,
    *,
    snapshot_id: str,
    as_of_date: date,
    proceeding_type: ProceedingType,
    question_plan: Optional[LegalQuestionPlan] = None,
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
    if question_plan is not None:
        if not isinstance(question_plan, LegalQuestionPlan):
            raise TypeError("question_plan must be a LegalQuestionPlan or None")
        if question_plan.proceeding_type is not proceeding_type:
            raise ValueError("question_plan proceeding_type is inconsistent")
        if question_plan.catalog_version != result.catalog_version:
            raise ValueError("question_plan catalog_version is inconsistent")

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
        "questions": _question_rows(question_plan),
    }


_V1_TOP_LEVEL_KEYS = frozenset({
    "schema_version",
    "snapshot_id",
    "catalog_version",
    "as_of_date",
    "proceeding_type",
    "matches",
    "unresolved_topics",
})
_V2_TOP_LEVEL_KEYS = _V1_TOP_LEVEL_KEYS | {"questions"}
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
_QUESTION_KEYS = frozenset({
    "question_id",
    "question_text",
    "topic",
    "date_basis",
    "status",
    "related_fact_ids",
    "missing_fact_selectors",
    "matched_rule_ids",
})
_SELECTOR_KEYS = frozenset({
    "fact_type",
    "fact_role",
    "accepted_statuses",
})


def _validate_common(payload: Dict[str, object]) -> None:
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
            LegalTopic(item["topic"])
            date.fromisoformat(item["effective_from"])
            date.fromisoformat(item["rule_verified_at"])
            if item["effective_to"] is not None:
                date.fromisoformat(item["effective_to"])
        except (ValueError, TypeError) as error:
            raise ValueError("legal brief match value is invalid") from error
        if not item["official_url"].startswith("https://"):
            raise ValueError("legal brief official_url is invalid")

    if any(not isinstance(value, str) or not value for value in unresolved):
        raise ValueError("legal brief unresolved topic is invalid")
    if len(unresolved) != len(set(unresolved)):
        raise ValueError("legal brief unresolved topics must be unique")
    try:
        for value in unresolved:
            LegalTopic(value)
    except ValueError as error:
        raise ValueError("legal brief unresolved topic is invalid") from error


def _validate_questions(payload: Dict[str, object]) -> None:
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("legal brief questions section is invalid")

    seen_ids = set()
    for item in questions:
        if not isinstance(item, dict) or set(item) != _QUESTION_KEYS:
            raise ValueError("legal brief question schema is invalid")
        for key in ("question_id", "question_text", "topic", "date_basis", "status"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise ValueError(f"legal brief question {key} is invalid")
        if item["question_id"] in seen_ids:
            raise ValueError("legal brief question_id must be unique")
        seen_ids.add(item["question_id"])
        try:
            LegalTopic(item["topic"])
            LegalDateBasis(item["date_basis"])
            LegalQuestionStatus(item["status"])
        except ValueError as error:
            raise ValueError("legal brief question enum value is invalid") from error

        related = item.get("related_fact_ids")
        missing = item.get("missing_fact_selectors")
        rule_ids = item.get("matched_rule_ids")
        if not isinstance(related, list) or not isinstance(missing, list):
            raise ValueError("legal brief question fact containers are invalid")
        if not isinstance(rule_ids, list):
            raise ValueError("legal brief question rule IDs are invalid")
        for values, label in (
            (related, "related fact ID"),
            (rule_ids, "matched rule ID"),
        ):
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"legal brief question {label} is invalid")
            if len(values) != len(set(values)):
                raise ValueError(
                    f"legal brief question {label} values must be unique"
                )

        for selector in missing:
            if not isinstance(selector, dict) or set(selector) != _SELECTOR_KEYS:
                raise ValueError(
                    "legal brief missing fact selector schema is invalid"
                )
            statuses = selector.get("accepted_statuses")
            if not isinstance(statuses, list) or not statuses:
                raise ValueError(
                    "legal brief missing fact selector statuses are invalid"
                )
            try:
                FactType(selector["fact_type"])
                FactRole(selector["fact_role"])
                for value in statuses:
                    FactStatus(value)
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError(
                    "legal brief missing fact selector value is invalid"
                ) from error


def validate_legal_brief_payload(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("legal brief top-level schema is invalid")
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_LEGAL_BRIEF_SCHEMA_VERSIONS:
        raise ValueError("unsupported legal brief schema version")
    expected_keys = (
        _V1_TOP_LEVEL_KEYS if schema_version == 1 else _V2_TOP_LEVEL_KEYS
    )
    if set(payload) != expected_keys:
        raise ValueError("legal brief top-level schema is invalid")

    _validate_common(payload)
    if schema_version == 2:
        _validate_questions(payload)
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
