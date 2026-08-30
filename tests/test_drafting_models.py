"""Unit tests for the Phase 2 Step 9.1 drafting domain models.

Verifies the v1.1-approved §20.20 Step-9A contracts added in Step 9.1:

  - DraftGenerationStatus (§20.20): exactly three members, exact values,
    no aliases, no UNKNOWN;
  - DraftFailureCode (§20.20): exactly six members, exact values, no
    aliases, no UNKNOWN, no RETRY_EXHAUSTED;
  - DraftSectionSpec, WorkflowDraftingProfile, DraftSection,
    DraftPostValidationResult and SpecialistDraftResult (§20.20): exact
    field order, exact annotations, no extra fields and the
    no-implicit-defaults policy (every field caller-supplied; Optional
    fields explicitly None — no default_factory, no automatic empty
    lists);
  - SpecialistDraftResult carries no filing_approved / legally_valid /
    liability_confirmed fields (§20.20);
  - legacy models NoticeAnalysis / ValidationCheck / ValidationResult /
    EvidenceGap / PotentialDefence remain unchanged compatibility
    artifacts (§20.42);
  - the existing Step-8 model contracts (ValidationEngineResult,
    ValidationItem, RequirementResult, EvidenceChecklistItem,
    ReviewRequirement, WorkflowRequirementSpec, DraftEligibility,
    ValidationStatus, ProceedingType) are unchanged by the additive
    Step-9.1 models;
  - dataclass equality is deterministic and list fields are caller-owned
    (never silently default-created);
  - domain/models.py remains standard-library-only.

Pure contract tests only. No drafting engine, no prompt loading, no LLM
calls, no network.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_drafting_models.py -v
No pytest, no external dependencies.
"""

import pathlib
import unittest
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from domain.models import (
    ArithmeticDraftBlock,
    DeadlineDraftBlock,
    DeadlineResult,
    DraftBlockKind,
    DraftCandidateBlock,
    DraftCandidateSection,
    DraftEligibility,
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftPostValidationResult,
    DraftSection,
    DraftSectionSpec,
    EvidenceDraftBlock,
    EvidenceChecklistItem,
    EvidenceGap,
    EvidenceStatus,
    ExtractedFact,
    FactDraftBlock,
    FactRole,
    FactStatus,
    FactType,
    HearingDraftBlock,
    NoticeAnalysis,
    PotentialDefence,
    ProceedingType,
    RequirementDraftBlock,
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewDraftBlock,
    ReviewRequirement,
    SpecialistDraftResult,
    StaticDraftBlock,
    ValidationCheck,
    ValidationEngineResult,
    ValidationItem,
    ValidationResult,
    ValidationStatus,
    WorkflowDraftingProfile,
    WorkflowRequirementSpec,
)

# Exact members, in architecture order, with the repository enum-value
# convention (lowercase member names).
EXPECTED_DRAFT_GENERATION_STATUSES = {
    "SUCCESS": "success",
    "BLOCKED": "blocked",
    "FAILED": "failed",
}

EXPECTED_DRAFT_FAILURE_CODES = {
    "VALIDATION_REQUIRED": "validation_required",
    "DRAFT_BLOCKED": "draft_blocked",
    "WORKFLOW_UNAVAILABLE": "workflow_unavailable",
    "LLM_ERROR": "llm_error",
    "MALFORMED_RESPONSE": "malformed_response",
    "POST_VALIDATION_FAILED": "post_validation_failed",
}

EXPECTED_DRAFT_BLOCK_KINDS = {
    "STATIC": "static",
    "FACT": "fact",
    "ARITHMETIC": "arithmetic",
    "DEADLINE": "deadline",
    "HEARING": "hearing",
    "REQUIREMENT": "requirement",
    "EVIDENCE": "evidence",
    "REVIEW": "review",
}


