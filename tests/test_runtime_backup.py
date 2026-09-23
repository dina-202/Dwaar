"""Tests for Phase 3P.2 encrypted runtime backup integrity."""

import sqlite3
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
from modules.runtime_backup import (
    RuntimeBackupError,
    create_runtime_backup,
    verify_runtime_backup,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 7, 30, tzinfo=timezone.utc)
STORAGE_KEY = "objects/" + "a" * 32
PLAINTEXT = b"professional notice payload"
DOCUMENT_KEY = b"k" * 32


class RuntimeBackupFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "live" / "dwaar.db"
        self.object_root = self.root / "live" / "objects"
        self.backup_root = self.root / "backups"
        self.db_path.parent.mkdir(parents=True)
        self.repo = LocalSQLiteCaseRepository(str(self.db_path))
        self.repo.create_firm(Firm("F-1", "Firm", NOW))
        self.repo.create_client(Client("C-1", "F-1", "Client", NOW))
        self.repo.create_case(
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
        self.store = EncryptedLocalDocumentStore(
            str(self.object_root),
            DOCUMENT_KEY,
        )
        self.store.put(STORAGE_KEY, PLAINTEXT)
        self.repo.add_document_ref(
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

    def tearDown(self):
        self.temp.cleanup()

    def create(self, backup_id="backup-001"):
        return create_runtime_backup(
            db_path=str(self.db_path),
            object_root=str(self.object_root),
            backup_root=str(self.backup_root),
            backup_id=backup_id,
            created_at=NOW,
            document_key=DOCUMENT_KEY,
        )


class RuntimeBackupTests(RuntimeBackupFixture):
    def test_backup_round_trip_is_verified_without_decrypting_objects(self):
        manifest = self.create()
        backup_dir = self.backup_root / "backup-001"
        loaded = verify_runtime_backup(str(backup_dir), document_key=DOCUMENT_KEY)

        self.assertEqual(loaded, manifest)
        self.assertEqual(manifest.object_count, 1)
        self.assertEqual(manifest.objects[0].storage_key, STORAGE_KEY)
        self.assertEqual(manifest.source_schema_version, 7)
        encrypted_db = backup_dir / "dwaar.sqlite3.enc"
        self.assertTrue(encrypted_db.is_file())
        self.assertNotIn(b"Client", encrypted_db.read_bytes())
        self.assertNotIn(b"Matter", encrypted_db.read_bytes())
        copied = backup_dir / "objects" / ("a" * 32 + ".dwaar")
        self.assertTrue(copied.is_file())
        self.assertNotIn(PLAINTEXT, copied.read_bytes())

        manifest_text = (backup_dir / "manifest.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Client", manifest_text)
        self.assertNotIn("Matter", manifest_text)
        self.assertNotIn(str(self.db_path), manifest_text)
        self.assertNotIn(str(self.object_root), manifest_text)

    def test_live_mutation_after_backup_does_not_change_backup(self):
        self.create()
        backup_dir = self.backup_root / "backup-001"
        before = (backup_dir / "dwaar.sqlite3.enc").read_bytes()
        self.repo.create_client(Client("C-2", "F-1", "Later", NOW))
        self.assertEqual(
            (backup_dir / "dwaar.sqlite3.enc").read_bytes(),
            before,
        )
        verify_runtime_backup(str(backup_dir), document_key=DOCUMENT_KEY)

    def test_missing_referenced_live_object_aborts_without_publishing(self):
        self.store.delete(STORAGE_KEY)
        with self.assertRaisesRegex(RuntimeBackupError, "missing encrypted"):
            self.create()
        self.assertFalse((self.backup_root / "backup-001").exists())
        if self.backup_root.exists():
            self.assertEqual(
                [
                    item
                    for item in self.backup_root.iterdir()
                    if item.name.startswith(".tmp-")
                ],
                [],
            )

    def test_tampered_backup_object_is_rejected(self):
        self.create()
        backup_dir = self.backup_root / "backup-001"
        object_path = backup_dir / "objects" / ("a" * 32 + ".dwaar")
        object_path.write_bytes(object_path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(RuntimeBackupError, "object hash"):
            verify_runtime_backup(str(backup_dir), document_key=DOCUMENT_KEY)

    def test_tampered_backup_database_is_rejected(self):
        self.create()
        backup_dir = self.backup_root / "backup-001"
        database = backup_dir / "dwaar.sqlite3.enc"
        database.write_bytes(database.read_bytes() + b"tamper")
        with self.assertRaisesRegex(RuntimeBackupError, "database hash"):
            verify_runtime_backup(str(backup_dir), document_key=DOCUMENT_KEY)

    def test_extra_backup_object_is_rejected(self):
        self.create()
        backup_dir = self.backup_root / "backup-001"
        (backup_dir / "objects" / ("b" * 32 + ".dwaar")).write_bytes(
            b"unexpected"
        )
        with self.assertRaisesRegex(RuntimeBackupError, "unexpected file set"):
            verify_runtime_backup(str(backup_dir), document_key=DOCUMENT_KEY)

    def test_duplicate_backup_id_refuses_overwrite(self):
        self.create()
        with self.assertRaisesRegex(RuntimeBackupError, "already exists"):
            self.create()

    def test_backup_root_inside_live_object_store_is_rejected(self):
        with self.assertRaisesRegex(RuntimeBackupError, "live object store"):
            create_runtime_backup(
                db_path=str(self.db_path),
                object_root=str(self.object_root),
                backup_root=str(self.object_root / "backups"),
                backup_id="backup-001",
                created_at=NOW,
                document_key=DOCUMENT_KEY,
            )

    def test_unsupported_schema_version_fails_closed(self):
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.execute(
                """
                UPDATE schema_meta
                SET value = '999'
                WHERE key = 'schema_version'
                """
            )
        with self.assertRaisesRegex(RuntimeBackupError, "unsupported"):
            self.create()

    def test_invalid_storage_key_in_database_fails_closed(self):
        with sqlite3.connect(str(self.db_path)) as connection:
            connection.execute(
                """
                UPDATE case_documents
                SET storage_key = 'unsafe/path'
                WHERE document_id = 'DOC-1'
                """
            )
        with self.assertRaisesRegex(RuntimeBackupError, "invalid encrypted"):
            self.create()

    def test_wrong_document_key_cannot_verify_backup(self):
        self.create()
        with self.assertRaisesRegex(
            RuntimeBackupError, "authentication failed"
        ):
            verify_runtime_backup(
                str(self.backup_root / "backup-001"),
                document_key=b"z" * 32,
            )

    def test_manifest_directory_name_binding_is_verified(self):
        self.create()
        source = self.backup_root / "backup-001"
        renamed = self.backup_root / "renamed"
        source.rename(renamed)
        with self.assertRaisesRegex(RuntimeBackupError, "directory name"):
            verify_runtime_backup(
                str(renamed),
                document_key=DOCUMENT_KEY,
            )


if __name__ == "__main__":
    unittest.main()
