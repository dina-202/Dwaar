"""Deterministic preflight engine for CA Notice AI
(ARCHITECTURE_SPEC_v1_1 §18.3–§18.15, §18.26–§18.30).

Architecture Phase 2 — Step 7.2 artifact. Pure Python, deterministic.

Consumes the Step 6 FactExtractionResult, the validated
NoticeClassification, and an optional already-calculated DeadlineResult,
and produces exactly the §18.13 PreflightResult:

  - absence-based conclusions only when extraction is SUCCESS (§18.3);
  - communication identifier mapping from validated FactTypes only (§18.5);
  - authority details mapping from validated FactTypes only (§18.7);
  - portal / authority verification flags always True in Phase 2
    (§18.6, §18.8);
  - deterministic stated-due-date parsing for the §18.10 formats;
  - deadline comparison against deadline_result.response_deadline only
    (§18.11–§18.12);
  - pass-through fact ID indexing (§18.14).

Never calls an LLM, never calls the Deadline Engine, never mutates its
inputs, never decides legal competence or notice validity, and creates no
evidence-gap objects (§18.27). Standard library + domain.models only.
"""

import re
from datetime import date
from typing import List, Optional, Set

from domain.models import (
    AuthorityDetailsStatus,
    CommunicationIdentifierStatus,
    DeadlineConflictStatus,
    DeadlineResult,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactType,
    NoticeClassification,
    PreflightResult,
)

# --- §18.10 stated due date parsing -------------------------------------

# DD-MM-YYYY and DD/MM/YYYY — the Indian day-first convention. Dashes and
# slashes only; dots, month-first semantics and two-digit years are
# deliberately unsupported.
_DAY_FIRST_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)"
)

# YYYY-MM-DD — ISO order, dashes only.
_YEAR_FIRST_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"
)

# English month names and abbreviations for DD Month YYYY / DD Mon YYYY.
# Case-insensitive: the same English name printed in capitals is still the
# same name.
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_ABBREVIATIONS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONTH_ALTERNATION = "|".join(_MONTH_NAMES + _MONTH_ABBREVIATIONS)
_PROSE_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})\s+(" + _MONTH_ALTERNATION + r")\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)

_MONTH_NUMBERS = {
    name.lower(): number
    for number, name in enumerate(_MONTH_NAMES, start=1)
}
_MONTH_NUMBERS.update(
    {
        abbreviation.lower(): number
        for number, abbreviation in enumerate(
            _MONTH_ABBREVIATIONS, start=1
        )
    }
)

# §18.7 core authority fields.
_CORE_AUTHORITY_FACT_TYPES = (
    FactType.AUTHORITY_DESIGNATION,
    FactType.AUTHORITY_OFFICE,
)

# §18.7 all authority-related fields (core + supplementary).
_AUTHORITY_FACT_TYPES = _CORE_AUTHORITY_FACT_TYPES + (
    FactType.AUTHORITY_NAME,
    FactType.JURISDICTION_TEXT,
)


def _try_date(
    year_text: str, month_text: str, day_text: str
) -> Optional[date]:
    """Construct a date from digit strings, or None when not a real date.

    Uses datetime.date's own validation — no manual leap-year or
    month-length logic, no repair, no reinterpretation (§18.10).
    """
    try:
        return date(int(year_text), int(month_text), int(day_text))
    except ValueError:
        return None


def _valid_dates_in_text(source_text: str) -> Set[date]:
    """Every distinct supported §18.10 date found in source_text.

    Unsupported shapes (two-digit years, dots, relative phrases, ordinal
    suffixes, month-only dates) match no pattern and contribute nothing.
    A matched token that is not a real calendar date is discarded.
    """
    distinct: Set[date] = set()
    for match in _DAY_FIRST_DATE_PATTERN.finditer(source_text):
        parsed = _try_date(match.group(3), match.group(2), match.group(1))
        if parsed is not None:
            distinct.add(parsed)
    for match in _YEAR_FIRST_DATE_PATTERN.finditer(source_text):
        parsed = _try_date(match.group(1), match.group(2), match.group(3))
        if parsed is not None:
            distinct.add(parsed)
    for match in _PROSE_DATE_PATTERN.finditer(source_text):
        month_number = _MONTH_NUMBERS.get(match.group(2).lower())
        if month_number is None:  # cannot occur with the compiled pattern
            continue
        parsed = _try_date(match.group(3), str(month_number), match.group(1))
        if parsed is not None:
            distinct.add(parsed)
    return distinct


def _parse_stated_due_date(source_text: Optional[str]) -> Optional[date]:
    """Parse one due-date fact's source_text into a single date, or None.

    Returns the date only when EXACTLY ONE distinct supported date occurs
    in the text. Zero distinct dates (unsupported/unparseable) and
    multiple distinct dates (ambiguous) both return None — preflight
    never arbitrarily chooses one (§18.10).
    """
    if not source_text:
        return None
    distinct = _valid_dates_in_text(source_text)
    if len(distinct) == 1:
        return next(iter(distinct))
    return None


