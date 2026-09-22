"""Unit tests for the generic deterministic Step-8.4 Validation Engine
(ARCHITECTURE_SPEC_v1_1 §19, §19.56–§19.117).

Fully offline and deterministic. No LLM calls, no network, no fixtures.

Verifies the complete Step-8.4 contract:

  - public API / pure-Python boundary (no LLM, no network, no engine
    recomputation, no source-code introspection, no upload/document
    matching, no filesystem evidence inference);
  - support gate and deep-workflow structural checks;
  - extraction health;
  - the ten fact safety invariants including the §19.5 FactRole
    compatibility table;
  - the five preflight checks;
  - deadline/hearing checks and the deadline urgent-review contract;
  - the six-check arithmetic structure, role provenance and
    status/result consistency;
  - deterministic workflow requirement resolution (Step 8.3): FACT and
    DERIVED selectors, statuses, absence-safety, structural-check
    reuse, ambiguity handling, stable machine IDs, and the two
    derived-difference special-rule replacements;
  - deterministic evidence checklist generation (Step 8.4): one
    UNKNOWN EvidenceChecklistItem per workflow evidence_requirements
    entry in exact workflow order with stable one-based "<prefix>.eN"
    IDs; evidence never becomes a ValidationItem and never enters
    overall status;
  - workflow special-rule handling (review gates, future legal rules,
    upstream invariants, the two fraud deterministic mirrors and the
    Section-129 deadline-source boundary);
  - ReviewRequirement dedup, overall status aggregation, the final
    §19.26 DraftEligibility including the requirement and evidence
    conditions, case severity, and input immutability.

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
    EvidenceChecklistItem,
    EvidenceStatus,
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
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewRequirement,
    SourceTextOrigin,
    SourceVerificationStatus,
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
    "fact.source_verification",
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
    evidence_requirements=None,
):
    return WorkflowDefinition(
        proceeding_type=proceeding_type,
        required_facts=[] if required_facts is None else list(required_facts),
        evidence_requirements=(
            [] if evidence_requirements is None
            else list(evidence_requirements)
        ),
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


# --- Step 8.3 requirement-resolution helpers ---------------------------------

ALL_DEEP_PROCEEDINGS = (
    ProceedingType.GST_SEC73_ITC,
    ProceedingType.GST_SEC73_GENERAL,
    ProceedingType.GST_SEC73_RCM,
    ProceedingType.GST_SEC74_FRAUD,
    ProceedingType.GST_SEC129_ENFORCE,
)

ITC_RULE_ID = "workflow.sec73_itc.special_rule.1.deterministic_check"
GENERAL_RULE_ID = "workflow.sec73_general.special_rule.1.deterministic_check"

DEEP_PROFILE_COUNTS = {
    ProceedingType.GST_SEC73_ITC: 5,
    ProceedingType.GST_SEC73_GENERAL: 5,
    ProceedingType.GST_SEC73_RCM: 5,
    ProceedingType.GST_SEC74_FRAUD: 5,
    ProceedingType.GST_SEC129_ENFORCE: 9,
}


def make_spec(
    requirement_id="mock.r0",
    requirement_text="Test requirement",
    kind=RequirementKind.FACT,
    fact_type=None,
    fact_role=None,
    calculation_type=None,
    accepted_fact_statuses=(FactStatus.CONFIRMED,),
    absent_on_success=RequirementStatus.MISSING,
):
    return WorkflowRequirementSpec(
        requirement_id=requirement_id,
        requirement_text=requirement_text,
        kind=kind,
        fact_type=fact_type,
        fact_role=fact_role,
        calculation_type=calculation_type,
        accepted_fact_statuses=accepted_fact_statuses,
        absent_on_success=absent_on_success,
    )


def make_custom_set(specs, proceeding_type=ProceedingType.GST_SEC73_ITC):
    """A synthetic workflow/profile pair driven by the given specs, with
    no special rules, so requirement behavior can be tested in
    isolation. required_facts mirrors the spec texts verbatim so
    requirement_alignment passes."""
    workflow = make_mock_workflow(
        proceeding_type=proceeding_type,
        required_facts=[spec.requirement_text for spec in specs],
    )
    profile = WorkflowValidationProfile(
        proceeding_type=proceeding_type,
        requirement_specs=list(specs),
        special_rule_handling={},
        review_rules={},
    )
    return workflow, profile


def run_custom(
    specs,
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    extraction=None,
    arithmetic=None,
    preflight=None,
    deadline=None,
):
    """run_defaults over a synthetic requirement set with a clean
    preflight (portal=False, authority=False) so requirement-driven
    outcomes can be observed in isolation."""
    workflow, profile = make_custom_set(specs, proceeding_type)
    classification = make_classification(proceeding_type=proceeding_type)
    with mock.patch.object(engine, "get_workflow", return_value=workflow), \
         mock.patch.object(
             engine, "get_validation_profile", return_value=profile
         ):
        return engine.run_validation(
            classification,
            extraction if extraction is not None else make_extraction(),
            preflight if preflight is not None else make_preflight(
                portal=False, authority=False
            ),
            arithmetic if arithmetic is not None else [],
            deadline,
        )


def get_requirement(result, requirement_id):
    for requirement in result.requirements:
        if requirement.requirement_id == requirement_id:
            return requirement
    return None


def requirement_item_ids(checks):
    return [
        item.check_id for item in checks
        if item.check_id.startswith("requirement.")
    ]


# --- Step 8.4 evidence-checklist helpers -------------------------------------

EVIDENCE_COUNTS = {
    ProceedingType.GST_SEC73_ITC: 5,
    ProceedingType.GST_SEC73_GENERAL: 3,
    ProceedingType.GST_SEC73_RCM: 4,
    ProceedingType.GST_SEC74_FRAUD: 5,
    ProceedingType.GST_SEC129_ENFORCE: 5,
}


def make_evidence_set(
    evidence_texts,
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    specs=None,
):
    """A synthetic workflow/profile carrying the given
    evidence_requirements with no required facts and no special rules,
    so requirement_alignment and special_rule_coverage pass."""
    workflow = make_mock_workflow(
        proceeding_type=proceeding_type,
        required_facts=[],
        evidence_requirements=list(evidence_texts),
    )
    profile = WorkflowValidationProfile(
        proceeding_type=proceeding_type,
        requirement_specs=[] if specs is None else list(specs),
        special_rule_handling={},
        review_rules={},
    )
    return workflow, profile


def run_evidence_custom(
    evidence_texts,
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    specs=None,
    extraction=None,
    preflight=None,
    arithmetic=None,
    deadline=None,
):
    """run_validation over a synthetic workflow whose
    evidence_requirements are the given texts, with a clean preflight,
    so evidence-checklist behavior can be observed in isolation."""
    workflow, profile = make_evidence_set(
        evidence_texts, proceeding_type, specs
    )
    classification = make_classification(proceeding_type=proceeding_type)
    with mock.patch.object(engine, "get_workflow", return_value=workflow), \
         mock.patch.object(
             engine, "get_validation_profile", return_value=profile
         ):
        return engine.run_validation(
            classification,
            extraction if extraction is not None else make_extraction(),
            preflight if preflight is not None else make_preflight(
                portal=False, authority=False
            ),
            arithmetic if arithmetic is not None else [],
            deadline,
        )


def make_preflight_with_indices(
    requested_document_fact_ids=(),
    referenced_annexure_fact_ids=(),
):
    """A clean preflight whose pass-through document/annexure indices
    point at the given fact IDs."""
    return PreflightResult(
        fact_extraction_status=FactExtractionStatus.SUCCESS,
        communication_identifier_status=CommunicationIdentifierStatus.RFN_PRESENT,
        portal_verification_required=False,
        authority_details_status=AuthorityDetailsStatus.PRESENT,
        authority_verification_required=False,
        stated_due_date_fact_ids=[],
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
        hearing_fact_ids=[],
        requested_document_fact_ids=list(requested_document_fact_ids),
        referenced_annexure_fact_ids=list(referenced_annexure_fact_ids),
    )


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

    def test_requirements_populated_only_for_usable_deep_profiles(self):
        # §19.110: one RequirementResult per spec for an eligible deep
        # profile; empty for TRIAGE_ONLY (and other unusable cases).
        deep = run_defaults()
        self.assertEqual(len(deep.requirements), 5)
        triage = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(triage.requirements, [])

    def test_evidence_checklist_populated_for_valid_deep_workflow(self):
        # Step 8.4 replaces the staged empty checklist: a usable deep
        # workflow renders one UNKNOWN item per evidence requirement.
        result = run_defaults()
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            [
                "sec73_itc.e1", "sec73_itc.e2", "sec73_itc.e3",
                "sec73_itc.e4", "sec73_itc.e5",
            ],
        )
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))

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
    """Phase-2 invariants plus Phase-3 source-verification safety."""

    def test_clean_facts_make_all_ten_invariant_checks_pass(self):
        result = run_defaults(extraction=make_extraction(facts=clean_facts()))
        for check_id in FACT_INVARIANT_IDS:
            item = get_item(result.checks, check_id)
            self.assertIsNotNone(item, check_id)
            self.assertIs(item.status, ValidationStatus.PASS, check_id)
            self.assertEqual(item.related_fact_ids, [], check_id)
            self.assertEqual(item.related_calculation_types, [], check_id)

    def test_unverified_ocr_source_fails_and_blocks_drafting(self):
        offender = make_fact(
            "F-OCR",
            "OCR-derived date",
            FactStatus.CONFIRMED,
            "Date: 17-08-2026",
            DraftPermission.YES,
            FactType.NOTICE_DATE,
            FactRole.NONE,
        )
        offender.source_origin = SourceTextOrigin.OCR
        offender.source_verification = (
            SourceVerificationStatus.REQUIRES_VERIFICATION
        )
        result = run_defaults(
            extraction=make_extraction(facts=[offender])
        )
        item = get_item(result.checks, "fact.source_verification")
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["F-OCR"])
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

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
        FactRole.NOTICE_SERVICE_DATE,
        FactRole.RESPONSE_PERIOD,
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

    def test_itc_deterministic_rule_resolution_warning_without_arithmetic(self):
        # §19.107: no arithmetic means no resolved ITC difference, so the
        # special rule warns with the Step-8.3 message.
        result = run_defaults()
        item = get_item(
            result.checks,
            "workflow.sec73_itc.special_rule.1.deterministic_check",
        )
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement could not be resolved from one sufficient arithmetic result.",
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

    def test_general_deterministic_rule_resolution_warning_without_arithmetic(self):
        # §19.108: no arithmetic means no resolved output-tax difference.
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
            "Deterministic output-tax-difference workflow requirement could not be resolved from one sufficient arithmetic result.",
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

    def test_unresolved_evidence_does_not_produce_allowed(self):
        # §19.26/§19.43: the Step-8.4 UNKNOWN evidence items keep the
        # default deep run out of ALLOWED.
        result = run_defaults()
        self.assertEqual(len(result.requirements), 5)
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))
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

    def test_requirements_empty_only_for_unusable_workflows(self):
        # §19.110: resolved for a usable deep profile, empty for triage.
        deep = run_defaults()
        self.assertEqual(len(deep.requirements), 5)
        triage = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(triage.requirements, [])

    def test_evidence_checklist_populated_for_deep_workflow(self):
        result = run_defaults()
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))

    def test_no_integration_import_from_app_or_notice_explainer(self):
        lowered = engine_source_text().lower()
        self.assertNotIn("notice_explainer", lowered)
        self.assertNotIn("import app", lowered)


# --- Step 8.3 N. Requirement processing gate / order (§19.90, §19.111) -------

class RequirementGateTests(unittest.TestCase):
    """Requirement resolution runs only for eligible usable deep
    workflows, and its output lands in the §19.112 processing order."""

    def test_deep_valid_profile_produces_requirements(self):
        result = run_defaults()
        self.assertEqual(len(result.requirements), 5)
        self.assertEqual(
            [r.requirement_id for r in result.requirements],
            [
                "sec73_itc.r1", "sec73_itc.r2", "sec73_itc.r3",
                "sec73_itc.r4", "sec73_itc.r5",
            ],
        )

    def test_triage_only_produces_empty_requirements(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(result.requirements, [])
        self.assertEqual(requirement_item_ids(result.checks), [])

    def test_unknown_support_produces_empty_requirements(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        self.assertEqual(result.requirements, [])

    def test_unknown_proceeding_produces_empty_requirements(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN
            )
        )
        self.assertEqual(result.requirements, [])

    def test_missing_workflow_produces_empty_requirements(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_missing_profile_produces_empty_requirements(self):
        with mock.patch.object(
            engine, "get_validation_profile", return_value=None
        ):
            result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_workflow_misalignment_produces_empty_requirements(self):
        wrong = make_mock_workflow(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(engine, "get_workflow", return_value=wrong):
            result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_profile_misalignment_produces_empty_requirements(self):
        wrong = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        self.assertEqual(result.requirements, [])

    def test_requirement_alignment_fail_produces_empty_requirements(self):
        wrong = make_mock_profile(requirement_texts=["Different text."])
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        self.assertEqual(result.requirements, [])
        self.assertEqual(requirement_item_ids(result.checks), [])

    def test_requirement_results_follow_exact_profile_order(self):
        result = run_defaults()
        profile = get_validation_profile(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(
            [r.requirement_id for r in result.requirements],
            [spec.requirement_id for spec in profile.requirement_specs],
        )

    def test_requirement_validation_items_follow_same_order(self):
        result = run_defaults()
        profile = get_validation_profile(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(
            requirement_item_ids(result.checks),
            [
                f"requirement.{spec.requirement_id}"
                for spec in profile.requirement_specs
            ],
        )

    def test_requirement_checks_precede_workflow_special_rule_checks(self):
        # §19.112: requirement resolution (step 7) runs before special
        # rules (step 8).
        result = run_defaults()
        requirement_indices = [
            index for index, item in enumerate(result.checks)
            if item.check_id.startswith("requirement.")
        ]
        workflow_indices = [
            index for index, item in enumerate(result.checks)
            if item.check_id.startswith("workflow.")
        ]
        self.assertTrue(requirement_indices)
        self.assertTrue(workflow_indices)
        self.assertLess(
            max(requirement_indices), min(workflow_indices)
        )


# --- Step 8.3 O. FACT selector matching (§19.91) -----------------------------

class FactRequirementSelectorTests(unittest.TestCase):
    """Exact enum selectors; FactRole.NONE is real, Python None is the
    only wildcard; claim/source_text never satisfy a requirement."""

    def _run_itc(self, facts):
        return run_defaults(extraction=make_extraction(facts=facts))

    def test_fact_type_selector_exact(self):
        # Correct role, wrong type: must not match sec73_itc.r1.
        fact = make_fact(
            "F-001", "3B ITC", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.TAX_PERIOD,
            FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )
        requirement = get_requirement(self._run_itc([fact]), "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.MISSING)

    def test_fact_role_selector_exact(self):
        # Correct type, wrong role: must not match sec73_itc.r1, while
        # the same fact satisfies the matching role requirement r5.
        fact = make_fact(
            "F-001", "Interest", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.STATED_AMOUNT,
            FactRole.INTEREST_PROPOSED_AMOUNT,
        )
        result = self._run_itc([fact])
        self.assertIs(
            get_requirement(result, "sec73_itc.r1").status,
            RequirementStatus.MISSING,
        )
        self.assertIs(
            get_requirement(result, "sec73_itc.r5").status,
            RequirementStatus.SATISFIED,
        )

    def test_fact_role_none_member_is_a_real_selector(self):
        # sec73_itc.r4 selects TAX_PERIOD + FactRole.NONE exactly.
        wrong_role = make_fact(
            "F-001", "Period", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.TAX_PERIOD,
            FactRole.EXPLICIT_PROCEDURAL_DATE,
        )
        self.assertIs(
            get_requirement(self._run_itc([wrong_role]), "sec73_itc.r4").status,
            RequirementStatus.MISSING,
        )
        right_role = make_fact(
            "F-002", "Period", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.TAX_PERIOD, FactRole.NONE,
        )
        self.assertIs(
            get_requirement(self._run_itc([right_role]), "sec73_itc.r4").status,
            RequirementStatus.SATISFIED,
        )

    def test_python_none_fact_type_is_a_wildcard(self):
        # sec129.r8: fact_type None + EXPLICIT_PROCEDURAL_DATE → every
        # procedurally compatible type matches.
        for fact_type in (
            FactType.STATED_DUE_DATE,
            FactType.HEARING_DETAILS,
            FactType.DOCUMENT_DETAIL,
        ):
            fact = make_fact(
                "F-001", "Date", FactStatus.CONFIRMED, "x",
                DraftPermission.YES, fact_type,
                FactRole.EXPLICIT_PROCEDURAL_DATE,
            )
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=ProceedingType.GST_SEC129_ENFORCE
                ),
                extraction=make_extraction(facts=[fact]),
            )
            requirement = get_requirement(result, "sec129.r8")
            self.assertIs(
                requirement.status, RequirementStatus.SATISFIED,
                fact_type.name,
            )

    def test_all_supplied_selectors_must_match(self):
        # A fact matching neither, only the type, or only the role of a
        # two-selector requirement never satisfies it.
        neither = make_fact(
            "F-001", "Other", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        type_only = make_fact(
            "F-002", "Amount", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.STATED_AMOUNT, FactRole.NONE,
        )
        role_only = make_fact(
            "F-003", "Amount", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.OTHER_NOTICE_FACT,
            FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )
        requirement = get_requirement(
            self._run_itc([neither, type_only, role_only]),
            "sec73_itc.r1",
        )
        self.assertIs(requirement.status, RequirementStatus.MISSING)

    def test_claim_text_cannot_satisfy_a_requirement(self):
        fact = make_fact(
            "F-001", "ITC claimed in GSTR-3B (amount)",
            FactStatus.CONFIRMED, "x", DraftPermission.YES,
            FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        requirement = get_requirement(self._run_itc([fact]), "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.MISSING)

    def test_source_text_cannot_satisfy_a_requirement(self):
        fact = make_fact(
            "F-001", "Claim", FactStatus.CONFIRMED,
            "ITC claimed in GSTR-3B (amount)", DraftPermission.YES,
            FactType.OTHER_NOTICE_FACT, FactRole.NONE,
        )
        requirement = get_requirement(self._run_itc([fact]), "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.MISSING)


# --- Step 8.3 P. FACT requirement statuses (§19.92–§19.97) -------------------

class FactRequirementStatusTests(unittest.TestCase):
    """Fixed precedence: accepted → REQUIRES_VERIFICATION → UNKNOWN →
    absence (SUCCESS: absent_on_success, otherwise UNKNOWN)."""

    def _r1_fact(self, fact_id, status, allowed_in_draft=DraftPermission.YES):
        return make_fact(
            fact_id, "3B ITC", status, "x", allowed_in_draft,
            FactType.STATED_AMOUNT, FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )

    def test_accepted_fact_satisfied_and_pass(self):
        result = run_defaults(
            extraction=make_extraction(
                facts=[self._r1_fact("F-001", FactStatus.CONFIRMED)]
            )
        )
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.SATISFIED)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])
        self.assertIsNone(requirement.calculation_type)
        item = get_item(result.checks, "requirement.sec73_itc.r1")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Workflow requirement is satisfied: ITC claimed in GSTR-3B (amount)",
        )
        self.assertEqual(item.related_fact_ids, ["F-001"])
        self.assertEqual(item.related_calculation_types, [])

    def test_multiple_accepted_facts_all_related_in_extraction_order(self):
        facts = [
            self._r1_fact("F-002", FactStatus.CONFIRMED),
            self._r1_fact("F-001", FactStatus.CONFIRMED),
        ]
        requirement = get_requirement(
            run_defaults(extraction=make_extraction(facts=facts)),
            "sec73_itc.r1",
        )
        self.assertIs(requirement.status, RequirementStatus.SATISFIED)
        self.assertEqual(requirement.related_fact_ids, ["F-002", "F-001"])

    def test_unaccepted_matching_facts_excluded_when_accepted_exists(self):
        facts = [
            self._r1_fact("F-001", FactStatus.CONFIRMED),
            self._r1_fact(
                "F-002", FactStatus.REQUIRES_VERIFICATION,
                DraftPermission.NO,
            ),
        ]
        requirement = get_requirement(
            run_defaults(extraction=make_extraction(facts=facts)),
            "sec73_itc.r1",
        )
        self.assertIs(requirement.status, RequirementStatus.SATISFIED)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])

    def test_rcm_alleged_requirement_satisfies_with_alleged(self):
        fact = make_fact(
            "F-001", "RCM category", FactStatus.ALLEGED, "x",
            DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
            FactRole.RCM_CATEGORY_ALLEGED,
        )
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            ),
            extraction=make_extraction(facts=[fact]),
        )
        self.assertIs(
            get_requirement(result, "sec73_rcm.r1").status,
            RequirementStatus.SATISFIED,
        )

    def test_fraud_alleged_requirement_satisfies_with_alleged(self):
        fact = make_fact(
            "F-001", "Basis", FactStatus.ALLEGED, "x",
            DraftPermission.CONDITIONAL, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=[fact]),
        )
        self.assertIs(
            get_requirement(result, "sec74_fraud.r1").status,
            RequirementStatus.SATISFIED,
        )

    def test_confirmed_does_not_satisfy_alleged_only_requirement(self):
        fact = make_fact(
            "F-001", "Basis", FactStatus.CONFIRMED, "x",
            DraftPermission.YES, FactType.DEPARTMENT_ALLEGATION,
            FactRole.FRAUD_BASIS_ALLEGED,
        )
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=[fact]),
        )
        requirement = get_requirement(result, "sec74_fraud.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])

    def test_matching_requires_verification_fact_resolves_requires_verification(self):
        fact = self._r1_fact(
            "F-001", FactStatus.REQUIRES_VERIFICATION, DraftPermission.NO
        )
        result = run_defaults(extraction=make_extraction(facts=[fact]))
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.REQUIRES_VERIFICATION)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])
        item = get_item(result.checks, "requirement.sec73_itc.r1")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement requires verification: ITC claimed in GSTR-3B (amount)",
        )

    def test_matching_nonaccepted_non_rv_fact_resolves_unknown(self):
        fact = self._r1_fact(
            "F-001", FactStatus.ALLEGED, DraftPermission.CONDITIONAL
        )
        result = run_defaults(extraction=make_extraction(facts=[fact]))
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])
        item = get_item(result.checks, "requirement.sec73_itc.r1")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement status is unknown: ITC claimed in GSTR-3B (amount)",
        )

    def test_no_match_on_success_missing_by_default(self):
        result = run_defaults()
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.MISSING)
        self.assertEqual(requirement.related_fact_ids, [])
        item = get_item(result.checks, "requirement.sec73_itc.r1")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement is missing from a successful extraction: ITC claimed in GSTR-3B (amount)",
        )

    def test_sec129_r6_no_match_on_success_requires_verification(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        requirement = get_requirement(result, "sec129.r6")
        self.assertIs(requirement.status, RequirementStatus.REQUIRES_VERIFICATION)
        item = get_item(result.checks, "requirement.sec129.r6")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement requires verification: Value of goods and tax payable on the goods where stated and relevant to penalty computation",
        )

    def test_sec129_r7_no_match_on_success_requires_verification(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        requirement = get_requirement(result, "sec129.r7")
        self.assertIs(requirement.status, RequirementStatus.REQUIRES_VERIFICATION)
        item = get_item(result.checks, "requirement.sec129.r7")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement requires verification: Whether the owner of the goods has come forward, where relevant and determinable",
        )

    def test_sec129_r9_no_match_on_success_requires_verification(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        requirement = get_requirement(result, "sec129.r9")
        self.assertIs(requirement.status, RequirementStatus.REQUIRES_VERIFICATION)
        item = get_item(result.checks, "requirement.sec129.r9")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement requires verification: Order date / current enforcement status if an order has already been issued",
        )

    def test_no_match_on_partial_unknown_not_missing(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.PARTIAL)
        )
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        item = get_item(result.checks, "requirement.sec73_itc.r1")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Workflow requirement status is unknown because fact extraction was not fully successful: ITC claimed in GSTR-3B (amount)",
        )

    def test_no_match_on_failed_unknown_not_missing(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertNotIn("missing", get_item(
            result.checks, "requirement.sec73_itc.r1"
        ).message.lower())

    def test_no_match_on_no_input_unknown_not_missing(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertNotIn("missing", get_item(
            result.checks, "requirement.sec73_itc.r1"
        ).message.lower())

    def test_fact_requirement_calculation_type_always_none(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            profile = get_validation_profile(proceeding_type)
            kinds = {
                spec.requirement_id: spec.kind
                for spec in profile.requirement_specs
            }
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            for requirement in result.requirements:
                if kinds[requirement.requirement_id] == RequirementKind.FACT:
                    self.assertIsNone(
                        requirement.calculation_type,
                        requirement.requirement_id,
                    )

    def test_exact_requirement_messages(self):
        # Templates for the remaining default-run states, verbatim.
        result = run_defaults()
        expected = {
            "requirement.sec73_itc.r1":
                "Workflow requirement is missing from a successful extraction: ITC claimed in GSTR-3B (amount)",
            "requirement.sec73_itc.r3":
                "Derived workflow requirement has no matching arithmetic result: Difference between GSTR-3B and GSTR-2B (INFERRED)",
            "requirement.sec73_itc.r4":
                "Workflow requirement is missing from a successful extraction: FY / tax period",
        }
        for check_id, message in expected.items():
            self.assertEqual(get_item(result.checks, check_id).message, message)

    def test_only_usable_non_empty_related_ids(self):
        facts = [
            self._r1_fact("F-001", FactStatus.CONFIRMED),
            self._r1_fact("", FactStatus.CONFIRMED),
            self._r1_fact(None, FactStatus.CONFIRMED),
        ]
        requirement = get_requirement(
            run_defaults(extraction=make_extraction(facts=facts)),
            "sec73_itc.r1",
        )
        self.assertIs(requirement.status, RequirementStatus.SATISFIED)
        self.assertEqual(requirement.related_fact_ids, ["F-001"])

    def test_matching_facts_are_never_mutated(self):
        facts = [
            self._r1_fact("F-001", FactStatus.CONFIRMED),
            self._r1_fact(
                "F-002", FactStatus.REQUIRES_VERIFICATION,
                DraftPermission.NO,
            ),
        ]
        snapshot = copy.deepcopy(facts)
        run_defaults(extraction=make_extraction(facts=facts))
        self.assertEqual(facts, snapshot)


# --- Step 8.3 Q. DERIVED requirement resolution (§19.98–§19.103) -------------

class DerivedRequirementTests(unittest.TestCase):
    """DERIVED resolution reuses the already-emitted Step-8.2 structural
    arithmetic checks; never recomputes arithmetic."""

    def test_itc_single_valid_pass_result_derived(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)
        self.assertEqual(requirement.related_fact_ids, ["A", "B"])
        self.assertEqual(
            requirement.calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Workflow requirement is deterministically derived: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )
        self.assertEqual(item.related_fact_ids, ["A", "B"])
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_itc_single_valid_mismatch_result_derived(self):
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
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)
        # The mismatch stays communicated by the arithmetic outcome item.
        outcome = get_item(result.checks, "arithmetic.1.outcome")
        self.assertIs(outcome.status, ValidationStatus.WARNING)

    def test_general_single_valid_pass_result_derived(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            ),
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        )
        requirement = get_requirement(result, "sec73_general.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)

    def test_general_single_valid_mismatch_result_derived(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            ),
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                )
            ],
        )
        requirement = get_requirement(result, "sec73_general.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)

    def test_mismatch_requirement_check_remains_pass(self):
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
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertIs(item.status, ValidationStatus.PASS)

    def test_insufficient_data_unknown_warning(self):
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
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, ["A", "B"])
        self.assertEqual(
            requirement.calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Derived workflow requirement has insufficient arithmetic data: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )

    def test_zero_matching_results_unknown_warning(self):
        result = run_defaults()
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, [])
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Derived workflow requirement has no matching arithmetic result: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_draft_permission_failure_unknown_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    source_fact_ids=["A", "B"],
                    allowed_in_draft=DraftPermission.YES,
                )
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertEqual(
            item.message,
            "Derived workflow requirement cannot be trusted because its arithmetic result failed structural validation: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )

    def test_source_resolution_failure_unknown_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "MISSING"])
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, ["A", "MISSING"])

    def test_role_provenance_failure_unknown_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(requirement.related_fact_ids, ["B", "A"])

    def test_consistency_failure_unknown_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    source_fact_ids=["A", "B"], result=Decimal("5")
                )
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)

    def test_calculation_type_failure_unknown_warning(self):
        # A matching enum calculation type whose calculation_type check
        # FAILs is only reachable by forcing the emitted Step-8.2 item.
        real = engine._arithmetic_checks

        def wrapper(checks, n, result, facts):
            real(checks, n, result, facts)
            for index, item in enumerate(checks):
                if item.check_id == f"arithmetic.{n}.calculation_type":
                    checks[index] = ValidationItem(
                        check_id=item.check_id,
                        status=ValidationStatus.FAIL,
                        message="Arithmetic calculation type is unsupported.",
                        related_fact_ids=[],
                        related_calculation_types=[],
                    )

        with mock.patch.object(
            engine, "_arithmetic_checks", side_effect=wrapper
        ):
            result = run_defaults(
                extraction=make_extraction(facts=itc_operand_facts()),
                arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
            )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        item = get_item(result.checks, "requirement.sec73_itc.r3")
        self.assertEqual(
            item.message,
            "Derived workflow requirement cannot be trusted because its arithmetic result failed structural validation: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )

    def test_outcome_warning_is_not_structural(self):
        # MISMATCH with a non-zero result: outcome WARNING while all five
        # structural checks PASS → requirement still DERIVED.
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
        outcome = get_item(result.checks, "arithmetic.1.outcome")
        self.assertIs(outcome.status, ValidationStatus.WARNING)
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)

    def test_exactly_five_structural_checks_consulted(self):
        looked_up = []
        real_find = engine._find_item

        def spy(checks, check_id):
            looked_up.append(check_id)
            return real_find(checks, check_id)

        with mock.patch.object(engine, "_find_item", side_effect=spy):
            run_defaults(
                extraction=make_extraction(facts=itc_operand_facts()),
                arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
            )
        arithmetic_lookups = {
            check_id for check_id in looked_up
            if check_id.startswith("arithmetic.")
        }
        self.assertEqual(
            arithmetic_lookups,
            {
                "arithmetic.1.calculation_type",
                "arithmetic.1.draft_permission",
                "arithmetic.1.source_resolution",
                "arithmetic.1.role_provenance",
                "arithmetic.1.result_status_consistency",
            },
        )

    def test_requirement_resolver_does_not_recompute_arithmetic(self):
        with mock.patch.object(
            engine, "_arithmetic_checks", wraps=engine._arithmetic_checks
        ) as spy:
            run_defaults(
                extraction=make_extraction(facts=itc_operand_facts()),
                arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
            )
        self.assertEqual(spy.call_count, 1)

    def test_source_ids_preserve_stored_operand_order(self):
        facts = [
            make_fact(
                "X", "3B", FactStatus.CONFIRMED, "x", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            make_fact(
                "W", "2B", FactStatus.CONFIRMED, "w", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
        ]
        result = run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=[make_arithmetic(source_fact_ids=["X", "W"])],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)
        self.assertEqual(requirement.related_fact_ids, ["X", "W"])

    def test_unusable_source_ids_excluded(self):
        facts = [
            make_fact(
                123, "3B", FactStatus.CONFIRMED, "x", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            make_fact(
                "B", "2B", FactStatus.CONFIRMED, "y", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
        ]
        result = run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=[make_arithmetic(source_fact_ids=[123, "B"])],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)
        self.assertEqual(requirement.related_fact_ids, ["B"])

    def test_calculation_type_populated_on_derived_and_unknown_results(self):
        derived = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        self.assertIs(
            get_requirement(derived, "sec73_itc.r3").calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        unknown_zero = run_defaults()
        self.assertIs(
            get_requirement(unknown_zero, "sec73_itc.r3").calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        unknown_failed = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        self.assertIs(
            get_requirement(unknown_failed, "sec73_itc.r3").calculation_type,
            ArithmeticCalculationType.ITC_DIFFERENCE,
        )


# --- Step 8.3 R. Multiple matching arithmetic results (§19.104) --------------

class MultipleArithmeticAmbiguityTests(unittest.TestCase):
    """Two or more matching results → UNKNOWN with the ambiguity
    WARNING; the engine never selects one arbitrarily."""

    def _two_valid(self):
        return run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        )

    def test_two_matching_results_unknown(self):
        requirement = get_requirement(self._two_valid(), "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)

    def test_does_not_select_first_result(self):
        # First structurally valid, second structurally invalid → still
        # UNKNOWN.
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["B", "A"]),
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)

    def test_does_not_prefer_pass_over_mismatch(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                ),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)

    def test_does_not_prefer_mismatch_over_pass(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(
                    status=ArithmeticStatus.MISMATCH,
                    source_fact_ids=["A", "B"],
                    result=Decimal("5"),
                ),
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)

    def test_does_not_prefer_structurally_valid_result(self):
        for arithmetic in (
            [
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["A", "MISSING"]),
            ],
            [
                make_arithmetic(source_fact_ids=["A", "MISSING"]),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        ):
            result = run_defaults(
                extraction=make_extraction(facts=itc_operand_facts()),
                arithmetic=arithmetic,
            )
            self.assertIs(
                get_requirement(result, "sec73_itc.r3").status,
                RequirementStatus.UNKNOWN,
            )

    def test_exact_ambiguity_message(self):
        item = get_item(self._two_valid().checks, "requirement.sec73_itc.r3")
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Derived workflow requirement is ambiguous because multiple arithmetic results match: Difference between GSTR-3B and GSTR-2B (INFERRED)",
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_one_requirement_item_only(self):
        matches = [
            item for item in self._two_valid().checks
            if item.check_id == "requirement.sec73_itc.r3"
        ]
        self.assertEqual(len(matches), 1)

    def test_related_ids_aggregate_in_input_and_operand_order(self):
        facts = [
            make_fact(
                "A", "3B", FactStatus.CONFIRMED, "a", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            make_fact(
                "B", "2B", FactStatus.CONFIRMED, "b", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
            make_fact(
                "C", "3B", FactStatus.CONFIRMED, "c", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            make_fact(
                "D", "2B", FactStatus.CONFIRMED, "d", DraftPermission.YES,
                FactType.STATED_AMOUNT,
                FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
        ]
        result = run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["C", "D"]),
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertEqual(
            requirement.related_fact_ids, ["A", "B", "C", "D"]
        )

    def test_duplicate_source_ids_first_occurrence_dedup(self):
        requirement = get_requirement(self._two_valid(), "sec73_itc.r3")
        self.assertEqual(requirement.related_fact_ids, ["A", "B"])

    def test_unrelated_calculation_types_ignored(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                ),
            ],
        )
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)


# --- Step 8.3 S. Stable requirement machine IDs (§19.89) ---------------------

class StableRequirementIdTests(unittest.TestCase):
    """check_id is always "requirement." + requirement_id; never the
    requirement text."""

    def test_itc_r1_id_exact(self):
        self.assertIn(
            "requirement.sec73_itc.r1", check_ids(run_defaults().checks)
        )

    def test_itc_r3_id_exact(self):
        self.assertIn(
            "requirement.sec73_itc.r3", check_ids(run_defaults().checks)
        )

    def test_general_r3_id_exact(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            )
        )
        self.assertIn(
            "requirement.sec73_general.r3", check_ids(result.checks)
        )

    def test_sec129_r9_id_exact(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        self.assertIn("requirement.sec129.r9", check_ids(result.checks))

    def test_all_29_ids_equal_requirement_prefix_plus_id(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            profile = get_validation_profile(proceeding_type)
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            expected = {
                f"requirement.{spec.requirement_id}"
                for spec in profile.requirement_specs
            }
            emitted = {
                item.check_id for item in result.checks
                if item.check_id.startswith("requirement.")
            }
            self.assertEqual(emitted, expected, proceeding_type.name)

    def test_no_requirement_text_appears_in_machine_id(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            profile = get_validation_profile(proceeding_type)
            texts = {
                spec.requirement_text for spec in profile.requirement_specs
            }
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            for item in result.checks:
                if item.check_id.startswith("requirement."):
                    for text in texts:
                        self.assertNotIn(
                            text, item.check_id, item.check_id
                        )


# --- Step 8.3 T. ITC derived special-rule replacement (§19.107) --------------

class ItcDerivedRuleReplacementTests(unittest.TestCase):
    """The resolved sec73_itc.r3 drives workflow rule 1; the Step-8.2
    temporary message must never appear."""

    def _derived(self):
        return run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )

    def test_temporary_deferral_message_never_emitted(self):
        self.assertNotIn("deferred until Step 8.3", engine_source_text())
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            for item in result.checks:
                self.assertNotIn(
                    "deferred until Step 8.3", item.message, item.check_id
                )

    def test_derived_requirement_makes_special_rule_pass(self):
        item = get_item(self._derived().checks, ITC_RULE_ID)
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)

    def test_exact_derived_pass_message(self):
        item = get_item(self._derived().checks, ITC_RULE_ID)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement is derived from approved arithmetic output.",
        )
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_related_ids_copied_from_r3(self):
        result = self._derived()
        requirement = get_requirement(result, "sec73_itc.r3")
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertEqual(item.related_fact_ids, requirement.related_fact_ids)
        self.assertEqual(item.related_fact_ids, ["A", "B"])

    def test_no_matching_result_warning(self):
        result = run_defaults()
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement could not be resolved from one sufficient arithmetic result.",
        )
        self.assertEqual(item.related_fact_ids, [])
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_insufficient_data_warning(self):
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
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement could not be resolved from one sufficient arithmetic result.",
        )

    def test_multiple_matches_warning(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(item.related_fact_ids, ["A", "B"])

    def test_matching_structural_failure_fail(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.FAIL)

    def test_exact_structural_fail_message(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement failed arithmetic structural validation.",
        )

    def test_structural_fail_related_ids_aggregated(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertEqual(item.related_fact_ids, ["B", "A"])

    def test_structural_fail_multiple_results_dedup_by_first_occurrence(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["B", "A"]),
            ],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(item.related_fact_ids, ["A", "B"])

    def test_calculation_type_exact_itc_difference_in_all_outcomes(self):
        cases = (
            {},  # no arithmetic → WARNING
            {
                "extraction": make_extraction(facts=itc_operand_facts()),
                "arithmetic": [make_arithmetic(source_fact_ids=["A", "B"])],
            },  # DERIVED → PASS
            {
                "extraction": make_extraction(facts=itc_operand_facts()),
                "arithmetic": [make_arithmetic(source_fact_ids=["B", "A"])],
            },  # structural fail → FAIL
        )
        for kwargs in cases:
            result = run_defaults(**kwargs)
            item = get_item(result.checks, ITC_RULE_ID)
            self.assertEqual(
                item.related_calculation_types,
                [ArithmeticCalculationType.ITC_DIFFERENCE],
            )


# --- Step 8.3 U. GENERAL derived special-rule replacement (§19.108) ----------

class GeneralDerivedRuleReplacementTests(unittest.TestCase):
    """The resolved sec73_general.r3 drives workflow rule 1."""

    def _run(self, **kwargs):
        kwargs.setdefault(
            "classification",
            make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            ),
        )
        return run_defaults(**kwargs)

    def test_derived_requirement_makes_special_rule_pass(self):
        result = self._run(
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        )
        item = get_item(result.checks, GENERAL_RULE_ID)
        self.assertIsNotNone(item)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Deterministic output-tax-difference workflow requirement is derived from approved arithmetic output.",
        )
        self.assertEqual(item.related_fact_ids, ["A", "B"])

    def test_unresolved_warning(self):
        result = self._run()
        item = get_item(result.checks, GENERAL_RULE_ID)
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "Deterministic output-tax-difference workflow requirement could not be resolved from one sufficient arithmetic result.",
        )

    def test_matching_structural_failure_fail(self):
        result = self._run(
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["B", "A"],
                )
            ],
        )
        item = get_item(result.checks, GENERAL_RULE_ID)
        self.assertIs(item.status, ValidationStatus.FAIL)
        self.assertEqual(
            item.message,
            "Deterministic output-tax-difference workflow requirement failed arithmetic structural validation.",
        )

    def test_calculation_type_exact_output_tax_difference(self):
        result = self._run(
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        )
        item = get_item(result.checks, GENERAL_RULE_ID)
        self.assertEqual(
            item.related_calculation_types,
            [ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE],
        )

    def test_temporary_message_absent_in_general_runs(self):
        for arithmetic in (
            [],
            [
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        ):
            result = self._run(
                extraction=make_extraction(facts=output_tax_operand_facts()),
                arithmetic=arithmetic,
            )
            for item in result.checks:
                self.assertNotIn(
                    "deferred until Step 8.3", item.message, item.check_id
                )


# --- Step 8.3 V. Special-rule regression (§19.83–§19.85) ---------------------

class SpecialRuleRegressionTests(unittest.TestCase):
    """Only ITC/GENERAL rule 1 changed in Step 8.3; everything else keeps
    its Step-8.2 semantics."""

    def test_fraud_rule_0_unchanged(self):
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
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Fraud/suppression allegations remain departmental allegations.",
        )

    def test_fraud_rule_2_unchanged(self):
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
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Fraud-workflow fact provenance is present.",
        )

    def test_sec129_rule_6_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.6.deterministic_check",
        )
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Section-129 deadline handling uses only supplied preflight/deadline results; validation adds no statutory deadline calculation.",
        )

    def test_review_gate_unchanged(self):
        result = run_defaults()
        item = get_item(
            result.checks, "workflow.sec73_itc.special_rule.0.review_gate"
        )
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertTrue(
            item.message.startswith("Mandatory review gate applies:")
        )

    def test_future_legal_rule_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec73_rcm.special_rule.1.future_legal_rule",
        )
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "This workflow rule requires future verified legal-rule support and CA review.",
        )

    def test_upstream_invariant_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.2.upstream_invariant",
        )
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "This safety boundary is enforced by an authoritative upstream component and is not re-run by validation.",
        )


# --- Step 8.3 W. Requirement-driven eligibility (§19.106) --------------------

class RequirementEligibilityTests(unittest.TestCase):
    """MISSING/UNKNOWN/REQUIRES_VERIFICATION force at least
    REVIEW_REQUIRED; SATISFIED/DERIVED never force review alone;
    BLOCKED conditions remain dominant."""

    def test_missing_requirement_forces_review_required(self):
        result = run_custom([make_spec()])
        requirement = get_requirement(result, "mock.r0")
        self.assertIs(requirement.status, RequirementStatus.MISSING)
        self.assertIsNot(result.draft_eligibility, DraftEligibility.BLOCKED)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_unknown_requirement_forces_review_required(self):
        spec = make_spec(
            requirement_id="mock.d1",
            requirement_text="Derived value",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        result = run_custom([spec])
        requirement = get_requirement(result, "mock.d1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_requires_verification_requirement_forces_review_required(self):
        spec = make_spec(
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION
        )
        result = run_custom([spec])
        requirement = get_requirement(result, "mock.r0")
        self.assertIs(requirement.status, RequirementStatus.REQUIRES_VERIFICATION)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_satisfied_requirement_does_not_independently_force_review(self):
        fact = make_fact(
            "F-001", "Date", FactStatus.CONFIRMED, "s",
            DraftPermission.YES, FactType.NOTICE_DATE, FactRole.NONE,
        )
        result = run_custom(
            [make_spec()], extraction=make_extraction(facts=[fact])
        )
        requirement = get_requirement(result, "mock.r0")
        self.assertIs(requirement.status, RequirementStatus.SATISFIED)
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_derived_requirement_does_not_independently_force_review(self):
        spec = make_spec(
            requirement_id="mock.d1",
            requirement_text="Derived value",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        result = run_custom(
            [spec],
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        requirement = get_requirement(result, "mock.d1")
        self.assertIs(requirement.status, RequirementStatus.DERIVED)
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_structural_arithmetic_fail_remains_blocked(self):
        # A structural FAIL blocks even while requirement resolution is
        # active and its own derived requirement is UNKNOWN.
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        self.assertIs(
            get_requirement(result, "sec73_itc.r3").status,
            RequirementStatus.UNKNOWN,
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_requirement_warning_affects_overall_status(self):
        result = run_custom([make_spec()])  # MISSING → requirement WARNING
        self.assertIs(result.overall_status, ValidationStatus.WARNING)

    def test_requirement_pass_does_not_create_warning(self):
        fact = make_fact(
            "F-001", "Date", FactStatus.CONFIRMED, "s",
            DraftPermission.YES, FactType.NOTICE_DATE, FactRole.NONE,
        )
        result = run_custom(
            [make_spec()], extraction=make_extraction(facts=[fact])
        )
        self.assertIs(result.overall_status, ValidationStatus.PASS)

    def test_requirements_never_create_fail_alone(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            for item in result.checks:
                if item.check_id.startswith("requirement."):
                    self.assertIn(
                        item.status,
                        (ValidationStatus.PASS, ValidationStatus.WARNING),
                        item.check_id,
                    )


# --- Step 8.3 X. Profile-wide requirement behavior (§19.16) ------------------

class ProfileWideRequirementTests(unittest.TestCase):
    """Every deep profile resolves all of its authoritative specs at
    runtime."""

    def _run(self, proceeding_type):
        return run_defaults(
            classification=make_classification(
                proceeding_type=proceeding_type
            )
        )

    def test_itc_produces_exactly_five_requirement_results(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_ITC).requirements), 5
        )

    def test_general_produces_exactly_five_requirement_results(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_GENERAL).requirements), 5
        )

    def test_rcm_produces_exactly_five_requirement_results(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_RCM).requirements), 5
        )

    def test_fraud_produces_exactly_five_requirement_results(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC74_FRAUD).requirements), 5
        )

    def test_sec129_produces_exactly_nine_requirement_results(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC129_ENFORCE).requirements), 9
        )

    def test_total_authoritative_profile_count_remains_29(self):
        static_total = sum(
            len(profile.requirement_specs)
            for profile in VALIDATION_PROFILE_REGISTRY.values()
        )
        self.assertEqual(static_total, 29)
        runtime_total = sum(
            len(self._run(proceeding_type).requirements)
            for proceeding_type in DEEP_PROFILE_COUNTS
        )
        self.assertEqual(runtime_total, 29)

    def test_requirement_ids_unique(self):
        for proceeding_type in DEEP_PROFILE_COUNTS:
            result = self._run(proceeding_type)
            ids = [r.requirement_id for r in result.requirements]
            self.assertEqual(len(ids), len(set(ids)), proceeding_type.name)

    def test_result_requirement_text_equals_profile_text_verbatim(self):
        for proceeding_type in DEEP_PROFILE_COUNTS:
            profile = get_validation_profile(proceeding_type)
            result = self._run(proceeding_type)
            for requirement, spec in zip(
                result.requirements, profile.requirement_specs
            ):
                self.assertEqual(
                    requirement.requirement_id, spec.requirement_id
                )
                self.assertEqual(
                    requirement.requirement_text, spec.requirement_text
                )


# --- Step 8.3 Y. Staging and purity ------------------------------------------

class StagingPurityTests(unittest.TestCase):
    """Step 8.4 evidence output and the engine purity/immutability contract."""

    def test_evidence_checklist_populated_only_for_usable_deep_workflows(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            workflow = get_workflow(proceeding_type)
            self.assertEqual(
                len(result.evidence_checklist),
                len(workflow.evidence_requirements),
                proceeding_type.name,
            )
            self.assertTrue(all(
                item.status == EvidenceStatus.UNKNOWN
                for item in result.evidence_checklist
            ))
        triage = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(triage.evidence_checklist, [])
        unknown = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        self.assertEqual(unknown.evidence_checklist, [])

    def test_no_evidence_gap_generation(self):
        self.assertNotIn("EvidenceGap", engine_source_text())

    def test_no_potential_defence_generation(self):
        self.assertNotIn("PotentialDefence", engine_source_text())

    def test_api_signature_unchanged(self):
        signature = inspect.signature(engine.run_validation)
        self.assertEqual(
            list(signature.parameters),
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

    def test_no_new_public_callable(self):
        public_callables = [
            name
            for name, obj in vars(engine).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == engine.__name__
        ]
        self.assertEqual(public_callables, ["run_validation"])

    def test_no_forbidden_imports(self):
        source = engine_source_text().lower()
        for token in (
            "llm_client", "gemini", "genai", "google", "requests",
            "urllib", "socket", "http", "sqlite", "streamlit",
            "deadline_engine", "arithmetic_engine", "fact_engine",
            "preflight_engine", "proceeding_classifier",
            "taxonomy_registry", "notice_explainer", "import app",
        ):
            self.assertNotIn(token, source, token)

    def test_no_deadline_or_arithmetic_recomputation(self):
        source = engine_source_text()
        self.assertNotIn("deadline_engine", source)
        self.assertNotIn("arithmetic_engine", source)
        lowered = source.lower()
        self.assertNotIn("timedelta", lowered)
        self.assertNotIn("seven", lowered)

    def test_input_objects_not_mutated_with_matching_facts(self):
        facts = itc_operand_facts() + [
            make_fact(
                "F-001", "Period", FactStatus.CONFIRMED, "p",
                DraftPermission.YES, FactType.TAX_PERIOD, FactRole.NONE,
            ),
        ]
        arithmetic = [
            make_arithmetic(
                status=ArithmeticStatus.MISMATCH,
                source_fact_ids=["A", "B"],
                result=Decimal("5"),
            )
        ]
        facts_snapshot = copy.deepcopy(facts)
        arithmetic_snapshot = copy.deepcopy(arithmetic)
        result = run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=arithmetic,
        )
        self.assertEqual(facts, facts_snapshot)
        self.assertEqual(arithmetic, arithmetic_snapshot)
        # Resolved related IDs are defensive copies: mutating the output
        # must not touch the inputs.
        requirement = get_requirement(result, "sec73_itc.r3")
        self.assertEqual(requirement.related_fact_ids, ["A", "B"])
        requirement.related_fact_ids.append("INJECTED")
        self.assertEqual(facts, facts_snapshot)

    def test_profile_and_spec_objects_not_mutated(self):
        profile = get_validation_profile(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(profile.requirement_specs)
        run_defaults()
        self.assertEqual(profile.requirement_specs, snapshot)


# --- Step 8.4 A. Evidence generation gate (§19.111) ---------------------------

class EvidenceGateTests(unittest.TestCase):
    """Evidence checklist generation uses the exact Step-8.3 deep
    structural gate; extraction failure never hides the static
    checklist."""

    def _run(self, proceeding_type):
        return run_defaults(
            classification=make_classification(
                proceeding_type=proceeding_type
            )
        )

    def test_itc_deep_produces_checklist(self):
        result = self._run(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(len(result.evidence_checklist), 5)

    def test_general_deep_produces_checklist(self):
        result = self._run(ProceedingType.GST_SEC73_GENERAL)
        self.assertEqual(len(result.evidence_checklist), 3)

    def test_rcm_deep_produces_checklist(self):
        result = self._run(ProceedingType.GST_SEC73_RCM)
        self.assertEqual(len(result.evidence_checklist), 4)

    def test_fraud_deep_produces_checklist(self):
        result = self._run(ProceedingType.GST_SEC74_FRAUD)
        self.assertEqual(len(result.evidence_checklist), 5)

    def test_sec129_deep_produces_checklist(self):
        result = self._run(ProceedingType.GST_SEC129_ENFORCE)
        self.assertEqual(len(result.evidence_checklist), 5)

    def test_triage_produces_empty_checklist(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(result.evidence_checklist, [])

    def test_unknown_support_produces_empty_checklist(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        self.assertEqual(result.evidence_checklist, [])

    def test_unknown_proceeding_produces_empty_checklist(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN
            )
        )
        self.assertEqual(result.evidence_checklist, [])

    def test_missing_workflow_produces_empty_checklist(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_missing_profile_produces_empty_checklist(self):
        with mock.patch.object(
            engine, "get_validation_profile", return_value=None
        ):
            result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_workflow_misalignment_produces_empty_checklist(self):
        wrong = make_mock_workflow(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(engine, "get_workflow", return_value=wrong):
            result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_profile_misalignment_produces_empty_checklist(self):
        wrong = make_mock_profile(
            proceeding_type=ProceedingType.GST_SEC73_GENERAL
        )
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_requirement_alignment_fail_produces_empty_checklist(self):
        wrong = make_mock_profile(requirement_texts=["Different text."])
        with mock.patch.object(
            engine, "get_validation_profile", return_value=wrong
        ):
            result = run_defaults()
        self.assertEqual(result.evidence_checklist, [])

    def test_failed_extraction_still_renders_checklist_but_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_no_input_extraction_still_renders_checklist_but_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)


# --- Step 8.4 B. Exact checklist contract (§19.18) ----------------------------

class EvidenceChecklistContractTests(unittest.TestCase):
    """One UNKNOWN item per workflow evidence_requirements entry, exact
    workflow order, verbatim text, positional one-based IDs."""

    def _run(self, proceeding_type):
        return run_defaults(
            classification=make_classification(
                proceeding_type=proceeding_type
            )
        )

    def test_one_item_per_evidence_requirement(self):
        for proceeding_type, expected_count in EVIDENCE_COUNTS.items():
            result = self._run(proceeding_type)
            workflow = get_workflow(proceeding_type)
            self.assertEqual(
                len(result.evidence_checklist),
                len(workflow.evidence_requirements),
                proceeding_type.name,
            )
            self.assertEqual(
                len(result.evidence_checklist),
                expected_count,
                proceeding_type.name,
            )

    def test_exact_workflow_order(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            workflow = get_workflow(proceeding_type)
            self.assertEqual(
                [
                    item.requirement_text
                    for item in result.evidence_checklist
                ],
                list(workflow.evidence_requirements),
                proceeding_type.name,
            )

    def test_requirement_text_is_verbatim_workflow_string(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            workflow = get_workflow(proceeding_type)
            for item, text in zip(
                result.evidence_checklist, workflow.evidence_requirements
            ):
                self.assertIs(item.requirement_text, text)
                self.assertEqual(item.requirement_text, text)

    def test_status_is_unknown_for_every_item(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            self.assertTrue(all(
                item.status == EvidenceStatus.UNKNOWN
                for item in result.evidence_checklist
            ), proceeding_type.name)

    def test_ids_are_one_based_positions(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            for position, item in enumerate(
                result.evidence_checklist, start=1
            ):
                self.assertTrue(
                    item.evidence_id.endswith(f".e{position}"),
                    item.evidence_id,
                )

    def test_itc_ids_use_sec73_itc_prefix(self):
        result = self._run(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            [
                "sec73_itc.e1", "sec73_itc.e2", "sec73_itc.e3",
                "sec73_itc.e4", "sec73_itc.e5",
            ],
        )

    def test_general_ids_use_sec73_general_prefix(self):
        result = self._run(ProceedingType.GST_SEC73_GENERAL)
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            ["sec73_general.e1", "sec73_general.e2", "sec73_general.e3"],
        )

    def test_rcm_ids_use_sec73_rcm_prefix(self):
        result = self._run(ProceedingType.GST_SEC73_RCM)
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            [
                "sec73_rcm.e1", "sec73_rcm.e2", "sec73_rcm.e3",
                "sec73_rcm.e4",
            ],
        )

    def test_fraud_ids_use_sec74_fraud_prefix(self):
        result = self._run(ProceedingType.GST_SEC74_FRAUD)
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            [
                "sec74_fraud.e1", "sec74_fraud.e2", "sec74_fraud.e3",
                "sec74_fraud.e4", "sec74_fraud.e5",
            ],
        )

    def test_sec129_ids_use_sec129_prefix(self):
        result = self._run(ProceedingType.GST_SEC129_ENFORCE)
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            [
                "sec129.e1", "sec129.e2", "sec129.e3", "sec129.e4",
                "sec129.e5",
            ],
        )

    def test_ids_unique_within_workflow(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            ids = [item.evidence_id for item in result.evidence_checklist]
            self.assertEqual(len(ids), len(set(ids)), proceeding_type.name)

    def test_evidence_text_never_appears_in_id(self):
        for proceeding_type in EVIDENCE_COUNTS:
            result = self._run(proceeding_type)
            for item in result.evidence_checklist:
                self.assertNotIn(item.requirement_text, item.evidence_id)

    def test_repeated_evidence_text_gets_distinct_position_ids(self):
        result = run_evidence_custom(
            ["Same document requested", "Same document requested"]
        )
        self.assertEqual(
            [item.evidence_id for item in result.evidence_checklist],
            ["sec73_itc.e1", "sec73_itc.e2"],
        )
        self.assertEqual(
            result.evidence_checklist[0].requirement_text,
            result.evidence_checklist[1].requirement_text,
        )

    def test_every_run_creates_fresh_list_and_items(self):
        first = run_defaults()
        second = run_defaults()
        self.assertIsNot(first.evidence_checklist, second.evidence_checklist)
        self.assertIsNot(
            first.evidence_checklist[0], second.evidence_checklist[0]
        )

    def test_workflow_evidence_list_not_mutated(self):
        workflow = get_workflow(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(workflow.evidence_requirements)
        run_defaults()
        self.assertEqual(workflow.evidence_requirements, snapshot)


# --- Step 8.4 C. UNKNOWN-only Phase-2 semantics (§19.17, §19.43) -------------

class EvidenceUnknownOnlyTests(unittest.TestCase):
    """Only EvidenceStatus.UNKNOWN is emitted; notice contents and
    preflight pass-through indices never change an evidence status."""

    def _deep_statuses(self, **kwargs):
        return [
            item.status for item in run_defaults(**kwargs).evidence_checklist
        ]

    def test_no_present_emitted(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            self.assertTrue(all(
                item.status != EvidenceStatus.PRESENT
                for item in result.evidence_checklist
            ), proceeding_type.name)

    def test_no_missing_emitted(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            self.assertTrue(all(
                item.status != EvidenceStatus.MISSING
                for item in result.evidence_checklist
            ), proceeding_type.name)

    def test_no_requires_verification_emitted(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            self.assertTrue(all(
                item.status != EvidenceStatus.REQUIRES_VERIFICATION
                for item in result.evidence_checklist
            ), proceeding_type.name)

    def test_requested_document_indices_do_not_produce_present(self):
        statuses = self._deep_statuses(
            preflight=make_preflight_with_indices(
                requested_document_fact_ids=["F-DOC"]
            )
        )
        self.assertEqual(statuses, [EvidenceStatus.UNKNOWN] * 5)

    def test_referenced_annexure_indices_do_not_produce_present(self):
        statuses = self._deep_statuses(
            preflight=make_preflight_with_indices(
                referenced_annexure_fact_ids=["F-ANN"]
            )
        )
        self.assertEqual(statuses, [EvidenceStatus.UNKNOWN] * 5)

    def test_requested_document_facts_do_not_produce_present(self):
        fact = make_fact(
            "F-DOC", "Invoice", FactStatus.CONFIRMED, "s",
            DraftPermission.YES, FactType.DOCUMENT_DETAIL,
            FactRole.GOODS_DESCRIPTION,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[fact]),
            preflight=make_preflight_with_indices(
                requested_document_fact_ids=["F-DOC"]
            ),
        )
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))

    def test_referenced_annexure_facts_do_not_produce_present(self):
        fact = make_fact(
            "F-ANN", "Annexure", FactStatus.CONFIRMED, "s",
            DraftPermission.YES, FactType.DOCUMENT_DETAIL,
            FactRole.GOODS_DESCRIPTION,
        )
        result = run_defaults(
            extraction=make_extraction(facts=[fact]),
            preflight=make_preflight_with_indices(
                referenced_annexure_fact_ids=["F-ANN"]
            ),
        )
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))

    def test_absence_of_requested_document_facts_not_missing(self):
        statuses = self._deep_statuses(
            preflight=make_preflight_with_indices()
        )
        self.assertEqual(statuses, [EvidenceStatus.UNKNOWN] * 5)

    def test_absence_of_annexure_facts_not_missing(self):
        statuses = self._deep_statuses(
            preflight=make_preflight_with_indices()
        )
        self.assertEqual(statuses, [EvidenceStatus.UNKNOWN] * 5)

    def test_source_text_matching_evidence_wording_not_present(self):
        fact = make_fact(
            "F-001",
            "GSTR-2B for all months in the relevant period",
            FactStatus.REQUIRES_VERIFICATION,
            "GSTR-2B for all months in the relevant period",
            DraftPermission.NO,
            FactType.OTHER_NOTICE_FACT,
            FactRole.NONE,
        )
        result = run_defaults(extraction=make_extraction(facts=[fact]))
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))

    def test_fact_role_does_not_determine_evidence_status(self):
        facts = itc_operand_facts() + [
            make_fact(
                "F-001", "Interest", FactStatus.CONFIRMED, "i",
                DraftPermission.YES, FactType.STATED_AMOUNT,
                FactRole.INTEREST_PROPOSED_AMOUNT,
            ),
            make_fact(
                "F-002", "Period", FactStatus.CONFIRMED, "p",
                DraftPermission.YES, FactType.TAX_PERIOD, FactRole.NONE,
            ),
        ]
        result = run_defaults(extraction=make_extraction(facts=facts))
        self.assertTrue(all(
            item.status == EvidenceStatus.UNKNOWN
            for item in result.evidence_checklist
        ))


# --- Step 8.4 D. No EvidenceGap / upload matching ----------------------------

class EvidenceNoGapTests(unittest.TestCase):
    """EvidenceChecklistItem is the only evidence output surface; the
    engine performs no upload/document inference of any kind."""

    def test_no_evidence_gap_objects(self):
        self.assertNotIn("EvidenceGap", engine_source_text())

    def test_no_potential_defence_objects(self):
        self.assertNotIn("PotentialDefence", engine_source_text())

    def test_no_evidence_validation_items(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            evidence_checks = [
                item for item in result.checks
                if item.check_id.startswith("evidence.")
            ]
            self.assertEqual(
                evidence_checks, [], proceeding_type.name
            )

    def test_no_upload_matching(self):
        lowered = engine_source_text().lower()
        for token in ("upload_dir", "document_path", "mime", "attachment"):
            self.assertNotIn(token, lowered, token)

    def test_no_filename_matching(self):
        self.assertNotIn("filename", engine_source_text().lower())

    def test_no_fuzzy_or_semantic_matching(self):
        lowered = engine_source_text().lower()
        self.assertNotIn("fuzzy", lowered)
        self.assertNotIn("difflib", lowered)
        self.assertNotIn("sequencematcher", lowered)

    def test_no_filesystem_scan(self):
        lowered = engine_source_text().lower()
        self.assertNotIn("pathlib", lowered)
        self.assertNotIn("os.walk", lowered)
        self.assertNotIn("glob", lowered)

    def test_no_ocr_or_pdf_imports(self):
        lowered = engine_source_text().lower()
        for token in ("ocr", "pypdf", "fitz"):
            self.assertNotIn(token, lowered, token)

    def test_no_network_or_llm(self):
        lowered = engine_source_text().lower()
        for token in (
            "llm_client", "gemini", "genai", "google", "requests",
            "urllib", "socket", "http",
        ):
            self.assertNotIn(token, lowered, token)


# --- Step 8.4 E. Evidence-driven DraftEligibility (§19.26, §19.43) -----------

class EvidenceEligibilityTests(unittest.TestCase):
    """BLOCKED stays dominant; UNKNOWN evidence resolves a non-blocked
    case to REVIEW_REQUIRED; ALLOWED stays reachable synthetically."""

    def test_evidence_unknown_forces_review_required(self):
        result = run_evidence_custom(["Invoice copy"])
        self.assertTrue(result.evidence_checklist)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_evidence_unknown_does_not_block(self):
        result = run_evidence_custom(["Invoice copy"])
        self.assertIsNot(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_support_gate_block_stays_blocked(self):
        result = run_defaults(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_failed_extraction_stays_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.FAILED)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_no_input_stays_blocked(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.NO_INPUT)
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_fact_invariant_fail_stays_blocked(self):
        offender = make_fact(
            "F-001", "3B ITC", FactStatus.CONFIRMED, "s",
            DraftPermission.NO, FactType.STATED_AMOUNT,
            FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_structural_arithmetic_fail_stays_blocked(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["B", "A"])],
        )
        self.assertEqual(len(result.evidence_checklist), 5)
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_unresolved_requirement_forces_review_required(self):
        result = run_custom([make_spec()])
        requirement = get_requirement(result, "mock.r0")
        self.assertIs(requirement.status, RequirementStatus.MISSING)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_review_requirement_forces_review_required(self):
        workflow = make_mock_workflow(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            required_facts=[],
            special_rules=["Mandatory CA review applies."],
        )
        profile = WorkflowValidationProfile(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            requirement_specs=[],
            special_rule_handling={
                0: (SpecialRuleHandling.REVIEW_GATE,),
            },
            review_rules={0: ReviewLevel.CA_REVIEW},
        )
        with mock.patch.object(engine, "get_workflow", return_value=workflow), \
             mock.patch.object(
                 engine, "get_validation_profile", return_value=profile
             ):
            result = engine.run_validation(
                make_classification(),
                make_extraction(),
                make_preflight(portal=False, authority=False),
                [],
            )
        self.assertTrue(result.review_requirements)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_warning_item_forces_review_required(self):
        result = run_evidence_custom([], preflight=make_preflight())
        self.assertFalse(result.review_requirements)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_satisfied_requirements_do_not_independently_force_review(self):
        fact = make_fact(
            "F-001", "Date", FactStatus.CONFIRMED, "s",
            DraftPermission.YES, FactType.NOTICE_DATE, FactRole.NONE,
        )
        result = run_custom(
            [make_spec()], extraction=make_extraction(facts=[fact])
        )
        self.assertIs(
            get_requirement(result, "mock.r0").status,
            RequirementStatus.SATISFIED,
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_derived_requirements_do_not_independently_force_review(self):
        spec = make_spec(
            requirement_id="mock.d1",
            requirement_text="Derived value",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
        result = run_custom(
            [spec],
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        self.assertIs(
            get_requirement(result, "mock.d1").status,
            RequirementStatus.DERIVED,
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_empty_evidence_list_alone_is_not_completeness(self):
        # §19.26: [] never proves completeness — other conditions still
        # resolve REVIEW_REQUIRED.
        result = run_evidence_custom(
            [], extraction=make_extraction(status=FactExtractionStatus.PARTIAL)
        )
        self.assertEqual(result.evidence_checklist, [])
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_synthetic_clean_configuration_reaches_allowed(self):
        result = run_evidence_custom([])
        self.assertEqual(result.evidence_checklist, [])
        self.assertIs(result.overall_status, ValidationStatus.PASS)
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_real_deep_workflows_normally_review_required(self):
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            self.assertTrue(result.evidence_checklist)
            self.assertIs(
                result.draft_eligibility,
                DraftEligibility.REVIEW_REQUIRED,
                proceeding_type.name,
            )

    def test_evidence_state_does_not_alter_case_severity(self):
        with_evidence = run_defaults()
        self.assertIs(with_evidence.case_severity, IssueSeverity.MEDIUM)
        sec129 = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        self.assertIs(sec129.case_severity, IssueSeverity.HIGH)
        synthetic = run_evidence_custom(["Invoice copy"])
        self.assertIs(synthetic.case_severity, IssueSeverity.MEDIUM)


# --- Step 8.4 F. Overall-status separation (§19.25) --------------------------

class EvidenceOverallStatusTests(unittest.TestCase):
    """Evidence never becomes a ValidationItem and never enters overall
    status; FAIL > WARNING > PASS dominance is unchanged."""

    def test_evidence_unknown_creates_no_validation_item(self):
        result = run_evidence_custom(["Invoice copy"])
        self.assertTrue(result.evidence_checklist)
        self.assertFalse(any(
            item.check_id.startswith("evidence.")
            for item in result.checks
        ))

    def test_evidence_unknown_not_aggregated_into_overall_status(self):
        result = run_evidence_custom(["Invoice copy"])
        self.assertIs(result.overall_status, ValidationStatus.PASS)

    def test_pass_overall_with_review_required_from_evidence_alone(self):
        result = run_evidence_custom(["Invoice copy"])
        self.assertIs(result.overall_status, ValidationStatus.PASS)
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_fail_dominance_unchanged(self):
        offender = make_fact(
            "F-001", "3B ITC", FactStatus.CONFIRMED, "s",
            DraftPermission.NO, FactType.STATED_AMOUNT,
            FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        )
        result = run_defaults(extraction=make_extraction(facts=[offender]))
        self.assertIs(result.overall_status, ValidationStatus.FAIL)

    def test_warning_dominance_unchanged(self):
        result = run_evidence_custom([], preflight=make_preflight())
        self.assertIs(result.overall_status, ValidationStatus.WARNING)


# --- Step 8.4 G. Step-8.3 requirement regression -----------------------------

class Step84RequirementRegressionTests(unittest.TestCase):
    """Step 8.4 changes nothing about Step-8.3 requirement resolution."""

    def _run(self, proceeding_type):
        return run_defaults(
            classification=make_classification(
                proceeding_type=proceeding_type
            )
        )

    def test_requirements_still_populated(self):
        result = self._run(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(len(result.requirements), 5)

    def test_itc_requirement_count_unchanged(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_ITC).requirements), 5
        )

    def test_general_requirement_count_unchanged(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_GENERAL).requirements), 5
        )

    def test_rcm_requirement_count_unchanged(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC73_RCM).requirements), 5
        )

    def test_fraud_requirement_count_unchanged(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC74_FRAUD).requirements), 5
        )

    def test_sec129_requirement_count_unchanged(self):
        self.assertEqual(
            len(self._run(ProceedingType.GST_SEC129_ENFORCE).requirements), 9
        )

    def test_all_29_requirement_ids_unchanged(self):
        for proceeding_type in DEEP_PROFILE_COUNTS:
            profile = get_validation_profile(proceeding_type)
            result = self._run(proceeding_type)
            self.assertEqual(
                requirement_item_ids(result.checks),
                [
                    f"requirement.{spec.requirement_id}"
                    for spec in profile.requirement_specs
                ],
                proceeding_type.name,
            )

    def test_non_success_absence_safety_unchanged(self):
        result = run_defaults(
            extraction=make_extraction(status=FactExtractionStatus.PARTIAL)
        )
        requirement = get_requirement(result, "sec73_itc.r1")
        self.assertIs(requirement.status, RequirementStatus.UNKNOWN)
        self.assertIsNot(requirement.status, RequirementStatus.MISSING)

    def test_mismatch_still_may_resolve_derived(self):
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
        self.assertIs(
            get_requirement(result, "sec73_itc.r3").status,
            RequirementStatus.DERIVED,
        )

    def test_multiple_matches_still_unknown(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[
                make_arithmetic(source_fact_ids=["A", "B"]),
                make_arithmetic(source_fact_ids=["A", "B"]),
            ],
        )
        self.assertIs(
            get_requirement(result, "sec73_itc.r3").status,
            RequirementStatus.UNKNOWN,
        )

    def test_itc_deterministic_rule_unchanged(self):
        result = run_defaults(
            extraction=make_extraction(facts=itc_operand_facts()),
            arithmetic=[make_arithmetic(source_fact_ids=["A", "B"])],
        )
        item = get_item(result.checks, ITC_RULE_ID)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Deterministic ITC-difference workflow requirement is derived from approved arithmetic output.",
        )

    def test_general_deterministic_rule_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_GENERAL
            ),
            extraction=make_extraction(facts=output_tax_operand_facts()),
            arithmetic=[
                make_arithmetic(
                    calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    source_fact_ids=["A", "B"],
                )
            ],
        )
        item = get_item(result.checks, GENERAL_RULE_ID)
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Deterministic output-tax-difference workflow requirement is derived from approved arithmetic output.",
        )

    def test_temporary_step_8_2_message_absent(self):
        self.assertNotIn("deferred until Step 8.3", engine_source_text())
        for proceeding_type in ALL_DEEP_PROCEEDINGS:
            result = self._run(proceeding_type)
            for item in result.checks:
                self.assertNotIn(
                    "deferred until Step 8.3", item.message, item.check_id
                )


# --- Step 8.4 H. Special-rule / review regression ----------------------------

class Step84SpecialRuleReviewRegressionTests(unittest.TestCase):
    """Only evidence changed in Step 8.4; special rules and reviews keep
    their Step-8.2/8.3 semantics."""

    def test_fraud_rule_0_unchanged(self):
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
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Fraud/suppression allegations remain departmental allegations.",
        )

    def test_fraud_rule_2_unchanged(self):
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
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Fraud-workflow fact provenance is present.",
        )

    def test_sec129_rule_6_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.6.deterministic_check",
        )
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "Section-129 deadline handling uses only supplied preflight/deadline results; validation adds no statutory deadline calculation.",
        )

    def test_future_legal_rule_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec73_rcm.special_rule.1.future_legal_rule",
        )
        self.assertIs(item.status, ValidationStatus.WARNING)
        self.assertEqual(
            item.message,
            "This workflow rule requires future verified legal-rule support and CA review.",
        )

    def test_upstream_invariant_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        item = get_item(
            result.checks,
            "workflow.sec129.special_rule.2.upstream_invariant",
        )
        self.assertIs(item.status, ValidationStatus.PASS)
        self.assertEqual(
            item.message,
            "This safety boundary is enforced by an authoritative upstream component and is not re-run by validation.",
        )

    def test_review_gate_ids_unchanged(self):
        itc = run_defaults()
        for index in (0, 2, 3):
            self.assertIn(
                f"workflow.sec73_itc.special_rule.{index}.review_gate",
                check_ids(itc.checks),
            )
        rcm = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC73_RCM
            )
        )
        self.assertIn(
            "workflow.sec73_rcm.special_rule.1.review_gate",
            check_ids(rcm.checks),
        )
        fraud = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            )
        )
        for index in (1, 3):
            self.assertIn(
                f"workflow.sec74_fraud.special_rule.{index}.review_gate",
                check_ids(fraud.checks),
            )
        sec129 = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC129_ENFORCE
            )
        )
        for index in (0, 1, 4):
            self.assertIn(
                f"workflow.sec129.special_rule.{index}.review_gate",
                check_ids(sec129.checks),
            )

    def test_review_reason_verbatim(self):
        result = run_defaults()
        workflow = get_workflow(ProceedingType.GST_SEC73_ITC)
        for review in result.review_requirements:
            if review.review_id.startswith("workflow."):
                # review_id: workflow.<prefix>.special_rule.<index>.review
                index = int(review.review_id.split(".")[3])
                self.assertEqual(
                    review.reason, workflow.special_rules[index]
                )

    def test_review_dedup_unchanged(self):
        result = run_defaults(
            classification=make_classification(
                proceeding_type=ProceedingType.GST_SEC74_FRAUD
            ),
            extraction=make_extraction(facts=fraud_clean_facts()),
        )
        keys = [
            (review.level, review.reason)
            for review in result.review_requirements
        ]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(keys)

    def test_urgent_deadline_review_unchanged(self):
        result = run_defaults(
            deadline=make_deadline(deadline_status=DeadlineStatus.CRITICAL)
        )
        urgent = [
            review for review in result.review_requirements
            if review.review_id == "deadline.urgent_review"
        ]
        self.assertEqual(len(urgent), 1)
        self.assertIs(urgent[0].level, ReviewLevel.URGENT_CA_REVIEW)
        self.assertEqual(
            urgent[0].reason,
            "Deadline status is CRITICAL; urgent CA review is required.",
        )


# --- Step 8.4 I. API / purity / immutability ---------------------------------

class Step84PurityTests(unittest.TestCase):
    """The Step-8.4 engine keeps the public surface, the pure-Python
    boundary and the no-mutation contract."""

    def test_public_signature_unchanged(self):
        signature = inspect.signature(engine.run_validation)
        self.assertEqual(
            list(signature.parameters),
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

    def test_only_public_callable_run_validation(self):
        public_callables = [
            name
            for name, obj in vars(engine).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == engine.__name__
        ]
        self.assertEqual(public_callables, ["run_validation"])

    def test_no_forbidden_imports(self):
        lowered = engine_source_text().lower()
        for token in (
            "llm_client", "gemini", "genai", "google", "requests",
            "urllib", "socket", "http", "sqlite", "streamlit",
            "deadline_engine", "arithmetic_engine", "fact_engine",
            "preflight_engine", "proceeding_classifier",
            "taxonomy_registry", "notice_explainer", "import app",
        ):
            self.assertNotIn(token, lowered, token)

    def test_no_llm_or_network(self):
        lowered = engine_source_text().lower()
        for token in (
            "llm_client", "gemini", "genai", "google", "requests",
            "urllib", "socket", "http",
        ):
            self.assertNotIn(token, lowered, token)

    def test_no_filesystem_evidence_inference(self):
        lowered = engine_source_text().lower()
        for token in ("pathlib", "os.", "open(", "glob", "filename"):
            self.assertNotIn(token, lowered, token)

    def test_inputs_not_mutated(self):
        facts = itc_operand_facts() + [
            make_fact(
                "F-001", "Period", FactStatus.CONFIRMED, "p",
                DraftPermission.YES, FactType.TAX_PERIOD, FactRole.NONE,
            ),
        ]
        arithmetic = [
            make_arithmetic(
                status=ArithmeticStatus.MISMATCH,
                source_fact_ids=["A", "B"],
                result=Decimal("5"),
            )
        ]
        facts_snapshot = copy.deepcopy(facts)
        arithmetic_snapshot = copy.deepcopy(arithmetic)
        run_defaults(
            extraction=make_extraction(facts=facts),
            arithmetic=arithmetic,
        )
        self.assertEqual(facts, facts_snapshot)
        self.assertEqual(arithmetic, arithmetic_snapshot)

    def test_workflow_not_mutated(self):
        workflow = get_workflow(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(workflow)
        run_defaults()
        self.assertEqual(workflow, snapshot)

    def test_profile_not_mutated(self):
        profile = get_validation_profile(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(profile)
        run_defaults()
        self.assertEqual(profile, snapshot)

    def test_requirement_specs_not_mutated(self):
        profile = get_validation_profile(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(profile.requirement_specs)
        run_defaults()
        self.assertEqual(profile.requirement_specs, snapshot)

    def test_evidence_requirements_not_mutated(self):
        workflow = get_workflow(ProceedingType.GST_SEC73_ITC)
        snapshot = copy.deepcopy(workflow.evidence_requirements)
        run_defaults()
        self.assertEqual(workflow.evidence_requirements, snapshot)

    def test_fresh_result_lists_each_call(self):
        first = run_defaults()
        second = run_defaults()
        self.assertIsNot(first.evidence_checklist, second.evidence_checklist)
        self.assertIsNot(first.requirements, second.requirements)
        self.assertIsNot(first.checks, second.checks)
        self.assertIsNot(
            first.review_requirements, second.review_requirements
        )

    def test_evidence_checklist_is_final_step_8_output(self):
        # §19.24/§19.110: the checklist is now the real Step-8.4 output,
        # not the staged empty list, for every valid deep workflow.
        for proceeding_type in EVIDENCE_COUNTS:
            result = run_defaults(
                classification=make_classification(
                    proceeding_type=proceeding_type
                )
            )
            self.assertTrue(
                result.evidence_checklist, proceeding_type.name
            )
            self.assertTrue(all(
                isinstance(item, EvidenceChecklistItem)
                and item.status == EvidenceStatus.UNKNOWN
                for item in result.evidence_checklist
            ))


def engine_source_text():
    return pathlib.Path(engine.__file__).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
