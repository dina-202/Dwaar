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

    def environment(self, key=KEY):
        values = dict(os.environ)
        values.update(
            {
                "DWAAR_DB_PATH": str(self.db_path),
                "DWAAR_OBJECT_ROOT": str(self.object_root),
                "DWAAR_BACKUP_ROOT": str(self.backup_root),
                "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                    key
                ).decode("ascii"),
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
