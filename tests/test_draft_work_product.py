"""Tests for Phase 3K durable professional draft work products."""

import hashlib
import inspect
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from docx import Document

from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisSnapshotRef,
    LoadedAnalysisSnapshot,
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
    DRAFT_VERSION_SCHEMA_VERSION,
    DraftReviewStatus,
    DraftVersionRef,
    LoadedDraftVersion,
)
from domain.models import NoticeForm, ProceedingType
from modules.authorized_draft_work_product_service import (
    AuthorizedDraftWorkProductService,
)
from modules.draft_docx_export import export_draft_docx
from modules.draft_work_product_payload import (
    build_draft_payload,
    decode_draft_payload,
    encode_draft_payload,
)
from modules.draft_work_product_service import (
    DraftIntegrityError,
    DraftPersistenceError,
    baseline_text_from_snapshot,
    load_draft_version,
    persist_draft_version,
    transition_draft_review_status,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_draft_version_repository import (
    LocalSQLiteDraftVersionRepository,
)


NOW = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 22, 18, 30, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)
DRAFT_TEXT = "## Facts\n\nProfessional draft text ₹125000"


def snapshot_payload(*, status="success", post_status="pass"):
    return {
        "draft": {
            "status": status,
            "post_validation": (
                None
                if post_status is None
                else {"overall_status": post_status}
            ),
            "sections": [
                {
                    "section_id": "S-001",
                    "title": "Facts",
                    "rendered_text": "Generated factual response.",
                },
                {
                    "section_id": "S-002",
                    "title": "Prayer",
                    "rendered_text": "Generated prayer text.",
                },
            ],
        }
    }


def loaded_snapshot(
    snapshot_id="SNAP-1",
    *,
    case_id="CASE-1",
    payload=None,
):
    metadata = AnalysisSnapshotRef(
        snapshot_id=snapshot_id,
        case_id=case_id,
        source_document_id="DOC-NOTICE",
        source_document_sha256="a" * 64,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        engine_version=ANALYSIS_ENGINE_VERSION,
        byte_size=100,
        sha256_hex="b" * 64,
        storage_key="objects/" + "b" * 32,
        created_at=NOW,
        created_by=PRINCIPAL.user_id,
    )
    return LoadedAnalysisSnapshot(
        metadata=metadata,
        payload=snapshot_payload() if payload is None else payload,
    )


class DraftPayloadTests(unittest.TestCase):
    def test_payload_is_closed_versioned_json(self):
        payload = build_draft_payload(
            case_id="CASE-1",
            source_snapshot_id="SNAP-1",
            parent_draft_version_id=None,
            version_number=1,
            generated_baseline=True,
            draft_text=DRAFT_TEXT,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
        )
        self.assertEqual(
            payload["schema_version"],
            DRAFT_VERSION_SCHEMA_VERSION,
        )
        self.assertEqual(
            decode_draft_payload(encode_draft_payload(payload)),
            payload,
        )

    def test_payload_source_has_no_native_object_deserializer(self):
        import modules.draft_work_product_payload as module

        source = inspect.getsource(module)
        self.assertNotIn("import pickle", source)
        self.assertNotIn("pickle.loads", source)
        self.assertNotIn("object_hook=", source)
        self.assertNotIn("yaml.load(", source)

    def test_pickle_like_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_draft_payload(
                b"cos\nsystem\n(S'echo should-never-run'\ntR."
            )


