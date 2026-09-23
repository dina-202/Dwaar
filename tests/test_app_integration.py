"""Offline integration tests for the Step-10.2 Streamlit shell."""

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pathlib
import runpy
import sys
import unittest
from unittest.mock import ANY, Mock, patch

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
from domain.evidence_review_models import (
    EvidenceReviewRef,
    LoadedEvidenceReview,
)
from domain.filing_models import FilingRecord
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
    LoadedDraftVersion,
)
from domain.client_workspace_models import ClientWorkspace
from domain.case_operations_models import (
    CaseWorkItem,
    WorkQueueDeadlineStatus,
)
from domain.professional_queue_models import ProfessionalQueueItem
from domain.professional_workbench_models import (
    CaseAttentionCode,
    CaseWorkspace,
    ProfessionalCaseAttention,
)
from domain.case_timeline_models import (
    CaseTimelineItem,
    TimelineCategory,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    StoredDocumentRef,
    TaxRegistration,
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
from modules import case_evidence_service as case_evidence_service_module
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
        file_upload_values=None,
        button_values=None,
        text_values=None,
        session_state=None,
        user=None,
        selectbox_values=None,
    ):
        self.uploaded = uploaded
        self.supporting_uploads = supporting_uploads or []
        self.file_upload_values = file_upload_values or {}
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
        key = kwargs.get("key")
        if key in self.file_upload_values:
            return self.file_upload_values[key]
        label = args[0] if args else kwargs.get("label", "")
        if "supporting evidence" in str(label).lower():
            return self.supporting_uploads
        return self.uploaded

    def text_input(self, *args, **kwargs):
        self._record("text_input", *args, **kwargs)
        return self.text_values.get(kwargs.get("key"), "")

    def text_area(self, *args, **kwargs):
        self._record("text_area", *args, **kwargs)
        key = kwargs.get("key")
        default = kwargs.get("value", "")
        return self.text_values.get(key, default)

    def download_button(self, *args, **kwargs):
        self._record("download_button", *args, **kwargs)
        return False

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
    file_upload_values=None,
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
    evidence_workspace_service=None,
    evidence_workspace_service_error=None,
    evidence_review_service=None,
    evidence_review_service_error=None,
    draft_service=None,
    draft_service_error=None,
    filing_service=None,
    filing_service_error=None,
    professional_workbench_service=None,
    professional_workbench_service_error=None,
    persisted_evidence_ref=None,
    persisted_evidence_error=None,
    reopen_result=None,
    reopen_error=None,
):
    events = []
    uploaded = _UploadedFile(events) if upload else None
    fake = FakeStreamlit(
        uploaded,
        supporting_uploads=supporting_uploads,
        file_upload_values=file_upload_values,
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
        persistence_service.list_clients.return_value = []
        persistence_service.list_registrations.return_value = []
        persistence_service.list_case_work_queue.return_value = []
        persistence_service.get_case_timeline.return_value = []
    else:
        if isinstance(persistence_service.get_case_timeline.return_value, Mock):
            persistence_service.get_case_timeline.return_value = []
        if isinstance(persistence_service.list_cases.return_value, Mock):
            persistence_service.list_cases.return_value = []
        if isinstance(persistence_service.list_clients.return_value, Mock):
            persistence_service.list_clients.return_value = []
        if isinstance(
            persistence_service.list_case_work_queue.return_value,
            Mock,
        ):
            persistence_service.list_case_work_queue.return_value = []
        if isinstance(
            persistence_service.list_registrations.return_value,
            Mock,
        ):
            persistence_service.list_registrations.return_value = []
    if isinstance(
        persistence_service.get_client_workspace.return_value,
        Mock,
    ):
        clients_for_workspace = persistence_service.list_clients.return_value
        if clients_for_workspace:
            workspace_client = clients_for_workspace[0]
            workspace_registrations = (
                persistence_service.list_registrations.return_value
            )
            workspace_cases = [
                item
                for item in persistence_service.list_cases.return_value
                if getattr(item, "client_id", None)
                == workspace_client.client_id
            ]
            persistence_service.get_client_workspace.return_value = (
                ClientWorkspace(
                    client=workspace_client,
                    registrations=workspace_registrations,
                    cases=workspace_cases,
                )
            )
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

    if evidence_workspace_service is None:
        evidence_workspace_service = Mock()
    evidence_workspace_service_mock = Mock(
        return_value=evidence_workspace_service
    )
    if evidence_workspace_service_error is not None:
        evidence_workspace_service_mock.side_effect = (
            evidence_workspace_service_error
        )

    if evidence_review_service is None:
        evidence_review_service = Mock()
        evidence_review_service.list_reviews.return_value = []
        evidence_review_service.legal_evidence_readiness.return_value = []
    else:
        if isinstance(evidence_review_service.list_reviews.return_value, Mock):
            evidence_review_service.list_reviews.return_value = []
        if isinstance(
            evidence_review_service.legal_evidence_readiness.return_value,
            Mock,
        ):
            evidence_review_service.legal_evidence_readiness.return_value = []
    evidence_review_service_mock = Mock(
        return_value=evidence_review_service
    )
    if evidence_review_service_error is not None:
        evidence_review_service_mock.side_effect = evidence_review_service_error

    if draft_service is None:
        draft_service = Mock()
        draft_service.list_versions.return_value = []
    elif isinstance(draft_service.list_versions.return_value, Mock):
        draft_service.list_versions.return_value = []
    draft_service_mock = Mock(return_value=draft_service)
    if draft_service_error is not None:
        draft_service_mock.side_effect = draft_service_error

    if filing_service is None:
        filing_service = Mock()
        filing_service.list_filings.return_value = []
    elif isinstance(filing_service.list_filings.return_value, Mock):
        filing_service.list_filings.return_value = []
    filing_service_mock = Mock(return_value=filing_service)
    if filing_service_error is not None:
        filing_service_mock.side_effect = filing_service_error

    if professional_workbench_service is None:
        professional_workbench_service = Mock()

        def professional_queue_side_effect(principal, firm_id, *, today):
            return [
                ProfessionalQueueItem(
                    work_item=item,
                    attention_codes=(),
                    attention_workspaces=(),
                )
                for item in persistence_service.list_case_work_queue(
                    principal,
                    firm_id,
                    today=today,
                )
            ]

        professional_workbench_service.list_case_attention_queue.side_effect = (
            professional_queue_side_effect
        )
        professional_workbench_service.get_case_attention.side_effect = (
            lambda principal, firm_id, *, case_id: ProfessionalCaseAttention(
                case_id=case_id,
                case_status=CaseStatus.ANALYZED,
                latest_snapshot_id=None,
                latest_legal_brief_id=None,
                latest_draft_version_id=None,
                latest_filing_id=None,
                items=(),
            )
        )
    professional_workbench_service_mock = Mock(
        return_value=professional_workbench_service
    )
    if professional_workbench_service_error is not None:
        professional_workbench_service_mock.side_effect = (
            professional_workbench_service_error
        )

    persisted_evidence_mock = Mock(return_value=persisted_evidence_ref)
    if persisted_evidence_error is not None:
        persisted_evidence_mock.side_effect = persisted_evidence_error

    reopen_mock = Mock(return_value=reopen_result)
    if reopen_error is not None:
        reopen_mock.side_effect = reopen_error

    fake.db_path_mock = db_path_mock
    fake.firms_mock = firms_mock
    fake.persistence_service_mock = persistence_service_mock
    fake.snapshot_service_mock = snapshot_service_mock
    fake.evidence_workspace_service_mock = evidence_workspace_service_mock
    fake.evidence_review_service_mock = evidence_review_service_mock
    fake.draft_service_mock = draft_service_mock
    fake.filing_service_mock = filing_service_mock
    fake.professional_workbench_service_mock = (
        professional_workbench_service_mock
    )
    fake.persisted_evidence_mock = persisted_evidence_mock
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
            runtime_persistence_module,
            "build_authorized_evidence_workspace_service",
            evidence_workspace_service_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_evidence_review_service",
            evidence_review_service_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_draft_work_product_service",
            draft_service_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_filing_service",
            filing_service_mock,
        ),
        patch.object(
            runtime_persistence_module,
            "build_authorized_professional_workbench_service",
            professional_workbench_service_mock,
        ),
        patch.object(
            case_evidence_service_module,
            "add_supporting_evidence_pdf",
            persisted_evidence_mock,
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
                "domain.case_models",
                "domain.draft_work_product_models",
                "domain.evidence_engine",
                "domain.evidence_review",
                "domain.models",
                "domain.phase2_orchestrator",
                "modules.case_evidence_service",
                "modules.case_reopen_service",
                "modules.evidence_workspace",
                "modules.pdf_reader",
                "modules.runtime_access",
                "modules.runtime_persistence",
                "modules.runtime_security",
                "workflows.gst.legal_questions",
                "workflows.gst.legal_research",
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

    def test_only_reviewed_draft_export_surface_exists(self):
        lowered = SOURCE.lower()
        self.assertEqual(lowered.count("download_button"), 1)
        self.assertIn("download reviewed draft docx", lowered)
        self.assertIn("draftreviewstatus.reviewed", lowered)
        self.assertIn("draftreviewstatus.approved", lowered)
        self.assertNotIn("template_text", lowered)
        self.assertIn("session_state", lowered)


class UploadAndFailureTests(unittest.TestCase):
    def test_no_upload_means_no_extraction_or_orchestrator(self):
        _, extractor, runner, _, events, today_calls = run_app(upload=False)
        extractor.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(events, [])
        self.assertEqual(today_calls, 1)

    def test_bytes_text_and_today_flow_exactly_once_in_order(self):
        _, extractor, runner, _, events, today_calls = run_app()
        extractor.assert_called_once_with(PDF_BYTES)
        runner.assert_called_once_with(DOCUMENT_PAGES, TODAY)
        self.assertEqual(events, ["getvalue:notice.pdf", "extract", "orchestrator"])
        self.assertEqual(today_calls, 2)
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
        self.assertEqual(today_calls, 1)
        self.assertIn(str(error), log_text(fake))
        self.assertEqual(len(calls_named(fake, "error")), 1)

    def test_unexpected_orchestrator_error_is_generic_and_has_no_fake_output(self):
        fake, _, runner, _, events, today_calls = run_app(
            orchestrator_error=ValueError("private infrastructure detail")
        )
        runner.assert_called_once_with(DOCUMENT_PAGES, TODAY)
        self.assertEqual(events, ["getvalue:notice.pdf", "extract", "orchestrator"])
        self.assertEqual(today_calls, 2)
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
                "Case work queue",
                "Client workspace",
                "Saved cases",
                "New notice intake",
                "Classification and support",
                "Fact extraction",
                "Preflight and deadline",
                "Verified legal sources",
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

    def test_explicit_rerun_with_current_engine_replaces_cached_analysis(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        shared_state = {}
        first_reopened = self._reopened()
        second_reopened = ReopenedCaseAnalysis(
            case=first_reopened.case,
            notice_document=first_reopened.notice_document,
            notice_pdf_bytes=first_reopened.notice_pdf_bytes,
            document_pages=first_reopened.document_pages,
            raw_text="UPDATED RAW TEXT",
            analysis=make_result(),
        )

        first = run_app(
            upload=False,
            session_state=shared_state,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_result=first_reopened,
            button_values={"open_saved_case_CASE-1": True},
        )
        first[0].reopen_mock.assert_called_once()

        second = run_app(
            upload=False,
            session_state=shared_state,
            available_firms=[self._read_only_firm()],
            persistence_service=service,
            reopen_result=second_reopened,
            button_values={"rerun_saved_case_CASE-1": True},
        )
        second[0].reopen_mock.assert_called_once()
        self.assertIs(
            shared_state["_dwaar_opened_case_analysis"],
            second_reopened,
        )
        self.assertIn("UPDATED RAW TEXT", log_text(second[0]))

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

class CaseTimelineUiTests(unittest.TestCase):
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

    def _service(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        service.list_clients.return_value = []
        service.list_documents.return_value = []
        service.list_case_work_queue.return_value = []
        return service

    def test_timeline_renders_authorized_projection(self):
        service = self._service()
        service.get_case_timeline.return_value = [
            CaseTimelineItem(
                event_id="EV-FILE",
                event_type=CaseEventType.FILING_RECORDED,
                category=TimelineCategory.FILING,
                occurred_at=datetime(
                    2026, 9, 22, 12, 0, tzinfo=timezone.utc
                ),
                actor_id="OIDC-FILER",
                title="Filing recorded",
                summary="Portal / filing reference ARN-123.",
            )
        ]

        fake, *_ = run_app(
            upload=False,
            persistence_service=service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertIn("Case timeline", headers(fake))
        text = log_text(fake)
        self.assertIn("ARN-123", text)
        self.assertIn("filing", text)
        self.assertIn("OIDC-FILER", text)
        service.get_case_timeline.assert_called_once_with(
            ANY,
            "F-TEST",
            case_id="CASE-1",
        )

    def test_timeline_failure_is_generic(self):
        service = self._service()
        service.get_case_timeline.side_effect = RuntimeError(
            "private audit database detail"
        )

        fake, *_ = run_app(
            upload=False,
            persistence_service=service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        text = log_text(fake)
        self.assertIn("case timeline could not be loaded", text.lower())
        self.assertNotIn("private audit database detail", text)


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

    def test_snapshot_save_success_with_refresh_failure_is_controlled(self):
        case_service = Mock()
        case_service.list_cases.return_value = [self._case()]
        snapshot_service = Mock()
        saved = self._snapshot_ref()
        snapshot_service.save_current_analysis.return_value = saved
        snapshot_service.list_snapshot_history.side_effect = [
            [],
            RuntimeError("private refresh detail"),
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

        text = log_text(fake)
        self.assertIn("snapshot was saved", text.lower())
        self.assertIn("could not be refreshed", text.lower())
        self.assertNotIn("private refresh detail", text)

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


class DraftWorkProductUiTests(unittest.TestCase):
    def _firm(
        self,
        *,
        case_update=False,
        draft_review=False,
        document_read=True,
    ):
        permissions = {AccessPermission.CASE_READ}
        if document_read:
            permissions.add(AccessPermission.DOCUMENT_READ)
        if case_update:
            permissions.add(AccessPermission.CASE_UPDATE)
        if draft_review:
            permissions.add(AccessPermission.DRAFT_REVIEW)
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
            title="Saved GST matter",
            status=CaseStatus.ANALYZED,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _notice(self):
        return StoredDocumentRef(
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(PDF_BYTES),
            sha256_hex="a" * 64,
            storage_key="objects/" + "a" * 32,
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

    def _snapshot(self):
        return AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=100,
            sha256_hex="b" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            created_by="OIDC-" + "e" * 64,
        )

    def _version(
        self,
        *,
        version_id="DRAFT-1",
        version_number=1,
        status=DraftReviewStatus.WORKING,
        parent=None,
        generated=True,
    ):
        return DraftVersionRef(
            draft_version_id=version_id,
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=parent,
            version_number=version_number,
            generated_baseline=generated,
            content_sha256="c" * 64,
            byte_size=100,
            sha256_hex="d" * 64,
            storage_key="objects/" + "d" * 32,
            review_status=status,
            created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            created_by="OIDC-" + "e" * 64,
            reviewed_at=(
                datetime(2026, 8, 4, tzinfo=timezone.utc)
                if status in {
                    DraftReviewStatus.REVIEWED,
                    DraftReviewStatus.APPROVED,
                }
                else None
            ),
            reviewed_by=(
                "OIDC-REVIEWER"
                if status in {
                    DraftReviewStatus.REVIEWED,
                    DraftReviewStatus.APPROVED,
                }
                else None
            ),
            approved_at=(
                datetime(2026, 8, 5, tzinfo=timezone.utc)
                if status is DraftReviewStatus.APPROVED
                else None
            ),
            approved_by=(
                "OIDC-APPROVER"
                if status is DraftReviewStatus.APPROVED
                else None
            ),
        )

    def _loaded(self, version, text="## Facts\n\nDurable draft text"):
        return LoadedDraftVersion(
            metadata=version,
            payload={"draft_text": text},
        )

    def _case_service(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        service.list_documents.return_value = []
        service.list_clients.return_value = []
        service.list_case_work_queue.return_value = []
        return service

    def test_no_snapshot_warns_before_generated_baseline(self):
        service = self._case_service()
        draft_service = Mock()
        draft_service.list_versions.return_value = []
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = []

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(case_update=True)
            ],
            persistence_service=service,
            snapshot_service=snapshot_service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertIn("Draft work product", headers(fake))
        self.assertIn(
            "Save an analysis snapshot before creating a durable draft",
            log_text(fake),
        )
        draft_service.create_generated_baseline.assert_not_called()

    def test_case_updater_can_seed_baseline_from_saved_snapshot(self):
        service = self._case_service()
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = [
            self._snapshot()
        ]
        draft_service = Mock()
        draft_service.list_versions.side_effect = [
            [],
            [self._version()],
        ]
        draft_service.create_generated_baseline.return_value = (
            self._version()
        )
        draft_service.load_version.return_value = self._loaded(
            self._version()
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(case_update=True)
            ],
            persistence_service=service,
            snapshot_service=snapshot_service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "create_draft_baseline_CASE-1_SNAP-1": True,
            },
        )

        draft_service.create_generated_baseline.assert_called_once()
        kwargs = draft_service.create_generated_baseline.call_args.kwargs
        self.assertEqual(kwargs["case_id"], "CASE-1")
        self.assertEqual(kwargs["snapshot_id"], "SNAP-1")
        self.assertIsNotNone(kwargs["created_at"].tzinfo)
        self.assertIn("created_draft_version_id", log_text(fake))

    def test_edit_creates_new_child_version_without_overwriting_parent(self):
        service = self._case_service()
        version = self._version()
        child = self._version(
            version_id="DRAFT-2",
            version_number=2,
            parent="DRAFT-1",
            generated=False,
        )
        draft_service = Mock()
        draft_service.list_versions.return_value = [version]
        draft_service.load_version.return_value = self._loaded(version)
        draft_service.create_edited_version.return_value = child
        snapshot_service = Mock()
        snapshot_service.list_snapshot_history.return_value = [
            self._snapshot()
        ]

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(case_update=True)
            ],
            persistence_service=service,
            snapshot_service=snapshot_service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            text_values={
                "draft_editor_DRAFT-1": (
                    "## Facts\n\nCA edited durable text"
                )
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "save_draft_edit_DRAFT-1": True,
            },
        )

        draft_service.create_edited_version.assert_called_once()
        kwargs = draft_service.create_edited_version.call_args.kwargs
        self.assertEqual(
            kwargs["parent_draft_version_id"],
            "DRAFT-1",
        )
        self.assertEqual(
            kwargs["draft_text"],
            "## Facts\n\nCA edited durable text",
        )
        self.assertIn("DRAFT-2", log_text(fake))

    def test_draft_reviewer_can_mark_working_version_reviewed(self):
        service = self._case_service()
        version = self._version()
        reviewed = self._version(status=DraftReviewStatus.REVIEWED)
        draft_service = Mock()
        draft_service.list_versions.return_value = [version]
        draft_service.load_version.return_value = self._loaded(version)
        draft_service.transition_review.return_value = reviewed
        draft_service.export_version_docx.return_value = b"DOCX-BYTES"

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(draft_review=True)
            ],
            persistence_service=service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "draft_review_DRAFT-1_reviewed": True,
            },
        )

        draft_service.transition_review.assert_called_once()
        kwargs = draft_service.transition_review.call_args.kwargs
        self.assertIs(
            kwargs["target_status"],
            DraftReviewStatus.REVIEWED,
        )
        self.assertIn("reviewed_draft_version_id", log_text(fake))
        self.assertEqual(
            len(calls_named(fake, "download_button")),
            1,
        )

    def test_working_draft_has_no_export_button(self):
        service = self._case_service()
        version = self._version()
        draft_service = Mock()
        draft_service.list_versions.return_value = [version]
        draft_service.load_version.return_value = self._loaded(version)

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm()],
            persistence_service=service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertEqual(calls_named(fake, "download_button"), [])
        draft_service.export_version_docx.assert_not_called()

    def test_historical_version_is_read_only_and_cannot_be_edited(self):
        service = self._case_service()
        old = self._version()
        latest = self._version(
            version_id="DRAFT-2",
            version_number=2,
            parent="DRAFT-1",
            generated=False,
        )
        draft_service = Mock()
        draft_service.list_versions.return_value = [old, latest]
        draft_service.load_version.return_value = self._loaded(old)

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(case_update=True)
            ],
            persistence_service=service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            selectbox_values={
                "draft_version_selector_CASE-1": (
                    "v1 — working — DRAFT-1"
                )
            },
            button_values={"open_saved_case_CASE-1": True},
        )

        historical_views = [
            call
            for call in calls_named(fake, "text_area")
            if call[2].get("key") == "draft_view_DRAFT-1"
        ]
        self.assertEqual(len(historical_views), 1)
        self.assertTrue(historical_views[0][2]["disabled"])
        self.assertIn(
            "Historical draft versions are immutable",
            log_text(fake),
        )
        draft_service.create_edited_version.assert_not_called()


