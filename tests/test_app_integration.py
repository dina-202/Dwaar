"""Offline integration tests for the Step-10.2 Streamlit shell."""

import ast
from datetime import date
from decimal import Decimal
import pathlib
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

from domain import phase2_orchestrator as orchestrator_module
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
    DraftPostValidationResult,
    DraftSection,
    EvidenceChecklistItem,
    EvidenceStatus,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    Phase2AnalysisResult,
    PreflightResult,
    ProceedingType,
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewRequirement,
    SpecialistDraftResult,
    SupportLevel,
    TriageSummary,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
)
from modules import pdf_reader


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SOURCE = APP_PATH.read_text(encoding="utf-8")
PDF_BYTES = b"%PDF uploaded sentinel"
RAW_TEXT = "RAW NOTICE TEXT SENTINEL"
TODAY = date(2026, 8, 30)
RAW_CANDIDATE_SENTINEL = "RAW PROVIDER CANDIDATE MUST NEVER RENDER"
RENDERED_ONE = "Rendered specialist section one."
RENDERED_TWO = "Rendered specialist section two."
CLAIM_SENTINEL = "EXTRACTED CLAIM MUST NOT BECOME DRAFT PROSE"


class _UploadedFile:
    def __init__(self, events):
        self.events = events

    def read(self):
        self.events.append("read")
        return PDF_BYTES


class _Context:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        return self.fake

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeStreamlit:
    def __init__(self, uploaded):
        self.uploaded = uploaded
        self.calls = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def set_page_config(self, *args, **kwargs):
        self._record("set_page_config", *args, **kwargs)

    def title(self, *args, **kwargs):
        self._record("title", *args, **kwargs)

    def write(self, *args, **kwargs):
        self._record("write", *args, **kwargs)

    def caption(self, *args, **kwargs):
        self._record("caption", *args, **kwargs)

    def file_uploader(self, *args, **kwargs):
        self._record("file_uploader", *args, **kwargs)
        return self.uploaded

    def spinner(self, *args, **kwargs):
        self._record("spinner", *args, **kwargs)
        return _Context(self)

    def error(self, *args, **kwargs):
        self._record("error", *args, **kwargs)

    def header(self, *args, **kwargs):
        self._record("header", *args, **kwargs)

    def subheader(self, *args, **kwargs):
        self._record("subheader", *args, **kwargs)

    def dataframe(self, *args, **kwargs):
        self._record("dataframe", *args, **kwargs)

    def markdown(self, *args, **kwargs):
        self._record("markdown", *args, **kwargs)

    def expander(self, *args, **kwargs):
        self._record("expander", *args, **kwargs)
        return _Context(self)

    def text(self, *args, **kwargs):
        self._record("text", *args, **kwargs)


def make_fact():
    return ExtractedFact(
        fact_id="F-001",
        claim=CLAIM_SENTINEL,
        status=FactStatus.CONFIRMED,
        source_text="Source provenance text",
        source_page=2,
        allowed_in_draft=DraftPermission.YES,
        fact_type=FactType.STATED_AMOUNT,
        fact_role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
    )


def make_check(check_id, status):
    return ValidationItem(
        check_id=check_id,
        status=status,
        message=f"{status.value} check message",
        related_fact_ids=["F-001"],
        related_calculation_types=[ArithmeticCalculationType.ITC_DIFFERENCE],
    )


def make_arithmetic(status=ArithmeticStatus.PASS):
    return ArithmeticResult(
        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        status=status,
        source_fact_ids=["F-001", "F-002"],
        operand_values=[Decimal("1000"), Decimal("900")],
        result=(None if status is ArithmeticStatus.INSUFFICIENT_DATA else Decimal("100")),
        formula="GSTR-3B ITC - GSTR-2B ITC",
        currency="INR",
        allowed_in_draft=DraftPermission.CONDITIONAL,
    )


