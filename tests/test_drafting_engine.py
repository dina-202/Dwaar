"""Unit tests for the Step-9.2 controlled drafting-context builder and
deterministic prompt assembly, and the Step-9.3 generation/parser state
machine (ARCHITECTURE_SPEC_v1_1 §21, §22).

Fully offline and deterministic. The Step-9.3 LLM boundary is always
mocked via engine.call_gemini: no live LLM calls, no network, no
fixtures.

Verifies:

  - module surface: only private underscore helpers exist, no public
    drafting API yet, no LLM/provider/network/engine imports (§21.26,
    §21.27);
  - the Step-9.2 gate: DEEP + REVIEW_REQUIRED/ALLOWED permits, every
    other state refuses, no fallbacks (§20.3, §21.28);
  - the controlled context: exact 12 top-level keys in exact order,
    section/fact/arithmetic/preflight/deadline/requirement/evidence/
    review/warning serialization exactly as §21.2–§21.16 pin it;
  - forbidden context surfaces (§21.16);
  - deterministic JSON encoding: indent=2, ensure_ascii=False, no
    alphabetical sort, byte-for-byte identical for identical inputs
    (§21.24);
  - the six static prompt assets, the closed prompt-key mapping and the
    base/workflow prompt content contracts (§21.17–§21.20);
  - exact prompt assembly order with the BEGIN/END markers (§21.23);
  - staging: no LLM call, no parser, no post-validation, no token
    resolution, no integration (§21.29–§21.30).

Tests may exercise private helpers directly (§21.27: private helper
names are implementation-local, not external machine contracts).

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_drafting_engine.py -v
No pytest, no external dependencies.
"""

import copy
import inspect
import json
import pathlib
import re
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

import domain.drafting_engine as engine
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
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftSection,
    EvidenceChecklistItem,
    EvidenceStatus,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    PreflightResult,
    ProceedingType,
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewRequirement,
    SpecialistDraftResult,
    SupportLevel,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
)
from workflows.gst import GST_WORKFLOW_REGISTRY
from workflows.gst.drafting_profiles import (
    DRAFTING_PROFILE_REGISTRY,
    WorkflowDraftingProfile,
    get_drafting_profile,
)

DEEP_TYPES = (
    ProceedingType.GST_SEC73_ITC,
    ProceedingType.GST_SEC73_GENERAL,
    ProceedingType.GST_SEC73_RCM,
    ProceedingType.GST_SEC74_FRAUD,
    ProceedingType.GST_SEC129_ENFORCE,
)

EXPECTED_TOP_LEVEL_KEYS = [
    "schema_version",
    "proceeding_type",
    "draft_eligibility",
    "sections",
    "facts",
    "arithmetic",
    "preflight",
    "deadline",
    "unresolved_requirements",
    "evidence_checklist",
    "review_requirements",
    "validation_warnings",
]

EXPECTED_FACT_KEYS = [
    "fact_id",
    "fact_type",
    "fact_role",
    "status",
    "source_text",
    "source_page",
    "allowed_in_draft",
]

EXPECTED_ARITHMETIC_KEYS = [
    "index",
    "calculation_type",
    "status",
    "source_fact_ids",
    "operand_values",
    "result",
    "formula",
    "currency",
    "allowed_in_draft",
]

EXPECTED_PREFLIGHT_KEYS = [
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

EXPECTED_DEADLINE_KEYS = [
    "notice_date",
    "service_date",
    "response_period_days",
    "response_deadline",
    "deadline_confidence",
    "deadline_status",
    "days_remaining",
    "hearing_date",
    "hearing_status",
    "portal_verification_required",
    "notes",
]

EXPECTED_REQUIREMENT_KEYS = [
    "requirement_id",
    "requirement_text",
    "status",
    "related_fact_ids",
    "calculation_type",
]

EXPECTED_EVIDENCE_KEYS = ["evidence_id", "requirement_text", "status"]

EXPECTED_REVIEW_KEYS = ["review_id", "level", "reason", "mandatory"]

EXPECTED_WARNING_KEYS = [
    "check_id",
    "status",
    "message",
    "related_fact_ids",
    "related_calculation_types",
]

ARITHMETIC_SUFFIXES = (
    "calculation_type",
    "draft_permission",
    "source_resolution",
    "role_provenance",
    "result_status_consistency",
)


# --- construction helpers ----------------------------------------------------


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
    claim="Claim text.",
    status=FactStatus.CONFIRMED,
    source_text="Notice text.",
    source_page=None,
    allowed_in_draft=DraftPermission.YES,
    fact_type=FactType.OTHER_NOTICE_FACT,
    fact_role=FactRole.NONE,
):
    from domain.models import ExtractedFact

    return ExtractedFact(
        fact_id=fact_id,
        claim=claim,
        status=status,
        source_text=source_text,
        source_page=source_page,
        allowed_in_draft=allowed_in_draft,
        fact_type=fact_type,
        fact_role=fact_role,
    )


def make_extraction(facts=None, status=FactExtractionStatus.SUCCESS):
    return FactExtractionResult(
        facts=[] if facts is None else list(facts),
        status=status,
        rejected_item_count=0,
    )


def make_preflight(
    fact_extraction_status=FactExtractionStatus.SUCCESS,
    communication_identifier_status=CommunicationIdentifierStatus.RFN_PRESENT,
    portal_verification_required=True,
    authority_details_status=AuthorityDetailsStatus.PRESENT,
    authority_verification_required=True,
    stated_due_date_fact_ids=(),
    parsed_stated_due_dates=(),
    unparsed_stated_due_date_fact_ids=(),
    deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
    hearing_fact_ids=(),
    requested_document_fact_ids=(),
    referenced_annexure_fact_ids=(),
):
    return PreflightResult(
        fact_extraction_status=fact_extraction_status,
        communication_identifier_status=communication_identifier_status,
        portal_verification_required=portal_verification_required,
        authority_details_status=authority_details_status,
        authority_verification_required=authority_verification_required,
        stated_due_date_fact_ids=list(stated_due_date_fact_ids),
        parsed_stated_due_dates=list(parsed_stated_due_dates),
        unparsed_stated_due_date_fact_ids=list(
            unparsed_stated_due_date_fact_ids
        ),
        deadline_conflict_status=deadline_conflict_status,
        hearing_fact_ids=list(hearing_fact_ids),
        requested_document_fact_ids=list(requested_document_fact_ids),
        referenced_annexure_fact_ids=list(referenced_annexure_fact_ids),
    )


def make_deadline(
    notice_date=date(2025, 3, 10),
    service_date=None,
    response_period_days=None,
    response_deadline=None,
    deadline_confidence=DeadlineConfidence.UNKNOWN,
    deadline_status=DeadlineStatus.UPCOMING,
    days_remaining=None,
    hearing_date=None,
    hearing_status=HearingStatus.NOT_SCHEDULED,
    portal_verification_required=True,
    notes=(),
):
    return DeadlineResult(
        notice_date=notice_date,
        service_date=service_date,
        response_period_days=response_period_days,
        response_deadline=response_deadline,
        deadline_confidence=deadline_confidence,
        deadline_status=deadline_status,
        days_remaining=days_remaining,
        hearing_date=hearing_date,
        hearing_status=hearing_status,
        portal_verification_required=portal_verification_required,
        notes=list(notes),
    )


def make_arithmetic(
    calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
    status=ArithmeticStatus.PASS,
    source_fact_ids=(),
    operand_values=(),
    result=Decimal("888.80"),
    formula="left - right",
    currency="INR",
    allowed_in_draft=DraftPermission.CONDITIONAL,
):
    return ArithmeticResult(
        calculation_type=calculation_type,
        status=status,
        source_fact_ids=list(source_fact_ids),
        operand_values=list(operand_values),
        result=result,
        formula=formula,
        currency=currency,
        allowed_in_draft=allowed_in_draft,
    )


def make_item(
    check_id,
    status=ValidationStatus.PASS,
    message="test message",
    fact_ids=(),
    calc_types=(),
):
    return ValidationItem(
        check_id=check_id,
        status=status,
        message=message,
        related_fact_ids=list(fact_ids),
        related_calculation_types=list(calc_types),
    )


def structural_checks_for(n, status=ValidationStatus.PASS):
    return [
        make_item(f"arithmetic.{n}.{suffix}", status)
        for suffix in ARITHMETIC_SUFFIXES
    ]


def checks_for_arithmetic(results, extra=()):
    """Five structural checks per result at its original one-based
    position, plus any extra check items."""
    checks = []
    for n in range(1, len(results) + 1):
        checks.extend(structural_checks_for(n))
    checks.extend(extra)
    return checks


def make_requirement(
    requirement_id="req.r1",
    requirement_text="Required item.",
    status=RequirementStatus.MISSING,
    related_fact_ids=(),
    calculation_type=None,
):
    return RequirementResult(
        requirement_id=requirement_id,
        requirement_text=requirement_text,
        status=status,
        related_fact_ids=list(related_fact_ids),
        calculation_type=calculation_type,
    )


def make_evidence(
    evidence_id="ev.e1",
    requirement_text="Evidence item.",
    status=EvidenceStatus.UNKNOWN,
):
    return EvidenceChecklistItem(
        evidence_id=evidence_id,
        requirement_text=requirement_text,
        status=status,
    )


def make_review(
    review_id="rev.r1",
    level=ReviewLevel.CA_REVIEW,
    reason="Standard CA review before use.",
    mandatory=True,
):
    return ReviewRequirement(
        review_id=review_id,
        level=level,
        reason=reason,
        mandatory=mandatory,
    )


def make_validation_result(
    draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
    checks=None,
    requirements=None,
    evidence_checklist=None,
    review_requirements=None,
):
    return ValidationEngineResult(
        overall_status=ValidationStatus.PASS,
        draft_eligibility=draft_eligibility,
        case_severity=None,
        checks=[] if checks is None else list(checks),
        requirements=[] if requirements is None else list(requirements),
        evidence_checklist=(
            [] if evidence_checklist is None else list(evidence_checklist)
        ),
        review_requirements=(
            []
            if review_requirements is None
            else list(review_requirements)
        ),
    )


def make_permitted_inputs(**overrides):
    inputs = dict(
        classification=make_classification(),
        extraction_result=make_extraction(),
        preflight_result=make_preflight(),
        arithmetic_results=[],
        validation_result=make_validation_result(),
        deadline_result=None,
    )
    inputs.update(overrides)
    return inputs


def build_context(**overrides):
    """Build a controlled context with default permitted inputs plus the
    given overrides."""
    defaults = dict(
        classification=make_classification(),
        extraction_result=make_extraction(),
        preflight_result=make_preflight(),
        arithmetic_results=[],
        validation_result=make_validation_result(),
        deadline_result=None,
        drafting_profile=get_drafting_profile(
            ProceedingType.GST_SEC73_ITC
        ),
    )
    defaults.update(overrides)
    return engine._build_controlled_context(**defaults)


def build_prompt(**overrides):
    return engine._build_specialist_prompt(**make_permitted_inputs(**overrides))


def marker_line_position(prompt):
    """Char index of the real BEGIN marker line (the base prompt text
    mentions the markers inline, so plain .index() finds the wrong
    occurrence)."""
    return (
        prompt.index("\n" + engine._CONTEXT_BEGIN_MARKER + "\n") + 1
    )


def context_json_from_prompt(prompt):
    start = marker_line_position(prompt) + len(
        engine._CONTEXT_BEGIN_MARKER
    )
    json_text = (
        prompt[start:]
        .split("\n" + engine._CONTEXT_END_MARKER, 1)[0]
        .strip()
    )
    return json.loads(json_text)


# --- Step-9.3 helpers -----------------------------------------------------------

ITC_SECTION_IDS = ["sec73_itc.s1", "sec73_itc.s2", "sec73_itc.s3"]

DEFAULT_RESPONSE_BODIES = [
    "Working paper text with token [[FACT:F-001]].",
    "Reconciliation table with token [[ARITH:1]].",
    "Reviewable draft with [[DEADLINE]] and [[HEARING]].",
]


def make_response_json(sections=None):
    """Deterministic schema-valid §20.23 response for the ITC profile."""
    if sections is None:
        sections = [
            {"section_id": sid, "body_template": body}
            for sid, body in zip(ITC_SECTION_IDS, DEFAULT_RESPONSE_BODIES)
        ]
    return json.dumps({"sections": sections})


def run_draft(response=None, **overrides):
    """Call generate_specialist_draft with engine.call_gemini patched to
    return `response`. Returns (result, mocked_call)."""
    if response is None:
        response = make_response_json()
    defaults = dict(
        classification=make_classification(),
        extraction_result=make_extraction(),
        preflight_result=make_preflight(),
        arithmetic_results=[],
        validation_result=make_validation_result(),
        deadline_result=None,
    )
    defaults.update(overrides)
    with mock.patch.object(
        engine, "call_gemini", return_value=response
    ) as mocked:
        result = engine.generate_specialist_draft(**defaults)
    return result, mocked


def make_rich_validation(
    draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
    checks=None,
):
    requirements = [
        make_requirement(
            requirement_id="req.s", status=RequirementStatus.SATISFIED
        ),
        make_requirement(
            requirement_id="req.m", status=RequirementStatus.MISSING
        ),
        make_requirement(
            requirement_id="req.u", status=RequirementStatus.UNKNOWN
        ),
        make_requirement(
            requirement_id="req.d", status=RequirementStatus.DERIVED
        ),
        make_requirement(
            requirement_id="req.v",
            status=RequirementStatus.REQUIRES_VERIFICATION,
        ),
    ]
    evidence_checklist = [
        make_evidence(evidence_id="ev.e1"),
        make_evidence(evidence_id="ev.e2"),
    ]
    review_requirements = [
        make_review(review_id="rev.r1"),
        make_review(review_id="rev.r2"),
    ]
    return make_validation_result(
        draft_eligibility=draft_eligibility,
        checks=checks,
        requirements=requirements,
        evidence_checklist=evidence_checklist,
        review_requirements=review_requirements,
    )


