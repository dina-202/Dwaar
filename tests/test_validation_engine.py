"""Unit tests for the generic deterministic Step-8.2 Validation Engine
(ARCHITECTURE_SPEC_v1_1 §19, §19.56–§19.87).

Fully offline and deterministic. No LLM calls, no network, no fixtures.

Verifies the complete staged Step-8.2 contract:

  - public API / pure-Python boundary (no LLM, no network, no engine
    recomputation, no source-code introspection, requirements and
    evidence_checklist always empty in Step 8.2);
  - support gate and deep-workflow structural checks;
  - extraction health;
  - the ten fact safety invariants including the §19.5 FactRole
    compatibility table;
  - the five preflight checks;
  - deadline/hearing checks and the deadline urgent-review contract;
  - the six-check arithmetic structure, role provenance and
    status/result consistency;
  - workflow special-rule handling (review gates, future legal rules,
    upstream invariants, the two temporary derived-rule deferrals, the
    two fraud deterministic mirrors and the Section-129 deadline-source
    boundary);
  - ReviewRequirement dedup, overall status aggregation, interim
    DraftEligibility, case severity, and input immutability.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_validation_engine.py -v
No pytest, no external dependencies.
"""

import copy
import inspect
import pathlib
import unittest
from dataclasses import fields
from datetime import date
from decimal import Decimal
from unittest import mock

import domain.validation_engine as engine
from domain.models import (
    ArithmeticCalculationType,
    ArithmeticResult,
    ArithmeticStatus,
    AuthorityDetailsStatus,
    ClassificationConfidence,
    CommunicationIdentifierStatus,
    DeadlineConfidence,
    DeadlineConflictStatus,
    DeadlineResult,
    DeadlineStatus,
    DraftEligibility,
    DraftPermission,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    IssueSeverity,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    PreflightResult,
    ProceedingType,
    RequirementKind,
    ReviewLevel,
    ReviewRequirement,
    SpecialRuleHandling,
    SupportLevel,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
    WorkflowRequirementSpec,
    WorkflowValidationProfile,
)
from workflows.gst import GST_WORKFLOW_REGISTRY, get_workflow
from workflows.gst.base import WorkflowDefinition
from workflows.gst.validation_profiles import (
    VALIDATION_PROFILE_REGISTRY,
    get_validation_profile,
)

# --- Shared helpers ---------------------------------------------------------

FACT_INVARIANT_IDS = (
    "fact.department_allegation_status",
    "fact.department_allegation_draft_permission",
    "fact.other_notice_fact_status",
    "fact.requires_verification_draft_permission",
    "fact.confirmed_draft_permission",
    "fact.alleged_draft_permission",
    "fact.fact_id_present",
    "fact.source_text_present",
    "fact.fact_id_unique",
    "fact.role_compatibility",
)


def make_classification(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    support_level=SupportLevel.DEEP_WORKFLOW,
):
    return NoticeClassification(
        notice_family=NoticeFamily.RETURN_COMPLIANCE,
        notice_form=NoticeForm.DRC_01C,
        proceeding_type=proceeding_type,
        support_level=support_level,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=["test"],
    )


def make_fact(
    fact_id="F-001",
    claim="Claim",
    status=FactStatus.CONFIRMED,
    source_text="Notice text.",
    allowed_in_draft=DraftPermission.YES,
    fact_type=FactType.OTHER_NOTICE_FACT,
    fact_role=FactRole.NONE,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim=claim,
        status=status,
        source_text=source_text,
        source_page=None,
        allowed_in_draft=allowed_in_draft,
        fact_type=fact_type,
        fact_role=fact_role,
    )


def clean_facts():
    """Three mutually consistent facts: every §19.28 invariant passes."""
    return [
        make_fact("F-001", "Notice date.", FactStatus.CONFIRMED, "dt",
                  DraftPermission.YES, FactType.NOTICE_DATE, FactRole.NONE),
        make_fact("F-002", "Alleged basis.", FactStatus.ALLEGED, "al",
                  DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
                  FactRole.FRAUD_BASIS_ALLEGED),
        make_fact("F-003", "Other detail.", FactStatus.REQUIRES_VERIFICATION,
                  "ot", DraftPermission.NO, FactType.OTHER_NOTICE_FACT,
                  FactRole.NONE),
    ]


def fraud_clean_facts():
    """A clean Section-74 fact set (allegations stay ALLEGED/CONDITIONAL)."""
    return [
        make_fact("F-001", "Basis", FactStatus.ALLEGED, "b",
                  DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
                  FactRole.FRAUD_BASIS_ALLEGED),
        make_fact("F-002", "Amount", FactStatus.ALLEGED, "a",
                  DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
                  FactRole.DEPARTMENT_ALLEGED_AMOUNT),
        make_fact("F-003", "Period", FactStatus.CONFIRMED, "p",
                  DraftPermission.YES, FactType.TAX_PERIOD, FactRole.NONE),
        make_fact("F-004", "Penalty", FactStatus.ALLEGED, "pe",
                  DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
                  FactRole.FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT),
        make_fact("F-005", "Limitation", FactStatus.CONFIRMED, "l",
                  DraftPermission.YES, FactType.DOCUMENT_DETAIL,
                  FactRole.LIMITATION_BASIS),
    ]


