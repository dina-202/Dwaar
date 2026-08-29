"""Deterministic arithmetic engine for CA Notice AI
(ARCHITECTURE_SPEC_v1_1 §18.16–§18.25).

Architecture Phase 2 — Step 7.3 artifact. Pure Python, deterministic.

Receives an explicit ArithmeticRequest that references exact source facts
and exact amount text, and produces the §18.21 ArithmeticResult:

  - exactly the two whitelisted difference calculations (§18.17, §18.23);
  - operand roles are authoritative in the request; the engine never
    infers semantic roles from claim text (§18.16, §18.19);
  - each operand must resolve to exactly one supplied ExtractedFact, and
    its value_text must be an exact substring of that fact's source_text
    (§18.18);
  - INR amounts parse deterministically with decimal.Decimal — never
    binary float (§18.20);
  - result = left - right; zero → PASS, otherwise MISMATCH; no
    tolerance, no rounding (§18.22);
  - unresolved or unparseable operands yield INSUFFICIENT_DATA with
    result None (§18.22);
  - the output is an ArithmeticResult, never an ExtractedFact and never
    a derived fact object (§18.21, §18.25).

Never calls an LLM, never mutates its inputs, and implements no
statutory calculations beyond the §18.23 whitelist. Standard library +
domain.models only.
"""

import re
from decimal import Decimal
from typing import List, Optional

from domain.models import (
    ArithmeticCalculationType,
    ArithmeticOperand,
    ArithmeticRequest,
    ArithmeticResult,
    ArithmeticStatus,
    ExtractedFact,
)

# §18.19 authoritative role convention: the caller chooses which sourced
# facts sit left/right; the engine only subtracts. These are the only
# whitelisted formulas (§18.23).
_FORMULAS = {
    ArithmeticCalculationType.ITC_DIFFERENCE: "GSTR-3B ITC - GSTR-2B ITC",
    ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE: (
        "GSTR-1 liability - GSTR-3B liability"
    ),
}

# Optional currency markers (§18.20). Textual forms are case-insensitive.
_CURRENCY_PATTERN = r"(?:₹|rs\.?|inr)?"

# Amount core (§18.20): ungrouped digits, standard 3-digit comma
# grouping, or Indian lakh/crore grouping, each with an optional one- or
# two-digit decimal fraction.
_AMOUNT_CORE = (
    r"(?:"
    r"\d+(?:\.\d{1,2})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d{1,2}(?:,\d{2})*(?:,\d{3})(?:\.\d{1,2})?"
    r")"
)

# Full amount: optional minus, optional currency marker, then the amount
# core. Matched against the whitespace-stripped value_text in full — no
# surrounding prose, no partial matches.
_AMOUNT_PATTERN = re.compile(
    r"(-?)" + _CURRENCY_PATTERN + r"\s*(" + _AMOUNT_CORE + r")",
    re.IGNORECASE,
)


def _lookup_unique_fact(
    facts: List[ExtractedFact], fact_id: str
) -> Optional[ExtractedFact]:
    """Return the single fact with fact_id, or None.

    None both when no fact matches and when more than one fact shares
    the ID — ambiguous provenance is never silently resolved.
    """
    matches = [fact for fact in facts if fact.fact_id == fact_id]
    if len(matches) == 1:
        return matches[0]
    return None


def _parse_amount(value_text: str) -> Optional[Decimal]:
    """Parse one supported INR amount fragment to Decimal, or None.

    The whole whitespace-stripped fragment must be exactly one amount:
    optional minus, optional currency marker, grouped/ungrouped digits,
    optional one- or two-digit fraction. Word forms, scientific
    notation, plus signs, parentheses, embedded expressions and
    surrounding prose are rejected rather than guessed (§18.20).
    """
    stripped = value_text.strip()
    if not stripped:
        return None
    match = _AMOUNT_PATTERN.fullmatch(stripped)
    if match is None:
        return None
    sign = match.group(1)
    digits = match.group(2).replace(",", "")
    return Decimal(sign + digits)


def _resolve_operand(
    operand: ArithmeticOperand, facts: List[ExtractedFact]
) -> Optional[Decimal]:
    """Resolve one operand to an exact Decimal, or None on any failure.

    All of these must hold (§18.18, §18.20, §18.22):

    - value_text is a non-empty string;
    - exactly one supplied fact matches source_fact_id;
    - that fact's source_text is a non-empty string;
    - value_text is an exact substring of source_text;
    - value_text parses as one supported amount.

    Any failure yields None — no partial repair, no fallback source, no
    claim-text guessing.
    """
    value_text = operand.value_text
    if not isinstance(value_text, str) or not value_text.strip():
        return None
    fact = _lookup_unique_fact(facts, operand.source_fact_id)
    if fact is None:
        return None
    source_text = fact.source_text
    if not isinstance(source_text, str) or not source_text:
        return None
    if value_text not in source_text:
        return None
    return _parse_amount(value_text)


def run_arithmetic(
    request: ArithmeticRequest, facts: List[ExtractedFact]
) -> ArithmeticResult:
    """Execute one whitelisted deterministic calculation (§18.19–§18.22).

    - The request's operand ordering is authoritative: the result is
      always left - right; the engine never infers roles from claim
      text (§18.19).
    - Provenance or parse failures produce INSUFFICIENT_DATA with
      result None, both requested source fact IDs in left/right order,
      and only the successfully resolved operand values (§18.22).
    - An unknown calculation type produces INSUFFICIENT_DATA with an
      empty formula and no operand resolution; nothing crashes and
      nothing is invented (§18.23).
    - No input object is mutated, and no ExtractedFact is created
      (§18.21).
    """
    formula = _FORMULAS.get(request.calculation_type)
    if formula is None:
        # Not one of the two authorized calculations (§18.23).
        return ArithmeticResult(
            calculation_type=request.calculation_type,
            status=ArithmeticStatus.INSUFFICIENT_DATA,
            source_fact_ids=[],
            operand_values=[],
            result=None,
            formula="",
        )

    left_value = _resolve_operand(request.left_operand, facts)
    right_value = _resolve_operand(request.right_operand, facts)

    source_fact_ids = [
        request.left_operand.source_fact_id,
        request.right_operand.source_fact_id,
    ]
    operand_values = [
        value for value in (left_value, right_value) if value is not None
    ]

    if left_value is None or right_value is None:
        return ArithmeticResult(
            calculation_type=request.calculation_type,
            status=ArithmeticStatus.INSUFFICIENT_DATA,
            source_fact_ids=source_fact_ids,
            operand_values=operand_values,
            result=None,
            formula=formula,
        )

    result = left_value - right_value
    status = (
        ArithmeticStatus.PASS
        if result == Decimal("0")
        else ArithmeticStatus.MISMATCH
    )
    return ArithmeticResult(
        calculation_type=request.calculation_type,
        status=status,
        source_fact_ids=source_fact_ids,
        operand_values=operand_values,
        result=result,
        formula=formula,
    )