def engine_source():
    """Raw engine module source text for surface assertions."""
    return pathlib.Path(engine.__file__).read_text(encoding="utf-8")


# --- 1. module surface (items 1–10) -------------------------------------------


class ModuleSurfaceTests(unittest.TestCase):
    """One public callable (generate_specialist_draft); the approved LLM
    boundary only; no provider SDK/network/engine imports."""

    SOURCE = pathlib.Path(engine.__file__).read_text(encoding="utf-8")

    ALLOWED_IMPORT_ROOTS = (
        "json", "pathlib", "typing", "domain", "modules", "workflows",
    )

    def test_module_imports(self):
        self.assertTrue(callable(engine._build_specialist_prompt))
        self.assertTrue(callable(engine._build_controlled_context))

    def test_only_public_callable_is_generate_specialist_draft(self):
        public = [
            name
            for name, obj in vars(engine).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == engine.__name__
        ]
        self.assertEqual(public, ["generate_specialist_draft"])

    def test_generate_specialist_draft_defined(self):
        self.assertTrue(callable(engine.generate_specialist_draft))

    def test_all_defs_private_except_public_api(self):
        for line in self.SOURCE.splitlines():
            match = re.match(r"^def (\w+)", line)
            if match:
                name = match.group(1)
                self.assertTrue(
                    name.startswith("_")
                    or name == "generate_specialist_draft",
                    name,
                )

    def test_only_private_module_assignments(self):
        for line in self.SOURCE.splitlines():
            match = re.match(r"^(\w+)\s*(?::[^=]*)?=", line)
            if match:
                self.assertTrue(
                    match.group(1).startswith("_"), match.group(1)
                )

    def test_approved_llm_client_boundary(self):
        self.assertIn(
            "from modules.llm_client import call_gemini", self.SOURCE
        )

    def test_no_provider_sdk_tokens(self):
        lowered = self.SOURCE.lower()
        for token in ("genai", "vertexai", "generativelanguage", "google"):
            self.assertNotIn(token, lowered, token)

    def test_no_network_imports(self):
        lowered = self.SOURCE.lower()
        for token in ("requests", "urllib", "socket", "streamlit", "http"):
            self.assertNotIn(token, lowered, token)

    def test_no_validation_engine_import(self):
        self.assertNotIn("validation_engine", self.SOURCE)

    def test_no_other_engine_imports(self):
        lowered = self.SOURCE.lower()
        for token in (
            "fact_engine",
            "preflight_engine",
            "arithmetic_engine",
            "deadline_engine",
            "proceeding_classifier",
            "taxonomy_registry",
        ):
            self.assertNotIn(token, lowered, token)

    def test_no_app_or_notice_explainer_import(self):
        lowered = self.SOURCE.lower()
        self.assertNotIn("notice_explainer", lowered)
        self.assertNotIn("app.py", lowered)
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
            roots <= set(self.ALLOWED_IMPORT_ROOTS), sorted(roots)
        )

    def test_no_caller_context_parameter(self):
        signature = inspect.signature(engine._build_specialist_prompt)
        names = set(signature.parameters)
        self.assertEqual(
            names,
            {
                "classification",
                "extraction_result",
                "preflight_result",
                "arithmetic_results",
                "validation_result",
                "deadline_result",
            },
        )


# --- 2. gate helper (items 11–22 preconditions) --------------------------------


class GateHelperTests(unittest.TestCase):
    """Direct unit tests of _gate_permitted preconditions 1–8."""

    def _gate(self, **overrides):
        defaults = dict(
            classification=make_classification(),
            validation_result=make_validation_result(),
            workflow=GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_ITC],
            drafting_profile=get_drafting_profile(
                ProceedingType.GST_SEC73_ITC
            ),
        )
        defaults.update(overrides)
        return engine._gate_permitted(**defaults)

    def test_permitted_inputs_pass_gate(self):
        self.assertTrue(self._gate())

    def test_non_deep_support_refuses(self):
        for level in (SupportLevel.TRIAGE_ONLY, SupportLevel.UNKNOWN):
            classification = make_classification(support_level=level)
            self.assertFalse(self._gate(classification=classification))

    def test_unknown_proceeding_refuses(self):
        classification = make_classification(
            proceeding_type=ProceedingType.UNKNOWN
        )
        self.assertFalse(self._gate(classification=classification))

    def test_blocked_eligibility_refuses(self):
        validation = make_validation_result(
            draft_eligibility=DraftEligibility.BLOCKED
        )
        self.assertFalse(self._gate(validation_result=validation))

    def test_missing_workflow_refuses(self):
        self.assertFalse(self._gate(workflow=None))

    def test_missing_profile_refuses(self):
        self.assertFalse(self._gate(drafting_profile=None))

    def test_workflow_misalignment_refuses(self):
        other = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_GENERAL]
        self.assertFalse(self._gate(workflow=other))

    def test_profile_misalignment_refuses(self):
        other = get_drafting_profile(ProceedingType.GST_SEC73_GENERAL)
        self.assertFalse(self._gate(drafting_profile=other))

    def test_validation_fail_refuses(self):
        validation = make_validation_result(
            checks=[make_item("x", ValidationStatus.FAIL)]
        )
        self.assertFalse(self._gate(validation_result=validation))

    def test_validation_warning_does_not_refuse(self):
        validation = make_validation_result(
            checks=[make_item("workflow.test.warning", ValidationStatus.WARNING)]
        )
        self.assertTrue(self._gate(validation_result=validation))


# --- 3. specialist prompt gate (items 11–25) -----------------------------------


class SpecialistPromptGateTests(unittest.TestCase):
    """End-to-end gate behavior through _build_specialist_prompt."""

    def test_deep_review_required_permits(self):
        prompt = build_prompt(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.REVIEW_REQUIRED
            )
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt)

    def test_deep_allowed_permits(self):
        prompt = build_prompt(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.ALLOWED
            )
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt)

    def test_blocked_refuses(self):
        self.assertIsNone(
            build_prompt(
                validation_result=make_validation_result(
                    draft_eligibility=DraftEligibility.BLOCKED
                )
            )
        )

    def test_triage_only_refuses(self):
        self.assertIsNone(
            build_prompt(
                classification=make_classification(
                    support_level=SupportLevel.TRIAGE_ONLY
                )
            )
        )

    def test_unknown_support_refuses(self):
        self.assertIsNone(
            build_prompt(
                classification=make_classification(
                    support_level=SupportLevel.UNKNOWN
                )
            )
        )

    def test_unknown_proceeding_refuses(self):
        self.assertIsNone(
            build_prompt(
                classification=make_classification(
                    proceeding_type=ProceedingType.UNKNOWN
                )
            )
        )

    def test_missing_workflow_refuses(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            self.assertIsNone(build_prompt())

    def test_missing_drafting_profile_refuses(self):
        with mock.patch.object(
            engine, "get_drafting_profile", return_value=None
        ):
            self.assertIsNone(build_prompt())

    def test_workflow_misalignment_refuses(self):
        other = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_GENERAL]
        with mock.patch.object(engine, "get_workflow", return_value=other):
            self.assertIsNone(build_prompt())

    def test_profile_misalignment_refuses(self):
        other = get_drafting_profile(ProceedingType.GST_SEC73_GENERAL)
        with mock.patch.object(
            engine, "get_drafting_profile", return_value=other
        ):
            self.assertIsNone(build_prompt())

    def test_validation_fail_refuses(self):
        validation = make_validation_result(
            checks=[make_item("fact.some.check", ValidationStatus.FAIL)]
        )
        self.assertIsNone(build_prompt(validation_result=validation))

    def test_validation_warning_does_not_refuse(self):
        validation = make_validation_result(
            checks=[
                make_item(
                    "workflow.test.warning",
                    ValidationStatus.WARNING,
                    message="Warning only.",
                )
            ]
        )
        prompt = build_prompt(validation_result=validation)
        self.assertIsInstance(prompt, str)
        context = context_json_from_prompt(prompt)
        self.assertEqual(
            [w["check_id"] for w in context["validation_warnings"]],
            ["workflow.test.warning"],
        )

    def test_prompt_missing_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "missing.txt"
            with mock.patch.object(
                engine, "_BASE_PROMPT_PATH", missing
            ):
                self.assertIsNone(build_prompt())

    def test_prompt_empty_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = pathlib.Path(tmp) / "empty.txt"
            empty.write_text("   \n\n  ", encoding="utf-8")
            with mock.patch.object(engine, "_BASE_PROMPT_PATH", empty):
                self.assertIsNone(build_prompt())

    def test_no_fallback_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "missing.txt"
            with mock.patch.dict(
                engine._WORKFLOW_PROMPT_PATHS,
                {"sec73_itc": missing},
                clear=False,
            ):
                self.assertIsNone(
                    engine._load_prompt_assets("sec73_itc")
                )
                # A different key still loads its own asset — no silent
                # substitution for the broken one.
                general = engine._load_prompt_assets("sec73_general")
                self.assertIsNotNone(general)
                self.assertNotIn(
                    "sec73_itc.s1", general[1]
                )
                self.assertIsNone(build_prompt())


# --- 4. top-level context (items 26–32) ----------------------------------------


class TopLevelContextTests(unittest.TestCase):
    def test_exactly_12_keys(self):
        context = build_context()
        self.assertEqual(len(context), 12)

    def test_exact_top_level_order(self):
        context = build_context()
        self.assertEqual(list(context), EXPECTED_TOP_LEVEL_KEYS)

    def test_schema_version_exact(self):
        self.assertEqual(build_context()["schema_version"], "phase2.step9.v1")

    def test_proceeding_type_uses_enum_value(self):
        self.assertEqual(
            build_context()["proceeding_type"], "gst_sec73_itc"
        )

    def test_draft_eligibility_uses_enum_value(self):
        context = build_context(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.ALLOWED
            )
        )
        self.assertEqual(context["draft_eligibility"], "allowed")

    def test_no_extra_top_level_key(self):
        context = build_context()
        self.assertEqual(set(context), set(EXPECTED_TOP_LEVEL_KEYS))

    def test_deterministic_identical_inputs_produce_identical_context(self):
        first = build_context()
        second = build_context()
        self.assertEqual(first, second)
        self.assertEqual(
            engine._serialize_context_json(first),
            engine._serialize_context_json(second),
        )


# --- 5. sections (items 33–37) --------------------------------------------------


class SectionContextTests(unittest.TestCase):
    def test_sections_exact_drafting_profile_order(self):
        for ptype in DEEP_TYPES:
            profile = get_drafting_profile(ptype)
            context = build_context(
                classification=make_classification(proceeding_type=ptype),
                drafting_profile=profile,
            )
            expected = [
                {"section_id": spec.section_id, "title": spec.title}
                for spec in profile.sections
            ]
            self.assertEqual(context["sections"], expected, ptype.name)

    def test_exact_section_object_two_key_shape(self):
        context = build_context()
        for section in context["sections"]:
            self.assertEqual(
                set(section), {"section_id", "title"}
            )

    def test_exact_section_ids(self):
        profile = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        context = build_context()
        self.assertEqual(
            [s["section_id"] for s in context["sections"]],
            [spec.section_id for spec in profile.sections],
        )

    def test_exact_section_titles(self):
        profile = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        context = build_context()
        self.assertEqual(
            [s["title"] for s in context["sections"]],
            [spec.title for spec in profile.sections],
        )

    def test_no_extra_section_field(self):
        context = build_context()
        for section in context["sections"]:
            self.assertEqual(len(section), 2)


# --- 6. facts (items 38–53) -----------------------------------------------------


class FactContextTests(unittest.TestCase):
    def _facts(self, *facts):
        context = build_context(
            extraction_result=make_extraction(facts=list(facts))
        )
        return context["facts"]

    def test_yes_fact_included(self):
        facts = self._facts(make_fact(fact_id="F-001"))
        self.assertEqual([f["fact_id"] for f in facts], ["F-001"])

    def test_conditional_fact_included(self):
        facts = self._facts(
            make_fact(
                fact_id="F-002",
                status=FactStatus.ALLEGED,
                allowed_in_draft=DraftPermission.CONDITIONAL,
            )
        )
        self.assertEqual([f["fact_id"] for f in facts], ["F-002"])

    def test_no_fact_excluded(self):
        facts = self._facts(
            make_fact(
                fact_id="F-003",
                allowed_in_draft=DraftPermission.NO,
            )
        )
        self.assertEqual(facts, [])

    def test_extraction_order_preserved_after_filtering(self):
        facts = self._facts(
            make_fact(fact_id="F-001"),
            make_fact(fact_id="F-002", allowed_in_draft=DraftPermission.NO),
            make_fact(
                fact_id="F-003",
                status=FactStatus.ALLEGED,
                allowed_in_draft=DraftPermission.CONDITIONAL,
            ),
            make_fact(fact_id="F-004", allowed_in_draft=DraftPermission.NO),
        )
        self.assertEqual(
            [f["fact_id"] for f in facts], ["F-001", "F-003"]
        )

    def test_object_has_exactly_7_keys(self):
        facts = self._facts(make_fact())
        self.assertEqual(len(facts[0]), 7)

    def test_exact_key_order(self):
        facts = self._facts(make_fact())
        self.assertEqual(list(facts[0]), EXPECTED_FACT_KEYS)

    def test_fact_type_uses_value(self):
        facts = self._facts(
            make_fact(fact_type=FactType.NOTICE_DATE)
        )
        self.assertEqual(facts[0]["fact_type"], "notice_date")

    def test_fact_role_uses_value(self):
        facts = self._facts(
            make_fact(fact_role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT)
        )
        self.assertEqual(
            facts[0]["fact_role"], "gstr3b_itc_claimed_amount"
        )

    def test_status_uses_value(self):
        facts = self._facts(make_fact(status=FactStatus.CONFIRMED))
        self.assertEqual(facts[0]["status"], "confirmed")

    def test_allowed_in_draft_uses_value(self):
        facts = self._facts(make_fact())
        self.assertEqual(facts[0]["allowed_in_draft"], "yes")

    def test_source_page_int_preserved(self):
        facts = self._facts(make_fact(source_page=7))
        self.assertEqual(facts[0]["source_page"], 7)

    def test_source_page_none_preserved(self):
        facts = self._facts(make_fact(source_page=None))
        self.assertIsNone(facts[0]["source_page"])

    def test_source_text_exact(self):
        facts = self._facts(make_fact(source_text="Exact source."))
        self.assertEqual(facts[0]["source_text"], "Exact source.")

    def test_claim_absent(self):
        context = build_context(
            extraction_result=make_extraction(
                facts=[make_fact(claim="CLAIM-SECRET")]
            )
        )
        self.assertNotIn("claim", context["facts"][0])
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("CLAIM-SECRET", json_text)

    def test_excluded_no_source_text_absent_from_serialized_json(self):
        context = build_context(
            extraction_result=make_extraction(
                facts=[
                    make_fact(fact_id="F-001"),
                    make_fact(
                        fact_id="F-002",
                        source_text="NO-SECRET-SOURCE",
                        allowed_in_draft=DraftPermission.NO,
                    ),
                ]
            )
        )
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("NO-SECRET-SOURCE", json_text)
        self.assertIn("Notice text.", json_text)

    def test_raw_notice_concept_absent(self):
        context = build_context()
        for key in context:
            self.assertNotIn("raw", key)
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("raw_text", json_text)


