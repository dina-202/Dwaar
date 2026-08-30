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

Step-9.4 surface (§23, authoritative):

- deterministic post-draft validation over the interim sections — the
  exact fourteen §23.3 checks in fixed order, PASS/FAIL only;
- the closed token syntax / resolution / permission / raw-literal /
  evidence / external-citation catalogs (§23.7–§23.37);
- Python-owned token resolution and single-pass rendering
  (§23.39–§23.43);
- the final SpecialistDraftResult transition — SUCCESS with rendered
  sections and a PASS DraftPostValidationResult, or FAILED with
  POST_VALIDATION_FAILED and no usable sections (§23.44–§23.45).

Step 9.4 adds ZERO new LLM calls (§23.49). Application integration
remains prohibited (§22.29, §21.30, §23.51).

All module-level names except generate_specialist_draft are
underscore-private (§21.27). Private helper names are implementation-local
and are NOT external machine contracts.
"""

import json
import re
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
    DraftPostValidationResult,
    DraftSection,
    FactExtractionResult,
    FactStatus,
    HearingStatus,
    NoticeClassification,
    PreflightResult,
    ProceedingType,
    RequirementStatus,
    SpecialistDraftResult,
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


# --- Phase 2 Step 9.4: deterministic post-validation + rendering (§23) ---------

# §23.3: the exact fourteen check IDs, in the exact emission order.
_CHECK_SCHEMA = "draft.response.schema"
_CHECK_COUNT = "draft.sections.count"
_CHECK_IDS = "draft.sections.ids"
_CHECK_ORDER = "draft.sections.order"
_CHECK_NONEMPTY = "draft.sections.nonempty"
_CHECK_TOKENS_SYNTAX = "draft.tokens.syntax"
_CHECK_FACT_RESOLUTION = "draft.tokens.fact_resolution"
_CHECK_FACT_PERMISSION = "draft.tokens.fact_permission"
_CHECK_ARITH_RESOLUTION = "draft.tokens.arithmetic_resolution"
_CHECK_DEADLINE_RESOLUTION = "draft.tokens.deadline_resolution"
_CHECK_HEARING_RESOLUTION = "draft.tokens.hearing_resolution"
_CHECK_RAW_FACT_LITERAL = "draft.prose.raw_fact_literal"
_CHECK_EVIDENCE = "draft.prose.evidence_presence_language"
_CHECK_CITATION = "draft.prose.external_citation_surface"

_POST_VALIDATION_CHECK_IDS = (
    _CHECK_SCHEMA,
    _CHECK_COUNT,
    _CHECK_IDS,
    _CHECK_ORDER,
    _CHECK_NONEMPTY,
    _CHECK_TOKENS_SYNTAX,
    _CHECK_FACT_RESOLUTION,
    _CHECK_FACT_PERMISSION,
    _CHECK_ARITH_RESOLUTION,
    _CHECK_DEADLINE_RESOLUTION,
    _CHECK_HEARING_RESOLUTION,
    _CHECK_RAW_FACT_LITERAL,
    _CHECK_EVIDENCE,
    _CHECK_CITATION,
)

# §23.5: the exact twenty-eight PASS/FAIL messages, keyed by check ID.
_POST_VALIDATION_MESSAGES = {
    _CHECK_SCHEMA: (
        "Draft response schema is structurally valid.",
        "Draft response schema is not structurally valid.",
    ),
    _CHECK_COUNT: (
        "Draft section count matches the drafting profile.",
        "Draft section count does not match the drafting profile.",
    ),
    _CHECK_IDS: (
        "Draft section IDs match the drafting profile.",
        "Draft section IDs do not match the drafting profile.",
    ),
    _CHECK_ORDER: (
        "Draft section order matches the drafting profile.",
        "Draft section order does not match the drafting profile.",
    ),
    _CHECK_NONEMPTY: (
        "Every draft section contains non-empty template text.",
        "One or more draft sections contain empty template text.",
    ),
    _CHECK_TOKENS_SYNTAX: (
        "Draft reference-token syntax is valid.",
        "Draft contains malformed or unsupported reference-token syntax.",
    ),
    _CHECK_FACT_RESOLUTION: (
        "All FACT tokens resolve to exactly one eligible fact.",
        "One or more FACT tokens do not resolve to exactly one eligible fact.",
    ),
    _CHECK_FACT_PERMISSION: (
        "All resolved FACT tokens satisfy draft-permission and fact-status invariants.",
        "One or more resolved FACT tokens violate draft-permission or fact-status invariants.",
    ),
    _CHECK_ARITH_RESOLUTION: (
        "All ARITH tokens resolve to approved deterministic arithmetic results.",
        "One or more ARITH tokens do not resolve to approved deterministic arithmetic results.",
    ),
    _CHECK_DEADLINE_RESOLUTION: (
        "All DEADLINE tokens resolve to the supplied deterministic deadline result.",
        "One or more DEADLINE tokens cannot resolve to the supplied deterministic deadline result.",
    ),
    _CHECK_HEARING_RESOLUTION: (
        "All HEARING tokens resolve to supplied deterministic hearing information.",
        "One or more HEARING tokens cannot resolve to supplied deterministic hearing information.",
    ),
    _CHECK_RAW_FACT_LITERAL: (
        "Draft template contains no prohibited raw case-specific factual literal.",
        "Draft template contains a prohibited raw case-specific factual literal outside authorized tokens.",
    ),
    _CHECK_EVIDENCE: (
        "Draft template contains no prohibited evidence-presence language.",
        "Draft template contains prohibited evidence-presence language.",
    ),
    _CHECK_CITATION: (
        "Draft template contains no prohibited external-citation surface.",
        "Draft template contains a prohibited external-citation surface.",
    ),
}

# §23.11: closed single-bracket lookalike detector (malformed-reference).
_LOOKALIKE_RE = re.compile(
    r"(?<!\[)\[(?:FACT:[^\[\]\r\n]*|ARITH:[^\[\]\r\n]*|"
    r"DEADLINE(?::[^\[\]\r\n]*)?|HEARING(?::[^\[\]\r\n]*)?)\](?!\])",
    re.IGNORECASE,
)

# §23.11: boundary-safe occurrence regexes (complete valid tokens only).
_FACT_OCCURRENCE_RE = re.compile(
    r"(?<!\[)\[\[FACT:([A-Za-z0-9][A-Za-z0-9._-]*)\]\](?!\])"
)
_ARITH_OCCURRENCE_RE = re.compile(
    r"(?<!\[)\[\[ARITH:([1-9][0-9]*)\]\](?!\])"
)
_DEADLINE_OCCURRENCE_RE = re.compile(r"(?<!\[)\[\[DEADLINE\]\](?!\])")
_HEARING_OCCURRENCE_RE = re.compile(r"(?<!\[)\[\[HEARING\]\](?!\])")

# §23.43: single-pass replacement — one complete valid token occurrence.
_COMPLETE_TOKEN_RE = re.compile(
    r"(?<!\[)(\[\[(?:FACT:[A-Za-z0-9][A-Za-z0-9._-]*|"
    r"ARITH:[1-9][0-9]*|DEADLINE|HEARING)\]\])(?!\])"
)

# §23.22: GSTIN-like literal.
_GSTIN_RE = re.compile(
    r"(?<![A-Z0-9])[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z](?![A-Z0-9])",
    re.IGNORECASE,
)

# §23.23: rupee / currency amount (two patterns).
_RUPEE_RE_A = re.compile(r"₹\s*[0-9][0-9,]*(?:\.[0-9]+)?")
_RUPEE_RE_B = re.compile(
    r"\b(?:INR|RS\.?|RUPEES?)\s*[:\-]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\b",
    re.IGNORECASE,
)

# §23.24: percentage.
_PERCENT_RE = re.compile(r"(?<![A-Z0-9.])[0-9]+(?:\.[0-9]+)?\s*%(?![A-Z0-9])")

# §23.25: numeric date (day-first, same separator).
_NUMERIC_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|[12][0-9]|3[01])([./-])(?:0?[1-9]|1[0-2])\1(?:19|20)[0-9]{2}\b"
)

# §23.26: ISO date.
_ISO_DATE_RE = re.compile(
    r"\b(?:19|20)[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])\b"
)

# §23.27: textual date (day-first).
_TEXTUAL_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|[12][0-9]|3[01])\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?:19|20)[0-9]{2}\b",
    re.IGNORECASE,
)

# §23.28: labelled RFN / DIN.
_RFN_DIN_RE = re.compile(
    r"\b(?:RFN|DIN)\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9/-]{5,}\b",
    re.IGNORECASE,
)

# §23.31: closed evidence-presence patterns.
_EVIDENCE_PATTERNS = (
    re.compile(r"\battached\b", re.IGNORECASE),
    re.compile(r"\benclosed\b", re.IGNORECASE),
    re.compile(r"\bannexed\b", re.IGNORECASE),
    re.compile(r"\bsubmitted\s+herewith\b", re.IGNORECASE),
    re.compile(r"\bwe\s+have\s+enclosed\b", re.IGNORECASE),
    re.compile(r"\bwe\s+attach\b", re.IGNORECASE),
)

# §23.32: URLs.
_URL_HTTP_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_URL_WWW_RE = re.compile(r"\bwww\.[^\s<>\"']+", re.IGNORECASE)

# §23.33: case-name style (case-sensitive).
_CASE_NAME_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.,'() -]{1,80}\s+(?:v\.|vs\.|versus)\s+"
    r"[A-Z][A-Za-z0-9&.,'() -]{1,80}\b"
)

# §23.34: reporter styles (case-insensitive).
_REPORTER_PATTERNS = (
    re.compile(r"\bAIR\s+(?:19|20)[0-9]{2}\s+[A-Z]{2,10}\s+[0-9]+\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)[0-9]{2}\s*\([0-9]+\)\s*(?:SCC|GSTL|ELT|STR)\s+[0-9]+\b", re.IGNORECASE),
    re.compile(r"\((?:19|20)[0-9]{2}\)\s*[0-9]+\s*(?:SCC|GSTL|ELT|STR)\s+[0-9]+\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)[0-9]{2}\s+(?:INSC|INHC)\s+[0-9]+\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)[0-9]{2}\s+SCC\s+OnLine\s+[A-Za-z]+\s+[0-9]+\b", re.IGNORECASE),
)

# §23.35: numeric footnote.
_NUMERIC_FOOTNOTE_RE = re.compile(r"(?<!\[)\[[0-9]{1,3}\](?!\])")


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


def _safe_template_texts(sections):
    """§23.6: string template_text of schema-compatible sections only."""
    return [
        section.template_text
        for section in sections
        if isinstance(section, DraftSection)
        and isinstance(section.template_text, str)
    ]


def _collect_tokens(texts):
    """§23.12: token references in section order then left-to-right
    occurrence order. Returns (fact_ids, arith_ns, deadline_seen,
    hearing_seen)."""
    fact_ids = []
    arith_ns = []
    deadline_seen = False
    hearing_seen = False
    for text in texts:
        for match in _FACT_OCCURRENCE_RE.finditer(text):
            fact_ids.append(match.group(1))
        for match in _ARITH_OCCURRENCE_RE.finditer(text):
            arith_ns.append(int(match.group(1)))
        if _DEADLINE_OCCURRENCE_RE.search(text):
            deadline_seen = True
        if _HEARING_OCCURRENCE_RE.search(text):
            hearing_seen = True
    return fact_ids, arith_ns, deadline_seen, hearing_seen


def _token_syntax_ok(texts):
    """§23.11 A/B algorithm: remove complete valid token occurrences, then
    FAIL on any remaining [[/]] or a single-bracket lookalike."""
    for text in texts:
        remaining = _COMPLETE_TOKEN_RE.sub("", text)
        if "[[" in remaining or "]]" in remaining:
            return False
        if _LOOKALIKE_RE.search(remaining):
            return False
    return True


def _resolve_fact(fact_id, extraction_result):
    """§23.13: exactly one eligible fact (YES or CONDITIONAL) with the
    exact case-sensitive fact_id."""
    matches = [
        fact
        for fact in extraction_result.facts
        if fact.fact_id == fact_id
        and fact.allowed_in_draft
        in (DraftPermission.YES, DraftPermission.CONDITIONAL)
    ]
    return matches[0] if len(matches) == 1 else None


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


def _render_template(text, fact_map, arith_map, deadline_result, preflight):
    """§23.43: single-pass left-to-right token replacement."""

    def replace(match):
        token = match.group(1)
        if token.startswith("[[FACT:"):
            return _render_fact(fact_map[token[7:-2]])
        if token.startswith("[[ARITH:"):
            return _render_arithmetic(arith_map[int(token[8:-2])])
        if token == "[[DEADLINE]]":
            return _render_deadline(deadline_result, preflight)
        if token == "[[HEARING]]":
            return _render_hearing(deadline_result)
        return match.group(0)

    return _COMPLETE_TOKEN_RE.sub(replace, text)


def _run_post_validation(
    sections,
    drafting_profile,
    extraction_result,
    arithmetic_results,
    validation_result,
    preflight_result,
    deadline_result,
):
    """§23.1–§23.38: emit exactly fourteen ValidationItems in fixed order."""
    profile_ids = [spec.section_id for spec in drafting_profile.sections]

    texts = _safe_template_texts(sections)
    fact_ids_in_order, arith_ns_in_order, deadline_seen, hearing_seen = (
        _collect_tokens(texts)
    )

    # --- checks 1–5: structural (§23.6) ---
    schema_ok = all(
        isinstance(section, DraftSection)
        and isinstance(section.section_id, str)
        and isinstance(section.title, str)
        and isinstance(section.template_text, str)
        and section.rendered_text == ""
        for section in sections
    )
    count_ok = len(sections) == len(profile_ids)
    returned_ids = [
        section.section_id if isinstance(section, DraftSection) else None
        for section in sections
    ]
    ids_ok = returned_ids == profile_ids
    order_ok = returned_ids == profile_ids
    nonempty_ok = all(
        isinstance(section, DraftSection)
        and isinstance(section.template_text, str)
        and section.template_text.strip() != ""
        for section in sections
    )

    # --- check 6: token syntax (§23.11) ---
    syntax_ok = _token_syntax_ok(texts)

    # --- checks 7–8: FACT resolution / permission (§23.13–§23.14) ---
    resolved_facts = {}
    fact_resolution_ok = True
    for fact_id in fact_ids_in_order:
        fact = _resolve_fact(fact_id, extraction_result)
        if fact is None:
            fact_resolution_ok = False
        else:
            resolved_facts[fact_id] = fact

    fact_permission_ok = True
    for fact_id in fact_ids_in_order:
        fact = resolved_facts.get(fact_id)
        if fact is None:
            continue
        permitted = (
            fact.status is FactStatus.CONFIRMED
            and fact.allowed_in_draft is DraftPermission.YES
        ) or (
            fact.status is FactStatus.ALLEGED
            and fact.allowed_in_draft is DraftPermission.CONDITIONAL
        )
        if not permitted:
            fact_permission_ok = False

    # --- check 9: ARITH resolution (§23.16) ---
    arith_resolution_ok = True
    for n in arith_ns_in_order:
        if _resolve_arithmetic(n, arithmetic_results, validation_result) is None:
            arith_resolution_ok = False

    # --- checks 10–11: DEADLINE / HEARING resolution (§23.18–§23.19) ---
    deadline_resolution_ok = True
    if deadline_seen and deadline_result is None:
        deadline_resolution_ok = False

    hearing_resolution_ok = True
    if hearing_seen and (
        deadline_result is None
        or deadline_result.hearing_date is None
        or deadline_result.hearing_status
        not in (
            HearingStatus.UPCOMING,
            HearingStatus.TODAY,
            HearingStatus.PASSED,
        )
    ):
        hearing_resolution_ok = False

    # --- check 12: raw fact literal (§23.20–§23.30) ---
    raw_literal_ok = True
    for text in texts:
        if (
            _GSTIN_RE.search(text)
            or _RUPEE_RE_A.search(text)
            or _RUPEE_RE_B.search(text)
            or _PERCENT_RE.search(text)
            or _NUMERIC_DATE_RE.search(text)
            or _ISO_DATE_RE.search(text)
            or _TEXTUAL_DATE_RE.search(text)
            or _RFN_DIN_RE.search(text)
        ):
            raw_literal_ok = False
            break

    raw_literal_fact_ids = []
    for fact in extraction_result.facts:
        if fact.allowed_in_draft not in (
            DraftPermission.YES,
            DraftPermission.CONDITIONAL,
        ):
            continue
        if fact.source_text is None:
            continue
        candidate = fact.source_text.strip()
        if len(candidate) < 24:
            continue
        for text in texts:
            if candidate in text:
                raw_literal_ok = False
                raw_literal_fact_ids.append(fact.fact_id)
                break

    # --- check 13: evidence-presence language (§23.31) ---
    evidence_ok = True
    for text in texts:
        if any(pattern.search(text) for pattern in _EVIDENCE_PATTERNS):
            evidence_ok = False
            break

    # --- check 14: external citation surface (§23.32–§23.35) ---
    citation_ok = True
    for text in texts:
        if (
            _URL_HTTP_RE.search(text)
            or _URL_WWW_RE.search(text)
            or _CASE_NAME_RE.search(text)
            or _NUMERIC_FOOTNOTE_RE.search(text)
            or any(pattern.search(text) for pattern in _REPORTER_PATTERNS)
        ):
            citation_ok = False
            break

    # --- related-ID metadata (§23.15, §23.17, §23.30, §23.46) ---
    fact_related_ids = _dedup_first_occurrence(fact_ids_in_order)
    arith_related_types = _dedup_first_occurrence(
        arithmetic_results[n - 1].calculation_type
        for n in arith_ns_in_order
        if 1 <= n <= len(arithmetic_results)
    )

    def item(check_id, ok, fact_ids=(), calc_types=()):
        pass_msg, fail_msg = _POST_VALIDATION_MESSAGES[check_id]
        return ValidationItem(
            check_id=check_id,
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            message=pass_msg if ok else fail_msg,
            related_fact_ids=list(fact_ids),
            related_calculation_types=list(calc_types),
        )

    checks = [
        item(_CHECK_SCHEMA, schema_ok),
        item(_CHECK_COUNT, count_ok),
        item(_CHECK_IDS, ids_ok),
        item(_CHECK_ORDER, order_ok),
        item(_CHECK_NONEMPTY, nonempty_ok),
        item(_CHECK_TOKENS_SYNTAX, syntax_ok),
        item(_CHECK_FACT_RESOLUTION, fact_resolution_ok, fact_related_ids),
        item(_CHECK_FACT_PERMISSION, fact_permission_ok, fact_related_ids),
        item(_CHECK_ARITH_RESOLUTION, arith_resolution_ok, (), arith_related_types),
        item(_CHECK_DEADLINE_RESOLUTION, deadline_resolution_ok),
        item(_CHECK_HEARING_RESOLUTION, hearing_resolution_ok),
        item(_CHECK_RAW_FACT_LITERAL, raw_literal_ok, raw_literal_fact_ids),
        item(_CHECK_EVIDENCE, evidence_ok),
        item(_CHECK_CITATION, citation_ok),
    ]

    overall = (
        ValidationStatus.FAIL
        if any(check.status is ValidationStatus.FAIL for check in checks)
        else ValidationStatus.PASS
    )
    return DraftPostValidationResult(overall_status=overall, checks=checks)


def _render_sections(
    sections,
    extraction_result,
    arithmetic_results,
    validation_result,
    deadline_result,
    preflight_result,
):
    """§23.43–§23.45: fresh DraftSection objects with rendered_text set via
    single-pass replacement; template_text unchanged (§23.48)."""
    texts = _safe_template_texts(sections)
    fact_map = {}
    arith_map = {}
    for text in texts:
        for match in _FACT_OCCURRENCE_RE.finditer(text):
            fact = _resolve_fact(match.group(1), extraction_result)
            if fact is not None:
                fact_map[match.group(1)] = fact
        for match in _ARITH_OCCURRENCE_RE.finditer(text):
            result = _resolve_arithmetic(
                int(match.group(1)), arithmetic_results, validation_result
            )
            if result is not None:
                arith_map[int(match.group(1))] = result

    rendered = []
    for section in sections:
        rendered.append(
            DraftSection(
                section_id=section.section_id,
                title=section.title,
                template_text=section.template_text,
                rendered_text=_render_template(
                    section.template_text,
                    fact_map,
                    arith_map,
                    deadline_result,
                    preflight_result,
                ),
            )
        )
    return rendered


def _post_validate_and_render(
    extraction_result,
    preflight_result,
    arithmetic_results,
    validation_result,
    deadline_result,
    drafting_profile,
    sections,
):
    """§23.44–§23.45: run Step-9.4 post-validation, then either fail with
    POST_VALIDATION_FAILED (no usable sections) or render and succeed."""
    post_validation = _run_post_validation(
        sections,
        drafting_profile,
        extraction_result,
        arithmetic_results,
        validation_result,
        preflight_result,
        deadline_result,
    )
    unresolved, evidence, reviews = _copy_result_metadata(validation_result)
    if post_validation.overall_status is ValidationStatus.FAIL:
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
    rendered = _render_sections(
        sections,
        extraction_result,
        arithmetic_results,
        validation_result,
        deadline_result,
        preflight_result,
    )
    return SpecialistDraftResult(
        status=DraftGenerationStatus.SUCCESS,
        draft_eligibility=validation_result.draft_eligibility,
        sections=rendered,
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

    return _post_validate_and_render(
        extraction_result,
        preflight_result,
        arithmetic_results,
        validation_result,
        deadline_result,
        drafting_profile,
        sections,
    )