def itc_operand_facts():
    """ITC_DIFFERENCE operands in the approved §19.15 role order."""
    return [
        make_fact("A", "3B ITC", FactStatus.CONFIRMED, "x",
                  DraftPermission.YES, FactType.STATED_AMOUNT,
                  FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
        make_fact("B", "2B ITC", FactStatus.CONFIRMED, "y",
                  DraftPermission.YES, FactType.STATED_AMOUNT,
                  FactRole.GSTR2B_ITC_REFLECTED_AMOUNT),
    ]


def output_tax_operand_facts():
    """OUTPUT_TAX_DIFFERENCE operands in the approved §19.15 role order."""
    return [
        make_fact("A", "GSTR-1", FactStatus.CONFIRMED, "x",
                  DraftPermission.YES, FactType.STATED_AMOUNT,
                  FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT),
        make_fact("B", "GSTR-3B", FactStatus.CONFIRMED, "y",
                  DraftPermission.YES, FactType.STATED_AMOUNT,
                  FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT),
    ]


def make_preflight(
    portal=True,
    authority=True,
    comm=CommunicationIdentifierStatus.RFN_PRESENT,
    authority_status=AuthorityDetailsStatus.PRESENT,
    stated_due=None,
    conflict=DeadlineConflictStatus.CANNOT_COMPARE,
):
    return PreflightResult(
        fact_extraction_status=FactExtractionStatus.SUCCESS,
        communication_identifier_status=comm,
        portal_verification_required=portal,
        authority_details_status=authority_status,
        authority_verification_required=authority,
        stated_due_date_fact_ids=[] if stated_due is None else list(stated_due),
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=conflict,
        hearing_fact_ids=[],
        requested_document_fact_ids=[],
        referenced_annexure_fact_ids=[],
    )


def make_extraction(facts=None, status=FactExtractionStatus.SUCCESS):
    return FactExtractionResult(
        facts=[] if facts is None else list(facts),
        status=status,
        rejected_item_count=0,
    )


def make_deadline(
    deadline_status=DeadlineStatus.UPCOMING,
    hearing_status=HearingStatus.NOT_SCHEDULED,
):
    return DeadlineResult(
        notice_date=date(2026, 8, 1),
        service_date=None,
        response_period_days=None,
        response_deadline=None,
        deadline_confidence=DeadlineConfidence.UNKNOWN,
        deadline_status=deadline_status,
        days_remaining=None,
        hearing_date=None,
        hearing_status=hearing_status,
        portal_verification_required=True,
        notes=[],
    )


def make_arithmetic(
    calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
    status=ArithmeticStatus.PASS,
    source_fact_ids=(),
    result=Decimal("0"),
    allowed_in_draft=DraftPermission.CONDITIONAL,
):
    return ArithmeticResult(
        calculation_type=calculation_type,
        status=status,
        source_fact_ids=list(source_fact_ids),
        operand_values=[],
        result=result,
        formula="left - right",
        currency="INR",
        allowed_in_draft=allowed_in_draft,
    )


def make_mock_workflow(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    special_rules=None,
    required_facts=None,
    default_severity=IssueSeverity.MEDIUM,
):
    return WorkflowDefinition(
        proceeding_type=proceeding_type,
        required_facts=[] if required_facts is None else list(required_facts),
        evidence_requirements=[],
        issue_types=[],
        default_severity=default_severity,
        output_structure=[],
        special_rules=[] if special_rules is None else list(special_rules),
    )


def make_mock_profile(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    requirement_texts=None,
    handling=None,
    review_rules=None,
):
    return WorkflowValidationProfile(
        proceeding_type=proceeding_type,
        requirement_specs=[
            WorkflowRequirementSpec(
                requirement_id=f"mock.r{index}",
                requirement_text=text,
                kind=RequirementKind.FACT,
            )
            for index, text in enumerate(requirement_texts or [])
        ],
        special_rule_handling=dict(handling) if handling is not None else {},
        review_rules=dict(review_rules) if review_rules is not None else {},
    )


def run_defaults(
    classification=None,
    extraction=None,
    preflight=None,
    arithmetic=None,
    deadline=None,
):
    return engine.run_validation(
        classification if classification is not None else make_classification(),
        extraction if extraction is not None else make_extraction(),
        preflight if preflight is not None else make_preflight(),
        arithmetic if arithmetic is not None else [],
        deadline,
    )


def get_item(checks, check_id):
    for item in checks:
        if item.check_id == check_id:
            return item
    return None


def check_ids(checks):
    return {item.check_id for item in checks}


def review_ids(reviews):
    return {review.review_id for review in reviews}


# --- A. API / purity --------------------------------------------------------

class ApiPurityTests(unittest.TestCase):
    """Public API shape and the pure-Python import boundary (§19.7–19.8)."""

    SOURCE = pathlib.Path(engine.__file__).read_text(encoding="utf-8")
    ALLOWED_IMPORT_ROOTS = {"decimal", "typing", "domain", "workflows"}
    FORBIDDEN_TOKENS = (
        "llm_client", "gemini", "genai", "google", "requests", "urllib",
        "socket", "http", "sqlite", "streamlit",
        "deadline_engine", "arithmetic_engine", "fact_engine",
        "preflight_engine", "proceeding_classifier", "taxonomy_registry",
        "inspect", "getsource", "timedelta", "seven",
        "notice_explainer", "import app", "PotentialDefence", "EvidenceGap",
    )

    def test_run_validation_exists(self):
        self.assertTrue(callable(engine.run_validation))

    def test_exact_public_signature(self):
        signature = inspect.signature(engine.run_validation)
        parameter_names = list(signature.parameters)
        self.assertEqual(
            parameter_names,
            [
                "classification",
                "extraction_result",
                "preflight_result",
                "arithmetic_results",
                "deadline_result",
            ],
        )
        self.assertEqual(
            signature.parameters["deadline_result"].default, None
        )

    def test_return_type_is_validation_engine_result(self):
        result = run_defaults()
        self.assertIsInstance(result, ValidationEngineResult)

    def test_module_imports_only_approved_modules(self):
        roots = set()
        for line in self.SOURCE.splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                module_name = stripped.split()[1]
                if module_name.startswith("."):
                    continue
                roots.add(module_name.split(".")[0])
            elif stripped.startswith("import "):
                roots.add(stripped.split()[1].split(".")[0])
        self.assertTrue(
            roots <= set(self.ALLOWED_IMPORT_ROOTS),
            f"unexpected import roots {sorted(roots)}",
        )

    def test_no_forbidden_technology_or_behavior_in_source(self):
        lowered = self.SOURCE.lower()
        for token in self.FORBIDDEN_TOKENS:
            self.assertNotIn(token, lowered, token)

    def test_no_source_code_introspection(self):
        # No runtime reading of implementation source files: no inspect,
        # no getsource, no os/pathlib file access.
        self.assertNotIn("inspect", self.SOURCE.lower())
        self.assertNotIn("getsource", self.SOURCE.lower())

    def test_no_additional_public_validation_api(self):
        public_callables = [
            name
            for name, obj in vars(engine).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == engine.__name__
        ]
        self.assertEqual(public_callables, ["run_validation"])

    def test_requirements_always_empty_in_step_8_2(self):
        result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_evidence_checklist_always_empty_in_step_8_2(self):
        result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_deadline_argument_optional_without_fifth_argument(self):
        # §19.7: deadline_result is Optional; four-argument calls succeed.
        result = engine.run_validation(
            make_classification(),
            make_extraction(),
            make_preflight(),
            [],
        )
        self.assertIsInstance(result, ValidationEngineResult)
        self.assertNotIn("deadline.status", check_ids(result.checks))

    def test_engine_obtains_workflow_and_profile_from_classification(self):
        # §19.7: the engine reads get_workflow/get_validation_profile
        # internally, driven only by classification.proceeding_type.
        with mock.patch.object(
            engine, "get_workflow", wraps=get_workflow
        ) as workflow_spy, mock.patch.object(
            engine, "get_validation_profile", wraps=get_validation_profile
        ) as profile_spy:
            classification = make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
            run_defaults(classification=classification)
        self.assertEqual(
            workflow_spy.call_args_list,
            [mock.call(ProceedingType.GST_SEC73_RCM)],
        )
        self.assertEqual(
            profile_spy.call_args_list,
            [mock.call(ProceedingType.GST_SEC73_RCM)],
        )

    def test_result_is_deterministic_across_identical_inputs(self):
        # §19.8: no randomness, no hidden state, no LLM variance.
        first = run_defaults()
        second = run_defaults()
        self.assertEqual(first, second)

    def test_output_items_follow_step_8_contracts(self):
        # §19.23/§19.21: every check is a ValidationItem with non-empty
        # machine ID and message; every review is a ReviewRequirement
        # that is mandatory.
        result = run_defaults()
        self.assertTrue(result.checks)
        for item in result.checks:
            self.assertIsInstance(item, ValidationItem)
            self.assertIsInstance(item.check_id, str)
            self.assertTrue(item.check_id)
            self.assertIsInstance(item.message, str)
            self.assertTrue(item.message)
            self.assertIsInstance(item.related_fact_ids, list)
            self.assertIsInstance(item.related_calculation_types, list)
        for review in result.review_requirements:
            self.assertIsInstance(review, ReviewRequirement)
            self.assertIsInstance(review.review_id, str)
            self.assertTrue(review.review_id)
            self.assertTrue(review.mandatory)

    def test_no_extra_output_model(self):
        # ValidationEngineResult has exactly the seven §19.24 fields — no
        # defences, no legal-validity fields.
        self.assertEqual(
            [field.name for field in fields(ValidationEngineResult)],
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


# --- B. Support gate --------------------------------------------------------

class SupportGateTests(unittest.TestCase):
    """§19.58 / §19.45–§19.46 exact messages and structural checks."""

    def test_triage_only_support_level_fail_exact_message(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        item = get_item(result.checks, "support.level")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Specialist deep-workflow drafting is unavailable for this recognized notice.",
        )

    def test_triage_only_blocked(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_unknown_support_fail_exact_message(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        item = get_item(result.checks, "support.level")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Specialist deep-workflow drafting is unavailable because the notice classification is unsupported or unknown.",
        )

    def test_unknown_proceeding_blocked(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_no_workflow_fallback(self):
        self.assertIsNone(get_workflow(ProceedingType.UNKNOWN))
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN
            )
        )
        # No workflow-anchored items are emitted for an unknown proceeding.
        self.assertEqual(
            [c for c in result.checks if c.check_id.startswith("workflow.")],
            [],
        )

    def test_valid_deep_support_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.level")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Deep workflow support is available for the classified proceeding.",
        )

    def test_workflow_registered_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.workflow_registered")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "A deep WorkflowDefinition is registered for the classified proceeding.",
        )

    def test_missing_workflow_fail(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result = run_defaults()
        item = get_item(result.checks, "support.workflow_registered")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "No deep WorkflowDefinition is registered for the classified proceeding.",
        )

    def test_profile_registered_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.profile_registered")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "A WorkflowValidationProfile is registered for the classified proceeding.",
        )

    def test_missing_profile_fail(self):
        with mock.patch.object(
            engine, "get_validation_profile", return_value=None
        ):
            result = run_defaults()
        item = get_item(result.checks, "support.profile_registered")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "No WorkflowValidationProfile is registered for the classified proceeding.",
        )

    def test_workflow_alignment_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.workflow_alignment")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "WorkflowDefinition proceeding type matches the classification.",
        )

    def test_workflow_alignment_fail(self):
        wrong = make_mock_workflow(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(engine, "get_workflow", return_value=wrong):
            result = run_defaults()
        item = get_item(result.checks, "support.workflow_alignment")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "WorkflowDefinition proceeding type does not match the classification.",
        )

    def test_profile_alignment_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.profile_alignment")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "WorkflowValidationProfile proceeding type matches the classification.",
        )

    def test_profile_alignment_fail(self):
        wrong = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        item = get_item(result.checks, "support.profile_alignment")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "WorkflowValidationProfile proceeding type does not match the classification.",
        )

    def test_requirement_alignment_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.requirement_alignment")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Workflow requirement profile matches the workflow required-facts contract.",
        )

    def test_requirement_alignment_fail(self):
        wrong = make_mock_profile(requirement_texts=["Different text."])
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        item = get_item(result.checks, "support.requirement_alignment")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Workflow requirement profile does not match the workflow required-facts contract.",
        )

    def test_special_rule_coverage_pass(self):
        result = run_defaults()
        item = get_item(result.checks, "support.special_rule_coverage")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Every workflow special rule has an authoritative validation/review handling mapping.",
        )

    def test_special_rule_coverage_fail(self):
        real_workflow = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_ITC]
        wrong = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            requirement_texts=list(real_workflow.required_facts),
            handling={0: (SpecialRuleHandling.REVIEW_GATE,)},
            review_rules={0: ReviewLevel.CA_REVIEW},
        )
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        item = get_item(result.checks, "support.special_rule_coverage")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "One or more workflow special rules lack an authoritative handling mapping.",
        )

    def test_deep_support_failure_blocked(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result = run_defaults()
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)


