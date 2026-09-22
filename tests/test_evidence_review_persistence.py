"""Tests for encrypted snapshot-bound evidence review persistence."""

import hashlib
import inspect
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
from domain.evidence_review_models import (
    EVIDENCE_REVIEW_SCHEMA_VERSION,
    EvidenceReviewRef,
)
from domain.models import (
    EvidenceCandidate,
    EvidenceReviewStatus,
    NoticeForm,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.evidence_review_payload import (
    build_review_payload,
    candidate_fingerprint,
    decode_review_payload,
    encode_review_payload,
    source_text_sha256,
)
from modules.evidence_review_persistence_service import (
    EvidenceReviewIntegrityError,
    EvidenceReviewPersistenceError,
    load_evidence_review,
    persist_evidence_review,
)
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_evidence_review_repository import (
    LocalSQLiteEvidenceReviewRepository,
)


NOW = datetime(2026, 9, 22, 19, 0, tzinfo=timezone.utc)
ACTOR = "OIDC-" + "a" * 64
SOURCE_TEXT = "GSTR-2B April 2026 Total ITC 125000"
REVIEW_NOTE = "Checked against portal export and purchase register."


def candidate() -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id="EC-001",
        evidence_id="evidence.one",
        document_id="DOC-EVIDENCE",
        source_text=SOURCE_TEXT,
        source_page=2,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )


class EvidenceReviewPayloadTests(unittest.TestCase):
    def test_payload_is_versioned_and_bound_without_native_objects(self):
        payload = build_review_payload(
            candidate(),
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            decision=EvidenceReviewStatus.CONFIRMED,
            reviewer_note=REVIEW_NOTE,
            reviewed_at=NOW,
            reviewed_by=ACTOR,
        )
        self.assertEqual(
            payload["schema_version"],
            EVIDENCE_REVIEW_SCHEMA_VERSION,
        )
        self.assertEqual(payload["binding"]["case_id"], "CASE-1")
        self.assertEqual(payload["binding"]["snapshot_id"], "SNAP-1")
        self.assertEqual(
            payload["binding"]["source_text_sha256"],
            hashlib.sha256(SOURCE_TEXT.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(payload["candidate"]["source_text"], SOURCE_TEXT)
        self.assertEqual(payload["reviewer_note"], REVIEW_NOTE)

        decoded = decode_review_payload(
            encode_review_payload(payload)
        )
        self.assertIsInstance(decoded, dict)
        self.assertIsInstance(decoded["candidate"], dict)
        self.assertNotIsInstance(decoded, EvidenceReviewRef)

    def test_candidate_fingerprint_ignores_transient_candidate_id(self):
        quote_hash = source_text_sha256(SOURCE_TEXT)
        first = candidate_fingerprint(
            snapshot_id="SNAP-1",
            evidence_id="evidence.one",
            document_id="DOC-EVIDENCE",
            source_page=2,
            source_text_hash=quote_hash,
        )
        second_candidate = candidate()
        second_candidate.candidate_id = "EC-999"
        second = candidate_fingerprint(
            snapshot_id="SNAP-1",
            evidence_id=second_candidate.evidence_id,
            document_id=second_candidate.document_id,
            source_page=second_candidate.source_page,
            source_text_hash=source_text_sha256(
                second_candidate.source_text
            ),
        )
        self.assertEqual(first, second)

    def test_binding_changes_change_candidate_fingerprint(self):
        quote_hash = source_text_sha256(SOURCE_TEXT)
        baseline = candidate_fingerprint(
            snapshot_id="SNAP-1",
            evidence_id="evidence.one",
            document_id="DOC-EVIDENCE",
            source_page=2,
            source_text_hash=quote_hash,
        )
        mutations = [
            ("SNAP-2", "evidence.one", "DOC-EVIDENCE", 2, quote_hash),
            ("SNAP-1", "evidence.two", "DOC-EVIDENCE", 2, quote_hash),
            ("SNAP-1", "evidence.one", "DOC-OTHER", 2, quote_hash),
            ("SNAP-1", "evidence.one", "DOC-EVIDENCE", 3, quote_hash),
            (
                "SNAP-1",
                "evidence.one",
                "DOC-EVIDENCE",
                2,
                source_text_sha256(SOURCE_TEXT + " changed"),
            ),
        ]
        for values in mutations:
            with self.subTest(values=values):
                self.assertNotEqual(
                    baseline,
                    candidate_fingerprint(
                        snapshot_id=values[0],
                        evidence_id=values[1],
                        document_id=values[2],
                        source_page=values[3],
                        source_text_hash=values[4],
                    ),
                )

    def test_payload_tamper_is_rejected(self):
        payload = build_review_payload(
            candidate(),
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            decision=EvidenceReviewStatus.CONFIRMED,
            reviewer_note=None,
            reviewed_at=NOW,
            reviewed_by=ACTOR,
        )
        tampered = {
            **payload,
            "candidate": {
                **payload["candidate"],
                "source_text": SOURCE_TEXT + " fabricated",
            },
        }
        with self.assertRaisesRegex(ValueError, "quote hash"):
            encode_review_payload(tampered)

    def test_pickle_like_payload_is_not_deserialized(self):
        with self.assertRaises(ValueError):
            decode_review_payload(
                b"cos\nsystem\n(S'echo should-never-run'\ntR."
            )

    def test_payload_module_has_no_native_object_deserializer(self):
        import modules.evidence_review_payload as module

        source = inspect.getsource(module)
        self.assertNotIn("import pickle", source)
        self.assertNotIn("pickle.loads", source)
        self.assertNotIn("object_hook=", source)
        self.assertNotIn("yaml.load(", source)


class EvidenceReviewPersistenceFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")

        self.case_repo = LocalSQLiteCaseRepository(self.db_path)
        self.case_repo.create_firm(Firm("F-1", "Firm", NOW))
        self.case_repo.create_client(
            Client("CLIENT-1", "F-1", "Client", NOW)
        )
        self.case_repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="CLIENT-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.ANALYZED,
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        self.notice = StoredDocumentRef(
            document_id="DOC-NOTICE",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=100,
            sha256_hex="1" * 64,
            storage_key="objects/" + "1" * 32,
            created_at=NOW,
        )
        self.evidence = StoredDocumentRef(
            document_id="DOC-EVIDENCE",
            case_id="CASE-1",
            kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
            original_filename="gstr2b.pdf",
            media_type="application/pdf",
            byte_size=200,
            sha256_hex="2" * 64,
            storage_key="objects/" + "2" * 32,
            created_at=NOW,
        )
        self.case_repo.add_document_ref(self.notice)
        self.case_repo.add_document_ref(self.evidence)

        self.snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(
            self.db_path
        )
        self.snapshot = AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id=self.notice.document_id,
            source_document_sha256=self.notice.sha256_hex,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            engine_version=ANALYSIS_ENGINE_VERSION,
            byte_size=10,
            sha256_hex="3" * 64,
            storage_key="objects/" + "3" * 32,
            created_at=NOW,
            created_by=ACTOR,
        )
        self.snapshot_repo.save_snapshot(
            self.snapshot,
            CaseEvent(
                event_id="EV-SNAPSHOT",
                case_id="CASE-1",
                event_type=CaseEventType.ANALYSIS_SAVED,
                occurred_at=NOW,
                actor_id=ACTOR,
                payload={
                    "snapshot_id": "SNAP-1",
                    "source_document_id": "DOC-NOTICE",
                },
            ),
        )

        self.review_repo = LocalSQLiteEvidenceReviewRepository(
            self.db_path
        )
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=1024 * 1024,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def persist(self, *, decision=EvidenceReviewStatus.CONFIRMED):
        return persist_evidence_review(
            self.review_repo,
            self.store,
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            candidate=candidate(),
            decision=decision,
            reviewer_note=REVIEW_NOTE,
            actor_id=ACTOR,
            reviewed_at=NOW,
        )


class EvidenceReviewRepositoryEncryptionTests(
    EvidenceReviewPersistenceFixture
):
    def test_round_trip_is_encrypted_and_audited_without_quote_or_note(self):
        review = self.persist()
        loaded = load_evidence_review(
            self.review_repo,
            self.store,
            review_id=review.review_id,
        )
        self.assertEqual(loaded.metadata, review)
        self.assertEqual(
            loaded.payload["candidate"]["source_text"],
            SOURCE_TEXT,
        )
        self.assertEqual(loaded.payload["reviewer_note"], REVIEW_NOTE)

        object_id = review.storage_key.split("/", 1)[1]
        ciphertext = (
            Path(self.object_root) / f"{object_id}.dwaar"
        ).read_bytes()
        self.assertNotIn(SOURCE_TEXT.encode("utf-8"), ciphertext)
        self.assertNotIn(REVIEW_NOTE.encode("utf-8"), ciphertext)

        events = [
            event
            for event in self.case_repo.list_events("CASE-1")
            if event.event_type is CaseEventType.EVIDENCE_REVIEWED
        ]
        self.assertEqual(len(events), 1)
        event_text = repr(events[0].payload)
        self.assertIn(review.review_id, event_text)
        self.assertIn(review.snapshot_id, event_text)
        self.assertNotIn(SOURCE_TEXT, event_text)
        self.assertNotIn(REVIEW_NOTE, event_text)

    def test_sqlite_metadata_does_not_have_quote_or_note_columns(self):
        with sqlite3.connect(self.db_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(evidence_reviews)"
                ).fetchall()
            }
        self.assertNotIn("source_text", columns)
        self.assertNotIn("reviewer_note", columns)
        self.assertIn("source_text_sha256", columns)

    def test_same_candidate_cannot_be_reviewed_twice_for_same_snapshot(self):
        first = self.persist()
        before = set(Path(self.object_root).glob("*.dwaar"))
        with self.assertRaises(EvidenceReviewPersistenceError):
            self.persist(decision=EvidenceReviewStatus.REJECTED)
        after = set(Path(self.object_root).glob("*.dwaar"))
        self.assertEqual(before, after)
        refs = self.review_repo.list_review_refs("SNAP-1")
        self.assertEqual(refs, [first])

    def test_wrong_document_kind_rolls_back_encrypted_payload(self):
        wrong = candidate()
        wrong.document_id = "DOC-NOTICE"
        with self.assertRaises(EvidenceReviewPersistenceError):
            persist_evidence_review(
                self.review_repo,
                self.store,
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=wrong,
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                actor_id=ACTOR,
                reviewed_at=NOW,
            )
        self.assertEqual(
            self.review_repo.list_review_refs("SNAP-1"),
            [],
        )
        self.assertEqual(list(Path(self.object_root).glob("*.dwaar")), [])

    def test_metadata_byte_size_tamper_is_detected(self):
        review = self.persist()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE evidence_reviews
                SET byte_size = byte_size + 1
                WHERE review_id = ?
                """,
                (review.review_id,),
            )
        with self.assertRaisesRegex(
            EvidenceReviewIntegrityError,
            "byte size",
        ):
            load_evidence_review(
                self.review_repo,
                self.store,
                review_id=review.review_id,
            )

    def test_metadata_binding_tamper_is_detected(self):
        review = self.persist()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE evidence_reviews
                SET evidence_id = 'evidence.tampered'
                WHERE review_id = ?
                """,
                (review.review_id,),
            )
        with self.assertRaisesRegex(
            EvidenceReviewIntegrityError,
            "evidence_id",
        ):
            load_evidence_review(
                self.review_repo,
                self.store,
                review_id=review.review_id,
            )

    def test_database_failure_deletes_encrypted_payload(self):
        repository = mock.Mock()
        repository.save_review.side_effect = RuntimeError("database failed")
        store = mock.Mock()
        with self.assertRaises(EvidenceReviewPersistenceError):
            persist_evidence_review(
                repository,
                store,
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                actor_id=ACTOR,
                reviewed_at=NOW,
            )
        store.put.assert_called_once()
        self.assertEqual(store.delete.call_count, 1)


