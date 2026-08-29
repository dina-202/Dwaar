"""Unit tests for Phase 2 Step 7.3: the Deterministic Arithmetic Engine.

Verifies domain/arithmetic_engine.py against the authoritative
ARCHITECTURE_SPEC v1.1 §18.16–§18.25 arithmetic contract:

  - exactly the two whitelisted difference calculations with their exact
    formula strings and left/right role convention (§18.17, §18.19,
    §18.23);
  - source-fact lookup: exactly one fact per operand, exact
    case-sensitive fact IDs, duplicates rejected (§18.18);
  - provenance: value_text must be an exact substring of the referenced
    fact's source_text — no fuzzy matching, no claim-text fallback;
  - deterministic INR amount parsing with decimal.Decimal (§18.20):
    ungrouped, Western and Indian comma grouping, currency markers,
    optional minus and 1–2 digit fractions; malformed grouping, word
    forms, scientific notation and surrounding prose are rejected;
  - status: result == 0 → PASS, otherwise MISMATCH, with no tolerance
    and no rounding; any failure → INSUFFICIENT_DATA with result None
    and partial operand recovery (§18.22);
  - the result is an ArithmeticResult — never an ExtractedFact and
    never a FactStatus.INFERRED object (§18.21, §18.25);
  - inputs are never mutated; no Section-129/74/74A/RCM/interest
    calculations exist;
  - module purity: stdlib + domain.models only, no LLM, no network, no
    other engine imports.

Every test is fully offline — no LLM call, no network.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_arithmetic_engine.py -v
No pytest, no external dependencies.
"""

import copy
import inspect
import pathlib
import unittest
from decimal import Decimal

from domain import arithmetic_engine
from domain.arithmetic_engine import run_arithmetic
from domain.models import (
    ArithmeticCalculationType,
    ArithmeticOperand,
    ArithmeticRequest,
    ArithmeticResult,
    ArithmeticStatus,
    DraftPermission,
    ExtractedFact,
    FactStatus,
    FactType,
)


def make_fact(fact_id, source_text, fact_type=FactType.STATED_AMOUNT,
              claim="Stated amount fact"):
    """Build a CONFIRMED ExtractedFact around the given source text."""
    return ExtractedFact(
        fact_id=fact_id,
        claim=claim,
        status=FactStatus.CONFIRMED,
        source_text=source_text,
        fact_type=fact_type,
    )


def sourced(value_text, fact_id="F-001", fact_type=FactType.STATED_AMOUNT):
    """A fact whose source_text contains value_text exactly."""
    return make_fact(
        fact_id, f"Amount: {value_text}", fact_type=fact_type
    )


def make_operand(fact_id, value_text):
    return ArithmeticOperand(source_fact_id=fact_id, value_text=value_text)


def make_request(
    calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
    left_fact_id="F-001",
    left_value="Rs. 10,00,000",
    right_fact_id="F-002",
    right_value="Rs. 8,50,000",
):
    return ArithmeticRequest(
        calculation_type=calculation_type,
        left_operand=make_operand(left_fact_id, left_value),
        right_operand=make_operand(right_fact_id, right_value),
    )


def make_itc_facts():
    """The two ITC reconciliation source facts matching make_request()."""
    return [
        make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000"),
        make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
    ]


def run_itc():
    """Run the default ITC reconciliation end to end."""
    return run_arithmetic(make_request(), make_itc_facts())


def run_single_operand(value_text, right_value="100000"):
    """Run with `value_text` as the LEFT operand and a valid right one."""
    request = make_request(
        left_value=value_text, right_value=right_value
    )
    facts = [sourced(value_text), sourced(right_value, fact_id="F-002")]
    return run_arithmetic(request, facts)


class PublicApiAndItcTests(unittest.TestCase):
    """A: public API contract and the end-to-end ITC difference."""

    def test_run_arithmetic_api_exists(self):
        signature = inspect.signature(run_arithmetic)
        self.assertEqual(
            list(signature.parameters), ["request", "facts"]
        )
        self.assertIs(
            signature.return_annotation, ArithmeticResult
        )

    def test_return_type_arithmetic_result(self):
        self.assertIs(type(run_itc()), ArithmeticResult)

    def test_itc_difference_result(self):
        # 10,00,000 - 8,50,000 = 1,50,000
        result = run_itc()
        self.assertEqual(result.result, Decimal("150000"))

    def test_itc_status_mismatch(self):
        result = run_itc()
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)

    def test_exact_source_fact_ids(self):
        result = run_itc()
        self.assertEqual(result.source_fact_ids, ["F-001", "F-002"])

    def test_exact_operand_decimals(self):
        result = run_itc()
        self.assertEqual(
            result.operand_values,
            [Decimal("1000000"), Decimal("850000")],
        )

    def test_exact_formula_string(self):
        result = run_itc()
        self.assertEqual(result.formula, "GSTR-3B ITC - GSTR-2B ITC")

    def test_inr_currency(self):
        self.assertEqual(run_itc().currency, "INR")

    def test_conditional_draft_permission(self):
        self.assertIs(
            run_itc().allowed_in_draft, DraftPermission.CONDITIONAL
        )


