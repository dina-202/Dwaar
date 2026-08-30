"""Provenance-complete controlled specialist drafting (§25).

The active public path applies the existing Step-9 eligibility gate,
builds the versioned provenance-v1 controlled prompt, makes exactly one
drafting-layer provider call, and strictly parses identifiers-only typed
blocks. Successfully parsed candidates receive the exact ordered 21-check
deterministic gate. Only candidates whose checks 1–19 pass reach the closed
Python renderer dispatcher; final section text uses only dispatcher output
and architecture-owned static templates.

Legacy body-template parsing, token substitution, and lexical validation
are not production paths. The older context/prompt construction helpers
remain private for their committed deterministic contracts, but
generate_specialist_draft(...) does not call them.

Application/orchestrator replay remains outside Step 9E.3 (§25.28).

All module-level names except generate_specialist_draft are
underscore-private (§21.27). Private helper names are implementation-local
and are NOT external machine contracts.
"""

import json
from pathlib import Path
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

from domain.models import (
    ArithmeticDraftBlock,
    ArithmeticResult,
    ArithmeticStatus,
    DeadlineDraftBlock,
    DeadlineResult,
    DraftCandidateBlock,
    DraftCandidateSection,
    DraftEligibility,
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftPostValidationResult,
    DraftSection,
    EvidenceDraftBlock,
    EvidenceStatus,
    FactExtractionResult,
    FactDraftBlock,
    FactStatus,
    HearingStatus,
    HearingDraftBlock,
    NoticeClassification,
    PreflightResult,
    ProceedingType,
    RequirementStatus,
    RequirementDraftBlock,
    ReviewDraftBlock,
    SpecialistDraftResult,
    StaticDraftBlock,
    SupportLevel,
    ValidationEngineResult,
    ValidationItem,
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

_PROVENANCE_SCHEMA_VERSION = "phase2.step9e.v1"
_PROVENANCE_PROMPTS_DIR = _PROMPTS_DIR / "provenance_v1"
_PROVENANCE_BASE_PROMPT_PATH = _PROVENANCE_PROMPTS_DIR / "base_rules.txt"
_PROVENANCE_WORKFLOW_PROMPT_PATHS: Dict[str, Path] = {
    "sec73_itc": _PROVENANCE_PROMPTS_DIR / "gst" / "sec73_itc.txt",
    "sec73_general": (
        _PROVENANCE_PROMPTS_DIR / "gst" / "sec73_general.txt"
    ),
    "sec73_rcm": _PROVENANCE_PROMPTS_DIR / "gst" / "sec73_rcm.txt",
    "sec74_fraud": _PROVENANCE_PROMPTS_DIR / "gst" / "sec74_fraud.txt",
    "sec129": _PROVENANCE_PROMPTS_DIR / "gst" / "sec129.txt",
}

# Closed §25.13 Python-owned static-template registry used by the active
# validator and STATIC renderer. It is immutable and non-parameterized.
_STATIC_TEMPLATE_REGISTRY: Mapping[str, str] = MappingProxyType(
    {
        "static.working_draft": (
            "This is a CA working draft and requires professional review "
            "before use."
        ),
        "static.notice_material": (
            "The following notice-grounded material is relevant to this "
            "section."
        ),
        "static.open_items": (
            "The following matters remain open for verification."
        ),
        "static.taxpayer_verify": (
            "The taxpayer should verify the relevant records before any "
            "factual submission is made."
        ),
        "static.ca_confirm": (
            "CA review should confirm the relevant factual and evidentiary "
            "position."
        ),
        "static.records_if_available": (
            "If the relevant records are available, they should be "
            "reconciled against the notice-grounded material."
        ),
        "static.records_reconcile": (
            "The relevant records should be reconciled before any factual "
            "submission is made."
        ),
        "static.conditional_response": (
            "Any response should remain conditional on verification of the "
            "structured facts and records identified in this working draft."
        ),
        "static.legal_research_required": (
            "CA legal research is required before relying on any legal "
            "proposition not supplied by a verified legal-rule source."
        ),
        "static.no_legal_conclusion": (
            "This working draft does not express filing approval or a final "
            "legal conclusion."
        ),
    }
)

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


# --- Phase 2 Step 9E: active provenance-v1 context/prompt/parser (§25) --------

def _build_provenance_controlled_context(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult],
    drafting_profile: WorkflowDraftingProfile,
) -> Optional[Dict]:
    """Build the exact active §25.8.1 provenance-v1 context.

    This helper is not called by generate_specialist_draft during Step
    9E.2. It performs no LLM call, parsing, validation or rendering.
    """
    if any(
        item.status is ValidationStatus.FAIL
        for item in validation_result.checks
    ):
        return None

    context = {}
    context["schema_version"] = _PROVENANCE_SCHEMA_VERSION
    context["proceeding_type"] = classification.proceeding_type.value
    context["draft_eligibility"] = validation_result.draft_eligibility.value
    context["sections"] = [
        {"section_id": spec.section_id, "title": spec.title}
        for spec in drafting_profile.sections
    ]
    context["static_template_ids"] = list(_STATIC_TEMPLATE_REGISTRY.keys())
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
    context["requirements"] = [
        _serialize_requirement(requirement)
        for requirement in validation_result.requirements
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


def _load_provenance_prompt_assets(
    prompt_key: str,
) -> Optional[Tuple[str, str]]:
    """Load only the fixed provenance-v1 prompt assets."""
    try:
        base_text = _PROVENANCE_BASE_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return None
    if not base_text:
        return None
    path = _PROVENANCE_WORKFLOW_PROMPT_PATHS.get(prompt_key)
    if path is None:
        return None
    try:
        workflow_text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not workflow_text:
        return None
    return base_text, workflow_text


def _build_provenance_prompt(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult] = None,
) -> Optional[str]:
    """Build the deterministic active provenance-v1 prompt.

    No provider is called. Step 9E.3 alone may activate this replacement.
    """
    workflow = get_workflow(classification.proceeding_type)
    drafting_profile = get_drafting_profile(classification.proceeding_type)
    if not _gate_permitted(
        classification, validation_result, workflow, drafting_profile
    ):
        return None
    assets = _load_provenance_prompt_assets(drafting_profile.prompt_key)
    if assets is None:
        return None
    context = _build_provenance_controlled_context(
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


def _strict_json_object(pairs):
    """Reject duplicate JSON object keys in the provenance-v1 parser."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_provenance_block(raw_block) -> Optional[DraftCandidateBlock]:
    """Construct one exact §25.6 typed block, or reject it."""
    if not isinstance(raw_block, dict):
        return None
    kind = raw_block.get("kind")
    if kind == "static":
        if set(raw_block.keys()) != {"kind", "template_id"}:
            return None
        value = raw_block["template_id"]
        if not isinstance(value, str) or value == "":
            return None
        return StaticDraftBlock(template_id=value)
    if kind == "fact":
        if set(raw_block.keys()) != {"kind", "fact_id"}:
            return None
        value = raw_block["fact_id"]
        if not isinstance(value, str) or value == "":
            return None
        return FactDraftBlock(fact_id=value)
    if kind == "arithmetic":
        if set(raw_block.keys()) != {"kind", "arithmetic_index"}:
            return None
        value = raw_block["arithmetic_index"]
        if type(value) is not int or value <= 0:
            return None
        return ArithmeticDraftBlock(arithmetic_index=value)
    if kind == "deadline":
        if set(raw_block.keys()) != {"kind"}:
            return None
        return DeadlineDraftBlock()
    if kind == "hearing":
        if set(raw_block.keys()) != {"kind"}:
            return None
        return HearingDraftBlock()
    if kind == "requirement":
        if set(raw_block.keys()) != {"kind", "requirement_id"}:
            return None
        value = raw_block["requirement_id"]
        if not isinstance(value, str) or value == "":
            return None
        return RequirementDraftBlock(requirement_id=value)
    if kind == "evidence":
        if set(raw_block.keys()) != {"kind", "evidence_id"}:
            return None
        value = raw_block["evidence_id"]
        if not isinstance(value, str) or value == "":
            return None
        return EvidenceDraftBlock(evidence_id=value)
    if kind == "review":
        if set(raw_block.keys()) != {"kind", "review_id"}:
            return None
        value = raw_block["review_id"]
        if not isinstance(value, str) or value == "":
            return None
        return ReviewDraftBlock(review_id=value)
    return None


def _parse_provenance_response(
    response,
    profile_sections,
) -> Optional[List[DraftCandidateSection]]:
    """Strict active §25.6 typed-response parser; no partial salvage."""
    if not isinstance(response, str):
        return None
    response_trimmed = response.strip()
    if response_trimmed == "":
        return None
    try:
        parsed = json.loads(
            response_trimmed,
            object_pairs_hook=_strict_json_object,
        )
    except Exception:
        return None
    if not isinstance(parsed, dict) or set(parsed.keys()) != {"sections"}:
        return None
    raw_sections = parsed["sections"]
    if not isinstance(raw_sections, list):
        return None
    if len(raw_sections) != len(profile_sections):
        return None

    candidate_sections = []
    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            return None
        if set(raw_section.keys()) != {"section_id", "blocks"}:
            return None
        returned_id = raw_section["section_id"]
        if not isinstance(returned_id, str):
            return None
        if returned_id != profile_sections[index].section_id:
            return None
        raw_blocks = raw_section["blocks"]
        if not isinstance(raw_blocks, list) or len(raw_blocks) == 0:
            return None
        blocks = []
        for raw_block in raw_blocks:
            block = _parse_provenance_block(raw_block)
            if block is None:
                return None
            blocks.append(block)
        candidate_sections.append(
            DraftCandidateSection(
                section_id=returned_id,
                blocks=tuple(blocks),
            )
        )
    return candidate_sections


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
_ERROR_POST_VALIDATION = (
    "Specialist draft failed deterministic post-generation validation."
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


def _dedup_first_occurrence(items):
    """§23.12, §23.15, §23.17: first-occurrence deduplication preserving
    order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _resolve_arithmetic(n, arithmetic_results, validation_result):
    """§23.16: approved only when in-range, all five structural checks
    PASS, status PASS/MISMATCH, and result is not None."""
    if n < 1 or n > len(arithmetic_results):
        return None
    result = arithmetic_results[n - 1]
    if result.status not in (ArithmeticStatus.PASS, ArithmeticStatus.MISMATCH):
        return None
    if result.result is None:
        return None
    status_by_id = {item.check_id: item.status for item in validation_result.checks}
    if any(
        status_by_id.get(f"arithmetic.{n}.{suffix}") is not ValidationStatus.PASS
        for suffix in _ARITHMETIC_STRUCTURAL_SUFFIXES
    ):
        return None
    return result


def _render_fact(fact):
    """§23.39: CONFIRMED → notice records, ALLEGED → department alleges."""
    if fact.status is FactStatus.CONFIRMED:
        text = 'The notice records: "' + (fact.source_text or "") + '"'
    else:
        text = 'The department alleges: "' + (fact.source_text or "") + '"'
    if fact.source_page is not None:
        text += " (notice p. " + str(fact.source_page) + ")"
    return text


def _render_arithmetic(result):
    """§23.40: deterministic reconciliation output line."""
    return (
        "Deterministic reconciliation output: "
        + result.formula
        + " = "
        + str(result.result)
        + " "
        + result.currency
        + " (status: "
        + result.status.value
        + ")."
    )


def _render_deadline(deadline, preflight):
    """§23.41: exact ten-field machine-labelled deadline output."""

    def date_field(value):
        return "null" if value is None else value.isoformat()

    def int_field(value):
        return "null" if value is None else str(value)

    def bool_field(value):
        return "true" if value else "false"

    fields = [
        "notice_date=" + date_field(deadline.notice_date),
        "service_date=" + date_field(deadline.service_date),
        "response_period_days=" + int_field(deadline.response_period_days),
        "response_deadline=" + date_field(deadline.response_deadline),
        "deadline_confidence=" + deadline.deadline_confidence.value,
        "deadline_status=" + deadline.deadline_status.value,
        "days_remaining=" + int_field(deadline.days_remaining),
        "portal_verification_required=" + bool_field(
            deadline.portal_verification_required
        ),
        "notes=" + json.dumps(deadline.notes),
        "preflight_deadline_conflict_status="
        + preflight.deadline_conflict_status.value,
    ]
    return "Deterministic deadline output: " + "; ".join(fields) + "."


def _render_hearing(deadline):
    """§23.42: deterministic hearing output line."""
    return (
        "Deterministic hearing output: hearing_date="
        + deadline.hearing_date.isoformat()
        + "; hearing_status="
        + deadline.hearing_status.value
        + "."
    )


# --- Phase 2 Step 9E.3: active typed validation + Python rendering (§25) ------

_PROVENANCE_CHECK_IDS = (
    "draft.response.schema",
    "draft.sections.count",
    "draft.sections.ids",
    "draft.sections.order",
    "draft.sections.nonempty",
    "draft.blocks.kind",
    "draft.blocks.schema",
    "draft.blocks.static_template",
    "draft.blocks.fact_resolution",
    "draft.blocks.fact_permission",
    "draft.blocks.arithmetic_resolution",
    "draft.blocks.deadline_resolution",
    "draft.blocks.hearing_resolution",
    "draft.blocks.requirement_resolution",
    "draft.blocks.requirement_status",
    "draft.blocks.evidence_resolution",
    "draft.blocks.evidence_status",
    "draft.blocks.review_resolution",
    "draft.blocks.no_freeform",
    "draft.rendering.completeness",
    "draft.rendering.python_owned",
)

_PROVENANCE_MESSAGES = {
    "draft.response.schema": (
        "Draft candidate schema is structurally valid.",
        "Draft candidate schema is not structurally valid.",
    ),
    "draft.sections.count": (
        "Draft section count matches the drafting profile.",
        "Draft section count does not match the drafting profile.",
    ),
    "draft.sections.ids": (
        "Draft section IDs match the drafting profile.",
        "Draft section IDs do not match the drafting profile.",
    ),
    "draft.sections.order": (
        "Draft section order matches the drafting profile.",
        "Draft section order does not match the drafting profile.",
    ),
    "draft.sections.nonempty": (
        "Every draft section contains at least one typed block.",
        "One or more draft sections contain no typed block.",
    ),
    "draft.blocks.kind": (
        "Every draft block kind is architecture-approved.",
        "One or more draft block kinds are not architecture-approved.",
    ),
    "draft.blocks.schema": (
        "Every draft block matches its exact typed schema.",
        "One or more draft blocks do not match their exact typed schema.",
    ),
    "draft.blocks.static_template": (
        "All static blocks resolve to the closed template registry.",
        "One or more static blocks do not resolve to the closed template registry.",
    ),
    "draft.blocks.fact_resolution": (
        "All fact blocks resolve to exactly one eligible ExtractedFact.",
        "One or more fact blocks do not resolve to exactly one eligible ExtractedFact.",
    ),
    "draft.blocks.fact_permission": (
        "All resolved fact blocks satisfy FactStatus and DraftPermission invariants.",
        "One or more resolved fact blocks violate FactStatus or DraftPermission invariants.",
    ),
    "draft.blocks.arithmetic_resolution": (
        "All arithmetic blocks resolve to approved deterministic arithmetic results.",
        "One or more arithmetic blocks do not resolve to approved deterministic arithmetic results.",
    ),
    "draft.blocks.deadline_resolution": (
        "All deadline blocks resolve to the supplied deterministic deadline result.",
        "One or more deadline blocks cannot resolve to the supplied deterministic deadline result.",
    ),
    "draft.blocks.hearing_resolution": (
        "All hearing blocks resolve to supplied deterministic hearing information.",
        "One or more hearing blocks cannot resolve to supplied deterministic hearing information.",
    ),
    "draft.blocks.requirement_resolution": (
        "All requirement blocks resolve to exactly one RequirementResult.",
        "One or more requirement blocks do not resolve to exactly one RequirementResult.",
    ),
    "draft.blocks.requirement_status": (
        "All requirement blocks use the deterministic template authorized for their status.",
        "One or more requirement blocks cannot use a deterministic template authorized for their status.",
    ),
    "draft.blocks.evidence_resolution": (
        "All evidence blocks resolve to exactly one EvidenceChecklistItem.",
        "One or more evidence blocks do not resolve to exactly one EvidenceChecklistItem.",
    ),
    "draft.blocks.evidence_status": (
        "All evidence blocks preserve the architecture-authorized evidence status.",
        "One or more evidence blocks would assert an unauthorized evidence state.",
    ),
    "draft.blocks.review_resolution": (
        "All review blocks resolve to exactly one mandatory ReviewRequirement.",
        "One or more review blocks do not resolve to exactly one mandatory ReviewRequirement.",
    ),
    "draft.blocks.no_freeform": (
        "Draft candidate contains no provider-authored free-form prose field.",
        "Draft candidate contains a provider-authored free-form prose field.",
    ),
    "draft.rendering.completeness": (
        "Every accepted draft block was rendered exactly once in candidate order.",
        "One or more accepted draft blocks were not rendered exactly once in candidate order.",
    ),
    "draft.rendering.python_owned": (
        "Final specialist text is assembled only from Python-owned renderers and closed templates.",
        "Final specialist text contains output not produced by an authorized Python renderer or closed template.",
    ),
}

_PRE_RENDER_COMPLETENESS_FAIL = (
    "Rendering completeness was not established because pre-render validation failed."
)
_PRE_RENDER_PYTHON_OWNED_FAIL = (
    "Python-owned final rendering was not established because pre-render validation failed."
)

_PROVENANCE_BLOCK_TYPES = (
    StaticDraftBlock,
    FactDraftBlock,
    ArithmeticDraftBlock,
    DeadlineDraftBlock,
    HearingDraftBlock,
    RequirementDraftBlock,
    EvidenceDraftBlock,
    ReviewDraftBlock,
)

_PROVENANCE_BLOCK_FIELDS = {
    StaticDraftBlock: (("template_id", str),),
    FactDraftBlock: (("fact_id", str),),
    ArithmeticDraftBlock: (("arithmetic_index", int),),
    DeadlineDraftBlock: (),
    HearingDraftBlock: (),
    RequirementDraftBlock: (("requirement_id", str),),
    EvidenceDraftBlock: (("evidence_id", str),),
    ReviewDraftBlock: (("review_id", str),),
}


def _provenance_item(
    check_id,
    ok,
    related_fact_ids=(),
    related_calculation_types=(),
    fail_message=None,
):
    pass_message, ordinary_fail_message = _PROVENANCE_MESSAGES[check_id]
    return ValidationItem(
        check_id=check_id,
        status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
        message=(
            pass_message
            if ok
            else ordinary_fail_message if fail_message is None else fail_message
        ),
        related_fact_ids=list(related_fact_ids),
        related_calculation_types=list(related_calculation_types),
    )


def _resolve_candidate_fact(fact_id, extraction_result):
    matches = [
        fact for fact in extraction_result.facts if fact.fact_id == fact_id
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_requirement(requirement_id, validation_result):
    matches = [
        item
        for item in validation_result.requirements
        if item.requirement_id == requirement_id
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_evidence(evidence_id, validation_result):
    matches = [
        item
        for item in validation_result.evidence_checklist
        if item.evidence_id == evidence_id
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_review(review_id, validation_result):
    matches = [
        item
        for item in validation_result.review_requirements
        if item.review_id == review_id
    ]
    return matches[0] if len(matches) == 1 else None


def _block_schema_ok(block):
    block_type = type(block)
    expected = _PROVENANCE_BLOCK_FIELDS.get(block_type)
    if expected is None:
        return False
    declared = getattr(block_type, "__dataclass_fields__", {})
    if tuple(
        (name, item.type) for name, item in declared.items()
    ) != expected:
        return False
    if set(vars(block).keys()) != {name for name, _ in expected}:
        return False
    for name, annotation in expected:
        value = getattr(block, name)
        if annotation is int:
            if type(value) is not int or value <= 0:
                return False
        elif not isinstance(value, annotation) or value == "":
            return False
    return True


def _run_provenance_pre_render_validation(
    candidate_sections,
    drafting_profile,
    extraction_result,
    arithmetic_results,
    validation_result,
    deadline_result,
):
    """Emit the exact §25.21 checks 1-19 without invoking a renderer."""
    profile_ids = [spec.section_id for spec in drafting_profile.sections]
    candidate_is_list = isinstance(candidate_sections, list)
    schema_ok = candidate_is_list and all(
        type(section) is DraftCandidateSection
        and isinstance(section.section_id, str)
        and isinstance(section.blocks, tuple)
        for section in candidate_sections
    )
    count_ok = candidate_is_list and len(candidate_sections) == len(profile_ids)
    returned_ids = (
        [
            section.section_id
            if type(section) is DraftCandidateSection
            else None
            for section in candidate_sections
        ]
        if candidate_is_list
        else []
    )
    ids_ok = count_ok and set(returned_ids) == set(profile_ids)
    order_ok = count_ok and returned_ids == profile_ids
    nonempty_ok = schema_ok and all(section.blocks for section in candidate_sections)

    blocks = []
    if candidate_is_list:
        for section in candidate_sections:
            if type(section) is DraftCandidateSection and isinstance(
                section.blocks, tuple
            ):
                blocks.extend(section.blocks)

    kind_ok = schema_ok and all(type(block) in _PROVENANCE_BLOCK_TYPES for block in blocks)
    block_schema_ok = kind_ok and all(_block_schema_ok(block) for block in blocks)

    static_blocks = [block for block in blocks if type(block) is StaticDraftBlock]
    fact_blocks = [block for block in blocks if type(block) is FactDraftBlock]
    arithmetic_blocks = [
        block for block in blocks if type(block) is ArithmeticDraftBlock
    ]
    deadline_blocks = [block for block in blocks if type(block) is DeadlineDraftBlock]
    hearing_blocks = [block for block in blocks if type(block) is HearingDraftBlock]
    requirement_blocks = [
        block for block in blocks if type(block) is RequirementDraftBlock
    ]
    evidence_blocks = [block for block in blocks if type(block) is EvidenceDraftBlock]
    review_blocks = [block for block in blocks if type(block) is ReviewDraftBlock]

    static_ok = all(
        _block_schema_ok(block)
        and block.template_id in _STATIC_TEMPLATE_REGISTRY
        for block in static_blocks
    )

    resolved_facts = {
        block.fact_id: _resolve_candidate_fact(block.fact_id, extraction_result)
        for block in fact_blocks
        if _block_schema_ok(block)
    }
    fact_resolution_ok = all(
        _block_schema_ok(block) and resolved_facts.get(block.fact_id) is not None
        for block in fact_blocks
    )
    fact_permission_ok = True
    for block in fact_blocks:
        if not _block_schema_ok(block):
            fact_permission_ok = False
            continue
        fact = resolved_facts.get(block.fact_id)
        if fact is None:
            continue
        if not (
            (
                fact.status is FactStatus.CONFIRMED
                and fact.allowed_in_draft is DraftPermission.YES
            )
            or (
                fact.status is FactStatus.ALLEGED
                and fact.allowed_in_draft is DraftPermission.CONDITIONAL
            )
        ):
            fact_permission_ok = False

    arithmetic_ok = all(
        _block_schema_ok(block)
        and _resolve_arithmetic(
            block.arithmetic_index, arithmetic_results, validation_result
        )
        is not None
        for block in arithmetic_blocks
    )
    deadline_ok = not deadline_blocks or deadline_result is not None
    hearing_ok = not hearing_blocks or (
        deadline_result is not None
        and deadline_result.hearing_date is not None
        and deadline_result.hearing_status
        in (HearingStatus.UPCOMING, HearingStatus.TODAY, HearingStatus.PASSED)
    )

    resolved_requirements = {
        block.requirement_id: _resolve_requirement(
            block.requirement_id, validation_result
        )
        for block in requirement_blocks
        if _block_schema_ok(block)
    }
    requirement_resolution_ok = all(
        _block_schema_ok(block)
        and resolved_requirements.get(block.requirement_id) is not None
        for block in requirement_blocks
    )
    authorized_requirement_statuses = (
        RequirementStatus.SATISFIED,
        RequirementStatus.DERIVED,
        RequirementStatus.MISSING,
        RequirementStatus.UNKNOWN,
        RequirementStatus.REQUIRES_VERIFICATION,
    )
    requirement_status_ok = True
    for block in requirement_blocks:
        if not _block_schema_ok(block):
            requirement_status_ok = False
            continue
        requirement = resolved_requirements.get(block.requirement_id)
        if requirement is None:
            continue
        if requirement.status not in authorized_requirement_statuses:
            requirement_status_ok = False
        if requirement.status is RequirementStatus.DERIVED:
            if requirement.calculation_type is None or not any(
                _resolve_arithmetic(index, arithmetic_results, validation_result)
                is not None
                and arithmetic_results[index - 1].calculation_type
                is requirement.calculation_type
                for index in range(1, len(arithmetic_results) + 1)
            ):
                requirement_status_ok = False

    resolved_evidence = {
        block.evidence_id: _resolve_evidence(block.evidence_id, validation_result)
        for block in evidence_blocks
        if _block_schema_ok(block)
    }
    evidence_resolution_ok = all(
        _block_schema_ok(block)
        and resolved_evidence.get(block.evidence_id) is not None
        for block in evidence_blocks
    )
    evidence_status_ok = all(
        resolved_evidence.get(block.evidence_id) is None
        or resolved_evidence[block.evidence_id].status is EvidenceStatus.UNKNOWN
        for block in evidence_blocks
        if _block_schema_ok(block)
    )

    resolved_reviews = {
        block.review_id: _resolve_review(block.review_id, validation_result)
        for block in review_blocks
        if _block_schema_ok(block)
    }
    review_resolution_ok = all(
        _block_schema_ok(block)
        and resolved_reviews.get(block.review_id) is not None
        and resolved_reviews[block.review_id].mandatory is True
        for block in review_blocks
    )

    no_freeform_ok = kind_ok and all(
        set(vars(block).keys())
        == {name for name, _ in _PROVENANCE_BLOCK_FIELDS[type(block)]}
        for block in blocks
    )

    fact_ids = _dedup_first_occurrence(
        block.fact_id for block in fact_blocks if _block_schema_ok(block)
    )
    calculation_types = _dedup_first_occurrence(
        arithmetic_results[block.arithmetic_index - 1].calculation_type
        for block in arithmetic_blocks
        if _block_schema_ok(block)
        and 1 <= block.arithmetic_index <= len(arithmetic_results)
    )

    return [
        _provenance_item(_PROVENANCE_CHECK_IDS[0], schema_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[1], count_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[2], ids_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[3], order_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[4], nonempty_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[5], kind_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[6], block_schema_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[7], static_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[8], fact_resolution_ok, fact_ids),
        _provenance_item(_PROVENANCE_CHECK_IDS[9], fact_permission_ok, fact_ids),
        _provenance_item(
            _PROVENANCE_CHECK_IDS[10],
            arithmetic_ok,
            related_calculation_types=calculation_types,
        ),
        _provenance_item(_PROVENANCE_CHECK_IDS[11], deadline_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[12], hearing_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[13], requirement_resolution_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[14], requirement_status_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[15], evidence_resolution_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[16], evidence_status_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[17], review_resolution_ok),
        _provenance_item(_PROVENANCE_CHECK_IDS[18], no_freeform_ok),
    ]


def _render_requirement(requirement):
    templates = {
        RequirementStatus.SATISFIED: "Requirement status — satisfied: ",
        RequirementStatus.DERIVED: (
            "Requirement status — derived from approved deterministic arithmetic: "
        ),
        RequirementStatus.MISSING: (
            "Open item — missing from a successful extraction: "
        ),
        RequirementStatus.UNKNOWN: "Open item — status not established: ",
        RequirementStatus.REQUIRES_VERIFICATION: "Verification required: ",
    }
    return templates[requirement.status] + requirement.requirement_text


def _render_evidence(item):
    return (
        "Evidence check required; availability, possession, preparation, "
        "compilation, enclosure, submission and verification are not "
        "established: "
        + item.requirement_text
    )


def _render_review(item):
    return (
        "Mandatory " + item.level.value + " review: " + item.reason
    )


def _render_provenance_block(
    block,
    extraction_result,
    arithmetic_results,
    validation_result,
    deadline_result,
    preflight_result,
):
    """Closed §25.14-§25.20 Python renderer dispatcher."""
    if type(block) is StaticDraftBlock:
        return _STATIC_TEMPLATE_REGISTRY[block.template_id]
    if type(block) is FactDraftBlock:
        return _render_fact(
            _resolve_candidate_fact(block.fact_id, extraction_result)
        )
    if type(block) is ArithmeticDraftBlock:
        return _render_arithmetic(
            _resolve_arithmetic(
                block.arithmetic_index,
                arithmetic_results,
                validation_result,
            )
        )
    if type(block) is DeadlineDraftBlock:
        return _render_deadline(deadline_result, preflight_result)
    if type(block) is HearingDraftBlock:
        return _render_hearing(deadline_result)
    if type(block) is RequirementDraftBlock:
        return _render_requirement(
            _resolve_requirement(block.requirement_id, validation_result)
        )
    if type(block) is EvidenceDraftBlock:
        return _render_evidence(
            _resolve_evidence(block.evidence_id, validation_result)
        )
    if type(block) is ReviewDraftBlock:
        return _render_review(
            _resolve_review(block.review_id, validation_result)
        )
    return None


def _post_validate_and_render_provenance(
    extraction_result,
    preflight_result,
    arithmetic_results,
    validation_result,
    deadline_result,
    drafting_profile,
    candidate_sections,
):
    """Run the exact §25 21-check gate and Python-only rendering."""
    checks = _run_provenance_pre_render_validation(
        candidate_sections,
        drafting_profile,
        extraction_result,
        arithmetic_results,
        validation_result,
        deadline_result,
    )
    unresolved, evidence, reviews = _copy_result_metadata(validation_result)
    if any(check.status is ValidationStatus.FAIL for check in checks):
        checks.extend(
            [
                _provenance_item(
                    _PROVENANCE_CHECK_IDS[19],
                    False,
                    fail_message=_PRE_RENDER_COMPLETENESS_FAIL,
                ),
                _provenance_item(
                    _PROVENANCE_CHECK_IDS[20],
                    False,
                    fail_message=_PRE_RENDER_PYTHON_OWNED_FAIL,
                ),
            ]
        )
        post_validation = DraftPostValidationResult(
            overall_status=ValidationStatus.FAIL,
            checks=checks,
        )
        return SpecialistDraftResult(
            status=DraftGenerationStatus.FAILED,
            draft_eligibility=validation_result.draft_eligibility,
            sections=[],
            unresolved_requirements=unresolved,
            evidence_checklist=evidence,
            review_requirements=reviews,
            post_validation=post_validation,
            failure_code=DraftFailureCode.POST_VALIDATION_FAILED,
            error_message=_ERROR_POST_VALIDATION,
        )

    rendered_sections = []
    rendering_complete = True
    python_owned = True
    for candidate, profile_section in zip(
        candidate_sections, drafting_profile.sections
    ):
        fragments = []
        for block in candidate.blocks:
            try:
                fragment = _render_provenance_block(
                    block,
                    extraction_result,
                    arithmetic_results,
                    validation_result,
                    deadline_result,
                    preflight_result,
                )
            except Exception:
                fragment = None
            if not isinstance(fragment, str):
                rendering_complete = False
                python_owned = False
                continue
            fragments.append(fragment)
        if len(fragments) != len(candidate.blocks):
            rendering_complete = False
        rendered_text = "\n\n".join(fragments)
        rendered_sections.append(
            DraftSection(
                section_id=profile_section.section_id,
                title=profile_section.title,
                rendered_text=rendered_text,
            )
        )

    if len(rendered_sections) != len(candidate_sections):
        rendering_complete = False
    checks.extend(
        [
            _provenance_item(
                _PROVENANCE_CHECK_IDS[19], rendering_complete
            ),
            _provenance_item(_PROVENANCE_CHECK_IDS[20], python_owned),
        ]
    )
    overall = (
        ValidationStatus.PASS
        if all(check.status is ValidationStatus.PASS for check in checks)
        else ValidationStatus.FAIL
    )
    post_validation = DraftPostValidationResult(
        overall_status=overall,
        checks=checks,
    )
    if overall is ValidationStatus.FAIL:
        return SpecialistDraftResult(
            status=DraftGenerationStatus.FAILED,
            draft_eligibility=validation_result.draft_eligibility,
            sections=[],
            unresolved_requirements=unresolved,
            evidence_checklist=evidence,
            review_requirements=reviews,
            post_validation=post_validation,
            failure_code=DraftFailureCode.POST_VALIDATION_FAILED,
            error_message=_ERROR_POST_VALIDATION,
        )
    return SpecialistDraftResult(
        status=DraftGenerationStatus.SUCCESS,
        draft_eligibility=validation_result.draft_eligibility,
        sections=rendered_sections,
        unresolved_requirements=unresolved,
        evidence_checklist=evidence,
        review_requirements=reviews,
        post_validation=post_validation,
        failure_code=None,
        error_message=None,
    )


def generate_specialist_draft(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    validation_result: ValidationEngineResult,
    deadline_result: Optional[DeadlineResult] = None,
) -> SpecialistDraftResult:
    """Public Step-9E API: one typed drafting call and Python rendering.

    Pre-call failure precedence is deterministic (§22.3):
    1. validation_result is None → VALIDATION_REQUIRED (§22.2);
    2. classification/support/eligibility prohibits drafting or any check
       is FAIL → DRAFT_BLOCKED (§22.4);
    3. workflow/profile/prompt availability inconsistency →
       WORKFLOW_UNAVAILABLE (§22.5);
    4. otherwise call modules.llm_client.call_gemini exactly once, parse the
       provenance-v1 typed response, validate 21 checks, and render through
       the closed Python dispatcher (§25).
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

    prompt = _build_provenance_prompt(
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

    candidate_sections = _parse_provenance_response(
        response_trimmed, drafting_profile.sections
    )
    if candidate_sections is None:
        return _specialist_result(
            validation_result,
            DraftGenerationStatus.FAILED,
            DraftFailureCode.MALFORMED_RESPONSE,
            _ERROR_MALFORMED,
        )

    return _post_validate_and_render_provenance(
        extraction_result,
        preflight_result,
        arithmetic_results,
        validation_result,
        deadline_result,
        drafting_profile,
        candidate_sections,
    )