class EvidenceReviewAuditMetadataTests(unittest.TestCase):
    def test_reviewer_note_key_is_globally_prohibited_from_audit_metadata(self):
        with self.assertRaisesRegex(ValueError, "prohibited"):
            LocalSQLiteCaseRepository._validate_event_payload(
                {"reviewer_note": "private reviewer note"}
            )


class EvidenceReviewSchemaMigrationTests(unittest.TestCase):
    def test_schema_v2_database_migrates_to_v4(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "legacy-v2.db")
            LocalSQLiteCaseRepository(path)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    UPDATE schema_meta
                    SET value = '2'
                    WHERE key = 'schema_version'
                    """
                )
                connection.execute("DROP TABLE evidence_reviews")

            LocalSQLiteCaseRepository(path)
            with sqlite3.connect(path) as connection:
                version = connection.execute(
                    """
                    SELECT value FROM schema_meta
                    WHERE key = 'schema_version'
                    """
                ).fetchone()[0]
                table = connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='evidence_reviews'
                    """
                ).fetchone()
            self.assertEqual(version, "4")
            self.assertEqual(table[0], "evidence_reviews")
            draft_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='draft_versions'
                """
            ).fetchone()
            self.assertEqual(draft_table[0], "draft_versions")


if __name__ == "__main__":
    unittest.main()
