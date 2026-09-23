"""Process-level tests for the Phase 3P.4 operator health CLI."""

import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from modules.runtime_backup import create_runtime_backup
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operator_health.py"
KEY = b"o" * 32
KEY_ID = "doc-key-operator-a"


class OperatorHealthCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.db_path = self.root / "live" / "dwaar.db"
        self.object_root = self.root / "live" / "objects"
        self.backup_root = self.root / "backups"
        self.db_path.parent.mkdir(parents=True)
        LocalSQLiteCaseRepository(str(self.db_path))
        self.object_root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def environment(self, key=KEY, key_id=KEY_ID):
        values = dict(os.environ)
        values.update(
            {
                "DWAAR_DB_PATH": str(self.db_path),
                "DWAAR_OBJECT_ROOT": str(self.object_root),
                "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                    key
                ).decode("ascii"),
                "DWAAR_DOCUMENT_KEY_ID": key_id,
            }
        )
        return values

    def create_backup(self, backup_id, created_at):
        create_runtime_backup(
            db_path=str(self.db_path),
            object_root=str(self.object_root),
            backup_root=str(self.backup_root),
            backup_id=backup_id,
            created_at=created_at,
            document_key=KEY,
            document_key_id=KEY_ID,
        )
        return self.backup_root / backup_id

    def run_cli(self, backup_dir, max_age, environment=None):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(backup_dir),
                "--max-backup-age-hours",
                str(max_age),
            ],
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

    def test_fresh_verified_backup_returns_zero_and_sanitized_json(self):
        now = datetime.now(timezone.utc)
        backup = self.create_backup(
            "operator-fresh",
            now - timedelta(minutes=15),
        )
        completed = self.run_cli(backup, 24)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = self.payload(completed)
        self.assertTrue(payload["healthy"])
        self.assertEqual(
            [item["status"] for item in payload["checks"]],
            ["pass", "pass", "pass", "pass", "pass"],
        )
        rendered = completed.stdout
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("operator-fresh", rendered)
        self.assertNotIn(
            self.environment()["DWAAR_DOCUMENT_KEY_B64"],
            rendered,
        )

    def test_stale_backup_returns_one_not_configuration_error(self):
        now = datetime.now(timezone.utc)
        backup = self.create_backup(
            "operator-stale",
            now - timedelta(hours=48),
        )
        completed = self.run_cli(backup, 24)
        self.assertEqual(completed.returncode, 1)
        payload = self.payload(completed)
        self.assertFalse(payload["healthy"])
        checks = {item["code"]: item for item in payload["checks"]}
        self.assertEqual(checks["runtime_preflight"]["status"], "pass")
        self.assertEqual(
            checks["live_storage_consistency"]["status"], "pass"
        )
        self.assertEqual(checks["backup_verification"]["status"], "pass")
        self.assertEqual(checks["backup_key_identity"]["status"], "pass")
        self.assertEqual(checks["backup_freshness"]["status"], "blocked")

    def test_wrong_backup_key_returns_one_with_no_secret_detail(self):
        backup = self.create_backup(
            "operator-key",
            datetime.now(timezone.utc),
        )
        completed = self.run_cli(
            backup,
            24,
            environment=self.environment(key=b"x" * 32),
        )
        self.assertEqual(completed.returncode, 1)
        payload = self.payload(completed)
        self.assertFalse(payload["healthy"])
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("operator-key", completed.stdout)

    def test_invalid_age_policy_returns_two(self):
        backup = self.create_backup(
            "operator-invalid",
            datetime.now(timezone.utc),
        )
        completed = self.run_cli(backup, 0)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            self.payload(completed),
            {"error": "health_check_invalid", "healthy": False},
        )


if __name__ == "__main__":
    unittest.main()