class _EnumContractMixin:
    """Shared exact-members/values assertions for the §20.20 enums."""

    enum_class = None
    expected_members = None

    def test_imports_and_is_enum(self):
        self.assertTrue(issubclass(self.enum_class, Enum))

    def test_members_and_values_exact(self):
        self.assertEqual(
            [(member.name, member.value) for member in self.enum_class],
            list(self.expected_members.items()),
        )

    def test_values_are_lowercase_member_names(self):
        for member in self.enum_class:
            self.assertEqual(member.value, member.name.lower(), member.name)

    def test_no_aliases(self):
        # Aliases would duplicate values or fail canonical lookup.
        values = [member.value for member in self.enum_class]
        self.assertEqual(len(values), len(set(values)))
        for member in self.enum_class:
            self.assertIs(self.enum_class(member.value), member, member.name)

    def test_no_unknown_member(self):
        self.assertFalse(hasattr(self.enum_class, "UNKNOWN"))


class _NoDefaultMixin:
    """Shared no-implicit-defaults assertions for the §20.20 dataclasses."""

    dataclass_type = None

    def test_no_implicit_defaults(self):
        for f in fields(self.dataclass_type):
            self.assertIs(f.default, MISSING, f.name)
            self.assertIs(f.default_factory, MISSING, f.name)

    def test_constructing_with_missing_field_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.dataclass_type()


class DraftGenerationStatusTests(_EnumContractMixin, unittest.TestCase):
    """§20.20: exactly three members; stable machine-contract values."""

    enum_class = DraftGenerationStatus
    expected_members = EXPECTED_DRAFT_GENERATION_STATUSES

    def test_has_exactly_3_members(self):
        self.assertEqual(len(DraftGenerationStatus), 3)

    def test_exact_values(self):
        self.assertEqual(DraftGenerationStatus.SUCCESS.value, "success")
        self.assertEqual(DraftGenerationStatus.BLOCKED.value, "blocked")
        self.assertEqual(DraftGenerationStatus.FAILED.value, "failed")


class DraftFailureCodeTests(_EnumContractMixin, unittest.TestCase):
    """§20.20: exactly six members; no UNKNOWN, no RETRY_EXHAUSTED."""

    enum_class = DraftFailureCode
    expected_members = EXPECTED_DRAFT_FAILURE_CODES

    def test_has_exactly_6_members(self):
        self.assertEqual(len(DraftFailureCode), 6)

    def test_exact_values(self):
        self.assertEqual(
            DraftFailureCode.VALIDATION_REQUIRED.value, "validation_required"
        )
        self.assertEqual(DraftFailureCode.DRAFT_BLOCKED.value, "draft_blocked")
        self.assertEqual(
            DraftFailureCode.WORKFLOW_UNAVAILABLE.value, "workflow_unavailable"
        )
        self.assertEqual(DraftFailureCode.LLM_ERROR.value, "llm_error")
        self.assertEqual(
            DraftFailureCode.MALFORMED_RESPONSE.value, "malformed_response"
        )
        self.assertEqual(
            DraftFailureCode.POST_VALIDATION_FAILED.value,
            "post_validation_failed",
        )

    def test_no_retry_exhausted_member(self):
        self.assertFalse(hasattr(DraftFailureCode, "RETRY_EXHAUSTED"))


class DraftBlockKindTests(_EnumContractMixin, unittest.TestCase):
    """§25.3: exact closed eight-member block-kind contract."""

    enum_class = DraftBlockKind
    expected_members = EXPECTED_DRAFT_BLOCK_KINDS

    def test_has_exactly_8_members(self):
        self.assertEqual(len(DraftBlockKind), 8)


