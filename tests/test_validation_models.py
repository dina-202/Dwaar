"""Unit tests for the Phase 2 Step 8.1 validation domain models.

Verifies the v1.1-approved §19 Step-8 contracts added in Step 8.1:

  - RequirementStatus (§19.9): exactly five members, no NOT_APPLICABLE;
  - RequirementKind (§19.10): exactly two members;
  - EvidenceStatus (§19.17): exactly four members;
  - ReviewLevel (§19.20): exactly three members;
  - DraftEligibility (§19.22): exactly three members;
  - SpecialRuleHandling (§19.33): exactly four members;
  - WorkflowRequirementSpec (§19.11): exact eight-field order, annotations
    and defaults (no claim-text / LLM-instruction fields);
  - RequirementResult (§19.12), EvidenceChecklistItem (§19.18),
    ReviewRequirement (§19.21, no filing-decision field), ValidationItem
    (§19.23), ValidationEngineResult (§19.24, no PotentialDefence / no
    legal-validity fields) and WorkflowValidationProfile (§19.34): exact
    field contracts;
  - legacy models ValidationCheck / ValidationResult / EvidenceGap /
    PotentialDefence unchanged (§19.52);
  - ExtractedFact remains the eight-field Step-6.4 contract and FactRole
    remains exactly 22 members;
  - domain/models.py remains standard-library-only.

Pure contract tests only. No validation engine behavior is implemented
or simulated here — the engine does not exist yet (Steps 8.2–8.4).

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_validation_models.py -v
No pytest, no external dependencies, no LLM calls, no network.
"""

import pathlib
import unittest
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from domain.models import (
    ArithmeticCalculationType,
    DraftEligibility,
    DraftPermission,
    EvidenceChecklistItem,
    EvidenceGap,
    EvidenceStatus,
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    IssueSeverity,
    PotentialDefence,
    ProceedingType,
    RequirementKind,
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewRequirement,
    SpecialRuleHandling,
    ValidationCheck,
    ValidationEngineResult,
    ValidationItem,
    ValidationResult,
    ValidationStatus,
    WorkflowRequirementSpec,
    WorkflowValidationProfile,
)

# Exact members, in architecture order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_REQUIREMENT_STATUSES = {
    "SATISFIED": "satisfied",
    "DERIVED": "derived",
    "REQUIRES_VERIFICATION": "requires_verification",
    "UNKNOWN": "unknown",
    "MISSING": "missing",
}

EXPECTED_REQUIREMENT_KINDS = {
    "FACT": "fact",
    "DERIVED": "derived",
}

EXPECTED_EVIDENCE_STATUSES = {
    "UNKNOWN": "unknown",
    "PRESENT": "present",
    "MISSING": "missing",
    "REQUIRES_VERIFICATION": "requires_verification",
}

EXPECTED_REVIEW_LEVELS = {
    "CA_REVIEW": "ca_review",
    "SENIOR_CA_OR_ADVOCATE": "senior_ca_or_advocate",
    "URGENT_CA_REVIEW": "urgent_ca_review",
}

EXPECTED_DRAFT_ELIGIBILITIES = {
    "ALLOWED": "allowed",
    "REVIEW_REQUIRED": "review_required",
    "BLOCKED": "blocked",
}

EXPECTED_SPECIAL_RULE_HANDLINGS = {
    "DETERMINISTIC_CHECK": "deterministic_check",
    "REVIEW_GATE": "review_gate",
    "UPSTREAM_INVARIANT": "upstream_invariant",
    "FUTURE_LEGAL_RULE": "future_legal_rule",
}


class _EnumContractMixin:
    """Shared exact-members/values assertions for the §19 enums."""

    enum_class = None
    expected_members = None

    def test_imports_and_is_enum(self):
        self.assertTrue(issubclass(self.enum_class, Enum))

    def test_members_and_values_exact(self):
        self.assertEqual(
            [(member.name, member.value) for member in self.enum_class],
            list(self.expected_members.items()),
        )

    def test_member_names_exact(self):
        self.assertEqual(
            {member.name for member in self.enum_class},
            set(self.expected_members),
        )

    def test_values_are_lowercase_member_names(self):
        for member in self.enum_class:
            self.assertEqual(member.value, member.name.lower(), member.name)


class RequirementStatusTests(_EnumContractMixin, unittest.TestCase):
    """§19.9: exactly five members; no NOT_APPLICABLE in Phase 2."""

    enum_class = RequirementStatus
    expected_members = EXPECTED_REQUIREMENT_STATUSES

    def test_has_exactly_5_members(self):
        self.assertEqual(len(RequirementStatus), 5)

    def test_no_not_applicable_member(self):
        self.assertFalse(hasattr(RequirementStatus, "NOT_APPLICABLE"))


