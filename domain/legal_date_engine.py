"""Deterministic source-proven legal applicability date extraction."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Optional, Tuple

from domain.legal_date_models import (
    LegalDateAnchor,
    LegalDateBasis,
    LegalDateContext,
)
from domain.models import (
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    SourceVerificationStatus,
)


_NUMERIC_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)"
)
_FINANCIAL_YEAR_PATTERN = re.compile(
    r"(?i)(?:\bFY\b|\bF\.?\s*Y\.?\b|\bfinancial\s+year\b)"
    r"\s*[:\-]?\s*(20\d{2})\s*[-/]\s*(\d{2}|20\d{2})(?!\d)"
)


def _parse_numeric_parts(parts: Tuple[str, str, str]) -> Optional[date]:
    day, month, year = (int(part) for part in parts)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _single_numeric_date(text: str) -> Optional[date]:
    matches = _NUMERIC_DATE_PATTERN.findall(text)
    if len(matches) != 1:
        return None
    return _parse_numeric_parts(matches[0])


def _financial_year_interval(text: str):
    matches = list(_FINANCIAL_YEAR_PATTERN.finditer(text))
    if len(matches) != 1:
        return None
    first_year = int(matches[0].group(1))
    second_token = matches[0].group(2)
    if len(second_token) == 2:
        second_year = (first_year // 100) * 100 + int(second_token)
    else:
        second_year = int(second_token)
    if second_year != first_year + 1:
        return None
    return (
        date(first_year, 4, 1),
        date(second_year, 3, 31),
    )


def _numeric_range_interval(text: str):
    matches = _NUMERIC_DATE_PATTERN.findall(text)
    if len(matches) != 2:
        return None
    start = _parse_numeric_parts(matches[0])
    end = _parse_numeric_parts(matches[1])
    if start is None or end is None or end < start:
        return None
    return (start, end)


def parse_tax_period_interval(text: str):
    """Parse only closed, unambiguous tax-period representations.

    Supported:
    - explicit FY / F.Y. / Financial Year YYYY-YY or YYYY-YYYY;
    - exactly two numeric dates forming an ordered range.

    If more than one representation is present, or neither is supported,
    return None. No prose/month/quarter guessing is performed.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    fy = _financial_year_interval(text)
    numeric_range = _numeric_range_interval(text)
    candidates = [value for value in (fy, numeric_range) if value is not None]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _trusted(fact: ExtractedFact) -> bool:
    return (
        isinstance(fact, ExtractedFact)
        and fact.status is FactStatus.CONFIRMED
        and fact.source_verification is SourceVerificationStatus.VERIFIED
        and isinstance(fact.source_text, str)
        and bool(fact.source_text.strip())
        and isinstance(fact.fact_id, str)
        and bool(fact.fact_id)
    )


def _anchor(
    fact: ExtractedFact,
    basis: LegalDateBasis,
    effective_date: date,
    *,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> LegalDateAnchor:
    return LegalDateAnchor(
        basis=basis,
        effective_date=effective_date,
        period_start=period_start,
        period_end=period_end,
        source_fact_id=fact.fact_id,
        source_page=fact.source_page,
        source_text=fact.source_text,
        source_fact_type=fact.fact_type,
        source_fact_role=fact.fact_role,
    )


def _unique_anchor(candidates):
    values = tuple(candidates)
    if len(values) != 1:
        return None
    return values[0]


def build_legal_date_context(
    facts: Iterable[ExtractedFact],
) -> LegalDateContext:
    fact_list = tuple(facts)
    if any(not isinstance(item, ExtractedFact) for item in fact_list):
        raise TypeError("facts must contain only ExtractedFact values")

    notice = _unique_anchor(
        _anchor(
            fact,
            LegalDateBasis.NOTICE_DATE,
            parsed,
        )
        for fact in fact_list
        if _trusted(fact)
        and fact.fact_type is FactType.NOTICE_DATE
        and (parsed := _single_numeric_date(fact.source_text)) is not None
    )

    tax_period = _unique_anchor(
        _anchor(
            fact,
            LegalDateBasis.TAX_PERIOD_END,
            interval[1],
            period_start=interval[0],
            period_end=interval[1],
        )
        for fact in fact_list
        if _trusted(fact)
        and fact.fact_type is FactType.TAX_PERIOD
        and (interval := parse_tax_period_interval(fact.source_text))
        is not None
    )

    detention = _unique_anchor(
        _anchor(
            fact,
            LegalDateBasis.DETENTION_OR_SEIZURE_DATE,
            parsed,
        )
        for fact in fact_list
        if _trusted(fact)
        and fact.fact_type is FactType.DOCUMENT_DETAIL
        and fact.fact_role is FactRole.DETENTION_OR_SEIZURE_DATE
        and (parsed := _single_numeric_date(fact.source_text)) is not None
    )

    return LegalDateContext(
        anchors=tuple(
            item
            for item in (notice, tax_period, detention)
            if item is not None
        )
    )