# --- 7. arithmetic (items 54–74) ------------------------------------------------


class ArithmeticContextTests(unittest.TestCase):
    def _arithmetic(self, results, checks):
        context = build_context(
            arithmetic_results=results,
            validation_result=make_validation_result(checks=checks),
        )
        return context["arithmetic"]

    def _items(self, results, checks):
        """Direct structural-filter unit test: no gate refusal involved."""
        return engine._build_arithmetic_context(results, checks)

    def test_structural_pass_plus_arithmetic_pass_included(self):
        result = make_arithmetic(status=ArithmeticStatus.PASS)
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["index"], 1)

    def test_structural_pass_plus_mismatch_included(self):
        result = make_arithmetic(status=ArithmeticStatus.MISMATCH)
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(len(items), 1)

    def test_insufficient_data_excluded(self):
        result = make_arithmetic(status=ArithmeticStatus.INSUFFICIENT_DATA)
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items, [])

    def test_structural_calculation_type_fail_excluded(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks[0] = make_item(
            "arithmetic.1.calculation_type", ValidationStatus.FAIL
        )
        self.assertEqual(self._items([result], checks), [])

    def test_structural_draft_permission_fail_excluded(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks[1] = make_item(
            "arithmetic.1.draft_permission", ValidationStatus.FAIL
        )
        self.assertEqual(self._items([result], checks), [])

    def test_structural_source_resolution_fail_excluded(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks[2] = make_item(
            "arithmetic.1.source_resolution", ValidationStatus.FAIL
        )
        self.assertEqual(self._items([result], checks), [])

    def test_structural_role_provenance_fail_excluded(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks[3] = make_item(
            "arithmetic.1.role_provenance", ValidationStatus.FAIL
        )
        self.assertEqual(self._items([result], checks), [])

    def test_structural_consistency_fail_excluded(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks[4] = make_item(
            "arithmetic.1.result_status_consistency", ValidationStatus.FAIL
        )
        self.assertEqual(self._items([result], checks), [])

    def test_missing_structural_check_excludes(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic([result])
        checks.pop(1)  # arithmetic.1.draft_permission gone
        self.assertEqual(self._items([result], checks), [])

    def test_arithmetic_outcome_warning_does_not_exclude(self):
        result = make_arithmetic()
        checks = checks_for_arithmetic(
            [result],
            extra=[
                make_item(
                    "arithmetic.1.outcome",
                    ValidationStatus.WARNING,
                    message="outcome warning",
                )
            ],
        )
        items = self._arithmetic([result], checks)
        self.assertEqual(len(items), 1)
        context = build_context(
            arithmetic_results=[result],
            validation_result=make_validation_result(checks=checks),
        )
        self.assertIn(
            "arithmetic.1.outcome",
            [w["check_id"] for w in context["validation_warnings"]],
        )

    def test_original_one_based_index_preserved(self):
        blocked = make_arithmetic(status=ArithmeticStatus.PASS)
        allowed = make_arithmetic(
            calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE
        )
        results = [blocked, allowed]
        checks = checks_for_arithmetic(results)
        checks[0] = make_item(
            "arithmetic.1.calculation_type", ValidationStatus.FAIL
        )
        items = self._items(results, checks)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["index"], 2)

    def test_filtering_does_not_renumber(self):
        blocked = make_arithmetic(status=ArithmeticStatus.INSUFFICIENT_DATA)
        allowed = make_arithmetic()
        results = [blocked, allowed]
        items = self._items(results, checks_for_arithmetic(results))
        self.assertEqual([item["index"] for item in items], [2])

    def test_exact_9_key_shape_and_order(self):
        result = make_arithmetic(
            source_fact_ids=["A", "B"],
            operand_values=[Decimal("777.70"), Decimal("111.10")],
        )
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(list(items[0]), EXPECTED_ARITHMETIC_KEYS)
        self.assertEqual(len(items[0]), 9)

    def test_decimal_operands_serialized_as_strings(self):
        result = make_arithmetic(operand_values=[Decimal("777.70")])
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["operand_values"], ["777.70"])
        self.assertIsInstance(items[0]["operand_values"][0], str)

    def test_decimal_result_serialized_as_string(self):
        result = make_arithmetic(result=Decimal("888.80"))
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["result"], "888.80")
        self.assertIsInstance(items[0]["result"], str)

    def test_no_float(self):
        result = make_arithmetic(
            operand_values=[Decimal("777.70")],
            result=Decimal("888.80"),
        )
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        json_text = engine._serialize_context_json(
            {
                "arithmetic": items,
                "proceeding_type": "gst_sec73_itc",
                "sections": [],
                "facts": [],
                "preflight": {},
                "deadline": None,
                "unresolved_requirements": [],
                "evidence_checklist": [],
                "review_requirements": [],
                "validation_warnings": [],
                "schema_version": "phase2.step9.v1",
                "draft_eligibility": "review_required",
            }
        )
        # a float would serialize as the truncated unquoted form
        self.assertNotIn('"777.7"', json_text)
        self.assertNotIn('"888.8"', json_text)
        self.assertNotIn(": 777.7", json_text)
        self.assertNotIn(": 888.8", json_text)
        self.assertIn('"777.70"', json_text)
        self.assertIn('"888.80"', json_text)

    def test_source_fact_ids_order_preserved(self):
        result = make_arithmetic(source_fact_ids=["A", "B"])
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["source_fact_ids"], ["A", "B"])

    def test_formula_preserved(self):
        result = make_arithmetic(formula="left - right")
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["formula"], "left - right")

    def test_currency_preserved(self):
        result = make_arithmetic(currency="INR")
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["currency"], "INR")

    def test_allowed_in_draft_enum_value_used(self):
        result = make_arithmetic(
            allowed_in_draft=DraftPermission.CONDITIONAL
        )
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["allowed_in_draft"], "conditional")

    def test_no_arithmetic_recomputation(self):
        result = make_arithmetic(
            operand_values=[Decimal("777.70")],
            result=Decimal("888.80"),
        )
        items = self._arithmetic([result], checks_for_arithmetic([result]))
        self.assertEqual(items[0]["result"], "888.80")
        self.assertEqual(items[0]["operand_values"], ["777.70"])
        self.assertEqual(items[0]["index"], 1)


# --- 8. preflight (items 75–83) -------------------------------------------------


class PreflightContextTests(unittest.TestCase):
    def _preflight(self, preflight):
        context = build_context(preflight_result=preflight)
        return context["preflight"]

    def test_exact_12_fields(self):
        self.assertEqual(
            len(self._preflight(make_preflight())), 12
        )

    def test_exact_model_order(self):
        self.assertEqual(
            list(self._preflight(make_preflight())),
            EXPECTED_PREFLIGHT_KEYS,
        )

    def test_enum_values_serialized(self):
        serialized = self._preflight(
            make_preflight(
                fact_extraction_status=FactExtractionStatus.PARTIAL,
                communication_identifier_status=(
                    CommunicationIdentifierStatus.BOTH_PRESENT
                ),
                authority_details_status=AuthorityDetailsStatus.MISSING,
                deadline_conflict_status=DeadlineConflictStatus.CONFLICT,
            )
        )
        self.assertEqual(serialized["fact_extraction_status"], "partial")
        self.assertEqual(
            serialized["communication_identifier_status"], "both_present"
        )
        self.assertEqual(serialized["authority_details_status"], "missing")
        self.assertEqual(serialized["deadline_conflict_status"], "conflict")

    def test_parsed_dates_iso(self):
        serialized = self._preflight(
            make_preflight(
                parsed_stated_due_dates=[
                    date(2026, 8, 1),
                    date(2026, 9, 15),
                ]
            )
        )
        self.assertEqual(
            serialized["parsed_stated_due_dates"],
            ["2026-08-01", "2026-09-15"],
        )

    def test_due_date_id_order_preserved(self):
        serialized = self._preflight(
            make_preflight(
                stated_due_date_fact_ids=["D-002", "D-001"]
            )
        )
        self.assertEqual(
            serialized["stated_due_date_fact_ids"], ["D-002", "D-001"]
        )

    def test_parsed_date_order_preserved(self):
        serialized = self._preflight(
            make_preflight(
                parsed_stated_due_dates=[
                    date(2026, 9, 15),
                    date(2026, 8, 1),
                ]
            )
        )
        self.assertEqual(
            serialized["parsed_stated_due_dates"],
            ["2026-09-15", "2026-08-01"],
        )

    def test_bool_values_remain_bool(self):
        serialized = self._preflight(
            make_preflight(
                portal_verification_required=False,
                authority_verification_required=True,
            )
        )
        self.assertIs(serialized["portal_verification_required"], False)
        self.assertIs(serialized["authority_verification_required"], True)

    def test_empty_lists_remain_empty(self):
        serialized = self._preflight(make_preflight())
        for key in (
            "stated_due_date_fact_ids",
            "parsed_stated_due_dates",
            "unparsed_stated_due_date_fact_ids",
            "hearing_fact_ids",
            "requested_document_fact_ids",
            "referenced_annexure_fact_ids",
        ):
            self.assertEqual(serialized[key], [], key)

    def test_no_extra_preflight_field(self):
        serialized = self._preflight(make_preflight())
        self.assertEqual(set(serialized), set(EXPECTED_PREFLIGHT_KEYS))


# --- 9. deadline (items 84–92) --------------------------------------------------


class DeadlineContextTests(unittest.TestCase):
    def _deadline(self, deadline):
        context = build_context(deadline_result=deadline)
        return context["deadline"]

    def test_none_becomes_json_null(self):
        context = build_context(deadline_result=None)
        self.assertIsNone(context["deadline"])
        json_text = engine._serialize_context_json(context)
        self.assertIn('"deadline": null', json_text)

    def test_supplied_deadline_exact_11_fields(self):
        self.assertEqual(
            len(self._deadline(make_deadline())), 11
        )

    def test_exact_model_order(self):
        self.assertEqual(
            list(self._deadline(make_deadline())),
            EXPECTED_DEADLINE_KEYS,
        )

    def test_enum_values_use_value(self):
        serialized = self._deadline(
            make_deadline(
                deadline_confidence=DeadlineConfidence.ESTIMATED,
                deadline_status=DeadlineStatus.CRITICAL,
                hearing_status=HearingStatus.UPCOMING,
            )
        )
        self.assertEqual(serialized["deadline_confidence"], "estimated")
        self.assertEqual(serialized["deadline_status"], "critical")
        self.assertEqual(serialized["hearing_status"], "upcoming")

    def test_dates_iso(self):
        serialized = self._deadline(
            make_deadline(
                notice_date=date(2025, 3, 10),
                response_deadline=date(2025, 4, 9),
                hearing_date=date(2025, 4, 15),
            )
        )
        self.assertEqual(serialized["notice_date"], "2025-03-10")
        self.assertEqual(serialized["response_deadline"], "2025-04-09")
        self.assertEqual(serialized["hearing_date"], "2025-04-15")

    def test_optional_none_remains_null(self):
        serialized = self._deadline(make_deadline())
        self.assertIsNone(serialized["service_date"])
        self.assertIsNone(serialized["response_period_days"])
        self.assertIsNone(serialized["response_deadline"])
        self.assertIsNone(serialized["days_remaining"])
        self.assertIsNone(serialized["hearing_date"])

    def test_no_current_date_field(self):
        serialized = self._deadline(make_deadline())
        self.assertNotIn("today", serialized)
        self.assertNotIn("current_date", serialized)

    def test_no_inferred_field(self):
        serialized = self._deadline(make_deadline())
        self.assertEqual(set(serialized), set(EXPECTED_DEADLINE_KEYS))

    def test_no_date_recomputation(self):
        serialized = self._deadline(
            make_deadline(
                notice_date=date(2025, 3, 10),
                response_deadline=date(2025, 4, 9),
            )
        )
        self.assertEqual(serialized["notice_date"], "2025-03-10")
        self.assertEqual(serialized["response_deadline"], "2025-04-09")


# --- 10. unresolved requirements (items 93–101) ----------------------------------


