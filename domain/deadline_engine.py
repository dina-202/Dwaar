"""Deterministic deadline engine for CA Notice AI (ARCHITECTURE_SPEC_v1.md §4.2).

Architecture Phase 2 — Step 2 artifact. Pure Python, deterministic.

- No LLM, no Gemini, no Streamlit, no network operations, no notice pipeline.
- Consumes the Phase 2 domain models from domain.models (no duplication).
- Implements exactly the spec's §4.2 rules: date arithmetic, day counts,
  deadline/hearing status, and explicit uncertainty when required inputs
  are missing. Never guesses — insufficient inputs yield UNKNOWN.
"""

import re
from datetime import date, timedelta
from typing import List, Optional

from domain.models import (
    DeadlineConfidence,
    DeadlineResult,
    DeadlineStatus,
    HearingStatus,
)

# Spec §3.1: DeadlineStatus.CRITICAL = "Within 7 days".
CRITICAL_WINDOW_DAYS = 7

# Numeric period must be syntactically tied to "day"/"days". This avoids
# treating unrelated identifiers such as "Section 61" or "ASMT-10" as the
# response period merely because they appear earlier in the same source span.
_PERIOD_DAYS_PATTERN = re.compile(
    r"\b(\d{1,3})\s+(?:calendar\s+)?days?\b",
    re.IGNORECASE,
)

_NUMBER_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_NUMBER_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_PERIOD_WORD_PATTERN = re.compile(
    r"\b("
    + "|".join(
        sorted(
            tuple(_NUMBER_UNITS) + tuple(_NUMBER_TENS),
            key=len,
            reverse=True,
        )
    )
    + r")(?:[-\s]+("
    + "|".join(sorted(_NUMBER_UNITS, key=len, reverse=True))
    + r"))?\s+(?:calendar\s+)?days?\b",
    re.IGNORECASE,
)

# First numeric dd-mm-yyyy style date (also dd/mm/yyyy, dd.mm.yyyy; 2- or
# 4-digit year). Prose dates are deliberately NOT interpreted.
_DATE_PATTERN = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


def _parse_period_days(response_period_text: Optional[str]) -> Optional[int]:
    """Deterministically extract an explicit calendar-day period, or None.

    The number must be attached to the word "day"/"days"; unrelated numbers
    such as section/form identifiers are ignored. Explicit English number
    words from one through ninety-nine are supported. Working/business-day
    periods deliberately remain unresolved until Dwaar has a verified
    working-day / holiday-calendar subsystem.
    """
    if not response_period_text:
        return None
    lowered = response_period_text.lower()
    if "working day" in lowered or "business day" in lowered:
        return None

    numeric_match = _PERIOD_DAYS_PATTERN.search(response_period_text)
    if numeric_match:
        days = int(numeric_match.group(1))
        return days if days > 0 else None

    word_match = _PERIOD_WORD_PATTERN.search(response_period_text)
    if not word_match:
        return None

    first = word_match.group(1).lower()
    second = word_match.group(2)
    if first in _NUMBER_UNITS:
        # Unit/teen words are complete numbers and cannot safely take a
        # second unit token ("fifteen two days" must not become 17).
        if second is not None:
            return None
        return _NUMBER_UNITS[first]

    days = _NUMBER_TENS[first]
    if second is not None:
        second_value = _NUMBER_UNITS.get(second.lower())
        if second_value is None or second_value >= 10:
            return None
        days += second_value
    return days


def _is_service_based(response_period_text: Optional[str]) -> bool:
    """True when the period is anchored to service / receipt.

    Receipt language is treated as service-based because substituting the
    notice issue date for an unknown receipt date would be unsafe.
    """
    if not response_period_text:
        return False
    lowered = response_period_text.lower()
    return any(
        token in lowered
        for token in ("service", "receipt", "received")
    )


def _parse_date_text(text: Optional[str]) -> Optional[date]:
    """Deterministically parse the first dd-mm-yyyy-style date, or None.

    Never interprets legal language or guesses: if no numeric date pattern
    is present (or the matched numbers are not a valid date), returns None.
    """
    if not text:
        return None
    match = _DATE_PATTERN.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def calculate_deadline(
    notice_date: Optional[date],
    service_date: Optional[date],
    response_period_text: Optional[str],
    hearing_date_text: Optional[str],
    today: date,
) -> DeadlineResult:
    """Compute the deadline analysis exactly per ARCHITECTURE_SPEC_v1.md §4.2.

    Deterministic only; never calls an LLM and never guesses:

    - Service date present -> deadline = service date + period, CONFIRMED.
    - Period text says "from date of service" but service date unavailable
      -> response_deadline = None, confidence = UNKNOWN (cannot calculate).
    - Otherwise (e.g. "from date of issue") with a notice date available ->
      deadline = notice date + period, ESTIMATED (assuming service =
      notice date), noted clearly.
    - Period undeterminable or no anchor date at all -> UNKNOWN.
    - days_remaining = None whenever the deadline is unknown.
    - Portal verification required = True whenever the deadline has passed
      or is unknown.
    """
    response_period_days = _parse_period_days(response_period_text)
    hearing_date = _parse_date_text(hearing_date_text)

    response_deadline: Optional[date]
    deadline_confidence: DeadlineConfidence
    notes: List[str] = []

    if response_period_days is None:
        response_deadline = None
        deadline_confidence = DeadlineConfidence.UNKNOWN
        notes.append(
            "Response period could not be safely determined from the notice "
            "text (including unsupported working-day periods); deadline not "
            "calculated"
        )
    elif service_date is not None:
        response_deadline = service_date + timedelta(days=response_period_days)
        deadline_confidence = DeadlineConfidence.CONFIRMED
    elif _is_service_based(response_period_text):
        response_deadline = None
        deadline_confidence = DeadlineConfidence.UNKNOWN
        notes.append(
            "Response period runs from date of service but service date is "
            "unavailable; deadline cannot be calculated"
        )
    elif notice_date is not None:
        response_deadline = notice_date + timedelta(days=response_period_days)
        deadline_confidence = DeadlineConfidence.ESTIMATED
        notes.append(
            "Service date absent; assuming service occurred on the notice "
            "date (estimated deadline)"
        )
    else:
        response_deadline = None
        deadline_confidence = DeadlineConfidence.UNKNOWN
        notes.append(
            "No date information available; deadline cannot be calculated"
        )

    if response_deadline is None:
        deadline_status = DeadlineStatus.UNKNOWN
        days_remaining = None
    else:
        days_remaining = (response_deadline - today).days
        if days_remaining < 0:
            deadline_status = DeadlineStatus.PASSED
        elif days_remaining <= CRITICAL_WINDOW_DAYS:
            deadline_status = DeadlineStatus.CRITICAL
        else:
            deadline_status = DeadlineStatus.UPCOMING

    if hearing_date is None:
        hearing_status = HearingStatus.NOT_SCHEDULED
    elif hearing_date > today:
        hearing_status = HearingStatus.UPCOMING
    elif hearing_date < today:
        hearing_status = HearingStatus.PASSED
    else:
        hearing_status = HearingStatus.TODAY

    portal_verification_required = deadline_status in (
        DeadlineStatus.PASSED,
        DeadlineStatus.UNKNOWN,
    )

    return DeadlineResult(
        notice_date=notice_date,
        service_date=service_date,
        response_period_days=response_period_days,
        response_deadline=response_deadline,
        deadline_confidence=deadline_confidence,
        deadline_status=deadline_status,
        days_remaining=days_remaining,
        hearing_date=hearing_date,
        hearing_status=hearing_status,
        portal_verification_required=portal_verification_required,
        notes=notes,
    )