def make_triage(
    message,
    support_level=SupportLevel.TRIAGE_ONLY,
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    extraction_status=FactExtractionStatus.SUCCESS,
):
    return TriageSummary(
        proceeding_type=proceeding_type,
        notice_form=NoticeForm.DRC_01,
        support_level=support_level,
        classification_confidence=ClassificationConfidence.LOW,
        extraction_status=extraction_status,
        portal_verification_required=True,
        authority_verification_required=True,
        communication_identifier_status=CommunicationIdentifierStatus.UNKNOWN,
        authority_details_status=AuthorityDetailsStatus.UNKNOWN,
        deadline_status=DeadlineStatus.UNKNOWN,
        hearing_status=HearingStatus.NOT_SCHEDULED,
        requested_document_fact_ids=["F-REQ"],
        referenced_annexure_fact_ids=["F-ANN"],
        message=message,
    )


def make_result(
    *,
    support_level=SupportLevel.DEEP_WORKFLOW,
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    extraction_status=FactExtractionStatus.SUCCESS,
    arithmetic_status=ArithmeticStatus.PASS,
    include_arithmetic=True,
    draft_status=DraftGenerationStatus.SUCCESS,
    draft_eligibility=DraftEligibility.ALLOWED,
    failure_code=None,
    error_message=None,
    post_status=ValidationStatus.PASS,
    triage_summary=None,
):
    classification = NoticeClassification(
        notice_family=NoticeFamily.DEMAND_ADJUDICATION,
        notice_form=NoticeForm.DRC_01,
        proceeding_type=proceeding_type,
        support_level=support_level,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=["fixture"],
    )
    extraction = FactExtractionResult(
        facts=[] if extraction_status in (
            FactExtractionStatus.FAILED,
            FactExtractionStatus.NO_INPUT,
        ) else [make_fact()],
        status=extraction_status,
    )
    deadline = DeadlineResult(
        notice_date=date(2026, 8, 1),
        service_date=None,
        response_period_days=None,
        response_deadline=None,
        deadline_confidence=DeadlineConfidence.UNKNOWN,
        deadline_status=DeadlineStatus.UNKNOWN,
        days_remaining=None,
        hearing_date=date(2026, 9, 5),
        hearing_status=HearingStatus.UPCOMING,
        portal_verification_required=True,
        notes=["fixture note"],
    )
    preflight = PreflightResult(
        fact_extraction_status=extraction_status,
        communication_identifier_status=CommunicationIdentifierStatus.RFN_PRESENT,
        portal_verification_required=True,
        authority_details_status=AuthorityDetailsStatus.PARTIAL,
        authority_verification_required=True,
        stated_due_date_fact_ids=[],
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
        hearing_fact_ids=["F-H"],
        requested_document_fact_ids=["F-REQ"],
        referenced_annexure_fact_ids=["F-ANN"],
    )
    checks = [
        make_check("check.pass", ValidationStatus.PASS),
        make_check("check.warning", ValidationStatus.WARNING),
        make_check("check.fail", ValidationStatus.FAIL),
    ]
    unresolved = [
        RequirementResult(
            requirement_id="requirement.r1",
            requirement_text="Provide reconciliation records",
            status=RequirementStatus.REQUIRES_VERIFICATION,
            related_fact_ids=["F-001"],
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        )
    ]
    evidence = [
        EvidenceChecklistItem(
            evidence_id="evidence.e1",
            requirement_text="Purchase register",
            status=EvidenceStatus.UNKNOWN,
        )
    ]
    reviews = [
        ReviewRequirement(
            review_id="review.senior",
            level=ReviewLevel.SENIOR_CA_OR_ADVOCATE,
            reason="Senior review reason",
            mandatory=True,
        ),
        ReviewRequirement(
            review_id="review.urgent",
            level=ReviewLevel.URGENT_CA_REVIEW,
            reason="Urgent review reason",
            mandatory=True,
        ),
    ]
    validation = ValidationEngineResult(
        overall_status=ValidationStatus.WARNING,
        draft_eligibility=draft_eligibility,
        case_severity=None,
        checks=checks,
        requirements=unresolved,
        evidence_checklist=evidence,
        review_requirements=reviews,
    )
    post_validation = (
        None
        if post_status is None
        else DraftPostValidationResult(
            overall_status=post_status,
            checks=[make_check("post.check", post_status)],
        )
    )
    draft = SpecialistDraftResult(
        status=draft_status,
        draft_eligibility=draft_eligibility,
        sections=[
            DraftSection(
                section_id="s1",
                title="Section one",
                rendered_text=RENDERED_ONE,
            ),
            DraftSection(
                section_id="s2",
                title="Section two",
                rendered_text=RENDERED_TWO,
            ),
        ],
        unresolved_requirements=unresolved,
        evidence_checklist=evidence,
        review_requirements=reviews,
        post_validation=post_validation,
        failure_code=failure_code,
        error_message=error_message,
    )
    arithmetic = [make_arithmetic(arithmetic_status)] if include_arithmetic else []
    return Phase2AnalysisResult(
        classification=classification,
        extraction_result=extraction,
        deadline_result=deadline,
        preflight_result=preflight,
        arithmetic_results=arithmetic,
        validation_result=validation,
        draft_result=draft,
        triage_summary=triage_summary,
    )


