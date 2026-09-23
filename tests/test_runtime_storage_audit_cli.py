"""Process-level tests for the live storage audit CLI."""

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
SCRIPT = ROOT / "scripts" / "runtime_storage_audit.py"
KEY = b"a" * 32
STORAGE_KEY = "objects/" + "7" * 32
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class RuntimeStorageAuditCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.db = self.root / "dwaar.db"
        self.objects = self.root / "objects"

        repo = LocalSQLiteCaseRepository(str(self.db))
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
        self.store = EncryptedLocalDocumentStore(str(self.objects), KEY)
        self.store.put(STORAGE_KEY, b"notice")
        repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=6,
                sha256_hex="b" * 64,
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
                "DWAAR_DB_PATH": str(self.db),
                "DWAAR_OBJECT_ROOT": str(self.objects),
                "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                    key
                ).decode("ascii"),
            }
        )
        return values

    def run_cli(self, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
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

    def test_clean_runtime_returns_zero_and_sanitized_counts(self):
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = self.payload(completed)
        self.assertTrue(payload["consistent"])
        self.assertEqual(payload["referenced_object_count"], 1)
        self.assertEqual(payload["object_file_count"], 1)
        self.assertEqual(payload["missing_object_count"], 0)
        self.assertEqual(payload["orphan_object_count"], 0)
        self.assertEqual(payload["authentication_failure_count"], 0)
        rendered = completed.stdout
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(STORAGE_KEY, rendered)
        self.assertNotIn(
            self.environment()["DWAAR_DOCUMENT_KEY_B64"],
            rendered,
        )

    def test_orphan_object_returns_one(self):
        self.store.put("objects/" + "8" * 32, b"orphan")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 1)
        payload = self.payload(completed)
        self.assertFalse(payload["consistent"])
        self.assertEqual(payload["orphan_object_count"], 1)

    def test_wrong_key_returns_one_with_authentication_count(self):
        completed = self.run_cli(
            environment=self.environment(key=b"x" * 32)
        )
        self.assertEqual(completed.returncode, 1)
        payload = self.payload(completed)
        self.assertFalse(payload["consistent"])
        self.assertEqual(payload["authentication_failure_count"], 1)
        self.assertEqual(completed.stderr, "")

    def test_missing_configuration_returns_two(self):
        values = self.environment()
        values.pop("DWAAR_DB_PATH", None)
        completed = self.run_cli(environment=values)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            self.payload(completed),
            {"consistent": False, "error": "configuration_invalid"},
        )


if __name__ == "__main__":
    unittest.main()
