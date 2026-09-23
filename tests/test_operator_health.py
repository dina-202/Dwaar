"""Tests for Phase 3P.4 sanitized operator health posture."""

import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from domain.operator_health_models import (
    OperatorHealthCode,
    OperatorHealthStatus,
)
from modules.runtime_backup import create_runtime_backup
from modules.operator_health import evaluate_operator_health
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
KEY = b"h" * 32
KEY_ID = "doc-key-health-a"


def environment(root: Path, key=KEY, key_id=KEY_ID):
    return {
        "DWAAR_DB_PATH": str(root / "live" / "dwaar.db"),
        "DWAAR_OBJECT_ROOT": str(root / "live" / "objects"),
        "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(key).decode("ascii"),
        "DWAAR_DOCUMENT_KEY_ID": key_id,
    }


class OperatorHealthTests(unittest.TestCase):
    def setUp(self):
        self.ocr_patcher = patch(
            "modules.runtime_readiness._ocr_runtime_available",
            return_value=True,
        )
        self.ocr_patcher.start()
        self.addCleanup(self.ocr_patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = environment(self.root)
        db_path = Path(self.env["DWAAR_DB_PATH"])
        db_path.parent.mkdir(parents=True)
        LocalSQLiteCaseRepository(str(db_path))
        object_root = Path(self.env["DWAAR_OBJECT_ROOT"])
        object_root.mkdir(parents=True)
        self.backups = self.root / "backups"

    def tearDown(self):
        self.temp.cleanup()

    def backup(self, *, created_at=NOW - timedelta(hours=2)):
        create_runtime_backup(
            db_path=self.env["DWAAR_DB_PATH"],
            object_root=self.env["DWAAR_OBJECT_ROOT"],
            backup_root=str(self.backups),
            backup_id="health-backup",
            created_at=created_at,
            document_key=KEY,
            document_key_id=KEY_ID,
        )
        return self.backups / "health-backup"

    def test_valid_runtime_and_fresh_verified_backup_are_healthy(self):
        report = evaluate_operator_health(
            backup_dir=str(self.backup()),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        self.assertTrue(report.healthy)
        self.assertAlmostEqual(report.backup_age_hours, 2.0)
        self.assertEqual(
            [item.status for item in report.checks],
            [OperatorHealthStatus.PASS] * 5,
        )

    def test_stale_backup_blocks_only_freshness(self):
        report = evaluate_operator_health(
            backup_dir=str(
                self.backup(created_at=NOW - timedelta(hours=30))
            ),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertFalse(report.healthy)
        self.assertIs(
            by_code[OperatorHealthCode.RUNTIME_PREFLIGHT].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.LIVE_STORAGE_CONSISTENCY].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_KEY_IDENTITY].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_FRESHNESS].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertAlmostEqual(report.backup_age_hours, 30.0)

    def test_corrupt_backup_blocks_verification_and_freshness(self):
        backup = self.backup()
        encrypted_db = backup / "dwaar.sqlite3.enc"
        encrypted_db.write_bytes(encrypted_db.read_bytes() + b"tamper")
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.RUNTIME_PREFLIGHT].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_KEY_IDENTITY].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_FRESHNESS].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertIsNone(report.backup_age_hours)

    def test_wrong_key_can_pass_empty_runtime_probe_but_not_backup_auth(self):
        backup = self.backup()
        wrong = environment(self.root, key=b"x" * 32)
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=wrong,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.RUNTIME_PREFLIGHT].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertFalse(report.healthy)

    def test_runtime_failure_does_not_hide_valid_backup(self):
        backup = self.backup()
        broken = dict(self.env)
        broken["DWAAR_DB_PATH"] = str(
            self.root / "missing" / "dwaar.db"
        )
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=broken,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.RUNTIME_PREFLIGHT].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_KEY_IDENTITY].status,
            OperatorHealthStatus.PASS,
        )
        self.assertFalse(report.healthy)

    def test_same_key_with_wrong_generation_id_blocks_identity(self):
        backup = self.backup()
        wrong_id = environment(
            self.root,
            key=KEY,
            key_id="doc-key-health-b",
        )
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=wrong_id,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_KEY_IDENTITY].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertFalse(report.healthy)

    def test_legacy_v1_backup_is_recoverable_but_not_rotation_ready(self):
        legacy_root = self.root / "legacy"
        create_runtime_backup(
            db_path=self.env["DWAAR_DB_PATH"],
            object_root=self.env["DWAAR_OBJECT_ROOT"],
            backup_root=str(legacy_root),
            backup_id="legacy-v1",
            created_at=NOW - timedelta(hours=1),
            document_key=KEY,
        )
        report = evaluate_operator_health(
            backup_dir=str(legacy_root / "legacy-v1"),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.PASS,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_KEY_IDENTITY].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertFalse(report.healthy)

    def test_live_orphan_blocks_health_without_invalidating_backup(self):
        backup = self.backup()
        from modules.encrypted_document_store import EncryptedLocalDocumentStore

        EncryptedLocalDocumentStore(
            self.env["DWAAR_OBJECT_ROOT"],
            KEY,
        ).put(
            "objects/" + "9" * 32,
            b"orphan",
        )
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[OperatorHealthCode.LIVE_STORAGE_CONSISTENCY].status,
            OperatorHealthStatus.BLOCKED,
        )
        self.assertIs(
            by_code[OperatorHealthCode.BACKUP_VERIFICATION].status,
            OperatorHealthStatus.PASS,
        )
        self.assertFalse(report.healthy)

    def test_future_backup_timestamp_fails_freshness_closed(self):
        report = evaluate_operator_health(
            backup_dir=str(
                self.backup(created_at=NOW + timedelta(minutes=1))
            ),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        self.assertFalse(report.healthy)
        self.assertIsNone(report.backup_age_hours)

    def test_output_does_not_contain_paths_keys_or_backup_id(self):
        backup = self.backup()
        report = evaluate_operator_health(
            backup_dir=str(backup),
            max_backup_age_hours=24,
            now=NOW,
            environment=self.env,
        )
        rendered = repr(report)
        self.assertNotIn(str(backup), rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("health-backup", rendered)
        self.assertNotIn(self.env["DWAAR_DOCUMENT_KEY_B64"], rendered)

    def test_invalid_policy_arguments_are_rejected(self):
        backup = self.backup()
        with self.assertRaises(ValueError):
            evaluate_operator_health(
                backup_dir=str(backup),
                max_backup_age_hours=0,
                now=NOW,
                environment=self.env,
            )
        with self.assertRaises(ValueError):
            evaluate_operator_health(
                backup_dir="",
                max_backup_age_hours=24,
                now=NOW,
                environment=self.env,
            )
        with self.assertRaises(ValueError):
            evaluate_operator_health(
                backup_dir=str(backup),
                max_backup_age_hours=24,
                now=NOW.replace(tzinfo=None),
                environment=self.env,
            )


if __name__ == "__main__":
    unittest.main()