class DraftCandidateContractTests(unittest.TestCase):
    """§25.4: identifier-only typed candidate contracts, still dormant."""

    FIELD_CONTRACTS = {
        StaticDraftBlock: [("template_id", str)],
        FactDraftBlock: [("fact_id", str)],
        ArithmeticDraftBlock: [("arithmetic_index", int)],
        DeadlineDraftBlock: [],
        HearingDraftBlock: [],
        RequirementDraftBlock: [("requirement_id", str)],
        EvidenceDraftBlock: [("evidence_id", str)],
        ReviewDraftBlock: [("review_id", str)],
    }

    def test_exact_block_dataclass_fields_order_and_annotations(self):
        for block_type, expected in self.FIELD_CONTRACTS.items():
            self.assertTrue(is_dataclass(block_type), block_type.__name__)
            self.assertEqual(
                [(item.name, item.type) for item in fields(block_type)],
                expected,
                block_type.__name__,
            )

    def test_fieldful_blocks_have_no_defaults(self):
        for block_type, expected in self.FIELD_CONTRACTS.items():
            for item in fields(block_type):
                self.assertIs(item.default, MISSING, item.name)
                self.assertIs(item.default_factory, MISSING, item.name)
            if expected:
                with self.assertRaises(TypeError, msg=block_type.__name__):
                    block_type()

    def test_zero_field_blocks_accept_no_keys(self):
        self.assertEqual(DeadlineDraftBlock(), DeadlineDraftBlock())
        self.assertEqual(HearingDraftBlock(), HearingDraftBlock())
        with self.assertRaises(TypeError):
            DeadlineDraftBlock(text="not authorized")
        with self.assertRaises(TypeError):
            HearingDraftBlock(metadata={})

    def test_candidate_union_is_exact_and_ordered(self):
        self.assertEqual(
            DraftCandidateBlock,
            Union[
                StaticDraftBlock,
                FactDraftBlock,
                ArithmeticDraftBlock,
                DeadlineDraftBlock,
                HearingDraftBlock,
                RequirementDraftBlock,
                EvidenceDraftBlock,
                ReviewDraftBlock,
            ],
        )

    def test_candidate_section_exact_contract(self):
        self.assertTrue(is_dataclass(DraftCandidateSection))
        self.assertEqual(
            [(item.name, item.type) for item in fields(DraftCandidateSection)],
            [
                ("section_id", str),
                ("blocks", Tuple[DraftCandidateBlock, ...]),
            ],
        )
        for item in fields(DraftCandidateSection):
            self.assertIs(item.default, MISSING, item.name)
            self.assertIs(item.default_factory, MISSING, item.name)
        with self.assertRaises(TypeError):
            DraftCandidateSection()

    def test_no_prose_bearing_or_arbitrary_payload_field(self):
        forbidden = {
            "text",
            "prose",
            "body",
            "body_template",
            "template_text",
            "claim",
            "explanation",
            "reason",
            "suffix",
            "prefix",
            "metadata",
            "payload",
        }
        for block_type in self.FIELD_CONTRACTS:
            names = {item.name for item in fields(block_type)}
            self.assertTrue(names.isdisjoint(forbidden), block_type.__name__)


class DraftSectionSpecTests(_NoDefaultMixin, unittest.TestCase):
    """§20.20: exact two-field contract; no defaults, no extra fields."""

    dataclass_type = DraftSectionSpec

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(DraftSectionSpec))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(DraftSectionSpec)],
            ["section_id", "title"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(DraftSectionSpec)), 2)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(DraftSectionSpec)}
        self.assertIs(by_name["section_id"].type, str)
        self.assertIs(by_name["title"].type, str)

    def test_supplied_values_preserved(self):
        spec = DraftSectionSpec(section_id="sec129.s1", title="Working paper")
        self.assertEqual(spec.section_id, "sec129.s1")
        self.assertEqual(spec.title, "Working paper")


