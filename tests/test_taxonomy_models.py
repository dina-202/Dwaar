"""Unit tests for Phase 2 Step 2.5 taxonomy/classification domain models.

Verifies the seven v1.1-approved enums and the NoticeClassification dataclass
(ARCHITECTURE_SPEC_v1_1 §5, §6.2, §6.3, §6.7, §13 Step 2.5):

  - all seven new enums import and contain exactly the spec-defined members,
    in spec order, with spec-conventional values;
  - NoticeClassification imports, has exactly the §5.4 fields, constructs,
    and preserves supplied values;
  - the Section-130-only Phase 2 representation is expressible (§3.9);
  - existing Step 1 enums/dataclasses still import and DeadlineResult still
    constructs under its existing contract.

Pure contract tests: construction and value preservation only.
No classifier logic is implemented or simulated here.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_taxonomy_models.py -v
No pytest, no external dependencies, no LLM calls, no network.
"""

import unittest
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum

from domain.models import (
    # Step 2.5 enums
    ArithmeticStatus,
    AuthorityDetailsStatus,
    ClassificationConfidence,
    CommunicationIdentifierStatus,
    NoticeFamily,
    NoticeForm,
    SupportLevel,
    # Step 2.5 dataclass
    NoticeClassification,
    # Existing Step 1 enums
    DeadlineConfidence,
    DeadlineStatus,
    DraftPermission,
    FactStatus,
    HearingStatus,
    IssueSeverity,
    ProceedingType,
    ValidationStatus,
    # Existing Step 1 dataclasses
    DeadlineResult,
    EvidenceGap,
    ExtractedFact,
    NoticeAnalysis,
    PotentialDefence,
    ValidationCheck,
    ValidationResult,
)

# Exact members, in spec order, with values per the repo convention
# (lowercase member names), as defined in ARCHITECTURE_SPEC_v1_1 §5.1, §5.2,
# §5.3, §5.5, §6.2, §6.3, §6.7.
EXPECTED_ENUMS = {
    "NoticeFamily": {
        "RETURN_COMPLIANCE": "return_compliance",
        "REGISTRATION": "registration",
        "COMPOSITION": "composition",
        "GST_PRACTITIONER": "gst_practitioner",
        "REFUND": "refund",
        "ASSESSMENT_SCRUTINY": "assessment_scrutiny",
        "AUDIT": "audit",
        "DEMAND_ADJUDICATION": "demand_adjudication",
        "ENFORCEMENT": "enforcement",
        "REVISION": "revision",
        "UNKNOWN": "unknown",
    },
    "NoticeForm": {
        "GSTR_3A": "gstr_3a",
        "CMP_05": "cmp_05",
        "REG_03": "reg_03",
        "REG_17": "reg_17",
        "REG_23": "reg_23",
        "PCT_03": "pct_03",
        "RFD_08": "rfd_08",
        "ASMT_02": "asmt_02",
        "ASMT_10": "asmt_10",
        "ASMT_14": "asmt_14",
        "ADT_01": "adt_01",
        "RVN_01": "rvn_01",
        "DRC_01A": "drc_01a",
        "DRC_01": "drc_01",
        "DRC_01B": "drc_01b",
        "DRC_01C": "drc_01c",
        "MOV_SERIES": "mov_series",
        "UNKNOWN": "unknown",
    },
    "SupportLevel": {
        "DEEP_WORKFLOW": "deep_workflow",
        "TRIAGE_ONLY": "triage_only",
        "UNKNOWN": "unknown",
    },
    "ClassificationConfidence": {
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
        "UNKNOWN": "unknown",
    },
    "CommunicationIdentifierStatus": {
        "RFN_PRESENT": "rfn_present",
        "DIN_PRESENT": "din_present",
        "BOTH_PRESENT": "both_present",
        "NEITHER_FOUND": "neither_found",
        "UNKNOWN": "unknown",
    },
    "AuthorityDetailsStatus": {
        "PRESENT": "present",
        "PARTIAL": "partial",
        "MISSING": "missing",
        "UNKNOWN": "unknown",
    },
    "ArithmeticStatus": {
        "PASS": "pass",
        "MISMATCH": "mismatch",
        "INSUFFICIENT_DATA": "insufficient_data",
    },
}