class DraftBaselineTests(unittest.TestCase):
    def test_valid_snapshot_becomes_editable_text_with_section_headings(self):
        text = baseline_text_from_snapshot(loaded_snapshot())
        self.assertEqual(
            text,
            (
                "## Facts\n\nGenerated factual response.\n\n"
                "## Prayer\n\nGenerated prayer text."
            ),
        )

    def test_failed_or_unvalidated_snapshot_cannot_seed_work_product(self):
        cases = [
            snapshot_payload(status="failed"),
            snapshot_payload(post_status="warning"),
            snapshot_payload(post_status=None),
            {
                "draft": {
                    "status": "success",
                    "post_validation": {"overall_status": "pass"},
                    "sections": [],
                }
            },
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    baseline_text_from_snapshot(
                        loaded_snapshot(payload=payload)
                    )


class DraftPersistenceFixture(unittest.TestCase):
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
                "CASE-1",
                "F-1",
                "C-1",
                None,
                "GST Notice Response",
                CaseStatus.ANALYZED,
                ProceedingType.GST_SEC73_GENERAL,
                NoticeForm.DRC_01,
                NOW,
            )
        )
        self.notice = StoredDocumentRef(
            "DOC-NOTICE",
            "CASE-1",
            CaseDocumentKind.NOTICE,
            "notice.pdf",
            "application/pdf",
            100,
            "a" * 64,
            "objects/" + "c" * 32,
            NOW,
        )
        self.case_repo.add_document_ref(self.notice)

        self.snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(
            self.db_path
        )
        self.snapshot_one = self._save_snapshot_ref("SNAP-1")
        self.snapshot_two = self._save_snapshot_ref("SNAP-2")
        self.repo = LocalSQLiteDraftVersionRepository(self.db_path)
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=3 * 1024 * 1024,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _save_snapshot_ref(self, snapshot_id):
        ref = AnalysisSnapshotRef(
            snapshot_id=snapshot_id,
            case_id="CASE-1",
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=10,
            sha256_hex=hashlib.sha256(snapshot_id.encode()).hexdigest(),
            storage_key="objects/" + hashlib.md5(
                snapshot_id.encode()
            ).hexdigest(),
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
        )
        self.snapshot_repo.save_snapshot(
            ref,
            CaseEvent(
                "EV-" + snapshot_id,
                "CASE-1",
                CaseEventType.ANALYSIS_SAVED,
                NOW,
                PRINCIPAL.user_id,
                {
                    "snapshot_id": snapshot_id,
                    "source_document_id": "DOC-NOTICE",
                },
            ),
        )
        return ref

    def persist(
        self,
        *,
        source_snapshot_id="SNAP-1",
        parent=None,
        version_number=1,
        generated=True,
        text=DRAFT_TEXT,
    ):
        return persist_draft_version(
            self.repo,
            self.store,
            case_id="CASE-1",
            source_snapshot_id=source_snapshot_id,
            parent_draft_version_id=parent,
            version_number=version_number,
            generated_baseline=generated,
            draft_text=text,
            actor_id=PRINCIPAL.user_id,
            created_at=NOW,
        )


