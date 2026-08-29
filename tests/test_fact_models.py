"""Unit tests for Phase 2 Step 6.1 fact domain models.

Verifies the v1.1-approved FactType enum and the additive, backward
compatible ExtractedFact.fact_type field (ARCHITECTURE_SPEC_v1_1 §17.1,
§17.2, §17.24):

  - FactType imports as an Enum with exactly the 21 §17.1 members, in spec
    order, with the lowercase spec values;
  - ExtractedFact keeps its six original fields unchanged (names, order,
    types, defaults) and gains exactly one additive field: fact_type;
  - explicit fact_type construction preserves the supplied value;
  - legacy-style construction (keyword and positional, omitting fact_type)
    still works and defaults to FactType.OTHER_NOTICE_FACT;
  - the existing allowed_in_draft default remains
    DraftPermission.CONDITIONAL;
  - FactExtractionStatus adds exactly the four §18.1 members, in order,
    with the lowercase spec values;
  - FactExtractionResult is the §18.2 dataclass with exactly the fields
    facts / status / rejected_item_count and no extras;
  - domain/models.py remains standard-library-only.

Pure contract tests only. No Fact Engine behavior is implemented or
simulated here — the Fact Engine does not exist yet (Step 6.2).

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_fact_models.py -v
No pytest, no external dependencies, no LLM calls, no network.
"""

import pathlib
import unittest
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import List, Optional

from domain.models import (
    DraftPermission,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactStatus,
    FactType,
)

# Exact members, in §17.1 spec order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_FACT_TYPES = {
    "NOTICE_REFERENCE": "notice_reference",
    "NOTICE_DATE": "notice_date",
    "TAXPAYER_NAME": "taxpayer_name",
    "GSTIN": "gstin",
    "AUTHORITY_NAME": "authority_name",
    "AUTHORITY_DESIGNATION": "authority_designation",
    "AUTHORITY_OFFICE": "authority_office",
    "JURISDICTION_TEXT": "jurisdiction_text",
    "RFN": "rfn",
    "DIN": "din",
    "STATUTORY_SECTION": "statutory_section",
    "STATUTORY_RULE": "statutory_rule",
    "STATUTORY_NOTIFICATION": "statutory_notification",
    "TAX_PERIOD": "tax_period",
    "STATED_DUE_DATE": "stated_due_date",
    "HEARING_DETAILS": "hearing_details",
    "STATED_AMOUNT": "stated_amount",
    "DEPARTMENT_ALLEGATION": "department_allegation",
    "REQUESTED_DOCUMENT": "requested_document",
    "REFERENCED_ANNEXURE": "referenced_annexure",
    "OTHER_NOTICE_FACT": "other_notice_fact",
}

# The exact pre-Step-6.1 ExtractedFact field contract, unchanged (§17.2).
EXPECTED_ORIGINAL_FIELDS = [
    "fact_id",
    "claim",
    "status",
    "source_text",
    "source_page",
    "allowed_in_draft",
]


class FactTypeContractTests(unittest.TestCase):
    """FactType: imports, Enum subclass, exact §17.1 members and values."""

    def test_fact_type_imports_and_is_enum(self):
        self.assertTrue(issubclass(FactType, Enum))

    def test_fact_type_members_and_values_exact(self):
        # Order + names + values pinned in one shot: exactly the §17.1
        # members, no extras, no renames, no value drift.
        self.assertEqual(
            [(member.name, member.value) for member in FactType],
            list(EXPECTED_FACT_TYPES.items()),
        )

    def test_fact_type_has_exactly_21_members(self):
        self.assertEqual(len(FactType), 21)

    def test_fact_type_member_names_exact(self):
        self.assertEqual(
            {member.name for member in FactType},
            set(EXPECTED_FACT_TYPES),
        )

    def test_fact_type_values_are_lowercase_member_names(self):
        for member in FactType:
            self.assertEqual(member.value, member.name.lower(), member.name)