class FilingWorkspaceUiTests(unittest.TestCase):
    def _firm(self, *, can_file=False):
        permissions = {
            AccessPermission.CASE_READ,
            AccessPermission.DOCUMENT_READ,
        }
        if can_file:
            permissions.update(
                {
                    AccessPermission.FILING_RECORD,
                    AccessPermission.DOCUMENT_ADD,
                }
            )
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
            title="Saved GST matter",
            status=CaseStatus.DRAFT_REVIEW,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _notice(self):
        return StoredDocumentRef(
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(PDF_BYTES),
            sha256_hex="a" * 64,
            storage_key="objects/" + "a" * 32,
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

    def _approved_draft(self):
        return DraftVersionRef(
            draft_version_id="DRAFT-APPROVED",
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            content_sha256="c" * 64,
            byte_size=100,
            sha256_hex="d" * 64,
            storage_key="objects/" + "d" * 32,
            review_status=DraftReviewStatus.APPROVED,
            created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            created_by="OIDC-CREATOR",
            reviewed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            reviewed_by="OIDC-REVIEWER",
            approved_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            approved_by="OIDC-APPROVER",
        )

    def _draft_service(self):
        service = Mock()
        approved = self._approved_draft()
        service.list_versions.return_value = [approved]
        service.load_version.return_value = LoadedDraftVersion(
            metadata=approved,
            payload={"draft_text": "## Response\n\nApproved response"},
        )
        service.export_version_docx.return_value = b"DOCX"
        return service

    def _filing(self, *, with_ack=False):
        return FilingRecord(
            filing_id="FILING-1",
            case_id="CASE-1",
            approved_draft_version_id="DRAFT-APPROVED",
            filed_response_document_id="DOC-FILED",
            acknowledgement_document_id=(
                "DOC-ACK" if with_ack else None
            ),
            filing_reference="ARN-TEST-001",
            filed_at=datetime(
                2026, 9, 22, 22, 0,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
            filed_by="OIDC-FILER",
            recorded_at=datetime(
                2026, 9, 22, 17, 0, tzinfo=timezone.utc
            ),
            acknowledgement_added_at=(
                datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
                if with_ack
                else None
            ),
            acknowledgement_added_by=(
                "OIDC-FILER" if with_ack else None
            ),
        )

    def _case_service(self):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        service.list_documents.return_value = []
        service.list_clients.return_value = []
        service.list_case_work_queue.return_value = []
        return service

    def test_read_only_user_sees_filing_history_but_no_record_controls(self):
        filing_service = Mock()
        filing_service.list_filings.return_value = [
            self._filing()
        ]
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=False)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=self._draft_service(),
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertIn("Filing & acknowledgement", headers(fake))
        text = log_text(fake)
        self.assertIn("ARN-TEST-001", text)
        self.assertIn(
            "requires FILING_RECORD and DOCUMENT_ADD",
            text,
        )
        filing_service.record_filing.assert_not_called()

    def test_filing_requires_approved_draft_version(self):
        draft_service = self._draft_service()
        working = DraftVersionRef(
            **{
                **self._approved_draft().__dict__,
                "draft_version_id": "DRAFT-WORKING",
                "review_status": DraftReviewStatus.WORKING,
                "reviewed_at": None,
                "reviewed_by": None,
                "approved_at": None,
                "approved_by": None,
            }
        )
        draft_service.list_versions.return_value = [working]
        draft_service.load_version.return_value = LoadedDraftVersion(
            metadata=working,
            payload={"draft_text": "Working"},
        )
        filing_service = Mock()
        filing_service.list_filings.return_value = []

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=True)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=draft_service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        self.assertIn(
            "APPROVED immutable draft version is required",
            log_text(fake),
        )
        filing_service.record_filing.assert_not_called()

    def test_record_filing_passes_actual_pdf_reference_and_timestamp(self):
        filing_service = Mock()
        saved = self._filing()
        filing_service.list_filings.side_effect = [[], [saved]]
        filing_service.record_filing.return_value = saved
        response = _UploadedFile(
            [],
            name="portal-filed.pdf",
            payload=b"%PDF filed response",
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=True)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=self._draft_service(),
            reopen_result=self._reopened(),
            file_upload_values={
                "filed_response_CASE-1": response,
                "filing_ack_CASE-1": None,
            },
            text_values={
                "filing_reference_CASE-1": "ARN-TEST-001",
                "filing_time_CASE-1": (
                    "2026-09-22T22:00:00+05:30"
                ),
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "record_filing_CASE-1": True,
            },
        )

        filing_service.record_filing.assert_called_once()
        kwargs = filing_service.record_filing.call_args.kwargs
        self.assertEqual(
            kwargs["approved_draft_version_id"],
            "DRAFT-APPROVED",
        )
        self.assertEqual(kwargs["filing_reference"], "ARN-TEST-001")
        self.assertEqual(
            kwargs["filed_response_filename"],
            "portal-filed.pdf",
        )
        self.assertEqual(
            kwargs["filed_response_payload"],
            b"%PDF filed response",
        )
        self.assertIsNone(kwargs["acknowledgement_filename"])
        self.assertIsNone(kwargs["acknowledgement_payload"])
        self.assertIsNotNone(kwargs["filed_at"].tzinfo)
        self.assertIsNotNone(kwargs["recorded_at"].tzinfo)
        self.assertIn("recorded_filing_id", log_text(fake))

    def test_missing_filed_response_blocks_recording(self):
        filing_service = Mock()
        filing_service.list_filings.return_value = []
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=True)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=self._draft_service(),
            reopen_result=self._reopened(),
            file_upload_values={
                "filed_response_CASE-1": None,
                "filing_ack_CASE-1": None,
            },
            text_values={
                "filing_reference_CASE-1": "ARN-TEST-001",
                "filing_time_CASE-1": (
                    "2026-09-22T22:00:00+05:30"
                ),
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "record_filing_CASE-1": True,
            },
        )
        self.assertIn(
            "Upload the actual filed response PDF",
            log_text(fake),
        )
        filing_service.record_filing.assert_not_called()

    def test_invalid_filed_time_blocks_recording(self):
        filing_service = Mock()
        filing_service.list_filings.return_value = []
        response = _UploadedFile(
            [],
            name="filed.pdf",
            payload=b"%PDF filed",
        )
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=True)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=self._draft_service(),
            reopen_result=self._reopened(),
            file_upload_values={
                "filed_response_CASE-1": response,
            },
            text_values={
                "filing_reference_CASE-1": "ARN-TEST-001",
                "filing_time_CASE-1": "2026-09-22 22:00",
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "record_filing_CASE-1": True,
            },
        )
        self.assertIn(
            "include a timezone offset",
            log_text(fake),
        )
        filing_service.record_filing.assert_not_called()

    def test_late_acknowledgement_calls_durable_service(self):
        filing = self._filing()
        updated = self._filing(with_ack=True)
        filing_service = Mock()
        filing_service.list_filings.return_value = [filing]
        filing_service.attach_acknowledgement.return_value = updated
        ack = _UploadedFile(
            [],
            name="ack.pdf",
            payload=b"%PDF ack",
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(can_file=True)],
            persistence_service=self._case_service(),
            filing_service=filing_service,
            draft_service=self._draft_service(),
            reopen_result=self._reopened(),
            file_upload_values={
                "late_filing_ack_FILING-1": ack,
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "attach_filing_ack_FILING-1": True,
            },
        )

        filing_service.attach_acknowledgement.assert_called_once()
        kwargs = (
            filing_service.attach_acknowledgement.call_args.kwargs
        )
        self.assertEqual(kwargs["filing_id"], "FILING-1")
        self.assertEqual(
            kwargs["acknowledgement_filename"],
            "ack.pdf",
        )
        self.assertEqual(
            kwargs["acknowledgement_payload"],
            b"%PDF ack",
        )
        self.assertIsNotNone(kwargs["added_at"].tzinfo)
        self.assertIn("DOC-ACK", log_text(fake))