class RequirementKindTests(_EnumContractMixin, unittest.TestCase):
    """§19.10: exactly two members."""

    enum_class = RequirementKind
    expected_members = EXPECTED_REQUIREMENT_KINDS

    def test_has_exactly_2_members(self):
        self.assertEqual(len(RequirementKind), 2)


class EvidenceStatusTests(_EnumContractMixin, unittest.TestCase):
    """§19.17: exactly four members."""

    enum_class = EvidenceStatus
    expected_members = EXPECTED_EVIDENCE_STATUSES

    def test_has_exactly_4_members(self):
        self.assertEqual(len(EvidenceStatus), 4)


class ReviewLevelTests(_EnumContractMixin, unittest.TestCase):
    """§19.20: exactly three members."""

    enum_class = ReviewLevel
    expected_members = EXPECTED_REVIEW_LEVELS

    def test_has_exactly_3_members(self):
        self.assertEqual(len(ReviewLevel), 3)


class DraftEligibilityTests(_EnumContractMixin, unittest.TestCase):
    """§19.22: exactly three members; a drafting gate, not legal validity."""

    enum_class = DraftEligibility
    expected_members = EXPECTED_DRAFT_ELIGIBILITIES

    def test_has_exactly_3_members(self):
        self.assertEqual(len(DraftEligibility), 3)


class SpecialRuleHandlingTests(_EnumContractMixin, unittest.TestCase):
    """§19.33: exactly four handling types."""

    enum_class = SpecialRuleHandling
    expected_members = EXPECTED_SPECIAL_RULE_HANDLINGS

    def test_has_exactly_4_members(self):
        self.assertEqual(len(SpecialRuleHandling), 4)


