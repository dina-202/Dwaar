"""Fact-review persistence, authorization and downstream reliance tests."""

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

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
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
)
from domain.fact_review_models import (
    FACT_REVIEW_SCHEMA_VERSION,
    FactReviewDecision,
)
from domain.models import NoticeForm, ProceedingType
from modules.analysis_snapshot import encode_snapshot_payload
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_draft_work_product_service import (
    AuthorizedDraftWorkProductService,
)
from modules.authorized_fact_review_service import AuthorizedFactReviewService
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.fact_review_payload import (
    build_fact_review_payload,
    decode_fact_review_payload,
    encode_fact_review_payload,
)
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_fact_review_repository import (
    LocalSQLiteFactReviewRepository,
)


NOW = datetime(2026, 9, 23, 17, 30, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "f" * 64)
SOURCE_TEXT = "Department states a turnover discrepancy of INR 125000."
REVIEW_NOTE = "The notice text is present, but this extracted fact is misclassified."


def fact_row():
    return {
        "fact_id": "F-001",
        "fact_type": "department_allegation",
        "fact_role": "none",
        "status": "alleged",
        "source_text": SOURCE_TEXT,
        "source_page": 1,
        "source_origin": "embedded",
        "source_verification": "verified",
        "allowed_in_draft": "conditional",
    }


def snapshot_payload():
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "engine_version": ANALYSIS_ENGINE_VERSION,
        "source": {
            "document_id": "DOC-NOTICE",
            "sha256": "a" * 64,
        },
        "classification": {},
        "extraction": {
            "status": "success",
            "rejected_item_count": 0,
            "facts": [
                {
                    **fact_row(),
                    "claim": "model-authored claim is historical only",
                }
            ],
        },
        "deadline": {},
        "preflight": {},
        "arithmetic": [],
        "validation": {},
        "draft": {},
        "triage_summary": None,
    }