class WorkflowDraftingProfileTests(_NoDefaultMixin, unittest.TestCase):
    """§20.19–§20.22: exact three-field contract; tuple of specs."""

    dataclass_type = WorkflowDraftingProfile

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(WorkflowDraftingProfile))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(WorkflowDraftingProfile)],
            ["proceeding_type", "sections", "prompt_key"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(WorkflowDraftingProfile)), 3)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(WorkflowDraftingProfile)}
        self.assertIs(by_name["proceeding_type"].type, ProceedingType)
        self.assertEqual(
            by_name["sections"].type, Tuple[DraftSectionSpec, ...]
        )
        self.assertIs(by_name["prompt_key"].type, str)

    def test_sections_annotation_is_typing_tuple(self):
        # §20.20: use typing.Tuple, not the builtin tuple constructor.
        by_name = {f.name: f for f in fields(WorkflowDraftingProfile)}
        self.assertEqual(by_name["sections"].type, Tuple[DraftSectionSpec, ...])

    def test_sections_is_tuple_not_list(self):
        profile = WorkflowDraftingProfile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            sections=(
                DraftSectionSpec(
                    section_id="sec73_itc.s1", title="Working paper"
                ),
            ),
            prompt_key="sec73_itc",
        )
        self.assertIsInstance(profile.sections, tuple)
        self.assertNotIsInstance(profile.sections, list)

    def test_no_prompt_text_or_filename_fields(self):
        # §20.22: the profile stores a prompt key only — no prompt text
        # and no filenames.
        field_names = {f.name for f in fields(WorkflowDraftingProfile)}
        for name in ("prompt_text", "prompt_path", "filename", "template"):
            self.assertNotIn(name, field_names, name)


class DraftSectionTests(_NoDefaultMixin, unittest.TestCase):
    """§20.20: exact four-field contract; no defaults, no extra fields."""

    dataclass_type = DraftSection

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(DraftSection))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(DraftSection)],
            ["section_id", "title", "template_text", "rendered_text"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(DraftSection)), 4)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(DraftSection)}
        for name in ("section_id", "title", "template_text", "rendered_text"):
            self.assertIs(by_name[name].type, str, name)

    def test_supplied_values_preserved(self):
        section = DraftSection(
            section_id="sec73_itc.s1",
            title="Working paper",
            template_text="Computed difference: [[ARITH:1]].",
            rendered_text="Computed difference: Rs 5,000 (calculated).",
        )
        self.assertEqual(section.section_id, "sec73_itc.s1")
        self.assertEqual(section.title, "Working paper")
        self.assertEqual(section.template_text, "Computed difference: [[ARITH:1]].")
        self.assertEqual(
            section.rendered_text, "Computed difference: Rs 5,000 (calculated)."
        )


class DraftPostValidationResultTests(_NoDefaultMixin, unittest.TestCase):
    """§20.20: exact two-field contract; no defaults, no default_factory."""

    dataclass_type = DraftPostValidationResult

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(DraftPostValidationResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(DraftPostValidationResult)],
            ["overall_status", "checks"],
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(DraftPostValidationResult)), 2)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(DraftPostValidationResult)}
        self.assertIs(by_name["overall_status"].type, ValidationStatus)
        self.assertEqual(by_name["checks"].type, List[ValidationItem])

    def test_checks_list_is_caller_owned(self):
        checks: List[ValidationItem] = []
        result = DraftPostValidationResult(
            overall_status=ValidationStatus.PASS, checks=checks
        )
        self.assertIs(result.checks, checks)
        self.assertIs(result.overall_status, ValidationStatus.PASS)

    def test_checks_have_no_default_factory(self):
        by_name = {f.name: f for f in fields(DraftPostValidationResult)}
        self.assertIs(by_name["checks"].default_factory, MISSING)


def _make_result(**overrides) -> SpecialistDraftResult:
    """Build a SpecialistDraftResult with every field explicitly supplied."""
    kwargs = dict(
        status=DraftGenerationStatus.SUCCESS,
        draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
        sections=[],
        unresolved_requirements=[],
        evidence_checklist=[],
        review_requirements=[],
        post_validation=None,
        failure_code=None,
        error_message=None,
    )
    kwargs.update(overrides)
    return SpecialistDraftResult(**kwargs)


