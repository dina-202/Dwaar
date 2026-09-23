"""Tests for Phase 3P.7 clean-target document-key rotation rehearsal."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
)
from domain.models import NoticeForm, ProceedingType
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.runtime_key_rotation import (
    RuntimeKeyRotationError,
    rehearse_document_key_rotation,
)
from modules.runtime_storage_audit import audit_runtime_storage
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
OLD_KEY = b"a" * 32
NEW_KEY = b"b" * 32
OLD_ID = "doc-key-a"
NEW_ID = "doc-key-b"
STORAGE_KEY = "objects/" + "c" * 32
PLAINTEXT = b"notice payload for rotation"


class RuntimeKeyRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_db = self.root / "source" / "dwaar.db"
        self.source_objects = self.root / "source" / "objects"
        self.target_db = self.root / "target" / "dwaar.db"
        self.target_objects = self.root / "target" / "objects"
        self.source_db.parent.mkdir(parents=True)

        repo = LocalSQLiteCaseRepository(str(self.source_db))
        repo.create_firm(Firm("F-1", "Firm", NOW))
        repo.create_client(Client("C-1", "F-1", "Client", NOW))
        repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.INTAKE,
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        self.source_store = EncryptedLocalDocumentStore(
            str(self.source_objects),
            OLD_KEY,
        )
        self.source_store.put(STORAGE_KEY, PLAINTEXT)
        repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=len(PLAINTEXT),
                sha256_hex="1" * 64,
                storage_key=STORAGE_KEY,
                created_at=NOW,
            )
        )
        self.source_ciphertext = (
            self.source_objects / ("c" * 32 + ".dwaar")
        ).read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def rotate(self):
        return rehearse_document_key_rotation(
            source_db_path=str(self.source_db),
            source_object_root=str(self.source_objects),
            old_document_key=OLD_KEY,
            old_document_key_id=OLD_ID,
            new_document_key=NEW_KEY,
            new_document_key_id=NEW_ID,
            target_db_path=str(self.target_db),
            target_object_root=str(self.target_objects),
        )

    def test_rotation_preserves_data_and_storage_key_identity(self):
        report = self.rotate()
        self.assertEqual(report.old_key_id, OLD_ID)
        self.assertEqual(report.new_key_id, NEW_ID)
        self.assertEqual(report.object_count, 1)
        self.assertEqual(report.schema_version, 6)

        target_repo = LocalSQLiteCaseRepository(str(self.target_db))
        refs = target_repo.list_document_refs("CASE-1")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].storage_key, STORAGE_KEY)

        target_store = EncryptedLocalDocumentStore(
            str(self.target_objects),
            NEW_KEY,
        )
        self.assertEqual(target_store.get(STORAGE_KEY), PLAINTEXT)

    def test_source_runtime_remains_unchanged_and_usable(self):
        self.rotate()
        source_path = self.source_objects / ("c" * 32 + ".dwaar")
        self.assertEqual(source_path.read_bytes(), self.source_ciphertext)
        self.assertEqual(self.source_store.get(STORAGE_KEY), PLAINTEXT)
        self.assertTrue(
            audit_runtime_storage(
                db_path=str(self.source_db),
                object_root=str(self.source_objects),
                document_key=OLD_KEY,
            ).consistent
        )

    def test_rotated_ciphertext_changes_and_old_key_cannot_authenticate_target(self):
        self.rotate()
        target_path = self.target_objects / ("c" * 32 + ".dwaar")
        self.assertNotEqual(
            target_path.read_bytes(),
            self.source_ciphertext,
        )
        old_store = EncryptedLocalDocumentStore(
            str(self.target_objects),
            OLD_KEY,
        )
        with self.assertRaises(Exception):
            old_store.get(STORAGE_KEY)
        self.assertFalse(
            audit_runtime_storage(
                db_path=str(self.target_db),
                object_root=str(self.target_objects),
                document_key=OLD_KEY,
            ).consistent
        )

    def test_new_key_cannot_authenticate_source_runtime(self):
        self.rotate()
        self.assertFalse(
            audit_runtime_storage(
                db_path=str(self.source_db),
                object_root=str(self.source_objects),
                document_key=NEW_KEY,
            ).consistent
        )

    def test_same_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must differ"):
            rehearse_document_key_rotation(
                source_db_path=str(self.source_db),
                source_object_root=str(self.source_objects),
                old_document_key=OLD_KEY,
                old_document_key_id=OLD_ID,
                new_document_key=OLD_KEY,
                new_document_key_id=NEW_ID,
                target_db_path=str(self.target_db),
                target_object_root=str(self.target_objects),
            )

    def test_same_key_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "key ID must differ"):
            rehearse_document_key_rotation(
                source_db_path=str(self.source_db),
                source_object_root=str(self.source_objects),
                old_document_key=OLD_KEY,
                old_document_key_id=OLD_ID,
                new_document_key=NEW_KEY,
                new_document_key_id=OLD_ID,
                target_db_path=str(self.target_db),
                target_object_root=str(self.target_objects),
            )

    def test_existing_target_database_is_never_overwritten(self):
        self.target_db.parent.mkdir(parents=True)
        self.target_db.write_bytes(b"sentinel")
        with self.assertRaisesRegex(
            RuntimeKeyRotationError,
            "target database already exists",
        ):
            self.rotate()
        self.assertEqual(self.target_db.read_bytes(), b"sentinel")

    def test_nonempty_target_object_directory_is_rejected(self):
        self.target_objects.mkdir(parents=True)
        (self.target_objects / "sentinel").write_bytes(b"x")
        with self.assertRaisesRegex(
            RuntimeKeyRotationError,
            "not empty",
        ):
            self.rotate()
        self.assertFalse(self.target_db.exists())

    def test_inconsistent_source_fails_before_target_publication(self):
        (self.source_objects / ("c" * 32 + ".dwaar")).unlink()
        with self.assertRaisesRegex(
            RuntimeKeyRotationError,
            "source runtime storage is inconsistent",
        ):
            self.rotate()
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_objects.exists())

    def test_invalid_key_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            rehearse_document_key_rotation(
                source_db_path=str(self.source_db),
                source_object_root=str(self.source_objects),
                old_document_key=OLD_KEY,
                old_document_key_id="bad id with spaces",
                new_document_key=NEW_KEY,
                new_document_key_id=NEW_ID,
                target_db_path=str(self.target_db),
                target_object_root=str(self.target_objects),
            )


if __name__ == "__main__":
    unittest.main()