class RequirementContextTests(unittest.TestCase):
    def _requirements(self, requirements):
        context = build_context(
            validation_result=make_validation_result(
                requirements=requirements
            )
        )
        return context["unresolved_requirements"]

    def test_missing_included(self):
        items = self._requirements([make_requirement(status=RequirementStatus.MISSING)])
        self.assertEqual([i["requirement_id"] for i in items], ["req.r1"])

    def test_unknown_included(self):
        items = self._requirements([make_requirement(status=RequirementStatus.UNKNOWN)])
        self.assertEqual(len(items), 1)

    def test_requires_verification_included(self):
        items = self._requirements(
            [make_requirement(status=RequirementStatus.REQUIRES_VERIFICATION)]
        )
        self.assertEqual(len(items), 1)

    def test_satisfied_excluded(self):
        items = self._requirements(
            [make_requirement(status=RequirementStatus.SATISFIED)]
        )
        self.assertEqual(items, [])

    def test_derived_excluded(self):
        items = self._requirements(
            [make_requirement(status=RequirementStatus.DERIVED)]
        )
        self.assertEqual(items, [])

    def test_source_order_preserved(self):
        requirements = [
            make_requirement(
                requirement_id="req.r1", status=RequirementStatus.SATISFIED
            ),
            make_requirement(
                requirement_id="req.r2", status=RequirementStatus.MISSING
            ),
            make_requirement(
                requirement_id="req.r3", status=RequirementStatus.DERIVED
            ),
            make_requirement(
                requirement_id="req.r4", status=RequirementStatus.UNKNOWN
            ),
            make_requirement(
                requirement_id="req.r5",
                status=RequirementStatus.REQUIRES_VERIFICATION,
            ),
        ]
        items = self._requirements(requirements)
        self.assertEqual(
            [i["requirement_id"] for i in items],
            ["req.r2", "req.r4", "req.r5"],
        )

    def test_exact_5_key_shape_and_order(self):
        items = self._requirements([make_requirement()])
        self.assertEqual(list(items[0]), EXPECTED_REQUIREMENT_KEYS)
        self.assertEqual(len(items[0]), 5)

    def test_calculation_type_value_or_null(self):
        requirements = [
            make_requirement(
                requirement_id="req.a",
                calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            ),
            make_requirement(
                requirement_id="req.b", calculation_type=None
            ),
        ]
        items = self._requirements(requirements)
        self.assertEqual(items[0]["calculation_type"], "itc_difference")
        self.assertIsNone(items[1]["calculation_type"])

    def test_no_factual_assertion_generated(self):
        items = self._requirements(
            [make_requirement(requirement_text="Missing material.")]
        )
        self.assertEqual(items[0]["requirement_text"], "Missing material.")
        json_text = engine._serialize_context_json(
            build_context(
                validation_result=make_validation_result(
                    requirements=[
                        make_requirement(
                            requirement_text="Missing material."
                        )
                    ]
                )
            )
        )
        self.assertNotIn("assertion", json_text)


# --- 11. evidence (items 102–108) -------------------------------------------------


class EvidenceContextTests(unittest.TestCase):
    def _evidence(self, items):
        context = build_context(
            validation_result=make_validation_result(
                evidence_checklist=items
            )
        )
        return context["evidence_checklist"]

    def test_exact_evidence_list_order(self):
        items = self._evidence(
            [
                make_evidence(evidence_id="ev.e1"),
                make_evidence(evidence_id="ev.e2"),
            ]
        )
        self.assertEqual(
            [i["evidence_id"] for i in items], ["ev.e1", "ev.e2"]
        )

    def test_exact_3_key_object(self):
        items = self._evidence([make_evidence()])
        self.assertEqual(list(items[0]), EXPECTED_EVIDENCE_KEYS)
        self.assertEqual(len(items[0]), 3)

    def test_status_enum_value(self):
        items = self._evidence([make_evidence(status=EvidenceStatus.UNKNOWN)])
        self.assertEqual(items[0]["status"], "unknown")

    def test_unknown_remains_unknown(self):
        items = self._evidence([make_evidence(status=EvidenceStatus.UNKNOWN)])
        self.assertEqual(items[0]["status"], "unknown")

    def test_no_present_inference(self):
        items = self._evidence([make_evidence(status=EvidenceStatus.UNKNOWN)])
        self.assertNotEqual(items[0]["status"], "present")

    def test_no_missing_inference(self):
        items = self._evidence([make_evidence(status=EvidenceStatus.UNKNOWN)])
        self.assertNotEqual(items[0]["status"], "missing")

    def test_no_duplicated_workflow_evidence_surface(self):
        context = build_context(
            validation_result=make_validation_result(
                evidence_checklist=[make_evidence()]
            )
        )
        self.assertNotIn("evidence_requirements", context)
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("evidence_requirements", json_text)


# --- 12. reviews (items 109–114) --------------------------------------------------


class ReviewContextTests(unittest.TestCase):
    def _reviews(self, items):
        context = build_context(
            validation_result=make_validation_result(
                review_requirements=items
            )
        )
        return context["review_requirements"]

    def test_exact_stored_order(self):
        items = self._reviews(
            [
                make_review(review_id="rev.r1"),
                make_review(review_id="rev.r2"),
            ]
        )
        self.assertEqual([i["review_id"] for i in items], ["rev.r1", "rev.r2"])

    def test_exact_4_key_object(self):
        items = self._reviews([make_review()])
        self.assertEqual(list(items[0]), EXPECTED_REVIEW_KEYS)
        self.assertEqual(len(items[0]), 4)

    def test_level_enum_value(self):
        items = self._reviews(
            [make_review(level=ReviewLevel.SENIOR_CA_OR_ADVOCATE)]
        )
        self.assertEqual(items[0]["level"], "senior_ca_or_advocate")

    def test_reason_verbatim(self):
        reason = "Mandatory senior review before any filing; escalate now."
        items = self._reviews([make_review(reason=reason)])
        self.assertEqual(items[0]["reason"], reason)

    def test_mandatory_bool(self):
        items = self._reviews(
            [make_review(review_id="rev.t", mandatory=True)]
        )
        self.assertIs(items[0]["mandatory"], True)
        items = self._reviews(
            [make_review(review_id="rev.f", mandatory=False)]
        )
        self.assertIs(items[0]["mandatory"], False)

    def test_no_reason_paraphrase(self):
        reason = "Escalate; do not file without partner sign-off."
        context = build_context(
            validation_result=make_validation_result(
                review_requirements=[make_review(reason=reason)]
            )
        )
        json_text = engine._serialize_context_json(context)
        self.assertIn(reason, json_text)


# --- 13. validation warnings (items 115–123) ---------------------------------------


class WarningContextTests(unittest.TestCase):
    def _warnings(self, checks):
        context = build_context(
            validation_result=make_validation_result(checks=checks)
        )
        return context["validation_warnings"]

    def test_warning_included(self):
        warnings = self._warnings(
            [make_item("workflow.test.warning", ValidationStatus.WARNING)]
        )
        self.assertEqual(
            [w["check_id"] for w in warnings], ["workflow.test.warning"]
        )

    def test_pass_excluded(self):
        warnings = self._warnings(
            [
                make_item("workflow.test.pass", ValidationStatus.PASS),
                make_item("workflow.test.warning", ValidationStatus.WARNING),
            ]
        )
        self.assertEqual(
            [w["check_id"] for w in warnings], ["workflow.test.warning"]
        )

    def test_fail_causes_gate_refusal(self):
        validation = make_validation_result(
            checks=[make_item("fact.some.check", ValidationStatus.FAIL)]
        )
        self.assertIsNone(build_prompt(validation_result=validation))
        self.assertIsNone(
            build_context(validation_result=validation)
        )

    def test_warning_order_preserved(self):
        warnings = self._warnings(
            [
                make_item("w1", ValidationStatus.WARNING),
                make_item("w2", ValidationStatus.WARNING),
            ]
        )
        self.assertEqual([w["check_id"] for w in warnings], ["w1", "w2"])

    def test_exact_5_key_shape(self):
        warnings = self._warnings(
            [make_item("w1", ValidationStatus.WARNING)]
        )
        self.assertEqual(list(warnings[0]), EXPECTED_WARNING_KEYS)
        self.assertEqual(len(warnings[0]), 5)

    def test_status_enum_value(self):
        warnings = self._warnings(
            [make_item("w1", ValidationStatus.WARNING)]
        )
        self.assertEqual(warnings[0]["status"], "warning")

    def test_related_fact_ids_order_preserved(self):
        warnings = self._warnings(
            [
                make_item(
                    "w1",
                    ValidationStatus.WARNING,
                    fact_ids=["F-002", "F-001"],
                )
            ]
        )
        self.assertEqual(
            warnings[0]["related_fact_ids"], ["F-002", "F-001"]
        )

    def test_calculation_types_serialized_to_values(self):
        warnings = self._warnings(
            [
                make_item(
                    "w1",
                    ValidationStatus.WARNING,
                    calc_types=[
                        ArithmeticCalculationType.ITC_DIFFERENCE,
                        ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
                    ],
                )
            ]
        )
        self.assertEqual(
            warnings[0]["related_calculation_types"],
            ["itc_difference", "output_tax_difference"],
        )

    def test_no_extra_explanation(self):
        warnings = self._warnings(
            [make_item("w1", ValidationStatus.WARNING)]
        )
        self.assertEqual(len(warnings[0]), 5)


# --- 14. forbidden context (items 124–138) ------------------------------------------


