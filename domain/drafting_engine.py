"""Controlled specialist-drafting context builder and deterministic prompt
assembly (ARCHITECTURE_SPEC_v1_1 §21 — Phase 2 Step 9.2).

This module implements ONLY the Step-9.2 machine contract:

- the deterministic Step-9 gate preconditions (§20.3, §21.28);
- the closed controlled-context JSON shape in the exact architecture key
  order (§21.1–§21.16);
- deterministic JSON serialization (§21.24);
- closed static prompt asset loading (§21.17–§21.22);
- deterministic prompt assembly (§21.23).

ZERO LLM calls, zero response parsing, zero post-draft validation, zero
application integration. The single LLM call belongs to Step 9.3 (§20.4)
and is not implemented here.

All module-level names are deliberately underscore-private (§21.27): the
architecture-owned public drafting API generate_specialist_draft(...)
begins in Step 9.3. Private helper names are implementation-local and are
NOT external machine contracts.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from domain.models import (
    ArithmeticResult,
    ArithmeticStatus,
    DeadlineResult,
    DraftEligibility,
    DraftPermission,
    FactExtractionResult,
    NoticeClassification,
    PreflightResult,
    ProceedingType,
    RequirementStatus,
    SupportLevel,
    ValidationEngineResult,
    ValidationStatus,
    WorkflowDraftingProfile,
)
from workflows.gst import get_workflow
from workflows.gst.drafting_profiles import get_drafting_profile

_SCHEMA_VERSION = "phase2.step9.v1"

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "drafting"
_BASE_PROMPT_PATH = _PROMPTS_DIR / "base_rules.txt"

# Closed §21.21 prompt-key → file mapping. No caller path, no traversal, no
# discovery: an unknown key resolves to None (§21.22).
_WORKFLOW_PROMPT_PATHS: Dict[str, Path] = {
    "sec73_itc": _PROMPTS_DIR / "gst" / "sec73_itc.txt",
    "sec73_general": _PROMPTS_DIR / "gst" / "sec73_general.txt",
    "sec73_rcm": _PROMPTS_DIR / "gst" / "sec73_rcm.txt",
    "sec74_fraud": _PROMPTS_DIR / "gst" / "sec74_fraud.txt",
    "sec129": _PROMPTS_DIR / "gst" / "sec129.txt",
}

_CONTEXT_BEGIN_MARKER = "CONTROLLED_CONTEXT_JSON_BEGIN"
_CONTEXT_END_MARKER = "CONTROLLED_CONTEXT_JSON_END"

# §21.7: the five structural arithmetic Step-8 checks. A result enters the
# affirmative arithmetic context only when all five are PASS. The emitted
# arithmetic.{N}.outcome check is NOT structural (§19.64) and is
# deliberately absent here.
_ARITHMETIC_STRUCTURAL_SUFFIXES = (
    "calculation_type",
    "draft_permission",
    "source_resolution",
    "role_provenance",
    "result_status_consistency",
)

# §20.15: the three unresolved requirement states.
_UNRESOLVED_REQUIREMENT_STATUSES = (
    RequirementStatus.MISSING,
    RequirementStatus.UNKNOWN,
    RequirementStatus.REQUIRES_VERIFICATION,
)


def _serialize_decimal(value):
    """Decimal → exact decimal string, never float (§21.15)."""
    return str(value)


def _serialize_date(value):
    """date → ISO YYYY-MM-DD (§21.15)."""
    return value.isoformat()


def _serialize_optional_date(value):
    """Optional date → ISO YYYY-MM-DD or None/null (§21.15)."""
    return None if value is None else value.isoformat()


def _serialize_fact(fact) -> Dict:
    """§21.5: the exact seven fact context fields in this order. No claim,
    no token, no invented fields."""
    return {
        "fact_id": fact.fact_id,
        "fact_type": fact.fact_type.value,
        "fact_role": fact.fact_role.value,
        "status": fact.status.value,
        "source_text": fact.source_text,
        "source_page": fact.source_page,
        "allowed_in_draft": fact.allowed_in_draft.value,
    }


def _build_arithmetic_context(
    arithmetic_results: List[ArithmeticResult],
    checks,
) -> List[Dict]:
    """§21.7–§21.8: affirmative arithmetic context.

    N is the ORIGINAL one-based input position; filtering never renumbers.
    A result is included only when all five structural checks for its N
    are PASS and its status is PASS or MISMATCH. No recomputation.
    """
    status_by_id = {item.check_id: item.status for item in checks}
    context = []
    for index, result in enumerate(arithmetic_results, start=1):
        if result.status not in (
            ArithmeticStatus.PASS,
            ArithmeticStatus.MISMATCH,
        ):
            continue
        if any(
            status_by_id.get(f"arithmetic.{index}.{suffix}")
            is not ValidationStatus.PASS
            for suffix in _ARITHMETIC_STRUCTURAL_SUFFIXES
        ):
            continue
        context.append(
            {
                "index": index,
                "calculation_type": result.calculation_type.value,
                "status": result.status.value,
                "source_fact_ids": list(result.source_fact_ids),
                "operand_values": [
                    _serialize_decimal(value)
                    for value in result.operand_values
                ],
                "result": (
                    None
                    if result.result is None
                    else _serialize_decimal(result.result)
                ),
                "formula": result.formula,
                "currency": result.currency,
                "allowed_in_draft": result.allowed_in_draft.value,
            }
        )
    return context


def _serialize_preflight(preflight: PreflightResult) -> Dict:
    """§21.9: the exact twelve PreflightResult fields in model order."""
    return {
        "fact_extraction_status": preflight.fact_extraction_status.value,
        "communication_identifier_status": (
            preflight.communication_identifier_status.value
        ),
        "portal_verification_required": (
            preflight.portal_verification_required
        ),
        "authority_details_status": preflight.authority_details_status.value,
        "authority_verification_required": (
            preflight.authority_verification_required
        ),
        "stated_due_date_fact_ids": list(
            preflight.stated_due_date_fact_ids
        ),
        "parsed_stated_due_dates": [
            _serialize_date(value)
            for value in preflight.parsed_stated_due_dates
        ],
        "unparsed_stated_due_date_fact_ids": list(
            preflight.unparsed_stated_due_date_fact_ids
        ),
        "deadline_conflict_status": preflight.deadline_conflict_status.value,
        "hearing_fact_ids": list(preflight.hearing_fact_ids),
        "requested_document_fact_ids": list(
            preflight.requested_document_fact_ids
        ),
        "referenced_annexure_fact_ids": list(
            preflight.referenced_annexure_fact_ids
        ),
    }


def _serialize_deadline(deadline: DeadlineResult) -> Dict:
    """§21.10: the exact eleven DeadlineResult fields in model order.

    Callers handle the deadline_result-is-None case (§21.10: null).
    No current date, no computation, no inferred fields.
    """
    return {
        "notice_date": _serialize_optional_date(deadline.notice_date),
        "service_date": _serialize_optional_date(deadline.service_date),
        "response_period_days": deadline.response_period_days,
        "response_deadline": _serialize_optional_date(
            deadline.response_deadline
        ),
        "deadline_confidence": deadline.deadline_confidence.value,
        "deadline_status": deadline.deadline_status.value,
        "days_remaining": deadline.days_remaining,
        "hearing_date": _serialize_optional_date(deadline.hearing_date),
        "hearing_status": deadline.hearing_status.value,
        "portal_verification_required": deadline.portal_verification_required,
        "notes": list(deadline.notes),
    }


def _serialize_requirement(requirement) -> Dict:
    """§21.11: exact five fields; calculation_type .value or null."""
    return {
        "requirement_id": requirement.requirement_id,
        "requirement_text": requirement.requirement_text,
        "status": requirement.status.value,
        "related_fact_ids": list(requirement.related_fact_ids),
        "calculation_type": (
            None
            if requirement.calculation_type is None
            else requirement.calculation_type.value
        ),
    }


def _serialize_evidence(item) -> Dict:
    """§21.12: exact three fields; status stays exactly as stored."""
    return {
        "evidence_id": item.evidence_id,
        "requirement_text": item.requirement_text,
        "status": item.status.value,
    }


def _serialize_review(item) -> Dict:
    """§21.13: exact four fields; reason copied verbatim."""
    return {
        "review_id": item.review_id,
        "level": item.level.value,
        "reason": item.reason,
        "mandatory": item.mandatory,
    }


def _serialize_warning(item) -> Dict:
    """§21.14: exact five fields for WARNING items only."""
    return {
        "check_id": item.check_id,
        "status": item.status.value,
        "message": item.message,
        "related_fact_ids": list(item.related_fact_ids),
        "related_calculation_types": [
            calc.value for calc in item.related_calculation_types
        ],
    }


def _build_controlled_context(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult],
    drafting_profile: WorkflowDraftingProfile,
) -> Optional[Dict]:
    """§21.1–§21.16: build the single controlled-context dict in the exact
    architecture-owned key order.

    Returns None when validation_result.checks contains any FAIL — an
    inconsistent precondition for a permitted specialist draft (§21.14,
    §21.28). The remaining §20.3 gate conditions are enforced by
    _gate_permitted before this builder is reached.
    """
    if any(
        item.status is ValidationStatus.FAIL
        for item in validation_result.checks
    ):
        return None

    context = {}
    context["schema_version"] = _SCHEMA_VERSION
    context["proceeding_type"] = classification.proceeding_type.value
    context["draft_eligibility"] = validation_result.draft_eligibility.value
    context["sections"] = [
        {"section_id": spec.section_id, "title": spec.title}
        for spec in drafting_profile.sections
    ]
    context["facts"] = [
        _serialize_fact(fact)
        for fact in extraction_result.facts
        if fact.allowed_in_draft
        in (DraftPermission.YES, DraftPermission.CONDITIONAL)
    ]
    context["arithmetic"] = _build_arithmetic_context(
        arithmetic_results, validation_result.checks
    )
    context["preflight"] = _serialize_preflight(preflight_result)
    context["deadline"] = (
        None
        if deadline_result is None
        else _serialize_deadline(deadline_result)
    )
    context["unresolved_requirements"] = [
        _serialize_requirement(requirement)
        for requirement in validation_result.requirements
        if requirement.status in _UNRESOLVED_REQUIREMENT_STATUSES
    ]
    context["evidence_checklist"] = [
        _serialize_evidence(item)
        for item in validation_result.evidence_checklist
    ]
    context["review_requirements"] = [
        _serialize_review(item)
        for item in validation_result.review_requirements
    ]
    context["validation_warnings"] = [
        _serialize_warning(item)
        for item in validation_result.checks
        if item.status is ValidationStatus.WARNING
    ]
    return context


def _serialize_context_json(context: Dict) -> str:
    """§21.24: indent=2, ensure_ascii=False, architecture insertion order
    (no sort_keys)."""
    return json.dumps(context, indent=2, ensure_ascii=False)


def _load_prompt_assets(prompt_key: str) -> Optional[Tuple[str, str]]:
    """§21.21–§21.22: load the fixed base prompt plus the selected
    workflow prompt via the closed key → path mapping. UTF-8, trimmed.

    Returns (base_text, workflow_text), or None when either asset is
    missing, unreadable, or empty after trimming. No fallback asset.
    """
    try:
        base_text = _BASE_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not base_text:
        return None
    path = _WORKFLOW_PROMPT_PATHS.get(prompt_key)
    if path is None:
        return None
    try:
        workflow_text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not workflow_text:
        return None
    return base_text, workflow_text


def _assemble_prompt(base_text: str, workflow_text: str, context_json: str) -> str:
    """§21.23: exact deterministic layout — base, one blank line,
    workflow, one blank line, BEGIN marker, JSON, END marker. Nothing
    before, nothing between, nothing after END."""
    return (
        base_text
        + "\n\n"
        + workflow_text
        + "\n\n"
        + _CONTEXT_BEGIN_MARKER
        + "\n"
        + context_json
        + "\n"
        + _CONTEXT_END_MARKER
    )


def _gate_permitted(
    classification: NoticeClassification,
    validation_result: ValidationEngineResult,
    workflow,
    drafting_profile,
) -> bool:
    """§21.28 gate preconditions 1–8. Prompt asset availability is
    condition 9 and is checked by _load_prompt_assets."""
    if classification.support_level is not SupportLevel.DEEP_WORKFLOW:
        return False
    if classification.proceeding_type is ProceedingType.UNKNOWN:
        return False
    if validation_result.draft_eligibility not in (
        DraftEligibility.REVIEW_REQUIRED,
        DraftEligibility.ALLOWED,
    ):
        return False
    if workflow is None or drafting_profile is None:
        return False
    if workflow.proceeding_type is not classification.proceeding_type:
        return False
    if drafting_profile.proceeding_type is not classification.proceeding_type:
        return False
    if any(
        item.status is ValidationStatus.FAIL
        for item in validation_result.checks
    ):
        return False
    return True


def _build_specialist_prompt(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult] = None,
) -> Optional[str]:
    """Step-9.2 top helper: apply the §21.28 gate, load the closed prompt
    assets, build the controlled context and assemble the deterministic
    specialist prompt.

    Returns None — no permitted prompt — when any gate condition or asset
    precondition fails. Zero LLM calls. Private implementation-local
    helper (§21.27); the public generate_specialist_draft API begins in
    Step 9.3.
    """
    workflow = get_workflow(classification.proceeding_type)
    drafting_profile = get_drafting_profile(classification.proceeding_type)
    if not _gate_permitted(
        classification, validation_result, workflow, drafting_profile
    ):
        return None
    assets = _load_prompt_assets(drafting_profile.prompt_key)
    if assets is None:
        return None
    context = _build_controlled_context(
        classification,
        extraction_result,
        preflight_result,
        arithmetic_results,
        validation_result,
        deadline_result,
        drafting_profile,
    )
    if context is None:
        return None
    return _assemble_prompt(
        assets[0], assets[1], _serialize_context_json(context)
    )