class FactReviewPayloadTests(unittest.TestCase):
    def test_payload_is_versioned_and_excludes_model_claim(self):
        payload = build_fact_review_payload(
            fact_row(),
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            decision=FactReviewDecision.REJECTED,
            reviewer_note=REVIEW_NOTE,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        self.assertEqual(payload["schema_version"], FACT_REVIEW_SCHEMA_VERSION)
        self.assertEqual(payload["fact"]["source_text"], SOURCE_TEXT)
        self.assertNotIn("claim", payload["fact"])
        self.assertEqual(payload["reviewer_note"], REVIEW_NOTE)
        decoded = decode_fact_review_payload(
            encode_fact_review_payload(payload)
        )
        self.assertEqual(decoded, payload)

    def test_source_tamper_breaks_binding(self):
        payload = build_fact_review_payload(
            fact_row(),
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            decision=FactReviewDecision.CONFIRMED,
            reviewer_note=None,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        tampered = {
            **payload,
            "fact": {
                **payload["fact"],
                "source_text": SOURCE_TEXT + " changed",
            },
        }
        with self.assertRaisesRegex(ValueError, "quote hash"):
            encode_fact_review_payload(tampered)


class FactReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
        )
        self.cases = LocalSQLiteCaseRepository(self.db_path)
        self.access = LocalSQLiteAccessGrantRepository(self.db_path)
        self.snapshots = LocalSQLiteAnalysisSnapshotRepository(self.db_path)
        self.reviews = LocalSQLiteFactReviewRepository(self.db_path)

        self.cases.create_firm(Firm("F-1", "Firm", NOW))
        self.cases.create_client(Client("C-1", "F-1", "Client", NOW))
        self.cases.create_case(
            CaseRecord(
                "CASE-1",
                "F-1",
                "C-1",
                None,
                "ASMT-10 matter",
                CaseStatus.ANALYZED,
                ProceedingType.GST_SEC61_SCRUTINY,
                NoticeForm.ASMT_10,
                NOW,
            )
        )
        notice = StoredDocumentRef(
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256_hex="a" * 64,
            storage_key="objects/" + "1" * 32,
            created_at=NOW,
        )
        self.cases.add_document_ref(notice)

        encoded = encode_snapshot_payload(snapshot_payload())
        storage_key = "objects/" + "2" * 32
        self.store.put(storage_key, encoded)
        snapshot = AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id=notice.document_id,
            source_document_sha256=notice.sha256_hex,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=len(encoded),
            sha256_hex=hashlib.sha256(encoded).hexdigest(),
            storage_key=storage_key,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
        )
        self.snapshots.save_snapshot(
            snapshot,
            CaseEvent(
                "EV-SNAP",
                "CASE-1",
                CaseEventType.ANALYSIS_SAVED,
                NOW,
                PRINCIPAL.user_id,
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "source_document_id": notice.document_id,
                },
            ),
        )
        self.access.save_grant(
            FirmAccessGrant(
                PRINCIPAL.user_id,
                "F-1",
                frozenset(
                    {
                        AccessPermission.CASE_READ,
                        AccessPermission.DOCUMENT_READ,
                        AccessPermission.FACT_REVIEW,
                    }
                ),
                True,
            )
        )
        case_service = AuthorizedCaseService(
            self.cases,
            self.access,
            self.store,
        )
        snapshot_service = AuthorizedAnalysisSnapshotService(
            case_service,
            self.access,
            self.snapshots,
            self.store,
        )
        self.service = AuthorizedFactReviewService(
            case_service,
            snapshot_service,
            self.access,
            self.reviews,
            self.store,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_reject_round_trip_is_encrypted_audited_and_source_bound(self):
        ref = self.service.save_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            fact_id="F-001",
            decision=FactReviewDecision.REJECTED,
            reviewer_note=REVIEW_NOTE,
            reviewed_at=NOW,
        )
        self.assertIs(ref.decision, FactReviewDecision.REJECTED)

        loaded = self.service.load_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            review_id=ref.review_id,
        )
        self.assertEqual(loaded.payload["fact"]["source_text"], SOURCE_TEXT)
        self.assertEqual(loaded.payload["reviewer_note"], REVIEW_NOTE)
        self.assertNotIn("claim", loaded.payload["fact"])

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(fact_reviews)"
                ).fetchall()
            }
            row = connection.execute(
                "SELECT * FROM fact_reviews WHERE review_id = ?",
                (ref.review_id,),
            ).fetchone()
        self.assertNotIn("source_text", columns)
        self.assertNotIn("reviewer_note", columns)
        self.assertNotIn(SOURCE_TEXT, repr(dict(row)))
        self.assertNotIn(REVIEW_NOTE, repr(dict(row)))

        event = [
            item
            for item in self.cases.list_events("CASE-1")
            if item.event_type is CaseEventType.FACT_REVIEWED
        ][0]
        self.assertEqual(event.payload["fact_id"], "F-001")
        self.assertEqual(event.payload["decision"], "rejected")
        self.assertNotIn(SOURCE_TEXT, repr(event.payload))
        self.assertNotIn(REVIEW_NOTE, repr(event.payload))

    def test_duplicate_terminal_review_is_rejected(self):
        kwargs = dict(
            principal=PRINCIPAL,
            firm_id="F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            fact_id="F-001",
            reviewer_note=None,
            reviewed_at=NOW,
        )
        self.service.save_review(
            decision=FactReviewDecision.CONFIRMED,
            **kwargs,
        )
        with self.assertRaises(Exception):
            self.service.save_review(
                decision=FactReviewDecision.REJECTED,
                **kwargs,
            )

    def test_caller_cannot_review_fact_not_in_snapshot(self):
        with self.assertRaisesRegex(LookupError, "fact does not exist"):
            self.service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                fact_id="F-INVENTED",
                decision=FactReviewDecision.REJECTED,
                reviewer_note=None,
                reviewed_at=NOW,
            )


