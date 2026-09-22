"""Offline integration tests for the Step-10.2 Streamlit shell."""

import ast
from datetime import date, datetime, timezone
from decimal import Decimal
import pathlib
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

from domain import evidence_engine as evidence_engine_module
from domain import evidence_review as evidence_review_module
from domain import phase2_orchestrator as orchestrator_module
from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisSnapshotRef,
    LoadedAnalysisSnapshot,
)
from domain.auth_models import AccessPermission, AuthenticatedPrincipal
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    StoredDocumentRef,
)
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
    DocumentPageText,
    DraftEligibility,
    DraftFailureCode,
    DraftGenerationStatus,
    DraftPermission,
    DraftPostValidationResult,
    DraftSection,
    EvidenceCandidate,
    EvidenceChecklistItem,
    EvidenceIntakeResult,
    EvidenceIntakeStatus,
    EvidenceReviewStatus,
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
    SourceTextOrigin,
    SourceVerificationStatus,
    SpecialistDraftResult,
    SupportLevel,
    TriageSummary,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
)
from modules import case_reopen_service as case_reopen_service_module
from modules.analysis_snapshot import build_snapshot_payload
from modules import evidence_workspace as evidence_workspace_module
from modules import pdf_reader
from modules import runtime_access as runtime_access_module
from modules import runtime_persistence as runtime_persistence_module
from modules.runtime_access import (
    AvailableFirmAccess,
    RuntimeAccessConfigurationError,
    RuntimeAccessConsistencyError,
)
from modules.case_reopen_service import (
    ReopenedCaseAnalysis,
    SavedCaseReopenError,
)
from modules.runtime_persistence import (
    RuntimePersistenceConfigurationError,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SOURCE = APP_PATH.read_text(encoding="utf-8")
PDF_BYTES = b"%PDF uploaded sentinel"
RAW_TEXT = "RAW NOTICE TEXT SENTINEL"
DOCUMENT_PAGES = [
    DocumentPageText(
        page_number=1,
        text=RAW_TEXT,
        origin=SourceTextOrigin.EMBEDDED,
        verification=SourceVerificationStatus.VERIFIED,
    )
]
TODAY = date(2026, 8, 30)
RAW_CANDIDATE_SENTINEL = "RAW PROVIDER CANDIDATE MUST NEVER RENDER"
RENDERED_ONE = "Rendered specialist section one."
RENDERED_TWO = "Rendered specialist section two."
CLAIM_SENTINEL = "EXTRACTED CLAIM MUST NOT BECOME DRAFT PROSE"
DEFAULT_USER_CLAIMS = {
    "iss": "https://issuer.test",
    "sub": "test-user-subject",
    "exp": 4102444800,
}


class _StopExecution(Exception):
    pass


class _FakeUser:
    def __init__(self, logged_in=True, claims=None):
        self.is_logged_in = logged_in
        self._claims = dict(
            DEFAULT_USER_CLAIMS if claims is None else claims
        )

    def to_dict(self):
        return dict(self._claims)


class _UploadedFile:
    def __init__(self, events, name="notice.pdf", payload=PDF_BYTES):
        self.events = events
        self.name = name
        self.payload = payload

    def read(self):
        self.events.append(f"read:{self.name}")
        return self.payload

    def getvalue(self):
        self.events.append(f"getvalue:{self.name}")
        return self.payload


class _Context:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        return self.fake

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeStreamlit:
    def __init__(
        self,
        uploaded,
        supporting_uploads=None,
        button_values=None,
        text_values=None,
        session_state=None,
        user=None,
        selectbox_values=None,
    ):
        self.uploaded = uploaded
        self.supporting_uploads = supporting_uploads or []
        self.button_values = button_values or {}
        self.text_values = text_values or {}
        self.session_state = {} if session_state is None else session_state
        self.user = user or _FakeUser()
        self.selectbox_values = selectbox_values or {}
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
        label = args[0] if args else kwargs.get("label", "")
        if "supporting evidence" in str(label).lower():
            return self.supporting_uploads
        return self.uploaded

    def text_input(self, *args, **kwargs):
        self._record("text_input", *args, **kwargs)
        return self.text_values.get(kwargs.get("key"), "")

    def button(self, *args, **kwargs):
        self._record("button", *args, **kwargs)
        return bool(self.button_values.get(kwargs.get("key"), False))

    def selectbox(self, *args, **kwargs):
        self._record("selectbox", *args, **kwargs)
        options = args[1] if len(args) > 1 else kwargs.get("options", [])
        key = kwargs.get("key")
        return self.selectbox_values.get(
            key,
            options[0] if options else None,
        )

    def login(self, *args, **kwargs):
        self._record("login", *args, **kwargs)

    def logout(self, *args, **kwargs):
        self._record("logout", *args, **kwargs)

    def stop(self):
        self._record("stop")
        raise _StopExecution()

    def spinner(self, *args, **kwargs):
        self._record("spinner", *args, **kwargs)
        return _Context(self)

    def error(self, *args, **kwargs):
        self._record("error", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._record("warning", *args, **kwargs)

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
    supporting_uploads=None,
    session_state=None,
    button_values=None,
    text_values=None,
    evidence_intake_result=None,
    logged_in=True,
    user_claims=None,
    available_firms=None,
    access_error=None,
    database_path_error=None,
    selectbox_values=None,
    persistence_service=None,
    persistence_error=None,
    snapshot_service=None,
    snapshot_service_error=None,
    reopen_result=None,
    reopen_error=None,
):
    events = []
    uploaded = _UploadedFile(events) if upload else None
    fake = FakeStreamlit(
        uploaded,
        supporting_uploads=supporting_uploads,
        button_values=button_values,
        text_values=text_values,
        session_state=session_state,
        user=_FakeUser(
            logged_in=logged_in,
            claims=user_claims,
        ),
        selectbox_values=selectbox_values,
    )
    result = result or make_result()
    if available_firms is None:
        available_firms = [
            AvailableFirmAccess(
                firm_id="F-TEST",
                display_name="Test Firm",
                permissions=frozenset(
                    {
                        AccessPermission.CASE_CREATE,
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                    }
                ),
            )
        ]

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
        return DOCUMENT_PAGES

    def orchestrator_side_effect(*args):
        events.append("orchestrator")
        if orchestrator_error is not None:
            raise orchestrator_error
        return result

    extract_mock = Mock(side_effect=extract_side_effect)
    orchestrator_mock = Mock(side_effect=orchestrator_side_effect)
    evidence_mock = Mock(
        return_value=evidence_intake_result
        if evidence_intake_result is not None
        else None
    )
    original_evidence = evidence_engine_module.propose_evidence_candidates

    def evidence_side_effect(*args, **kwargs):
        if evidence_intake_result is not None:
            return evidence_intake_result
        return original_evidence(*args, **kwargs)

    evidence_mock.side_effect = evidence_side_effect
    db_path_mock = Mock(return_value="test-dwaar.db")
    if database_path_error is not None:
        db_path_mock.side_effect = database_path_error
    firms_mock = Mock(return_value=available_firms)
    if access_error is not None:
        firms_mock.side_effect = access_error
    if persistence_service is None:
        persistence_service = Mock()
        persistence_service.list_cases.return_value = []
    elif isinstance(persistence_service.list_cases.return_value, Mock):
        persistence_service.list_cases.return_value = []
    persistence_service_mock = Mock(
        return_value=persistence_service
    )
    if persistence_error is not None:
        persistence_service_mock.side_effect = persistence_error

    if snapshot_service is None:
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = []
    elif isinstance(snapshot_service.list_snapshot_history.return_value, Mock):
        snapshot_service.list_snapshot_history.return_value = []
    snapshot_service_mock = Mock(return_value=snapshot_service)
    if snapshot_service_error is not None:
        snapshot_service_mock.side_effect = snapshot_service_error

    reopen_mock = Mock(return_value=reopen_result)
    if reopen_error is not None:
        reopen_mock.side_effect = reopen_error

    fake.db_path_mock = db_path_mock
    fake.firms_mock = firms_mock
    fake.persistence_service_mock = persistence_service_mock
    fake.snapshot_service_mock = snapshot_service_mock
    fake.reopen_mock = reopen_mock

    with (
        patch.dict(sys.modules, {"streamlit": fake}),
        patch("datetime.date", FixedDate),
        patch.object(
            runtime_access_module,
            "database_path_from_environment",
            db_path_mock,
        ),
        patch.object(
            runtime_access_module,
            "load_available_firms_for_permissions",
            firms_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_case_service",
            persistence_service_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_analysis_snapshot_service",
            snapshot_service_mock,
        ),
        patch.object(
            case_reopen_service_module,
            "reopen_case_analysis",
            reopen_mock,
        ),
        patch.object(pdf_reader, "extract_document_pages", extract_mock),
        patch.object(
            orchestrator_module,
            "run_phase2_analysis_from_document_pages",
            orchestrator_mock,
        ),
        patch.object(
            evidence_engine_module,
            "propose_evidence_candidates",
            evidence_mock,
        ),
        patch.object(
            evidence_workspace_module,
            "build_evidence_documents",
            return_value=[],
        ),
    ):
        try:
            runpy.run_path(
                str(APP_PATH),
                run_name="__app_integration_test__",
            )
        except _StopExecution:
            pass

    return (
        fake,
        extract_mock,
        orchestrator_mock,
        evidence_mock,
        events,
        FixedDate.calls,
    )


class AuthenticationAndFirmGateTests(unittest.TestCase):
    def test_logged_out_user_stops_before_upload_or_access_lookup(self):
        fake, extractor, runner, _, events, today_calls = run_app(
            logged_in=False,
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        fake.db_path_mock.assert_not_called()
        fake.firms_mock.assert_not_called()
        self.assertEqual(events, [])
        self.assertEqual(today_calls, 0)
        self.assertEqual(calls_named(fake, "file_uploader"), [])
        self.assertIn("Sign in to access", log_text(fake))
        self.assertTrue(calls_named(fake, "stop"))

    def test_logged_out_sign_in_button_invokes_streamlit_login(self):
        fake, *_ = run_app(
            logged_in=False,
            button_values={"dwaar_sign_in": True},
        )
        self.assertEqual(len(calls_named(fake, "login")), 1)
        self.assertTrue(calls_named(fake, "stop"))

    def test_unprovisioned_user_never_reaches_uploader(self):
        fake, extractor, runner, _, _, _ = run_app(
            available_firms=[],
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(calls_named(fake, "file_uploader"), [])
        self.assertIn("not provisioned to access cases", log_text(fake))
        self.assertIn("OIDC-", log_text(fake))
        fake.db_path_mock.assert_called_once_with()
        fake.firms_mock.assert_called_once()
        _, args, _ = fake.firms_mock.mock_calls[0]
        self.assertIsInstance(args[0], AuthenticatedPrincipal)
        self.assertEqual(args[1], "test-dwaar.db")
        self.assertEqual(
            args[2],
            {
                AccessPermission.CASE_CREATE,
                AccessPermission.CASE_READ,
            },
        )

    def test_expired_oidc_identity_stops_before_firm_lookup(self):
        fake, extractor, runner, _, _, _ = run_app(
            user_claims={
                "iss": "https://issuer.test",
                "sub": "expired-user",
                "exp": 1,
            },
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        fake.db_path_mock.assert_not_called()
        fake.firms_mock.assert_not_called()
        self.assertEqual(calls_named(fake, "file_uploader"), [])
        self.assertIn("expired", log_text(fake).lower())

    def test_database_configuration_failure_is_generic_and_closed(self):
        fake, extractor, runner, _, _, _ = run_app(
            database_path_error=RuntimeAccessConfigurationError(
                "private path detail"
            )
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        fake.firms_mock.assert_not_called()
        text = log_text(fake)
        self.assertIn("case storage is not configured", text)
        self.assertNotIn("private path detail", text)
        self.assertEqual(calls_named(fake, "file_uploader"), [])

    def test_access_consistency_failure_is_generic_and_closed(self):
        fake, extractor, runner, _, _, _ = run_app(
            access_error=RuntimeAccessConsistencyError(
                "private database detail"
            )
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        text = log_text(fake)
        self.assertIn("access configuration is inconsistent", text)
        self.assertNotIn("private database detail", text)
        self.assertEqual(calls_named(fake, "file_uploader"), [])

    def test_default_authorized_path_requires_case_create(self):
        fake, *_ = run_app(upload=False)
        fake.db_path_mock.assert_called_once_with()
        fake.firms_mock.assert_called_once()
        args = fake.firms_mock.call_args.args
        self.assertIsInstance(args[0], AuthenticatedPrincipal)
        self.assertEqual(args[1], "test-dwaar.db")
        self.assertEqual(
            args[2],
            {
                AccessPermission.CASE_CREATE,
                AccessPermission.CASE_READ,
            },
        )
        self.assertIn("Active firm: Test Firm (F-TEST)", log_text(fake))

    def test_multi_firm_selection_uses_selected_firm(self):
        firms = [
            AvailableFirmAccess(
                "F-1",
                "Alpha",
                frozenset(
                    {
                        AccessPermission.CASE_CREATE,
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                    }
                ),
            ),
            AvailableFirmAccess(
                "F-2",
                "Beta",
                frozenset(
                    {
                        AccessPermission.CASE_CREATE,
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                    }
                ),
            ),
        ]
        fake, *_ = run_app(
            upload=False,
            available_firms=firms,
            selectbox_values={
                "dwaar_active_firm_selector": "Beta (F-2)"
            },
        )
        self.assertEqual(len(calls_named(fake, "selectbox")), 1)
        self.assertIn("Active firm: Beta (F-2)", log_text(fake))
        self.assertEqual(
            fake.session_state["_dwaar_active_firm_id"],
            "F-2",
        )

    def test_switching_firms_clears_notice_and_evidence_session_state(self):
        shared_state = {
            "_dwaar_active_firm_id": "F-1",
            "_dwaar_notice_analysis_key": "notice-key",
            "_dwaar_notice_analysis_result": object(),
            "_dwaar_notice_document_pages": ["secret page"],
            "_dwaar_notice_raw_text": "Firm A secret raw text",
            "_dwaar_evidence_workspace_key": "evidence-key",
            "_dwaar_evidence_intake_result": object(),
            "_dwaar_evidence_reviews": [object()],
            "_dwaar_saved_intake_cases": {"old": "CASE-OLD"},
        }
        firms = [
            AvailableFirmAccess(
                "F-1",
                "Alpha",
                frozenset(
                    {
                        AccessPermission.CASE_CREATE,
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                    }
                ),
            ),
            AvailableFirmAccess(
                "F-2",
                "Beta",
                frozenset(
                    {
                        AccessPermission.CASE_CREATE,
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                    }
                ),
            ),
        ]
        fake, *_ = run_app(
            upload=False,
            session_state=shared_state,
            available_firms=firms,
            selectbox_values={
                "dwaar_active_firm_selector": "Beta (F-2)"
            },
        )
        self.assertEqual(shared_state["_dwaar_active_firm_id"], "F-2")
        for key in (
            "_dwaar_notice_analysis_key",
            "_dwaar_notice_analysis_result",
            "_dwaar_notice_document_pages",
            "_dwaar_notice_raw_text",
            "_dwaar_evidence_workspace_key",
            "_dwaar_evidence_intake_result",
            "_dwaar_evidence_reviews",
            "_dwaar_saved_intake_cases",
        ):
            self.assertNotIn(key, shared_state, key)
        self.assertNotIn("Firm A secret raw text", log_text(fake))

    def test_logout_clears_workspace_and_stops_before_uploader(self):
        shared_state = {
            "_dwaar_active_firm_id": "F-TEST",
            "_dwaar_notice_analysis_key": "notice-key",
            "_dwaar_notice_raw_text": "secret",
            "_dwaar_evidence_reviews": [object()],
            "_dwaar_saved_intake_cases": {"old": "CASE-OLD"},
        }
        fake, extractor, runner, _, _, _ = run_app(
            session_state=shared_state,
            button_values={"dwaar_logout": True},
        )
        extractor.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(len(calls_named(fake, "logout")), 1)
        self.assertEqual(calls_named(fake, "file_uploader"), [])
        self.assertNotIn("_dwaar_active_firm_id", shared_state)
        self.assertNotIn("_dwaar_notice_analysis_key", shared_state)
        self.assertNotIn("_dwaar_notice_raw_text", shared_state)
        self.assertNotIn("_dwaar_evidence_reviews", shared_state)
        self.assertNotIn("_dwaar_saved_intake_cases", shared_state)


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
                "domain.auth_models",
                "domain.evidence_engine",
                "domain.evidence_review",
                "domain.models",
                "domain.phase2_orchestrator",
                "modules.case_reopen_service",
                "modules.evidence_workspace",
                "modules.pdf_reader",
                "modules.runtime_access",
                "modules.runtime_persistence",
                "modules.runtime_security",
            },
        )
        self.assertIn("run_phase2_analysis_from_document_pages", SOURCE)
        self.assertIn("extract_document_pages", SOURCE)

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
        self.assertIn("session_state", lowered)


class UploadAndFailureTests(unittest.TestCase):
    def test_no_upload_means_no_extraction_or_orchestrator(self):
        _, extractor, runner, _, events, today_calls = run_app(upload=False)
        extractor.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(events, [])
        self.assertEqual(today_calls, 0)

    def test_bytes_text_and_today_flow_exactly_once_in_order(self):
        _, extractor, runner, _, events, today_calls = run_app()
        extractor.assert_called_once_with(PDF_BYTES)
        runner.assert_called_once_with(DOCUMENT_PAGES, TODAY)
        self.assertEqual(events, ["getvalue:notice.pdf", "extract", "orchestrator"])
        self.assertEqual(today_calls, 1)
        self.assertEqual(len(runner.call_args.args), 2)
        self.assertEqual(runner.call_args.kwargs, {})

    def test_pdf_runtime_error_is_displayed_and_stops_analysis(self):
        error = RuntimeError("Could not read this PDF: corrupt")
        fake, extractor, runner, _, events, today_calls = run_app(
            extraction_error=error
        )
        extractor.assert_called_once_with(PDF_BYTES)
        runner.assert_not_called()
        self.assertEqual(events, ["getvalue:notice.pdf", "extract"])
        self.assertEqual(today_calls, 0)
        self.assertIn(str(error), log_text(fake))
        self.assertEqual(len(calls_named(fake, "error")), 1)

    def test_unexpected_orchestrator_error_is_generic_and_has_no_fake_output(self):
        fake, _, runner, _, events, today_calls = run_app(
            orchestrator_error=ValueError("private infrastructure detail")
        )
        runner.assert_called_once_with(DOCUMENT_PAGES, TODAY)
        self.assertEqual(events, ["getvalue:notice.pdf", "extract", "orchestrator"])
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
                "Saved cases",
                "New notice intake",
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
                "Save as intake case",
                "Supporting evidence workspace",
            ],
        )
        self.assertEqual(fake.calls[-2][0], "expander")
        self.assertEqual(fake.calls[-2][1][0], "Extracted notice text")
        self.assertEqual(fake.calls[-1], ("text", (RAW_TEXT,), {}))

    def test_raw_text_is_only_displayed_in_final_extracted_text_area(self):
        fake, _, runner, _, _, _ = run_app()
        displayed = [call for call in fake.calls if RAW_TEXT in repr(call)]
        self.assertEqual(displayed, [("text", (RAW_TEXT,), {})])
        runner.assert_called_once_with(DOCUMENT_PAGES, TODAY)
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


class SavedCaseWorkspaceUiTests(unittest.TestCase):
    def _read_only_firm(
        self,
        *,
        document_read=True,
        case_update=False,
    ):
        permissions = {AccessPermission.CASE_READ}
        if document_read:
            permissions.add(AccessPermission.DOCUMENT_READ)
        if case_update:
            permissions.add(AccessPermission.CASE_UPDATE)
        return AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset(permissions),
        )

    def _create_only_firm(self):
        return AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset({AccessPermission.CASE_CREATE}),
        )

    def _case(self):
        return CaseRecord(
            case_id="CASE-1",
            firm_id="F-TEST",
            client_id="CLIENT-1",
            registration_id=None,
            title="Saved matter",
            status=CaseStatus.INTAKE,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _notice(self):
        return StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="saved-notice.pdf",
            media_type="application/pdf",
            byte_size=len(PDF_BYTES),
            sha256_hex="a" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _reopened(self):
        return ReopenedCaseAnalysis(
            case=self._case(),
            notice_document=self._notice(),
            notice_pdf_bytes=PDF_BYTES,
            document_pages=DOCUMENT_PAGES,
            raw_text=RAW_TEXT,
            analysis=make_result(),
        )

    def test_read_only_user_sees_saved_cases_but_no_new_uploader(self):
        service = Mock()
        service.list_cases.return_value = []
        fake, extractor, runner, _, _, _ = run_app(
            available_firms=[self._read_only_firm()],
            persistence_service=service,
        )
        self.assertIn("Saved cases", headers(fake))
        self.assertNotIn("New notice intake", headers(fake))
        self.assertEqual(calls_named(fake, "file_uploader"), [])
        extractor.assert_not_called()
        runner.assert_not_called()
        service.list_cases.assert_called_once()

    def test_create_only_user_sees_new_uploader_but_not_saved_cases(self):
        service = Mock()
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._create_only_firm()],
            persistence_service=service,
        )
        self.assertNotIn("Saved cases", headers(fake))
        self.assertIn("New notice intake", headers(fake))
        self.assertEqual(len(calls_named(fake, "file_uploader")), 1)
        service.list_cases.assert_not_called()

    def test_case_read_without_document_read_shows_metadata_only(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._read_only_firm(document_read=False)
            ],
            persistence_service=service,
        )
        text = log_text(fake)
        self.assertIn("CASE-1", text)
        self.assertIn("Saved matter", text)
        self.assertIn("do not have permission", text)
        self.assertEqual(
            [
                call
                for call in calls_named(fake, "button")
                if call[1] and call[1][0] == "Open saved case"
            ],
            [],
        )

    def test_open_saved_case_reanalyzes_verified_persisted_notice(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        reopened = self._reopened()

        fake, extractor, runner, _, _, today_calls = run_app(
            upload=False,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_result=reopened,
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertEqual(extractor.call_count, 0)
        self.assertEqual(runner.call_count, 0)
        self.assertGreaterEqual(today_calls, 1)
        fake.reopen_mock.assert_called_once()
        args = fake.reopen_mock.call_args.args
        self.assertIs(args[0], service)
        self.assertIsInstance(args[1], AuthenticatedPrincipal)
        self.assertEqual(args[2], "F-TEST")
        self.assertEqual(args[3], "CASE-1")
        self.assertEqual(args[4], TODAY)

        text = log_text(fake)
        self.assertIn("Opened case", text)
        self.assertIn("CASE-1", text)
        self.assertIn("recomputed_from_encrypted_notice", text)
        self.assertIn(
            "Saved historical snapshots, when present, are shown separately",
            text,
        )
        self.assertIn(RAW_TEXT, text)

    def test_opened_case_is_reused_on_unrelated_rerun(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        shared_state = {}
        reopened = self._reopened()

        first = run_app(
            upload=False,
            session_state=shared_state,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_result=reopened,
            button_values={"open_saved_case_CASE-1": True},
        )
        first[0].reopen_mock.assert_called_once()

        second = run_app(
            upload=False,
            session_state=shared_state,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_result=reopened,
        )
        second[0].reopen_mock.assert_not_called()
        self.assertIn("Opened case", log_text(second[0]))

    def test_reopen_failure_does_not_leak_internal_detail(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_error=SavedCaseReopenError(
                "private storage/parser detail"
            ),
            button_values={"open_saved_case_CASE-1": True},
        )
        text = log_text(fake)
        self.assertIn(
            "saved notice could not be safely reopened",
            text.lower(),
        )
        self.assertNotIn("private storage/parser detail", text)

class AnalysisSnapshotHistoryUiTests(unittest.TestCase):
    def _firm(self, *, case_update=False):
        permissions = {
            AccessPermission.CASE_READ,
            AccessPermission.DOCUMENT_READ,
        }
        if case_update:
            permissions.add(AccessPermission.CASE_UPDATE)
        return AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset(permissions),
        )

    def _case(self):
        return CaseRecord(
            case_id="CASE-1",
            firm_id="F-TEST",
            client_id="CLIENT-1",
            registration_id=None,
            title="Saved matter",
            status=CaseStatus.ANALYZED,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _notice(self):
        return StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="saved-notice.pdf",
            media_type="application/pdf",
            byte_size=len(PDF_BYTES),
            sha256_hex="a" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _reopened(self):
        return ReopenedCaseAnalysis(
            case=self._case(),
            notice_document=self._notice(),
            notice_pdf_bytes=PDF_BYTES,
            document_pages=DOCUMENT_PAGES,
            raw_text=RAW_TEXT,
            analysis=make_result(),
        )

    def _snapshot_ref(self, snapshot_id="SNAP-1"):
        return AnalysisSnapshotRef(
            snapshot_id=snapshot_id,
            case_id="CASE-1",
            source_document_id="DOC-1",
            source_document_sha256="a" * 64,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=123,
            sha256_hex="c" * 64,
            storage_key="objects/" + "d" * 32,
            created_at=datetime(
                2026, 8, 2, 12, 0, tzinfo=timezone.utc
            ),
            created_by="OIDC-" + "e" * 64,
        )

    def _loaded_snapshot(self):
        payload = build_snapshot_payload(
            make_result(),
            source_document_id="DOC-1",
            source_document_sha256="a" * 64,
        )
        payload["draft"]["sections"][0]["rendered_text"] = (
            "HISTORICAL DRAFT SENTINEL"
        )
        return LoadedAnalysisSnapshot(
            metadata=self._snapshot_ref(),
            payload=payload,
        )

    def _open_buttons(self, extra=None):
        values = {"open_saved_case_CASE-1": True}
        if extra:
            values.update(extra)
        return values

    def test_opened_case_lists_snapshot_history(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = [
            self._snapshot_ref()
        ]

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm()],
            persistence_service=case_service,
            snapshot_service=snapshot_service,
            reopen_result=self._reopened(),
            button_values=self._open_buttons(),
        )

        self.assertIn("Analysis history", headers(fake))
        snapshot_service.list_snapshot_history.assert_called_once()
        args = snapshot_service.list_snapshot_history.call_args
        self.assertIsInstance(args.args[0], AuthenticatedPrincipal)
        self.assertEqual(args.args[1], "F-TEST")
        self.assertEqual(args.kwargs["case_id"], "CASE-1")
        self.assertIn("SNAP-1", log_text(fake))

    def test_read_only_user_cannot_save_snapshot(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = []

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(case_update=False)],
            persistence_service=case_service,
            snapshot_service=snapshot_service,
            reopen_result=self._reopened(),
            button_values=self._open_buttons(),
        )

        save_buttons = [
            call
            for call in calls_named(fake, "button")
            if call[1]
            and call[1][0] == "Save current analysis snapshot"
        ]
        self.assertEqual(save_buttons, [])
        snapshot_service.save_current_analysis.assert_not_called()

    def test_case_updater_can_save_current_recomputed_analysis(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        saved = self._snapshot_ref()
        snapshot_service.save_current_analysis.return_value = saved
        snapshot_service.list_snapshot_history.side_effect = [
            [],
            [saved],
        ]

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(case_update=True)],
            persistence_service=case_service,
            snapshot_service=snapshot_service,
            reopen_result=self._reopened(),
            button_values=self._open_buttons(
                {"save_snapshot_CASE-1": True}
            ),
        )

        snapshot_service.save_current_analysis.assert_called_once()
        args = snapshot_service.save_current_analysis.call_args
        self.assertIsInstance(args.args[0], AuthenticatedPrincipal)
        self.assertEqual(args.args[1], "F-TEST")
        self.assertEqual(args.kwargs["case_id"], "CASE-1")
        self.assertIsInstance(
            args.kwargs["analysis"],
            Phase2AnalysisResult,
        )
        self.assertIsNotNone(args.kwargs["created_at"].tzinfo)
        self.assertIn("saved_snapshot_id", log_text(fake))
        self.assertIn("SNAP-1", log_text(fake))

    def test_view_historical_snapshot_is_labeled_and_read_only(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = [
            self._snapshot_ref()
        ]
        snapshot_service.load_snapshot.return_value = (
            self._loaded_snapshot()
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm()],
            persistence_service=case_service,
            snapshot_service=snapshot_service,
            reopen_result=self._reopened(),
            button_values=self._open_buttons(
                {"view_snapshot_SNAP-1": True}
            ),
        )

        snapshot_service.load_snapshot.assert_called_once()
        text = log_text(fake)
        self.assertIn("Historical analysis snapshot", text)
        self.assertIn("Historical record only", text)
        self.assertIn(ANALYSIS_ENGINE_VERSION, text)
        self.assertIn("HISTORICAL DRAFT SENTINEL", text)
        self.assertIn(
            "Historical draft text below is preserved for audit/history",
            text,
        )

    def test_snapshot_load_failure_does_not_leak_backend_detail(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = [
            self._snapshot_ref()
        ]
        snapshot_service.load_snapshot.side_effect = RuntimeError(
            "private ciphertext or database detail"
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm()],
            persistence_service=case_service,
            snapshot_service=snapshot_service,
            reopen_result=self._reopened(),
            button_values=self._open_buttons(
                {"view_snapshot_SNAP-1": True}
            ),
        )

        text = log_text(fake)
        self.assertIn(
            "historical analysis snapshot could not be loaded",
            text.lower(),
        )
        self.assertNotIn("private ciphertext", text)

    def test_snapshot_factory_failure_does_not_leak_config_detail(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm()],
            persistence_service=case_service,
            snapshot_service_error=RuntimePersistenceConfigurationError(
                "private path/key detail"
            ),
            reopen_result=self._reopened(),
            button_values=self._open_buttons(),
        )

        text = log_text(fake)
        self.assertIn(
            "Analysis history storage is not fully configured",
            text,
        )
        self.assertNotIn("private path/key detail", text)