def log_text(fake):
    return repr(fake.calls)


def headers(fake):
    return [args[0] for name, args, _ in fake.calls if name == "header"]


def calls_named(fake, name):
    return [call for call in fake.calls if call[0] == name]


def run_app(
    *,
    upload=True,
    result=None,
    extraction_error=None,
    orchestrator_error=None,
):
    events = []
    uploaded = _UploadedFile(events) if upload else None
    fake = FakeStreamlit(uploaded)
    result = result or make_result()

    class FixedDate(date):
        calls = 0

        @classmethod
        def today(cls):
            cls.calls += 1
            return TODAY

    def extract_side_effect(pdf_bytes):
        events.append("extract")
        if extraction_error is not None:
            raise extraction_error
        return RAW_TEXT

    def orchestrator_side_effect(*args):
        events.append("orchestrator")
        if orchestrator_error is not None:
            raise orchestrator_error
        return result

    extract_mock = Mock(side_effect=extract_side_effect)
    orchestrator_mock = Mock(side_effect=orchestrator_side_effect)
    with (
        patch.dict(sys.modules, {"streamlit": fake}),
        patch("datetime.date", FixedDate),
        patch.object(pdf_reader, "extract_text", extract_mock),
        patch.object(
            orchestrator_module,
            "run_phase2_analysis",
            orchestrator_mock,
        ),
    ):
        runpy.run_path(str(APP_PATH), run_name="__app_integration_test__")

    return fake, extract_mock, orchestrator_mock, events, FixedDate.calls


class SourceBoundaryTests(unittest.TestCase):
    def test_exact_allowed_import_boundary(self):
        tree = ast.parse(SOURCE)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(
            set(imports),
            {
                "datetime",
                "streamlit",
                "domain.models",
                "domain.phase2_orchestrator",
                "modules.pdf_reader",
            },
        )
        self.assertIn("run_phase2_analysis", SOURCE)
        self.assertIn("extract_text", SOURCE)

    def test_no_direct_engine_or_legacy_runtime_reference(self):
        lowered = SOURCE.lower()
        for prohibited in (
            "notice_explainer",
            "explain_notice",
            "build_notice_prompt",
            "notice_prompt",
            "classify_notice",
            "extract_facts",
            "calculate_deadline",
            "run_preflight",
            "run_arithmetic",
            "run_validation",
            "generate_specialist_draft",
            "proceeding_classifier",
            "fact_engine",
            "deadline_engine",
            "preflight_engine",
            "arithmetic_engine",
            "validation_engine",
            "drafting_engine",
        ):
            self.assertNotIn(prohibited, lowered, prohibited)

    def test_no_export_or_unsafe_draft_surface(self):
        lowered = SOURCE.lower()
        self.assertNotIn("download_button", lowered)
        self.assertNotIn("template_text", lowered)
        self.assertNotIn("session_state", lowered)


