"""Offline unit tests for controlled and provenance-complete drafting.

The drafting LLM boundary is always
mocked via engine.call_gemini: no live LLM calls, no network, no
fixtures.

Coverage includes the retained deterministic §21 context contracts, the
public gate/result-state behavior, the active §25 provenance-v1 prompt and
strict parser, all 21 post-validation checks, the eight closed Python
renderers, legacy-prose rejection, and the mandatory P0 regressions.

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
    ArithmeticDraftBlock,
    ArithmeticResult,
    ArithmeticStatus,
    AuthorityDetailsStatus,
    ClassificationConfidence,
    CommunicationIdentifierStatus,
    DeadlineConfidence,
    DeadlineConflictStatus,
    DeadlineResult,
    DeadlineStatus,
    DeadlineDraftBlock,
    DraftBlockKind,
    DraftCandidateSection,
    DraftEligibility,
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftSection,
    EvidenceDraftBlock,
    EvidenceChecklistItem,
    EvidenceStatus,
    FactExtractionResult,
    FactDraftBlock,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    HearingDraftBlock,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    PreflightResult,
    ProceedingType,
    RequirementResult,
    RequirementDraftBlock,
    RequirementStatus,
    ReviewLevel,
    ReviewDraftBlock,
    ReviewRequirement,
    SpecialistDraftResult,
    StaticDraftBlock,
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
    ProceedingType.GST_SEC61_SCRUTINY,
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
    "Working paper body without reference tokens.",
    "Reconciliation table body without reference tokens.",
    "Reviewable draft body without reference tokens.",
]


def make_response_json(sections=None):
    """Deterministic schema-valid §20.23 response for the ITC profile."""
    if sections is None:
        sections = [
            {"section_id": sid, "body_template": body}
            for sid, body in zip(ITC_SECTION_IDS, DEFAULT_RESPONSE_BODIES)
        ]
    return json.dumps({"sections": sections})


def make_provenance_response_json(sections=None):
    """Schema-valid §25 typed response for the ITC profile."""
    if sections is None:
        sections = [
            {
                "section_id": sid,
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.working_draft",
                    }
                ],
            }
            for sid in ITC_SECTION_IDS
        ]
    return json.dumps({"sections": sections})


def run_draft(response=None, **overrides):
    """Call generate_specialist_draft with engine.call_gemini patched to
    return `response`. Returns (result, mocked_call)."""
    if response is None:
        response = make_provenance_response_json()
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


def check_by_id(result, check_id):
    for item in result.checks:
        if item.check_id == check_id:
            return item
    raise KeyError(check_id)


# --- 1. module surface (items 1–10) -------------------------------------------


class ModuleSurfaceTests(unittest.TestCase):
    """One public callable (generate_specialist_draft); the approved LLM
    boundary only; no provider SDK/network/engine imports."""

    SOURCE = pathlib.Path(engine.__file__).read_text(encoding="utf-8")

    ALLOWED_IMPORT_ROOTS = (
        "json", "pathlib", "re", "types", "typing", "domain", "modules",
        "workflows",
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
        for token in ("requests", "urllib", "socket", "streamlit"):
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
        "gst/sec61_scrutiny.txt",
        "gst/sec73_itc.txt",
        "gst/sec73_general.txt",
        "gst/sec73_rcm.txt",
        "gst/sec74_fraud.txt",
        "gst/sec129.txt",
    }

    def test_exactly_seven_active_prompt_files_exist(self):
        found = {
            path.relative_to(engine._PROMPTS_DIR).as_posix()
            for path in engine._PROMPTS_DIR.rglob("*.txt")
            if "provenance_v1" not in path.parts
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
                "sec61_scrutiny",
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
        r"\b(?:sec61_scrutiny|sec73_itc|sec73_general|sec73_rcm|sec74_fraud|sec129)"
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

    def test_sec61_keeps_discrepancy_as_allegation(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC61_SCRUTINY
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Every ASMT-10 discrepancy remains a departmental allegation",
            normalized,
        )

    def test_sec61_does_not_inject_generic_reply_period(self):
        _, prompt = self._workflow_prompt(
            ProceedingType.GST_SEC61_SCRUTINY
        )
        normalized = " ".join(prompt.split())
        self.assertIn(
            "Do not inject a generic statutory reply period",
            normalized,
        )

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

    def test_closed_typed_dispatcher_present(self):
        source = inspect.getsource(engine._render_provenance_block)
        for block_type in (
            "StaticDraftBlock",
            "FactDraftBlock",
            "ArithmeticDraftBlock",
            "DeadlineDraftBlock",
            "HearingDraftBlock",
            "RequirementDraftBlock",
            "EvidenceDraftBlock",
            "ReviewDraftBlock",
        ):
            self.assertIn(block_type, source, block_type)

    def test_final_rendered_text_construction_present(self):
        source = inspect.getsource(
            engine._post_validate_and_render_provenance
        )
        self.assertIn("rendered_text=rendered_text", source)
        self.assertNotIn("template_text", source)

    def test_draft_post_validation_result_present(self):
        self.assertIn("DraftPostValidationResult", self.SOURCE)

    def test_provenance_check_catalog_emitted(self):
        self.assertEqual(len(engine._PROVENANCE_CHECK_IDS), 21)
        self.assertEqual(
            engine._PROVENANCE_CHECK_IDS[-2:],
            (
                "draft.rendering.completeness",
                "draft.rendering.python_owned",
            ),
        )

    def test_no_lexical_primary_gate(self):
        source = inspect.getsource(
            engine._run_provenance_pre_render_validation
        )
        self.assertNotIn("re.", source)
        self.assertNotIn(".lower(", source)

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
            engine, "_build_provenance_prompt"
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
            engine, "_build_provenance_prompt", return_value=None
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
                engine,
                "_PROVENANCE_BASE_PROMPT_PATH",
                pathlib.Path(empty_path),
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
        expected_prompt = engine._build_provenance_prompt(**inputs)
        with mock.patch.object(
            engine,
            "call_gemini",
            return_value=make_provenance_response_json(),
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
        for token in ("requests", "urllib", "socket"):
            self.assertNotIn(token, source, token)

    def test_no_app_integration(self):
        self.assertNotIn("app.py", engine_source())

    def test_no_notice_explainer_integration(self):
        self.assertNotIn("notice_explainer", engine_source())

    def test_no_notice_prompt_reference(self):
        self.assertNotIn("notice_prompt", engine_source())

    def test_provenance_validation_has_no_phrase_classifier(self):
        source = inspect.getsource(
            engine._run_provenance_pre_render_validation
        )
        self.assertNotIn("re.", source)
        self.assertNotIn(".lower(", source)

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

    def test_step_9_4_symbols_in_engine(self):
        source = engine_source()
        self.assertIn("DraftPostValidationResult", source)


class Step9E1DormantContractTests(unittest.TestCase):
    """§25 Step 9E.1 registry/contracts are exact, private and dormant."""

    EXPECTED_STATIC_TEMPLATES = {
        "static.working_draft": (
            "This is a CA working draft and requires professional review "
            "before use."
        ),
        "static.notice_material": (
            "The following notice-grounded material is relevant to this "
            "section."
        ),
        "static.open_items": (
            "The following matters remain open for verification."
        ),
        "static.taxpayer_verify": (
            "The taxpayer should verify the relevant records before any "
            "factual submission is made."
        ),
        "static.ca_confirm": (
            "CA review should confirm the relevant factual and evidentiary "
            "position."
        ),
        "static.records_if_available": (
            "If the relevant records are available, they should be "
            "reconciled against the notice-grounded material."
        ),
        "static.records_reconcile": (
            "The relevant records should be reconciled before any factual "
            "submission is made."
        ),
        "static.conditional_response": (
            "Any response should remain conditional on verification of the "
            "structured facts and records identified in this working draft."
        ),
        "static.legal_research_required": (
            "CA legal research is required before relying on any legal "
            "proposition not supplied by a verified legal-rule source."
        ),
        "static.no_legal_conclusion": (
            "This working draft does not express filing approval or a final "
            "legal conclusion."
        ),
    }

    def test_exact_closed_static_template_registry(self):
        self.assertEqual(len(engine._STATIC_TEMPLATE_REGISTRY), 10)
        self.assertEqual(
            dict(engine._STATIC_TEMPLATE_REGISTRY),
            self.EXPECTED_STATIC_TEMPLATES,
        )

    def test_unknown_static_template_has_no_fallback(self):
        with self.assertRaises(KeyError):
            engine._STATIC_TEMPLATE_REGISTRY["static.unknown"]

    def test_registry_is_immutable_and_non_parameterized(self):
        with self.assertRaises(TypeError):
            engine._STATIC_TEMPLATE_REGISTRY["static.dynamic"] = "dynamic"
        for template_id, text in engine._STATIC_TEMPLATE_REGISTRY.items():
            self.assertTrue(template_id.startswith("static."), template_id)
            self.assertNotIn("{", text, template_id)
            self.assertNotIn("}", text, template_id)
            self.assertNotIn("[[", text, template_id)
            self.assertNotIn("]]", text, template_id)

    def test_contract_construction_and_registry_use_make_no_llm_call(self):
        with mock.patch.object(engine, "call_gemini") as mocked:
            section = DraftCandidateSection(
                section_id="sec73_itc.s1",
                blocks=(
                    StaticDraftBlock(template_id="static.working_draft"),
                    DeadlineDraftBlock(),
                ),
            )
            self.assertIs(DraftBlockKind.STATIC, DraftBlockKind.STATIC)
            self.assertEqual(
                engine._STATIC_TEMPLATE_REGISTRY[
                    section.blocks[0].template_id
                ],
                self.EXPECTED_STATIC_TEMPLATES["static.working_draft"],
            )
            mocked.assert_not_called()

class Step9E2ProvenancePreparationTests(unittest.TestCase):
    """§25 Step 9E.2 context, prompt and strict parser contracts."""

    CONTEXT_KEYS = [
        "schema_version",
        "proceeding_type",
        "draft_eligibility",
        "sections",
        "static_template_ids",
        "facts",
        "arithmetic",
        "preflight",
        "deadline",
        "requirements",
        "evidence_checklist",
        "review_requirements",
        "validation_warnings",
    ]
    P0_SENTENCE = (
        "The Noticee is in the process of compiling vendor ledgers and "
        "agreements."
    )

    def _profile(self):
        return get_drafting_profile(ProceedingType.GST_SEC73_ITC)

    def _context_inputs(self):
        arithmetic = make_arithmetic(
            operand_values=(Decimal("999.90"), Decimal("111.10")),
            result=Decimal("888.80"),
        )
        return {
            "classification": make_classification(),
            "extraction_result": make_extraction(
                facts=[
                    make_fact(
                        fact_id="F-YES",
                        claim="CLAIM_MUST_NOT_APPEAR",
                        source_text="Allowed source text.",
                    ),
                    make_fact(
                        fact_id="F-NO",
                        claim="NO_CLAIM_MUST_NOT_APPEAR",
                        source_text="NO_SOURCE_MUST_NOT_APPEAR",
                        status=FactStatus.REQUIRES_VERIFICATION,
                        allowed_in_draft=DraftPermission.NO,
                    ),
                ]
            ),
            "preflight_result": make_preflight(),
            "arithmetic_results": [arithmetic],
            "validation_result": make_rich_validation(
                checks=checks_for_arithmetic([arithmetic])
            ),
            "deadline_result": make_deadline(),
        }

    def _build_context(self):
        inputs = self._context_inputs()
        return engine._build_provenance_controlled_context(
            **inputs,
            drafting_profile=self._profile(),
        )

    def _valid_payload(self):
        ids = [spec.section_id for spec in self._profile().sections]
        return {
            "sections": [
                {
                    "section_id": ids[0],
                    "blocks": [
                        {
                            "kind": "static",
                            "template_id": "static.working_draft",
                        },
                        {"kind": "fact", "fact_id": "F-YES"},
                        {"kind": "arithmetic", "arithmetic_index": 1},
                        {"kind": "deadline"},
                        {"kind": "hearing"},
                        {"kind": "requirement", "requirement_id": "req.s"},
                        {"kind": "evidence", "evidence_id": "ev.e1"},
                        {"kind": "review", "review_id": "rev.r1"},
                    ],
                },
                {
                    "section_id": ids[1],
                    "blocks": [
                        {"kind": "static", "template_id": "static.open_items"}
                    ],
                },
                {
                    "section_id": ids[2],
                    "blocks": [
                        {"kind": "fact", "fact_id": "F-YES"}
                    ],
                },
            ]
        }

    def _parse(self, payload):
        response = payload if isinstance(payload, str) else json.dumps(payload)
        return engine._parse_provenance_response(
            response,
            self._profile().sections,
        )

    def test_exact_provenance_context_keys_and_schema(self):
        context = self._build_context()
        self.assertEqual(list(context.keys()), self.CONTEXT_KEYS)
        self.assertEqual(context["schema_version"], "phase2.step9e.v1")
        self.assertEqual(
            context["static_template_ids"],
            list(engine._STATIC_TEMPLATE_REGISTRY.keys()),
        )
        self.assertEqual(
            [item["requirement_id"] for item in context["requirements"]],
            ["req.s", "req.m", "req.u", "req.d", "req.v"],
        )
        self.assertEqual(
            [item["status"] for item in context["requirements"]],
            [
                "satisfied",
                "missing",
                "unknown",
                "derived",
                "requires_verification",
            ],
        )

    def test_prohibited_data_absent_from_context(self):
        serialized = engine._serialize_context_json(self._build_context())
        self.assertNotIn("CLAIM_MUST_NOT_APPEAR", serialized)
        self.assertNotIn("NO_CLAIM_MUST_NOT_APPEAR", serialized)
        self.assertNotIn("NO_SOURCE_MUST_NOT_APPEAR", serialized)
        self.assertNotIn('"claim"', serialized)
        self.assertNotIn('"raw_notice"', serialized)
        self.assertNotIn('"special_rules"', serialized)
        self.assertNotIn('"current_date"', serialized)
        self.assertNotIn(
            engine._STATIC_TEMPLATE_REGISTRY["static.working_draft"],
            serialized,
        )
        self.assertEqual(
            [item["fact_id"] for item in self._build_context()["facts"]],
            ["F-YES"],
        )

    def test_provenance_context_serialization_is_deterministic(self):
        first = engine._serialize_context_json(self._build_context())
        second = engine._serialize_context_json(self._build_context())
        self.assertEqual(first, second)
        self.assertEqual(list(json.loads(first).keys()), self.CONTEXT_KEYS)
        self.assertIn('"888.80"', first)
        self.assertIn('"2025-03-10"', first)

    def test_versioned_prompt_assets_are_exact_closed_paths(self):
        self.assertEqual(
            engine._PROVENANCE_BASE_PROMPT_PATH,
            engine._PROMPTS_DIR / "provenance_v1" / "base_rules.txt",
        )
        self.assertEqual(
            list(engine._PROVENANCE_WORKFLOW_PROMPT_PATHS.keys()),
            [
                "sec61_scrutiny",
                "sec73_itc",
                "sec73_general",
                "sec73_rcm",
                "sec74_fraud",
                "sec129",
            ],
        )
        for path in engine._PROVENANCE_WORKFLOW_PROMPT_PATHS.values():
            self.assertTrue(path.is_file(), path)
            self.assertIn("provenance_v1", path.parts)
        found = {
            path.relative_to(engine._PROVENANCE_PROMPTS_DIR).as_posix()
            for path in engine._PROVENANCE_PROMPTS_DIR.rglob("*.txt")
        }
        self.assertEqual(
            found,
            {
                "base_rules.txt",
                "gst/sec61_scrutiny.txt",
                "gst/sec73_itc.txt",
                "gst/sec73_general.txt",
                "gst/sec73_rcm.txt",
                "gst/sec74_fraud.txt",
                "gst/sec129.txt",
            },
        )

    def test_exact_versioned_prompt_assembly_and_zero_llm_calls(self):
        inputs = self._context_inputs()
        with mock.patch.object(engine, "call_gemini") as mocked:
            prompt = engine._build_provenance_prompt(**inputs)
            mocked.assert_not_called()
        assets = engine._load_provenance_prompt_assets("sec73_itc")
        context = engine._build_provenance_controlled_context(
            **inputs,
            drafting_profile=self._profile(),
        )
        expected = engine._assemble_prompt(
            assets[0], assets[1], engine._serialize_context_json(context)
        )
        self.assertEqual(prompt, expected)
        self.assertEqual(prompt, engine._build_provenance_prompt(**inputs))

    def test_prompt_requests_only_typed_blocks_and_python_wording(self):
        base = engine._load_provenance_prompt_assets("sec73_itc")[0]
        self.assertIn('"blocks": [', base)
        self.assertIn("Python owns all final wording and rendering.", base)
        for field_name in (
            "body_template",
            "template_text",
            "text",
            "prose",
            "body",
            "claim",
            "explanation",
            "metadata",
            "payload",
        ):
            self.assertNotIn(f'"{field_name}":', base, field_name)

    def test_valid_response_builds_every_exact_block_dataclass_in_order(self):
        sections = self._parse(self._valid_payload())
        self.assertEqual(
            [type(block) for block in sections[0].blocks],
            [
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
        self.assertEqual(
            [section.section_id for section in sections],
            [spec.section_id for spec in self._profile().sections],
        )
        self.assertEqual(sections[0].blocks[1].fact_id, "F-YES")

    def test_unknown_static_id_is_typed_without_fallback_or_text(self):
        payload = self._valid_payload()
        payload["sections"][0]["blocks"] = [
            {"kind": "static", "template_id": "static.unknown"}
        ]
        sections = self._parse(payload)
        self.assertEqual(
            sections[0].blocks,
            (StaticDraftBlock(template_id="static.unknown"),),
        )
        self.assertNotIn("static.unknown", engine._STATIC_TEMPLATE_REGISTRY)

    def test_unknown_block_kind_rejected(self):
        payload = self._valid_payload()
        payload["sections"][0]["blocks"][0] = {"kind": "prose"}
        self.assertIsNone(self._parse(payload))

    def test_extra_root_section_and_block_fields_rejected(self):
        root = self._valid_payload()
        root["extra"] = True
        self.assertIsNone(self._parse(root))
        section = self._valid_payload()
        section["sections"][0]["extra"] = True
        self.assertIsNone(self._parse(section))
        block = self._valid_payload()
        block["sections"][0]["blocks"][0]["extra"] = True
        self.assertIsNone(self._parse(block))

    def test_legacy_and_prose_fields_reject_exact_p0_sentence(self):
        legacy_section = self._valid_payload()
        legacy_section["sections"][0] = {
            "section_id": self._profile().sections[0].section_id,
            "body_template": self.P0_SENTENCE,
        }
        self.assertIsNone(self._parse(legacy_section))
        for field_name in (
            "body_template",
            "template_text",
            "text",
            "prose",
            "body",
            "claim",
            "explanation",
            "metadata",
            "payload",
        ):
            with self.subTest(field_name=field_name):
                payload = self._valid_payload()
                payload["sections"][0]["blocks"][0][field_name] = (
                    self.P0_SENTENCE
                )
                self.assertIsNone(self._parse(payload))

    def test_missing_and_wrong_reference_fields_rejected(self):
        for block in (
            {"kind": "static"},
            {"kind": "fact"},
            {"kind": "arithmetic"},
            {"kind": "requirement"},
            {"kind": "evidence"},
            {"kind": "review"},
            {"kind": "fact", "fact_id": 1},
            {"kind": "arithmetic", "arithmetic_index": True},
            {"kind": "arithmetic", "arithmetic_index": 0},
        ):
            with self.subTest(block=block):
                payload = self._valid_payload()
                payload["sections"][0]["blocks"][0] = block
                self.assertIsNone(self._parse(payload))

    def test_malformed_json_provider_error_and_nonstring_rejected(self):
        for response in ("{", "Error: provider failed", "", "[]"):
            with self.subTest(response=response):
                self.assertIsNone(self._parse(response))
        self.assertIsNone(
            engine._parse_provenance_response(3, self._profile().sections)
        )

    def test_section_count_id_and_order_violations_rejected(self):
        count = self._valid_payload()
        count["sections"].pop()
        self.assertIsNone(self._parse(count))
        wrong_id = self._valid_payload()
        wrong_id["sections"][0]["section_id"] = "wrong"
        self.assertIsNone(self._parse(wrong_id))
        reordered = self._valid_payload()
        reordered["sections"][0], reordered["sections"][1] = (
            reordered["sections"][1],
            reordered["sections"][0],
        )
        self.assertIsNone(self._parse(reordered))

    def test_empty_blocks_duplicate_keys_and_partial_salvage_rejected(self):
        empty = self._valid_payload()
        empty["sections"][0]["blocks"] = []
        self.assertIsNone(self._parse(empty))
        duplicate = (
            '{"sections": [], "sections": []}'
        )
        self.assertIsNone(self._parse(duplicate))
        partial = self._valid_payload()
        partial["sections"][2]["blocks"] = [
            {"kind": "fact", "fact_id": "F-YES", "text": self.P0_SENTENCE}
        ]
        self.assertIsNone(self._parse(partial))

    def test_prepared_parser_performs_no_rendering_or_postvalidation(self):
        sections = self._parse(self._valid_payload())
        self.assertTrue(all(isinstance(item, DraftCandidateSection) for item in sections))
        self.assertTrue(all(not hasattr(item, "rendered_text") for item in sections))
        source = inspect.getsource(engine._parse_provenance_response)
        self.assertNotIn("DraftSection(", source)
        self.assertNotIn("_render", source)
        self.assertNotIn("_post_validate", source)

    def test_public_generation_uses_only_provenance_single_call_path(self):
        source = inspect.getsource(engine.generate_specialist_draft)
        self.assertIn("_build_provenance_prompt", source)
        self.assertIn("_parse_provenance_response", source)
        self.assertNotIn("_build_specialist_prompt", source)
        self.assertNotIn("_parse_strict_sections", source)
        self.assertEqual(source.count("call_gemini("), 1)
        result, mocked = run_draft()
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(
            list(DraftSection.__dataclass_fields__.keys()),
            ["section_id", "title", "rendered_text"],
        )


class Step9E3ActiveProvenanceTests(unittest.TestCase):
    """Atomic §25 activation: 21 checks and Python-only final text."""

    CHECK_IDS = [
        "draft.response.schema",
        "draft.sections.count",
        "draft.sections.ids",
        "draft.sections.order",
        "draft.sections.nonempty",
        "draft.blocks.kind",
        "draft.blocks.schema",
        "draft.blocks.static_template",
        "draft.blocks.fact_resolution",
        "draft.blocks.fact_permission",
        "draft.blocks.arithmetic_resolution",
        "draft.blocks.deadline_resolution",
        "draft.blocks.hearing_resolution",
        "draft.blocks.requirement_resolution",
        "draft.blocks.requirement_status",
        "draft.blocks.evidence_resolution",
        "draft.blocks.evidence_status",
        "draft.blocks.review_resolution",
        "draft.blocks.no_freeform",
        "draft.rendering.completeness",
        "draft.rendering.python_owned",
    ]
    P0_SENTENCE = (
        "The Noticee is in the process of compiling vendor ledgers and "
        "agreements."
    )
    PRE_RENDER_MESSAGES = (
        "Rendering completeness was not established because pre-render "
        "validation failed.",
        "Python-owned final rendering was not established because "
        "pre-render validation failed.",
    )

    def _success_inputs(self):
        arithmetic = make_arithmetic(
            status=ArithmeticStatus.MISMATCH,
            result=Decimal("1250.00"),
            formula="notice_credit - return_credit",
            currency="INR",
        )
        validation = make_validation_result(
            checks=checks_for_arithmetic([arithmetic]),
            requirements=[
                make_requirement(
                    requirement_id="req.open",
                    requirement_text="Vendor ledger reconciliation.",
                    status=RequirementStatus.UNKNOWN,
                )
            ],
            evidence_checklist=[
                make_evidence(
                    evidence_id="ev.ledger",
                    requirement_text="Vendor ledgers and agreements.",
                )
            ],
            review_requirements=[
                make_review(
                    review_id="rev.ca",
                    reason="Confirm the factual and evidentiary position.",
                )
            ],
        )
        return {
            "classification": make_classification(),
            "extraction_result": make_extraction(
                facts=[
                    make_fact(
                        fact_id="F-CONFIRMED",
                        source_text="ITC of INR 10,000 appears in the notice.",
                        source_page=2,
                    ),
                    make_fact(
                        fact_id="F-ALLEGED",
                        status=FactStatus.ALLEGED,
                        allowed_in_draft=DraftPermission.CONDITIONAL,
                        source_text="The taxpayer claimed excess credit.",
                        source_page=4,
                    ),
                ]
            ),
            "preflight_result": make_preflight(),
            "arithmetic_results": [arithmetic],
            "validation_result": validation,
            "deadline_result": make_deadline(
                notice_date=date(2025, 3, 10),
                service_date=date(2025, 3, 12),
                response_period_days=30,
                response_deadline=date(2025, 4, 11),
                deadline_confidence=DeadlineConfidence.CONFIRMED,
                deadline_status=DeadlineStatus.UPCOMING,
                days_remaining=20,
                hearing_date=date(2025, 5, 1),
                hearing_status=HearingStatus.UPCOMING,
                portal_verification_required=False,
                notes=("portal copy",),
            ),
        }

    def _success_payload(self):
        return {
            "sections": [
                {
                    "section_id": ITC_SECTION_IDS[0],
                    "blocks": [
                        {
                            "kind": "static",
                            "template_id": "static.notice_material",
                        },
                        {"kind": "fact", "fact_id": "F-CONFIRMED"},
                        {"kind": "fact", "fact_id": "F-ALLEGED"},
                    ],
                },
                {
                    "section_id": ITC_SECTION_IDS[1],
                    "blocks": [
                        {"kind": "arithmetic", "arithmetic_index": 1},
                        {"kind": "deadline"},
                        {"kind": "hearing"},
                        {
                            "kind": "requirement",
                            "requirement_id": "req.open",
                        },
                    ],
                },
                {
                    "section_id": ITC_SECTION_IDS[2],
                    "blocks": [
                        {"kind": "evidence", "evidence_id": "ev.ledger"},
                        {"kind": "review", "review_id": "rev.ca"},
                        {
                            "kind": "static",
                            "template_id": "static.conditional_response",
                        },
                    ],
                },
            ]
        }

    def _run_success(self):
        return run_draft(
            response=json.dumps(self._success_payload()),
            **self._success_inputs(),
        )

    def _assert_malformed(self, response):
        with mock.patch.object(engine, "_post_validate_and_render_provenance") as gate:
            result, mocked = run_draft(response=response)
        gate.assert_not_called()
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(
            result.failure_code, DraftFailureCode.MALFORMED_RESPONSE
        )
        self.assertEqual(result.sections, [])
        self.assertIsNone(result.post_validation)
        return result

    def _reference_payload(self, block):
        payload = json.loads(make_provenance_response_json())
        payload["sections"][0]["blocks"] = [block]
        return json.dumps(payload)

    def _assert_pre_render_failure(
        self,
        block,
        failed_check,
        **overrides,
    ):
        with mock.patch.object(engine, "_render_provenance_block") as renderer:
            result, mocked = run_draft(
                response=self._reference_payload(block),
                **overrides,
            )
        renderer.assert_not_called()
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(result.status, DraftGenerationStatus.FAILED)
        self.assertIs(
            result.failure_code,
            DraftFailureCode.POST_VALIDATION_FAILED,
        )
        self.assertEqual(result.sections, [])
        self.assertIsNotNone(result.post_validation)
        self.assertEqual(
            [item.check_id for item in result.post_validation.checks],
            self.CHECK_IDS,
        )
        self.assertEqual(len(result.post_validation.checks), 21)
        self.assertIs(
            check_by_id(result.post_validation, failed_check).status,
            ValidationStatus.FAIL,
        )
        self.assertEqual(
            tuple(item.message for item in result.post_validation.checks[-2:]),
            self.PRE_RENDER_MESSAGES,
        )
        self.assertTrue(
            all(
                item.status is ValidationStatus.FAIL
                for item in result.post_validation.checks[-2:]
            )
        )
        return result

    def test_success_renders_all_eight_block_kinds_exactly(self):
        result, mocked = self._run_success()
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertIsNone(result.failure_code)
        self.assertIsNone(result.error_message)
        self.assertEqual(
            [item.check_id for item in result.post_validation.checks],
            self.CHECK_IDS,
        )
        self.assertEqual(len(result.post_validation.checks), 21)
        self.assertTrue(
            all(
                item.status is ValidationStatus.PASS
                for item in result.post_validation.checks
            )
        )
        self.assertIs(
            result.post_validation.overall_status, ValidationStatus.PASS
        )
        expected = [
            (
                "The following notice-grounded material is relevant to this "
                "section.\n\n"
                'The notice records: "ITC of INR 10,000 appears in the '
                'notice." (notice p. 2)\n\n'
                'The department alleges: "The taxpayer claimed excess '
                'credit." (notice p. 4)'
            ),
            (
                "Deterministic reconciliation output: notice_credit - "
                "return_credit = 1250.00 INR (status: mismatch).\n\n"
                "Deterministic deadline output: notice_date=2025-03-10; "
                "service_date=2025-03-12; response_period_days=30; "
                "response_deadline=2025-04-11; "
                "deadline_confidence=confirmed; deadline_status=upcoming; "
                "days_remaining=20; portal_verification_required=false; "
                'notes=["portal copy"]; '
                "preflight_deadline_conflict_status=cannot_compare.\n\n"
                "Deterministic hearing output: hearing_date=2025-05-01; "
                "hearing_status=upcoming.\n\n"
                "Open item — status not established: Vendor ledger "
                "reconciliation."
            ),
            (
                "Evidence check required; availability, possession, "
                "preparation, compilation, enclosure, submission and "
                "verification are not established: Vendor ledgers and "
                "agreements.\n\n"
                "Mandatory ca_review review: Confirm the factual and "
                "evidentiary position.\n\n"
                "Any response should remain conditional on verification of "
                "the structured facts and records identified in this working "
                "draft."
            ),
        ]
        self.assertEqual(
            [section.rendered_text for section in result.sections], expected
        )
        profile = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        self.assertEqual(
            [section.title for section in result.sections],
            [section.title for section in profile.sections],
        )
        self.assertEqual(
            list(DraftSection.__dataclass_fields__),
            ["section_id", "title", "rendered_text"],
        )
        self.assertNotIn(self.P0_SENTENCE, "\n".join(expected))

    def test_success_dispatches_each_block_once_in_candidate_order(self):
        original = engine._render_provenance_block
        with mock.patch.object(
            engine,
            "_render_provenance_block",
            wraps=original,
        ) as dispatcher:
            result, mocked = self._run_success()
        self.assertIs(result.status, DraftGenerationStatus.SUCCESS)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(dispatcher.call_count, 10)
        self.assertEqual(
            [type(call.args[0]) for call in dispatcher.call_args_list],
            [
                StaticDraftBlock,
                FactDraftBlock,
                FactDraftBlock,
                ArithmeticDraftBlock,
                DeadlineDraftBlock,
                HearingDraftBlock,
                RequirementDraftBlock,
                EvidenceDraftBlock,
                ReviewDraftBlock,
                StaticDraftBlock,
            ],
        )

    def test_success_check_relationships_are_exact(self):
        result, _ = self._run_success()
        fact_resolution = check_by_id(
            result.post_validation, "draft.blocks.fact_resolution"
        )
        fact_permission = check_by_id(
            result.post_validation, "draft.blocks.fact_permission"
        )
        arithmetic = check_by_id(
            result.post_validation, "draft.blocks.arithmetic_resolution"
        )
        expected_fact_ids = ["F-CONFIRMED", "F-ALLEGED"]
        self.assertEqual(fact_resolution.related_fact_ids, expected_fact_ids)
        self.assertEqual(fact_permission.related_fact_ids, expected_fact_ids)
        self.assertEqual(
            arithmetic.related_calculation_types,
            [ArithmeticCalculationType.ITC_DIFFERENCE],
        )
        for item in result.post_validation.checks:
            if item not in (fact_resolution, fact_permission, arithmetic):
                self.assertEqual(item.related_fact_ids, [], item.check_id)
                self.assertEqual(
                    item.related_calculation_types, [], item.check_id
                )

    def test_success_messages_are_exact_in_authoritative_order(self):
        result, _ = self._run_success()
        self.assertEqual(
            [item.message for item in result.post_validation.checks],
            [
                "Draft candidate schema is structurally valid.",
                "Draft section count matches the drafting profile.",
                "Draft section IDs match the drafting profile.",
                "Draft section order matches the drafting profile.",
                "Every draft section contains at least one typed block.",
                "Every draft block kind is architecture-approved.",
                "Every draft block matches its exact typed schema.",
                "All static blocks resolve to the closed template registry.",
                "All fact blocks resolve to exactly one eligible ExtractedFact.",
                "All resolved fact blocks satisfy FactStatus and "
                "DraftPermission invariants.",
                "All arithmetic blocks resolve to approved deterministic "
                "arithmetic results.",
                "All deadline blocks resolve to the supplied deterministic "
                "deadline result.",
                "All hearing blocks resolve to supplied deterministic hearing "
                "information.",
                "All requirement blocks resolve to exactly one "
                "RequirementResult.",
                "All requirement blocks use the deterministic template "
                "authorized for their status.",
                "All evidence blocks resolve to exactly one "
                "EvidenceChecklistItem.",
                "All evidence blocks preserve the architecture-authorized "
                "evidence status.",
                "All review blocks resolve to exactly one mandatory "
                "ReviewRequirement.",
                "Draft candidate contains no provider-authored free-form prose "
                "field.",
                "Every accepted draft block was rendered exactly once in "
                "candidate order.",
                "Final specialist text is assembled only from Python-owned "
                "renderers and closed templates.",
            ],
        )

    def test_requirement_renderer_exact_closed_status_mapping(self):
        cases = [
            (
                RequirementStatus.SATISFIED,
                "Requirement status — satisfied: Required item.",
            ),
            (
                RequirementStatus.DERIVED,
                "Requirement status — derived from approved deterministic "
                "arithmetic: Required item.",
            ),
            (
                RequirementStatus.MISSING,
                "Open item — missing from a successful extraction: Required "
                "item.",
            ),
            (
                RequirementStatus.UNKNOWN,
                "Open item — status not established: Required item.",
            ),
            (
                RequirementStatus.REQUIRES_VERIFICATION,
                "Verification required: Required item.",
            ),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(
                    engine._render_requirement(
                        make_requirement(status=status)
                    ),
                    expected,
                )

    def test_evidence_and_review_renderers_are_exact(self):
        self.assertEqual(
            engine._render_evidence(
                make_evidence(requirement_text="Vendor agreement.")
            ),
            "Evidence check required; availability, possession, preparation, "
            "compilation, enclosure, submission and verification are not "
            "established: Vendor agreement.",
        )
        self.assertEqual(
            engine._render_review(
                make_review(reason="Confirm source material.")
            ),
            "Mandatory ca_review review: Confirm source material.",
        )

    def test_exact_p0_incident_rejected_in_every_prose_bearing_field(self):
        fields = (
            "body_template",
            "template_text",
            "text",
            "prose",
            "body",
            "claim",
            "explanation",
            "metadata",
            "payload",
        )
        for field_name in fields:
            with self.subTest(field_name=field_name):
                payload = self._success_payload()
                if field_name == "body_template":
                    payload["sections"][0] = {
                        "section_id": ITC_SECTION_IDS[0],
                        field_name: self.P0_SENTENCE,
                    }
                else:
                    payload["sections"][0]["blocks"][0][field_name] = (
                        self.P0_SENTENCE
                    )
                self._assert_malformed(json.dumps(payload))

    def test_semantic_family_has_no_successful_prose_field(self):
        attempts = (
            "The records have been prepared.",
            "Documents are being compiled.",
            "Documents have been submitted.",
            "Evidence is available and ready.",
            "The taxpayer has paid the amount.",
            "The taxpayer has filed the return.",
            "The taxpayer maintains compliant records.",
            "The ledgers have been reconciled.",
        )
        unauthorized_fields = (
            "text",
            "prose",
            "explanation",
            "metadata",
            "payload",
            "claim",
            "body",
            "template_text",
        )
        for attempted_text, field_name in zip(attempts, unauthorized_fields):
            with self.subTest(field_name=field_name):
                payload = self._success_payload()
                payload["sections"][0]["blocks"][0][field_name] = attempted_text
                result = self._assert_malformed(json.dumps(payload))
                self.assertNotIn(
                    attempted_text,
                    "\n".join(section.rendered_text for section in result.sections),
                )
        source = inspect.getsource(engine._run_provenance_pre_render_validation)
        self.assertNotIn("re.", source)
        self.assertNotIn(".lower(", source)

    def test_legacy_response_is_malformed_without_fallback(self):
        result = self._assert_malformed(make_response_json())
        self.assertEqual(
            result.error_message,
            "Specialist drafting response did not match the required schema.",
        )

    def test_duplicate_json_key_is_parser_level_malformed(self):
        response = make_provenance_response_json().replace(
            '"kind": "static"',
            '"kind": "static", "kind": "fact"',
            1,
        )
        self._assert_malformed(response)

    def test_parser_schema_failures_never_create_post_validation(self):
        for response in (
            "{",
            "[]",
            '{"sections": []}',
            make_provenance_response_json(
                sections=[
                    {
                        "section_id": ITC_SECTION_IDS[0],
                        "blocks": [{"kind": "prose", "text": "anything"}],
                    }
                ]
            ),
        ):
            with self.subTest(response=response):
                self._assert_malformed(response)

    def test_invalid_references_fail_before_every_renderer(self):
        valid_arithmetic = make_arithmetic()
        cases = [
            (
                {"kind": "static", "template_id": "static.unknown"},
                "draft.blocks.static_template",
                {},
            ),
            (
                {"kind": "fact", "fact_id": "F-UNKNOWN"},
                "draft.blocks.fact_resolution",
                {},
            ),
            (
                {"kind": "fact", "fact_id": "F-NO"},
                "draft.blocks.fact_permission",
                {
                    "extraction_result": make_extraction(
                        facts=[
                            make_fact(
                                fact_id="F-NO",
                                status=FactStatus.REQUIRES_VERIFICATION,
                                allowed_in_draft=DraftPermission.NO,
                            )
                        ]
                    )
                },
            ),
            (
                {"kind": "arithmetic", "arithmetic_index": 2},
                "draft.blocks.arithmetic_resolution",
                {
                    "arithmetic_results": [valid_arithmetic],
                    "validation_result": make_validation_result(
                        checks=checks_for_arithmetic([valid_arithmetic])
                    ),
                },
            ),
            (
                {"kind": "arithmetic", "arithmetic_index": 1},
                "draft.blocks.arithmetic_resolution",
                {
                    "arithmetic_results": [
                        make_arithmetic(status=ArithmeticStatus.INSUFFICIENT_DATA)
                    ],
                    "validation_result": make_validation_result(
                        checks=checks_for_arithmetic(
                            [make_arithmetic(status=ArithmeticStatus.INSUFFICIENT_DATA)]
                        )
                    ),
                },
            ),
            (
                {"kind": "deadline"},
                "draft.blocks.deadline_resolution",
                {"deadline_result": None},
            ),
            (
                {"kind": "hearing"},
                "draft.blocks.hearing_resolution",
                {"deadline_result": make_deadline()},
            ),
            (
                {"kind": "requirement", "requirement_id": "req.unknown"},
                "draft.blocks.requirement_resolution",
                {},
            ),
            (
                {"kind": "evidence", "evidence_id": "ev.unknown"},
                "draft.blocks.evidence_resolution",
                {},
            ),
            (
                {"kind": "review", "review_id": "rev.unknown"},
                "draft.blocks.review_resolution",
                {},
            ),
            (
                {"kind": "fact", "fact_id": "req.cross-family"},
                "draft.blocks.fact_resolution",
                {
                    "validation_result": make_validation_result(
                        requirements=[
                            make_requirement(requirement_id="req.cross-family")
                        ]
                    )
                },
            ),
            (
                {"kind": "fact", "fact_id": "F-DUP"},
                "draft.blocks.fact_resolution",
                {
                    "extraction_result": make_extraction(
                        facts=[
                            make_fact(fact_id="F-DUP"),
                            make_fact(fact_id="F-DUP"),
                        ]
                    )
                },
            ),
        ]
        for block, failed_check, overrides in cases:
            with self.subTest(block=block, failed_check=failed_check):
                self._assert_pre_render_failure(
                    block, failed_check, **overrides
                )

    def test_unauthorized_evidence_and_review_states_fail_pre_render(self):
        self._assert_pre_render_failure(
            {"kind": "evidence", "evidence_id": "ev.present"},
            "draft.blocks.evidence_status",
            validation_result=make_validation_result(
                evidence_checklist=[
                    make_evidence(
                        evidence_id="ev.present",
                        status=EvidenceStatus.PRESENT,
                    )
                ]
            ),
        )
        self._assert_pre_render_failure(
            {"kind": "review", "review_id": "rev.optional"},
            "draft.blocks.review_resolution",
            validation_result=make_validation_result(
                review_requirements=[
                    make_review(review_id="rev.optional", mandatory=False)
                ]
            ),
        )

    def test_derived_requirement_without_approved_arithmetic_fails(self):
        self._assert_pre_render_failure(
            {"kind": "requirement", "requirement_id": "req.derived"},
            "draft.blocks.requirement_status",
            validation_result=make_validation_result(
                requirements=[
                    make_requirement(
                        requirement_id="req.derived",
                        status=RequirementStatus.DERIVED,
                        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
                    )
                ]
            ),
        )

    def test_in_memory_freeform_tampering_fails_check_19_without_rendering(self):
        profile = get_drafting_profile(ProceedingType.GST_SEC73_ITC)
        sections = engine._parse_provenance_response(
            make_provenance_response_json(), profile.sections
        )
        sections[0].blocks[0].text = self.P0_SENTENCE
        with mock.patch.object(engine, "_render_provenance_block") as renderer:
            result = engine._post_validate_and_render_provenance(
                make_extraction(),
                make_preflight(),
                [],
                make_validation_result(),
                None,
                profile,
                sections,
            )
        renderer.assert_not_called()
        self.assertEqual(len(result.post_validation.checks), 21)
        self.assertIs(
            check_by_id(
                result.post_validation, "draft.blocks.no_freeform"
            ).status,
            ValidationStatus.FAIL,
        )

    def test_renderer_failure_uses_ordinary_checks_20_and_21_messages(self):
        with mock.patch.object(
            engine, "_render_provenance_block", return_value=None
        ) as renderer:
            result, mocked = run_draft()
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(renderer.call_count, 3)
        self.assertIs(
            result.failure_code, DraftFailureCode.POST_VALIDATION_FAILED
        )
        self.assertEqual(result.sections, [])
        self.assertEqual(len(result.post_validation.checks), 21)
        self.assertEqual(
            [item.message for item in result.post_validation.checks[-2:]],
            [
                "One or more accepted draft blocks were not rendered exactly "
                "once in candidate order.",
                "Final specialist text contains output not produced by an "
                "authorized Python renderer or closed template.",
            ],
        )

    def test_active_runtime_has_one_call_and_no_legacy_fallback(self):
        source = inspect.getsource(engine.generate_specialist_draft)
        self.assertEqual(source.count("call_gemini("), 1)
        self.assertIn("_build_provenance_prompt", source)
        self.assertIn("_parse_provenance_response", source)
        self.assertIn("_post_validate_and_render_provenance", source)
        for legacy in (
            "_build_specialist_prompt",
            "_parse_strict_sections",
            "_post_validate_and_render(",
        ):
            self.assertNotIn(legacy, source)


if __name__ == "__main__":
    unittest.main()
