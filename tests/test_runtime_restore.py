"""Tests for Phase 3P.3 clean-target runtime recovery."""

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
    restore_runtime_backup,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 8, 30, tzinfo=timezone.utc)
KEY = b"r" * 32
STORAGE_KEY = "objects/" + "d" * 32
NOTICE = b"restorable professional notice"


class RuntimeRestoreFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.live_db = self.root / "live" / "dwaar.db"
        self.live_objects = self.root / "live" / "objects"
        self.backups = self.root / "backups"
        self.target_db = self.root / "recovery" / "dwaar.db"
        self.target_objects = self.root / "recovery" / "objects"
        self.live_db.parent.mkdir(parents=True)

        repo = LocalSQLiteCaseRepository(str(self.live_db))
        repo.create_firm(Firm("F-1", "Recovery Firm", NOW))
        repo.create_client(
            Client("C-1", "F-1", "Recovery Client", NOW)
        )
        repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Recovery Matter",
                status=CaseStatus.INTAKE,
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        store = EncryptedLocalDocumentStore(
            str(self.live_objects),
            KEY,
        )
        store.put(STORAGE_KEY, NOTICE)
        repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=len(NOTICE),
                sha256_hex="1" * 64,
                storage_key=STORAGE_KEY,
                created_at=NOW,
            )
        )
        create_runtime_backup(
            db_path=str(self.live_db),
            object_root=str(self.live_objects),
            backup_root=str(self.backups),
            backup_id="restore-source",
            created_at=NOW,
            document_key=KEY,
        )
        self.backup_dir = self.backups / "restore-source"

    def tearDown(self):
        self.temp.cleanup()

    def restore(self, key=KEY):
        return restore_runtime_backup(
            str(self.backup_dir),
            target_db_path=str(self.target_db),
            target_object_root=str(self.target_objects),
            document_key=key,
        )


class RuntimeRestoreTests(RuntimeRestoreFixture):
    def test_restore_to_clean_target_rehydrates_normal_runtime(self):
        manifest = self.restore()

        self.assertEqual(manifest.backup_id, "restore-source")
        self.assertTrue(self.target_db.is_file())
        self.assertTrue(self.target_objects.is_dir())

        repo = LocalSQLiteCaseRepository(str(self.target_db))
        firm = repo.get_firm("F-1")
        client = repo.get_client("C-1")
        case = repo.get_case("CASE-1")
        documents = repo.list_document_refs("CASE-1")
        self.assertEqual(len(documents), 1)
        document = documents[0]

        self.assertEqual(firm.display_name, "Recovery Firm")
        self.assertEqual(client.display_name, "Recovery Client")
        self.assertEqual(case.title, "Recovery Matter")
        self.assertEqual(document.storage_key, STORAGE_KEY)

        store = EncryptedLocalDocumentStore(
            str(self.target_objects),
            KEY,
        )
        self.assertEqual(store.get(STORAGE_KEY), NOTICE)

    def test_existing_target_database_is_never_overwritten(self):
        self.target_db.parent.mkdir(parents=True)
        self.target_db.write_bytes(b"existing-runtime")
        with self.assertRaisesRegex(
            RuntimeBackupError, "database already exists"
        ):
            self.restore()
        self.assertEqual(
            self.target_db.read_bytes(),
            b"existing-runtime",
        )
        self.assertFalse(self.target_objects.exists())

    def test_nonempty_object_target_is_never_overwritten(self):
        self.target_objects.mkdir(parents=True)
        sentinel = self.target_objects / "keep.txt"
        sentinel.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(
            RuntimeBackupError, "not empty"
        ):
            self.restore()
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"),
            "existing",
        )
        self.assertFalse(self.target_db.exists())

    def test_empty_object_target_is_allowed(self):
        self.target_objects.mkdir(parents=True)
        self.restore()
        self.assertTrue(self.target_db.is_file())
        self.assertTrue(self.target_objects.is_dir())
        self.assertEqual(
            EncryptedLocalDocumentStore(
                str(self.target_objects), KEY
            ).get(STORAGE_KEY),
            NOTICE,
        )

    def test_wrong_key_fails_before_target_publication(self):
        with self.assertRaises(RuntimeBackupError):
            self.restore(key=b"x" * 32)
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_objects.exists())

    def test_tampered_backup_fails_before_target_publication(self):
        encrypted_db = self.backup_dir / "dwaar.sqlite3.enc"
        encrypted_db.write_bytes(
            encrypted_db.read_bytes() + b"tamper"
        )
        with self.assertRaises(RuntimeBackupError):
            self.restore()
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_objects.exists())

    def test_restore_leaves_no_staging_artifacts(self):
        self.restore()
        recovery_root = self.target_db.parent
        leftovers = [
            item.name
            for item in recovery_root.iterdir()
            if item.name.startswith(".dwaar-restore-")
        ]
        self.assertEqual(leftovers, [])

    def test_restore_preserves_encrypted_object_bytes_exactly(self):
        source = (
            self.backup_dir
            / "objects"
            / ("d" * 32 + ".dwaar")
        ).read_bytes()
        self.restore()
        restored = (
            self.target_objects
            / ("d" * 32 + ".dwaar")
        ).read_bytes()
        self.assertEqual(restored, source)
        self.assertNotIn(NOTICE, restored)


if __name__ == "__main__":
    unittest.main()
