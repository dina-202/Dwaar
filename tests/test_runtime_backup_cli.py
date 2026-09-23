"""Process-level tests for the runtime backup operator CLI."""

import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

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
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "runtime_backup.py"
NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
KEY = b"p" * 32
STORAGE_KEY = "objects/" + "c" * 32
KEY_ID = "doc-key-cli-a"


class RuntimeBackupCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.db_path = self.root / "live" / "dwaar.db"
        self.object_root = self.root / "live" / "objects"
        self.backup_root = self.root / "backups"
        self.db_path.parent.mkdir(parents=True)
        repo = LocalSQLiteCaseRepository(str(self.db_path))
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
        store = EncryptedLocalDocumentStore(str(self.object_root), KEY)
        payload = b"notice"
        store.put(STORAGE_KEY, payload)
        repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=len(payload),
                sha256_hex="1" * 64,
                storage_key=STORAGE_KEY,
                created_at=NOW,
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def environment(self, key=KEY, key_id=KEY_ID):
        values = dict(os.environ)
        values.update(
            {
                "DWAAR_DB_PATH": str(self.db_path),
                "DWAAR_OBJECT_ROOT": str(self.object_root),
                "DWAAR_BACKUP_ROOT": str(self.backup_root),
                "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                    key
                ).decode("ascii"),
                "DWAAR_DOCUMENT_KEY_ID": key_id,
            }
        )
        return values

    def run_cli(self, *args, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(ROOT),
            env=environment or self.environment(),
            capture_output=True,
            text=True,
            check=False,
        )

    def payload(self, completed):
        lines = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 1, completed.stdout + completed.stderr)
        return json.loads(lines[0])

    def test_create_then_verify_returns_sanitized_json(self):
        created = self.run_cli(
            "create",
            "--backup-id",
            "cli-backup",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        create_payload = self.payload(created)
        self.assertEqual(
            create_payload,
            {
                "backup_id": "cli-backup",
                "object_count": 1,
                "ok": True,
                "operation": "create",
                "source_schema_version": 6,
            },
        )

        backup_dir = self.backup_root / "cli-backup"
        verified = self.run_cli("verify", str(backup_dir))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        verify_payload = self.payload(verified)
        self.assertEqual(verify_payload["backup_id"], "cli-backup")
        self.assertTrue(verify_payload["ok"])
        combined = created.stdout + verified.stdout
        self.assertNotIn(str(self.db_path), combined)
        self.assertNotIn(str(self.object_root), combined)
        self.assertNotIn(
            self.environment()["DWAAR_DOCUMENT_KEY_B64"],
            combined,
        )

    def test_create_then_restore_to_clean_target(self):
        created = self.run_cli(
            "create",
            "--backup-id",
            "cli-restore",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        target_db = self.root / "recovered" / "dwaar.db"
        target_objects = self.root / "recovered" / "objects"

        restored = self.run_cli(
            "restore",
            str(self.backup_root / "cli-restore"),
            "--target-db",
            str(target_db),
            "--target-objects",
            str(target_objects),
        )
        self.assertEqual(restored.returncode, 0, restored.stderr)
        payload = self.payload(restored)
        self.assertEqual(
            payload,
            {
                "backup_id": "cli-restore",
                "object_count": 1,
                "ok": True,
                "operation": "restore",
                "source_schema_version": 6,
            },
        )

        repo = LocalSQLiteCaseRepository(str(target_db))
        self.assertEqual(repo.get_case("CASE-1").title, "Matter")
        store = EncryptedLocalDocumentStore(
            str(target_objects),
            KEY,
        )
        self.assertEqual(store.get(STORAGE_KEY), b"notice")

        combined = created.stdout + restored.stdout
        self.assertNotIn(str(target_db), combined)
        self.assertNotIn(str(target_objects), combined)

    def test_restore_refuses_existing_target_and_returns_sanitized_error(self):
        created = self.run_cli(
            "create",
            "--backup-id",
            "cli-restore",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        target_db = self.root / "recovered" / "dwaar.db"
        target_db.parent.mkdir(parents=True)
        target_db.write_bytes(b"sentinel")

        restored = self.run_cli(
            "restore",
            str(self.backup_root / "cli-restore"),
            "--target-db",
            str(target_db),
            "--target-objects",
            str(self.root / "recovered" / "objects"),
        )
        self.assertEqual(restored.returncode, 1)
        self.assertEqual(
            self.payload(restored),
            {"error": "restore_failed", "ok": False},
        )
        self.assertEqual(target_db.read_bytes(), b"sentinel")
        self.assertNotIn(str(target_db), restored.stdout)
        self.assertEqual(restored.stderr, "")

    def test_verify_with_wrong_key_fails_safely(self):
        created = self.run_cli(
            "create",
            "--backup-id",
            "cli-backup",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        wrong = self.run_cli(
            "verify",
            str(self.backup_root / "cli-backup"),
            environment=self.environment(key=b"x" * 32),
        )
        self.assertEqual(wrong.returncode, 1)
        self.assertEqual(
            self.payload(wrong),
            {"error": "verification_failed", "ok": False},
        )
        self.assertEqual(wrong.stderr, "")

    def test_create_missing_key_id_is_configuration_error(self):
        values = self.environment()
        values.pop("DWAAR_DOCUMENT_KEY_ID", None)
        completed = self.run_cli(
            "create",
            "--backup-id",
            "missing-key-id",
            environment=values,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            self.payload(completed),
            {"error": "configuration_invalid", "ok": False},
        )

    def test_verify_with_wrong_key_id_fails_safely(self):
        created = self.run_cli(
            "create",
            "--backup-id",
            "cli-key-id",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        wrong = self.run_cli(
            "verify",
            str(self.backup_root / "cli-key-id"),
            environment=self.environment(
                key=KEY,
                key_id="doc-key-cli-b",
            ),
        )
        self.assertEqual(wrong.returncode, 1)
        self.assertEqual(
            self.payload(wrong),
            {"error": "verification_failed", "ok": False},
        )

    def test_create_missing_backup_root_is_configuration_error(self):
        values = self.environment()
        values.pop("DWAAR_BACKUP_ROOT", None)
        completed = self.run_cli("create", environment=values)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            self.payload(completed),
            {"error": "configuration_invalid", "ok": False},
        )


if __name__ == "__main__":
    unittest.main()
