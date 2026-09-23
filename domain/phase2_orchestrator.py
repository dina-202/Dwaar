"""UI-independent Phase-2 orchestration (architecture §24).

The orchestrator coordinates the existing Phase-2 engines. It owns only
deterministic input mapping and result assembly: no PDF/UI dependency, no
provider call, no retry, and no legacy runtime fallback.
"""

from datetime import date as _date
import re as _re
from typing import List as _List, Optional as _Optional, Tuple as _Tuple

from domain.arithmetic_engine import run_arithmetic
from domain.deadline_engine import (
    _parse_date_text,
    calculate_deadline,
)
from domain.drafting_engine import (
    generate_specialist_draft,
)
from domain.fact_engine import (
    extract_facts_with_document_provenance,
    extract_facts_with_page_provenance,
    extract_facts_with_status,
)
from domain.models import (
    ArithmeticCalculationType as _ArithmeticCalculationType,
    ArithmeticOperand as _ArithmeticOperand,
    ArithmeticRequest as _ArithmeticRequest,
    ArithmeticResult as _ArithmeticResult,
    ArithmeticStatus as _ArithmeticStatus,
    DocumentPageText as _DocumentPageText,
    DraftPermission as _DraftPermission,
    ExtractedFact as _ExtractedFact,
    FactExtractionResult as _FactExtractionResult,
    FactExtractionStatus as _FactExtractionStatus,
    FactRole as _FactRole,
    FactStatus as _FactStatus,
    FactType as _FactType,
    NoticeClassification as _NoticeClassification,
    Phase2AnalysisResult as _Phase2AnalysisResult,
    ProceedingType as _ProceedingType,
    RequirementKind as _RequirementKind,
    SourceVerificationStatus as _SourceVerificationStatus,
    SupportLevel as _SupportLevel,
    TriageSummary as _TriageSummary,
)
from domain.preflight_engine import run_preflight
from domain.proceeding_classifier import classify_notice, classifier_failed
from domain.validation_engine import run_validation
from workflows.gst.validation_profiles import (
    get_validation_profile,
)


_ALLOWED_DEADLINE_STATUSES = (
    _FactStatus.CONFIRMED,
)

_AMOUNT_TOKEN_REGEX = (
    r"(?<![A-Za-z0-9])(-?)(?:₹|rs\.?|inr)?\s*"
    r"(?:\d{1,2}(?:,\d{2})*(?:,\d{3})(?:\.\d{1,2})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d+(?:\.\d{1,2})?)(?![A-Za-z0-9])"
)
_AMOUNT_TOKEN_PATTERN = _re.compile(_AMOUNT_TOKEN_REGEX, _re.IGNORECASE)

_CALCULATION_OPERANDS = {
    _ArithmeticCalculationType.ITC_DIFFERENCE: (
        _FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        _FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
    ),
    _ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE: (
        _FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT,
        _FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT,
    ),
}

_CALCULATION_FORMULAS = {
    _ArithmeticCalculationType.ITC_DIFFERENCE: (
        "GSTR-3B ITC - GSTR-2B ITC"
    ),
    _ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE: (
        "GSTR-1 liability - GSTR-3B liability"
    ),
}

_NO_INPUT_MESSAGE = (
    "No usable notice text was available for Phase-2 analysis."
)
_FAILED_MESSAGE = (
    "Fact extraction failed, so specialist drafting is blocked."
)
_CLASSIFICATION_FAILED_MESSAGE = (
    "Notice classification could not be completed because the AI "
    "classification step did not return a usable result."
)
_UNKNOWN_MESSAGE = (
    "This notice could not be matched to an approved deep specialist workflow."
)
_TRIAGE_ONLY_MESSAGE = (
    "This notice is recognized for triage, but no approved deep specialist "
    "workflow is available."
)


def _deadline_candidates(
    facts: _List[_ExtractedFact],
    fact_type: _FactType,
) -> _List[_ExtractedFact]:
    return [
        fact
        for fact in facts
        if fact.fact_type is fact_type
        and fact.status in _ALLOWED_DEADLINE_STATUSES
        and fact.source_verification is _SourceVerificationStatus.VERIFIED
        and bool(fact.source_text)
    ]


def _deadline_role_candidates(
    facts: _List[_ExtractedFact],
    role: _FactRole,
) -> _List[_ExtractedFact]:
    """Verified confirmed document-detail facts for one deadline role."""
    return [
        fact
        for fact in facts
        if fact.fact_type is _FactType.DOCUMENT_DETAIL
        and fact.fact_role is role
        and fact.status is _FactStatus.CONFIRMED
        and fact.source_verification is _SourceVerificationStatus.VERIFIED
        and bool(fact.source_text)
    ]