# --- C. Extraction health ---------------------------------------------------

class ExtractionHealthTests(unittest.TestCase):
    """§19.59 exact mappings."""

    def test_success_pass(self):
        result = run_defaults(extraction=make_extraction())
        item = get_item(result.checks, "extraction.status")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Fact extraction completed successfully."
        )

    def test_partial_warning(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.PARTIAL)
        )
        item = get_item(result.checks, "extraction.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Fact extraction was partial; validated positive facts remain usable but absence-based conclusions are not reliable.",
        )

    def test_failed_fail(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        item = get_item(result.checks, "extraction.status")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Fact extraction failed; specialist drafting is blocked.",
        )

    def test_no_input_fail(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        item = get_item(result.checks, "extraction.status")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "No usable notice text was available for fact extraction; specialist drafting is blocked.",
        )

    def test_failed_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_no_input_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_partial_not_blocked_solely_because_partial(self):
        result = run_defaults(
            extraction=make_extraction(
                facts=clean_facts(), status=FactExtractionStatus.PARTIAL
            )
        )
        self.assertIsNot(
            result.draft_eligibility, DraftEligibility.BLOCKED
        )


# --- D. Fact invariants -----------------------------------------------------

class FactInvariantTests(unittest.TestCase):
    """§19.60 / §19.28: the ten fixed invariant items."""

    def test_clean_facts_make_all_ten_invariant_checks_pass(self):
        result = run_defaults(extraction=make_extraction(facts=clean_facts()))
        for check_id in FACT_INVARIANT_IDS:
            item = get_item(result.checks, check_id)
            self.assertIsNotNone(item, check_id)
            self.assertIs(item.status, ValidationStatus.PASS, check_id)
            self.assertEqual(item.related_fact_ids, [], check_id)
            self.assertEqual(item.related_calculation_types, [], check_id)

    def test_department_allegation_wrong_status_fail(self):
        offender = make_fact(
            "F-001", "Allegation", FactStatus.REQUIRES_VERIFICATION, "a",
            DraftPermission.NO, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(result.checks, "fact.department_allegation_status")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])
        self.assertEqual(
            item.message, "Department-allegation status invariant failed."
        )

    def test_department_allegation_yes_permission_fail(self):
        offender = make_fact(
            "F-001", "Allegation", FactStatus.ALLEGED, "a",
            DraftPermission.YES, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(
            result.checks, "fact.department_allegation_draft_permission"
        )
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_other_notice_fact_wrong_status_fail(self):
        offender = make_fact(
            "F-001", "Other", FactStatus.CONFIRMED, "o",
            DraftPermission.YES, FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(result.checks, "fact.other_notice_fact_status")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_requires_verification_wrong_permission_fail(self):
        offender = make_fact(
            "F-001", "Verify", FactStatus.REQUIRES_VERIFICATION, "v",
            DraftPermission.CONDITIONAL, FactType.OTHER_NOTICE_FACT,
            FactRole.NONE,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(
            result.checks, "fact.requires_verification_draft_permission"
        )
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_confirmed_wrong_permission_fail(self):
        offender = make_fact(
            "F-001", "Confirmed", FactStatus.CONFIRMED, "c",
            DraftPermission.CONDITIONAL, FactType.NOTICE_DATE, FactRole.NONE,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(result.checks, "fact.confirmed_draft_permission")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_alleged_wrong_permission_fail(self):
        offender = make_fact(
            "F-001", "Alleged", FactStatus.ALLEGED, "a",
            DraftPermission.NO, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(result.checks, "fact.alleged_draft_permission")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_empty_fact_id_fail(self):
        offender = make_fact("", "No id", FactStatus.CONFIRMED, "n",
                             DraftPermission.YES, FactType.NOTICE_DATE,
                             FactRole.NONE)
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        item = get_item(result.checks, "fact.fact_id_present")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, [])
        self.assertEqual(
            item.message, "Fact-ID presence invariant failed."
        )

    def test_empty_source_text_fail(self):
        offender = make_fact("F-001", "No source", FactStatus.CONFIRMED,
                             None, DraftPermission.YES, FactType.NOTICE_DATE,
                             FactRole.NONE)
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        item = get_item(result.checks, "fact.source_text_present")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-001"])
        self.assertEqual(
            item.message, "Fact source-text presence invariant failed."
        )

    def test_duplicate_fact_ids_fail(self):
        facts = [
            make_fact("F-001", "One", FactStatus.CONFIRMED, "1",
                      DraftPermission.YES, FactType.NOTICE_DATE,
                      FactRole.NONE),
            make_fact("F-001", "Two", FactStatus.CONFIRMED, "2",
                      DraftPermission.YES, FactType.NOTICE_DATE,
                      FactRole.NONE),
        ]
        result = run_defaults(extraction=make_extraction(facts=facts))
        item = get_item(result.checks, "fact.fact_id_unique")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message, "Fact-ID uniqueness invariant failed."
        )

    def test_duplicate_related_ids_deduped_and_preserved(self):
        facts = [
            make_fact(fact_id, f"Fact {fact_id}", FactStatus.CONFIRMED, "s",
                      DraftPermission.YES, FactType.NOTICE_DATE,
                      FactRole.NONE)
            for fact_id in ["F-1", "F-1", "F-2", "F-2", "F-1"]
        ]
        result = run_defaults(extraction=make_extraction(facts=facts))
        item = get_item(result.checks, "fact.fact_id_unique")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-1", "F-2"])

    def test_fact_violation_blocked(self):
        offender = make_fact(
            "F-001", "Other", FactStatus.CONFIRMED, "o",
            DraftPermission.YES, FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_facts_never_mutated(self):
        facts = clean_facts()
        snapshot = copy.deepcopy(facts)
        run_defaults(extraction=make_extraction(facts=facts))
        self.assertEqual(facts, snapshot)
        for fact, before in zip(facts, snapshot):
            self.assertEqual(fact, before)


# --- D2. FactRole compatibility (§19.5) -------------------------------------

class RoleCompatibilityTests(unittest.TestCase):
    """§19.5 closed compatibility table via fact.role_compatibility."""

    STATED_AMOUNT_ROLES = (
        FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
        FactRole.INTEREST_PROPOSED_AMOUNT,
        FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT,
        FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT,
        FactRole.SEC129_PENALTY_PROPOSED_AMOUNT,
    )
    ALLEGATION_ROLES = (
        FactRole.RCM_CATEGORY_ALLEGED,
        FactRole.RCM_VALUE_ALLEGED_AMOUNT,
        FactRole.RCM_TAX_ALLEGED_AMOUNT,
        FactRole.FRAUD_BASIS_ALLEGED,
        FactRole.DEPARTMENT_ALLEGED_AMOUNT,
        FactRole.FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT,
    )
    DOCUMENT_DETAIL_ROLES = (
        FactRole.LIMITATION_BASIS,
        FactRole.GOODS_DESCRIPTION,
        FactRole.VEHICLE_NUMBER,
        FactRole.DETENTION_OR_SEIZURE_DATE,
        FactRole.SECTION129_NOTICE_OR_SERVICE_DATE,
        FactRole.GOODS_VALUE_OR_TAX_PAYABLE,
        FactRole.OWNER_CAME_FORWARD_STATUS,
        FactRole.ORDER_DATE_OR_ENFORCEMENT_STATUS,
    )

    def _role_check(self, fact_type, fact_role, status=FactStatus.CONFIRMED,
                    permission=DraftPermission.YES):
        fact = make_fact("F-001", "Role check", status, "s", permission,
                         fact_type, fact_role)
        result = run_defaults(extraction=make_extraction(facts=[fact]))
        item = get_item(result.checks, "fact.role_compatibility")
        self.assertIsNotNone(item)
        return item.status

    def test_none_role_compatible_with_every_fact_type(self):
        for fact_type in FactType:
            self.assertIs(
                self._role_check(fact_type, FactRole.NONE),
                ValidationStatus.PASS,
                fact_type.name,
            )

    def test_each_stated_amount_role_compatible(self):
        for role in self.STATED_AMOUNT_ROLES:
            self.assertIs(
                self._role_check(FactType.STATED_AMOUNT, role),
                ValidationStatus.PASS,
                role.name,
            )

    def test_incompatible_stated_amount_role_fail(self):
        self.assertIs(
            self._role_check(
                FactType.DEPARTMENT_ALLEGATION,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
                status=FactStatus.ALLEGED,
                permission=DraftPermission.CONDITIONAL,
            ),
            ValidationStatus.FAIL,
        )

    def test_each_allegation_role_compatible(self):
        for role in self.ALLEGATION_ROLES:
            self.assertIs(
                self._role_check(
                    FactType.DEPARTMENT_ALLEGATION,
                    role,
                    status=FactStatus.ALLEGED,
                    permission=DraftPermission.CONDITIONAL,
                ),
                ValidationStatus.PASS,
                role.name,
            )

    def test_incompatible_allegation_role_fail(self):
        self.assertIs(
            self._role_check(
                FactType.STATED_AMOUNT, FactRole.FRAUD_BASIS_ALLEGED
            ),
            ValidationStatus.FAIL,
        )

    def test_each_document_detail_role_compatible(self):
        for role in self.DOCUMENT_DETAIL_ROLES:
            self.assertIs(
                self._role_check(FactType.DOCUMENT_DETAIL, role),
                ValidationStatus.PASS,
                role.name,
            )

    def test_incompatible_document_detail_role_fail(self):
        self.assertIs(
            self._role_check(FactType.NOTICE_DATE, FactRole.GOODS_DESCRIPTION),
            ValidationStatus.FAIL,
        )

    def test_procedural_date_role_allowed_on_all_three_types(self):
        for fact_type in (
            FactType.STATED_DUE_DATE,
            FactType.HEARING_DETAILS,
            FactType.DOCUMENT_DETAIL,
        ):
            self.assertIs(
                self._role_check(
                    fact_type, FactRole.EXPLICIT_PROCEDURAL_DATE
                ),
                ValidationStatus.PASS,
                fact_type.name,
            )

    def test_procedural_date_incompatible_type_fail(self):
        self.assertIs(
            self._role_check(
                FactType.TAX_PERIOD, FactRole.EXPLICIT_PROCEDURAL_DATE
            ),
            ValidationStatus.FAIL,
        )


# --- E. Preflight checks ----------------------------------------------------

class PreflightTests(unittest.TestCase):
    """§19.61 exact messages/status rules."""

    def test_portal_true_warning_exact_message(self):
        result = run_defaults(preflight=make_preflight(portal=True))
        item = get_item(result.checks, "preflight.portal_verification")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "GST portal identifier/authenticity verification is required.",
        )

    def test_portal_false_pass(self):
        result = run_defaults(preflight=make_preflight(portal=False))
        item = get_item(result.checks, "preflight.portal_verification")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "GST portal identifier/authenticity verification is not currently flagged by preflight.",
        )

    def test_authority_verification_true_warning_exact_message(self):
        result = run_defaults(preflight=make_preflight(authority=True))
        item = get_item(result.checks, "preflight.authority_verification")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Issuing-authority competence/jurisdiction requires CA/legal verification.",
        )

    def test_authority_verification_false_pass(self):
        result = run_defaults(preflight=make_preflight(authority=False))
        item = get_item(result.checks, "preflight.authority_verification")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Issuing-authority verification is not currently flagged by preflight.",
        )

    def test_communication_unknown_warning(self):
        result = run_defaults(
            preflight=make_preflight(comm=CommunicationIdentifierStatus.UNKNOWN)
        )
        item = get_item(result.checks, "preflight.communication_identifier")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "Communication identifier status is UNKNOWN."
        )

    def test_known_communication_status_pass(self):
        result = run_defaults(
            preflight=make_preflight(comm=CommunicationIdentifierStatus.RFN_PRESENT)
        )
        item = get_item(result.checks, "preflight.communication_identifier")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Communication identifier status is available."
        )

    def test_authority_details_unknown_warning(self):
        result = run_defaults(
            preflight=make_preflight(
                authority_status=AuthorityDetailsStatus.UNKNOWN
            )
        )
        item = get_item(result.checks, "preflight.authority_details")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "Authority details status is UNKNOWN."
        )

    def test_known_authority_status_pass(self):
        result = run_defaults(
            preflight=make_preflight(
                authority_status=AuthorityDetailsStatus.PRESENT
            )
        )
        item = get_item(result.checks, "preflight.authority_details")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Authority details status is available."
        )

    def test_conflict_warning(self):
        result = run_defaults(
            preflight=make_preflight(
                conflict=DeadlineConflictStatus.CONFLICT
            )
        )
        item = get_item(result.checks, "preflight.deadline_conflict")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "The notice-stated due date conflicts with the calculated response deadline.",
        )

    def test_cannot_compare_with_due_ids_warning(self):
        result = run_defaults(
            preflight=make_preflight(
                stated_due=["F-001"],
                conflict=DeadlineConflictStatus.CANNOT_COMPARE,
            )
        )
        item = get_item(result.checks, "preflight.deadline_conflict")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "The notice-stated due date and calculated response deadline cannot be reliably compared.",
        )

    def test_cannot_compare_with_deadline_result_warning(self):
        result = run_defaults(
            preflight=make_preflight(
                conflict=DeadlineConflictStatus.CANNOT_COMPARE
            ),
            deadline=make_deadline(),
        )
        item = get_item(result.checks, "preflight.deadline_conflict")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "The notice-stated due date and calculated response deadline cannot be reliably compared.",
        )

    def test_cannot_compare_without_either_pass(self):
        result = run_defaults(
            preflight=make_preflight(
                conflict=DeadlineConflictStatus.CANNOT_COMPARE
            )
        )
        item = get_item(result.checks, "preflight.deadline_conflict")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "No deadline comparison is currently available or required.",
        )

    def test_match_pass(self):
        result = run_defaults(
            preflight=make_preflight(conflict=DeadlineConflictStatus.MATCH)
        )
        item = get_item(result.checks, "preflight.deadline_conflict")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "The notice-stated due date matches the calculated response deadline.",
        )

    def test_all_preflight_items_have_empty_related_lists(self):
        result = run_defaults()
        for check_id in (
            "preflight.portal_verification",
            "preflight.authority_verification",
            "preflight.communication_identifier",
            "preflight.authority_details",
            "preflight.deadline_conflict",
        ):
            item = get_item(result.checks, check_id)
            self.assertIsNotNone(item, check_id)
            self.assertEqual(item.related_fact_ids, [], check_id)
            self.assertEqual(item.related_calculation_types, [], check_id)