class NewEnumImportTests(unittest.TestCase):
    """All seven Step 2.5 enums import as Enum subclasses."""

    def test_all_seven_new_enums_import(self):
        for cls in (
            NoticeFamily,
            NoticeForm,
            SupportLevel,
            ClassificationConfidence,
            CommunicationIdentifierStatus,
            AuthorityDetailsStatus,
            ArithmeticStatus,
        ):
            self.assertTrue(issubclass(cls, Enum), cls.__name__)


class EnumExactMemberTests(unittest.TestCase):
    """Each new enum has exactly the spec-defined members, order, and values."""

    def assert_enum_exact(self, cls, expected):
        self.assertEqual(
            [(member.name, member.value) for member in cls],
            list(expected.items()),
            cls.__name__,
        )

    def test_notice_family_members_exact(self):
        self.assert_enum_exact(NoticeFamily, EXPECTED_ENUMS["NoticeFamily"])

    def test_notice_form_members_exact(self):
        self.assert_enum_exact(NoticeForm, EXPECTED_ENUMS["NoticeForm"])

    def test_support_level_members_exact(self):
        self.assert_enum_exact(SupportLevel, EXPECTED_ENUMS["SupportLevel"])

    def test_classification_confidence_members_exact(self):
        self.assert_enum_exact(
            ClassificationConfidence, EXPECTED_ENUMS["ClassificationConfidence"]
        )

    def test_communication_identifier_status_members_exact(self):
        self.assert_enum_exact(
            CommunicationIdentifierStatus,
            EXPECTED_ENUMS["CommunicationIdentifierStatus"],
        )

    def test_authority_details_status_members_exact(self):
        self.assert_enum_exact(
            AuthorityDetailsStatus, EXPECTED_ENUMS["AuthorityDetailsStatus"]
        )

    def test_arithmetic_status_members_exact(self):
        self.assert_enum_exact(ArithmeticStatus, EXPECTED_ENUMS["ArithmeticStatus"])

    def test_classification_confidence_is_categorical_only(self):
        # HIGH/MEDIUM/LOW/UNKNOWN — no numeric/percentage members.
        self.assertEqual(
            {member.name for member in ClassificationConfidence},
            {"HIGH", "MEDIUM", "LOW", "UNKNOWN"},
        )

    def test_no_section_130_notice_form_member(self):
        # §3.9: Section 130 is NOT a NoticeForm registry entry.
        self.assertFalse(hasattr(NoticeForm, "SECTION_130"))

    def test_no_portal_verification_member_in_communication_identifier_status(self):
        # §6.2: portal verification is a separate boolean, not a member.
        self.assertFalse(
            hasattr(CommunicationIdentifierStatus, "REQUIRES_PORTAL_VERIFICATION")
        )

    def test_authority_details_status_has_no_competence_members(self):
        # §6.3: extraction completeness only — no jurisdiction conclusions.
        self.assertEqual(
            {member.name for member in AuthorityDetailsStatus},
            {"PRESENT", "PARTIAL", "MISSING", "UNKNOWN"},
        )