def _build_deadline_inputs(
    facts: _List[_ExtractedFact],
) -> _Tuple[
    _Optional[_date],
    _Optional[_date],
    _Optional[str],
    _Optional[str],
]:
    """Map only unambiguous, verified document-native deadline inputs.

    Returns (notice_date, service_date, response_period_text,
    hearing_date_text). No statutory period is inferred here.
    """
    notice_candidates = _deadline_candidates(facts, _FactType.NOTICE_DATE)
    notice_date = (
        _parse_date_text(notice_candidates[0].source_text)
        if len(notice_candidates) == 1
        else None
    )

    service_candidates = _deadline_role_candidates(
        facts, _FactRole.NOTICE_SERVICE_DATE
    )
    service_date = (
        _parse_date_text(service_candidates[0].source_text)
        if len(service_candidates) == 1
        else None
    )

    period_candidates = _deadline_role_candidates(
        facts, _FactRole.RESPONSE_PERIOD
    )
    response_period_text = (
        period_candidates[0].source_text
        if len(period_candidates) == 1
        else None
    )

    hearing_candidates = _deadline_candidates(
        facts, _FactType.HEARING_DETAILS
    )
    hearing_date_text = (
        hearing_candidates[0].source_text
        if len(hearing_candidates) == 1
        else None
    )
    return (
        notice_date,
        service_date,
        response_period_text,
        hearing_date_text,
    )


def _operand_candidates(
    facts: _List[_ExtractedFact],
    role: _FactRole,
) -> _List[_ExtractedFact]:
    return [
        fact
        for fact in facts
        if fact.fact_type is _FactType.STATED_AMOUNT
        and fact.fact_role is role
        and fact.status is _FactStatus.CONFIRMED
        and fact.source_verification is _SourceVerificationStatus.VERIFIED
    ]


def _value_text(fact: _ExtractedFact) -> _Optional[str]:
    if not isinstance(fact.source_text, str):
        return None
    matches = list(_re.finditer(_AMOUNT_TOKEN_PATTERN, fact.source_text))
    if len(matches) != 1:
        return None
    return matches[0].group(0)


def _ordered_candidate_ids(
    left_candidates: _List[_ExtractedFact],
    right_candidates: _List[_ExtractedFact],
) -> _List[str]:
    ordered_ids: _List[str] = []
    seen = set()
    for fact in left_candidates + right_candidates:
        if fact.fact_id not in seen:
            seen.add(fact.fact_id)
            ordered_ids.append(fact.fact_id)
    return ordered_ids


def _insufficient_arithmetic_result(
    calculation_type: _ArithmeticCalculationType,
    left_candidates: _List[_ExtractedFact],
    right_candidates: _List[_ExtractedFact],
) -> _ArithmeticResult:
    return _ArithmeticResult(
        calculation_type=calculation_type,
        status=_ArithmeticStatus.INSUFFICIENT_DATA,
        source_fact_ids=_ordered_candidate_ids(
            left_candidates, right_candidates
        ),
        operand_values=[],
        result=None,
        formula=_CALCULATION_FORMULAS[calculation_type],
        currency="INR",
        allowed_in_draft=_DraftPermission.CONDITIONAL,
    )


def _build_arithmetic_results(
    classification: _NoticeClassification,
    extraction_result: _FactExtractionResult,
) -> _List[_ArithmeticResult]:
    if (
        classification.support_level is not _SupportLevel.DEEP_WORKFLOW
        or classification.proceeding_type is _ProceedingType.UNKNOWN
    ):
        return []

    profile = get_validation_profile(classification.proceeding_type)
    if profile is None:
        return []

    calculation_types = []
    seen = set()
    for requirement in profile.requirement_specs:
        calculation_type = requirement.calculation_type
        if (
            requirement.kind is _RequirementKind.DERIVED
            and calculation_type is not None
            and calculation_type in _CALCULATION_OPERANDS
            and calculation_type not in seen
        ):
            seen.add(calculation_type)
            calculation_types.append(calculation_type)

    facts = extraction_result.facts
    arithmetic_results: _List[_ArithmeticResult] = []
    for calculation_type in calculation_types:
        left_role, right_role = _CALCULATION_OPERANDS[calculation_type]
        left_candidates = _operand_candidates(facts, left_role)
        right_candidates = _operand_candidates(facts, right_role)

        left_value_text = (
            _value_text(left_candidates[0])
            if len(left_candidates) == 1
            else None
        )
        right_value_text = (
            _value_text(right_candidates[0])
            if len(right_candidates) == 1
            else None
        )

        if left_value_text is None or right_value_text is None:
            arithmetic_results.append(
                _insufficient_arithmetic_result(
                    calculation_type,
                    left_candidates,
                    right_candidates,
                )
            )
            continue

        request = _ArithmeticRequest(
            calculation_type=calculation_type,
            left_operand=_ArithmeticOperand(
                source_fact_id=left_candidates[0].fact_id,
                value_text=left_value_text,
            ),
            right_operand=_ArithmeticOperand(
                source_fact_id=right_candidates[0].fact_id,
                value_text=right_value_text,
            ),
        )
        arithmetic_results.append(run_arithmetic(request, facts))

    return arithmetic_results