class UploadAndFailureTests(unittest.TestCase):
    def test_no_upload_means_no_extraction_or_orchestrator(self):
        _, extractor, runner, events, today_calls = run_app(upload=False)
        extractor.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(events, [])
        self.assertEqual(today_calls, 0)

    def test_bytes_text_and_today_flow_exactly_once_in_order(self):
        _, extractor, runner, events, today_calls = run_app()
        extractor.assert_called_once_with(PDF_BYTES)
        runner.assert_called_once_with(RAW_TEXT, TODAY)
        self.assertEqual(events, ["read", "extract", "orchestrator"])
        self.assertEqual(today_calls, 1)
        self.assertEqual(len(runner.call_args.args), 2)
        self.assertEqual(runner.call_args.kwargs, {})

    def test_pdf_runtime_error_is_displayed_and_stops_analysis(self):
        error = RuntimeError("Could not read this PDF: corrupt")
        fake, extractor, runner, events, today_calls = run_app(
            extraction_error=error
        )
        extractor.assert_called_once_with(PDF_BYTES)
        runner.assert_not_called()
        self.assertEqual(events, ["read", "extract"])
        self.assertEqual(today_calls, 0)
        self.assertIn(str(error), log_text(fake))
        self.assertEqual(len(calls_named(fake, "error")), 1)

    def test_unexpected_orchestrator_error_is_generic_and_has_no_fake_output(self):
        fake, _, runner, events, today_calls = run_app(
            orchestrator_error=ValueError("private infrastructure detail")
        )
        runner.assert_called_once_with(RAW_TEXT, TODAY)
        self.assertEqual(events, ["read", "extract", "orchestrator"])
        self.assertEqual(today_calls, 1)
        text = log_text(fake)
        self.assertIn("Phase-2 analysis could not be completed.", text)
        self.assertNotIn("private infrastructure detail", text)
        self.assertNotIn("Specialist draft", headers(fake))
        self.assertEqual(calls_named(fake, "expander"), [])