# --- F. Deadline / hearing --------------------------------------------------

class DeadlineHearingTests(unittest.TestCase):
    """§19.62 / §19.63 / §19.31 exact mappings."""

    def test_deadline_none_emits_neither_check(self):
        result = run_defaults(deadline=None)
        ids = check_ids(result.checks)
        self.assertNotIn("deadline.status", ids)
        self.assertNotIn("hearing.status", ids)

    def test_deadline_upcoming_pass(self):
        result = run_defaults(deadline=make_deadline())
        item = get_item(result.checks, "deadline.status")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "The calculated response deadline is upcoming."
        )

    def test_deadline_critical_warning(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        item = get_item(result.checks, "deadline.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "The calculated response deadline is critical."
        )

    def test_deadline_passed_warning(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.PASSED)
        )
        item = get_item(result.checks, "deadline.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "The calculated response deadline has passed."
        )

    def test_deadline_unknown_warning(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.UNKNOWN)
        )
        item = get_item(result.checks, "deadline.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "The calculated response deadline is unknown."
        )

    def test_hearing_upcoming_pass(self):
        result = run_defaults(
            deadline=make_deadline(hearing_status=HearingStatus.UPCOMING)
        )
        item = get_item(result.checks, "hearing.status")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(item.message, "The scheduled hearing is upcoming.")

    def test_hearing_today_warning(self):
        result = run_defaults(
            deadline=make_deadline(hearing_status=HearingStatus.TODAY)
        )
        item = get_item(result.checks, "hearing.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(item.message, "The scheduled hearing is today.")

    def test_hearing_passed_warning(self):
        result = run_defaults(
            deadline=make_deadline(hearing_status=HearingStatus.PASSED)
        )
        item = get_item(result.checks, "hearing.status")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(item.message, "The scheduled hearing has passed.")

    def test_hearing_not_scheduled_pass(self):
        result = run_defaults(
            deadline=make_deadline(hearing_status=HearingStatus.NOT_SCHEDULED)
        )
        item = get_item(result.checks, "hearing.status")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "No hearing is currently scheduled in the DeadlineResult.",
        )

    def test_critical_creates_urgent_review(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        self.assertIn("deadline.urgent_review", review_ids(result.review_requirements))

    def test_passed_creates_urgent_review(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.PASSED)
        )
        self.assertIn("deadline.urgent_review", review_ids(result.review_requirements))

    def test_exact_urgent_review_ids_reasons(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        review = next(
            r for r in result.review_requirements
            if r.review_id == "deadline.urgent_review"
        )
        self.assertIs(review.level, ReviewLevel.URGENT_CA_REVIEW)
        self.assertTrue(review.mandatory)
        self.assertEqual(
            review.reason,
            "Deadline status is CRITICAL; urgent CA review is required.",
        )

        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.PASSED)
        )
        review = next(
            r for r in result.review_requirements
            if r.review_id == "deadline.urgent_review"
        )
        self.assertIs(review.level, ReviewLevel.URGENT_CA_REVIEW)
        self.assertEqual(
            review.reason,
            "Deadline status is PASSED; urgent CA review is required.",
        )

    def test_upcoming_creates_no_deadline_review(self):
        result = run_defaults(deadline=make_deadline())
        self.assertNotIn(
            "deadline.urgent_review", review_ids(result.review_requirements)
        )

    def test_unknown_creates_no_deadline_review(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.UNKNOWN)
        )
        self.assertNotIn(
            "deadline.urgent_review", review_ids(result.review_requirements)
        )

    def test_critical_deadline_severity_critical(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)

    def test_passed_deadline_severity_critical(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.PASSED)
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)


