"""Controlled specialist drafting: deterministic context/prompt assembly
plus the Step-9.3 generation/parser state machine
(ARCHITECTURE_SPEC_v1_1 §21 and §22 — Phase 2 Steps 9.2 and 9.3).

Step-9.2 surface (private, unchanged):

- the deterministic Step-9 gate preconditions (§20.3, §21.28);
- the closed controlled-context JSON shape in the exact architecture key
  order (§21.1–§21.16);
- deterministic JSON serialization (§21.24);
- closed static prompt asset loading (§21.17–§21.22);
- deterministic prompt assembly (§21.23).

Step-9.3 surface (§22, authoritative):

- the public generate_specialist_draft(...) API (§22.1);
- the exact pre-call failure precedence and blocked-result shapes
  (§22.2–§22.5);
- fresh Python-owned metadata copying (§22.6);
- exactly one LLM call through modules.llm_client.call_gemini (§22.7);
- provider exception / "Error:"-string / non-string handling
  (§22.8–§22.10);
- the strict response JSON parser and interim DraftSection construction
  (§22.12–§22.17);
- the closed SpecialistDraftResult consistency contract
  (§22.18–§22.25).

Step 9.3 does NOT implement post-draft validation, token resolution or
final factual rendering; every successful section carries rendered_text
= "" and post_validation is always None (§22.19, §22.23). Application
integration remains prohibited (§22.29, §21.30).

All module-level names except generate_specialist_draft are
underscore-private (§21.27). Private helper names are implementation-local
and are NOT external machine contracts.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from domain.models import (
    ArithmeticResult,
    ArithmeticStatus,
    DeadlineResult,
    DraftEligibility,
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftSection,
    FactExtractionResult,
    NoticeClassification,
    PreflightResult,
    ProceedingType,
    RequirementStatus,
    SpecialistDraftResult,
    SupportLevel,
    ValidationEngineResult,
    ValidationStatus,
    WorkflowDraftingProfile,
)
from modules.llm_client import call_gemini
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


# --- Phase 2 Step 9.3: generation / parser result-state (§22) -----------------

# §22.24: architecture-owned exact error-message catalog. No alternate
# wording, no raw exception/provider/parser text.
_ERROR_VALIDATION_REQUIRED = (
    "Validation result is required before specialist drafting."
)
_ERROR_DRAFT_BLOCKED = (
    "Specialist drafting is blocked by validation or classification state."
)
_ERROR_WORKFLOW_UNAVAILABLE = (
    "Specialist drafting workflow or prompt assets are unavailable."
)
_ERROR_LLM = "Specialist drafting provider call failed."
_ERROR_MALFORMED = (
    "Specialist drafting response did not match the required schema."
)


def _copy_result_metadata(
    validation_result: ValidationEngineResult,
):
    """§22.6: fresh Python-owned metadata lists. The contained dataclass
    objects may be shared; the returned LIST objects never alias the
    ValidationEngineResult lists. Unresolved = MISSING/UNKNOWN/
    REQUIRES_VERIFICATION only, in validation-result order (§20.15).
    """
    unresolved_requirements = [
        requirement
        for requirement in validation_result.requirements
        if requirement.status in _UNRESOLVED_REQUIREMENT_STATUSES
    ]
    return (
        unresolved_requirements,
        list(validation_result.evidence_checklist),
        list(validation_result.review_requirements),
    )


def _specialist_result(
    validation_result: ValidationEngineResult,
    status: DraftGenerationStatus,
    failure_code=None,
    error_message=None,
    sections=None,
) -> SpecialistDraftResult:
    """§22.4–§22.6, §22.18, §22.20: closed result construction for every
    validation_result-present path. post_validation is always None in
    Step 9.3 (§22.23)."""
    unresolved, evidence, reviews = _copy_result_metadata(validation_result)
    return SpecialistDraftResult(
        status=status,
        draft_eligibility=validation_result.draft_eligibility,
        sections=[] if sections is None else sections,
        unresolved_requirements=unresolved,
        evidence_checklist=evidence,
        review_requirements=reviews,
        post_validation=None,
        failure_code=failure_code,
        error_message=error_message,
    )


def _parse_strict_sections(
    response_trimmed: str,
    profile_sections,
) -> Optional[List[DraftSection]]:
    """§22.12–§22.17: strict response parser.

    Parses only response_trimmed via json.loads — no fence stripping, no
    substring extraction, no repair, no coercion, no retry. Enforces the
    exact root/section schema, the exact section count, and the exact
    case-sensitive profile IDs in profile order. Every body_template is
    stripped once and must be non-empty; internal content is preserved
    exactly. Returns a fresh List[DraftSection] with rendered_text == ""
    on complete success, or None on ANY violation (§22.21: no partial
    success).
    """
    try:
        parsed = json.loads(response_trimmed)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if set(parsed.keys()) != {"sections"}:
        return None
    raw_sections = parsed["sections"]
    if not isinstance(raw_sections, list):
        return None
    if len(raw_sections) != len(profile_sections):
        return None
    sections = []
    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            return None
        if set(raw_section.keys()) != {"section_id", "body_template"}:
            return None
        returned_id = raw_section["section_id"]
        body_template = raw_section["body_template"]
        if not isinstance(returned_id, str) or not isinstance(
            body_template, str
        ):
            return None
        profile_section = profile_sections[index]
        if returned_id != profile_section.section_id:
            return None
        normalized_body = body_template.strip()
        if normalized_body == "":
            return None
        sections.append(
            DraftSection(
                section_id=profile_section.section_id,
                title=profile_section.title,
                template_text=normalized_body,
                rendered_text="",
            )
        )
    return sections


def generate_specialist_draft(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult] = None,
) -> SpecialistDraftResult:
    """Public Step-9 API (§20.1, §22.1): exactly one controlled specialist
    drafting LLM call plus the strict response parser (§22).

    Pre-call failure precedence is deterministic (§22.3):
    1. validation_result is None → VALIDATION_REQUIRED (§22.2);
    2. classification/support/eligibility prohibits drafting or any check
       is FAIL → DRAFT_BLOCKED (§22.4);
    3. workflow/profile/prompt availability inconsistency →
       WORKFLOW_UNAVAILABLE (§22.5);
    4. otherwise call modules.llm_client.call_gemini exactly once (§22.7)
       and parse the single response strictly (§22.12–§22.17).

    SUCCESS is interim only: post_validation is None and every section
    has rendered_text == "" (§22.19). No token resolution, no post-draft
    validation, no app integration. Inputs are never mutated (§22.26).
    """
    if validation_result is None:
        return SpecialistDraftResult(
            status=DraftGenerationStatus.BLOCKED,
            draft_eligibility=DraftEligibility.BLOCKED,
            sections=[],
            unresolved_requirements=[],
            evidence_checklist=[],
            review_requirements=[],
            post_validation=None,
            failure_code=DraftFailureCode.VALIDATION_REQUIRED,
            error_message=_ERROR_VALIDATION_REQUIRED,
        )

    if (
        classification.support_level is not SupportLevel.DEEP_WORKFLOW
        or classification.proceeding_type is ProceedingType.UNKNOWN
        or validation_result.draft_eligibility
        not in (DraftEligibility.REVIEW_REQUIRED, DraftEligibility.ALLOWED)
        or any(
            item.status is ValidationStatus.FAIL
            for item in validation_result.checks
        )
    ):
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.BLOCKED,
            DraftFailureCode.DRAFT_BLOCKED,
            _ERROR_DRAFT_BLOCKED,
        )

    workflow = get_workflow(classification.proceeding_type)
    drafting_profile = get_drafting_profile(classification.proceeding_type)
    if (
        workflow is None
        or drafting_profile is None
        or workflow.proceeding_type is not classification.proceeding_type
        or drafting_profile.proceeding_type
        is not classification.proceeding_type
    ):
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.BLOCKED,
            DraftFailureCode.WORKFLOW_UNAVAILABLE,
            _ERROR_WORKFLOW_UNAVAILABLE,
        )

    prompt = _build_specialist_prompt(
        classification,
        extraction_result,
        preflight_result,
        arithmetic_results,
        validation_result,
        deadline_result,
    )
    if prompt is None:
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.BLOCKED,
            DraftFailureCode.WORKFLOW_UNAVAILABLE,
            _ERROR_WORKFLOW_UNAVAILABLE,
        )

    try:
        response = call_gemini(prompt)
    except Exception:
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.LLM_ERROR,
            _ERROR_LLM,
        )

    if not isinstance(response, str):
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.LLM_ERROR,
            _ERROR_LLM,
        )

    response_trimmed = response.strip()
    if response_trimmed.startswith("Error:"):
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.LLM_ERROR,
            _ERROR_LLM,
        )

    if response_trimmed == "":
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.MALFORMED_RESPONSE,
            _ERROR_MALFORMED,
        )

    sections = _parse_strict_sections(
        response_trimmed, drafting_profile.sections
    )
    if sections is None:
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.MALFORMED_RESPONSE,
            _ERROR_MALFORMED,
        )

    return _specialist_result(
        validation_result,
        DraftGenerationStatus.SUCCESS,
        sections=sections,
    )