class StructuredRenderingTests(unittest.TestCase):
    def test_classification_extraction_and_fact_fields_render_enum_values(self):
        fake, *_ = run_app()
        text = log_text(fake)
        for expected in (
            "gst_sec73_itc",
            "deep_workflow",
            "drc_01",
            "high",
            "success",
            "F-001",
            "stated_amount",
            "gstr3b_itc_claimed_amount",
            "confirmed",
            "Source provenance text",
            "yes",
        ):
            self.assertIn(expected, text)
        self.assertNotIn(CLAIM_SENTINEL, text)

    def test_preflight_and_deadline_fields_render_without_fabricating_none(self):
        fake, *_ = run_app()
        text = log_text(fake)
        for expected in (
            "rfn_present",
            "partial",
            "portal_verification_required",
            "authority_verification_required",
            "unknown",
            "response_deadline",
            "days_remaining",
            "upcoming",
            "2026-09-05",
            "cannot_compare",
            "unavailable",
        ):
            self.assertIn(expected, text)

    def test_arithmetic_pass_mismatch_and_insufficient_are_not_hidden(self):
        for status in (
            ArithmeticStatus.PASS,
            ArithmeticStatus.MISMATCH,
            ArithmeticStatus.INSUFFICIENT_DATA,
        ):
            with self.subTest(status=status):
                fake, *_ = run_app(result=make_result(arithmetic_status=status))
                text = log_text(fake)
                self.assertIn("Arithmetic results", headers(fake))
                self.assertIn(status.value, text)
                self.assertIn("itc_difference", text)
                self.assertIn("GSTR-3B ITC - GSTR-2B ITC", text)
                self.assertIn("INR", text)
                self.assertIn("F-002", text)

    def test_empty_arithmetic_list_omits_section_safely(self):
        fake, *_ = run_app(result=make_result(include_arithmetic=False))
        self.assertNotIn("Arithmetic results", headers(fake))

    def test_validation_pass_warning_fail_and_gate_are_visible(self):
        fake, *_ = run_app()
        text = log_text(fake)
        self.assertIn("Validation status", headers(fake))
        for expected in (
            "overall_status",
            "draft_eligibility",
            "check.pass",
            "check.warning",
            "check.fail",
            "pass",
            "warning",
            "fail",
        ):
            self.assertIn(expected, text)

    def test_unresolved_evidence_and_review_metadata_render_separately(self):
        fake, *_ = run_app()
        text = log_text(fake)
        self.assertIn("Unresolved requirements", headers(fake))
        self.assertIn("Evidence checklist", headers(fake))
        self.assertIn("Review requirements", headers(fake))
        for expected in (
            "requirement.r1",
            "requires_verification",
            "Provide reconciliation records",
            "evidence.e1",
            "Purchase register",
            "unknown",
            "senior_ca_or_advocate",
            "urgent_ca_review",
        ):
            self.assertIn(expected, text)

    def test_empty_metadata_lists_are_safe(self):
        result = make_result()
        result.draft_result.unresolved_requirements.clear()
        result.draft_result.evidence_checklist.clear()
        result.draft_result.review_requirements.clear()
        fake, *_ = run_app(result=result)
        self.assertIn("Unresolved requirements", headers(fake))
        self.assertIn("Evidence checklist", headers(fake))
        self.assertIn("Review requirements", headers(fake))
        self.assertGreaterEqual(log_text(fake).count("None."), 3)


class TriageBranchTests(unittest.TestCase):
    def _assert_triage(self, result, expected_message):
        fake, *_ = run_app(result=result)
        text = log_text(fake)
        self.assertIn("Triage summary", headers(fake))
        self.assertIn(expected_message, text)
        self.assertEqual(calls_named(fake, "markdown"), [])
        self.assertNotIn(RENDERED_ONE, text)
        return fake

    def test_triage_only_and_unknown_remain_triage(self):
        triage_message = (
            "This notice is recognized for triage, but no approved deep "
            "specialist workflow is available."
        )
        triage = make_triage(triage_message)
        self._assert_triage(
            make_result(
                support_level=SupportLevel.TRIAGE_ONLY,
                draft_status=DraftGenerationStatus.BLOCKED,
                draft_eligibility=DraftEligibility.BLOCKED,
                failure_code=DraftFailureCode.DRAFT_BLOCKED,
                error_message="blocked",
                post_status=None,
                triage_summary=triage,
            ),
            triage_message,
        )

        unknown_message = (
            "This notice could not be matched to an approved deep specialist "
            "workflow."
        )
        unknown = make_triage(
            unknown_message,
            SupportLevel.UNKNOWN,
            ProceedingType.UNKNOWN,
        )
        self._assert_triage(
            make_result(
                support_level=SupportLevel.UNKNOWN,
                proceeding_type=ProceedingType.UNKNOWN,
                draft_status=DraftGenerationStatus.BLOCKED,
                draft_eligibility=DraftEligibility.BLOCKED,
                failure_code=DraftFailureCode.DRAFT_BLOCKED,
                error_message="blocked",
                post_status=None,
                triage_summary=unknown,
            ),
            unknown_message,
        )

    def test_no_input_and_failed_messages_are_exact(self):
        cases = [
            (
                FactExtractionStatus.NO_INPUT,
                "No usable notice text was available for Phase-2 analysis.",
            ),
            (
                FactExtractionStatus.FAILED,
                "Fact extraction failed, so specialist drafting is blocked.",
            ),
        ]
        for status, message in cases:
            with self.subTest(status=status):
                triage = make_triage(
                    message,
                    SupportLevel.DEEP_WORKFLOW,
                    ProceedingType.GST_SEC73_ITC,
                    status,
                )
                self._assert_triage(
                    make_result(
                        extraction_status=status,
                        draft_status=DraftGenerationStatus.BLOCKED,
                        draft_eligibility=DraftEligibility.BLOCKED,
                        failure_code=DraftFailureCode.DRAFT_BLOCKED,
                        error_message="blocked",
                        post_status=None,
                        triage_summary=triage,
                    ),
                    message,
                )