class SpecialistDraftResultTests(_NoDefaultMixin, unittest.TestCase):
    """§20.20: exact nine-field contract; explicit-None optional fields."""

    dataclass_type = SpecialistDraftResult

    EXPECTED_FIELDS = [
        "status",
        "draft_eligibility",
        "sections",
        "unresolved_requirements",
        "evidence_checklist",
        "review_requirements",
        "post_validation",
        "failure_code",
        "error_message",
    ]

    def test_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(SpecialistDraftResult))

    def test_field_names_and_order_exact(self):
        self.assertEqual(
            [f.name for f in fields(SpecialistDraftResult)],
            self.EXPECTED_FIELDS,
        )

    def test_no_extra_fields(self):
        self.assertEqual(len(fields(SpecialistDraftResult)), 9)

    def test_field_annotations_exact(self):
        by_name = {f.name: f for f in fields(SpecialistDraftResult)}
        self.assertIs(by_name["status"].type, DraftGenerationStatus)
        self.assertIs(by_name["draft_eligibility"].type, DraftEligibility)
        self.assertEqual(by_name["sections"].type, List[DraftSection])
        self.assertEqual(
            by_name["unresolved_requirements"].type, List[RequirementResult]
        )
        self.assertEqual(
            by_name["evidence_checklist"].type, List[EvidenceChecklistItem]
        )
        self.assertEqual(
            by_name["review_requirements"].type, List[ReviewRequirement]
        )
        self.assertEqual(
            by_name["post_validation"].type,
            Optional[DraftPostValidationResult],
        )
        self.assertEqual(
            by_name["failure_code"].type, Optional[DraftFailureCode]
        )
        self.assertEqual(by_name["error_message"].type, Optional[str])

    def test_optional_fields_accept_explicit_none(self):
        # §20.20: callers must explicitly supply None when absent.
        result = _make_result(
            post_validation=None, failure_code=None, error_message=None
        )
        self.assertIsNone(result.post_validation)
        self.assertIsNone(result.failure_code)
        self.assertIsNone(result.error_message)

    def test_constructing_without_optional_fields_raises_type_error(self):
        with self.assertRaises(TypeError):
            SpecialistDraftResult(
                status=DraftGenerationStatus.SUCCESS,
                draft_eligibility=DraftEligibility.ALLOWED,
                sections=[],
                unresolved_requirements=[],
                evidence_checklist=[],
                review_requirements=[],
            )

    def test_no_default_factory_anywhere(self):
        for f in fields(SpecialistDraftResult):
            self.assertIs(f.default_factory, MISSING, f.name)

    def test_supplied_values_preserved(self):
        section = DraftSection(
            section_id="sec73_itc.s1",
            title="Working paper",
            template_text="[[ARITH:1]]",
            rendered_text="deterministic text",
        )
        requirement = RequirementResult(
            requirement_id="sec73_itc.r1",
            requirement_text="ITC claimed in GSTR-3B (amount)",
            status=RequirementStatus.MISSING,
            related_fact_ids=["F-001"],
        )
        evidence = EvidenceChecklistItem(
            evidence_id="sec73_itc.e1",
            requirement_text="GSTR-2B for all months in the relevant period",
            status=EvidenceStatus.UNKNOWN,
        )
        review = ReviewRequirement(
            review_id="rev-001",
            level=ReviewLevel.CA_REVIEW,
            reason="mismatch present",
        )
        post = DraftPostValidationResult(
            overall_status=ValidationStatus.PASS, checks=[]
        )
        result = _make_result(
            status=DraftGenerationStatus.FAILED,
            draft_eligibility=DraftEligibility.ALLOWED,
            sections=[section],
            unresolved_requirements=[requirement],
            evidence_checklist=[evidence],
            review_requirements=[review],
            post_validation=post,
            failure_code=DraftFailureCode.POST_VALIDATION_FAILED,
            error_message="check failed",
        )
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)
        self.assertEqual(result.sections, [section])
        self.assertEqual(result.unresolved_requirements, [requirement])
        self.assertEqual(result.evidence_checklist, [evidence])
        self.assertEqual(result.review_requirements, [review])
        self.assertIs(result.post_validation, post)
        self.assertIs(
            result.failure_code, DraftFailureCode.POST_VALIDATION_FAILED
        )
        self.assertEqual(result.error_message, "check failed")

    def test_list_fields_are_caller_owned_not_factory_created(self):
        sections: List[DraftSection] = []
        requirements: List[RequirementResult] = []
        evidence: List[EvidenceChecklistItem] = []
        reviews: List[ReviewRequirement] = []
        result = _make_result(
            sections=sections,
            unresolved_requirements=requirements,
            evidence_checklist=evidence,
            review_requirements=reviews,
        )
        self.assertIs(result.sections, sections)
        self.assertIs(result.unresolved_requirements, requirements)
        self.assertIs(result.evidence_checklist, evidence)
        self.assertIs(result.review_requirements, reviews)

    def test_no_forbidden_legal_validity_fields(self):
        # §20.20: no filing_approved / legally_valid / liability_confirmed
        # or equivalent field.
        field_names = [f.name for f in fields(SpecialistDraftResult)]
        for name in ("filing_approved", "legally_valid", "liability_confirmed"):
            self.assertNotIn(name, field_names, name)
        for name in field_names:
            self.assertNotIn("filing", name, name)
            self.assertNotIn("legally", name, name)
            self.assertNotIn("liability", name, name)
            self.assertNotIn("approved", name, name)

    def test_post_validation_has_no_legal_validity_fields(self):
        field_names = [f.name for f in fields(DraftPostValidationResult)]
        for name in ("legally_valid", "legal_validity", "liability"):
            self.assertNotIn(name, field_names, name)