class WorkflowRequirementSpecTests(unittest.TestCase):
    """§19.11: exact eight-field contract, order, annotations, defaults."""

    EXPECTED_FIELDS = [
        "requirement_id",
        "requirement_text",
        "kind",
        "fact_type",
        "fact_role",
        "calculation_type",
        "accepted_fact_statuses",
        "absent_on_success",
    ]

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(WorkflowRequirementSpec))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(WorkflowRequirementSpec)],
            self.EXPECTED_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(WorkflowRequirementSpec)), 8)

    def test_field_annotations_exact(self):
        # Enum classes and str are asserted by identity; typing aliases by
        # equality (typing caches can be refreshed in one-process runs).
        by_name = {f.name: f for f in fields(WorkflowRequirementSpec)}
        self.assertIs(by_name["requirement_id"].type, str)
        self.assertIs(by_name["requirement_text"].type, str)
        self.assertIs(by_name["kind"].type, RequirementKind)
        self.assertEqual(by_name["fact_type"].type, Optional[FactType])
        self.assertEqual(by_name["fact_role"].type, Optional[FactRole])
        self.assertEqual(
            by_name["calculation_type"].type,
            Optional[ArithmeticCalculationType],
        )
        self.assertEqual(
            by_name["accepted_fact_statuses"].type, Tuple[FactStatus, ...]
        )
        self.assertIs(by_name["absent_on_success"].type, RequirementStatus)

    def test_defaults_exact(self):
        spec = WorkflowRequirementSpec(
            requirement_id="sec73_itc.r1",
            requirement_text="ITC claimed in GSTR-3B (amount)",
            kind=RequirementKind.FACT,
        )
        self.assertIsNone(spec.fact_type)
        self.assertIsNone(spec.fact_role)
        self.assertIsNone(spec.calculation_type)
        self.assertEqual(spec.accepted_fact_statuses, (FactStatus.CONFIRMED,))
        self.assertIs(spec.absent_on_success, RequirementStatus.MISSING)

    def test_supplied_values_preserved(self):
        spec = WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r1",
            requirement_text="Service / supply category alleged to attract RCM",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.RCM_CATEGORY_ALLEGED,
            calculation_type=None,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        )
        self.assertEqual(spec.requirement_id, "sec73_rcm.r1")
        self.assertEqual(
            spec.requirement_text,
            "Service / supply category alleged to attract RCM",
        )
        self.assertIs(spec.kind, RequirementKind.FACT)
        self.assertIs(spec.fact_type, FactType.DEPARTMENT_ALLEGATION)
        self.assertIs(spec.fact_role, FactRole.RCM_CATEGORY_ALLEGED)
        self.assertIsNone(spec.calculation_type)
        self.assertEqual(spec.accepted_fact_statuses, (FactStatus.ALLEGED,))
        self.assertIs(
            spec.absent_on_success, RequirementStatus.REQUIRES_VERIFICATION
        )

    def test_derived_spec_uses_calculation_type_not_selectors(self):
        spec = WorkflowRequirementSpec(
            requirement_id="sec73_itc.r3",
            requirement_text="Difference between GSTR-3B and GSTR-2B (INFERRED)",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        self.assertIsNone(spec.fact_type)
        self.assertIsNone(spec.fact_role)
        self.assertIs(
            spec.calculation_type, ArithmeticCalculationType.ITC_DIFFERENCE
        )

    def test_no_forbidden_selector_fields(self):
        # §19.11: no description, severity, evidence IDs, matching
        # function, regex, claim text or LLM instructions.
        field_names = {f.name for f in fields(WorkflowRequirementSpec)}
        for name in (
            "description",
            "severity",
            "evidence_ids",
            "matching_function",
            "regex",
            "claim_text",
            "llm_instructions",
            "prompt",
        ):
            self.assertNotIn(name, field_names, name)


class RequirementResultTests(unittest.TestCase):
    """§19.12: exact five-field contract; no LLM explanation field."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(RequirementResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(RequirementResult)],
            [
                "requirement_id",
                "requirement_text",
                "status",
                "related_fact_ids",
                "calculation_type",
            ],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(RequirementResult)), 5)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(RequirementResult)}
        self.assertIs(by_name["requirement_id"].type, str)
        self.assertIs(by_name["requirement_text"].type, str)
        self.assertIs(by_name["status"].type, RequirementStatus)
        self.assertEqual(by_name["related_fact_ids"].type, List[str])
        self.assertEqual(
            by_name["calculation_type"].type,
            Optional[ArithmeticCalculationType],
        )

    def test_calculation_type_default_is_none(self):
        result = RequirementResult(
            requirement_id="sec73_itc.r1",
            requirement_text="ITC claimed in GSTR-3B (amount)",
            status=RequirementStatus.SATISFIED,
            related_fact_ids=["F-001"],
        )
        self.assertIsNone(result.calculation_type)

    def test_supplied_values_preserved(self):
        result = RequirementResult(
            requirement_id="sec73_itc.r3",
            requirement_text="Difference between GSTR-3B and GSTR-2B (INFERRED)",
            status=RequirementStatus.DERIVED,
            related_fact_ids=["F-001", "F-002"],
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        self.assertIs(result.status, RequirementStatus.DERIVED)
        self.assertEqual(result.related_fact_ids, ["F-001", "F-002"])
        self.assertIs(
            result.calculation_type, ArithmeticCalculationType.ITC_DIFFERENCE
        )

    def test_no_free_form_explanation_field(self):
        # §19.12: "No free-form LLM explanation field."
        field_names = {f.name for f in fields(RequirementResult)}
        for name in ("explanation", "llm_text", "message", "note"):
            self.assertNotIn(name, field_names, name)


class EvidenceChecklistItemTests(unittest.TestCase):
    """§19.18: exact three-field contract."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(EvidenceChecklistItem))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(EvidenceChecklistItem)],
            ["evidence_id", "requirement_text", "status"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(EvidenceChecklistItem)), 3)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(EvidenceChecklistItem)}
        self.assertIs(by_name["evidence_id"].type, str)
        self.assertIs(by_name["requirement_text"].type, str)
        self.assertIs(by_name["status"].type, EvidenceStatus)

    def test_supplied_values_preserved(self):
        item = EvidenceChecklistItem(
            evidence_id="sec73_itc.e1",
            requirement_text="GSTR-2B for all months in the relevant period",
            status=EvidenceStatus.UNKNOWN,
        )
        self.assertEqual(item.evidence_id, "sec73_itc.e1")
        self.assertEqual(
            item.requirement_text,
            "GSTR-2B for all months in the relevant period",
        )
        self.assertIs(item.status, EvidenceStatus.UNKNOWN)