class PersistedEvidenceWorkspaceUiTests(unittest.TestCase):
    def _firm(
        self,
        *,
        document_add=False,
        evidence_review=False,
    ):
        permissions = {
            AccessPermission.CASE_READ,
            AccessPermission.DOCUMENT_READ,
        }
        if document_add:
            permissions.add(AccessPermission.DOCUMENT_ADD)
        if evidence_review:
            permissions.add(AccessPermission.EVIDENCE_REVIEW)
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
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(PDF_BYTES),
            sha256_hex="a" * 64,
            storage_key="objects/" + "a" * 32,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def _evidence_ref(self, document_id="DOC-EVIDENCE-1"):
        return StoredDocumentRef(
            document_id=document_id,
            case_id="CASE-1",
            kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
            original_filename="gstr2b.pdf",
            media_type="application/pdf",
            byte_size=321,
            sha256_hex="b" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

    def _snapshot(self):
        return AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=100,
            sha256_hex="c" * 64,
            storage_key="objects/" + "c" * 32,
            created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            created_by="OIDC-" + "a" * 64,
        )

    def _review_ref(
        self,
        *,
        review_id="EREV-1",
        decision=EvidenceReviewStatus.CONFIRMED,
    ):
        return EvidenceReviewRef(
            review_id=review_id,
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            evidence_id="evidence.e1",
            document_id="DOC-PERSISTED-77",
            source_page=2,
            source_text_sha256="d" * 64,
            candidate_fingerprint="e" * 64,
            decision=decision,
            byte_size=120,
            sha256_hex="f" * 64,
            storage_key="objects/" + "f" * 32,
            reviewed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            reviewed_by="OIDC-" + "a" * 64,
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

    def _case_service(self, docs):
        service = Mock()
        service.list_cases.return_value = [self._case()]
        service.list_documents.return_value = list(docs)
        return service

    def _snapshot_service(self, with_history=True):
        service = Mock()
        service.list_snapshot_history.return_value = (
            [self._snapshot()] if with_history else []
        )
        return service

    def _review_service(self, checklist=None):
        service = Mock()
        service.snapshot_evidence_checklist.return_value = (
            checklist
            if checklist is not None
            else [
                EvidenceChecklistItem(
                    evidence_id="evidence.e1",
                    requirement_text="Persisted snapshot requirement",
                    status=EvidenceStatus.UNKNOWN,
                )
            ]
        )
        service.list_reviews.return_value = []
        return service

    def test_document_add_user_can_attach_encrypted_supporting_pdf(self):
        service = self._case_service([self._notice()])
        persisted = self._evidence_ref()
        shared_state = {
            "_dwaar_evidence_workspace_key": "stale",
            "_dwaar_evidence_intake_result": object(),
            "_dwaar_evidence_reviews": [object()],
        }
        upload = _UploadedFile(
            [],
            name="gstr2b.pdf",
            payload=b"%PDF supporting evidence",
        )

        fake, *_ = run_app(
            upload=False,
            session_state=shared_state,
            supporting_uploads=[upload],
            available_firms=[self._firm(document_add=True)],
            persistence_service=service,
            persisted_evidence_ref=persisted,
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "attach_evidence_CASE-1": True,
            },
        )

        fake.persisted_evidence_mock.assert_called_once()
        args = fake.persisted_evidence_mock.call_args
        self.assertIs(args.args[0], service)
        self.assertIsInstance(args.args[1], AuthenticatedPrincipal)
        self.assertEqual(args.args[2], "F-TEST")
        self.assertEqual(args.kwargs["case_id"], "CASE-1")
        self.assertEqual(args.kwargs["filename"], "gstr2b.pdf")
        self.assertEqual(
            args.kwargs["payload"],
            b"%PDF supporting evidence",
        )
        self.assertIsNotNone(args.kwargs["created_at"].tzinfo)
        self.assertIn("DOC-EVIDENCE-1", log_text(fake))
        self.assertNotIn("_dwaar_evidence_workspace_key", shared_state)
        self.assertNotIn("_dwaar_evidence_intake_result", shared_state)
        self.assertNotIn("_dwaar_evidence_reviews", shared_state)

    def test_without_document_add_attachment_control_is_hidden(self):
        evidence_ref = self._evidence_ref()
        service = self._case_service([self._notice(), evidence_ref])
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(evidence_review=True)],
            persistence_service=service,
            snapshot_service=self._snapshot_service(),
            evidence_review_service=self._review_service(),
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        attach_uploaders = [
            call
            for call in calls_named(fake, "file_uploader")
            if call[1]
            and "attach supporting evidence" in call[1][0].lower()
        ]
        self.assertEqual(attach_uploaders, [])
        self.assertIn(
            "Attaching supporting evidence requires DOCUMENT_ADD",
            log_text(fake),
        )

    def test_evidence_review_permission_controls_matching_action(self):
        evidence_ref = self._evidence_ref()
        service = self._case_service([self._notice(), evidence_ref])
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(document_add=True)],
            persistence_service=service,
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )

        analyze_buttons = [
            call
            for call in calls_named(fake, "button")
            if call[1]
            and "Analyze attached evidence" in call[1][0]
        ]
        self.assertEqual(analyze_buttons, [])
        self.assertIn(
            "Evidence matching/review requires EVIDENCE_REVIEW",
            log_text(fake),
        )
        fake.evidence_workspace_service_mock.assert_not_called()
        fake.evidence_review_service_mock.assert_not_called()

    def test_no_snapshot_blocks_durable_review_context(self):
        evidence_ref = self._evidence_ref()
        service = self._case_service([self._notice(), evidence_ref])
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(evidence_review=True)],
            persistence_service=service,
            snapshot_service=self._snapshot_service(with_history=False),
            evidence_review_service=self._review_service(),
            reopen_result=self._reopened(),
            button_values={"open_saved_case_CASE-1": True},
        )
        self.assertIn(
            "Save the current analysis as an analysis snapshot",
            log_text(fake),
        )
        fake.evidence_review_service_mock.assert_called_once()
        fake.evidence_workspace_service_mock.assert_not_called()

    def test_matching_uses_selected_snapshot_checklist_and_persisted_ids(self):
        evidence_ref = self._evidence_ref("DOC-PERSISTED-77")
        service = self._case_service([self._notice(), evidence_ref])
        candidate = EvidenceCandidate(
            candidate_id="EC-001",
            evidence_id="evidence.e1",
            document_id="DOC-PERSISTED-77",
            source_text="Persisted GSTR-2B source",
            source_page=2,
            source_origin=SourceTextOrigin.EMBEDDED,
            source_verification=SourceVerificationStatus.VERIFIED,
        )
        intake = EvidenceIntakeResult(
            status=EvidenceIntakeStatus.SUCCESS,
            candidates=[candidate],
            rejected_candidate_count=0,
        )
        workspace = Mock()
        workspace.document_refs = [evidence_ref]
        workspace.intake_result = intake
        evidence_service = Mock()
        evidence_service.analyze_case_evidence.return_value = workspace
        checklist = [
            EvidenceChecklistItem(
                evidence_id="evidence.e1",
                requirement_text="Snapshot-specific GSTR-2B requirement",
                status=EvidenceStatus.UNKNOWN,
            )
        ]
        review_service = self._review_service(checklist)

        fake, *_ = run_app(
            upload=False,
            available_firms=[
                self._firm(document_add=True, evidence_review=True)
            ],
            persistence_service=service,
            snapshot_service=self._snapshot_service(),
            evidence_workspace_service=evidence_service,
            evidence_review_service=review_service,
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "analyze_persisted_evidence_CASE-1_SNAP-1": True,
            },
        )

        review_service.snapshot_evidence_checklist.assert_called_once_with(
            ANY,
            "F-TEST",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        evidence_service.analyze_case_evidence.assert_called_once()
        args = evidence_service.analyze_case_evidence.call_args
        self.assertEqual(args.kwargs["evidence_checklist"], checklist)
        text = log_text(fake)
        self.assertIn("SNAP-1", text)
        self.assertIn("DOC-PERSISTED-77", text)
        self.assertIn("Persisted GSTR-2B source", text)
        self.assertNotIn("session-only", text)

    def test_confirm_persists_snapshot_bound_review_and_refreshes_history(self):
        evidence_ref = self._evidence_ref("DOC-PERSISTED-77")
        service = self._case_service([self._notice(), evidence_ref])
        candidate = EvidenceCandidate(
            candidate_id="EC-001",
            evidence_id="evidence.e1",
            document_id="DOC-PERSISTED-77",
            source_text="Persisted GSTR-2B source",
            source_page=2,
            source_origin=SourceTextOrigin.EMBEDDED,
            source_verification=SourceVerificationStatus.VERIFIED,
        )
        intake = EvidenceIntakeResult(
            status=EvidenceIntakeStatus.SUCCESS,
            candidates=[candidate],
        )
        workspace = Mock()
        workspace.document_refs = [evidence_ref]
        workspace.intake_result = intake
        evidence_service = Mock()
        evidence_service.analyze_case_evidence.return_value = workspace

        saved = self._review_ref()
        review_service = self._review_service()
        review_service.save_review.return_value = saved
        review_service.list_reviews.side_effect = [[], [saved]]
        workspace_key = (
            "persisted:CASE-1:SNAP-1:DOC-PERSISTED-77"
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(evidence_review=True)],
            persistence_service=service,
            snapshot_service=self._snapshot_service(),
            evidence_workspace_service=evidence_service,
            evidence_review_service=review_service,
            reopen_result=self._reopened(),
            text_values={
                f"durable_evidence_note_{workspace_key}_EC-001": (
                    "Checked against portal"
                )
            },
            button_values={
                "open_saved_case_CASE-1": True,
                "analyze_persisted_evidence_CASE-1_SNAP-1": True,
                f"durable_confirm_{workspace_key}_EC-001": True,
            },
        )

        review_service.save_review.assert_called_once()
        kwargs = review_service.save_review.call_args.kwargs
        self.assertEqual(kwargs["case_id"], "CASE-1")
        self.assertEqual(kwargs["snapshot_id"], "SNAP-1")
        self.assertIs(kwargs["candidate"], candidate)
        self.assertIs(
            kwargs["decision"],
            EvidenceReviewStatus.CONFIRMED,
        )
        self.assertEqual(
            kwargs["reviewer_note"],
            "Checked against portal",
        )
        self.assertIsNotNone(kwargs["reviewed_at"].tzinfo)
        text = log_text(fake)
        self.assertIn("saved_evidence_review_id", text)
        self.assertIn("EREV-1", text)
        self.assertIn("Durable evidence review history", text)

    def test_durable_review_history_can_load_encrypted_details(self):
        evidence_ref = self._evidence_ref("DOC-PERSISTED-77")
        service = self._case_service([self._notice(), evidence_ref])
        saved = self._review_ref()
        review_service = self._review_service()
        review_service.list_reviews.return_value = [saved]
        review_service.load_review.return_value = LoadedEvidenceReview(
            metadata=saved,
            payload={
                "candidate": {
                    "candidate_id": "EC-OLD",
                    "source_text": "Historical encrypted quote",
                    "source_origin": "embedded",
                    "source_verification": "verified",
                },
                "reviewer_note": "Historical private note",
                "reviewed_at": saved.reviewed_at.isoformat(),
                "reviewed_by": saved.reviewed_by,
            },
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(evidence_review=True)],
            persistence_service=service,
            snapshot_service=self._snapshot_service(),
            evidence_review_service=review_service,
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "view_evidence_review_EREV-1": True,
            },
        )

        review_service.load_review.assert_called_once_with(
            ANY,
            "F-TEST",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            review_id="EREV-1",
        )
        text = log_text(fake)
        self.assertIn("Historical encrypted quote", text)
        self.assertIn("Historical private note", text)

    def test_persisted_evidence_analysis_failure_is_generic(self):
        evidence_ref = self._evidence_ref()
        service = self._case_service([self._notice(), evidence_ref])
        evidence_service = Mock()
        evidence_service.analyze_case_evidence.side_effect = RuntimeError(
            "private llm/storage detail"
        )

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(evidence_review=True)],
            persistence_service=service,
            snapshot_service=self._snapshot_service(),
            evidence_workspace_service=evidence_service,
            evidence_review_service=self._review_service(),
            reopen_result=self._reopened(),
            button_values={
                "open_saved_case_CASE-1": True,
                "analyze_persisted_evidence_CASE-1_SNAP-1": True,
            },
        )

        text = log_text(fake)
        self.assertIn(
            "Persisted evidence could not be analyzed",
            text,
        )
        self.assertNotIn("private llm/storage detail", text)