class DraftApprovalFactReviewGateTests(unittest.TestCase):
    @mock.patch(
        "modules.authorized_draft_work_product_service."
        "transition_draft_review_status"
    )
    @mock.patch(
        "modules.authorized_draft_work_product_service.load_draft_version"
    )
    def test_rejected_source_fact_blocks_approval(
        self,
        load_version,
        transition,
    ):
        case_service = mock.Mock()
        case_service.get_case.return_value = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            None,
            "Matter",
            CaseStatus.DRAFT_REVIEW,
            ProceedingType.GST_SEC61_SCRUTINY,
            NoticeForm.ASMT_10,
            NOW,
        )
        access = mock.Mock()
        access.get_grant.return_value = FirmAccessGrant(
            PRINCIPAL.user_id,
            "F-1",
            frozenset(
                {
                    AccessPermission.CASE_READ,
                    AccessPermission.DOCUMENT_READ,
                    AccessPermission.DRAFT_REVIEW,
                }
            ),
            True,
        )
        drafts = mock.Mock()
        version = DraftVersionRef(
            draft_version_id="DRAFT-1",
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            content_sha256="a" * 64,
            byte_size=10,
            sha256_hex="b" * 64,
            storage_key="objects/" + "3" * 32,
            review_status=DraftReviewStatus.REVIEWED,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        drafts.get_version_ref.return_value = version
        fact_reviews = mock.Mock()
        rejected = mock.Mock()
        rejected.fact_id = "F-001"
        rejected.decision = FactReviewDecision.REJECTED
        fact_reviews.list_review_refs.return_value = [rejected]

        service = AuthorizedDraftWorkProductService(
            case_service,
            mock.Mock(),
            access,
            drafts,
            mock.Mock(),
            fact_review_repository=fact_reviews,
        )
        with self.assertRaisesRegex(
            ValueError,
            "professionally rejected extracted facts",
        ):
            service.transition_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                draft_version_id="DRAFT-1",
                target_status=DraftReviewStatus.APPROVED,
                occurred_at=NOW,
            )
        transition.assert_not_called()
        load_version.assert_called_once()

    @mock.patch(
        "modules.authorized_draft_work_product_service."
        "transition_draft_review_status"
    )
    @mock.patch(
        "modules.authorized_draft_work_product_service.load_draft_version"
    )
    def test_confirmed_fact_does_not_block_approval(
        self,
        load_version,
        transition,
    ):
        case_service = mock.Mock()
        case_service.get_case.return_value = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            None,
            "Matter",
            CaseStatus.DRAFT_REVIEW,
            ProceedingType.GST_SEC61_SCRUTINY,
            NoticeForm.ASMT_10,
            NOW,
        )
        access = mock.Mock()
        access.get_grant.return_value = FirmAccessGrant(
            PRINCIPAL.user_id,
            "F-1",
            frozenset(
                {
                    AccessPermission.DOCUMENT_READ,
                    AccessPermission.DRAFT_REVIEW,
                }
            ),
            True,
        )
        drafts = mock.Mock()
        version = DraftVersionRef(
            draft_version_id="DRAFT-1",
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            content_sha256="a" * 64,
            byte_size=10,
            sha256_hex="b" * 64,
            storage_key="objects/" + "3" * 32,
            review_status=DraftReviewStatus.REVIEWED,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        drafts.get_version_ref.return_value = version
        confirmed = mock.Mock()
        confirmed.fact_id = "F-001"
        confirmed.decision = FactReviewDecision.CONFIRMED
        fact_reviews = mock.Mock()
        fact_reviews.list_review_refs.return_value = [confirmed]
        transition.return_value = mock.sentinel.approved

        service = AuthorizedDraftWorkProductService(
            case_service,
            mock.Mock(),
            access,
            drafts,
            mock.Mock(),
            fact_review_repository=fact_reviews,
        )
        result = service.transition_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            draft_version_id="DRAFT-1",
            target_status=DraftReviewStatus.APPROVED,
            occurred_at=NOW,
        )
        self.assertIs(result, mock.sentinel.approved)
        transition.assert_called_once()


if __name__ == "__main__":
    unittest.main()