class LegacyModelCompatibilityTests(unittest.TestCase):
    """§20.42: legacy models are unchanged compatibility artifacts."""

    def test_legacy_models_still_exist(self):
        for cls in (
            NoticeAnalysis,
            ValidationCheck,
            ValidationResult,
            EvidenceGap,
            PotentialDefence,
        ):
            self.assertTrue(is_dataclass(cls), cls.__name__)

    def test_legacy_validation_check_contract_unchanged(self):
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
        self.assertEqual(
            [f.name for f in fields(ValidationResult)],
            ["overall_passed", "checks", "warnings"],
        )
        by_name = {f.name: f for f in fields(ValidationResult)}
        self.assertIs(by_name["overall_passed"].type, bool)
        self.assertEqual(by_name["checks"].type, List[ValidationCheck])
        self.assertEqual(by_name["warnings"].type, List[str])

    def test_legacy_evidence_gap_contract_unchanged(self):
        self.assertEqual(
            [f.name for f in fields(EvidenceGap)],
            ["item", "why_it_matters", "status"],
        )
        gap = EvidenceGap(item="GSTR-2B", why_it_matters="reconcile ITC")
        self.assertEqual(gap.status, "REQUIRES VERIFICATION")

    def test_legacy_potential_defence_contract_unchanged(self):
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

    def test_legacy_notice_analysis_contract_unchanged(self):
        self.assertEqual(
            [f.name for f in fields(NoticeAnalysis)],
            [
                "proceeding_type",
                "notice_date",
                "notice_reference",
                "issuing_authority",
                "taxpayer_name",
                "gstin",
                "tax_period",
                "sections_cited",
                "reply_form",
                "facts",
                "deadlines",
                "allegations",
                "evidence_gaps",
                "potential_defences",
                "notice_summary",
                "required_action",
                "draft_reply",
                "client_whatsapp",
                "validation",
                "raw_text_chars",
                "today",
                "analysis_timestamp",
            ],
        )
        by_name = {f.name: f for f in fields(NoticeAnalysis)}
        self.assertIs(by_name["proceeding_type"].type, ProceedingType)
        self.assertIs(by_name["validation"].type, ValidationResult)
        self.assertEqual(by_name["facts"].type, List[ExtractedFact])
        self.assertIs(by_name["deadlines"].type, DeadlineResult)
        self.assertEqual(by_name["evidence_gaps"].type, List[EvidenceGap])
        self.assertEqual(
            by_name["potential_defences"].type, List[PotentialDefence]
        )