class CaseWorkQueueUiTests(unittest.TestCase):
    def _firm(self, *, update=False):
        permissions = {
            AccessPermission.CASE_READ,
            AccessPermission.DOCUMENT_READ,
        }
        if update:
            permissions.add(AccessPermission.CASE_UPDATE)
        return AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset(permissions),
        )

    def _case(self, *, status=CaseStatus.INTAKE):
        return CaseRecord(
            case_id="CASE-URGENT",
            firm_id="F-TEST",
            client_id="CLIENT-1",
            registration_id=None,
            title="Urgent notice",
            status=status,
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            response_deadline=date(2026, 8, 29),
            closed_at=(
                datetime(2026, 9, 20, tzinfo=timezone.utc)
                if status is CaseStatus.CLOSED
                else None
            ),
        )

    def _work_item(self, *, status=CaseStatus.INTAKE):
        return CaseWorkItem(
            case_id="CASE-URGENT",
            client_id="CLIENT-1",
            client_name="Acme Private Limited",
            title="Urgent notice",
            status=status,
            response_deadline=date(2026, 8, 29),
            days_remaining=(
                None if status is CaseStatus.CLOSED else -1
            ),
            deadline_status=(
                WorkQueueDeadlineStatus.CLOSED
                if status is CaseStatus.CLOSED
                else WorkQueueDeadlineStatus.OVERDUE
            ),
            assigned_to=None,
            reviewer_id=None,
        )

    def _service(self, *, status=CaseStatus.INTAKE):
        service = Mock()
        item = self._work_item(status=status)
        case = self._case(status=status)
        service.list_case_work_queue.return_value = [item]
        service.list_cases.return_value = [case]
        service.list_clients.return_value = []
        return service, item, case

    def test_read_only_queue_renders_priority_without_update_controls(self):
        service, item, _ = self._service()
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=False)],
            persistence_service=service,
        )

        self.assertIn("Case work queue", headers(fake))
        text = log_text(fake)
        self.assertIn(item.client_name, text)
        self.assertIn("overdue", text)
        self.assertIn("-1", text)
        self.assertIn(
            "cannot update case operations",
            text,
        )
        service.list_case_work_queue.assert_called_once_with(
            ANY,
            "F-TEST",
            today=TODAY,
        )
        service.list_assignable_user_ids.assert_not_called()
        service.update_case_operations.assert_not_called()

    def test_queue_renders_professional_attention_without_reordering(self):
        service, item, _ = self._service()
        professional = Mock()
        professional.list_case_attention_queue.return_value = [
            ProfessionalQueueItem(
                work_item=item,
                attention_codes=(
                    CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,
                    CaseAttentionCode.DRAFT_AWAITING_REVIEW,
                ),
                attention_workspaces=(
                    CaseWorkspace.LEGAL_RESEARCH,
                    CaseWorkspace.DRAFT,
                ),
            )
        ]

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=False)],
            persistence_service=service,
            professional_workbench_service=professional,
        )

        professional.list_case_attention_queue.assert_called_once_with(
            ANY,
            "F-TEST",
            today=TODAY,
        )
        text = log_text(fake)
        self.assertIn("legal_research_unresolved", text)
        self.assertIn("draft_awaiting_review", text)
        self.assertIn("legal_research", text)
        self.assertIn("draft", text)
        self.assertIn("Needs attention", text)
        self.assertIn("not a priority score or legal verdict", text)
        service.update_case_operations.assert_not_called()

    def test_focus_queue_case_moves_it_to_saved_cases(self):
        service, item, _ = self._service()
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=False)],
            persistence_service=service,
            button_values={
                f"focus_queue_case_{item.case_id}": True,
            },
        )

        self.assertEqual(
            fake.session_state["_dwaar_focused_case_id"],
            item.case_id,
        )
        self.assertIn(
            "Open saved case",
            log_text(fake),
        )

    def test_update_user_can_save_controlled_case_operations(self):
        service, item, original_case = self._service()
        service.allowed_case_status_targets.return_value = (
            CaseStatus.INTAKE,
            CaseStatus.ANALYZED,
        )
        service.list_assignable_user_ids.return_value = [
            "OIDC-ASSIGNEE",
            "OIDC-REVIEWER",
        ]
        updated = CaseRecord(
            case_id=original_case.case_id,
            firm_id=original_case.firm_id,
            client_id=original_case.client_id,
            registration_id=None,
            title=original_case.title,
            status=CaseStatus.ANALYZED,
            proceeding_type=original_case.proceeding_type,
            notice_form=original_case.notice_form,
            opened_at=original_case.opened_at,
            response_deadline=date(2026, 10, 1),
            assigned_to="OIDC-ASSIGNEE",
            reviewer_id="OIDC-REVIEWER",
        )
        service.update_case_operations.return_value = updated

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=True)],
            persistence_service=service,
            selectbox_values={
                f"case_ops_status_{item.case_id}": "analyzed",
                f"case_ops_assignee_{item.case_id}": "OIDC-ASSIGNEE",
                f"case_ops_reviewer_{item.case_id}": "OIDC-REVIEWER",
            },
            text_values={
                f"case_ops_deadline_{item.case_id}": "2026-10-01",
            },
            button_values={
                f"save_case_ops_{item.case_id}": True,
            },
        )

        service.update_case_operations.assert_called_once()
        kwargs = service.update_case_operations.call_args.kwargs
        self.assertEqual(kwargs["case_id"], item.case_id)
        self.assertIs(kwargs["status"], CaseStatus.ANALYZED)
        self.assertEqual(
            kwargs["response_deadline"],
            date(2026, 10, 1),
        )
        self.assertEqual(kwargs["assigned_to"], "OIDC-ASSIGNEE")
        self.assertEqual(kwargs["reviewer_id"], "OIDC-REVIEWER")
        self.assertIsNotNone(kwargs["updated_at"].tzinfo)
        self.assertIn("updated_case_id", log_text(fake))
        self.assertEqual(
            fake.session_state["_dwaar_focused_case_id"],
            item.case_id,
        )

    def test_invalid_deadline_does_not_call_update(self):
        service, item, _ = self._service()
        service.allowed_case_status_targets.return_value = (
            CaseStatus.INTAKE,
        )
        service.list_assignable_user_ids.return_value = []

        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=True)],
            persistence_service=service,
            text_values={
                f"case_ops_deadline_{item.case_id}": "01/10/2026",
            },
            button_values={
                f"save_case_ops_{item.case_id}": True,
            },
        )

        self.assertIn(
            "Response deadline must use YYYY-MM-DD",
            log_text(fake),
        )
        service.update_case_operations.assert_not_called()

    def test_closed_case_is_visible_but_has_no_update_controls(self):
        service, item, _ = self._service(status=CaseStatus.CLOSED)
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=True)],
            persistence_service=service,
        )
        self.assertIn(
            "Closed cases are terminal",
            log_text(fake),
        )
        service.allowed_case_status_targets.assert_not_called()
        service.list_assignable_user_ids.assert_not_called()
        service.update_case_operations.assert_not_called()

    def test_queue_failure_is_generic(self):
        service, _, _ = self._service()
        service.list_case_work_queue.side_effect = RuntimeError(
            "private database detail"
        )
        fake, *_ = run_app(
            upload=False,
            available_firms=[self._firm(update=False)],
            persistence_service=service,
        )
        text = log_text(fake)
        self.assertIn("case work queue could not be loaded", text)
        self.assertNotIn("private database detail", text)


