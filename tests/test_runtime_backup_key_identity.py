"""Tests for Phase 3P.5 backup key identity compatibility."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modules.runtime_backup import (
    RuntimeBackupError,
    create_runtime_backup,
    restore_runtime_backup,
    verify_runtime_backup,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
KEY = b"i" * 32
KEY_ID = "doc-key-2026-a"


class RuntimeBackupKeyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "live" / "dwaar.db"
        self.objects = self.root / "live" / "objects"
        self.backups = self.root / "backups"
        self.db.parent.mkdir(parents=True)
        LocalSQLiteCaseRepository(str(self.db))
        self.objects.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def create_v1(self, backup_id="legacy-v1"):
        return create_runtime_backup(
            db_path=str(self.db),
            object_root=str(self.objects),
            backup_root=str(self.backups),
            backup_id=backup_id,
            created_at=NOW,
            document_key=KEY,
        )

    def create_v2(self, backup_id="identified-v2", key_id=KEY_ID):
        return create_runtime_backup(
            db_path=str(self.db),
            object_root=str(self.objects),
            backup_root=str(self.backups),
            backup_id=backup_id,
            created_at=NOW,
            document_key=KEY,
            document_key_id=key_id,
        )

    def test_v1_backup_remains_verifiable_without_key_identity(self):
        manifest = self.create_v1()
        self.assertEqual(manifest.manifest_version, 1)
        self.assertIsNone(manifest.document_key_id)

        loaded = verify_runtime_backup(
            str(self.backups / "legacy-v1"),
            document_key=KEY,
        )
        self.assertEqual(loaded.manifest_version, 1)
        self.assertIsNone(loaded.document_key_id)

    def test_v1_backup_cannot_satisfy_expected_key_identity(self):
        self.create_v1()
        with self.assertRaisesRegex(
            RuntimeBackupError,
            "identity is unavailable",
        ):
            verify_runtime_backup(
                str(self.backups / "legacy-v1"),
                document_key=KEY,
                expected_document_key_id=KEY_ID,
            )

    def test_v1_backup_remains_clean_target_recoverable(self):
        self.create_v1()
        target_db = self.root / "restore-v1" / "dwaar.db"
        target_objects = self.root / "restore-v1" / "objects"
        restored = restore_runtime_backup(
            str(self.backups / "legacy-v1"),
            target_db_path=str(target_db),
            target_object_root=str(target_objects),
            document_key=KEY,
        )
        self.assertEqual(restored.manifest_version, 1)
        self.assertTrue(target_db.is_file())
        self.assertTrue(target_objects.is_dir())

    def test_v2_backup_records_and_verifies_key_identity(self):
        manifest = self.create_v2()
        self.assertEqual(manifest.manifest_version, 2)
        self.assertEqual(manifest.document_key_id, KEY_ID)

        loaded = verify_runtime_backup(
            str(self.backups / "identified-v2"),
            document_key=KEY,
            expected_document_key_id=KEY_ID,
        )
        self.assertEqual(loaded.document_key_id, KEY_ID)

    def test_v2_expected_key_identity_mismatch_fails_closed(self):
        self.create_v2()
        with self.assertRaisesRegex(
            RuntimeBackupError,
            "identity mismatch",
        ):
            verify_runtime_backup(
                str(self.backups / "identified-v2"),
                document_key=KEY,
                expected_document_key_id="doc-key-2026-b",
            )

    def test_v2_manifest_key_id_is_bound_into_database_aad(self):
        self.create_v2()
        backup = self.backups / "identified-v2"
        path = backup / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["document_key_id"] = "doc-key-2026-b"
        path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            RuntimeBackupError,
            "authentication failed",
        ):
            verify_runtime_backup(
                str(backup),
                document_key=KEY,
            )

    def test_v2_restore_can_require_expected_key_identity(self):
        self.create_v2()
        target_db = self.root / "restore-v2" / "dwaar.db"
        target_objects = self.root / "restore-v2" / "objects"
        restored = restore_runtime_backup(
            str(self.backups / "identified-v2"),
            target_db_path=str(target_db),
            target_object_root=str(target_objects),
            document_key=KEY,
            expected_document_key_id=KEY_ID,
        )
        self.assertEqual(restored.document_key_id, KEY_ID)

    def test_v2_restore_wrong_identity_publishes_nothing(self):
        self.create_v2()
        target_db = self.root / "restore-wrong" / "dwaar.db"
        target_objects = self.root / "restore-wrong" / "objects"
        with self.assertRaisesRegex(
            RuntimeBackupError,
            "identity mismatch",
        ):
            restore_runtime_backup(
                str(self.backups / "identified-v2"),
                target_db_path=str(target_db),
                target_object_root=str(target_objects),
                document_key=KEY,
                expected_document_key_id="doc-key-2026-b",
            )
        self.assertFalse(target_db.exists())
        self.assertFalse(target_objects.exists())

    def test_invalid_key_identity_cannot_create_v2_backup(self):
        with self.assertRaises(ValueError):
            self.create_v2(key_id="unsafe key id")
        self.assertFalse((self.backups / "identified-v2").exists())


if __name__ == "__main__":
    unittest.main()