class DraftSafetyTests(unittest.TestCase):
    def test_success_with_post_validation_pass_displays_rendered_text_in_order(self):
        fake, *_ = run_app()
        self.assertIn("Specialist draft", headers(fake))
        markdown = [args[0] for _, args, _ in calls_named(fake, "markdown")]
        self.assertEqual(markdown, [RENDERED_ONE, RENDERED_TWO])
        subheaders = [args[0] for _, args, _ in calls_named(fake, "subheader")]
        self.assertEqual(subheaders[-2:], ["Section one", "Section two"])
        self.assertNotIn(RAW_CANDIDATE_SENTINEL, log_text(fake))

    def test_final_sections_require_no_legacy_or_candidate_fields(self):
        result = make_result()
        self.assertEqual(
            list(DraftSection.__dataclass_fields__),
            ["section_id", "title", "rendered_text"],
        )
        for section in result.draft_result.sections:
            self.assertFalse(hasattr(section, "template_text"))
            self.assertFalse(hasattr(section, "body_template"))
            self.assertFalse(hasattr(section, "candidate_blocks"))
            self.assertFalse(hasattr(section, "provider_json"))
        fake, *_ = run_app(result=result)
        self.assertEqual(
            [args[0] for _, args, _ in calls_named(fake, "markdown")],
            [RENDERED_ONE, RENDERED_TWO],
        )

    def test_raw_provider_candidate_attributes_are_never_rendered(self):
        result = make_result()
        result.draft_result.sections[0].candidate_blocks = (
            RAW_CANDIDATE_SENTINEL
        )
        result.draft_result.sections[0].provider_json = (
            RAW_CANDIDATE_SENTINEL
        )
        fake, *_ = run_app(result=result)
        self.assertEqual(
            [args[0] for _, args, _ in calls_named(fake, "markdown")],
            [RENDERED_ONE, RENDERED_TWO],
        )
        self.assertNotIn(RAW_CANDIDATE_SENTINEL, log_text(fake))

    def test_review_required_safe_final_draft_is_displayable(self):
        result = make_result(draft_eligibility=DraftEligibility.REVIEW_REQUIRED)
        fake, *_ = run_app(result=result)
        self.assertEqual(
            [args[0] for _, args, _ in calls_named(fake, "markdown")],
            [RENDERED_ONE, RENDERED_TWO],
        )

    def test_every_unsafe_draft_branch_suppresses_all_section_prose(self):
        cases = [
            make_result(post_status=None),
            make_result(post_status=ValidationStatus.FAIL),
            make_result(
                draft_status=DraftGenerationStatus.BLOCKED,
                draft_eligibility=DraftEligibility.BLOCKED,
                failure_code=DraftFailureCode.DRAFT_BLOCKED,
                error_message="blocked state",
                post_status=None,
            ),
            make_result(
                draft_status=DraftGenerationStatus.FAILED,
                failure_code=DraftFailureCode.LLM_ERROR,
                error_message="llm failure",
                post_status=None,
            ),
            make_result(
                draft_status=DraftGenerationStatus.FAILED,
                failure_code=DraftFailureCode.MALFORMED_RESPONSE,
                error_message="malformed response",
                post_status=None,
            ),
            make_result(
                draft_status=DraftGenerationStatus.FAILED,
                failure_code=DraftFailureCode.POST_VALIDATION_FAILED,
                error_message="post validation failed",
                post_status=ValidationStatus.FAIL,
            ),
        ]
        for result in cases:
            with self.subTest(
                status=result.draft_result.status,
                failure=result.draft_result.failure_code,
                post=result.draft_result.post_validation,
            ):
                fake, *_ = run_app(result=result)
                text = log_text(fake)
                self.assertEqual(calls_named(fake, "markdown"), [])
                self.assertNotIn("Specialist draft", headers(fake))
                self.assertIn("Drafting status", headers(fake))
                self.assertNotIn(RENDERED_ONE, text)
                self.assertNotIn(RENDERED_TWO, text)
                self.assertNotIn(RAW_CANDIDATE_SENTINEL, text)

    def test_failure_state_and_post_validation_diagnostics_are_structured(self):
        result = make_result(
            draft_status=DraftGenerationStatus.FAILED,
            draft_eligibility=DraftEligibility.BLOCKED,
            failure_code=DraftFailureCode.POST_VALIDATION_FAILED,
            error_message="post-validation diagnostic",
            post_status=ValidationStatus.FAIL,
        )
        fake, *_ = run_app(result=result)
        text = log_text(fake)
        for expected in (
            "failed",
            "post_validation_failed",
            "post-validation diagnostic",
            "blocked",
            "Post-validation diagnostics",
            "post.check",
        ):
            self.assertIn(expected, text)

    def test_llm_error_and_malformed_response_are_structured_only(self):
        for failure_code in (
            DraftFailureCode.LLM_ERROR,
            DraftFailureCode.MALFORMED_RESPONSE,
        ):
            with self.subTest(failure_code=failure_code):
                fake, *_ = run_app(
                    result=make_result(
                        draft_status=DraftGenerationStatus.FAILED,
                        failure_code=failure_code,
                        error_message="controlled failure",
                        post_status=None,
                    )
                )
                text = log_text(fake)
                self.assertIn(failure_code.value, text)
                self.assertIn("controlled failure", text)
                self.assertEqual(calls_named(fake, "markdown"), [])