class ClientWorkspaceUiTests(unittest.TestCase):
    def _service(self):
        service = Mock()
        client = Client(
            "CLIENT-1",
            "F-TEST",
            "Acme Private Limited",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        registration = TaxRegistration(
            "REG-1",
            client.client_id,
            "IN-GST",
            "GSTIN",
            "06ABCDE1234F1Z5",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        older = CaseRecord(
            case_id="CASE-OLD",
            firm_id="F-TEST",
            client_id=client.client_id,
            registration_id=registration.registration_id,
            title="Older DRC-01",
            status=CaseStatus.INTAKE,
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        newer = CaseRecord(
            case_id="CASE-NEW",
            firm_id="F-TEST",
            client_id=client.client_id,
            registration_id=registration.registration_id,
            title="Newer DRC-01",
            status=CaseStatus.ANALYZED,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            opened_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        service.list_clients.return_value = [client]
        service.list_registrations.return_value = [registration]
        service.list_cases.return_value = [newer, older]
        service.get_client_workspace.return_value = ClientWorkspace(
            client=client,
            registrations=[registration],
            cases=[newer, older],
        )
        return service, client, registration, newer, older

    def test_client_workspace_renders_registration_and_notice_history(self):
        service, client, registration, newer, older = self._service()
        fake, *_ = run_app(
            upload=False,
            persistence_service=service,
        )

        self.assertIn("Client workspace", headers(fake))
        text = log_text(fake)
        self.assertIn(client.display_name, text)
        self.assertIn(registration.identifier_value, text)
        self.assertIn(newer.case_id, text)
        self.assertIn(older.case_id, text)
        service.get_client_workspace.assert_called_once_with(
            ANY,
            "F-TEST",
            client_id=client.client_id,
        )

    def test_focus_from_client_workspace_moves_case_to_saved_case_selector(self):
        service, client, _, newer, older = self._service()
        selected_case_label = f"{older.title} — {older.case_id}"
        fake, *_ = run_app(
            upload=False,
            persistence_service=service,
            selectbox_values={
                "dwaar_client_workspace_selector": (
                    f"{client.display_name} — {client.client_id}"
                ),
                f"dwaar_client_case_selector_{client.client_id}": (
                    selected_case_label
                ),
            },
            button_values={
                f"focus_client_case_{older.case_id}": True,
            },
        )

        self.assertEqual(
            fake.session_state["_dwaar_focused_case_id"],
            older.case_id,
        )
        saved_case_selects = [
            call
            for call in calls_named(fake, "selectbox")
            if call[2].get("key") == "dwaar_saved_case_selector"
        ]
        self.assertEqual(len(saved_case_selects), 1)
        saved_options = saved_case_selects[0][1][1]
        self.assertTrue(saved_options[0].endswith(older.case_id))
        self.assertIn(
            "Open saved case",
            log_text(fake),
        )

    def test_read_only_case_access_still_gets_client_workspace(self):
        service, *_ = self._service()
        firm = AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset({AccessPermission.CASE_READ}),
        )
        fake, *_ = run_app(
            upload=False,
            available_firms=[firm],
            persistence_service=service,
        )
        self.assertIn("Client workspace", headers(fake))
        self.assertIn(
            "new notice upload requires CASE_CREATE",
            log_text(fake),
        )

    def test_client_workspace_failure_does_not_leak_internal_detail(self):
        service, *_ = self._service()
        service.get_client_workspace.side_effect = RuntimeError(
            "private sqlite detail"
        )
        fake, *_ = run_app(
            upload=False,
            persistence_service=service,
        )
        text = log_text(fake)
        self.assertIn("Client history could not be loaded", text)
        self.assertNotIn("private sqlite detail", text)


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
            "mode": f"intake_client_mode_{save_key}",
            "existing_client": f"intake_existing_client_{save_key}",
            "existing_registration": (
                f"intake_existing_registration_{save_key}"
            ),
        }

    def test_analysis_renders_save_panel_without_persisting(self):
        fake, *_ = run_app()
        self.assertIn("Save as intake case", headers(fake))
        self.assertGreaterEqual(
            fake.persistence_service_mock.call_count,
            1,
        )
        self.assertIn(
            "Dwaar never auto-merges clients by name or GSTIN",
            log_text(fake),
        )

    def test_save_uses_structured_classification_and_authenticated_firm(self):
        keys = self._save_keys()
        service = Mock()
        saved_case = Mock()
        saved_case.case_id = "CASE-SAVED-1"
        saved_case.status.value = "intake"
        saved_case.client_id = "CLIENT-NEW"
        saved_case.registration_id = "REG-NEW"
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
            4,
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

    def test_existing_client_mode_reuses_selected_client_and_registration(self):
        keys = self._save_keys()
        service = Mock()
        client = Client(
            "CLIENT-EXISTING",
            "F-TEST",
            "Existing Taxpayer",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        registration = TaxRegistration(
            "REG-EXISTING",
            client.client_id,
            "IN-GST",
            "GSTIN",
            "06ABCDE1234F1Z5",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        service.list_cases.return_value = []
        service.list_clients.return_value = [client]
        service.list_registrations.return_value = [registration]
        saved_case = Mock()
        saved_case.case_id = "CASE-REUSED"
        saved_case.status.value = "intake"
        saved_case.client_id = client.client_id
        saved_case.registration_id = registration.registration_id
        service.create_existing_client_case_intake.return_value = saved_case

        client_label = f"{client.display_name} — {client.client_id}"
        registration_label = (
            f"GSTIN: {registration.identifier_value} — "
            f"{registration.registration_id}"
        )
        fake, *_ = run_app(
            persistence_service=service,
            selectbox_values={
                keys["mode"]: "Existing client",
                keys["existing_client"]: client_label,
                keys["existing_registration"]: registration_label,
            },
            button_values={keys["button"]: True},
            text_values={keys["title"]: "Second notice"},
        )

        self.assertEqual(service.list_clients.call_count, 2)
        service.list_registrations.assert_called_once_with(
            ANY,
            "F-TEST",
            client_id="CLIENT-EXISTING",
        )
        service.create_existing_client_case_intake.assert_called_once()
        kwargs = (
            service.create_existing_client_case_intake.call_args.kwargs
        )
        self.assertEqual(kwargs["client_id"], "CLIENT-EXISTING")
        self.assertEqual(kwargs["registration_id"], "REG-EXISTING")
        self.assertEqual(kwargs["case_title"], "Second notice")
        service.create_case_intake.assert_not_called()
        self.assertIn("CASE-REUSED", log_text(fake))
        self.assertIn("CLIENT-EXISTING", log_text(fake))

    def test_existing_client_can_explicitly_choose_no_registration(self):
        keys = self._save_keys()
        service = Mock()
        client = Client(
            "CLIENT-EXISTING",
            "F-TEST",
            "Existing Taxpayer",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        service.list_cases.return_value = []
        service.list_clients.return_value = [client]
        service.list_registrations.return_value = []
        saved_case = Mock()
        saved_case.case_id = "CASE-REUSED"
        saved_case.status.value = "intake"
        saved_case.client_id = client.client_id
        saved_case.registration_id = None
        service.create_existing_client_case_intake.return_value = saved_case

        fake, *_ = run_app(
            persistence_service=service,
            selectbox_values={
                keys["mode"]: "Existing client",
                keys["existing_client"]: (
                    f"{client.display_name} — {client.client_id}"
                ),
                keys["existing_registration"]: "No registration",
            },
            button_values={keys["button"]: True},
            text_values={keys["title"]: "Registration-free matter"},
        )

        kwargs = (
            service.create_existing_client_case_intake.call_args.kwargs
        )
        self.assertIsNone(kwargs["registration_id"])
        self.assertIn("CASE-REUSED", log_text(fake))

    def test_new_client_remains_default_even_when_existing_clients_exist(self):
        keys = self._save_keys()
        service = Mock()
        service.list_cases.return_value = []
        service.list_clients.return_value = [
            Client(
                "CLIENT-EXISTING",
                "F-TEST",
                "Existing Taxpayer",
                datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
        ]
        saved_case = Mock()
        saved_case.case_id = "CASE-NEW"
        saved_case.status.value = "intake"
        saved_case.client_id = "CLIENT-NEW"
        saved_case.registration_id = None
        service.create_case_intake.return_value = saved_case

        run_app(
            persistence_service=service,
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "Another Taxpayer",
                keys["title"]: "New taxpayer matter",
            },
        )

        service.create_case_intake.assert_called_once()
        service.create_existing_client_case_intake.assert_not_called()

    def test_create_only_user_is_not_allowed_to_browse_existing_clients(self):
        keys = self._save_keys()
        service = Mock()
        saved_case = Mock()
        saved_case.case_id = "CASE-NEW"
        saved_case.status.value = "intake"
        saved_case.client_id = "CLIENT-NEW"
        saved_case.registration_id = None
        service.create_case_intake.return_value = saved_case
        firm = AvailableFirmAccess(
            firm_id="F-TEST",
            display_name="Test Firm",
            permissions=frozenset({AccessPermission.CASE_CREATE}),
        )

        fake, *_ = run_app(
            available_firms=[firm],
            persistence_service=service,
            button_values={keys["button"]: True},
            text_values={
                keys["client"]: "New Client",
                keys["title"]: "Matter",
            },
        )

        service.list_clients.assert_not_called()
        service.list_registrations.assert_not_called()
        service.create_case_intake.assert_called_once()
        self.assertNotIn("Existing client", log_text(fake))

    def test_saved_notice_does_not_create_duplicate_on_rerun(self):
        keys = self._save_keys()
        shared_state = {}
        first_service = Mock()
        saved_case = Mock()
        saved_case.case_id = "CASE-SAVED-1"
        saved_case.status.value = "intake"
        saved_case.client_id = "CLIENT-NEW"
        saved_case.registration_id = None
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
            "DRC-01 — Section 73 — ITC",
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