# --- G. Arithmetic checks ---------------------------------------------------

class ArithmeticTests(unittest.TestCase):
    """§19.64 / §19.65 / §19.29 / §19.15: six checks per result."""

    def test_six_ids_emitted_per_arithmetic_result(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        for suffix in (
            "calculation_type",
            "draft_permission",
            "source_resolution",
            "role_provenance",
            "result_status_consistency",
            "outcome",
        ):
            self.assertIn(f"arithmetic.1.{suffix}", check_ids(result.checks))

    def test_n_is_one_based_input_order(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE
                ),
            ],
        )
        ids = check_ids(result.checks)
        self.assertIn("arithmetic.1.calculation_type", ids)
        self.assertIn("arithmetic.2.calculation_type", ids)
        self.assertNotIn("arithmetic.0.calculation_type", ids)

    def test_duplicate_calculation_types_get_distinct_n(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        )
        ids = check_ids(result.checks)
        self.assertIn("arithmetic.1.calculation_type", ids)
        self.assertIn("arithmetic.2.calculation_type", ids)

    def test_approved_calculation_type_pass(self):
        result = run_defaults(
            arithmetic=[make_arithmetic()]
        )
        item = get_item(result.checks, "arithmetic.1.calculation_type")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Arithmetic calculation type is approved."
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_unsupported_runtime_type_fail(self):
        bad = make_arithmetic(calculation_type="itc_difference")
        result = run_defaults(arithmetic=[bad])
        item = get_item(result.checks, "arithmetic.1.calculation_type")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message, "Arithmetic calculation type is unsupported."
        )
        self.assertEqual(item.related_calculation_types, [])

    def test_conditional_permission_pass(self):
        result = run_defaults(arithmetic=[make_arithmetic()])
        item = get_item(result.checks, "arithmetic.1.draft_permission")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Arithmetic draft permission is CONDITIONAL."
        )

    def test_wrong_arithmetic_permission_fail(self):
        bad = make_arithmetic(allowed_in_draft=DraftPermission.YES)
        result = run_defaults(arithmetic=[bad])
        item = get_item(result.checks, "arithmetic.1.draft_permission")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message, "Arithmetic draft permission must be CONDITIONAL."
        )

    def test_unique_source_resolution_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        item = get_item(result.checks, "arithmetic.1.source_resolution")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Arithmetic source facts resolve uniquely."
        )
        self.assertEqual(item.related_fact_ids, ["A", "B"])

    def test_missing_source_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "MISSING"])],
        )
        item = get_item(result.checks, "arithmetic.1.source_resolution")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message, "Arithmetic source facts do not resolve uniquely."
        )

    def test_duplicate_source_fact_id_causes_source_resolution_fail(self):
        facts = [
            make_fact("A", "First A", FactStatus.CONFIRMED, "1",
                      DraftPermission.YES, FactType.STATED_AMOUNT,
                      FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
            make_fact("A", "Second A", FactStatus.CONFIRMED, "2",
                      DraftPermission.YES, FactType.STATED_AMOUNT,
                      FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
        ]
        result = run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=[make_arithmetic(source_fact_ids=["A"])],
        )
        item = get_item(result.checks, "arithmetic.1.source_resolution")
        self.assertIs(item.status, ValidationStatus.FAIL)

    def test_itc_role_provenance_correct_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        item = get_item(result.checks, "arithmetic.1.role_provenance")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Arithmetic operand FactRoles match the approved calculation contract.",
        )

    def test_itc_reversed_roles_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        item = get_item(result.checks, "arithmetic.1.role_provenance")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Arithmetic operand FactRoles do not match the approved calculation contract.",
        )

    def test_output_tax_roles_correct_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        )
        item = get_item(result.checks, "arithmetic.1.role_provenance")
        self.assertIs(item.status, ValidationStatus.PASS)

    def test_output_tax_wrong_roles_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["B", "A"],
                )
            ],
        )
        item = get_item(result.checks, "arithmetic.1.role_provenance")
        self.assertIs(item.status, ValidationStatus.FAIL)

    def test_pass_with_zero_consistency_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.PASS,
                    source_fact_ids=["A", "B"],
                    result=Decimal("0"),
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Arithmetic status and result are internally consistent.",
        )

    def test_pass_with_nonzero_consistency_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.PASS,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Arithmetic status and result are internally inconsistent.",
        )

    def test_mismatch_with_nonzero_consistency_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.PASS)

    def test_mismatch_with_zero_consistency_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("0"),
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.FAIL)

    def test_insufficient_data_with_none_consistency_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.INSUFFICIENT_DATA,
                    source_fact_ids=["A", "B"],
                    result=None,
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.PASS)

    def test_insufficient_data_with_value_consistency_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.INSUFFICIENT_DATA,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        item = get_item(
            result.checks, "arithmetic.1.result_status_consistency"
        )
        self.assertIs(item.status, ValidationStatus.FAIL)

    def test_pass_outcome_pass(self):
        result = run_defaults(arithmetic=[make_arithmetic()])
        item = get_item(result.checks, "arithmetic.1.outcome")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(item.message, "Arithmetic result matches.")

    def test_mismatch_outcome_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        item = get_item(result.checks, "arithmetic.1.outcome")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(item.message, "Arithmetic result is a mismatch.")

    def test_insufficient_data_outcome_warning(self):
        result = run_defaults(
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.INSUFFICIENT_DATA, result=None
                )
            ]
        )
        item = get_item(result.checks, "arithmetic.1.outcome")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message, "Arithmetic result has insufficient data."
        )

    def test_valid_mismatch_alone_not_blocked(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        self.assertIsNot(
            result.draft_eligibility, DraftEligibility.BLOCKED
        )

    def test_structural_arithmetic_fail_blocked(self):
        bad = make_arithmetic(allowed_in_draft=DraftPermission.YES)
        result = run_defaults(arithmetic=[bad])
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_arithmetic_objects_not_mutated(self):
        arithmetic = [
            make_arithmetic(
                status=ArithmeticStatus.MISMATCH,
                source_fact_ids=["A", "B"],
                result=Decimal("5"),
            )
        ]
        snapshot = copy.deepcopy(arithmetic)
        run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=arithmetic,
        )
        self.assertEqual(arithmetic, snapshot)