class ReviewRequirementTests(unittest.TestCase):
    """§19.21: exact four-field contract; mandatory defaults True."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ReviewRequirement))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ReviewRequirement)],
            ["review_id", "level", "reason", "mandatory"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ReviewRequirement)), 4)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(ReviewRequirement)}
        self.assertIs(by_name["review_id"].type, str)
        self.assertIs(by_name["level"].type, ReviewLevel)
        self.assertIs(by_name["reason"].type, str)
        self.assertIs(by_name["mandatory"].type, bool)

    def test_mandatory_defaults_to_true(self):
        review = ReviewRequirement(
            review_id="rev-001", level=ReviewLevel.CA_REVIEW, reason="reason"
        )
        self.assertIs(review.mandatory, True)

    def test_supplied_values_preserved(self):
        review = ReviewRequirement(
            review_id="rev-002",
            level=ReviewLevel.URGENT_CA_REVIEW,
            reason="deadline passed",
            mandatory=True,
        )
        self.assertEqual(review.review_id, "rev-002")
        self.assertIs(review.level, ReviewLevel.URGENT_CA_REVIEW)
        self.assertEqual(review.reason, "deadline passed")
        self.assertIs(review.mandatory, True)

    def test_no_filing_decision_field(self):
        # §19.21: "No filing decision field."
        field_names = {f.name for f in fields(ReviewRequirement)}
        for name in field_names:
            self.assertNotIn("filing", name, name)
            self.assertNotIn("decision", name, name)


class ValidationItemTests(unittest.TestCase):
    """§19.23: exact five-field contract; status is ValidationStatus."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ValidationItem))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ValidationItem)],
            [
                "check_id",
                "status",
                "message",
                "related_fact_ids",
                "related_calculation_types",
            ],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ValidationItem)), 5)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(ValidationItem)}
        self.assertIs(by_name["check_id"].type, str)
        self.assertIs(by_name["status"].type, ValidationStatus)
        self.assertIs(by_name["message"].type, str)
        self.assertEqual(by_name["related_fact_ids"].type, List[str])
        self.assertEqual(
            by_name["related_calculation_types"].type,
            List[ArithmeticCalculationType],
        )

    def test_supplied_values_preserved(self):
        item = ValidationItem(
            check_id="fact-safety-001",
            status=ValidationStatus.WARNING,
            message="Arithmetic mismatch",
            related_fact_ids=["F-001", "F-002"],
            related_calculation_types=[
                ArithmeticCalculationType.ITC_DIFFERENCE
            ],
        )
        self.assertEqual(item.check_id, "fact-safety-001")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(item.message, "Arithmetic mismatch")
        self.assertEqual(item.related_fact_ids, ["F-001", "F-002"])
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )


class ValidationEngineResultTests(unittest.TestCase):
    """§19.24: exact seven-field contract; no defences / validity fields."""

    EXPECTED_FIELDS = [
        "overall_status",
        "draft_eligibility",
        "case_severity",
        "checks",
        "requirements",
        "evidence_checklist",
        "review_requirements",
    ]

    def make_result(self) -> ValidationEngineResult:
        return ValidationEngineResult(
            overall_status=ValidationStatus.PASS,
            draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
            case_severity=IssueSeverity.MEDIUM,
            checks=[],
            requirements=[],
            evidence_checklist=[],
            review_requirements=[],
        )

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(ValidationEngineResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(ValidationEngineResult)],
            self.EXPECTED_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(ValidationEngineResult)), 7)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(ValidationEngineResult)}
        self.assertIs(by_name["overall_status"].type, ValidationStatus)
        self.assertIs(by_name["draft_eligibility"].type, DraftEligibility)
        self.assertEqual(by_name["case_severity"].type, Optional[IssueSeverity])
        self.assertEqual(by_name["checks"].type, List[ValidationItem])
        self.assertEqual(by_name["requirements"].type, List[RequirementResult])
        self.assertEqual(
            by_name["evidence_checklist"].type, List[EvidenceChecklistItem]
        )
        self.assertEqual(
            by_name["review_requirements"].type, List[ReviewRequirement]
        )

    def test_supplied_values_preserved(self):
        result = self.make_result()
        self.assertIs(result.overall_status, ValidationStatus.PASS)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )
        self.assertIs(result.case_severity, IssueSeverity.MEDIUM)
        self.assertEqual(result.checks, [])
        self.assertEqual(result.requirements, [])
        self.assertEqual(result.evidence_checklist, [])
        self.assertEqual(result.review_requirements, [])

    def test_no_defences_or_legal_validity_fields(self):
        # §19.24: no PotentialDefence and no legal-validity fields; the
        # task also forbids raw facts, a workflow object and error strings.
        field_names = {f.name for f in fields(ValidationEngineResult)}
        for name in (
            "potential_defence",
            "defences",
            "evidence_gap",
            "notice_valid",
            "notice_invalid",
            "jurisdiction_valid",
            "officer_competent",
            "facts",
            "workflow",
            "errors",
            "debug",
        ):
            self.assertNotIn(name, field_names, name)