class DurableIntakeUiTests(unittest.TestCase):
    def _save_keys(self):
        notice_key = evidence_workspace_module.notice_analysis_key(
            PDF_BYTES
        )
        save_key = f"F-TEST:{notice_key}"
        return {
            "save_key": save_key,
            "button": f"save_intake_{save_key}",
            "client": f"intake_client_{save_key}",
            "gstin": f"intake_gstin_{save_key}",
            "title": f"intake_title_{save_key}",
        }

    def test_analysis_renders_save_panel_without_persisting(self):
        fake, *_ = run_app()
        self.assertIn("Save as intake case", headers(fake))
        self.assertGreaterEqual(
            fake.persistence_service_mock.call_count,
            1,
        )
        self.assertIn(
            "current analysis is not yet persisted",
            log_text(fake),
        )

    def test_save_uses_structured_classification_and_authenticated_firm(self):
        keys = self._save_keys()
        service = Mock()
        saved_case = Mock()
        saved_case.case_id = "CASE-SAVED-1"
        saved_case.status.value = "intake"
        service.create_case_intake.return_value = saved_case

        fake, _, runner, _, _, _ = run_app(
            persistence_service=service,
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "Example Private Limited",
                keys["gstin"]: "06ABCDE1234F1Z5",
                keys["title"]: "ITC mismatch August",
            },
        )

        self.assertEqual(runner.call_count, 1)
        self.assertEqual(
            fake.persistence_service_mock.call_count,
            2,
        )
        service.create_case_intake.assert_called_once()
        args = service.create_case_intake.call_args
        self.assertIsInstance(args.args[0], AuthenticatedPrincipal)
        self.assertEqual(args.args[1], "F-TEST")
        self.assertEqual(
            args.kwargs["client_name"],
            "Example Private Limited",
        )
        self.assertEqual(
            args.kwargs["gstin"],
            "06ABCDE1234F1Z5",
        )
        self.assertEqual(
            args.kwargs["case_title"],
            "ITC mismatch August",
        )
        self.assertIs(
            args.kwargs["proceeding_type"],
            ProceedingType.GST_SEC73_ITC,
        )
        self.assertIs(args.kwargs["notice_form"], NoticeForm.DRC_01)
        self.assertIsNone(args.kwargs["response_deadline"])
        self.assertEqual(args.kwargs["notice_filename"], "notice.pdf")
        self.assertEqual(args.kwargs["notice_payload"], PDF_BYTES)
        self.assertIsNotNone(args.kwargs["opened_at"].tzinfo)
        self.assertEqual(
            fake.session_state["_dwaar_saved_intake_cases"][
                keys["save_key"]
            ],
            "CASE-SAVED-1",
        )
        self.assertIn("CASE-SAVED-1", log_text(fake))

    def test_saved_notice_does_not_create_duplicate_on_rerun(self):
        keys = self._save_keys()
        shared_state = {}
        first_service = Mock()
        saved_case = Mock()
        saved_case.case_id = "CASE-SAVED-1"
        saved_case.status.value = "intake"
        first_service.create_case_intake.return_value = saved_case

        run_app(
            session_state=shared_state,
            persistence_service=first_service,
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "Client",
                keys["title"]: "Matter",
            },
        )
        first_service.create_case_intake.assert_called_once()

        second_service = Mock()
        fake, _, runner, _, _, _ = run_app(
            session_state=shared_state,
            persistence_service=second_service,
        )
        self.assertEqual(runner.call_count, 0)
        self.assertGreaterEqual(
            fake.persistence_service_mock.call_count,
            1,
        )
        second_service.create_case_intake.assert_not_called()
        self.assertIn("CASE-SAVED-1", log_text(fake))

    def test_persistence_configuration_error_does_not_leak_detail(self):
        keys = self._save_keys()
        fake, *_ = run_app(
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "Client",
                keys["title"]: "Matter",
            },
            persistence_error=RuntimePersistenceConfigurationError(
                "private key/path detail"
            ),
        )
        text = log_text(fake)
        self.assertIn(
            "Durable case storage is not fully configured",
            text,
        )
        self.assertNotIn("private key/path detail", text)

    def test_validation_error_is_shown_without_saving_marker(self):
        keys = self._save_keys()
        service = Mock()
        service.create_case_intake.side_effect = ValueError(
            "gstin must match the standard 15-character GSTIN structure"
        )
        shared_state = {}
        fake, *_ = run_app(
            session_state=shared_state,
            persistence_service=service,
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "Client",
                keys["gstin"]: "INVALID",
                keys["title"]: "Matter",
            },
        )
        self.assertIn("gstin must match", log_text(fake))
        self.assertEqual(
            shared_state.get("_dwaar_saved_intake_cases", {}),
            {},
        )

    def test_default_case_title_is_derived_from_structured_classification(self):
        fake, *_ = run_app()
        title_calls = [
            call
            for call in calls_named(fake, "text_input")
            if call[2].get("key", "").startswith("intake_title_")
        ]
        self.assertEqual(len(title_calls), 1)
        self.assertEqual(
            title_calls[0][2]["value"],
            "DRC-01 — gst_sec73_itc",
        )