class Step8ContractCompatibilityTests(unittest.TestCase):
    """Existing Step-8 contracts are untouched by the Step-9.1 models."""

    def test_validation_engine_result_remains_seven_field_contract(self):
        self.assertEqual(
            [f.name for f in fields(ValidationEngineResult)],
            [
                "overall_status",
                "draft_eligibility",
                "case_severity",
                "checks",
                "requirements",
                "evidence_checklist",
                "review_requirements",
            ],
        )

    def test_validation_item_remains_five_field_contract(self):
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

    def test_requirement_result_remains_five_field_contract(self):
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

    def test_evidence_checklist_item_remains_three_field_contract(self):
        self.assertEqual(
            [f.name for f in fields(EvidenceChecklistItem)],
            ["evidence_id", "requirement_text", "status"],
        )

    def test_review_requirement_remains_four_field_contract(self):
        self.assertEqual(
            [f.name for f in fields(ReviewRequirement)],
            ["review_id", "level", "reason", "mandatory"],
        )

    def test_workflow_requirement_spec_remains_eight_field_contract(self):
        self.assertEqual(
            [f.name for f in fields(WorkflowRequirementSpec)],
            [
                "requirement_id",
                "requirement_text",
                "kind",
                "fact_type",
                "fact_role",
                "calculation_type",
                "accepted_fact_statuses",
                "absent_on_success",
            ],
        )

    def test_step8_enums_remain_exact(self):
        self.assertEqual(len(ValidationStatus), 3)
        self.assertEqual(len(DraftEligibility), 3)
        self.assertEqual(len(RequirementStatus), 5)
        self.assertEqual(len(EvidenceStatus), 4)
        self.assertEqual(len(ReviewLevel), 3)

    def test_proceeding_type_remains_six_members(self):
        self.assertEqual(len(ProceedingType), 6)
        self.assertTrue(hasattr(ProceedingType, "UNKNOWN"))

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
            ],
        )
        fact = ExtractedFact("F-001", "claim", FactStatus.CONFIRMED)
        self.assertIs(fact.allowed_in_draft, DraftPermission.CONDITIONAL)
        self.assertIs(fact.fact_type, FactType.OTHER_NOTICE_FACT)
        self.assertIs(fact.fact_role, FactRole.NONE)

    def test_fact_role_remains_exactly_22_members(self):
        self.assertEqual(len(FactRole), 22)


class DataclassEqualityTests(unittest.TestCase):
    """§20.20 dataclasses compare deterministically using field equality."""

    def test_draft_section_spec_equality(self):
        self.assertEqual(
            DraftSectionSpec(section_id="sec129.s1", title="Working paper"),
            DraftSectionSpec(section_id="sec129.s1", title="Working paper"),
        )
        self.assertNotEqual(
            DraftSectionSpec(section_id="sec129.s1", title="Working paper"),
            DraftSectionSpec(section_id="sec129.s2", title="Other"),
        )

    def test_workflow_drafting_profile_equality(self):
        def make():
            return WorkflowDraftingProfile(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
                sections=(
                    DraftSectionSpec(
                        section_id="sec129.s1",
                        title="URGENT enforcement working paper",
                    ),
                ),
                prompt_key="sec129",
            )

        self.assertEqual(make(), make())

    def test_draft_section_equality(self):
        self.assertEqual(
            DraftSection(
                section_id="s1", title="t", template_text="a", rendered_text="b"
            ),
            DraftSection(
                section_id="s1", title="t", template_text="a", rendered_text="b"
            ),
        )

    def test_draft_post_validation_result_equality(self):
        self.assertEqual(
            DraftPostValidationResult(
                overall_status=ValidationStatus.PASS, checks=[]
            ),
            DraftPostValidationResult(
                overall_status=ValidationStatus.PASS, checks=[]
            ),
        )

    def test_specialist_draft_result_equality(self):
        self.assertEqual(_make_result(), _make_result())
        self.assertNotEqual(
            _make_result(status=DraftGenerationStatus.SUCCESS),
            _make_result(status=DraftGenerationStatus.FAILED),
        )


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

        source = pathlib.Path(models_module.__file__).read_text(encoding="utf-8")
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
