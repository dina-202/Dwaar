"""Unit tests for Phase 2 Step 7.1 preflight + arithmetic domain models.

Verifies the v1.1-approved §18 contracts added in Step 7.1:

  - DeadlineConflictStatus: exactly the three §18.9 members, with no
    VALID / INVALID concept;
  - ArithmeticCalculationType: exactly the two §18.17/§18.23 whitelisted
    reconciliation calculations, no statutory penalty/RCM/interest types;
  - PreflightResult: exactly the twelve §18.13 fields in order, with no
    legal-validity fields (notice_valid, notice_invalid,
    jurisdiction_valid, officer_competent, ...);
  - ArithmeticOperand (§18.18), ArithmeticRequest (§18.19) and
    ArithmeticResult (§18.21) dataclass contracts, including the
    ArithmeticResult-is-NOT-an-ExtractedFact rule and its defaults
    (currency "INR", allowed_in_draft CONDITIONAL);
  - Decimal representation for arithmetic operands/results;
  - backward compatibility: FactExtractionResult and ExtractedFact keep
    their previous exact contracts, legacy constructors still work, and
    domain/models.py remains standard-library-only (now including
    decimal).

Pure contract tests only. No engine behavior (preflight, due-date
parsing, identifier derivation, amount parsing, arithmetic) is
implemented or simulated here — the engines do not exist yet
(Steps 7.2 / 7.3).

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_preflight_arithmetic_models.py -v
No pytest, no external dependencies, no LLM calls, no network.
"""

import pathlib
import unittest
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from domain.models import (
    ArithmeticCalculationType,
    ArithmeticOperand,
    ArithmeticRequest,
    ArithmeticResult,
    ArithmeticStatus,
    AuthorityDetailsStatus,
    CommunicationIdentifierStatus,
    DeadlineConflictStatus,
    DraftPermission,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactStatus,
    FactType,
    PreflightResult,
)

# Exact members, in §18.9 spec order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_DEADLINE_CONFLICT_MEMBERS = [
    ("MATCH", "match"),
    ("CONFLICT", "conflict"),
    ("CANNOT_COMPARE", "cannot_compare"),
]

# Exact members, in §18.17 spec order.
EXPECTED_CALCULATION_TYPES = [
    ("ITC_DIFFERENCE", "itc_difference"),
    ("OUTPUT_TAX_DIFFERENCE", "output_tax_difference"),
]

# The exact §18.13 PreflightResult field contract, in order.
EXPECTED_PREFLIGHT_FIELDS = [
    "fact_extraction_status",
    "communication_identifier_status",
    "portal_verification_required",
    "authority_details_status",
    "authority_verification_required",
    "stated_due_date_fact_ids",
    "parsed_stated_due_dates",
    "unparsed_stated_due_date_fact_ids",
    "deadline_conflict_status",
    "hearing_fact_ids",
    "requested_document_fact_ids",
    "referenced_annexure_fact_ids",
]

# The exact §18.21 ArithmeticResult field contract, in order.
EXPECTED_ARITHMETIC_RESULT_FIELDS = [
    "calculation_type",
    "status",
    "source_fact_ids",
    "operand_values",
    "result",
    "formula",
    "currency",
    "allowed_in_draft",
]


class DeadlineConflictStatusTests(unittest.TestCase):
    """§18.9: date comparison only, no VALID / INVALID concept."""

    def test_imports_and_is_enum(self):
        self.assertTrue(issubclass(DeadlineConflictStatus, Enum))

    def test_has_exactly_3_members(self):
        self.assertEqual(len(DeadlineConflictStatus), 3)

    def test_member_names_and_order_exact(self):
        self.assertEqual(
            [member.name for member in DeadlineConflictStatus],
            [name for name, _ in EXPECTED_DEADLINE_CONFLICT_MEMBERS],
        )

    def test_member_values_exact(self):
        self.assertEqual(
            [(member.name, member.value) for member in DeadlineConflictStatus],
            EXPECTED_DEADLINE_CONFLICT_MEMBERS,
        )

    def test_values_are_lowercase_member_names(self):
        for member in DeadlineConflictStatus:
            self.assertEqual(member.value, member.name.lower(), member.name)

    def test_no_valid_or_invalid_members(self):
        # §18.9: "No VALID / INVALID member." This enum compares dates
        # only; it never decides legal validity.
        self.assertFalse(hasattr(DeadlineConflictStatus, "VALID"))
        self.assertFalse(hasattr(DeadlineConflictStatus, "INVALID"))