class ExtractedFactContractTests(unittest.TestCase):
    """ExtractedFact: six original fields unchanged + one additive field."""

    def test_extracted_fact_is_dataclass(self):
        self.assertTrue(is_dataclass(ExtractedFact))

    def test_original_field_names_and_order_unchanged(self):
        self.assertEqual(
            [f.name for f in fields(ExtractedFact)][:6],
            EXPECTED_ORIGINAL_FIELDS,
        )

    def test_extracted_fact_exposes_fact_type(self):
        self.assertIn(
            "fact_type", [f.name for f in fields(ExtractedFact)]
        )

    def test_extracted_fact_field_contract_exact(self):
        by_name = {f.name: f for f in fields(ExtractedFact)}
        self.assertIs(by_name["fact_id"].type, str)
        self.assertIs(by_name["claim"].type, str)
        self.assertIs(by_name["status"].type, FactStatus)
        self.assertIs(by_name["source_text"].type, Optional[str])
        self.assertEqual(by_name["source_page"].type, Optional[int])
        self.assertIs(by_name["allowed_in_draft"].type, DraftPermission)
        self.assertIs(by_name["fact_type"].type, FactType)

    def test_explicit_fact_type_construction_is_preserved(self):
        fact = ExtractedFact(
            fact_id="F-001",
            claim="Notice reference is ZD2608260012345",
            status=FactStatus.CONFIRMED,
            source_text="Reference No. ZD2608260012345",
            source_page=1,
            allowed_in_draft=DraftPermission.YES,
            fact_type=FactType.NOTICE_REFERENCE,
        )
        self.assertIs(fact.fact_type, FactType.NOTICE_REFERENCE)

    def test_legacy_keyword_construction_without_fact_type(self):
        fact = ExtractedFact(
            fact_id="F-002",
            claim="Notice is dated 17-08-2026",
            status=FactStatus.CONFIRMED,
            source_text="Date: 17-08-2026",
        )
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)

    def test_legacy_partial_positional_construction(self):
        # The original minimal positional form (3 args) must still work.
        fact = ExtractedFact("F-003", "GSTIN stated", FactStatus.CONFIRMED)
        self.assertIsNone(fact.source_text)
        self.assertIsNone(fact.source_page)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)

    def test_legacy_full_positional_construction(self):
        # The original six-positional form must still work and keep the
        # pre-Step-6.1 meaning of every position.
        fact = ExtractedFact(
            "F-004",
            "Officer designation stated",
            FactStatus.CONFIRMED,
            "Joint Commissioner, CGST",
            2,
            DraftPermission.YES,
        )
        self.assertEqual(fact.fact_id, "F-004")
        self.assertEqual(fact.claim, "Officer designation stated")
        self.assertIs(fact.status, FactStatus.CONFIRMED)
        self.assertEqual(fact.source_text, "Joint Commissioner, CGST")
        self.assertEqual(fact.source_page, 2)
        self.assertIs(fact.allowed_in_draft, DraftPermission.YES)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)

    def test_allowed_in_draft_default_unchanged(self):
        fact = ExtractedFact("F-005", "claim", FactStatus.CONFIRMED)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)

    def test_existing_field_defaults_unchanged(self):
        fact = ExtractedFact("F-006", "claim", FactStatus.CONFIRMED)
        self.assertIsNone(fact.source_text)
        self.assertIsNone(fact.source_page)

    def test_field_values_preserved_under_full_construction(self):
        fact = ExtractedFact(
            fact_id="F-007",
            claim="Department alleges ineligible ITC of Rs. 5,00,000",
            status=FactStatus.ALLEGED,
            source_text="ineligible ITC of Rs. 5,00,000 was availed",
            source_page=None,
            allowed_in_draft=DraftPermission.CONDITIONAL,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
        )
        self.assertEqual(fact.fact_id, "F-007")
        self.assertIs(fact.status, FactStatus.ALLEGED)
        self.assertIsNone(fact.source_page)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.DEPARTMENT_ALLEGATION)


# Exact members, in §18.1 spec order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_FACT_EXTRACTION_STATUSES = {
    "SUCCESS": "success",
    "PARTIAL": "partial",
    "FAILED": "failed",
    "NO_INPUT": "no_input",
}


class FactExtractionStatusContractTests(unittest.TestCase):
    """FactExtractionStatus: imports, Enum subclass, exact §18.1 members."""

    def test_fact_extraction_status_imports_and_is_enum(self):
        self.assertTrue(issubclass(FactExtractionStatus, Enum))

    def test_fact_extraction_status_members_and_values_exact(self):
        # Order + names + values pinned in one shot: exactly the §18.1
        # members, no extras, no renames, no value drift.
        self.assertEqual(
            [(member.name, member.value) for member in FactExtractionStatus],
            list(EXPECTED_FACT_EXTRACTION_STATUSES.items()),
        )

    def test_fact_extraction_status_has_exactly_4_members(self):
        self.assertEqual(len(FactExtractionStatus), 4)

    def test_fact_extraction_status_values_are_lowercase_member_names(self):
        for member in FactExtractionStatus:
            self.assertEqual(member.value, member.name.lower(), member.name)


class FactExtractionResultContractTests(unittest.TestCase):
    """FactExtractionResult: the exact §18.2 dataclass field contract."""

    EXPECTED_FIELDS = ["facts", "status", "rejected_item_count"]

    def test_fact_extraction_result_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(FactExtractionResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(FactExtractionResult)],
            self.EXPECTED_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(FactExtractionResult)), 3)

    def test_field_types_exact(self):
        by_name = {f.name: f for f in fields(FactExtractionResult)}
        self.assertEqual(by_name["facts"].type, List[ExtractedFact])
        self.assertIs(by_name["status"].type, FactExtractionStatus)
        self.assertIs(by_name["rejected_item_count"].type, int)

    def test_rejected_item_count_defaults_to_zero(self):
        result = FactExtractionResult(
            facts=[], status=FactExtractionStatus.SUCCESS
        )
        self.assertEqual(result.rejected_item_count, 0)

    def test_supplied_values_preserved(self):
        fact = ExtractedFact("F-001", "claim", FactStatus.CONFIRMED)
        result = FactExtractionResult(
            facts=[fact],
            status=FactExtractionStatus.PARTIAL,
            rejected_item_count=2,
        )
        self.assertEqual(result.facts, [fact])
        self.assertIs(result.status, FactExtractionStatus.PARTIAL)
        self.assertEqual(result.rejected_item_count, 2)


class StdlibPurityTests(unittest.TestCase):
    """domain/models.py remains standard-library-only (§17.24, AGENTS.md)."""

    ALLOWED_IMPORT_ROOTS = {"enum", "dataclasses", "typing", "datetime"}

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


if __name__ == "__main__":
    unittest.main()
