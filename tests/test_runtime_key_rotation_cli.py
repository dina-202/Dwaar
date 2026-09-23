"""Process-level tests for the document-key rotation rehearsal CLI."""

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
SCRIPT = ROOT / "scripts" / "runtime_key_rotation.py"
NOW = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
OLD_KEY = b"a" * 32
NEW_KEY = b"b" * 32
STORAGE_KEY = "objects/" + "d" * 32


class RuntimeKeyRotationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
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
        store = EncryptedLocalDocumentStore(
            str(self.source_objects),
            OLD_KEY,
        )
        store.put(STORAGE_KEY, b"notice")
        repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=6,
                sha256_hex="1" * 64,
                storage_key=STORAGE_KEY,
                created_at=NOW,
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def environment(self):
        env = dict(os.environ)
        env.update(
            {
                "DWAAR_DB_PATH": str(self.source_db),
                "DWAAR_OBJECT_ROOT": str(self.source_objects),
                "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                    OLD_KEY
                ).decode("ascii"),
                "DWAAR_DOCUMENT_KEY_ID": "doc-key-a",
                "DWAAR_NEW_DOCUMENT_KEY_B64": base64.b64encode(
                    NEW_KEY
                ).decode("ascii"),
                "DWAAR_NEW_DOCUMENT_KEY_ID": "doc-key-b",
            }
        )
        return env

    def run_cli(self, environment):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--target-db",
                str(self.target_db),
                "--target-objects",
                str(self.target_objects),
            ],
            cwd=str(ROOT),
            env=environment,
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
        self.assertEqual(
            len(lines),
            1,
            "unexpected CLI output; stdout="
            + repr(completed.stdout)
            + " stderr="
            + repr(completed.stderr),
        )
        return json.loads(lines[0])

    def test_rotation_cli_rehearses_clean_target(self):
        completed = self.run_cli(self.environment())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.payload(completed),
            {
                "new_key_id": "doc-key-b",
                "object_count": 1,
                "ok": True,
                "old_key_id": "doc-key-a",
                "operation": "key_rotation_rehearsal",
                "schema_version": 7,
            },
        )
        target_store = EncryptedLocalDocumentStore(
            str(self.target_objects),
            NEW_KEY,
        )
        self.assertEqual(target_store.get(STORAGE_KEY), b"notice")

        rendered = completed.stdout + completed.stderr
        self.assertNotIn(str(self.source_db), rendered)
        self.assertNotIn(str(self.target_db), rendered)
        self.assertNotIn(
            self.environment()["DWAAR_DOCUMENT_KEY_B64"],
            rendered,
        )
        self.assertNotIn(
            self.environment()["DWAAR_NEW_DOCUMENT_KEY_B64"],
            rendered,
        )

    def test_missing_new_key_returns_sanitized_configuration_error(self):
        env = self.environment()
        env.pop("DWAAR_NEW_DOCUMENT_KEY_B64")
        completed = self.run_cli(env)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            self.payload(completed),
            {"error": "configuration_invalid", "ok": False},
        )
        self.assertFalse(self.target_db.exists())

    def test_existing_target_returns_sanitized_failure(self):
        self.target_db.parent.mkdir(parents=True)
        self.target_db.write_bytes(b"sentinel")
        completed = self.run_cli(self.environment())
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            self.payload(completed),
            {"error": "rotation_rehearsal_failed", "ok": False},
        )
        self.assertEqual(self.target_db.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