class ForbiddenContextTests(unittest.TestCase):
    def _rich_context(self):
        workflow = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC73_ITC]
        return build_context(
            extraction_result=make_extraction(
                facts=[
                    make_fact(
                        fact_id="F-001",
                        claim="CLAIM-SECRET",
                        source_text="KEEP-SOURCE",
                    ),
                    make_fact(
                        fact_id="F-002",
                        source_text="NO-SECRET-SOURCE",
                        allowed_in_draft=DraftPermission.NO,
                    ),
                ]
            )
        ), workflow

    def test_no_claim(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("claim", json_text)
        self.assertNotIn("CLAIM-SECRET", json_text)

    def test_no_draft_permission_no_source_text(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("NO-SECRET-SOURCE", json_text)

    def test_no_workflow_special_rules(self):
        context, workflow = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("special_rules", context)
        self.assertNotIn("special_rules", json_text)
        for rule in workflow.special_rules:
            self.assertNotIn(rule, json_text, rule)

    def test_no_workflow_issue_types(self):
        context, workflow = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("issue_types", json_text)
        for issue in workflow.issue_types:
            self.assertNotIn(issue, json_text, issue)

    def test_no_workflow_required_facts_surface(self):
        context, workflow = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("required_facts", context)
        self.assertNotIn("required_facts", json_text)

    def test_no_raw_evidence_requirements_duplicate(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("evidence_requirements", json_text)

    def test_no_notice_analysis(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("NoticeAnalysis", json_text)

    def test_no_evidence_gap(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("EvidenceGap", json_text)

    def test_no_potential_defence(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("PotentialDefence", json_text)

    def test_no_current_date_time(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("today", context)
        self.assertNotIn("timestamp", json_text)
        self.assertNotIn(str(date.today()), json_text)

    def test_no_environment_variable(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("USERPROFILE", json_text)
        self.assertNotIn("PATH", context)

    def test_no_prompt_path(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("base_rules.txt", json_text)
        self.assertNotIn("sec73_itc.txt", json_text)
        self.assertNotIn(str(engine._PROMPTS_DIR), json_text)

    def test_no_api_key(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("api", json_text.lower())
        self.assertNotIn("key", json_text.lower())

    def test_no_external_url_introduced_by_builder(self):
        context, _ = self._rich_context()
        json_text = engine._serialize_context_json(context)
        self.assertNotIn("http", json_text)

    def test_no_caller_context_parameter(self):
        signature = inspect.signature(engine._build_controlled_context)
        names = set(signature.parameters)
        self.assertEqual(
            names,
            {
                "classification",
                "extraction_result",
                "preflight_result",
                "arithmetic_results",
                "validation_result",
                "deadline_result",
                "drafting_profile",
            },
        )


# --- 15. JSON encoding (items 139–145) ----------------------------------------------


class JsonEncodingTests(unittest.TestCase):
    def test_indent_2_behavior(self):
        context = build_context()
        json_text = engine._serialize_context_json(context)
        self.assertIn('\n  "schema_version"', json_text)
        self.assertIn('\n  "proceeding_type"', json_text)

    def test_ensure_ascii_false_preserves_non_ascii(self):
        context = build_context(
            extraction_result=make_extraction(
                facts=[
                    make_fact(
                        source_text="₹ 12,34,567.00 — as per notice"
                    )
                ]
            )
        )
        json_text = engine._serialize_context_json(context)
        self.assertIn("₹ 12,34,567.00 — as per notice", json_text)

    def test_keys_not_alphabetically_sorted(self):
        json_text = engine._serialize_context_json(build_context())
        self.assertLess(
            json_text.index('"proceeding_type"'),
            json_text.index('"arithmetic"'),
        )

    def test_deterministic_json_byte_for_byte(self):
        first = engine._serialize_context_json(build_context())
        second = engine._serialize_context_json(build_context())
        self.assertEqual(first, second)
        prompt_a = build_prompt()
        prompt_b = build_prompt()
        self.assertEqual(prompt_a, prompt_b)

    def test_no_python_repr_syntax(self):
        json_text = engine._serialize_context_json(build_context())
        self.assertNotIn("FactStatus.", json_text)
        self.assertNotIn("ProceedingType.", json_text)
        self.assertNotIn("Decimal(", json_text)
        self.assertNotIn("GST_SEC73_ITC", json_text)
        self.assertIn("gst_sec73_itc", json_text)

    def test_decimal_strings_exact(self):
        result = make_arithmetic(result=Decimal("888.80"))
        context = build_context(
            arithmetic_results=[result],
            validation_result=make_validation_result(
                checks=checks_for_arithmetic([result])
            ),
        )
        json_text = engine._serialize_context_json(context)
        self.assertIn('"888.80"', json_text)
        self.assertNotIn('"888.8"', json_text)
        self.assertNotIn(": 888.8", json_text)

    def test_dates_exact_iso(self):
        context = build_context(
            preflight_result=make_preflight(
                parsed_stated_due_dates=[date(2026, 8, 1)]
            )
        )
        json_text = engine._serialize_context_json(context)
        self.assertIn("2026-08-01", json_text)


# --- 16. prompt assets (items 146–155) -----------------------------------------------


class PromptAssetTests(unittest.TestCase):
    EXPECTED_RELATIVE_PATHS = {
        "base_rules.txt",
        "gst/sec73_itc.txt",
        "gst/sec73_general.txt",
        "gst/sec73_rcm.txt",
        "gst/sec74_fraud.txt",
        "gst/sec129.txt",
    }

    def test_exactly_six_authorized_prompt_files_exist(self):
        found = {
            path.relative_to(engine._PROMPTS_DIR).as_posix()
            for path in engine._PROMPTS_DIR.rglob("*.txt")
        }
        self.assertEqual(found, self.EXPECTED_RELATIVE_PATHS)

    def test_base_prompt_non_empty_utf8(self):
        text = engine._BASE_PROMPT_PATH.read_text(encoding="utf-8")
        self.assertTrue(text.strip())

    def test_each_workflow_prompt_non_empty_utf8(self):
        for path in engine._WORKFLOW_PROMPT_PATHS.values():
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.strip(), str(path))

    def test_closed_prompt_key_mapping_exact(self):
        expected = {
            key: engine._PROMPTS_DIR / "gst" / f"{key}.txt"
            for key in (
                "sec73_itc",
                "sec73_general",
                "sec73_rcm",
                "sec74_fraud",
                "sec129",
            )
        }
        self.assertEqual(engine._WORKFLOW_PROMPT_PATHS, expected)

    def test_no_unknown_prompt_key_mapping(self):
        self.assertIsNone(engine._load_prompt_assets("sec999"))
        self.assertIsNone(engine._load_prompt_assets(""))
        self.assertIsNone(
            engine._load_prompt_assets("../base_rules")
        )

    def test_no_path_traversal_behavior(self):
        for path in engine._WORKFLOW_PROMPT_PATHS.values():
            self.assertNotIn("..", str(path))
            self.assertEqual(path.parent, engine._PROMPTS_DIR / "gst")

    def test_no_dynamic_prompt_discovery(self):
        lowered = ModuleSurfaceTests.SOURCE.lower()
        for token in ("glob", "iterdir", "listdir", "walk", "scandir"):
            self.assertNotIn(token, lowered, token)

    def test_notice_prompt_not_referenced(self):
        self.assertNotIn("notice_prompt", ModuleSurfaceTests.SOURCE)

    def test_no_prompt_contains_raw_synthetic_notice_facts(self):
        for path in engine._PROMPTS_DIR.rglob("*.txt"):
            text = path.read_text(encoding="utf-8")
            for token in ("F-001", "GSTIN", "₹", "2026"):
                self.assertNotIn(token, text, f"{path}: {token}")

    def test_no_prompt_contains_api_key_or_env_data(self):
        for path in engine._PROMPTS_DIR.rglob("*.txt"):
            lowered = path.read_text(encoding="utf-8").lower()
            for token in ("api_key", ".env", "sk-"):
                self.assertNotIn(token, lowered, f"{path}: {token}")


# --- 17. base prompt content (items 156–176) -----------------------------------------


class BasePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = engine._BASE_PROMPT_PATH.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.text.split())

    def assert_phrase(self, phrase):
        self.assertIn(phrase, self.normalized, phrase)

    def test_strict_json_only_requirement(self):
        self.assert_phrase("Return ONLY one strict JSON object")

    def test_no_markdown_fence_requirement(self):
        self.assert_phrase("No markdown code fence")

    def test_exact_supplied_sections_and_order_requirement(self):
        self.assert_phrase(
            "Emit exactly one section for each supplied section, in the "
            "supplied order, with the exact supplied section_id."
        )

    def test_approved_fact_token_guidance(self):
        self.assertIn("[[FACT:<fact_id>]]", self.text)

    def test_approved_arith_token_guidance(self):
        self.assertIn("[[ARITH:<N>]]", self.text)

    def test_approved_deadline_token_guidance(self):
        self.assertIn("[[DEADLINE]]", self.text)

    def test_approved_hearing_token_guidance(self):
        self.assertIn("[[HEARING]]", self.text)

    def test_no_invented_taxpayer_facts(self):
        self.assert_phrase("Do not invent taxpayer facts.")

    def test_allegation_preservation_instruction(self):
        self.assert_phrase("Allegations remain allegations")

    def test_unresolved_requirement_instruction(self):
        self.assert_phrase(
            "Do not convert unresolved requirements into factual assertions."
        )

    def test_unknown_evidence_instruction(self):
        self.assert_phrase(
            "UNKNOWN evidence must not be described as attached, enclosed, "
            "annexed, submitted, provided, available, or verified."
        )

    def test_no_case_law_invention(self):
        self.assert_phrase("Do not invent case law.")

    def test_no_citation_invention(self):
        self.assert_phrase("Do not invent citations.")

    def test_no_external_url(self):
        self.assert_phrase("Do not output external URLs.")

    def test_no_statutory_quotation_invention(self):
        self.assert_phrase("Do not invent statutory quotations.")

    def test_no_arithmetic_calculation(self):
        self.assert_phrase("Do not compute arithmetic.")

    def test_no_deadline_calculation(self):
        self.assert_phrase("Do not compute deadlines.")

    def test_no_authenticity_decision(self):
        self.assert_phrase("Do not decide GST-portal authenticity.")

    def test_no_jurisdiction_competence_decision(self):
        self.assert_phrase("Do not decide officer competence or jurisdiction.")

    def test_mandatory_review_remains_mandatory(self):
        self.assert_phrase(
            "Mandatory review requirements remain mandatory"
        )

    def test_ca_working_draft_limitation(self):
        self.assert_phrase(
            "The output is a CA working draft, not filing approval."
        )


# --- 18. workflow prompt content (items 177–198) -------------------------------------


class WorkflowPromptTests(unittest.TestCase):
    SECTION_ID_PATTERN = re.compile(
        r"\b(?:sec73_itc|sec73_general|sec73_rcm|sec74_fraud|sec129)"
        r"\.s\d+\b"
    )

    def _workflow_prompt(self, ptype):
        profile = get_drafting_profile(ptype)
        return (
            profile,
            engine._load_prompt_assets(profile.prompt_key)[1],
        )

    def test_each_section_id_appears_exactly_once(self):
        for ptype in DEEP_TYPES:
            profile, prompt = self._workflow_prompt(ptype)
            for spec in profile.sections:
                self.assertEqual(
                    prompt.count(spec.section_id),
                    1,
                    f"{ptype.name}: {spec.section_id}",
                )

    def test_ids_occur_in_profile_order(self):
        for ptype in DEEP_TYPES:
            profile, prompt = self._workflow_prompt(ptype)
            positions = [prompt.index(spec.section_id) for spec in profile.sections]
            self.assertEqual(positions, sorted(positions), ptype.name)

    def test_exact_profile_titles_present(self):
        for ptype in DEEP_TYPES:
            profile, prompt = self._workflow_prompt(ptype)
            normalized = " ".join(prompt.split())
            for spec in profile.sections:
                self.assertIn(
                    spec.title, normalized, f"{ptype.name}: {spec.title}"
                )

    def test_no_extra_section_id(self):
        for ptype in DEEP_TYPES:
            profile, prompt = self._workflow_prompt(ptype)
            found = set(self.SECTION_ID_PATTERN.findall(prompt))
            expected = {spec.section_id for spec in profile.sections}
            self.assertEqual(found, expected, ptype.name)

    def test_itc_reconciliation_not_final_liability(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_ITC)
        normalized = " ".join(prompt.split())
        self.assertIn("not final legal liability", normalized)

    def test_itc_unresolved_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_ITC)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Unresolved ITC or evidence matters stay unresolved", normalized
        )

    def test_general_reconciliation_not_final_liability(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_GENERAL)
        normalized = " ".join(prompt.split())
        self.assertIn("not final legal liability", normalized)

    def test_general_unresolved_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_GENERAL)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Unresolved liability or evidence matters stay unresolved",
            normalized,
        )

    def test_rcm_allegation_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_RCM)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Departmental RCM content represented by ALLEGED facts remains "
            "an allegation",
            normalized,
        )

    def test_rcm_no_amount_computation_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC73_RCM)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Do not perform or state any RCM amount computation.", normalized
        )

    def test_fraud_allegation_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC74_FRAUD)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Fraud or suppression content remains a departmental allegation",
            normalized,
        )

    def test_fraud_not_established_or_proved_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC74_FRAUD)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "never state fraud as established or proved", normalized
        )

    def test_fraud_senior_review_reminder(self):
        _, prompt = self._workflow_prompt(ProceedingType.GST_SEC74_FRAUD)
        normalized = " ".join(prompt.split())
        self.assertIn(
            "The mandatory senior CA or advocate review remains mandatory "
            "and outside model control",
            normalized,
        )

    def test_sec129_no_static_100_percent(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn("Do not state a static 100% penalty.", normalized)

    def test_sec129_no_universal_seven_day(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Do not apply a universal seven-day response rule.", normalized
        )

    def test_sec129_mov09_not_taxpayer_reply(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Do not treat MOV-09 as a taxpayer reply form.", normalized
        )

    def test_sec129_no_invented_eway_reason(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn("Do not invent an e-way-bill reason.", normalized)

    def test_sec129_no_section_130_deep_assumption(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Do not assume a Section 130 deep-workflow proceeding.",
            normalized,
        )

    def test_sec129_deadline_only_supplied_context(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC129_ENFORCE
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Use deadline information only through the supplied deadline "
            "context",
            normalized,
        )

    def test_no_workflow_prompt_contains_case_law_citation(self):
        for ptype in DEEP_TYPES:
            _, prompt = self._workflow_prompt(ptype)
            lowered = prompt.lower()
            self.assertNotIn("case law", lowered, ptype.name)
            self.assertNotIn("citation", lowered, ptype.name)
            self.assertNotIn("supreme court", lowered, ptype.name)
            self.assertNotIn("cestat", lowered, ptype.name)
            self.assertIsNone(
                re.search(r"\bv\.\s+[A-Z]", prompt), ptype.name
            )

    def test_no_workflow_prompt_contains_raw_special_rules(self):
        for ptype in DEEP_TYPES:
            _, prompt = self._workflow_prompt(ptype)
            for rule in GST_WORKFLOW_REGISTRY[ptype].special_rules:
                self.assertNotIn(rule, prompt, ptype.name)

    def test_no_workflow_prompt_adds_hidden_case_facts(self):
        for ptype in DEEP_TYPES:
            _, prompt = self._workflow_prompt(ptype)
            for token in ("F-001", "GSTIN", "₹", "2026"):
                self.assertNotIn(token, prompt, f"{ptype.name}: {token}")


# --- 19. prompt assembly (items 199–211) ----------------------------------------------


class AssemblyTests(unittest.TestCase):
    def _parts(self, **overrides):
        prompt = build_prompt(**overrides)
        self.assertIsNotNone(prompt)
        base_text = engine._BASE_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()
        workflow_text = engine._load_prompt_assets("sec73_itc")[1]
        context = engine._build_controlled_context(
            classification=make_classification(),
            extraction_result=make_extraction(),
            preflight_result=make_preflight(),
            arithmetic_results=[],
            validation_result=make_validation_result(),
            deadline_result=None,
            drafting_profile=get_drafting_profile(
                ProceedingType.GST_SEC73_ITC
            ),
        )
        context_json = engine._serialize_context_json(context)
        return prompt, base_text, workflow_text, context_json

    def test_base_appears_first(self):
        prompt, base_text, _, _ = self._parts()
        self.assertTrue(prompt.startswith(base_text))

    def test_exactly_one_blank_line_between_base_and_workflow(self):
        prompt, base_text, workflow_text, _ = self._parts()
        tail = prompt[len(base_text):]
        self.assertTrue(tail.startswith("\n\n" + workflow_text), tail[:80])
        self.assertFalse(tail.startswith("\n\n\n"))

    def test_workflow_appears_second(self):
        prompt, base_text, workflow_text, _ = self._parts()
        self.assertEqual(
            prompt[len(base_text):len(base_text) + len(workflow_text) + 2],
            "\n\n" + workflow_text,
        )

    def test_exactly_one_blank_line_before_begin_marker(self):
        prompt, _, _, _ = self._parts()
        marker_index = marker_line_position(prompt)
        self.assertEqual(
            prompt[marker_index - 2:marker_index], "\n\n"
        )

    def test_exact_begin_marker(self):
        prompt, _, _, _ = self._parts()
        self.assertIn(engine._CONTEXT_BEGIN_MARKER, prompt)

    def test_json_immediately_follows_marker_on_next_line(self):
        prompt, _, _, context_json = self._parts()
        start = marker_line_position(prompt) + len(
            engine._CONTEXT_BEGIN_MARKER
        )
        after = prompt[start:]
        self.assertTrue(
            after.startswith("\n" + context_json), after[:80]
        )

    def test_exact_end_marker_after_json(self):
        prompt, _, _, context_json = self._parts()
        start = marker_line_position(prompt) + len(
            engine._CONTEXT_BEGIN_MARKER
        )
        after = prompt[start:]
        self.assertEqual(
            after, "\n" + context_json + "\n" + engine._CONTEXT_END_MARKER
        )

    def test_no_dynamic_text_after_end(self):
        prompt, _, _, _ = self._parts()
        self.assertTrue(prompt.endswith(engine._CONTEXT_END_MARKER))

    def test_no_markdown_fence(self):
        prompt, _, _, _ = self._parts()
        self.assertNotIn("```", prompt)

    def test_no_raw_notice_append(self):
        prompt, _, _, _ = self._parts()
        self.assertNotIn("raw_text", prompt)

    def test_no_current_date_append(self):
        prompt, _, _, _ = self._parts()
        self.assertNotIn(str(date.today()), prompt)

    def test_only_one_controlled_context_block(self):
        prompt, _, _, _ = self._parts()
        begins = re.findall(
            r"(?m)^CONTROLLED_CONTEXT_JSON_BEGIN$", prompt
        )
        ends = re.findall(r"(?m)^CONTROLLED_CONTEXT_JSON_END$", prompt)
        self.assertEqual(begins, [engine._CONTEXT_BEGIN_MARKER])
        self.assertEqual(ends, [engine._CONTEXT_END_MARKER])

    def test_identical_inputs_produce_identical_final_prompt_bytes(self):
        first = build_prompt()
        second = build_prompt()
        self.assertEqual(first, second)
        self.assertIsInstance(first, str)

    def test_exact_full_assembly_equality(self):
        prompt, base_text, workflow_text, context_json = self._parts()
        expected = (
            base_text
            + "\n\n"
            + workflow_text
            + "\n\n"
            + engine._CONTEXT_BEGIN_MARKER
            + "\n"
            + context_json
            + "\n"
            + engine._CONTEXT_END_MARKER
        )
        self.assertEqual(prompt, expected)


# --- 20. staging (items 212–224) ------------------------------------------------------


class StagingTests(unittest.TestCase):
    SOURCE = pathlib.Path(engine.__file__).read_text(encoding="utf-8")

    def test_approved_call_gemini_boundary_only(self):
        self.assertIn("call_gemini", self.SOURCE)
        self.assertNotIn("_router", self.SOURCE)
        self.assertNotIn("ProviderError", self.SOURCE)
        self.assertNotIn("PoolExhaustedError", self.SOURCE)

    def test_strict_json_loads_parser_present(self):
        self.assertIn("json.loads(", self.SOURCE)

    def test_no_alternate_json_loader(self):
        # "json.load(" must not appear; "json.loads(" is the only loader.
        self.assertNotIn("json.load(", self.SOURCE)

    def test_interim_draft_section_creation_present(self):
        self.assertIn("DraftSection(", self.SOURCE)

    def test_specialist_draft_result_creation_present(self):
        self.assertIn("SpecialistDraftResult(", self.SOURCE)

    def test_no_token_resolver(self):
        for token in ("[[FACT", "[[ARITH", "[[DEADLINE]]", "[[HEARING]]"):
            self.assertNotIn(token, self.SOURCE, token)

    def test_only_interim_rendered_text_construction(self):
        self.assertIn('rendered_text=""', self.SOURCE)

    def test_no_draft_post_validation_result_production(self):
        self.assertNotIn("DraftPostValidationResult", self.SOURCE)

    def test_no_post_draft_check_ids_emitted(self):
        self.assertNotIn("draft.response", self.SOURCE)
        self.assertNotIn("draft.sections", self.SOURCE)
        self.assertNotIn("draft.tokens", self.SOURCE)
        self.assertNotIn("draft.prose", self.SOURCE)

    def test_no_leakage_regex_implementation(self):
        self.assertNotIn("import re", self.SOURCE)
        for token in ("re.compile", "re.search", "re.match", "regex"):
            self.assertNotIn(token, self.SOURCE, token)

    def test_no_app_integration(self):
        self.assertNotIn("app.py", self.SOURCE)

    def test_no_notice_explainer_integration(self):
        self.assertNotIn("notice_explainer", self.SOURCE)

    def test_no_notice_prompt_modification_or_reference(self):
        self.assertNotIn("notice_prompt", self.SOURCE)
        notice_prompt = (
            pathlib.Path(__file__).resolve().parent.parent
            / "prompts"
            / "notice_prompt.txt"
        )
        self.assertTrue(notice_prompt.exists())


# --- 21. Step-9.3 public API (items 1–9) -----------------------------------------


class PublicApiTests(unittest.TestCase):
    def _signature(self):
        return inspect.signature(engine.generate_specialist_draft)

    def test_signature_exact(self):
        self.assertEqual(
            list(self._signature().parameters),
            [
                "classification",
                "extraction_result",
                "preflight_result",
                "arithmetic_results",
                "validation_result",
                "deadline_result",
            ],
        )

    def test_deadline_result_defaults_to_none(self):
        self.assertIsNone(
            self._signature().parameters["deadline_result"].default
        )

    def test_all_other_parameters_required(self):
        for name, parameter in self._signature().parameters.items():
            if name != "deadline_result":
                self.assertIs(
                    parameter.default, inspect.Parameter.empty, name
                )

    def test_no_raw_text_parameter(self):
        self.assertNotIn("raw_text", self._signature().parameters)

    def test_no_workflow_parameter(self):
        self.assertNotIn("workflow", self._signature().parameters)

    def test_no_prompt_parameter(self):
        self.assertNotIn("prompt", self._signature().parameters)

    def test_no_current_date_parameter(self):
        self.assertNotIn("current_date", self._signature().parameters)

    def test_returns_specialist_draft_result(self):
        result, _ = run_draft()
        self.assertIsInstance(result, SpecialistDraftResult)

    def test_no_overload_single_definition(self):
        self.assertEqual(
            engine_source().count("def generate_specialist_draft"), 1
        )


# --- 22. validation-None defense (items 10–17) ----------------------------------


class ValidationNoneTests(unittest.TestCase):
    VALIDATION_MESSAGE = (
        "Validation result is required before specialist drafting."
    )

    def test_none_validation_blocked_status(self):
        result, _ = run_draft(validation_result=None)
        self.assertIs(result.status, DraftGenerationStatus.BLOCKED)

    def test_none_validation_eligibility_blocked(self):
        result, _ = run_draft(validation_result=None)
        self.assertIs(result.draft_eligibility, DraftEligibility.BLOCKED)

    def test_none_validation_all_lists_empty(self):
        result, _ = run_draft(validation_result=None)
        self.assertEqual(result.sections, [])
        self.assertEqual(result.unresolved_requirements, [])
        self.assertEqual(result.evidence_checklist, [])
        self.assertEqual(result.review_requirements, [])

    def test_none_validation_post_validation_none(self):
        result, _ = run_draft(validation_result=None)
        self.assertIsNone(result.post_validation)

    def test_none_validation_failure_code(self):
        result, _ = run_draft(validation_result=None)
        self.assertIs(
            result.failure_code, DraftFailureCode.VALIDATION_REQUIRED
        )

    def test_none_validation_error_message_exact(self):
        result, _ = run_draft(validation_result=None)
        self.assertEqual(result.error_message, self.VALIDATION_MESSAGE)

    def test_none_validation_zero_llm_calls(self):
        result, mocked = run_draft(validation_result=None)
        self.assertEqual(mocked.call_count, 0)

    def test_none_validation_wins_over_everything_else(self):
        result, mocked = run_draft(
            validation_result=None,
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN,
                support_level=SupportLevel.TRIAGE_ONLY,
            ),
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.VALIDATION_REQUIRED
        )
        self.assertEqual(mocked.call_count, 0)


# --- 23. pre-call failure precedence (items 18–22) ------------------------------


class FailurePrecedenceTests(unittest.TestCase):
    def test_validation_none_beats_blocked_conditions(self):
        result, mocked = run_draft(
            validation_result=None,
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN,
                support_level=SupportLevel.TRIAGE_ONLY,
            ),
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.VALIDATION_REQUIRED
        )
        self.assertEqual(mocked.call_count, 0)

    def test_blocked_beats_missing_workflow(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            with mock.patch.object(
                engine, "get_drafting_profile", return_value=None
            ):
                result, mocked = run_draft(
                    classification=make_classification(
                        support_level=SupportLevel.TRIAGE_ONLY
                    )
                )
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)
        self.assertEqual(mocked.call_count, 0)

    def test_blocked_beats_prompt_refusal(self):
        with mock.patch.object(
            engine, "_build_specialist_prompt"
        ) as builder:
            result, mocked = run_draft(
                classification=make_classification(
                    support_level=SupportLevel.TRIAGE_ONLY
                )
            )
        builder.assert_not_called()
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)
        self.assertEqual(mocked.call_count, 0)

    def test_workflow_unavailable_beats_provider(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, mocked = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(mocked.call_count, 0)

    def test_permitted_inputs_reach_exactly_one_call(self):
        result, mocked = run_draft()
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)