# --- H. Special rules -------------------------------------------------------

class SpecialRuleTests(unittest.TestCase):
    """§19.40 / §19.66–§19.71 / §19.81–§19.85."""

    def test_only_deep_valid_workflow_executes_special_rule_items(self):
        triage = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        unknown = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        deep = run_defaults()
        self.assertEqual(
            [c for c in triage.checks if c.check_id.startswith("workflow.")],
            [],
        )
        self.assertEqual(
            [c for c in unknown.checks if c.check_id.startswith("workflow.")],
            [],
        )
        self.assertTrue(
            [c for c in deep.checks if c.check_id.startswith("workflow.")]
        )

    def test_itc_deterministic_rule_temporary_warning_exact_text(self):
        result = run_defaults()
        item = get_item(
            result.checks,
            "workflow.sec73_itc.special_rule.1.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Derived workflow validation is deferred until Step 8.3 requirement resolution.",
        )
        self.assertEqual(item.related_fact_ids, [])

    def test_itc_calculation_type_link_exact(self):
        result = run_defaults()
        item = get_item(
            result.checks,
            "workflow.sec73_itc.special_rule.1.deterministic_check",
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_general_temporary_warning(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec73_general.special_rule.1.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Derived workflow validation is deferred until Step 8.3 requirement resolution.",
        )

    def test_general_calculation_type_link_exact(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec73_general.special_rule.1.deterministic_check",
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE],
        )

    def test_fraud_rule_0_mirrors_generic_pass(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=fraud_clean_facts()),
        )
        item = get_item(
            result.checks,
            "workflow.sec74_fraud.special_rule.0.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Fraud/suppression allegations remain departmental allegations.",
        )
        self.assertEqual(item.related_fact_ids, [])
        self.assertEqual(item.related_calculation_types, [])

    def test_fraud_rule_0_mirrors_generic_fail_ids(self):
        offender = make_fact(
            "F-BAD", "Bad allegation", FactStatus.CONFIRMED, "b",
            DraftPermission.YES, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=[offender]),
        )
        item = get_item(
            result.checks,
            "workflow.sec74_fraud.special_rule.0.deterministic_check",
        )
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Fraud/suppression allegation status safety failed.",
        )
        generic = get_item(
            result.checks, "fact.department_allegation_status"
        )
        self.assertIs(generic.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, generic.related_fact_ids)
        self.assertEqual(item.related_fact_ids, ["F-BAD"])

    def test_fraud_rule_2_mirrors_source_text_pass(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=fraud_clean_facts()),
        )
        item = get_item(
            result.checks,
            "workflow.sec74_fraud.special_rule.2.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message, "Fraud-workflow fact provenance is present."
        )
        self.assertEqual(item.related_fact_ids, [])

    def test_fraud_rule_2_mirrors_source_text_fail_ids(self):
        offender = make_fact(
            "F-001", "No source", FactStatus.CONFIRMED, None,
            DraftPermission.YES, FactType.NOTICE_DATE, FactRole.NONE,
        )
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=[offender]),
        )
        item = get_item(
            result.checks,
            "workflow.sec74_fraud.special_rule.2.deterministic_check",
        )
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message, "Fraud-workflow fact provenance safety failed."
        )
        generic = get_item(result.checks, "fact.source_text_present")
        self.assertEqual(item.related_fact_ids, generic.related_fact_ids)
        self.assertEqual(item.related_fact_ids, ["F-001"])

    def test_sec129_deterministic_boundary_pass_exact_message(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.6.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Section-129 deadline handling uses only supplied preflight/deadline results; validation adds no statutory deadline calculation.",
        )
        self.assertEqual(item.related_fact_ids, [])
        self.assertEqual(item.related_calculation_types, [])

    def test_validation_source_contains_no_seven_day_computation(self):
        lowered = engine_source_text().lower()
        self.assertNotIn("seven", lowered)
        self.assertNotIn("timedelta", lowered)

    def test_future_legal_rule_warning_exact_message(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec73_rcm.special_rule.1.future_legal_rule",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "This workflow rule requires future verified legal-rule support and CA review.",
        )

    def test_upstream_invariant_pass_exact_message(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.2.upstream_invariant",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "This safety boundary is enforced by an authoritative upstream component and is not re-run by validation.",
        )

    def test_review_gate_check_warning(self):
        result = run_defaults()
        item = get_item(
            result.checks, "workflow.sec73_itc.special_rule.0.review_gate"
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.WARNING)

    def test_review_gate_exact_machine_id(self):
        result = run_defaults()
        self.assertIn(
            "workflow.sec73_itc.special_rule.0.review_gate",
            check_ids(result.checks),
        )

    def test_review_gate_message_contains_exact_special_rule_text(self):
        result = run_defaults()
        rule_text = GST_WORKFLOW_REGISTRY[
            ProceedingType.GST_SEC73_ITC
        ].special_rules[0]
        item = get_item(
            result.checks, "workflow.sec73_itc.special_rule.0.review_gate"
        )
        self.assertEqual(
            item.message, f"Mandatory review gate applies: {rule_text}"
        )

    def test_review_requirement_exact_id(self):
        result = run_defaults()
        self.assertIn(
            "workflow.sec73_itc.special_rule.0.review",
            review_ids(result.review_requirements),
        )

    def test_review_requirement_reason_is_exact_special_rule_text(self):
        result = run_defaults()
        rule_text = GST_WORKFLOW_REGISTRY[
            ProceedingType.GST_SEC73_ITC
        ].special_rules[0]
        review = next(
            r for r in result.review_requirements
            if r.review_id == "workflow.sec73_itc.special_rule.0.review"
        )
        self.assertEqual(review.reason, rule_text)
        self.assertTrue(review.mandatory)

    def test_exact_review_level_from_profile(self):
        result = run_defaults()
        review = next(
            r for r in result.review_requirements
            if r.review_id == "workflow.sec73_itc.special_rule.0.review"
        )
        self.assertIs(review.level, ReviewLevel.CA_REVIEW)

    def test_fraud_produces_senior_review(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=fraud_clean_facts()),
        )
        reviews = {
            r.review_id: r for r in result.review_requirements
        }
        self.assertIs(
            reviews["workflow.sec74_fraud.special_rule.1.review"].level,
            ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        )
        self.assertIs(
            reviews["workflow.sec74_fraud.special_rule.3.review"].level,
            ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        )

    def test_sec129_produces_urgent_review(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        review = next(
            r for r in result.review_requirements
            if r.review_id == "workflow.sec129.special_rule.6.review"
        )
        self.assertIs(review.level, ReviewLevel.URGENT_CA_REVIEW)

    def test_rcm_future_legal_rule_also_produces_review_gate(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        self.assertIn(
            "workflow.sec73_rcm.special_rule.1.future_legal_rule",
            check_ids(result.checks),
        )
        self.assertIn(
            "workflow.sec73_rcm.special_rule.1.review_gate",
            check_ids(result.checks),
        )
        self.assertIn(
            "workflow.sec73_rcm.special_rule.1.review",
            review_ids(result.review_requirements),
        )

    def test_no_semantic_interpretation_of_special_rule_strings(self):
        # The engine must not contain the workflow rule text — the strings
        # live in the workflow definitions and are only copied verbatim.
        source = engine_source_text()
        for snippet in (
            "Never assume invoices",
            "GSTR-3B versus GSTR-2B mismatch is not by itself proof",
            "Do not hardcode a 100% penalty assumption",
        ):
            self.assertNotIn(snippet, source)


# --- I. Review dedup --------------------------------------------------------

class ReviewDedupTests(unittest.TestCase):
    """§19.42 / §19.72."""

    def _run_with_mock_rules(self, rules, levels):
        workflow = make_mock_workflow(special_rules=rules)
        profile = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            handling={
                index: (SpecialRuleHandling.REVIEW_GATE,)
                for index in range(len(rules))
            },
            review_rules=dict(levels),
        )
        with mock.patch.object(engine, "get_workflow", return_value=workflow), \
             mock.patch.object(
                 engine, "get_validation_profile", return_value=profile
             ):
            return run_defaults(
                preflight=make_preflight(portal=False, authority=False)
            )

    def test_dedup_by_level_and_reason(self):
        result = self._run_with_mock_rules(
            ["Same rule.", "Same rule."],
            {0: ReviewLevel.CA_REVIEW, 1: ReviewLevel.CA_REVIEW},
        )
        self.assertEqual(len(result.review_requirements), 1)

    def test_first_review_id_preserved(self):
        result = self._run_with_mock_rules(
            ["Same rule.", "Same rule."],
            {0: ReviewLevel.CA_REVIEW, 1: ReviewLevel.CA_REVIEW},
        )
        self.assertEqual(
            result.review_requirements[0].review_id,
            "workflow.sec73_itc.special_rule.0.review",
        )

    def test_different_review_levels_not_merged(self):
        result = self._run_with_mock_rules(
            ["Rule A.", "Rule B."],
            {0: ReviewLevel.CA_REVIEW, 1: ReviewLevel.SENIOR_CA_OR_ADVOCATE},
        )
        self.assertEqual(len(result.review_requirements), 2)
        levels = {r.level for r in result.review_requirements}
        self.assertEqual(
            levels, {ReviewLevel.CA_REVIEW, ReviewLevel.SENIOR_CA_OR_ADVOCATE}
        )


# --- J. Overall status ------------------------------------------------------

class OverallStatusTests(unittest.TestCase):
    """§19.25 / §19.76 deterministic dominance."""

    def test_any_fail_dominates(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        self.assertIs(result.overall_status, ValidationStatus.FAIL)

    def test_warning_dominates_pass(self):
        result = run_defaults()
        self.assertIs(result.overall_status, ValidationStatus.WARNING)

    def test_all_pass_gives_pass_with_synthetic_configuration(self):
        workflow = make_mock_workflow()
        profile = make_mock_profile(proceeding_type=ProceedingType.GST_SEC73_ITC)
        with mock.patch.object(engine, "get_workflow", return_value=workflow), \
             mock.patch.object(
                 engine, "get_validation_profile", return_value=profile
             ):
            result = run_defaults(
                preflight=make_preflight(portal=False, authority=False)
            )
        self.assertIs(result.overall_status, ValidationStatus.PASS)
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_fail_semantics_are_product_safety_only(self):
        # ValidationEngineResult carries no legal-validity field.
        result = run_defaults()
        self.assertFalse(hasattr(result, "notice_valid"))
        self.assertFalse(hasattr(result, "legally_invalid"))


# --- K. Draft eligibility ---------------------------------------------------

class DraftEligibilityTests(unittest.TestCase):
    """§19.75 interim Step-8.2 blocking conditions."""

    def test_triage_only_blocked(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_unknown_blocked(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_extraction_failed_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_extraction_no_input_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_fact_invariant_fail_blocked(self):
        offender = make_fact(
            "F-001", "Other", FactStatus.CONFIRMED, "o",
            DraftPermission.YES, FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_arithmetic_structural_fail_blocked(self):
        bad = make_arithmetic(allowed_in_draft=DraftPermission.NO)
        result = run_defaults(arithmetic=[bad])
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_ordinary_mismatch_does_not_itself_block(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        self.assertIsNot(
            result.draft_eligibility, DraftEligibility.BLOCKED
        )

    def test_review_gate_makes_review_required(self):
        workflow = make_mock_workflow(special_rules=["Rule A."])
        profile = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            handling={0: (SpecialRuleHandling.REVIEW_GATE,)},
            review_rules={0: ReviewLevel.CA_REVIEW},
        )
        with mock.patch.object(engine, "get_workflow", return_value=workflow), \
             mock.patch.object(
                 engine, "get_validation_profile", return_value=profile
             ):
            result = run_defaults(
                preflight=make_preflight(portal=False, authority=False)
            )
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_preflight_warning_makes_review_required(self):
        workflow = make_mock_workflow()
        profile = make_mock_profile(proceeding_type=ProceedingType.GST_SEC73_ITC)
        with mock.patch.object(engine, "get_workflow", return_value=workflow), \
             mock.patch.object(
                 engine, "get_validation_profile", return_value=profile
             ):
            result = run_defaults(
                preflight=make_preflight(portal=True, authority=False)
            )
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_partial_extraction_makes_review_required(self):
        result = run_defaults(
            extraction=make_extraction(
                facts=clean_facts(), status=FactExtractionStatus.PARTIAL
            )
        )
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_empty_requirements_evidence_do_not_produce_allowed(self):
        result = run_defaults()
        self.assertEqual(result.requirements, [])
        self.assertEqual(result.evidence_checklist, [])
        self.assertIsNot(result.draft_eligibility, DraftEligibility.ALLOWED)


# --- L. Case severity -------------------------------------------------------

class CaseSeverityTests(unittest.TestCase):
    """§19.32."""

    def test_itc_default_medium(self):
        result = run_defaults()
        self.assertIs(result.case_severity, IssueSeverity.MEDIUM)

    def test_general_default_medium(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            )
        )
        self.assertIs(result.case_severity, IssueSeverity.MEDIUM)

    def test_rcm_default_medium(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        self.assertIs(result.case_severity, IssueSeverity.MEDIUM)

    def test_fraud_default_critical(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=fraud_clean_facts()),
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)

    def test_sec129_default_high(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        self.assertIs(result.case_severity, IssueSeverity.HIGH)

    def test_deadline_critical_overrides_to_critical(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)

    def test_deadline_passed_overrides_to_critical(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.PASSED)
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)

    def test_triage_no_urgent_deadline_none(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertIsNone(result.case_severity)

    def test_triage_critical_deadline_critical(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            ),
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL),
        )
        self.assertIs(result.case_severity, IssueSeverity.CRITICAL)


# --- M. Immutability / staging ---------------------------------------------

class ImmutabilityStagingTests(unittest.TestCase):
    """Inputs and static registry objects are never mutated; staged output
    stays empty."""

    def test_classification_not_mutated(self):
        classification = make_classification()
        snapshot = copy.deepcopy(classification)
        run_defaults(classification=classification)
        self.assertEqual(classification, snapshot)

    def test_extraction_result_and_facts_not_mutated(self):
        extraction = make_extraction(facts=clean_facts())
        snapshot = copy.deepcopy(extraction)
        run_defaults(extraction=extraction)
        self.assertEqual(extraction, snapshot)

    def test_preflight_result_not_mutated(self):
        preflight = make_preflight(stated_due=["F-001"])
        snapshot = copy.deepcopy(preflight)
        run_defaults(preflight=preflight)
        self.assertEqual(preflight, snapshot)

    def test_arithmetic_list_not_mutated(self):
        arithmetic = [make_arithmetic()]
        snapshot = copy.deepcopy(arithmetic)
        run_defaults(arithmetic=arithmetic)
        self.assertEqual(arithmetic, snapshot)

    def test_deadline_result_not_mutated(self):
        deadline = make_deadline()
        snapshot = copy.deepcopy(deadline)
        run_defaults(deadline=deadline)
        self.assertEqual(deadline, snapshot)

    def test_workflow_and_profile_static_objects_not_mutated(self):
        workflow = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_ITC]
        profile = VALIDATION_PROFILE_REGISTRY[ProceedingType.GST_SEC73_ITC]
        snapshot = (
            list(workflow.required_facts),
            list(workflow.special_rules),
            copy.deepcopy(profile.requirement_specs),
            copy.deepcopy(profile.special_rule_handling),
            copy.deepcopy(profile.review_rules),
        )
        run_defaults()
        self.assertEqual(list(workflow.required_facts), snapshot[0])
        self.assertEqual(list(workflow.special_rules), snapshot[1])
        self.assertEqual(profile.requirement_specs, snapshot[2])
        self.assertEqual(profile.special_rule_handling, snapshot[3])
        self.assertEqual(profile.review_rules, snapshot[4])

    def test_requirements_remain_empty(self):
        result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_evidence_checklist_remains_empty(self):
        result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_no_integration_import_from_app_or_notice_explainer(self):
        lowered = engine_source_text().lower()
        self.assertNotIn("notice_explainer", lowered)
        self.assertNotIn("import app", lowered)


def engine_source_text():
    return pathlib.Path(engine.__file__).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
