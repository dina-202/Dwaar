"""Tests for Phase 3L filing and acknowledgement lifecycle."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fitz
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisSnapshotRef,
)
from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
)
from domain.draft_work_product_models import DraftReviewStatus
from domain.fact_review_models import (
    FactReviewDecision,
    FactReviewRef,
)
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_filing_service import AuthorizedFilingService
from modules.draft_work_product_service import (
    persist_draft_version,
    transition_draft_review_status,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.filing_service import (
    FilingPersistenceError,
    attach_filing_acknowledgement,
    persist_filing,
)
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_draft_version_repository import (
    LocalSQLiteDraftVersionRepository,
)
from modules.sqlite_filing_repository import LocalSQLiteFilingRepository


NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
FILED_AT = NOW - timedelta(hours=1)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def pdf_bytes(text):
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


class FilingIntegrationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")

        self.case_repo = LocalSQLiteCaseRepository(self.db_path)
        self.case_repo.create_firm(Firm("F-1", "Firm", NOW))
        self.case_repo.create_client(Client("C-1", "F-1", "Client", NOW))
        self.case_repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.DRAFT_REVIEW,
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW - timedelta(days=10),
            )
        )
        self.notice = StoredDocumentRef(
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=100,
            sha256_hex="a" * 64,
            storage_key="objects/" + "a" * 32,
            created_at=NOW - timedelta(days=10),
        )
        self.case_repo.add_document_ref(self.notice)

        snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(self.db_path)
        self.snapshot = AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=10,
            sha256_hex="b" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=NOW - timedelta(days=2),
            created_by=PRINCIPAL.user_id,
        )
        snapshot_repo.save_snapshot(
            self.snapshot,
            CaseEvent(
                event_id="EV-SNAP",
                case_id="CASE-1",
                event_type=CaseEventType.ANALYSIS_SAVED,
                occurred_at=NOW - timedelta(days=2),
                actor_id=PRINCIPAL.user_id,
                payload={
                    "snapshot_id": "SNAP-1",
                    "source_document_id": "DOC-NOTICE",
                },
            ),
        )

        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=5 * 1024 * 1024,
        )
        self.draft_repo = LocalSQLiteDraftVersionRepository(self.db_path)
        working = persist_draft_version(
            self.draft_repo,
            self.store,
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            draft_text="## Response\n\nApproved professional response.",
            actor_id=PRINCIPAL.user_id,
            created_at=NOW - timedelta(days=1),
        )
        reviewed = transition_draft_review_status(
            self.draft_repo,
            version=working,
            target_status=DraftReviewStatus.REVIEWED,
            actor_id="OIDC-REVIEWER",
            occurred_at=NOW - timedelta(hours=4),
        )
        self.approved = transition_draft_review_status(
            self.draft_repo,
            version=reviewed,
            target_status=DraftReviewStatus.APPROVED,
            actor_id="OIDC-APPROVER",
            occurred_at=NOW - timedelta(hours=2),
        )
        self.filing_repo = LocalSQLiteFilingRepository(self.db_path)
        self.response_pdf = pdf_bytes("Actually filed response")
        self.ack_pdf = pdf_bytes("Portal acknowledgement")

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **overrides):
        values = {
            "case": self.case_repo.get_case("CASE-1"),
            "approved_draft_version_id": self.approved.draft_version_id,
            "filing_reference": "ARN-TEST-001",
            "filed_response_filename": "filed-response.pdf",
            "filed_response_payload": self.response_pdf,
            "acknowledgement_filename": None,
            "acknowledgement_payload": None,
            "filed_at": FILED_AT,
            "recorded_at": NOW,
            "actor_id": PRINCIPAL.user_id,
        }
        values.update(overrides)
        return persist_filing(
            self.filing_repo,
            self.draft_repo,
            self.store,
            **values,
        )


class FilingPersistenceTests(FilingIntegrationFixture):
    def test_first_filing_links_approved_draft_and_promotes_case_to_filed(self):
        filing = self.record()

        self.assertEqual(
            filing.approved_draft_version_id,
            self.approved.draft_version_id,
        )
        self.assertEqual(filing.filing_reference, "ARN-TEST-001")
        self.assertIs(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.FILED,
        )
        self.assertEqual(
            self.filing_repo.list_filings("CASE-1"),
            [filing],
        )

        docs = self.case_repo.list_document_refs("CASE-1")
        filed_docs = [
            item for item in docs
            if item.kind is CaseDocumentKind.FILED_RESPONSE
        ]
        self.assertEqual(len(filed_docs), 1)
        self.assertEqual(
            self.store.get(filed_docs[0].storage_key),
            self.response_pdf,
        )

        event_types = [
            item.event_type
            for item in self.case_repo.list_events("CASE-1")
        ]
        self.assertIn(CaseEventType.FILING_RECORDED, event_types)
        self.assertIn(CaseEventType.CASE_STATUS_CHANGED, event_types)
        filing_event = [
            item for item in self.case_repo.list_events("CASE-1")
            if item.event_type is CaseEventType.FILING_RECORDED
        ][0]
        self.assertEqual(filing_event.actor_id, PRINCIPAL.user_id)
        self.assertNotIn(
            "Approved professional response",
            repr(filing_event.payload),
        )

    def test_filing_with_acknowledgement_persists_both_artifacts(self):
        filing = self.record(
            acknowledgement_filename="ack.pdf",
            acknowledgement_payload=self.ack_pdf,
        )
        self.assertIsNotNone(filing.acknowledgement_document_id)
        self.assertEqual(filing.acknowledgement_added_at, NOW)
        self.assertEqual(
            filing.acknowledgement_added_by,
            PRINCIPAL.user_id,
        )
        docs = self.case_repo.list_document_refs("CASE-1")
        self.assertEqual(
            [item.kind for item in docs].count(
                CaseDocumentKind.FILED_RESPONSE
            ),
            1,
        )
        self.assertEqual(
            [item.kind for item in docs].count(
                CaseDocumentKind.ACKNOWLEDGEMENT
            ),
            1,
        )

    def test_supplemental_filing_while_filed_does_not_emit_status_change(self):
        self.record()
        before = len(
            [
                e for e in self.case_repo.list_events("CASE-1")
                if e.event_type is CaseEventType.CASE_STATUS_CHANGED
            ]
        )
        second = self.record(
            case=self.case_repo.get_case("CASE-1"),
            filing_reference="ARN-TEST-002",
            filed_at=NOW - timedelta(minutes=20),
            recorded_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(second.filing_reference, "ARN-TEST-002")
        self.assertIs(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.FILED,
        )
        after = len(
            [
                e for e in self.case_repo.list_events("CASE-1")
                if e.event_type is CaseEventType.CASE_STATUS_CHANGED
            ]
        )
        self.assertEqual(before, after)

    def test_hearing_case_can_record_supplemental_filing_without_status_regress(self):
        current = self.case_repo.get_case("CASE-1")
        self.case_repo.update_case(
            CaseRecord(
                **{
                    **current.__dict__,
                    "status": CaseStatus.HEARING,
                }
            )
        )
        filing = self.record(
            case=self.case_repo.get_case("CASE-1"),
        )
        self.assertEqual(filing.case_id, "CASE-1")
        self.assertIs(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.HEARING,
        )

    def test_disallowed_case_status_fails_before_new_artifact_write(self):
        current = self.case_repo.get_case("CASE-1")
        self.case_repo.update_case(
            CaseRecord(
                **{
                    **current.__dict__,
                    "status": CaseStatus.ANALYZED,
                }
            )
        )
        before = set(Path(self.object_root).glob("*.dwaar"))
        with self.assertRaisesRegex(ValueError, "does not permit"):
            self.record(case=self.case_repo.get_case("CASE-1"))
        self.assertEqual(
            set(Path(self.object_root).glob("*.dwaar")),
            before,
        )

    def test_approved_draft_from_another_case_is_rejected_before_storage(self):
        self.case_repo.create_case(
            CaseRecord(
                case_id="CASE-2",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Other matter",
                status=CaseStatus.DRAFT_REVIEW,
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW - timedelta(days=5),
            )
        )
        other_notice = StoredDocumentRef(
            document_id="DOC-NOTICE-2",
            case_id="CASE-2",
            kind=CaseDocumentKind.NOTICE,
            original_filename="other-notice.pdf",
            media_type="application/pdf",
            byte_size=100,
            sha256_hex="c" * 64,
            storage_key="objects/" + "c" * 32,
            created_at=NOW - timedelta(days=5),
        )
        self.case_repo.add_document_ref(other_notice)
        other_snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(
            self.db_path
        )
        other_snapshot = AnalysisSnapshotRef(
            snapshot_id="SNAP-2",
            case_id="CASE-2",
            source_document_id=other_notice.document_id,
            source_document_sha256=other_notice.sha256_hex,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=10,
            sha256_hex="d" * 64,
            storage_key="objects/" + "d" * 32,
            created_at=NOW - timedelta(hours=4),
            created_by=PRINCIPAL.user_id,
        )
        other_snapshot_repo.save_snapshot(
            other_snapshot,
            CaseEvent(
                event_id="EV-SNAP-2",
                case_id="CASE-2",
                event_type=CaseEventType.ANALYSIS_SAVED,
                occurred_at=other_snapshot.created_at,
                actor_id=PRINCIPAL.user_id,
                payload={
                    "snapshot_id": other_snapshot.snapshot_id,
                    "source_document_id": other_notice.document_id,
                },
            ),
        )

        other_working = persist_draft_version(
            self.draft_repo,
            self.store,
            case_id="CASE-2",
            source_snapshot_id="SNAP-2",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            draft_text="Other case professional response.",
            actor_id=PRINCIPAL.user_id,
            created_at=NOW - timedelta(hours=3),
        )
        other_reviewed = transition_draft_review_status(
            self.draft_repo,
            version=other_working,
            target_status=DraftReviewStatus.REVIEWED,
            actor_id="OIDC-OTHER-REVIEWER",
            occurred_at=NOW - timedelta(hours=2),
        )
        other_approved = transition_draft_review_status(
            self.draft_repo,
            version=other_reviewed,
            target_status=DraftReviewStatus.APPROVED,
            actor_id="OIDC-OTHER-APPROVER",
            occurred_at=NOW - timedelta(hours=1, minutes=30),
        )

        before_objects = set(Path(self.object_root).glob("*.dwaar"))
        with self.assertRaisesRegex(
            LookupError,
            "approved draft version does not exist",
        ):
            self.record(
                approved_draft_version_id=other_approved.draft_version_id,
            )

        self.assertEqual(
            set(Path(self.object_root).glob("*.dwaar")),
            before_objects,
        )
        self.assertEqual(
            self.filing_repo.list_filings("CASE-1"),
            [],
        )


    def test_unapproved_draft_is_rejected(self):
        working = persist_draft_version(
            self.draft_repo,
            self.store,
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=self.approved.draft_version_id,
            version_number=2,
            generated_baseline=False,
            draft_text="Unapproved later edit",
            actor_id=PRINCIPAL.user_id,
            created_at=NOW,
        )
        with self.assertRaisesRegex(ValueError, "approved draft"):
            self.record(
                approved_draft_version_id=working.draft_version_id,
            )

    def test_duplicate_filing_reference_is_rejected_before_new_artifact(self):
        self.record()
        before = set(Path(self.object_root).glob("*.dwaar"))
        with self.assertRaisesRegex(ValueError, "already recorded"):
            self.record(
                case=self.case_repo.get_case("CASE-1"),
            )
        self.assertEqual(
            set(Path(self.object_root).glob("*.dwaar")),
            before,
        )

    def test_future_filing_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "later than"):
            self.record(
                filed_at=NOW + timedelta(minutes=1),
                recorded_at=NOW,
            )

    def test_repository_failure_rolls_back_new_artifacts(self):
        repository = mock.Mock()
        repository.list_filings.return_value = []
        repository.save_filing.side_effect = RuntimeError("db failed")
        before = set(Path(self.object_root).glob("*.dwaar"))
        with self.assertRaises(FilingPersistenceError):
            persist_filing(
                repository,
                self.draft_repo,
                self.store,
                case=self.case_repo.get_case("CASE-1"),
                approved_draft_version_id=(
                    self.approved.draft_version_id
                ),
                filing_reference="ARN-ROLLBACK",
                filed_response_filename="filed.pdf",
                filed_response_payload=self.response_pdf,
                acknowledgement_filename="ack.pdf",
                acknowledgement_payload=self.ack_pdf,
                filed_at=FILED_AT,
                recorded_at=NOW,
                actor_id=PRINCIPAL.user_id,
            )
        self.assertEqual(
            set(Path(self.object_root).glob("*.dwaar")),
            before,
        )


class FilingAcknowledgementTests(FilingIntegrationFixture):
    def test_late_acknowledgement_is_encrypted_and_audited(self):
        filing = self.record()
        updated = attach_filing_acknowledgement(
            self.filing_repo,
            self.store,
            filing=filing,
            acknowledgement_filename="ack-later.pdf",
            acknowledgement_payload=self.ack_pdf,
            actor_id="OIDC-ACK-USER",
            added_at=NOW + timedelta(hours=1),
        )
        self.assertIsNotNone(updated.acknowledgement_document_id)
        self.assertEqual(
            updated.acknowledgement_added_by,
            "OIDC-ACK-USER",
        )
        stored = self.filing_repo.get_filing(filing.filing_id)
        self.assertEqual(stored, updated)

        events = self.case_repo.list_events("CASE-1")
        ack_events = [
            item
            for item in events
            if item.event_type
            is CaseEventType.FILING_ACKNOWLEDGEMENT_RECORDED
        ]
        self.assertEqual(len(ack_events), 1)
        self.assertEqual(ack_events[0].actor_id, "OIDC-ACK-USER")

    def test_second_acknowledgement_is_rejected(self):
        filing = self.record(
            acknowledgement_filename="ack.pdf",
            acknowledgement_payload=self.ack_pdf,
        )
        with self.assertRaisesRegex(ValueError, "already has"):
            attach_filing_acknowledgement(
                self.filing_repo,
                self.store,
                filing=filing,
                acknowledgement_filename="ack-2.pdf",
                acknowledgement_payload=self.ack_pdf,
                actor_id=PRINCIPAL.user_id,
                added_at=NOW + timedelta(hours=1),
            )


class AuthorizedFilingServiceTests(unittest.TestCase):
    def build(self, permissions=None, fact_reviews=None):
        case_service = mock.Mock()
        case_service.get_case.return_value = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            None,
            "Matter",
            CaseStatus.DRAFT_REVIEW,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            NOW,
        )
        access = mock.Mock()
        granted = (
            {
                AccessPermission.CASE_READ,
                AccessPermission.FILING_RECORD,
                AccessPermission.DOCUMENT_ADD,
            }
            if permissions is None
            else permissions
        )
        access.get_grant.return_value = FirmAccessGrant(
            PRINCIPAL.user_id,
            "F-1",
            frozenset(granted),
            True,
        )
        filings = mock.Mock()
        filings.list_filings.return_value = []
        drafts = mock.Mock()
        store = mock.Mock()
        service = AuthorizedFilingService(
            case_service,
            access,
            filings,
            drafts,
            store,
            fact_review_repository=fact_reviews,
        )
        return service, case_service, access, filings, drafts, store

    @mock.patch(
        "modules.authorized_filing_service.persist_filing"
    )
    def test_record_filing_uses_authenticated_actor(self, persist):
        service, *_ = self.build()
        expected = mock.Mock()
        persist.return_value = expected
        result = service.record_filing(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            approved_draft_version_id="DRAFT-1",
            filing_reference="ARN-1",
            filed_response_filename="response.pdf",
            filed_response_payload=b"%PDF fixture",
            acknowledgement_filename=None,
            acknowledgement_payload=None,
            filed_at=FILED_AT,
            recorded_at=NOW,
        )
        self.assertIs(result, expected)
        self.assertEqual(
            persist.call_args.kwargs["actor_id"],
            PRINCIPAL.user_id,
        )

    @mock.patch(
        "modules.authorized_filing_service.persist_filing"
    )
    def test_filing_record_permission_is_required(self, persist):
        service, *_ = self.build(
            permissions={
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_ADD,
            }
        )
        with self.assertRaises(PermissionError):
            service.record_filing(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                approved_draft_version_id="DRAFT-1",
                filing_reference="ARN-1",
                filed_response_filename="response.pdf",
                filed_response_payload=b"%PDF fixture",
                acknowledgement_filename=None,
                acknowledgement_payload=None,
                filed_at=FILED_AT,
                recorded_at=NOW,
            )
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_filing_service.persist_filing"
    )
    def test_document_add_permission_is_also_required(self, persist):
        service, *_ = self.build(
            permissions={
                AccessPermission.CASE_READ,
                AccessPermission.FILING_RECORD,
            }
        )
        with self.assertRaises(PermissionError):
            service.record_filing(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                approved_draft_version_id="DRAFT-1",
                filing_reference="ARN-1",
                filed_response_filename="response.pdf",
                filed_response_payload=b"%PDF fixture",
                acknowledgement_filename=None,
                acknowledgement_payload=None,
                filed_at=FILED_AT,
                recorded_at=NOW,
            )
        persist.assert_not_called()

    @staticmethod
    def _fact_review(decision, *, review_id, reviewed_at):
        return FactReviewRef(
            review_id=review_id,
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            fact_id="F-001",
            fact_fingerprint="a" * 64,
            source_text_sha256="b" * 64,
            decision=decision,
            byte_size=10,
            sha256_hex="c" * 64,
            storage_key="objects/" + "d" * 32,
            reviewed_at=reviewed_at,
            reviewed_by=PRINCIPAL.user_id,
        )

    @mock.patch(
        "modules.authorized_filing_service.persist_filing"
    )
    def test_later_rejected_source_fact_blocks_already_approved_draft_filing(
        self,
        persist,
    ):
        fact_reviews = mock.Mock()
        fact_reviews.list_review_refs.return_value = [
            self._fact_review(
                FactReviewDecision.REJECTED,
                review_id="FREV-1",
                reviewed_at=NOW,
            )
        ]
        service, _, _, _, drafts, _ = self.build(
            fact_reviews=fact_reviews
        )
        drafts.get_version_ref.return_value = mock.Mock(
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
        )

        with self.assertRaisesRegex(
            ValueError,
            "professionally rejected extracted fact",
        ):
            service.record_filing(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                approved_draft_version_id="DRAFT-1",
                filing_reference="ARN-1",
                filed_response_filename="response.pdf",
                filed_response_payload=b"%PDF fixture",
                acknowledgement_filename=None,
                acknowledgement_payload=None,
                filed_at=FILED_AT,
                recorded_at=NOW,
            )

        fact_reviews.list_review_refs.assert_called_once_with("SNAP-1")
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_filing_service.persist_filing"
    )
    def test_later_confirmation_supersedes_old_rejection_for_filing(
        self,
        persist,
    ):
        fact_reviews = mock.Mock()
        fact_reviews.list_review_refs.return_value = [
            self._fact_review(
                FactReviewDecision.REJECTED,
                review_id="FREV-1",
                reviewed_at=NOW,
            ),
            self._fact_review(
                FactReviewDecision.CONFIRMED,
                review_id="FREV-2",
                reviewed_at=NOW + timedelta(minutes=1),
            ),
        ]
        service, _, _, _, drafts, _ = self.build(
            fact_reviews=fact_reviews
        )
        drafts.get_version_ref.return_value = mock.Mock(
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
        )
        persist.return_value = mock.sentinel.filing

        result = service.record_filing(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            approved_draft_version_id="DRAFT-1",
            filing_reference="ARN-1",
            filed_response_filename="response.pdf",
            filed_response_payload=b"%PDF fixture",
            acknowledgement_filename=None,
            acknowledgement_payload=None,
            filed_at=FILED_AT,
            recorded_at=NOW,
        )

        self.assertIs(result, mock.sentinel.filing)
        fact_reviews.list_review_refs.assert_called_once_with("SNAP-1")
        persist.assert_called_once()

    def test_list_filings_is_case_scoped(self):
        service, _, _, filings, _, _ = self.build()
        expected = [mock.Mock()]
        filings.list_filings.return_value = expected
        self.assertEqual(
            service.list_filings(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
            ),
            expected,
        )
        filings.list_filings.assert_called_once_with("CASE-1")


if __name__ == "__main__":
    unittest.main()
