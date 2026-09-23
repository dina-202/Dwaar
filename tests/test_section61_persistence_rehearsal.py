"""Persistence rehearsal for the Section 61 / ASMT-10 specialist path.

This test uses the real SQLite repositories and encrypted object store. It
proves that a deep ASMT-10 analysis can be saved, reopened, used to create a
snapshot-bound verified legal brief, and retain itemized notice-evidence
targets/reviews across process-style repository re-instantiation.
"""

import hashlib
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fitz
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
)
from domain.models import (
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
    EvidenceReviewStatus,
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
    SourceTextOrigin,
    SourceVerificationStatus,
    SpecialistDraftResult,
    SupportLevel,
    ValidationStatus,
)
from domain.validation_engine import run_validation
from modules.analysis_snapshot_service import (
    load_analysis_snapshot,
    persist_analysis_snapshot,
)
from modules.authorized_evidence_review_service import (
    AuthorizedEvidenceReviewService,
)
from modules.authorized_legal_brief_service import AuthorizedLegalBriefService
from modules.encrypted_document_store import (
    EncryptedLocalDocumentStore,
    generate_storage_key,
)
from modules.evidence_review_persistence_service import load_evidence_review
from modules.legal_brief_service import load_legal_brief
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_evidence_review_repository import (
    LocalSQLiteEvidenceReviewRepository,
)
from modules.sqlite_legal_brief_repository import (
    LocalSQLiteLegalBriefRepository,
)


NOW = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "6" * 64)
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sample_notices"
    / "NOTICE_5_ASMT10_Synthetic.pdf"
)


def _fact(
    fact_id,
    fact_type,
    source_text,
    *,
    status=FactStatus.CONFIRMED,
    role=FactRole.NONE,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim=source_text,
        status=status,
        source_text=source_text,
        source_page=1,
        allowed_in_draft=(
            DraftPermission.CONDITIONAL
            if status is FactStatus.ALLEGED
            else DraftPermission.YES
        ),
        fact_type=fact_type,
        fact_role=role,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )


def _analysis():
    facts = [
        _fact("F-NOTICE", FactType.NOTICE_DATE, "Date: 01-09-2026"),
        _fact("F-PERIOD", FactType.TAX_PERIOD, "FY 2025-26"),
        _fact(
            "F-DISC",
            FactType.DEPARTMENT_ALLEGATION,
            (
                "Discrepancy 1: Department states that taxable turnover "
                "reported in GSTR-3B differs from available records."
            ),
            status=FactStatus.ALLEGED,
        ),
        _fact(
            "F-RESPONSE",
            FactType.DOCUMENT_DETAIL,
            (
                "Under Section 61, furnish an explanation within fifteen "
                "days from the date of receipt of this notice."
            ),
            role=FactRole.RESPONSE_PERIOD,
        ),
        _fact(
            "F-REQ",
            FactType.REQUESTED_DOCUMENT,
            "1. Purchase register for FY 2025-26",
        ),
        _fact(
            "F-ANN",
            FactType.REFERENCED_ANNEXURE,
            "Annexure A - discrepancy computation",
        ),
    ]
    classification = NoticeClassification(
        notice_family=NoticeFamily.ASSESSMENT_SCRUTINY,
        notice_form=NoticeForm.ASMT_10,
        proceeding_type=ProceedingType.GST_SEC61_SCRUTINY,
        support_level=SupportLevel.DEEP_WORKFLOW,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=[
            "FORM GST ASMT-10 marker present",
            "Section 61 scrutiny marker present",
            "explicit discrepancy wording present",
        ],
    )
    extraction = FactExtractionResult(
        facts=facts,
        status=FactExtractionStatus.SUCCESS,
    )
    deadline = DeadlineResult(
        notice_date=date(2026, 9, 1),
        service_date=None,
        response_period_days=15,
        response_deadline=None,
        deadline_confidence=DeadlineConfidence.UNKNOWN,
        deadline_status=DeadlineStatus.UNKNOWN,
        days_remaining=None,
        hearing_date=None,
        hearing_status=HearingStatus.NOT_SCHEDULED,
        portal_verification_required=True,
        notes=[
            "Response period is notice-grounded; service/receipt date is "
            "not independently verified."
        ],
    )
    preflight = PreflightResult(
        fact_extraction_status=FactExtractionStatus.SUCCESS,
        communication_identifier_status=(
            CommunicationIdentifierStatus.NEITHER_FOUND
        ),
        portal_verification_required=True,
        authority_details_status=AuthorityDetailsStatus.MISSING,
        authority_verification_required=True,
        stated_due_date_fact_ids=[],
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
        hearing_fact_ids=[],
        requested_document_fact_ids=["F-REQ"],
        referenced_annexure_fact_ids=["F-ANN"],
    )
    validation = run_validation(
        classification,
        extraction,
        preflight,
        [],
        deadline,
    )
    draft = SpecialistDraftResult(
        status=DraftGenerationStatus.SUCCESS,
        draft_eligibility=validation.draft_eligibility,
        sections=[
            DraftSection(
                section_id="sec61_scrutiny.s1",
                title="Scrutiny working paper",
                rendered_text="CA working paper.",
            ),
            DraftSection(
                section_id="sec61_scrutiny.s2",
                title="Discrepancy-by-discrepancy response matrix",
                rendered_text="Discrepancy review matrix.",
            ),
            DraftSection(
                section_id="sec61_scrutiny.s3",
                title="Reviewable ASMT-11 explanation",
                rendered_text="Conditional ASMT-11 working explanation.",
            ),
        ],
        unresolved_requirements=[
            item
            for item in validation.requirements
            if item.status.value
            in {"missing", "unknown", "requires_verification"}
        ],
        evidence_checklist=list(validation.evidence_checklist),
        review_requirements=list(validation.review_requirements),
        post_validation=DraftPostValidationResult(
            overall_status=ValidationStatus.PASS,
            checks=[],
        ),
        failure_code=None,
        error_message=None,
    )
    return Phase2AnalysisResult(
        classification=classification,
        extraction_result=extraction,
        deadline_result=deadline,
        preflight_result=preflight,
        arithmetic_results=[],
        validation_result=validation,
        draft_result=draft,
        triage_summary=None,
    )