def _build_triage_summary(
    classification: _NoticeClassification,
    extraction_result: _FactExtractionResult,
    preflight_result,
    deadline_result,
) -> _Optional[_TriageSummary]:
    if extraction_result.status is _FactExtractionStatus.NO_INPUT:
        message = _NO_INPUT_MESSAGE
    elif classifier_failed(classification):
        message = _CLASSIFICATION_FAILED_MESSAGE
    elif extraction_result.status is _FactExtractionStatus.FAILED:
        message = _FAILED_MESSAGE
    elif (
        classification.support_level is _SupportLevel.UNKNOWN
        or classification.proceeding_type is _ProceedingType.UNKNOWN
    ):
        message = _UNKNOWN_MESSAGE
    elif classification.support_level is _SupportLevel.TRIAGE_ONLY:
        message = _TRIAGE_ONLY_MESSAGE
    else:
        return None

    return _TriageSummary(
        proceeding_type=classification.proceeding_type,
        notice_form=classification.notice_form,
        support_level=classification.support_level,
        classification_confidence=classification.confidence,
        extraction_status=extraction_result.status,
        portal_verification_required=(
            preflight_result.portal_verification_required
        ),
        authority_verification_required=(
            preflight_result.authority_verification_required
        ),
        communication_identifier_status=(
            preflight_result.communication_identifier_status
        ),
        authority_details_status=preflight_result.authority_details_status,
        deadline_status=deadline_result.deadline_status,
        hearing_status=deadline_result.hearing_status,
        requested_document_fact_ids=(
            preflight_result.requested_document_fact_ids
        ),
        referenced_annexure_fact_ids=(
            preflight_result.referenced_annexure_fact_ids
        ),
        message=message,
    )


def _assemble_phase2_result(
    classification: _NoticeClassification,
    extraction_result: _FactExtractionResult,
    today: _date,
) -> _Phase2AnalysisResult:
    """Run deterministic downstream Phase-2 stages after fact extraction."""
    (
        notice_date,
        service_date,
        response_period_text,
        hearing_date_text,
    ) = _build_deadline_inputs(extraction_result.facts)
    deadline_result = calculate_deadline(
        notice_date=notice_date,
        service_date=service_date,
        response_period_text=response_period_text,
        hearing_date_text=hearing_date_text,
        today=today,
    )
    preflight_result = run_preflight(
        extraction_result,
        classification,
        deadline_result,
    )
    arithmetic_results = _build_arithmetic_results(
        classification,
        extraction_result,
    )
    validation_result = run_validation(
        classification,
        extraction_result,
        preflight_result,
        arithmetic_results,
        deadline_result,
    )
    draft_result = generate_specialist_draft(
        classification,
        extraction_result,
        preflight_result,
        arithmetic_results,
        validation_result,
        deadline_result,
    )
    triage_summary = _build_triage_summary(
        classification,
        extraction_result,
        preflight_result,
        deadline_result,
    )

    return _Phase2AnalysisResult(
        classification=classification,
        extraction_result=extraction_result,
        deadline_result=deadline_result,
        preflight_result=preflight_result,
        arithmetic_results=arithmetic_results,
        validation_result=validation_result,
        draft_result=draft_result,
        triage_summary=triage_summary,
    )


def run_phase2_analysis(
    raw_text: str,
    today: _date,
) -> _Phase2AnalysisResult:
    """Run the backward-compatible raw-text Phase-2 pipeline from §24."""
    classification = classify_notice(raw_text)
    extraction_result = extract_facts_with_status(raw_text, classification)
    return _assemble_phase2_result(
        classification,
        extraction_result,
        today,
    )


def run_phase2_analysis_from_pages(
    page_texts: _List[str],
    today: _date,
) -> _Phase2AnalysisResult:
    """Run Phase 2 with deterministic page-aware fact provenance.

    Classification and every downstream engine still receive the exact
    legacy flattened text representation. Only fact provenance gains page
    boundaries, so this path is additive rather than a classification or
    workflow semantics change.
    """
    if (
        not isinstance(page_texts, list)
        or any(not isinstance(page_text, str) for page_text in page_texts)
    ):
        raw_text = ""
        safe_pages: _List[str] = []
    else:
        safe_pages = page_texts
        raw_text = "".join(safe_pages)

    classification = classify_notice(raw_text)
    extraction_result = extract_facts_with_page_provenance(
        raw_text,
        classification,
        safe_pages,
    )
    return _assemble_phase2_result(
        classification,
        extraction_result,
        today,
    )



def run_phase2_analysis_from_document_pages(
    document_pages: _List[_DocumentPageText],
    today: _date,
) -> _Phase2AnalysisResult:
    """Run Phase 2 with page and extraction-channel trust metadata."""
    if (
        not isinstance(document_pages, list)
        or any(
            not isinstance(page, _DocumentPageText)
            or page.page_number != index
            for index, page in enumerate(document_pages, start=1)
        )
    ):
        safe_pages: _List[_DocumentPageText] = []
        raw_text = ""
    else:
        safe_pages = document_pages
        raw_text = "".join(page.text for page in safe_pages)

    classification = classify_notice(raw_text)
    extraction_result = extract_facts_with_document_provenance(
        raw_text,
        classification,
        safe_pages,
    )
    return _assemble_phase2_result(
        classification,
        extraction_result,
        today,
    )
