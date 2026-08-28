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

# First integer in the response period text, e.g. "21 days", "THIRTY (30) DAYS".
_PERIOD_DAYS_PATTERN = re.compile(r"(\d{1,3})")

# First numeric dd-mm-yyyy style date (also dd/mm/yyyy, dd.mm.yyyy; 2- or
# 4-digit year). Prose dates are deliberately NOT interpreted.
_DATE_PATTERN = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


def _parse_period_days(response_period_text: Optional[str]) -> Optional[int]:
    """Deterministically extract the response period in days, or None."""
    if not response_period_text:
        return None
    match = _PERIOD_DAYS_PATTERN.search(response_period_text)
    if not match:
        return None
    days = int(match.group(1))
    if days <= 0:
        return None
    return days


def _is_service_based(response_period_text: Optional[str]) -> bool:
    """True when the response period text says it runs from date of service."""
    if not response_period_text:
        return False
    return "service" in response_period_text.lower()


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
            "Response period could not be determined from the notice text; "
            "deadline not calculated"
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