def _pdf(text):
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


class Section61PersistenceRehearsalTests(unittest.TestCase):
    def test_saved_section61_history_reopens_with_law_and_itemized_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = str(root / "dwaar.db")
            object_root = root / "objects"
            key = AESGCM.generate_key(bit_length=256)

            cases = LocalSQLiteCaseRepository(db_path)
            cases.create_firm(Firm("F-1", "Pilot Firm", NOW))
            cases.create_client(Client("C-1", "F-1", "Pilot Client", NOW))
            case = CaseRecord(
                case_id="CASE-ASMT",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Synthetic ASMT-10 scrutiny",
                status=CaseStatus.ANALYZED,
                proceeding_type=ProceedingType.GST_SEC61_SCRUTINY,
                notice_form=NoticeForm.ASMT_10,
                opened_at=NOW,
            )
            cases.create_case(case)

            store = EncryptedLocalDocumentStore(
                str(object_root),
                key,
                max_bytes=4 * 1024 * 1024,
            )
            notice_bytes = FIXTURE.read_bytes()
            notice_key = generate_storage_key()
            store.put(notice_key, notice_bytes)
            notice = StoredDocumentRef(
                document_id="DOC-NOTICE",
                case_id=case.case_id,
                kind=CaseDocumentKind.NOTICE,
                original_filename=FIXTURE.name,
                media_type="application/pdf",
                byte_size=len(notice_bytes),
                sha256_hex=hashlib.sha256(notice_bytes).hexdigest(),
                storage_key=notice_key,
                created_at=NOW,
            )
            cases.add_document_ref(notice)

            snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(db_path)
            snapshot = persist_analysis_snapshot(
                snapshot_repo,
                store,
                case_id=case.case_id,
                source_document=notice,
                analysis=_analysis(),
                actor_id=PRINCIPAL.user_id,
                created_at=NOW + timedelta(minutes=5),
            )

            # Re-instantiate DB and object-store adapters to simulate reopen.
            reopened_store = EncryptedLocalDocumentStore(
                str(object_root),
                key,
                max_bytes=4 * 1024 * 1024,
            )
            reopened_snapshots = LocalSQLiteAnalysisSnapshotRepository(
                db_path
            )
            loaded = load_analysis_snapshot(
                reopened_snapshots,
                reopened_store,
                snapshot_id=snapshot.snapshot_id,
                expected_source_document=notice,
            )
            self.assertEqual(
                loaded.payload["classification"]["proceeding_type"],
                "gst_sec61_scrutiny",
            )
            self.assertEqual(
                loaded.payload["preflight"]["requested_document_fact_ids"],
                ["F-REQ"],
            )
            self.assertEqual(
                loaded.payload["preflight"]["referenced_annexure_fact_ids"],
                ["F-ANN"],
            )
            self.assertEqual(
                loaded.payload["deadline"]["response_period_days"],
                15,
            )
            self.assertIsNone(
                loaded.payload["deadline"]["response_deadline"]
            )

            access = mock.Mock()
            access.get_grant.return_value = FirmAccessGrant(
                user_id=PRINCIPAL.user_id,
                firm_id="F-1",
                permissions=frozenset(
                    {
                        AccessPermission.CASE_READ,
                        AccessPermission.CASE_UPDATE,
                        AccessPermission.EVIDENCE_REVIEW,
                    }
                ),
                active=True,
            )
            case_service = mock.Mock()
            case_service.get_case.return_value = case
            snapshot_service = mock.Mock()
            snapshot_service.list_snapshot_history.return_value = [snapshot]
            snapshot_service.load_snapshot.return_value = loaded

            legal_repo = LocalSQLiteLegalBriefRepository(db_path)
            legal_service = AuthorizedLegalBriefService(
                case_service,
                snapshot_service,
                access,
                legal_repo,
                reopened_store,
            )
            brief = legal_service.save_for_snapshot(
                PRINCIPAL,
                "F-1",
                case_id=case.case_id,
                snapshot_id=snapshot.snapshot_id,
                created_at=NOW + timedelta(minutes=10),
            )

            # Reopen the legal repository before reading the durable brief.
            reopened_legal_repo = LocalSQLiteLegalBriefRepository(db_path)
            reopened_legal = load_legal_brief(
                reopened_legal_repo,
                reopened_store,
                legal_brief_id=brief.legal_brief_id,
                expected_snapshot=snapshot,
            )
            self.assertEqual(
                reopened_legal.payload["proceeding_type"],
                "gst_sec61_scrutiny",
            )
            self.assertEqual(reopened_legal.payload["unresolved_topics"], [])
            self.assertEqual(
                {item["rule_key"] for item in reopened_legal.payload["matches"]},
                {
                    "cgst.s61.scrutiny_process",
                    "cgst.r99.asmt_forms",
                },
            )
            self.assertEqual(
                reopened_legal.payload["questions"][0]["status"],
                "source_verified_research_ready",
            )

            evidence_repo = LocalSQLiteEvidenceReviewRepository(db_path)
            evidence_service = AuthorizedEvidenceReviewService(
                case_service,
                snapshot_service,
                access,
                evidence_repo,
                reopened_store,
            )
            checklist = evidence_service.snapshot_evidence_checklist(
                PRINCIPAL,
                "F-1",
                case_id=case.case_id,
                snapshot_id=snapshot.snapshot_id,
            )
            self.assertEqual(len(checklist), 6)
            itemized_ids = {
                item.evidence_id
                for item in checklist
                if item.evidence_id.startswith("sec61_scrutiny.notice.")
            }
            self.assertEqual(
                itemized_ids,
                {
                    "sec61_scrutiny.notice.requested_document.F-REQ",
                    "sec61_scrutiny.notice.referenced_annexure.F-ANN",
                },
            )

            support_bytes = _pdf(
                "Purchase register FY 2025-26\n"
                "Synthetic supporting evidence for persistence rehearsal."
            )
            support_key = generate_storage_key()
            store.put(support_key, support_bytes)
            support = StoredDocumentRef(
                document_id="DOC-EVIDENCE",
                case_id=case.case_id,
                kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
                original_filename="purchase-register.pdf",
                media_type="application/pdf",
                byte_size=len(support_bytes),
                sha256_hex=hashlib.sha256(support_bytes).hexdigest(),
                storage_key=support_key,
                created_at=NOW + timedelta(minutes=15),
            )
            cases.add_document_ref(support)
            case_service.read_document.return_value = (
                support,
                support_bytes,
            )

            review = evidence_service.save_review(
                PRINCIPAL,
                "F-1",
                case_id=case.case_id,
                snapshot_id=snapshot.snapshot_id,
                candidate=EvidenceCandidate(
                    candidate_id="EC-ASMT-PURCHASE",
                    evidence_id=(
                        "sec61_scrutiny.notice.requested_document.F-REQ"
                    ),
                    document_id=support.document_id,
                    source_text="Purchase register FY 2025-26",
                    source_page=1,
                    source_origin=SourceTextOrigin.EMBEDDED,
                    source_verification=SourceVerificationStatus.VERIFIED,
                ),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note="Matched the exact requested purchase register.",
                reviewed_at=NOW + timedelta(minutes=20),
            )

            # Reopen review metadata and encrypted payload as a final
            # restart-style durability check.
            reopened_reviews = LocalSQLiteEvidenceReviewRepository(db_path)
            reopened_review = load_evidence_review(
                reopened_reviews,
                reopened_store,
                review_id=review.review_id,
            )
            self.assertEqual(
                reopened_review.metadata.evidence_id,
                "sec61_scrutiny.notice.requested_document.F-REQ",
            )
            self.assertIs(
                reopened_review.metadata.decision,
                EvidenceReviewStatus.CONFIRMED,
            )
            self.assertEqual(
                reopened_review.payload["reviewer_note"],
                "Matched the exact requested purchase register.",
            )


if __name__ == "__main__":
    unittest.main()