# --- 24. DRAFT_BLOCKED behavior (items 23–31) -----------------------------------


class DraftBlockedTests(unittest.TestCase):
    BLOCKED_MESSAGE = (
        "Specialist drafting is blocked by validation or "
        "classification state."
    )

    def test_triage_only_support_blocked(self):
        result, mocked = run_draft(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertIs(result.status, DraftGenerationStatus.BLOCKED)
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)
        self.assertEqual(result.error_message, self.BLOCKED_MESSAGE)
        self.assertEqual(mocked.call_count, 0)

    def test_unknown_support_blocked(self):
        result, _ = run_draft(
            classification=make_classification(
                support_level=SupportLevel.UNKNOWN
            )
        )
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)

    def test_unknown_proceeding_blocked(self):
        result, _ = run_draft(
            classification=make_classification(
                proceeding_type=ProceedingType.UNKNOWN
            )
        )
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)

    def test_blocked_eligibility_blocked(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.BLOCKED
            )
        )
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)

    def test_fail_check_blocked(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                checks=[make_item("generic.fail", ValidationStatus.FAIL)]
            )
        )
        self.assertIs(result.failure_code, DraftFailureCode.DRAFT_BLOCKED)

    def test_review_required_no_fail_reaches_call(self):
        result, mocked = run_draft(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.REVIEW_REQUIRED
            )
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertEqual(mocked.call_count, 1)

    def test_allowed_eligibility_reaches_call(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.ALLOWED
            )
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_warning_check_does_not_block(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                checks=[
                    make_item("generic.warn", ValidationStatus.WARNING)
                ]
            )
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_blocked_result_carries_validation_metadata(self):
        validation = make_rich_validation()
        result, _ = run_draft(
            validation_result=validation,
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            ),
        )
        self.assertIs(
            result.draft_eligibility, validation.draft_eligibility
        )
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )
        self.assertEqual(
            result.review_requirements, validation.review_requirements
        )


# --- 25. WORKFLOW_UNAVAILABLE behavior (items 32–43) ----------------------------


class WorkflowUnavailableTests(unittest.TestCase):
    UNAVAILABLE_MESSAGE = (
        "Specialist drafting workflow or prompt assets are unavailable."
    )

    def test_missing_workflow(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, mocked = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.BLOCKED)
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(result.error_message, self.UNAVAILABLE_MESSAGE)
        self.assertEqual(mocked.call_count, 0)

    def test_missing_drafting_profile(self):
        with mock.patch.object(
            engine, "get_drafting_profile", return_value=None
        ):
            result, mocked = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(mocked.call_count, 0)

    def test_workflow_proceeding_type_mismatch(self):
        foreign = GST_WORKFLOW_REGISTRY[ProceedingType.GST_SEC74_FRAUD]
        with mock.patch.object(
            engine, "get_workflow", return_value=foreign
        ):
            result, _ = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )

    def test_profile_proceeding_type_mismatch(self):
        foreign = get_drafting_profile(ProceedingType.GST_SEC73_GENERAL)
        with mock.patch.object(
            engine, "get_drafting_profile", return_value=foreign
        ):
            result, _ = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )

    def test_prompt_builder_refusal_maps_to_workflow_unavailable(self):
        with mock.patch.object(
            engine, "_build_specialist_prompt", return_value=None
        ):
            result, mocked = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(mocked.call_count, 0)

    def test_missing_prompt_asset(self):
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False
        ) as handle:
            empty_path = handle.name
        try:
            with mock.patch.object(
                engine, "_BASE_PROMPT_PATH", pathlib.Path(empty_path)
            ):
                result, mocked = run_draft()
        finally:
            pathlib.Path(empty_path).unlink(missing_ok=True)
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(mocked.call_count, 0)

    def test_unknown_prompt_key(self):
        real = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        unknown_key_profile = WorkflowDraftingProfile(
            proceeding_type=real.proceeding_type,
            sections=real.sections,
            prompt_key="sec999_unknown",
        )
        with mock.patch.object(
            engine,
            "get_drafting_profile",
            return_value=unknown_key_profile,
        ):
            result, mocked = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )
        self.assertEqual(mocked.call_count, 0)

    def test_workflow_unavailable_message_exact(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, _ = run_draft()
        self.assertEqual(result.error_message, self.UNAVAILABLE_MESSAGE)

    def test_workflow_unavailable_failure_code_exact(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, _ = run_draft()
        self.assertIs(
            result.failure_code, DraftFailureCode.WORKFLOW_UNAVAILABLE
        )

    def test_workflow_unavailable_zero_llm_calls(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            _, mocked = run_draft()
        self.assertEqual(mocked.call_count, 0)

    def test_workflow_unavailable_status_blocked(self):
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, _ = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.BLOCKED)

    def test_workflow_unavailable_metadata_copied(self):
        validation = make_rich_validation()
        with mock.patch.object(engine, "get_workflow", return_value=None):
            result, _ = run_draft(validation_result=validation)
        self.assertIs(
            result.draft_eligibility, validation.draft_eligibility
        )
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )


# --- 26. metadata copying (items 44–58) -----------------------------------------


class MetadataCopyTests(unittest.TestCase):
    UNRESOLVED = (
        RequirementStatus.MISSING,
        RequirementStatus.UNKNOWN,
        RequirementStatus.REQUIRES_VERIFICATION,
    )

    def _run_rich(self, **overrides):
        validation = make_rich_validation()
        result, _ = run_draft(validation_result=validation, **overrides)
        return validation, result

    def test_success_unresolved_is_exactly_missing_unknown_verify(self):
        validation, result = self._run_rich()
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )
        self.assertEqual(
            result.unresolved_requirements,
            [
                r
                for r in validation.requirements
                if r.status in self.UNRESOLVED
            ],
        )

    def test_success_unresolved_source_order_preserved(self):
        _, result = self._run_rich()
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )

    def test_success_evidence_copied_equal(self):
        validation, result = self._run_rich()
        self.assertEqual(
            [e.evidence_id for e in result.evidence_checklist],
            ["ev.e1", "ev.e2"],
        )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )

    def test_success_reviews_copied_equal(self):
        validation, result = self._run_rich()
        self.assertEqual(
            result.review_requirements, validation.review_requirements
        )

    def test_success_metadata_lists_are_fresh(self):
        validation, result = self._run_rich()
        self.assertIsNot(
            result.unresolved_requirements, validation.requirements
        )
        self.assertIsNot(
            result.evidence_checklist, validation.evidence_checklist
        )
        self.assertIsNot(
            result.review_requirements, validation.review_requirements
        )

    def test_success_contained_objects_may_be_shared(self):
        validation, result = self._run_rich()
        self.assertIs(
            result.evidence_checklist[0],
            validation.evidence_checklist[0],
        )

    def test_blocked_result_copies_metadata(self):
        validation, result = self._run_rich(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )

    def test_failed_result_copies_metadata(self):
        validation = make_rich_validation()
        with mock.patch.object(
            engine, "call_gemini", side_effect=RuntimeError("boom")
        ):
            result = engine.generate_specialist_draft(
                **make_permitted_inputs(validation_result=validation)
            )
        self.assertEqual(
            [r.requirement_id for r in result.unresolved_requirements],
            ["req.m", "req.u", "req.v"],
        )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )

    def test_satisfied_requirement_excluded(self):
        _, result = self._run_rich()
        ids = [r.requirement_id for r in result.unresolved_requirements]
        self.assertNotIn("req.s", ids)

    def test_derived_requirement_excluded(self):
        _, result = self._run_rich()
        ids = [r.requirement_id for r in result.unresolved_requirements]
        self.assertNotIn("req.d", ids)

    def test_unresolved_list_is_not_the_requirements_list(self):
        validation, result = self._run_rich()
        self.assertIsNot(
            result.unresolved_requirements, validation.requirements
        )

    def test_success_sections_list_is_fresh_between_calls(self):
        first, _ = run_draft(validation_result=make_rich_validation())
        second, _ = run_draft(validation_result=make_rich_validation())
        self.assertIsNot(first.sections, second.sections)

    def test_copied_lists_preserve_validation_order(self):
        evidence = [
            make_evidence(evidence_id="ev.z1"),
            make_evidence(evidence_id="ev.a2"),
        ]
        validation = make_validation_result(
            evidence_checklist=evidence,
            requirements=[make_requirement(requirement_id="req.z")],
        )
        result, _ = run_draft(validation_result=validation)
        self.assertEqual(
            [e.evidence_id for e in result.evidence_checklist],
            ["ev.z1", "ev.a2"],
        )

    def test_draft_eligibility_copied_from_validation(self):
        review_validation, review_result = self._run_rich()
        self.assertIs(
            review_result.draft_eligibility,
            review_validation.draft_eligibility,
        )
        allowed_validation = make_rich_validation(
            draft_eligibility=DraftEligibility.ALLOWED
        )
        allowed_result, _ = run_draft(
            validation_result=allowed_validation
        )
        self.assertIs(
            allowed_result.draft_eligibility,
            allowed_validation.draft_eligibility,
        )

    def test_validation_none_result_lists_are_literal_empty(self):
        result, _ = run_draft(validation_result=None)
        self.assertEqual(result.sections, [])
        self.assertEqual(result.unresolved_requirements, [])
        self.assertEqual(result.evidence_checklist, [])
        self.assertEqual(result.review_requirements, [])


