"""Unit tests for the fact domain models.

Verifies the v1.1-approved FactType enum and the additive, backward
compatible ExtractedFact fields (ARCHITECTURE_SPEC_v1_1 §17.1, §17.2,
§17.24, plus the Step 6.4 amendments §19.1–19.3):

  - FactType imports as an Enum with exactly the 22 members (the 21 §17.1
    members plus the §19.1 DOCUMENT_DETAIL), in spec order, with the
    lowercase spec values;
  - FactRole imports as an Enum with exactly the 22 §19.2 members, in
    spec order, with the lowercase spec values;
  - ExtractedFact keeps its six original fields unchanged (names, order,
    types, defaults) and gains the additive fields fact_type then
    fact_role, with fact_role last and defaulting to FactRole.NONE;
  - explicit fact_type / fact_role construction preserves the supplied
    values;
  - legacy-style construction (keyword and positional, omitting
    fact_type and/or fact_role) still works with the documented defaults;
  - the existing allowed_in_draft default remains
    DraftPermission.CONDITIONAL;
  - FactExtractionStatus adds exactly the four §18.1 members, in order,
    with the lowercase spec values;
  - FactExtractionResult is the §18.2 dataclass with exactly the fields
    facts / status / rejected_item_count and no extras;
  - domain/models.py remains standard-library-only.

Pure contract tests only. No Fact Engine behavior is implemented or
simulated here.

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
    DocumentPageText,
    DraftPermission,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    SourceTextOrigin,
    SourceVerificationStatus,
)

# Exact members, in §17.1 spec order (plus the §19.1 DOCUMENT_DETAIL in
# its amended spec position), with the repository enum-value convention
# (lowercase member names).
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
    "DOCUMENT_DETAIL": "document_detail",
    "OTHER_NOTICE_FACT": "other_notice_fact",
}

# Exact members, in §19.2 spec order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_FACT_ROLES = {
    "NONE": "none",
    "GSTR3B_ITC_CLAIMED_AMOUNT": "gstr3b_itc_claimed_amount",
    "GSTR2B_ITC_REFLECTED_AMOUNT": "gstr2b_itc_reflected_amount",
    "INTEREST_PROPOSED_AMOUNT": "interest_proposed_amount",
    "GSTR1_LIABILITY_DECLARED_AMOUNT": "gstr1_liability_declared_amount",
    "GSTR3B_LIABILITY_DISCHARGED_AMOUNT": "gstr3b_liability_discharged_amount",
    "RCM_CATEGORY_ALLEGED": "rcm_category_alleged",
    "RCM_VALUE_ALLEGED_AMOUNT": "rcm_value_alleged_amount",
    "RCM_TAX_ALLEGED_AMOUNT": "rcm_tax_alleged_amount",
    "FRAUD_BASIS_ALLEGED": "fraud_basis_alleged",
    "DEPARTMENT_ALLEGED_AMOUNT": "department_alleged_amount",
    "FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT": (
        "fraud_penalty_proposed_alleged_amount"
    ),
    "LIMITATION_BASIS": "limitation_basis",
    "GOODS_DESCRIPTION": "goods_description",
    "VEHICLE_NUMBER": "vehicle_number",
    "DETENTION_OR_SEIZURE_DATE": "detention_or_seizure_date",
    "SECTION129_NOTICE_OR_SERVICE_DATE": "section129_notice_or_service_date",
    "SEC129_PENALTY_PROPOSED_AMOUNT": "sec129_penalty_proposed_amount",
    "GOODS_VALUE_OR_TAX_PAYABLE": "goods_value_or_tax_payable",
    "OWNER_CAME_FORWARD_STATUS": "owner_came_forward_status",
    "EXPLICIT_PROCEDURAL_DATE": "explicit_procedural_date",
    "ORDER_DATE_OR_ENFORCEMENT_STATUS": "order_date_or_enforcement_status",
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
    """FactType: imports, Enum subclass, exact §17.1 + §19.1 members/values."""

    def test_fact_type_imports_and_is_enum(self):
        self.assertTrue(issubclass(FactType, Enum))

    def test_fact_type_members_and_values_exact(self):
        # Order + names + values pinned in one shot: exactly the §17.1
        # members plus the §19.1 DOCUMENT_DETAIL, no extras, no renames,
        # no value drift.
        self.assertEqual(
            [(member.name, member.value) for member in FactType],
            list(EXPECTED_FACT_TYPES.items()),
        )

    def test_fact_type_has_exactly_22_members(self):
        self.assertEqual(len(FactType), 22)

    def test_fact_type_contains_document_detail(self):
        self.assertIs(FactType.DOCUMENT_DETAIL.value, "document_detail")

    def test_fact_type_member_names_exact(self):
        self.assertEqual(
            {member.name for member in FactType},
            set(EXPECTED_FACT_TYPES),
        )

    def test_fact_type_values_are_lowercase_member_names(self):
        for member in FactType:
            self.assertEqual(member.value, member.name.lower(), member.name)


class FactRoleContractTests(unittest.TestCase):
    """FactRole: imports, Enum subclass, exact §19.2 members and values."""

    def test_fact_role_imports_and_is_enum(self):
        self.assertTrue(issubclass(FactRole, Enum))

    def test_fact_role_has_exactly_22_members(self):
        self.assertEqual(len(FactRole), 22)

    def test_fact_role_members_and_values_exact(self):
        # Order + names + values pinned in one shot: exactly the §19.2
        # members, no extras, no renames, no value drift.
        self.assertEqual(
            [(member.name, member.value) for member in FactRole],
            list(EXPECTED_FACT_ROLES.items()),
        )

    def test_fact_role_member_names_exact(self):
        self.assertEqual(
            {member.name for member in FactRole},
            set(EXPECTED_FACT_ROLES),
        )

    def test_no_unexpected_role(self):
        for member in FactRole:
            self.assertIn(member.name, EXPECTED_FACT_ROLES)

    def test_fact_role_values_are_lowercase_member_names(self):
        for member in FactRole:
            self.assertEqual(member.value, member.name.lower(), member.name)


class ExtractedFactContractTests(unittest.TestCase):
    """ExtractedFact: six original fields + additive fact_type, fact_role."""

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

    def test_extracted_fact_final_field_order_exact(self):
        # §17.2 + §19.3 conceptual final contract: fact_role last, after
        # fact_type, after the six original fields.
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
                "fact_role",
                "source_origin",
                "source_verification",
            ],
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
        self.assertIs(by_name["fact_role"].type, FactRole)
        self.assertIs(by_name["source_origin"].type, SourceTextOrigin)
        self.assertIs(
            by_name["source_verification"].type,
            SourceVerificationStatus,
        )

    def test_fact_role_defaults_to_none(self):
        fact = ExtractedFact("F-010", "claim", FactStatus.CONFIRMED)
        self.assertIs(fact.fact_role, FactRole.NONE)
        self.assertIs(fact.source_origin, SourceTextOrigin.EMBEDDED)
        self.assertIs(
            fact.source_verification,
            SourceVerificationStatus.VERIFIED,
        )

    def test_legacy_seven_field_construction_still_works(self):
        # The Step 6.1 seven-positional form must still work and default
        # fact_role to NONE.
        fact = ExtractedFact(
            "F-011",
            "Officer designation stated",
            FactStatus.CONFIRMED,
            "Joint Commissioner, CGST",
            2,
            DraftPermission.YES,
            FactType.AUTHORITY_DESIGNATION,
        )
        self.assertEqual(fact.fact_id, "F-011")
        self.assertIs(fact.fact_type, FactType.AUTHORITY_DESIGNATION)
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_keyword_construction_without_fact_role_works(self):
        fact = ExtractedFact(
            fact_id="F-012",
            claim="Notice is dated 17-08-2026",
            status=FactStatus.CONFIRMED,
            source_text="Date: 17-08-2026",
            fact_type=FactType.NOTICE_DATE,
        )
        self.assertIs(fact.fact_type, FactType.NOTICE_DATE)
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_supplied_fact_role_is_preserved(self):
        fact = ExtractedFact(
            fact_id="F-013",
            claim="ITC in GSTR-3B is Rs. 10,00,000",
            status=FactStatus.CONFIRMED,
            source_text="ITC in GSTR-3B: Rs. 10,00,000",
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )
        self.assertIs(fact.fact_type, FactType.STATED_AMOUNT)
        self.assertIs(fact.fact_role, FactRole.GSTR3B_ITC_CLAIMED_AMOUNT)

    def test_document_detail_fact_constructs(self):
        fact = ExtractedFact(
            fact_id="F-014",
            claim="Goods description stated as 100 bags of cement",
            status=FactStatus.CONFIRMED,
            source_text="Goods: 100 bags of cement",
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.GOODS_DESCRIPTION,
        )
        self.assertIs(fact.fact_type, FactType.DOCUMENT_DETAIL)
        self.assertIs(fact.fact_role, FactRole.GOODS_DESCRIPTION)

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
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_legacy_keyword_construction_without_fact_type(self):
        fact = ExtractedFact(
            fact_id="F-002",
            claim="Notice is dated 17-08-2026",
            status=FactStatus.CONFIRMED,
            source_text="Date: 17-08-2026",
        )
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_legacy_partial_positional_construction(self):
        # The original minimal positional form (3 args) must still work.
        fact = ExtractedFact("F-003", "GSTIN stated", FactStatus.CONFIRMED)
        self.assertIsNone(fact.source_text)
        self.assertIsNone(fact.source_page)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)
        self.assertIs(fact.fact_role, FactRole.NONE)

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
        self.assertIs(fact.fact_role, FactRole.NONE)

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
        self.assertIs(fact.fact_role, FactRole.NONE)


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

    ALLOWED_IMPORT_ROOTS = {"enum", "dataclasses", "typing", "datetime", "decimal"}

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



class Phase3SourceTrustModelTests(unittest.TestCase):
    def test_source_origin_members_exact(self):
        self.assertEqual(
            [(member.name, member.value) for member in SourceTextOrigin],
            [
                ("EMBEDDED", "embedded"),
                ("OCR", "ocr"),
                ("MIXED", "mixed"),
                ("UNKNOWN", "unknown"),
            ],
        )

    def test_source_verification_members_exact(self):
        self.assertEqual(
            [
                (member.name, member.value)
                for member in SourceVerificationStatus
            ],
            [
                ("VERIFIED", "verified"),
                ("REQUIRES_VERIFICATION", "requires_verification"),
            ],
        )

    def test_document_page_text_contract(self):
        self.assertTrue(is_dataclass(DocumentPageText))
        self.assertEqual(
            [f.name for f in fields(DocumentPageText)],
            [
                "page_number",
                "text",
                "origin",
                "verification",
                "ocr_language",
                "ocr_dpi",
            ],
        )

    def test_ocr_page_requires_verification(self):
        page = DocumentPageText(
            page_number=1,
            text="recognized",
            origin=SourceTextOrigin.OCR,
            verification=SourceVerificationStatus.REQUIRES_VERIFICATION,
            ocr_language="eng",
            ocr_dpi=300,
        )
        self.assertIs(page.origin, SourceTextOrigin.OCR)
        self.assertIs(
            page.verification,
            SourceVerificationStatus.REQUIRES_VERIFICATION,
        )