class OutputTaxTests(unittest.TestCase):
    """B: successful OUTPUT_TAX_DIFFERENCE reconciliation."""

    def _run_output_tax(self):
        request = make_request(
            calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
            left_value="Rs. 5,00,000",
            right_value="Rs. 5,00,000",
        )
        facts = [
            make_fact("F-001", "Liability in GSTR-1: Rs. 5,00,000"),
            make_fact("F-002", "Liability in GSTR-3B: Rs. 5,00,000"),
        ]
        return run_arithmetic(request, facts)

    def test_output_tax_zero_result(self):
        result = self._run_output_tax()
        self.assertEqual(result.result, Decimal("0"))

    def test_output_tax_status_pass(self):
        self.assertIs(
            self._run_output_tax().status, ArithmeticStatus.PASS
        )

    def test_exact_output_tax_formula(self):
        result = self._run_output_tax()
        self.assertEqual(
            result.formula, "GSTR-1 liability - GSTR-3B liability"
        )


class DecimalAccuracyTests(unittest.TestCase):
    """C: exact Decimal arithmetic, never float."""

    def test_paise_subtraction_exact(self):
        request = make_request(
            left_value="Rs. 10,00,000.50", right_value="Rs. 8,50,000.25"
        )
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000.50"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000.25"),
        ]
        result = run_arithmetic(request, facts)
        self.assertEqual(result.result, Decimal("150000.25"))
        self.assertEqual(str(result.result), "150000.25")  # exact digits

    def test_one_decimal_values(self):
        request = make_request(left_value="100.5", right_value="50.5")
        facts = [sourced("100.5"), sourced("50.5", fact_id="F-002")]
        result = run_arithmetic(request, facts)
        self.assertEqual(str(result.result), "50.0")  # exact precision

    def test_negative_result_allowed_and_mismatch(self):
        request = make_request(
            left_value="Rs. 8,50,000", right_value="Rs. 10,00,000"
        )
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 8,50,000"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 10,00,000"),
        ]
        result = run_arithmetic(request, facts)
        self.assertEqual(result.result, Decimal("-150000"))
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)

    def test_no_float_type_in_operands_or_result(self):
        result = run_itc()
        for value in result.operand_values:
            self.assertIsInstance(value, Decimal)
            self.assertNotIsInstance(value, float)
        self.assertIsInstance(result.result, Decimal)


class UngroupedFormsTests(unittest.TestCase):
    """D: accepted ungrouped digit forms."""

    def test_150000(self):
        result = run_single_operand("150000", right_value="50000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))
        self.assertEqual(result.result, Decimal("100000"))

    def test_150000_50(self):
        result = run_single_operand("150000.50", right_value="50000.00")
        self.assertEqual(result.operand_values[0], Decimal("150000.50"))
        self.assertEqual(result.result, Decimal("100000.50"))

    def test_negative_ungrouped(self):
        result = run_single_operand("-150000", right_value="50000")
        self.assertEqual(result.operand_values[0], Decimal("-150000"))
        self.assertEqual(result.result, Decimal("-200000"))
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)