# --- 27. exactly-one-call behavior (items 59–64) --------------------------------


class OneCallTests(unittest.TestCase):
    def test_success_path_makes_exactly_one_call(self):
        result, mocked = run_draft()
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_call_receives_exact_build_prompt_output(self):
        inputs = make_permitted_inputs()
        expected_prompt = engine._build_specialist_prompt(**inputs)
        with mock.patch.object(
            engine, "call_gemini", return_value=make_response_json()
        ) as mocked:
            engine.generate_specialist_draft(**inputs)
        self.assertEqual(mocked.call_count, 1)
        self.assertIsInstance(mocked.call_args.args[0], str)
        self.assertEqual(mocked.call_args.args[0], expected_prompt)

    def test_call_receives_a_string(self):
        _, mocked = run_draft()
        self.assertIsInstance(mocked.call_args.args[0], str)

    def test_no_call_on_draft_blocked(self):
        _, mocked = run_draft(
            classification=make_classification(
                support_level=SupportLevel.TRIAGE_ONLY
            )
        )
        self.assertEqual(mocked.call_count, 0)

    def test_no_call_on_validation_none(self):
        _, mocked = run_draft(validation_result=None)
        self.assertEqual(mocked.call_count, 0)

    def test_single_response_parsed_once(self):
        result, mocked = run_draft()
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(len(result.sections), 3)


# --- 28. provider failure handling (items 65–79) --------------------------------


class ProviderFailureTests(unittest.TestCase):
    LLM_MESSAGE = "Specialist drafting provider call failed."

    def _run_exception(self, exception):
        with mock.patch.object(
            engine, "call_gemini", side_effect=exception
        ) as mocked:
            result = engine.generate_specialist_draft(
                **make_permitted_inputs()
            )
        return result, mocked

    def test_provider_exception_llm_error(self):
        result, _ = self._run_exception(RuntimeError("boom"))
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)
        self.assertEqual(result.error_message, self.LLM_MESSAGE)

    def test_provider_exception_no_retry(self):
        _, mocked = self._run_exception(RuntimeError("boom"))
        self.assertEqual(mocked.call_count, 1)

    def test_provider_exception_text_not_leaked(self):
        result, _ = self._run_exception(RuntimeError("boom-secret"))
        self.assertEqual(result.error_message, self.LLM_MESSAGE)
        self.assertNotIn("boom-secret", result.error_message)

    def test_provider_exception_metadata_copied(self):
        validation = make_rich_validation()
        with mock.patch.object(
            engine, "call_gemini", side_effect=RuntimeError("boom")
        ):
            result = engine.generate_specialist_draft(
                **make_permitted_inputs(validation_result=validation)
            )
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )

    def test_provider_exception_sections_empty(self):
        result, _ = self._run_exception(RuntimeError("boom"))
        self.assertEqual(result.sections, [])

    def test_provider_exception_post_validation_none(self):
        result, _ = self._run_exception(RuntimeError("boom"))
        self.assertIsNone(result.post_validation)

    def test_error_prefix_string_llm_error(self):
        result, _ = run_draft(response="Error: provider exploded")
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)
        self.assertEqual(result.error_message, self.LLM_MESSAGE)

    def test_error_prefix_after_strip_llm_error(self):
        result, _ = run_draft(
            response="  \n Error: provider exploded \n"
        )
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)

    def test_lowercase_error_prefix_not_matched(self):
        # Case-sensitive: lowercase "error:" is NOT the provider-error
        # prefix, so the response proceeds to the strict JSON parser.
        result, _ = run_draft(response="error: provider exploded")
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_non_string_response_llm_error(self):
        result, _ = run_draft(response={"sections": []})
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)
        self.assertEqual(result.error_message, self.LLM_MESSAGE)

    def test_non_string_response_never_stringified(self):
        result, _ = run_draft(response=12345)
        self.assertEqual(result.error_message, self.LLM_MESSAGE)
        self.assertNotIn("12345", result.error_message)

    def test_non_string_response_skips_parser(self):
        with mock.patch("json.loads") as loads:
            result, _ = run_draft(response={"sections": []})
        loads.assert_not_called()
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)

    def test_int_response_llm_error(self):
        result, _ = run_draft(response=7)
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)

    def test_list_response_llm_error(self):
        result, _ = run_draft(response=["sections"])
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)

    def test_none_response_llm_error(self):
        with mock.patch.object(
            engine, "call_gemini", return_value=None
        ):
            result = engine.generate_specialist_draft(
                **make_permitted_inputs()
            )
        self.assertIs(result.failure_code, DraftFailureCode.LLM_ERROR)


# --- 29. empty / invalid JSON responses (items 80–88) ---------------------------