class WorkflowValidationProfileTests(unittest.TestCase):
    """§19.34: exact four-field contract."""

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(WorkflowValidationProfile))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(WorkflowValidationProfile)],
            [
                "proceeding_type",
                "requirement_specs",
                "special_rule_handling",
                "review_rules",
            ],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(WorkflowValidationProfile)), 4)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(WorkflowValidationProfile)}
        self.assertIs(by_name["proceeding_type"].type, ProceedingType)
        self.assertEqual(
            by_name["requirement_specs"].type, List[WorkflowRequirementSpec]
        )
        self.assertEqual(
            by_name["special_rule_handling"].type,
            Dict[int, Tuple[SpecialRuleHandling, ...]],
        )
        self.assertEqual(by_name["review_rules"].type, Dict[int, ReviewLevel])

    def test_supplied_values_preserved(self):
        profile = WorkflowValidationProfile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            requirement_specs=[],
            special_rule_handling={
                0: (SpecialRuleHandling.REVIEW_GATE,)
            },
            review_rules={0: ReviewLevel.CA_REVIEW},
        )
        self.assertIs(
            profile.proceeding_type, ProceedingType.GST_SEC73_ITC
        )
        self.assertEqual(profile.requirement_specs, [])
        self.assertEqual(
            profile.special_rule_handling,
            {0: (SpecialRuleHandling.REVIEW_GATE,)},
        )
        self.assertEqual(profile.review_rules, {0: ReviewLevel.CA_REVIEW})


class LegacyModelCompatibilityTests(unittest.TestCase):
    """§19.52: legacy validation models are unchanged compatibility
    artifacts."""

    def test_legacy_validation_check_contract_unchanged(self):
        self.assertTrue(is_dataclass(ValidationCheck))
        self.assertEqual(
            [f.name for f in fields(ValidationCheck)],
            ["rule_id", "description", "passed", "message"],
        )
        by_name = {f.name: f for f in fields(ValidationCheck)}
        self.assertIs(by_name["rule_id"].type, str)
        self.assertIs(by_name["description"].type, str)
        self.assertIs(by_name["passed"].type, bool)
        self.assertIs(by_name["message"].type, str)

    def test_legacy_validation_result_contract_unchanged(self):
        self.assertTrue(is_dataclass(ValidationResult))
        self.assertEqual(
            [f.name for f in fields(ValidationResult)],
            ["overall_passed", "checks", "warnings"],
        )
        by_name = {f.name: f for f in fields(ValidationResult)}
        self.assertIs(by_name["overall_passed"].type, bool)
        self.assertEqual(by_name["checks"].type, List[ValidationCheck])
        self.assertEqual(by_name["warnings"].type, List[str])

    def test_legacy_evidence_gap_contract_unchanged(self):
        self.assertTrue(is_dataclass(EvidenceGap))
        self.assertEqual(
            [f.name for f in fields(EvidenceGap)],
            ["item", "why_it_matters", "status"],
        )
        gap = EvidenceGap(item="GSTR-2B", why_it_matters="reconcile ITC")
        self.assertEqual(gap.status, "REQUIRES VERIFICATION")

    def test_legacy_potential_defence_contract_unchanged(self):
        self.assertTrue(is_dataclass(PotentialDefence))
        self.assertEqual(
            [f.name for f in fields(PotentialDefence)],
            [
                "name",
                "legal_basis",
                "argument",
                "facts_required",
                "evidence_required",
                "strength",
                "limitations",
                "case_law_note",
            ],
        )
        defence = PotentialDefence(
            name="defence",
            legal_basis="s. 73",
            argument="argument",
            facts_required=[],
            evidence_required=[],
            strength="Cannot assess yet",
            limitations="none",
        )
        self.assertEqual(
            defence.case_law_note, "[CA LEGAL RESEARCH REQUIRED]"
        )


class Step64ContractCompatibilityTests(unittest.TestCase):
    """Step 6.4 contracts are untouched by the additive Step 8.1 models."""

    def test_extracted_fact_remains_eight_field_contract(self):
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
        fact = ExtractedFact("F-001", "claim", FactStatus.CONFIRMED)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_fact_role_remains_exactly_22_members(self):
        self.assertEqual(len(FactRole), 22)


class StdlibPurityTests(unittest.TestCase):
    """domain/models.py remains standard-library-only (§17.24, AGENTS.md)."""

    ALLOWED_IMPORT_ROOTS = {
        "enum",
        "dataclasses",
        "typing",
        "datetime",
        "decimal",
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


if __name__ == "__main__":
    unittest.main()