class WesternGroupingTests(unittest.TestCase):
    """E: accepted standard 3-digit comma grouping."""

    def test_150_000(self):
        result = run_single_operand("150,000", right_value="50,000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))
        self.assertEqual(result.result, Decimal("100000"))

    def test_1_500_000(self):
        result = run_single_operand("1,500,000", right_value="500,000")
        self.assertEqual(result.operand_values[0], Decimal("1500000"))
        self.assertEqual(result.result, Decimal("1000000"))

    def test_123_456_789(self):
        result = run_single_operand("123,456,789", right_value="456,789")
        self.assertEqual(result.operand_values[0], Decimal("123456789"))
        self.assertEqual(result.result, Decimal("123000000"))


class IndianGroupingTests(unittest.TestCase):
    """F: accepted Indian lakh/crore comma grouping."""

    def test_1_50_000(self):
        result = run_single_operand("1,50,000", right_value="50,000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))
        self.assertEqual(result.result, Decimal("100000"))

    def test_10_00_000_25(self):
        result = run_single_operand("10,00,000.25", right_value="5,00,000.25")
        self.assertEqual(
            result.operand_values[0], Decimal("1000000.25")
        )
        self.assertEqual(result.result, Decimal("500000.00"))

    def test_1_23_45_678(self):
        result = run_single_operand("1,23,45,678", right_value="23,45,678")
        self.assertEqual(result.operand_values[0], Decimal("12345678"))
        self.assertEqual(result.result, Decimal("10000000"))

    def test_12_34_56_789(self):
        result = run_single_operand("12,34,56,789", right_value="34,56,789")
        self.assertEqual(result.operand_values[0], Decimal("123456789"))
        # 123456789 - 3456789 = 120000000
        self.assertEqual(result.result, Decimal("120000000"))


class CurrencyFormsTests(unittest.TestCase):
    """G: accepted currency markers and case handling."""

    def test_rupee_symbol_amount(self):
        result = run_single_operand("₹1,50,000", right_value="50,000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))

    def test_rs_dot_amount(self):
        result = run_single_operand("Rs. 1,50,000.00", right_value="50,000")
        self.assertEqual(result.operand_values[0], Decimal("150000.00"))
        self.assertEqual(str(result.operand_values[0]), "150000.00")

    def test_rs_amount(self):
        result = run_single_operand("Rs 150000", right_value="50000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))

    def test_inr_amount(self):
        result = run_single_operand("INR 150000", right_value="50000")
        self.assertEqual(result.operand_values[0], Decimal("150000"))

    def test_textual_currency_case_insensitive(self):
        lower = run_single_operand("rs 1,50,000", right_value="50,000")
        self.assertEqual(lower.operand_values[0], Decimal("150000"))
        mixed = run_single_operand("Inr 150000", right_value="50000")
        self.assertEqual(mixed.operand_values[0], Decimal("150000"))

    def test_negative_currency_amount(self):
        result = run_single_operand("-Rs. 1,50,000.50", right_value="50,000")
        self.assertEqual(
            result.operand_values[0], Decimal("-150000.50")
        )
        self.assertEqual(result.result, Decimal("-200000.50"))


class RejectedAmountFormsTests(unittest.TestCase):
    """H: unsupported amount forms are rejected, never guessed."""

    def assert_rejected_form(self, value_text):
        result = run_single_operand(value_text)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        # The valid right operand is still recovered; the bad left form
        # contributed nothing.
        self.assertEqual(result.operand_values, [Decimal("100000")])

    def test_word_form_rejected(self):
        self.assert_rejected_form("one lakh")

    def test_scientific_notation_rejected(self):
        self.assert_rejected_form("1.5e6")

    def test_percent_rejected(self):
        self.assert_rejected_form("10%")

    def test_plus_sign_rejected(self):
        self.assert_rejected_form("+150000")

    def test_parentheses_negative_rejected(self):
        self.assert_rejected_form("(150000)")

    def test_expression_rejected(self):
        self.assert_rejected_form("100000+50000")

    def test_multiple_currency_tokens_rejected(self):
        self.assert_rejected_form("Rs. ₹1,50,000")

    def test_prose_around_amount_rejected(self):
        self.assert_rejected_form("approx Rs. 1,50,000")

    def test_trailing_decimal_point_rejected(self):
        self.assert_rejected_form("100.")

    def test_leading_decimal_point_rejected(self):
        self.assert_rejected_form(".50")

    def test_more_than_two_decimal_places_rejected(self):
        self.assert_rejected_form("100.123")


class InvalidGroupingTests(unittest.TestCase):
    """I: malformed comma grouping is rejected, never guessed."""

    def assert_rejected_grouping(self, value_text):
        result = run_single_operand(value_text)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        self.assertEqual(result.operand_values, [Decimal("100000")])

    def test_1_500_00_rejected(self):
        self.assert_rejected_grouping("1,500,00")

    def test_12_345_67_rejected(self):
        self.assert_rejected_grouping("12,345,67")

    def test_1_2_345_rejected(self):
        self.assert_rejected_grouping("1,2,345")

    def test_123_45_678_rejected(self):
        self.assert_rejected_grouping("123,45,678")

    def test_1_double_comma_50_000_rejected(self):
        self.assert_rejected_grouping("1,,50,000")

    def test_leading_comma_rejected(self):
        self.assert_rejected_grouping(",150000")

    def test_trailing_comma_rejected(self):
        self.assert_rejected_grouping("150000,")


class SourceLookupTests(unittest.TestCase):
    """J: exactly one matching source fact per operand."""

    def test_missing_left_fact_insufficient(self):
        request = make_request(left_fact_id="F-999")
        facts = [
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000")
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        # Requested IDs are still reported, left/right order preserved.
        self.assertEqual(result.source_fact_ids, ["F-999", "F-002"])
        self.assertEqual(result.operand_values, [Decimal("850000")])

    def test_missing_right_fact_insufficient(self):
        request = make_request(right_fact_id="F-999")
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000")
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        self.assertEqual(result.source_fact_ids, ["F-001", "F-999"])
        self.assertEqual(result.operand_values, [Decimal("1000000")])

    def test_duplicate_matching_fact_id_insufficient(self):
        # Identical duplicated source_text does not resolve the
        # ambiguity — provenance must never be silently resolved.
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000"),
            make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        self.assertEqual(result.operand_values, [Decimal("850000")])

    def test_ids_matched_exactly_case_sensitive(self):
        request = make_request(left_fact_id="f-001")
        result = run_arithmetic(request, make_itc_facts())
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_operand_fact_type_is_not_required(self):
        # A valid sourced numeric value is accepted even when the
        # containing fact has another FactType — the operand carries its
        # own exact provenance.
        facts = [
            sourced("Rs. 10,00,000", fact_type=FactType.OTHER_NOTICE_FACT),
            sourced("Rs. 8,50,000", fact_id="F-002",
                    fact_type=FactType.TAX_PERIOD),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertEqual(result.result, Decimal("150000"))
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)


class ProvenanceTests(unittest.TestCase):
    """K: exact-substring provenance, no fallbacks."""

    def test_value_text_exact_substring_required(self):
        # "1,50,000" is NOT a substring of "Rs. 15,00,000": the comma
        # positions differ. No fuzzy matching, no repair.
        request = make_request(left_value="1,50,000")
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 15,00,000"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_value_text_empty_rejected(self):
        request = make_request(left_value="")
        result = run_arithmetic(request, make_itc_facts())
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_value_text_non_string_rejected(self):
        request = make_request(left_value=None)
        result = run_arithmetic(request, make_itc_facts())
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_source_text_none_rejected(self):
        facts = [
            make_fact("F-001", None),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_source_text_empty_rejected(self):
        facts = [
            make_fact("F-001", ""),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_source_text_non_string_insufficient_not_crash(self):
        facts = [
            make_fact("F-001", 42),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)

    def test_no_claim_text_fallback(self):
        # The claim mentions the amount, but provenance comes from
        # source_text only: a non-matching source_text is insufficient.
        facts = [
            make_fact(
                "F-001",
                "See the attached reconciliation statement",
                claim="The ITC amount is Rs. 10,00,000",
            ),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(make_request(), facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)


class PartialOperandRecoveryTests(unittest.TestCase):
    """L: INSUFFICIENT_DATA preserves only resolved operands."""

    def test_left_parses_right_fails(self):
        request = make_request(right_value="bogus amount")
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 10,00,000"),
            sourced("bogus amount", fact_id="F-002"),
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertEqual(result.operand_values, [Decimal("1000000")])

    def test_left_fails_right_parses(self):
        request = make_request(left_value="bogus amount")
        facts = [
            sourced("bogus amount"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 8,50,000"),
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertEqual(result.operand_values, [Decimal("850000")])

    def test_both_fail_operand_values_empty(self):
        request = make_request(
            left_value="bogus left", right_value="bogus right"
        )
        facts = [
            sourced("bogus left"),
            sourced("bogus right", fact_id="F-002"),
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertEqual(result.operand_values, [])

    def test_result_none_for_insufficient(self):
        request = make_request(right_fact_id="F-999")
        result = run_arithmetic(request, make_itc_facts())
        self.assertIsNone(result.result)


class SameSourceFactTests(unittest.TestCase):
    """M: one source fact may feed both operands when it uniquely exists."""

    def test_same_fact_can_contain_both_operands(self):
        facts = [
            make_fact(
                "F-001",
                "GSTR-3B ITC: Rs. 10,00,000; GSTR-2B ITC: Rs. 8,50,000",
            )
        ]
        request = make_request(
            left_fact_id="F-001",
            left_value="Rs. 10,00,000",
            right_fact_id="F-001",
            right_value="Rs. 8,50,000",
        )
        result = run_arithmetic(request, facts)
        self.assertEqual(result.result, Decimal("150000"))
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)
        self.assertEqual(result.source_fact_ids, ["F-001", "F-001"])

    def test_shared_fact_must_be_unique(self):
        facts = [
            make_fact(
                "F-001",
                "GSTR-3B ITC: Rs. 10,00,000; GSTR-2B ITC: Rs. 8,50,000",
            ),
            make_fact(
                "F-001",
                "GSTR-3B ITC: Rs. 10,00,000; GSTR-2B ITC: Rs. 8,50,000",
            ),
        ]
        request = make_request(
            left_fact_id="F-001",
            left_value="Rs. 10,00,000",
            right_fact_id="F-001",
            right_value="Rs. 8,50,000",
        )
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)


class CalculationWhitelistTests(unittest.TestCase):
    """N: exactly the two authorized calculations exist."""

    def test_exactly_two_calculation_types_supported(self):
        self.assertEqual(
            [(member.name, member.value) for member in ArithmeticCalculationType],
            [
                ("ITC_DIFFERENCE", "itc_difference"),
                ("OUTPUT_TAX_DIFFERENCE", "output_tax_difference"),
            ],
        )
        # The engine's formula map covers exactly the enum — no more, no
        # less (§18.23).
        self.assertEqual(
            set(arithmetic_engine._FORMULAS),
            set(ArithmeticCalculationType),
        )

    def test_no_section_129_calculation(self):
        for name in (
            "SEC129",
            "SEC129_PENALTY",
            "PENALTY_100_PERCENT",
            "PENALTY_200_PERCENT",
        ):
            self.assertFalse(
                hasattr(ArithmeticCalculationType, name), name
            )

    def test_no_section_74_calculation(self):
        for name in ("SEC74_PENALTY", "SEC74A", "PENALTY"):
            self.assertFalse(
                hasattr(ArithmeticCalculationType, name), name
            )

    def test_no_rcm_calculation(self):
        for name in ("RCM", "RCM_LIABILITY", "RCM_STATUTORY"):
            self.assertFalse(
                hasattr(ArithmeticCalculationType, name), name
            )

    def test_no_interest_calculation(self):
        for name in ("INTEREST", "STATUTORY_INTEREST"):
            self.assertFalse(
                hasattr(ArithmeticCalculationType, name), name
            )


class UnsupportedTypeTests(unittest.TestCase):
    """O: an unknown calculation type never crashes or invents."""

    def test_invalid_calculation_type_insufficient(self):
        request = make_request(calculation_type="sec129_penalty")
        result = run_arithmetic(request, make_itc_facts())
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)
        self.assertEqual(result.source_fact_ids, [])
        self.assertEqual(result.operand_values, [])

    def test_invalid_calculation_type_empty_formula(self):
        request = make_request(calculation_type="itc_difference")
        result = run_arithmetic(request, make_itc_facts())
        self.assertEqual(result.formula, "")


class NoInferredFactTests(unittest.TestCase):
    """P: the result is an ArithmeticResult, never an ExtractedFact."""

    def test_result_is_not_extracted_fact(self):
        self.assertNotIsInstance(run_itc(), ExtractedFact)

    def test_no_fact_id_on_arithmetic_result(self):
        self.assertFalse(hasattr(run_itc(), "fact_id"))

    def test_no_inferred_fact_object_created(self):
        # The engine never references FactStatus or INFERRED at all, so
        # no FactStatus.INFERRED ExtractedFact can be produced.
        source = pathlib.Path(arithmetic_engine.__file__).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("INFERRED", source)
        self.assertNotIn("FactStatus", source)


class InputImmutabilityTests(unittest.TestCase):
    """Q: no input object is mutated."""

    def test_request_unchanged(self):
        request = make_request()
        before = copy.deepcopy(request)
        run_arithmetic(request, make_itc_facts())
        self.assertEqual(request, before)

    def test_operands_unchanged(self):
        request = make_request()
        left_before = copy.deepcopy(request.left_operand)
        right_before = copy.deepcopy(request.right_operand)
        run_arithmetic(request, make_itc_facts())
        self.assertEqual(request.left_operand, left_before)
        self.assertEqual(request.right_operand, right_before)

    def test_source_facts_unchanged(self):
        facts = make_itc_facts()
        before = copy.deepcopy(facts)
        run_arithmetic(make_request(), facts)
        self.assertEqual(facts, before)

    def test_source_facts_list_unchanged(self):
        facts = make_itc_facts()
        before_ids = [id(fact) for fact in facts]
        run_arithmetic(make_request(), facts)
        # Same objects, same order, same length — nothing replaced or
        # reordered.
        self.assertEqual([id(fact) for fact in facts], before_ids)
        self.assertEqual(len(facts), 2)


class ModulePurityTests(unittest.TestCase):
    """R: arithmetic_engine.py stays stdlib + domain.models."""

    ALLOWED_IMPORT_ROOTS = {"re", "decimal", "typing", "domain"}

    FORBIDDEN_TOKENS = (
        "llm_client",
        "gemini",
        "google",
        "workflows",
        "requests",
        "urllib",
        "socket",
        "calculate_deadline",
        "deadline_engine",
        "fact_engine",
        "preflight_engine",
    )

    NETWORK_ROOTS = {"requests", "urllib", "socket", "http"}

    LEGAL_RULE_ROOTS = {"legal", "law", "statute", "rules"}

    @classmethod
    def _source(cls) -> str:
        return pathlib.Path(arithmetic_engine.__file__).read_text(
            encoding="utf-8"
        )

    @classmethod
    def _import_roots(cls) -> set:
        roots = set()
        for line in cls._source().splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                module_name = stripped.split()[1]
                if module_name.startswith("."):
                    continue
                roots.add(module_name.split(".")[0])
            elif stripped.startswith("import "):
                roots.add(stripped.split()[1].split(".")[0])
        return roots

    def test_stdlib_and_domain_models_only(self):
        roots = self._import_roots()
        self.assertTrue(
            roots <= self.ALLOWED_IMPORT_ROOTS,
            f"unexpected import roots {sorted(roots)}",
        )

    def test_no_llm(self):
        source = self._source()
        for token in ("llm_client", "gemini", "google"):
            self.assertNotIn(token, source, token)
        self.assertNotIn("modules", self._import_roots())

    def test_no_workflows(self):
        self.assertNotIn("workflows", self._source())

    def test_no_other_engine_imports(self):
        source = self._source()
        for token in (
            "calculate_deadline",
            "deadline_engine",
            "fact_engine",
            "preflight_engine",
        ):
            self.assertNotIn(token, source, token)

    def test_no_network(self):
        roots = self._import_roots()
        self.assertTrue(
            roots.isdisjoint(self.NETWORK_ROOTS),
            f"network import roots {sorted(roots)}",
        )

    def test_no_direct_legal_rule_imports(self):
        roots = self._import_roots()
        self.assertTrue(
            roots.isdisjoint(self.LEGAL_RULE_ROOTS),
            f"legal-rule import roots {sorted(roots)}",
        )

    def test_no_statutory_penalty_formula_in_source(self):
        source = self._source()
        self.assertNotIn("100% penalty", source)
        self.assertNotIn("200% penalty", source)


class FullStatusBehaviorTests(unittest.TestCase):
    """S: complete status behavior matrix."""

    def test_zero_result_pass(self):
        request = make_request(
            calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
            left_value="Rs. 5,00,000",
            right_value="Rs. 5,00,000",
        )
        facts = [
            make_fact("F-001", "Liability in GSTR-1: Rs. 5,00,000"),
            make_fact("F-002", "Liability in GSTR-3B: Rs. 5,00,000"),
        ]
        result = run_arithmetic(request, facts)
        self.assertEqual(result.result, Decimal("0"))
        self.assertIs(result.status, ArithmeticStatus.PASS)

    def test_positive_result_mismatch(self):
        self.assertIs(run_itc().status, ArithmeticStatus.MISMATCH)

    def test_negative_result_mismatch(self):
        request = make_request(
            left_value="Rs. 8,50,000", right_value="Rs. 10,00,000"
        )
        facts = [
            make_fact("F-001", "ITC in GSTR-3B: Rs. 8,50,000"),
            make_fact("F-002", "ITC in GSTR-2B: Rs. 10,00,000"),
        ]
        result = run_arithmetic(request, facts)
        self.assertIs(result.status, ArithmeticStatus.MISMATCH)

    def test_missing_data_insufficient(self):
        request = make_request(right_fact_id="F-999")
        result = run_arithmetic(request, make_itc_facts())
        self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertIsNone(result.result)


if __name__ == "__main__":
    unittest.main()