class ArithmeticCalculationTypeTests(unittest.TestCase):
    """§18.17/§18.23: exactly the two whitelisted calculations."""

    def test_imports_and_is_enum(self):
        self.assertTrue(issubclass(ArithmeticCalculationType, Enum))

    def test_has_exactly_2_members(self):
        self.assertEqual(len(ArithmeticCalculationType), 2)

    def test_member_names_and_order_exact(self):
        self.assertEqual(
            [member.name for member in ArithmeticCalculationType],
            [name for name, _ in EXPECTED_CALCULATION_TYPES],
        )

    def test_member_values_exact(self):
        self.assertEqual(
            [(member.name, member.value) for member in ArithmeticCalculationType],
            EXPECTED_CALCULATION_TYPES,
        )

    def test_values_are_lowercase_member_names(self):
        for member in ArithmeticCalculationType:
            self.assertEqual(member.value, member.name.lower(), member.name)

    def test_no_extra_calculation_types(self):
        # §18.23: no Section 129/74/74A penalty, no RCM, no interest.
        for name in (
            "SEC129_PENALTY",
            "SEC74_PENALTY",
            "SEC74A",
            "RCM_LIABILITY",
            "INTEREST",
            "PENALTY",
        ):
            self.assertFalse(
                hasattr(ArithmeticCalculationType, name), name
            )


class PreflightResultTests(unittest.TestCase):
    """§18.13: exactly twelve fields, no legal-validity fields."""

    def make_preflight_result(self) -> PreflightResult:
        return PreflightResult(
            fact_extraction_status=FactExtractionStatus.SUCCESS,
            communication_identifier_status=(
                CommunicationIdentifierStatus.BOTH_PRESENT
            ),
            portal_verification_required=True,
            authority_details_status=AuthorityDetailsStatus.PRESENT,
            authority_verification_required=True,
            stated_due_date_fact_ids=["F-005"],
            parsed_stated_due_dates=[date(2026, 9, 17)],
            unparsed_stated_due_date_fact_ids=["F-006"],
            deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
            hearing_fact_ids=["F-007"],
            requested_document_fact_ids=["F-008"],
            referenced_annexure_fact_ids=["F-009"],
        )

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(PreflightResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(PreflightResult)],
            EXPECTED_PREFLIGHT_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(PreflightResult)), 12)

    def test_field_annotations_exact(self):
        # Enum classes and bool are asserted by identity; typing aliases
        # by equality (typing caches can be refreshed in one-process runs).
        by_name = {f.name: f for f in fields(PreflightResult)}
        self.assertIs(
            by_name["fact_extraction_status"].type, FactExtractionStatus
        )
        self.assertIs(
            by_name["communication_identifier_status"].type,
            CommunicationIdentifierStatus,
        )
        self.assertIs(by_name["portal_verification_required"].type, bool)
        self.assertIs(
            by_name["authority_details_status"].type, AuthorityDetailsStatus
        )
        self.assertIs(by_name["authority_verification_required"].type, bool)
        self.assertEqual(by_name["stated_due_date_fact_ids"].type, List[str])
        self.assertEqual(by_name["parsed_stated_due_dates"].type, List[date])
        self.assertEqual(
            by_name["unparsed_stated_due_date_fact_ids"].type, List[str]
        )
        self.assertIs(
            by_name["deadline_conflict_status"].type, DeadlineConflictStatus
        )
        self.assertEqual(by_name["hearing_fact_ids"].type, List[str])
        self.assertEqual(by_name["requested_document_fact_ids"].type, List[str])
        self.assertEqual(by_name["referenced_annexure_fact_ids"].type, List[str])

    def test_supplied_values_preserved(self):
        result = self.make_preflight_result()
        self.assertIs(
            result.fact_extraction_status, FactExtractionStatus.SUCCESS
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.BOTH_PRESENT,
        )
        self.assertIs(result.portal_verification_required, True)
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PRESENT
        )
        self.assertIs(result.authority_verification_required, True)
        self.assertEqual(result.stated_due_date_fact_ids, ["F-005"])
        self.assertEqual(
            result.parsed_stated_due_dates, [date(2026, 9, 17)]
        )
        self.assertEqual(result.unparsed_stated_due_date_fact_ids, ["F-006"])
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )
        self.assertEqual(result.hearing_fact_ids, ["F-007"])
        self.assertEqual(result.requested_document_fact_ids, ["F-008"])
        self.assertEqual(result.referenced_annexure_fact_ids, ["F-009"])

    def test_no_forbidden_validity_fields(self):
        # §18.13: "Do NOT create: notice_valid, notice_invalid,
        # jurisdiction_valid, officer_competent" — plus the task's
        # additional forbidden names.
        field_names = {f.name for f in fields(PreflightResult)}
        for name in (
            "notice_valid",
            "notice_invalid",
            "jurisdiction_valid",
            "officer_competent",
            "warning_text",
            "legal_conclusion",
        ):
            self.assertNotIn(name, field_names, name)