def run_preflight(
    extraction_result: FactExtractionResult,
    classification: NoticeClassification,
    deadline_result: Optional[DeadlineResult] = None,
) -> PreflightResult:
    """Derive the deterministic §18.13 PreflightResult from extracted facts.

    Behavior (§18.3–§18.15):

    - Absence-based conclusions (NEITHER_FOUND, MISSING) are derived only
      when extraction_result.status is SUCCESS. Positively extracted
      identifier/authority facts remain reportable under PARTIAL extraction;
      when no positive fact is available, PARTIAL / FAILED / NO_INPUT yield
      UNKNOWN (§18.3 pilot clarification).
    - Identifier and authority mappings inspect FactTypes only — never
      claim text (§18.5, §18.7).
    - portal_verification_required and authority_verification_required are
      always True in Phase 2 (§18.6, §18.8). PRESENT authority details do
      not establish competence.
    - STATED_DUE_DATE facts are parsed deterministically (§18.10);
      unresolved or ambiguous facts force CANNOT_COMPARE (§18.11).
    - deadline_result is consumed read-only: only response_deadline is
      compared (§18.12). Nothing is recalculated or replaced.
    - classification is required by the §18.4 signature for integration
      consistency and is never consulted: the same deterministic mapping
      serves DEEP_WORKFLOW, TRIAGE_ONLY and UNKNOWN. Nothing is mutated.
    - HEARING_DETAILS / REQUESTED_DOCUMENT / REFERENCED_ANNEXURE fact IDs
      are indexed in accepted order (§18.14). No evidence gaps are
      created; annexure-upload comparison belongs to later steps.
    """
    status = extraction_result.status
    extraction_succeeded = status is FactExtractionStatus.SUCCESS

    # Non-ExtractedFact entries are ignored rather than crashing: inputs
    # are typed domain models, and an invalid entry simply matches no
    # FactType below.
    accepted_facts = [
        fact
        for fact in extraction_result.facts
        if isinstance(fact, ExtractedFact)
    ]

    has_rfn = any(
        fact.fact_type is FactType.RFN for fact in accepted_facts
    )
    has_din = any(
        fact.fact_type is FactType.DIN for fact in accepted_facts
    )
    if has_rfn and has_din:
        communication_identifier_status = (
            CommunicationIdentifierStatus.BOTH_PRESENT
        )
    elif has_rfn:
        communication_identifier_status = (
            CommunicationIdentifierStatus.RFN_PRESENT
        )
    elif has_din:
        communication_identifier_status = (
            CommunicationIdentifierStatus.DIN_PRESENT
        )
    elif extraction_succeeded:
        # Absence is safe only after a complete successful extraction.
        communication_identifier_status = (
            CommunicationIdentifierStatus.NEITHER_FOUND
        )
    else:
        communication_identifier_status = CommunicationIdentifierStatus.UNKNOWN

    has_designation = any(
        fact.fact_type is FactType.AUTHORITY_DESIGNATION
        for fact in accepted_facts
    )
    has_office = any(
        fact.fact_type is FactType.AUTHORITY_OFFICE
        for fact in accepted_facts
    )
    has_any_authority = any(
        fact.fact_type in _AUTHORITY_FACT_TYPES
        for fact in accepted_facts
    )
    if has_designation and has_office:
        authority_details_status = AuthorityDetailsStatus.PRESENT
    elif has_any_authority:
        authority_details_status = AuthorityDetailsStatus.PARTIAL
    elif extraction_succeeded:
        authority_details_status = AuthorityDetailsStatus.MISSING
    else:
        authority_details_status = AuthorityDetailsStatus.UNKNOWN

    stated_due_date_fact_ids: List[str] = []
    parsed_stated_due_dates: List[date] = []
    unparsed_stated_due_date_fact_ids: List[str] = []
    hearing_fact_ids: List[str] = []
    requested_document_fact_ids: List[str] = []
    referenced_annexure_fact_ids: List[str] = []

    for fact in accepted_facts:
        fact_type = fact.fact_type
        if fact_type is FactType.STATED_DUE_DATE:
            stated_due_date_fact_ids.append(fact.fact_id)
            parsed = _parse_stated_due_date(fact.source_text)
            if parsed is None:
                unparsed_stated_due_date_fact_ids.append(fact.fact_id)
            else:
                parsed_stated_due_dates.append(parsed)
        elif fact_type is FactType.HEARING_DETAILS:
            hearing_fact_ids.append(fact.fact_id)
        elif fact_type is FactType.REQUESTED_DOCUMENT:
            requested_document_fact_ids.append(fact.fact_id)
        elif fact_type is FactType.REFERENCED_ANNEXURE:
            referenced_annexure_fact_ids.append(fact.fact_id)

    if unparsed_stated_due_date_fact_ids:
        # §18.11: any unresolved due-date fact makes comparison unsafe,
        # even when another fact parsed successfully.
        deadline_conflict_status = DeadlineConflictStatus.CANNOT_COMPARE
    elif (
        len(set(parsed_stated_due_dates)) == 1
        and deadline_result is not None
        and deadline_result.response_deadline is not None
    ):
        # Exactly one unique safely parsed stated due date (§18.12).
        unique_stated_date = parsed_stated_due_dates[0]
        if unique_stated_date == deadline_result.response_deadline:
            deadline_conflict_status = DeadlineConflictStatus.MATCH
        else:
            deadline_conflict_status = DeadlineConflictStatus.CONFLICT
    else:
        # Multiple distinct stated dates, no stated date at all, or no
        # calculated deadline: nothing can be compared (§18.11–§18.12).
        deadline_conflict_status = DeadlineConflictStatus.CANNOT_COMPARE

    return PreflightResult(
        fact_extraction_status=status,
        communication_identifier_status=communication_identifier_status,
        portal_verification_required=True,
        authority_details_status=authority_details_status,
        authority_verification_required=True,
        stated_due_date_fact_ids=stated_due_date_fact_ids,
        parsed_stated_due_dates=parsed_stated_due_dates,
        unparsed_stated_due_date_fact_ids=unparsed_stated_due_date_fact_ids,
        deadline_conflict_status=deadline_conflict_status,
        hearing_fact_ids=hearing_fact_ids,
        requested_document_fact_ids=requested_document_fact_ids,
        referenced_annexure_fact_ids=referenced_annexure_fact_ids,
    )