class NoticeClassificationTests(unittest.TestCase):
    """The §5.4 dataclass contract: fields, construction, value preservation."""

    def test_notice_classification_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(NoticeClassification))

    def test_notice_classification_field_contract(self):
        expected_fields = [
            "notice_family",
            "notice_form",
            "proceeding_type",
            "support_level",
            "confidence",
            "classification_reasons",
        ]
        self.assertEqual(
            [f.name for f in fields(NoticeClassification)], expected_fields
        )
        expected_enum_types = {
            "notice_family": NoticeFamily,
            "notice_form": NoticeForm,
            "proceeding_type": ProceedingType,
            "support_level": SupportLevel,
            "confidence": ClassificationConfidence,
        }
        for f in fields(NoticeClassification):
            if f.name in expected_enum_types:
                self.assertIs(f.type, expected_enum_types[f.name], f.name)

    def test_construction_preserves_supplied_values(self):
        reasons = ['form marker "DRC-01" found']
        result = NoticeClassification(
            notice_family=NoticeFamily.DEMAND_ADJUDICATION,
            notice_form=NoticeForm.DRC_01,
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            support_level=SupportLevel.TRIAGE_ONLY,
            confidence=ClassificationConfidence.HIGH,
            classification_reasons=reasons,
        )
        self.assertIs(result.notice_family, NoticeFamily.DEMAND_ADJUDICATION)
        self.assertIs(result.notice_form, NoticeForm.DRC_01)
        self.assertIs(result.proceeding_type, ProceedingType.GST_SEC73_GENERAL)
        self.assertIs(result.support_level, SupportLevel.TRIAGE_ONLY)
        self.assertIs(result.confidence, ClassificationConfidence.HIGH)
        self.assertEqual(result.classification_reasons, reasons)

    def test_section_130_only_phase2_representation(self):
        # §3.9: a Section-130-only proceeding classifies exactly as
        # NoticeForm.UNKNOWN / NoticeFamily.ENFORCEMENT /
        # ProceedingType.UNKNOWN / SupportLevel.TRIAGE_ONLY.
        result = NoticeClassification(
            notice_family=NoticeFamily.ENFORCEMENT,
            notice_form=NoticeForm.UNKNOWN,
            proceeding_type=ProceedingType.UNKNOWN,
            support_level=SupportLevel.TRIAGE_ONLY,
            confidence=ClassificationConfidence.UNKNOWN,
            classification_reasons=[],
        )
        self.assertIs(result.notice_form, NoticeForm.UNKNOWN)
        self.assertIs(result.notice_family, NoticeFamily.ENFORCEMENT)
        self.assertIs(result.proceeding_type, ProceedingType.UNKNOWN)
        self.assertIs(result.support_level, SupportLevel.TRIAGE_ONLY)


class ExistingStep1ContractTests(unittest.TestCase):
    """Step 1 contracts remain importable and constructible, unchanged."""

    def test_existing_step1_enums_still_import(self):
        for cls in (
            ProceedingType,
            FactStatus,
            DraftPermission,
            DeadlineConfidence,
            DeadlineStatus,
            HearingStatus,
            IssueSeverity,
            ValidationStatus,
        ):
            self.assertTrue(issubclass(cls, Enum), cls.__name__)

    def test_existing_step1_dataclasses_still_import(self):
        for cls in (
            ExtractedFact,
            DeadlineResult,
            EvidenceGap,
            PotentialDefence,
            ValidationCheck,
            ValidationResult,
            NoticeAnalysis,
        ):
            self.assertTrue(is_dataclass(cls), cls.__name__)

    def test_deadline_result_constructible_under_existing_contract(self):
        result = DeadlineResult(
            notice_date=date(2026, 8, 1),
            service_date=date(2026, 8, 5),
            response_period_days=30,
            response_deadline=date(2026, 9, 4),
            deadline_confidence=DeadlineConfidence.CONFIRMED,
            deadline_status=DeadlineStatus.UPCOMING,
            days_remaining=7,
            hearing_date=None,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            portal_verification_required=False,
        )
        self.assertEqual(result.notice_date, date(2026, 8, 1))
        self.assertEqual(result.service_date, date(2026, 8, 5))
        self.assertEqual(result.response_period_days, 30)
        self.assertEqual(result.response_deadline, date(2026, 9, 4))
        self.assertIs(result.deadline_confidence, DeadlineConfidence.CONFIRMED)
        self.assertIs(result.deadline_status, DeadlineStatus.UPCOMING)
        self.assertEqual(result.days_remaining, 7)
        self.assertIsNone(result.hearing_date)
        self.assertIs(result.hearing_status, HearingStatus.NOT_SCHEDULED)
        self.assertFalse(result.portal_verification_required)
        self.assertEqual(result.notes, [])


if __name__ == "__main__":
    unittest.main()