class EvidenceWorkspaceUiTests(unittest.TestCase):
    def _supporting_upload(self):
        return _UploadedFile(
            [],
            name="gstr2b.pdf",
            payload=b"%PDF supporting sentinel",
        )

    def _intake_result(self):
        return EvidenceIntakeResult(
            status=EvidenceIntakeStatus.SUCCESS,
            candidates=[
                EvidenceCandidate(
                    candidate_id="EC-001",
                    evidence_id="evidence.e1",
                    document_id="D-001",
                    source_text="Supporting source text",
                    source_page=1,
                    source_origin=SourceTextOrigin.EMBEDDED,
                    source_verification=SourceVerificationStatus.VERIFIED,
                )
            ],
        )

    def test_supporting_upload_renders_candidate_workspace(self):
        fake, _, _, evidence_mock, _, _ = run_app(
            supporting_uploads=[self._supporting_upload()],
            evidence_intake_result=self._intake_result(),
        )
        text = log_text(fake)
        self.assertIn("Supporting evidence workspace", headers(fake))
        self.assertIn("EC-001", text)
        self.assertIn("evidence.e1", text)
        self.assertIn("Supporting source text", text)
        evidence_mock.assert_called_once()

    def test_unchanged_session_reuses_notice_and_evidence_results(self):
        shared_state = {}
        support = [self._supporting_upload()]
        intake = self._intake_result()

        first = run_app(
            supporting_uploads=support,
            session_state=shared_state,
            evidence_intake_result=intake,
        )
        self.assertEqual(first[2].call_count, 1)
        self.assertEqual(first[3].call_count, 1)

        second = run_app(
            supporting_uploads=support,
            session_state=shared_state,
            evidence_intake_result=intake,
        )
        self.assertEqual(second[2].call_count, 0)
        self.assertEqual(second[3].call_count, 0)

    def test_supporting_file_change_recomputes_evidence_not_notice(self):
        shared_state = {}
        intake = self._intake_result()
        run_app(
            supporting_uploads=[self._supporting_upload()],
            session_state=shared_state,
            evidence_intake_result=intake,
        )
        changed = _UploadedFile(
            [],
            name="different.pdf",
            payload=b"%PDF changed supporting sentinel",
        )
        second = run_app(
            supporting_uploads=[changed],
            session_state=shared_state,
            evidence_intake_result=intake,
        )
        self.assertEqual(second[2].call_count, 0)
        self.assertEqual(second[3].call_count, 1)

    def test_confirm_creates_review_record_without_mutating_phase2(self):
        shared_state = {}
        support = [self._supporting_upload()]
        intake = self._intake_result()
        workspace_key = evidence_workspace_module.evidence_workspace_key(
            PDF_BYTES,
            [("gstr2b.pdf", b"%PDF supporting sentinel")],
            ["evidence.e1"],
        )
        button_key = f"confirm_{workspace_key}_EC-001"
        note_key = f"evidence_note_{workspace_key}_EC-001"

        original = make_result()
        fake, _, runner, _, _, _ = run_app(
            result=original,
            supporting_uploads=support,
            session_state=shared_state,
            evidence_intake_result=intake,
            button_values={button_key: True},
            text_values={note_key: "Checked by CA"},
        )

        self.assertEqual(runner.call_count, 1)
        reviews = shared_state["_dwaar_evidence_reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertIs(
            reviews[0].decision,
            EvidenceReviewStatus.CONFIRMED,
        )
        self.assertEqual(reviews[0].reviewer_note, "Checked by CA")
        self.assertIs(
            original.draft_result.evidence_checklist[0].status,
            EvidenceStatus.UNKNOWN,
        )
        self.assertIn("Evidence review records", log_text(fake))

    def test_reject_creates_rejected_review_record(self):
        shared_state = {}
        support = [self._supporting_upload()]
        intake = self._intake_result()
        workspace_key = evidence_workspace_module.evidence_workspace_key(
            PDF_BYTES,
            [("gstr2b.pdf", b"%PDF supporting sentinel")],
            ["evidence.e1"],
        )
        button_key = f"reject_{workspace_key}_EC-001"
        run_app(
            supporting_uploads=support,
            session_state=shared_state,
            evidence_intake_result=intake,
            button_values={button_key: True},
        )
        reviews = shared_state["_dwaar_evidence_reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertIs(reviews[0].decision, EvidenceReviewStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