class RenderOrderAndRawTextTests(unittest.TestCase):
    def test_full_functional_render_order_and_raw_text_last(self):
        triage_message = "Deterministic triage message sentinel."
        result = make_result(
            triage_summary=make_triage(triage_message),
        )
        fake, *_ = run_app(result=result)
        self.assertEqual(
            headers(fake),
            [
                "Classification and support",
                "Fact extraction",
                "Preflight and deadline",
                "Arithmetic results",
                "Validation status",
                "Unresolved requirements",
                "Evidence checklist",
                "Review requirements",
                "Triage summary",
                "Specialist draft",
            ],
        )
        self.assertEqual(fake.calls[-2][0], "expander")
        self.assertEqual(fake.calls[-2][1][0], "Extracted notice text")
        self.assertEqual(fake.calls[-1], ("text", (RAW_TEXT,), {}))

    def test_raw_text_is_only_displayed_in_final_extracted_text_area(self):
        fake, _, runner, _, _ = run_app()
        displayed = [call for call in fake.calls if RAW_TEXT in repr(call)]
        self.assertEqual(displayed, [("text", (RAW_TEXT,), {})])
        runner.assert_called_once_with(RAW_TEXT, TODAY)
        self.assertNotIn("raw_text", Phase2AnalysisResult.__dataclass_fields__)

    def test_absent_optional_sections_preserve_relative_order(self):
        fake, *_ = run_app(result=make_result(include_arithmetic=False))
        rendered_headers = headers(fake)
        self.assertLess(
            rendered_headers.index("Preflight and deadline"),
            rendered_headers.index("Validation status"),
        )
        self.assertLess(
            rendered_headers.index("Review requirements"),
            rendered_headers.index("Specialist draft"),
        )


if __name__ == "__main__":
    unittest.main()