class EmptyInvalidJsonTests(unittest.TestCase):
    MALFORMED_MESSAGE = (
        "Specialist drafting response did not match the required schema."
    )

    def test_whitespace_only_malformed(self):
        result, _ = run_draft(response="   \n\t  ")
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )
        self.assertEqual(result.error_message, self.MALFORMED_MESSAGE)

    def test_empty_string_malformed(self):
        result, _ = run_draft(response="")
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_whitespace_malformed_sections_empty(self):
        result, _ = run_draft(response="   ")
        self.assertEqual(result.sections, [])

    def test_prose_rejected(self):
        result, _ = run_draft(response="not json at all")
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_markdown_fenced_json_rejected(self):
        result, _ = run_draft(
            response="```json\n" + make_response_json() + "\n```"
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_prose_wrapped_json_rejected(self):
        result, _ = run_draft(
            response="Here is your draft: " + make_response_json()
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_python_dict_repr_rejected(self):
        result, _ = run_draft(
            response="{'sections': [{'section_id': 'x', "
            "'body_template': 'y'}]}"
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_truncated_json_rejected(self):
        result, _ = run_draft(response='{"sections": [')
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_malformed_message_exact(self):
        result, _ = run_draft(response="{bad json")
        self.assertEqual(result.error_message, self.MALFORMED_MESSAGE)


# --- 30. root schema (items 89–95) ----------------------------------------------


class RootSchemaTests(unittest.TestCase):
    def _malformed(self, response):
        result, _ = run_draft(response=response)
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )
        return result

    def test_root_must_be_dict(self):
        self._malformed('"just a string"')

    def test_root_list_rejected(self):
        self._malformed("[]")

    def test_root_number_rejected(self):
        self._malformed("42")

    def test_exactly_one_root_key(self):
        self._malformed('{"sections": [], "meta": {}}')

    def test_missing_sections_key(self):
        self._malformed("{}")

    def test_extra_root_key_rejected(self):
        self._malformed('{"notes": 1, "sections": []}')

    def test_sections_must_be_list(self):
        self._malformed('{"sections": {}}')

    def test_sections_string_rejected(self):
        self._malformed('{"sections": "x"}')


# --- 31. section schema (items 96–101) ------------------------------------------


class SectionSchemaTests(unittest.TestCase):
    def _section_json(self, section):
        return make_response_json(
            sections=[
                {
                    "section_id": "sec73_itc.s1",
                    "body_template": "One.",
                },
                {
                    "section_id": "sec73_itc.s2",
                    "body_template": "Two.",
                },
                section,
            ]
        )

    def test_section_must_be_dict(self):
        result, _ = run_draft(
            response=self._section_json(["not", "a", "dict"])
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_exactly_two_section_keys(self):
        result, _ = run_draft(
            response=self._section_json(
                {
                    "section_id": "sec73_itc.s3",
                    "body_template": "Three.",
                    "extra": True,
                }
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_missing_section_id_key(self):
        result, _ = run_draft(
            response=self._section_json({"body_template": "Three."})
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_missing_body_template_key(self):
        result, _ = run_draft(
            response=self._section_json(
                {"section_id": "sec73_itc.s3"}
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_non_string_section_id(self):
        result, _ = run_draft(
            response=self._section_json(
                {"section_id": 3, "body_template": "Three."}
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_non_string_body_template(self):
        result, _ = run_draft(
            response=self._section_json(
                {"section_id": "sec73_itc.s3", "body_template": ["text"]}
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )


# --- 32. section count / ID / order (items 102–109) -----------------------------


class CountIdOrderTests(unittest.TestCase):
    def test_too_few_sections_malformed(self):
        result, _ = run_draft(
            response=make_response_json(
                sections=[
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "One.",
                    },
                    {
                        "section_id": "sec73_itc.s2",
                        "body_template": "Two.",
                    },
                ]
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_too_many_sections_malformed(self):
        sections = [
            {"section_id": sid, "body_template": "Text."}
            for sid in ITC_SECTION_IDS
        ]
        sections.append(
            {"section_id": "sec73_itc.s4", "body_template": "Extra."}
        )
        result, _ = run_draft(
            response=make_response_json(sections=sections)
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_wrong_section_id_malformed(self):
        result, _ = run_draft(
            response=make_response_json(
                sections=[
                    {
                        "section_id": "sec73_itc.s2",
                        "body_template": "A.",
                    },
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "B.",
                    },
                    {
                        "section_id": "sec73_itc.s3",
                        "body_template": "C.",
                    },
                ]
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_case_mismatch_malformed(self):
        result, _ = run_draft(
            response=make_response_json(
                sections=[
                    {
                        "section_id": "SEC73_ITC.S1",
                        "body_template": "A.",
                    },
                    {
                        "section_id": "sec73_itc.s2",
                        "body_template": "B.",
                    },
                    {
                        "section_id": "sec73_itc.s3",
                        "body_template": "C.",
                    },
                ]
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_reordered_sections_rejected(self):
        result, _ = run_draft(
            response=make_response_json(
                sections=[
                    {
                        "section_id": "sec73_itc.s2",
                        "body_template": "B.",
                    },
                    {
                        "section_id": "sec73_itc.s3",
                        "body_template": "C.",
                    },
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "A.",
                    },
                ]
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_duplicate_section_ids_rejected(self):
        result, _ = run_draft(
            response=make_response_json(
                sections=[
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "A.",
                    },
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "B.",
                    },
                    {
                        "section_id": "sec73_itc.s3",
                        "body_template": "C.",
                    },
                ]
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_profile_order_success(self):
        result, _ = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertEqual(
            [s.section_id for s in result.sections], ITC_SECTION_IDS
        )

    def test_section_id_comes_from_profile(self):
        result, _ = run_draft()
        profile = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(
            [s.section_id for s in result.sections],
            [spec.section_id for spec in profile.sections],
        )


# --- 33. body normalization (items 110–115) -------------------------------------


class BodyNormalizationTests(unittest.TestCase):
    def _bodies(self, bodies):
        return make_response_json(
            sections=[
                {"section_id": sid, "body_template": body}
                for sid, body in zip(ITC_SECTION_IDS, bodies)
            ]
        )

    def test_leading_trailing_whitespace_stripped(self):
        result, _ = run_draft(
            response=self._bodies(["  One.  ", "  Two.  ", "  Three.  "])
        )
        self.assertEqual(
            [s.template_text for s in result.sections],
            ["One.", "Two.", "Three."],
        )

    def test_internal_whitespace_preserved(self):
        result, _ = run_draft(
            response=self._bodies(
                ["Line  one.", "Line\ttwo.", "Line  three."]
            )
        )
        self.assertEqual(
            [s.template_text for s in result.sections],
            ["Line  one.", "Line\ttwo.", "Line  three."],
        )

    def test_newlines_inside_preserved(self):
        result, _ = run_draft(
            response=self._bodies(
                ["One\nline.", "Two\nlines.", "Three\nlines."]
            )
        )
        self.assertEqual(
            result.sections[0].template_text, "One\nline."
        )

    def test_whitespace_only_body_malformed(self):
        result, _ = run_draft(
            response=self._bodies(["One.", "   ", "Three."])
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_empty_body_malformed(self):
        result, _ = run_draft(
            response=self._bodies(["One.", "", "Three."])
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )

    def test_strip_applied_once_no_normalization_inside(self):
        result, _ = run_draft(
            response=self._bodies(["\t\n One \t\n", "Two.", "Three."])
        )
        self.assertEqual(result.sections[0].template_text, "One")


# --- 34. parse-success result (items 116–128) -----------------------------------


class SuccessResultTests(unittest.TestCase):
    ITC_TITLES = [
        "Working paper",
        "ITC reconciliation table",
        "Reviewable DRC-06 draft",
    ]

    def test_success_status(self):
        result, _ = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_success_failure_code_none(self):
        result, _ = run_draft()
        self.assertIsNone(result.failure_code)

    def test_success_error_message_none(self):
        result, _ = run_draft()
        self.assertIsNone(result.error_message)

    def test_success_eligibility_review_required_copied(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.REVIEW_REQUIRED
            )
        )
        self.assertIs(
            result.draft_eligibility, DraftEligibility.REVIEW_REQUIRED
        )

    def test_success_eligibility_allowed_copied(self):
        result, _ = run_draft(
            validation_result=make_validation_result(
                draft_eligibility=DraftEligibility.ALLOWED
            )
        )
        self.assertIs(result.draft_eligibility, DraftEligibility.ALLOWED)

    def test_success_section_count_matches_profile(self):
        result, _ = run_draft()
        self.assertEqual(len(result.sections), len(ITC_SECTION_IDS))

    def test_success_section_ids_from_profile(self):
        result, _ = run_draft()
        self.assertEqual(
            [s.section_id for s in result.sections], ITC_SECTION_IDS
        )

    def test_success_titles_from_profile(self):
        result, _ = run_draft()
        self.assertEqual(
            [s.title for s in result.sections], self.ITC_TITLES
        )

    def test_success_template_text_normalized(self):
        result, _ = run_draft()
        self.assertEqual(
            [s.template_text for s in result.sections],
            DEFAULT_RESPONSE_BODIES,
        )

    def test_success_rendered_text_empty(self):
        result, _ = run_draft()
        for section in result.sections:
            self.assertEqual(section.rendered_text, "")

    def test_success_post_validation_none(self):
        result, _ = run_draft()
        self.assertIsNone(result.post_validation)

    def test_success_metadata_copied(self):
        validation = make_rich_validation()
        result, _ = run_draft(validation_result=validation)
        self.assertEqual(
            result.evidence_checklist, validation.evidence_checklist
        )
        self.assertEqual(
            result.review_requirements, validation.review_requirements
        )

    def test_success_sections_list_is_fresh(self):
        first, _ = run_draft()
        second, _ = run_draft()
        self.assertIsNot(first.sections, second.sections)

    def test_result_has_exactly_nine_fields(self):
        self.assertEqual(
            list(SpecialistDraftResult.__dataclass_fields__.keys()),
            [
                "status",
                "draft_eligibility",
                "sections",
                "unresolved_requirements",
                "evidence_checklist",
                "review_requirements",
                "post_validation",
                "failure_code",
                "error_message",
            ],
        )


# --- 35. no partial success (items 129–131) -------------------------------------


class NoPartialSuccessTests(unittest.TestCase):
    def _one_bad_section(self, bad_section):
        return make_response_json(
            sections=[
                {
                    "section_id": "sec73_itc.s1",
                    "body_template": "One.",
                },
                {
                    "section_id": "sec73_itc.s2",
                    "body_template": "Two.",
                },
                bad_section,
            ]
        )

    def test_one_bad_section_fails_whole_result(self):
        result, _ = run_draft(
            response=self._one_bad_section(
                {"section_id": "wrong.id", "body_template": "Three."}
            )
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )
        self.assertIs(result.status, DraftGenerationStatus.FAILED)

    def test_one_bad_section_yields_no_sections(self):
        result, _ = run_draft(
            response=self._one_bad_section(
                {"section_id": "wrong.id", "body_template": "Three."}
            )
        )
        self.assertEqual(result.sections, [])

    def test_non_dict_last_section_fails_whole_result(self):
        result, _ = run_draft(
            response=self._one_bad_section(["not", "a", "dict"])
        )
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )
        self.assertEqual(result.sections, [])


# --- 36. Step-9.3 vs Step-9.4 boundary (items 132–140) --------------------------


class StepBoundaryTests(unittest.TestCase):
    def _run_unsafe_bodies(self, bodies):
        return run_draft(
            response=make_response_json(
                sections=[
                    {"section_id": sid, "body_template": body}
                    for sid, body in zip(ITC_SECTION_IDS, bodies)
                ]
            )
        )

    def test_unknown_token_still_success(self):
        result, _ = self._run_unsafe_bodies(
            ["Has [[BAD:TOKEN]].", "Two.", "Three."]
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_unresolved_fact_token_still_success(self):
        result, _ = self._run_unsafe_bodies(
            ["Refers [[FACT:F-999]].", "Two.", "Three."]
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_invalid_arithmetic_index_still_success(self):
        result, _ = self._run_unsafe_bodies(
            ["Uses [[ARITH:999]].", "Two.", "Three."]
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_attached_word_still_success(self):
        result, _ = self._run_unsafe_bodies(
            ["Please find the annexure attached.", "Two.", "Three."]
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_urls_and_citations_still_success(self):
        result, _ = self._run_unsafe_bodies(
            [
                "See https://example.com/page and (2025) 1 SCC 100.",
                "Two.",
                "Three.",
            ]
        )
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)

    def test_rendered_text_never_populated(self):
        result, _ = self._run_unsafe_bodies(
            ["[[BAD:TOKEN]]", "Two.", "Three."]
        )
        for section in result.sections:
            self.assertEqual(section.rendered_text, "")

    def test_post_validation_never_populated(self):
        result, _ = run_draft()
        self.assertIsNone(result.post_validation)

    def test_no_draft_post_validation_result_in_engine(self):
        self.assertNotIn("DraftPostValidationResult", engine_source())

    def test_no_step_9_4_check_ids_in_engine(self):
        source = engine_source()
        for token in (
            "draft.response",
            "draft.sections",
            "draft.tokens",
            "draft.prose",
        ):
            self.assertNotIn(token, source, token)


# --- 37. status / failure-code consistency (items 141–144) ----------------------


class StatusConsistencyTests(unittest.TestCase):
    def test_success_implies_no_failure_code_or_error(self):
        result, _ = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertIsNone(result.failure_code)
        self.assertIsNone(result.error_message)

    def test_blocked_implies_blocked_failure_codes_only(self):
        blocked_codes = {
            DraftFailureCode.VALIDATION_REQUIRED,
            DraftFailureCode.DRAFT_BLOCKED,
            DraftFailureCode.WORKFLOW_UNAVAILABLE,
        }
        scenarios = [
            run_draft(validation_result=None),
            run_draft(
                classification=make_classification(
                    support_level=SupportLevel.TRIAGE_ONLY
                )
            ),
            run_draft(
                validation_result=make_validation_result(
                    checks=[
                        make_item(
                            "generic.fail", ValidationStatus.FAIL
                        )
                    ]
                )
            ),
        ]
        with mock.patch.object(engine, "get_workflow", return_value=None):
            scenarios.append(run_draft())
        for result, _ in scenarios:
            self.assertIs(result.status, DraftGenerationStatus.BLOCKED)
            self.assertIn(result.failure_code, blocked_codes)

    def test_failed_implies_failed_failure_codes_only(self):
        failed_codes = {
            DraftFailureCode.LLM_ERROR,
            DraftFailureCode.MALFORMED_RESPONSE,
        }
        for response in (
            "Error: provider exploded",
            "   ",
            "{bad json",
            make_response_json(
                sections=[
                    {
                        "section_id": "sec73_itc.s1",
                        "body_template": "A.",
                    },
                    {
                        "section_id": "sec73_itc.s2",
                        "body_template": "B.",
                    },
                    {"section_id": "wrong", "body_template": "C."},
                ]
            ),
            {"sections": []},
        ):
            result, _ = run_draft(response=response)
            self.assertIs(result.status, DraftGenerationStatus.FAILED)
            self.assertIn(result.failure_code, failed_codes)

    def test_post_validation_failed_never_produced(self):
        self.assertNotIn("POST_VALIDATION_FAILED", engine_source())
        scenarios = [
            run_draft(),
            run_draft(validation_result=None),
            run_draft(
                classification=make_classification(
                    support_level=SupportLevel.TRIAGE_ONLY
                )
            ),
            run_draft(response="Error: boom"),
            run_draft(response="{bad json"),
        ]
        with mock.patch.object(engine, "get_workflow", return_value=None):
            scenarios.append(run_draft())
        for result, _ in scenarios:
            self.assertIsNot(
                result.failure_code,
                DraftFailureCode.POST_VALIDATION_FAILED,
            )


# --- 38. purity / scope (items 145–160) -----------------------------------------


class PurityScopeTests(unittest.TestCase):
    def test_no_provider_sdk_imports(self):
        source = engine_source().lower()
        for token in (
            "genai",
            "vertexai",
            "generativelanguage",
            "google",
        ):
            self.assertNotIn(token, source, token)

    def test_no_network_imports(self):
        source = engine_source().lower()
        for token in ("requests", "urllib", "socket", "http"):
            self.assertNotIn(token, source, token)

    def test_no_app_integration(self):
        self.assertNotIn("app.py", engine_source())

    def test_no_notice_explainer_integration(self):
        self.assertNotIn("notice_explainer", engine_source())

    def test_no_notice_prompt_reference(self):
        self.assertNotIn("notice_prompt", engine_source())

    def test_no_regex_implementation(self):
        source = engine_source()
        self.assertNotIn("import re", source)
        for token in ("re.compile", "re.search", "re.match", "regex"):
            self.assertNotIn(token, source, token)

    def test_no_leakage_scanners(self):
        self.assertNotIn("leakage", engine_source().lower())

    def test_all_inputs_never_mutated(self):
        inputs = {
            "classification": make_classification(),
            "extraction_result": make_extraction(
                facts=[make_fact(fact_id="F-001")]
            ),
            "preflight_result": make_preflight(),
            "arithmetic_results": [
                make_arithmetic(source_fact_ids=["F-001"])
            ],
            "validation_result": make_rich_validation(),
            "deadline_result": make_deadline(),
        }
        snapshots = {
            key: copy.deepcopy(value) for key, value in inputs.items()
        }
        run_draft(**inputs)
        for key, value in inputs.items():
            self.assertEqual(value, snapshots[key], key)

    def test_classification_never_mutated(self):
        classification = make_classification()
        snapshot = copy.deepcopy(classification)
        run_draft(classification=classification)
        self.assertEqual(classification, snapshot)

    def test_extraction_never_mutated(self):
        extraction = make_extraction(facts=[make_fact(fact_id="F-001")])
        snapshot = copy.deepcopy(extraction)
        run_draft(extraction_result=extraction)
        self.assertEqual(extraction, snapshot)

    def test_preflight_never_mutated(self):
        preflight = make_preflight()
        snapshot = copy.deepcopy(preflight)
        run_draft(preflight_result=preflight)
        self.assertEqual(preflight, snapshot)

    def test_arithmetic_results_never_mutated(self):
        arithmetic = [make_arithmetic(source_fact_ids=["F-001"])]
        snapshot = copy.deepcopy(arithmetic)
        run_draft(arithmetic_results=arithmetic)
        self.assertEqual(arithmetic, snapshot)

    def test_validation_result_never_mutated(self):
        validation = make_rich_validation()
        snapshot = copy.deepcopy(validation)
        run_draft(validation_result=validation)
        self.assertEqual(validation, snapshot)

    def test_deadline_result_never_mutated(self):
        deadline = make_deadline(notes=("note a", "note b"))
        snapshot = copy.deepcopy(deadline)
        run_draft(deadline_result=deadline)
        self.assertEqual(deadline, snapshot)

    def test_result_lists_never_alias_validation(self):
        validation = make_rich_validation()
        result, _ = run_draft(validation_result=validation)
        self.assertIsNot(
            result.unresolved_requirements, validation.requirements
        )
        self.assertIsNot(
            result.evidence_checklist, validation.evidence_checklist
        )
        self.assertIsNot(
            result.review_requirements, validation.review_requirements
        )

    def test_no_step_9_4_symbols_in_engine(self):
        source = engine_source()
        for token in (
            "resolve_token",
            "token_resolver",
            "DraftPostValidationResult",
        ):
            self.assertNotIn(token, source, token)


if __name__ == "__main__":
    unittest.main()
