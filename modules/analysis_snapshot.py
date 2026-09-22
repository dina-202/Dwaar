"""Explicit JSON projection for Phase-2 analysis snapshots.

No pickle, object hooks, dataclass recursion, or dynamic class construction.
The schema is intentionally curated and versioned.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
)
from domain.models import (
    ArithmeticResult,
    DraftPostValidationResult,
    DraftSection,
    EvidenceChecklistItem,
    ExtractedFact,
    Phase2AnalysisResult,
    RequirementResult,
    ReviewRequirement,
    TriageSummary,
    ValidationItem,
)


def _date(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _decimal(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def _fact(item: ExtractedFact) -> Dict[str, object]:
    return {
        "fact_id": item.fact_id,
        "claim": item.claim,
        "status": item.status.value,
        "source_text": item.source_text,
        "source_page": item.source_page,
        "allowed_in_draft": item.allowed_in_draft.value,
        "fact_type": item.fact_type.value,
        "fact_role": item.fact_role.value,
        "source_origin": item.source_origin.value,
        "source_verification": item.source_verification.value,
    }


def _arithmetic(item: ArithmeticResult) -> Dict[str, object]:
    return {
        "calculation_type": item.calculation_type.value,
        "status": item.status.value,
        "source_fact_ids": list(item.source_fact_ids),
        "operand_values": [_decimal(value) for value in item.operand_values],
        "result": _decimal(item.result),
        "formula": item.formula,
        "currency": item.currency,
        "allowed_in_draft": item.allowed_in_draft.value,
    }


def _validation_item(item: ValidationItem) -> Dict[str, object]:
    return {
        "check_id": item.check_id,
        "status": item.status.value,
        "message": item.message,
        "related_fact_ids": list(item.related_fact_ids),
        "related_calculation_types": [
            value.value for value in item.related_calculation_types
        ],
    }


def _requirement(item: RequirementResult) -> Dict[str, object]:
    return {
        "requirement_id": item.requirement_id,
        "requirement_text": item.requirement_text,
        "status": item.status.value,
        "related_fact_ids": list(item.related_fact_ids),
        "calculation_type": (
            None
            if item.calculation_type is None
            else item.calculation_type.value
        ),
    }


def _evidence(item: EvidenceChecklistItem) -> Dict[str, object]:
    return {
        "evidence_id": item.evidence_id,
        "requirement_text": item.requirement_text,
        "status": item.status.value,
    }


def _review(item: ReviewRequirement) -> Dict[str, object]:
    return {
        "review_id": item.review_id,
        "level": item.level.value,
        "reason": item.reason,
        "mandatory": item.mandatory,
    }


def _draft_section(item: DraftSection) -> Dict[str, object]:
    return {
        "section_id": item.section_id,
        "title": item.title,
        "rendered_text": item.rendered_text,
    }


def _post_validation(
    item: Optional[DraftPostValidationResult],
) -> Optional[Dict[str, object]]:
    if item is None:
        return None
    return {
        "overall_status": item.overall_status.value,
        "checks": [_validation_item(value) for value in item.checks],
    }


def _triage(
    item: Optional[TriageSummary],
) -> Optional[Dict[str, object]]:
    if item is None:
        return None
    return {
        "proceeding_type": item.proceeding_type.value,
        "notice_form": item.notice_form.value,
        "support_level": item.support_level.value,
        "classification_confidence": (
            item.classification_confidence.value
        ),
        "extraction_status": item.extraction_status.value,
        "portal_verification_required": item.portal_verification_required,
        "authority_verification_required": (
            item.authority_verification_required
        ),
        "communication_identifier_status": (
            item.communication_identifier_status.value
        ),
        "authority_details_status": item.authority_details_status.value,
        "deadline_status": item.deadline_status.value,
        "hearing_status": item.hearing_status.value,
        "requested_document_fact_ids": list(
            item.requested_document_fact_ids
        ),
        "referenced_annexure_fact_ids": list(
            item.referenced_annexure_fact_ids
        ),
        "message": item.message,
    }


def build_snapshot_payload(
    analysis: Phase2AnalysisResult,
    *,
    source_document_id: str,
    source_document_sha256: str,
) -> Dict[str, object]:
    """Project current analysis into the closed snapshot schema."""
    if not isinstance(analysis, Phase2AnalysisResult):
        raise TypeError("analysis must be a Phase2AnalysisResult")
    if not isinstance(source_document_id, str) or not source_document_id:
        raise ValueError("source_document_id must be non-empty")
    if (
        not isinstance(source_document_sha256, str)
        or len(source_document_sha256) != 64
    ):
        raise ValueError("source_document_sha256 must be 64 hex chars")
    try:
        int(source_document_sha256, 16)
    except ValueError as error:
        raise ValueError(
            "source_document_sha256 must be 64 hex chars"
        ) from error

    classification = analysis.classification
    extraction = analysis.extraction_result
    deadline = analysis.deadline_result
    preflight = analysis.preflight_result
    validation = analysis.validation_result
    draft = analysis.draft_result

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "engine_version": ANALYSIS_ENGINE_VERSION,
        "source": {
            "document_id": source_document_id,
            "sha256": source_document_sha256.lower(),
        },
        "classification": {
            "notice_family": classification.notice_family.value,
            "notice_form": classification.notice_form.value,
            "proceeding_type": classification.proceeding_type.value,
            "support_level": classification.support_level.value,
            "confidence": classification.confidence.value,
            "classification_reasons": list(
                classification.classification_reasons
            ),
        },
        "extraction": {
            "status": extraction.status.value,
            "rejected_item_count": extraction.rejected_item_count,
            "facts": [_fact(item) for item in extraction.facts],
        },
        "deadline": {
            "notice_date": _date(deadline.notice_date),
            "service_date": _date(deadline.service_date),
            "response_period_days": deadline.response_period_days,
            "response_deadline": _date(deadline.response_deadline),
            "deadline_confidence": deadline.deadline_confidence.value,
            "deadline_status": deadline.deadline_status.value,
            "days_remaining": deadline.days_remaining,
            "hearing_date": _date(deadline.hearing_date),
            "hearing_status": deadline.hearing_status.value,
            "portal_verification_required": (
                deadline.portal_verification_required
            ),
            "notes": list(deadline.notes),
        },
        "preflight": {
            "fact_extraction_status": (
                preflight.fact_extraction_status.value
            ),
            "communication_identifier_status": (
                preflight.communication_identifier_status.value
            ),
            "portal_verification_required": (
                preflight.portal_verification_required
            ),
            "authority_details_status": (
                preflight.authority_details_status.value
            ),
            "authority_verification_required": (
                preflight.authority_verification_required
            ),
            "stated_due_date_fact_ids": list(
                preflight.stated_due_date_fact_ids
            ),
            "parsed_stated_due_dates": [
                _date(value) for value in preflight.parsed_stated_due_dates
            ],
            "unparsed_stated_due_date_fact_ids": list(
                preflight.unparsed_stated_due_date_fact_ids
            ),
            "deadline_conflict_status": (
                preflight.deadline_conflict_status.value
            ),
            "hearing_fact_ids": list(preflight.hearing_fact_ids),
            "requested_document_fact_ids": list(
                preflight.requested_document_fact_ids
            ),
            "referenced_annexure_fact_ids": list(
                preflight.referenced_annexure_fact_ids
            ),
        },
        "arithmetic": [
            _arithmetic(item) for item in analysis.arithmetic_results
        ],
        "validation": {
            "overall_status": validation.overall_status.value,
            "draft_eligibility": validation.draft_eligibility.value,
            "case_severity": (
                None
                if validation.case_severity is None
                else validation.case_severity.value
            ),
            "checks": [
                _validation_item(item) for item in validation.checks
            ],
            "requirements": [
                _requirement(item) for item in validation.requirements
            ],
            "evidence_checklist": [
                _evidence(item) for item in validation.evidence_checklist
            ],
            "review_requirements": [
                _review(item) for item in validation.review_requirements
            ],
        },
        "draft": {
            "status": draft.status.value,
            "draft_eligibility": draft.draft_eligibility.value,
            "sections": [
                _draft_section(item) for item in draft.sections
            ],
            "unresolved_requirements": [
                _requirement(item)
                for item in draft.unresolved_requirements
            ],
            "evidence_checklist": [
                _evidence(item) for item in draft.evidence_checklist
            ],
            "review_requirements": [
                _review(item) for item in draft.review_requirements
            ],
            "post_validation": _post_validation(
                draft.post_validation
            ),
            "failure_code": (
                None
                if draft.failure_code is None
                else draft.failure_code.value
            ),
            "error_message": draft.error_message,
        },
        "triage_summary": _triage(analysis.triage_summary),
    }


def encode_snapshot_payload(payload: Dict[str, object]) -> bytes:
    """Encode exactly one schema-v1 snapshot as deterministic UTF-8 JSON."""
    validate_snapshot_payload(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "engine_version",
        "source",
        "classification",
        "extraction",
        "deadline",
        "preflight",
        "arithmetic",
        "validation",
        "draft",
        "triage_summary",
    }
)


def validate_snapshot_payload(payload: object) -> Dict[str, object]:
    """Fail closed on unsupported/malformed snapshot envelope."""
    if not isinstance(payload, dict):
        raise ValueError("snapshot payload must be a JSON object")
    if set(payload) != _TOP_LEVEL_KEYS:
        raise ValueError("snapshot payload top-level schema is invalid")
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema version")
    if payload.get("engine_version") != ANALYSIS_ENGINE_VERSION:
        raise ValueError("unsupported snapshot engine version")

    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {
        "document_id",
        "sha256",
    }:
        raise ValueError("snapshot source binding is invalid")
    document_id = source.get("document_id")
    sha256_hex = source.get("sha256")
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("snapshot source document_id is invalid")
    if not isinstance(sha256_hex, str) or len(sha256_hex) != 64:
        raise ValueError("snapshot source sha256 is invalid")
    try:
        int(sha256_hex, 16)
    except ValueError as error:
        raise ValueError("snapshot source sha256 is invalid") from error

    # Every remaining section has a fixed container type. Deeper field
    # contracts are pinned by serializer tests and schema-version changes.
    for key in (
        "classification",
        "extraction",
        "deadline",
        "preflight",
        "validation",
        "draft",
    ):
        if not isinstance(payload.get(key), dict):
            raise ValueError(f"snapshot section '{key}' is invalid")
    if not isinstance(payload.get("arithmetic"), list):
        raise ValueError("snapshot arithmetic section is invalid")
    if payload.get("triage_summary") is not None and not isinstance(
        payload.get("triage_summary"), dict
    ):
        raise ValueError("snapshot triage_summary is invalid")

    return payload


def decode_snapshot_payload(encoded: bytes) -> Dict[str, object]:
    """Decode JSON only; never construct Python domain objects."""
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError("snapshot bytes must be non-empty")
    try:
        text = encoded.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("snapshot is not valid UTF-8 JSON") from error
    return validate_snapshot_payload(payload)
