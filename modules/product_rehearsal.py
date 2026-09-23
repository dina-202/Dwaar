"""Deterministic end-to-end product rehearsal for Dwaar Phase 3P.8.

This is an offline tour-readiness gate. It exercises the real local runtime
and persistence/service boundaries without calling an external LLM.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Tuple

import fitz

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseStatus,
    Firm,
)
from domain.draft_work_product_models import DraftReviewStatus
from domain.legal_knowledge_models import LegalTopic
from domain.legal_question_models import LegalQuestionStatus
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
    DraftGenerationStatus,
    DraftPermission,
    DraftPostValidationResult,
    DraftSection,
    EvidenceCandidate,
    EvidenceChecklistItem,
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
from modules.analysis_snapshot_service import (
    load_analysis_snapshot,
    persist_analysis_snapshot,
)
from modules.case_document_service import persist_pdf_document
from modules.case_intake_service import persist_new_case_intake
from modules.case_timeline import build_case_timeline
from modules.draft_work_product_service import (
    baseline_text_from_snapshot,
    persist_draft_version,
    transition_draft_review_status,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.evidence_review_persistence_service import (
    persist_evidence_review,
)
from modules.filing_service import persist_filing
from modules.legal_brief_service import persist_legal_brief
from modules.runtime_backup import (
    create_runtime_backup,
    restore_runtime_backup,
    verify_runtime_backup,
)
from modules.runtime_key_rotation import rehearse_document_key_rotation
from modules.runtime_storage_audit import audit_runtime_storage
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_draft_version_repository import (
    LocalSQLiteDraftVersionRepository,
)
from modules.sqlite_evidence_review_repository import (
    LocalSQLiteEvidenceReviewRepository,
)
from modules.sqlite_filing_repository import LocalSQLiteFilingRepository
from modules.sqlite_legal_brief_repository import (
    LocalSQLiteLegalBriefRepository,
)
from workflows.gst.legal_questions import build_gst_legal_question_plan
from workflows.gst.legal_research import (
    build_gst_legal_date_context,
    resolve_gst_legal_brief_from_context,
)


ACTOR = "OIDC-" + "7" * 64
REVIEWER = "OIDC-" + "8" * 64
APPROVER = "OIDC-" + "9" * 64
KEY_A = b"a" * 32
KEY_B = b"b" * 32
KEY_ID_A = "tour-key-a"
KEY_ID_B = "tour-key-b"


@dataclass(frozen=True)
class ProductRehearsalCheck:
    code: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ProductRehearsalReport:
    checks: Tuple[ProductRehearsalCheck, ...]

    @property
    def tour_ready(self) -> bool:
        return bool(self.checks) and all(item.passed for item in self.checks)


def _pdf(text: str) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


def _fact(
    fact_id: str,
    fact_type: FactType,
    source_text: str,
    *,
    role: FactRole = FactRole.NONE,
) -> ExtractedFact:
    return ExtractedFact(
        fact_id=fact_id,
        claim=source_text,
        status=FactStatus.CONFIRMED,
        source_text=source_text,
        source_page=1,
        allowed_in_draft=DraftPermission.CONDITIONAL,
        fact_type=fact_type,
        fact_role=role,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )


def _analysis_fixture() -> Phase2AnalysisResult:
    facts = [
        _fact(
            "F-NOTICE",
            FactType.NOTICE_DATE,
            "Notice dated 15/05/2024",
        ),
        _fact(
            "F-PERIOD",
            FactType.TAX_PERIOD,
            "FY 2022-23",
        ),
        _fact(
            "F-3B",
            FactType.STATED_AMOUNT,
            "GSTR-3B ITC claimed INR 100000",
            role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        ),
        _fact(
            "F-2B",
            FactType.STATED_AMOUNT,
            "GSTR-2B ITC reflected INR 90000",
            role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
        ),
    ]
    calculation = ArithmeticResult(
        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        status=ArithmeticStatus.PASS,
        source_fact_ids=["F-3B", "F-2B"],
        operand_values=[Decimal("100000"), Decimal("90000")],
        result=Decimal("10000"),
        formula="claimed - available",
        currency="INR",
        allowed_in_draft=DraftPermission.CONDITIONAL,
    )
    check = ValidationItem(
        check_id="tour.itc.reconciliation",
        status=ValidationStatus.WARNING,
        message="Invoice-level professional reconciliation required.",
        related_fact_ids=["F-3B", "F-2B"],
        related_calculation_types=[ArithmeticCalculationType.ITC_DIFFERENCE],
    )
    requirement = RequirementResult(
        requirement_id="tour.itc.evidence",
        requirement_text="Verify invoice-level ITC eligibility evidence.",
        status=RequirementStatus.REQUIRES_VERIFICATION,
        related_fact_ids=["F-3B", "F-2B"],
        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
    )
    evidence = [
        EvidenceChecklistItem(
            evidence_id="sec73_itc.e3",
            requirement_text="Invoice-level ITC reconciliation",
            status=EvidenceStatus.UNKNOWN,
        ),
        EvidenceChecklistItem(
            evidence_id="sec73_itc.e4",
            requirement_text="Supplier filing evidence",
            status=EvidenceStatus.UNKNOWN,
        ),
        EvidenceChecklistItem(
            evidence_id="sec73_itc.e5",
            requirement_text="Supplier payment proof",
            status=EvidenceStatus.UNKNOWN,
        ),
    ]
    review = ReviewRequirement(
        review_id="tour.ca.review",
        level=ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        reason="Professional review required before filing.",
        mandatory=True,
    )
    return Phase2AnalysisResult(
        classification=NoticeClassification(
            notice_family=NoticeFamily.DEMAND_ADJUDICATION,
            notice_form=NoticeForm.DRC_01,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            support_level=SupportLevel.DEEP_WORKFLOW,
            confidence=ClassificationConfidence.HIGH,
            classification_reasons=["DRC-01", "Section 73 ITC mismatch"],
        ),
        extraction_result=FactExtractionResult(
            facts=facts,
            status=FactExtractionStatus.SUCCESS,
        ),
        deadline_result=DeadlineResult(
            notice_date=date(2024, 5, 15),
            service_date=date(2024, 5, 15),
            response_period_days=30,
            response_deadline=date(2024, 6, 14),
            deadline_confidence=DeadlineConfidence.CONFIRMED,
            deadline_status=DeadlineStatus.PASSED,
            days_remaining=-831,
            hearing_date=None,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            portal_verification_required=True,
            notes=["Deterministic tour fixture."],
        ),
        preflight_result=PreflightResult(
            fact_extraction_status=FactExtractionStatus.SUCCESS,
            communication_identifier_status=CommunicationIdentifierStatus.RFN_PRESENT,
            portal_verification_required=True,
            authority_details_status=AuthorityDetailsStatus.PARTIAL,
            authority_verification_required=True,
            stated_due_date_fact_ids=[],
            parsed_stated_due_dates=[],
            unparsed_stated_due_date_fact_ids=[],
            deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
            hearing_fact_ids=[],
            requested_document_fact_ids=[],
            referenced_annexure_fact_ids=[],
        ),
        arithmetic_results=[calculation],
        validation_result=ValidationEngineResult(
            overall_status=ValidationStatus.WARNING,
            draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
            case_severity=None,
            checks=[check],
            requirements=[requirement],
            evidence_checklist=evidence,
            review_requirements=[review],
        ),
        draft_result=SpecialistDraftResult(
            status=DraftGenerationStatus.SUCCESS,
            draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
            sections=[
                DraftSection(
                    section_id="tour.s1",
                    title="Facts and reconciliation",
                    rendered_text=(
                        "The registered person submits that the alleged ITC "
                        "difference requires invoice-level verification."
                    ),
                ),
                DraftSection(
                    section_id="tour.s2",
                    title="Prayer",
                    rendered_text=(
                        "The response is submitted subject to professional "
                        "review and supporting evidence."
                    ),
                ),
            ],
            unresolved_requirements=[requirement],
            evidence_checklist=evidence,
            review_requirements=[review],
            post_validation=DraftPostValidationResult(
                overall_status=ValidationStatus.PASS,
                checks=[check],
            ),
            failure_code=None,
            error_message=None,
        ),
        triage_summary=TriageSummary(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            support_level=SupportLevel.DEEP_WORKFLOW,
            classification_confidence=ClassificationConfidence.HIGH,
            extraction_status=FactExtractionStatus.SUCCESS,
            portal_verification_required=True,
            authority_verification_required=True,
            communication_identifier_status=CommunicationIdentifierStatus.RFN_PRESENT,
            authority_details_status=AuthorityDetailsStatus.PARTIAL,
            deadline_status=DeadlineStatus.PASSED,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            requested_document_fact_ids=[],
            referenced_annexure_fact_ids=[],
            message="Tour fixture: ITC mismatch professional workflow.",
        ),
    )


def run_product_rehearsal(root_dir: str) -> ProductRehearsalReport:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    live = root / "live"
    live.mkdir(parents=True, exist_ok=True)
    db_path = live / "dwaar.db"
    object_root = live / "objects"
    backup_root = root / "backups"
    recovered_db = root / "recovered" / "dwaar.db"
    recovered_objects = root / "recovered" / "objects"
    rotated_db = root / "rotated" / "dwaar.db"
    rotated_objects = root / "rotated" / "objects"
    checks = []

    repo = LocalSQLiteCaseRepository(str(db_path))
    repo.create_firm(Firm("F-TOUR", "Dwaar Tour Firm", datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)))
    store = EncryptedLocalDocumentStore(str(object_root), KEY_A)
    opened = datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc)

    case = persist_new_case_intake(
        repo,
        store,
        firm_id="F-TOUR",
        client_name="Northstar Components Pvt Ltd",
        gstin="06AAAAA0000A1Z5",
        case_title="FY 2022-23 ITC mismatch — DRC-01",
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        response_deadline=date(2026, 6, 14),
        notice_filename="DRC-01_ITC_Mismatch.pdf",
        notice_payload=_pdf("DRC-01 Section 73 ITC mismatch FY 2022-23"),
        actor_id=ACTOR,
        opened_at=opened,
    )
    notice = [
        item
        for item in repo.list_document_refs(case.case_id)
        if item.kind is CaseDocumentKind.NOTICE
    ][0]
    checks.append(ProductRehearsalCheck("encrypted_intake", True, "Case and notice persisted."))

    analysis = _analysis_fixture()
    snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(str(db_path))
    snapshot = persist_analysis_snapshot(
        snapshot_repo,
        store,
        case_id=case.case_id,
        source_document=notice,
        analysis=analysis,
        actor_id=ACTOR,
        created_at=opened + timedelta(hours=1),
    )
    loaded_snapshot = load_analysis_snapshot(
        snapshot_repo,
        store,
        snapshot_id=snapshot.snapshot_id,
        expected_source_document=notice,
    )
    checks.append(ProductRehearsalCheck("analysis_snapshot", True, "Encrypted analysis snapshot round-tripped."))

    facts = analysis.extraction_result.facts
    date_context = build_gst_legal_date_context(facts)
    legal_result = resolve_gst_legal_brief_from_context(
        ProceedingType.GST_SEC73_ITC,
        date_context,
    )
    question_plan = build_gst_legal_question_plan(
        ProceedingType.GST_SEC73_ITC,
        facts,
        date_context,
    )
    legal_repo = LocalSQLiteLegalBriefRepository(str(db_path))
    notice_anchor = date_context.get(__import__("domain.legal_date_models", fromlist=["LegalDateBasis"]).LegalDateBasis.NOTICE_DATE)
    if notice_anchor is None:
        raise RuntimeError("tour rehearsal notice-date anchor is missing")
    legal = persist_legal_brief(
        legal_repo,
        store,
        case_id=case.case_id,
        snapshot=snapshot,
        result=legal_result,
        as_of_date=notice_anchor.effective_date,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        actor_id=ACTOR,
        created_at=opened + timedelta(hours=2),
        question_plan=question_plan,
    )
    mismatch = [
        item for item in question_plan.questions
        if item.question_id == "gst_sec73_itc.mismatch_verification"
    ][0]
    eligibility = [
        item for item in question_plan.questions
        if item.question_id == "gst_sec73_itc.eligibility"
    ][0]
    if mismatch.status is not LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY:
        raise RuntimeError("tour mismatch legal research is not ready")
    if eligibility.status is not LegalQuestionStatus.AUTHORITY_UNCURATED:
        raise RuntimeError("tour eligibility uncertainty boundary regressed")
    if LegalTopic.ITC_ELIGIBILITY not in legal_result.unresolved_topics:
        raise RuntimeError("tour final ITC eligibility must remain unresolved")
    checks.append(ProductRehearsalCheck("verified_legal_research", True, "Verified mismatch law preserved; final eligibility remains unresolved."))

    support = persist_pdf_document(
        repo,
        store,
        case_id=case.case_id,
        kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
        original_filename="Invoice_Reconciliation.pdf",
        payload=_pdf("Invoice reconciliation supports review item e3."),
        actor_id=ACTOR,
        created_at=opened + timedelta(hours=3),
    )
    evidence_repo = LocalSQLiteEvidenceReviewRepository(str(db_path))
    review = persist_evidence_review(
        evidence_repo,
        store,
        case_id=case.case_id,
        snapshot_id=snapshot.snapshot_id,
        candidate=EvidenceCandidate(
            candidate_id="EC-TOUR",
            evidence_id="sec73_itc.e3",
            document_id=support.document_id,
            source_text="Invoice reconciliation checked against purchase register.",
            source_page=1,
            source_origin=SourceTextOrigin.EMBEDDED,
            source_verification=SourceVerificationStatus.VERIFIED,
        ),
        decision=EvidenceReviewStatus.CONFIRMED,
        reviewer_note="Confirmed for rehearsal; no legal conclusion implied.",
        actor_id=REVIEWER,
        reviewed_at=opened + timedelta(hours=4),
    )
    if review.decision is not EvidenceReviewStatus.CONFIRMED:
        raise RuntimeError("tour evidence review did not persist")
    checks.append(ProductRehearsalCheck("human_evidence_review", True, "Snapshot-bound supporting evidence was human-confirmed."))

    baseline = baseline_text_from_snapshot(loaded_snapshot)
    draft_repo = LocalSQLiteDraftVersionRepository(str(db_path))
    working = persist_draft_version(
        draft_repo,
        store,
        case_id=case.case_id,
        source_snapshot_id=snapshot.snapshot_id,
        parent_draft_version_id=None,
        version_number=1,
        generated_baseline=True,
        draft_text=baseline,
        actor_id=ACTOR,
        created_at=opened + timedelta(hours=5),
    )
    reviewed = transition_draft_review_status(
        draft_repo,
        version=working,
        target_status=DraftReviewStatus.REVIEWED,
        actor_id=REVIEWER,
        occurred_at=opened + timedelta(hours=6),
    )
    approved = transition_draft_review_status(
        draft_repo,
        version=reviewed,
        target_status=DraftReviewStatus.APPROVED,
        actor_id=APPROVER,
        occurred_at=opened + timedelta(hours=7),
    )
    checks.append(ProductRehearsalCheck("draft_review_approval", True, "Draft was versioned, reviewed and approved."))

    current_case = repo.get_case(case.case_id)
    draft_case = replace(current_case, status=CaseStatus.DRAFT_REVIEW)
    repo.update_case_with_events(
        draft_case,
        [
            CaseEvent(
                event_id="EV-" + uuid.uuid4().hex,
                case_id=case.case_id,
                event_type=CaseEventType.CASE_STATUS_CHANGED,
                occurred_at=opened + timedelta(hours=7, minutes=1),
                actor_id=APPROVER,
                payload={
                    "from_status": current_case.status.value,
                    "to_status": CaseStatus.DRAFT_REVIEW.value,
                },
            )
        ],
    )

    filing_repo = LocalSQLiteFilingRepository(str(db_path))
    filing = persist_filing(
        filing_repo,
        draft_repo,
        store,
        case=draft_case,
        approved_draft_version_id=approved.draft_version_id,
        filing_reference="ARN-TOUR-2026-0001",
        filed_response_filename="DRC06_Filed_Response.pdf",
        filed_response_payload=_pdf("Filed DRC-06 professional response."),
        acknowledgement_filename="GST_Portal_Acknowledgement.pdf",
        acknowledgement_payload=_pdf("GST portal acknowledgement ARN-TOUR-2026-0001"),
        filed_at=opened + timedelta(hours=8),
        recorded_at=opened + timedelta(hours=8, minutes=5),
        actor_id=ACTOR,
    )
    if filing.acknowledgement_document_id is None:
        raise RuntimeError("tour acknowledgement was not recorded")
    checks.append(ProductRehearsalCheck("filing_acknowledgement", True, "Approved draft linked to filing and acknowledgement."))

    timeline = build_case_timeline(repo.list_events(case.case_id))
    event_types = {item.event_type for item in timeline}
    required_events = {
        CaseEventType.CASE_CREATED,
        CaseEventType.DOCUMENT_ADDED,
        CaseEventType.ANALYSIS_SAVED,
        CaseEventType.LEGAL_BRIEF_SAVED,
        CaseEventType.EVIDENCE_REVIEWED,
        CaseEventType.DRAFT_CREATED,
        CaseEventType.DRAFT_REVIEWED,
        CaseEventType.FILING_RECORDED,
    }
    if not required_events.issubset(event_types):
        raise RuntimeError("tour timeline is missing lifecycle events")
    checks.append(ProductRehearsalCheck("unified_timeline", True, f"Timeline contains {len(timeline)} audited events."))

    audit = audit_runtime_storage(
        db_path=str(db_path),
        object_root=str(object_root),
        document_key=KEY_A,
    )
    if not audit.consistent:
        raise RuntimeError("tour live storage is inconsistent")
    checks.append(ProductRehearsalCheck("live_storage", True, f"{audit.referenced_object_count} encrypted objects are consistent."))

    manifest = create_runtime_backup(
        db_path=str(db_path),
        object_root=str(object_root),
        backup_root=str(backup_root),
        backup_id="tour-backup-a",
        created_at=opened + timedelta(hours=9),
        document_key=KEY_A,
        document_key_id=KEY_ID_A,
    )
    verify_runtime_backup(
        str(backup_root / "tour-backup-a"),
        document_key=KEY_A,
        expected_document_key_id=KEY_ID_A,
    )
    restore_runtime_backup(
        str(backup_root / "tour-backup-a"),
        target_db_path=str(recovered_db),
        target_object_root=str(recovered_objects),
        document_key=KEY_A,
        expected_document_key_id=KEY_ID_A,
    )
    recovered_repo = LocalSQLiteCaseRepository(str(recovered_db))
    recovered = recovered_repo.get_case(case.case_id)
    if recovered is None or recovered.status is not CaseStatus.FILED:
        raise RuntimeError("tour recovered case is incomplete")
    recovered_audit = audit_runtime_storage(
        db_path=str(recovered_db),
        object_root=str(recovered_objects),
        document_key=KEY_A,
    )
    if not recovered_audit.consistent:
        raise RuntimeError("tour recovered runtime is inconsistent")
    checks.append(ProductRehearsalCheck("backup_recovery", True, f"Backup v{manifest.manifest_version} restored the filed case."))

    rotation = rehearse_document_key_rotation(
        source_db_path=str(db_path),
        source_object_root=str(object_root),
        old_document_key=KEY_A,
        old_document_key_id=KEY_ID_A,
        new_document_key=KEY_B,
        new_document_key_id=KEY_ID_B,
        target_db_path=str(rotated_db),
        target_object_root=str(rotated_objects),
    )
    rotated_audit = audit_runtime_storage(
        db_path=str(rotated_db),
        object_root=str(rotated_objects),
        document_key=KEY_B,
    )
    if not rotated_audit.consistent:
        raise RuntimeError("tour rotated runtime is inconsistent")
    checks.append(ProductRehearsalCheck("key_rotation", True, f"Rotated {rotation.object_count} encrypted objects into key generation B."))

    return ProductRehearsalReport(checks=tuple(checks))