class DraftPersistenceTests(DraftPersistenceFixture):
    def test_round_trip_encrypts_text_and_audit_excludes_text(self):
        version = self.persist()
        loaded = load_draft_version(
            self.repo,
            self.store,
            draft_version_id=version.draft_version_id,
        )
        self.assertEqual(loaded.payload["draft_text"], DRAFT_TEXT)
        self.assertEqual(loaded.metadata, version)

        object_id = version.storage_key.split("/", 1)[1]
        ciphertext = (
            Path(self.object_root) / f"{object_id}.dwaar"
        ).read_bytes()
        self.assertNotIn(DRAFT_TEXT.encode("utf-8"), ciphertext)

        events = [
            item
            for item in self.case_repo.list_events("CASE-1")
            if item.event_type is CaseEventType.DRAFT_CREATED
        ]
        self.assertEqual(len(events), 1)
        self.assertNotIn(DRAFT_TEXT, repr(events[0].payload))

    def test_child_is_immutable_new_version_same_snapshot_lineage(self):
        parent = self.persist()
        child = self.persist(
            parent=parent.draft_version_id,
            version_number=2,
            generated=False,
            text=DRAFT_TEXT + "\nEdited by CA.",
        )
        self.assertEqual(child.parent_draft_version_id, parent.draft_version_id)
        self.assertEqual(child.source_snapshot_id, parent.source_snapshot_id)
        self.assertNotEqual(child.content_sha256, parent.content_sha256)
        self.assertEqual(
            [item.version_number for item in self.repo.list_version_refs("CASE-1")],
            [1, 2],
        )

    def test_new_snapshot_can_start_new_baseline_lineage(self):
        first = self.persist()
        second = self.persist(
            source_snapshot_id="SNAP-2",
            parent=None,
            version_number=2,
            generated=True,
            text="## New baseline\n\nNew analysis output.",
        )
        self.assertIsNone(second.parent_draft_version_id)
        self.assertTrue(second.generated_baseline)
        self.assertNotEqual(
            first.source_snapshot_id,
            second.source_snapshot_id,
        )

    def test_child_must_follow_latest_version_and_same_snapshot(self):
        first = self.persist()
        with self.assertRaises(DraftPersistenceError):
            self.persist(
                source_snapshot_id="SNAP-2",
                parent=first.draft_version_id,
                version_number=2,
                generated=False,
            )

    def test_database_failure_rolls_back_encrypted_payload(self):
        repository = mock.Mock()
        repository.save_version.side_effect = RuntimeError("db failed")
        store = mock.Mock()
        with self.assertRaises(DraftPersistenceError):
            persist_draft_version(
                repository,
                store,
                case_id="CASE-1",
                source_snapshot_id="SNAP-1",
                parent_draft_version_id=None,
                version_number=1,
                generated_baseline=True,
                draft_text=DRAFT_TEXT,
                actor_id=PRINCIPAL.user_id,
                created_at=NOW,
            )
        store.put.assert_called_once()
        store.delete.assert_called_once()

    def test_metadata_tamper_is_detected_on_load(self):
        version = self.persist()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE draft_versions
                SET content_sha256 = ?
                WHERE draft_version_id = ?
                """,
                ("f" * 64, version.draft_version_id),
            )
        with self.assertRaisesRegex(
            DraftIntegrityError,
            "content hash",
        ):
            load_draft_version(
                self.repo,
                self.store,
                draft_version_id=version.draft_version_id,
            )

    def test_review_then_approve_preserves_content_identity(self):
        version = self.persist()
        reviewed = transition_draft_review_status(
            self.repo,
            version=version,
            target_status=DraftReviewStatus.REVIEWED,
            actor_id="REVIEWER-1",
            occurred_at=NOW,
        )
        approved = transition_draft_review_status(
            self.repo,
            version=reviewed,
            target_status=DraftReviewStatus.APPROVED,
            actor_id="REVIEWER-2",
            occurred_at=LATER,
        )
        self.assertEqual(approved.content_sha256, version.content_sha256)
        self.assertEqual(approved.storage_key, version.storage_key)
        self.assertEqual(approved.reviewed_by, "REVIEWER-1")
        self.assertEqual(approved.approved_by, "REVIEWER-2")
        self.assertEqual(
            self.repo.get_version_ref(version.draft_version_id),
            approved,
        )

    def test_review_transition_cannot_skip_or_reverse(self):
        version = self.persist()
        with self.assertRaises(ValueError):
            transition_draft_review_status(
                self.repo,
                version=version,
                target_status=DraftReviewStatus.APPROVED,
                actor_id="R-1",
                occurred_at=NOW,
            )


class DraftDocxExportTests(unittest.TestCase):
    def loaded(self, status):
        metadata = DraftVersionRef(
            "DRAFT-1",
            "CASE-1",
            "SNAP-1",
            None,
            1,
            True,
            hashlib.sha256(DRAFT_TEXT.encode()).hexdigest(),
            10,
            "a" * 64,
            "objects/" + "a" * 32,
            status,
            NOW,
            PRINCIPAL.user_id,
            reviewed_at=(NOW if status is not DraftReviewStatus.WORKING else None),
            reviewed_by=("R-1" if status is not DraftReviewStatus.WORKING else None),
            approved_at=(LATER if status is DraftReviewStatus.APPROVED else None),
            approved_by=("R-2" if status is DraftReviewStatus.APPROVED else None),
        )
        return LoadedDraftVersion(
            metadata=metadata,
            payload={"draft_text": DRAFT_TEXT},
        )

    def test_working_version_cannot_export(self):
        with self.assertRaisesRegex(ValueError, "reviewed or approved"):
            export_draft_docx(
                self.loaded(DraftReviewStatus.WORKING),
                case_title="Matter",
            )

    def test_reviewed_docx_contains_case_version_status_and_text(self):
        data = export_draft_docx(
            self.loaded(DraftReviewStatus.REVIEWED),
            case_title="Matter",
        )
        document = Document(BytesIO(data))
        text = "\n".join(
            paragraph.text for paragraph in document.paragraphs
        )
        self.assertIn("Matter", text)
        self.assertIn("Dwaar draft version 1", text)
        self.assertIn("REVIEWED", text)
        self.assertIn("Professional draft text ₹125000", text)
        self.assertIn("Source analysis snapshot: SNAP-1", text)
        self.assertIn("does not record filing", text)


class AuthorizedDraftServiceTests(unittest.TestCase):
    def build(self, *, permissions=None):
        case_service = mock.Mock()
        case_service.get_case.return_value = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            None,
            "Matter",
            CaseStatus.ANALYZED,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            NOW,
        )
        snapshot_service = mock.Mock()
        snapshot_service.load_snapshot.return_value = loaded_snapshot()
        access = mock.Mock()
        granted = (
            {
                AccessPermission.CASE_READ,
                AccessPermission.CASE_UPDATE,
                AccessPermission.DOCUMENT_READ,
                AccessPermission.DRAFT_REVIEW,
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
        repo = mock.Mock()
        repo.list_version_refs.return_value = []
        store = mock.Mock()
        service = AuthorizedDraftWorkProductService(
            case_service,
            snapshot_service,
            access,
            repo,
            store,
        )
        return service, case_service, snapshot_service, access, repo, store

    @mock.patch(
        "modules.authorized_draft_work_product_service.persist_draft_version"
    )
    def test_generated_baseline_comes_only_from_selected_snapshot(
        self,
        persist,
    ):
        service, _, snapshots, _, repo, _ = self.build()
        expected = mock.Mock()
        persist.return_value = expected
        result = service.create_generated_baseline(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            created_at=NOW,
        )
        self.assertIs(result, expected)
        snapshots.load_snapshot.assert_called_once_with(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertIn(
            "Generated factual response",
            persist.call_args.kwargs["draft_text"],
        )
        self.assertTrue(
            persist.call_args.kwargs["generated_baseline"]
        )
        self.assertIsNone(
            persist.call_args.kwargs["parent_draft_version_id"]
        )

    @mock.patch(
        "modules.authorized_draft_work_product_service.persist_draft_version"
    )
    def test_same_snapshot_cannot_seed_duplicate_baseline(self, persist):
        service, *_rest = self.build()
        repo = _rest[-2]
        repo.list_version_refs.return_value = [
            DraftVersionRef(
                "DRAFT-1",
                "CASE-1",
                "SNAP-1",
                None,
                1,
                True,
                "a" * 64,
                10,
                "b" * 64,
                "objects/" + "a" * 32,
                DraftReviewStatus.WORKING,
                NOW,
                PRINCIPAL.user_id,
            )
        ]
        with self.assertRaisesRegex(ValueError, "already has"):
            service.create_generated_baseline(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                created_at=NOW,
            )
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_draft_work_product_service.load_draft_version"
    )
    @mock.patch(
        "modules.authorized_draft_work_product_service.persist_draft_version"
    )
    def test_edit_must_branch_from_latest_version(
        self,
        persist,
        load,
    ):
        service, _, _, _, repo, _ = self.build()
        old = DraftVersionRef(
            "DRAFT-1",
            "CASE-1",
            "SNAP-1",
            None,
            1,
            True,
            "a" * 64,
            10,
            "b" * 64,
            "objects/" + "a" * 32,
            DraftReviewStatus.WORKING,
            NOW,
            PRINCIPAL.user_id,
        )
        latest = DraftVersionRef(
            "DRAFT-2",
            "CASE-1",
            "SNAP-1",
            old.draft_version_id,
            2,
            False,
            "c" * 64,
            10,
            "d" * 64,
            "objects/" + "b" * 32,
            DraftReviewStatus.WORKING,
            NOW,
            PRINCIPAL.user_id,
        )
        repo.get_version_ref.return_value = old
        repo.list_version_refs.return_value = [old, latest]
        with self.assertRaisesRegex(ValueError, "latest"):
            service.create_edited_version(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                parent_draft_version_id=old.draft_version_id,
                draft_text="Edited",
                created_at=NOW,
            )
        load.assert_not_called()
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_draft_work_product_service.transition_draft_review_status"
    )
    @mock.patch(
        "modules.authorized_draft_work_product_service.load_draft_version"
    )
    def test_review_requires_draft_review_and_verifies_content(
        self,
        load,
        transition,
    ):
        service, _, _, _, repo, _ = self.build()
        version = DraftVersionRef(
            "DRAFT-1",
            "CASE-1",
            "SNAP-1",
            None,
            1,
            True,
            "a" * 64,
            10,
            "b" * 64,
            "objects/" + "a" * 32,
            DraftReviewStatus.WORKING,
            NOW,
            PRINCIPAL.user_id,
        )
        repo.get_version_ref.return_value = version
        expected = mock.Mock()
        transition.return_value = expected
        result = service.transition_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            draft_version_id="DRAFT-1",
            target_status=DraftReviewStatus.REVIEWED,
            occurred_at=NOW,
        )
        self.assertIs(result, expected)
        load.assert_called_once()
        transition.assert_called_once()
        self.assertEqual(
            transition.call_args.kwargs["actor_id"],
            PRINCIPAL.user_id,
        )

    def test_create_requires_case_update(self):
        service, *_ = self.build(
            permissions={
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        with self.assertRaises(PermissionError):
            service.create_generated_baseline(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                created_at=NOW,
            )

    def test_review_requires_draft_review(self):
        service, *_ = self.build(
            permissions={
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        with self.assertRaises(PermissionError):
            service.transition_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                draft_version_id="DRAFT-1",
                target_status=DraftReviewStatus.REVIEWED,
                occurred_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