class ArithmeticOperandTests(unittest.TestCase):
    """§18.18: provenance-reference fields only."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ArithmeticOperand))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ArithmeticOperand)],
            ["source_fact_id", "value_text"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ArithmeticOperand)), 2)

    def test_supplied_values_preserved(self):
        operand = ArithmeticOperand(
            source_fact_id="F-003", value_text="Rs. 10,00,000"
        )
        self.assertEqual(operand.source_fact_id, "F-003")
        self.assertEqual(operand.value_text, "Rs. 10,00,000")


class ArithmeticRequestTests(unittest.TestCase):
    """§18.19: calculation type + two operands, nothing else."""

    def make_request(self) -> ArithmeticRequest:
        return ArithmeticRequest(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            left_operand=ArithmeticOperand("F-003", "Rs. 10,00,000"),
            right_operand=ArithmeticOperand("F-004", "Rs. 8,50,000"),
        )

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ArithmeticRequest))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ArithmeticRequest)],
            ["calculation_type", "left_operand", "right_operand"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ArithmeticRequest)), 3)

    def test_supplied_values_preserved(self):
        request = self.make_request()
        self.assertIs(
            request.calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        self.assertEqual(request.left_operand.source_fact_id, "F-003")
        self.assertEqual(request.left_operand.value_text, "Rs. 10,00,000")
        self.assertEqual(request.right_operand.source_fact_id, "F-004")
        self.assertEqual(request.right_operand.value_text, "Rs. 8,50,000")


class ArithmeticResultTests(unittest.TestCase):
    """§18.21: the eight-field contract; NOT an ExtractedFact."""

    def make_result(self) -> ArithmeticResult:
        return ArithmeticResult(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            status=ArithmeticStatus.MISMATCH,
            source_fact_ids=["F-003", "F-004"],
            operand_values=[Decimal("1000000"), Decimal("150000")],
            result=Decimal("850000"),
            formula="F-003 − F-004",
        )

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ArithmeticResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ArithmeticResult)],
            EXPECTED_ARITHMETIC_RESULT_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ArithmeticResult)), 8)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(ArithmeticResult)}
        self.assertIs(
            by_name["calculation_type"].type, ArithmeticCalculationType
        )
        self.assertIs(by_name["status"].type, ArithmeticStatus)
        self.assertEqual(by_name["source_fact_ids"].type, List[str])
        self.assertEqual(by_name["operand_values"].type, List[Decimal])
        self.assertEqual(by_name["result"].type, Optional[Decimal])
        self.assertIs(by_name["formula"].type, str)
        self.assertIs(by_name["currency"].type, str)
        self.assertIs(by_name["allowed_in_draft"].type, DraftPermission)

    def test_currency_default_is_inr(self):
        result = self.make_result()
        self.assertEqual(result.currency, "INR")

    def test_allowed_in_draft_default_is_conditional(self):
        result = self.make_result()
        self.assertIs(result.allowed_in_draft, DraftPermission.CONDITIONAL)

    def test_decimal_operands_and_result_preserved_exactly(self):
        # Decimal is stored as supplied — no float conversion, no rounding.
        result = ArithmeticResult(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            status=ArithmeticStatus.MISMATCH,
            source_fact_ids=["F-003", "F-004"],
            operand_values=[Decimal("1.50"), Decimal("1000000.25")],
            result=Decimal("999998.75"),
            formula="F-003 − F-004",
        )
        self.assertEqual(result.operand_values[0], Decimal("1.50"))
        self.assertEqual(str(result.operand_values[0]), "1.50")  # exact
        self.assertEqual(result.operand_values[1], Decimal("1000000.25"))
        self.assertEqual(result.result, Decimal("999998.75"))
        self.assertIsInstance(result.operand_values[0], Decimal)
        self.assertIsInstance(result.result, Decimal)

    def test_result_accepts_none(self):
        # §18.22: INSUFFICIENT_DATA yields result = None.
        result = ArithmeticResult(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            status=ArithmeticStatus.INSUFFICIENT_DATA,
            source_fact_ids=[],
            operand_values=[],
            result=None,
            formula="",
        )
        self.assertIsNone(result.result)

    def test_has_no_fact_id_field(self):
        # §18.21: "Do NOT assign F-xxx fact IDs to ArithmeticResult."
        self.assertNotIn(
            "fact_id", [f.name for f in fields(ArithmeticResult)]
        )

    def test_has_no_extracted_fact_fields(self):
        # §18.21: no FactStatus, source_text or source_page — the status
        # field present here is ArithmeticStatus, not FactStatus.
        field_names = {f.name for f in fields(ArithmeticResult)}
        self.assertNotIn("source_text", field_names)
        self.assertNotIn("source_page", field_names)
        by_name = {f.name: f for f in fields(ArithmeticResult)}
        self.assertIs(by_name["status"].type, ArithmeticStatus)
        self.assertIsNot(by_name["status"].type, FactStatus)

    def test_not_subclass_of_extracted_fact(self):
        # §18.21: "semantically INFERRED but it is NOT an ExtractedFact."
        self.assertFalse(issubclass(ArithmeticResult, ExtractedFact))


class PurityAndBackwardCompatibilityTests(unittest.TestCase):
    """domain/models.py stays stdlib-only; earlier contracts unchanged."""

    ALLOWED_IMPORT_ROOTS = {
        "enum", "dataclasses", "typing", "datetime", "decimal",
    }

    def test_models_module_imports_only_stdlib(self):
        import domain.models as models_module

        source = (
            pathlib.Path(models_module.__file__)
            .read_text(encoding="utf-8")
        )
        roots = set()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                module_name = stripped.split()[1]
                if module_name.startswith("."):
                    continue
                roots.add(module_name.split(".")[0])
            elif stripped.startswith("import "):
                roots.add(stripped.split()[1].split(".")[0])
        self.assertTrue(
            roots <= self.ALLOWED_IMPORT_ROOTS,
            f"unexpected import roots {sorted(roots)}",
        )

    def test_fact_extraction_result_contract_unchanged(self):
        # §18.2 as implemented in Step 6.3: same three fields, same order,
        # same default.
        self.assertEqual(
            [f.name for f in fields(FactExtractionResult)],
            ["facts", "status", "rejected_item_count"],
        )
        result = FactExtractionResult(
            facts=[], status=FactExtractionStatus.SUCCESS
        )
        self.assertEqual(result.rejected_item_count, 0)

    def test_extracted_fact_contract_unchanged(self):
        # §17.2: six original fields plus the additive fact_type, in order.
        self.assertEqual(
            [f.name for f in fields(ExtractedFact)],
            [
                "fact_id",
                "claim",
                "status",
                "source_text",
                "source_page",
                "allowed_in_draft",
                "fact_type",
            ],
        )
        fact = ExtractedFact("F-001", "claim", FactStatus.CONFIRMED)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)

    def test_legacy_constructors_still_work(self):
        # Pre-Step-6.1 positional/keyword forms remain compatible (§17.2).
        fact = ExtractedFact("F-003", "GSTIN stated", FactStatus.CONFIRMED)
        self.assertIsNone(fact.source_text)
        self.assertIsNone(fact.source_page)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)


if __name__ == "__main__":
    unittest.main()
