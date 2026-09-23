"""Tests for Phase 3P.1 sanitized runtime readiness."""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain.runtime_readiness_models import (
    RuntimeReadinessCode,
    RuntimeReadinessStatus,
)
from modules.runtime_readiness import evaluate_runtime_readiness


def env(root: Path):
    key = base64.b64encode(b"k" * 32).decode("ascii")
    return {
        "DWAAR_DB_PATH": str(root / "dwaar.db"),
        "DWAAR_OBJECT_ROOT": str(root / "objects"),
        "DWAAR_DOCUMENT_KEY_B64": key,
        "DWAAR_DOCUMENT_KEY_ID": "doc-key-2026-a",
    }


class RuntimeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.ocr_patcher = patch(
            "modules.runtime_readiness._ocr_runtime_available",
            return_value=True,
        )
        self.ocr_patcher.start()
        self.addCleanup(self.ocr_patcher.stop)
        self.llm_patcher = patch(
            "modules.runtime_readiness.llm_runtime_configuration_ready",
            return_value=True,
        )
        self.llm_patcher.start()
        self.addCleanup(self.llm_patcher.stop)

    def test_fresh_valid_runtime_is_ready_and_creates_no_probe_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = evaluate_runtime_readiness(env(root))
            self.assertTrue(report.ready)
            self.assertEqual(
                [item.status for item in report.checks],
                [RuntimeReadinessStatus.PASS] * 9,
            )
            object_root = root / "objects"
            self.assertTrue((root / "dwaar.db").is_file())
            self.assertTrue(object_root.is_dir())
            self.assertEqual(list(object_root.glob("*.dwaar")), [])

    def test_missing_configuration_fails_closed_without_values(self):
        report = evaluate_runtime_readiness({})
        self.assertFalse(report.ready)
        by_code = {item.code: item for item in report.checks}
        self.assertIs(
            by_code[RuntimeReadinessCode.DB_CONFIGURATION].status,
            RuntimeReadinessStatus.BLOCKED,
        )
        self.assertIs(
            by_code[
                RuntimeReadinessCode.OBJECT_STORE_CONFIGURATION
            ].status,
            RuntimeReadinessStatus.BLOCKED,
        )
        self.assertIs(
            by_code[
                RuntimeReadinessCode.DOCUMENT_KEY_CONFIGURATION
            ].status,
            RuntimeReadinessStatus.BLOCKED,
        )
        self.assertIs(
            by_code[
                RuntimeReadinessCode.DOCUMENT_KEY_ID_CONFIGURATION
            ].status,
            RuntimeReadinessStatus.BLOCKED,
        )
        rendered = repr(report)
        self.assertNotIn("DWAAR_DB_PATH", rendered)
        self.assertNotIn("DWAAR_DOCUMENT_KEY_B64", rendered)

    def test_invalid_document_key_blocks_storage_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            values = env(Path(temp))
            values["DWAAR_DOCUMENT_KEY_B64"] = "not-base64"
            report = evaluate_runtime_readiness(values)
            by_code = {item.code: item for item in report.checks}
            self.assertIs(
                by_code[
                    RuntimeReadinessCode.DOCUMENT_KEY_CONFIGURATION
                ].status,
                RuntimeReadinessStatus.BLOCKED,
            )
            self.assertIs(
                by_code[
                    RuntimeReadinessCode.OBJECT_STORE_ROUND_TRIP
                ].status,
                RuntimeReadinessStatus.BLOCKED,
            )

    def test_invalid_document_key_id_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            values = env(Path(temp))
            values["DWAAR_DOCUMENT_KEY_ID"] = "bad id with spaces"
            report = evaluate_runtime_readiness(values)
            by_code = {item.code: item for item in report.checks}
            self.assertIs(
                by_code[
                    RuntimeReadinessCode.DOCUMENT_KEY_ID_CONFIGURATION
                ].status,
                RuntimeReadinessStatus.BLOCKED,
            )
            self.assertFalse(report.ready)

    def test_database_path_with_missing_parent_blocks_db_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = env(root)
            values["DWAAR_DB_PATH"] = str(
                root / "missing-parent" / "dwaar.db"
            )
            report = evaluate_runtime_readiness(values)
            by_code = {item.code: item for item in report.checks}
            self.assertIs(
                by_code[
                    RuntimeReadinessCode.DB_OPEN_AND_MIGRATION
                ].status,
                RuntimeReadinessStatus.BLOCKED,
            )
            self.assertIs(
                by_code[RuntimeReadinessCode.DB_INTEGRITY].status,
                RuntimeReadinessStatus.BLOCKED,
            )

    def test_corrupt_database_fails_without_leaking_file_contents_or_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = env(root)
            db_path = Path(values["DWAAR_DB_PATH"])
            db_path.write_bytes(b"NOT A SQLITE DATABASE SECRET-SENTINEL")
            report = evaluate_runtime_readiness(values)
            self.assertFalse(report.ready)
            rendered = repr(report)
            self.assertNotIn(str(db_path), rendered)
            self.assertNotIn("SECRET-SENTINEL", rendered)

    def test_object_root_that_is_a_file_blocks_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = env(root)
            object_path = root / "object-file"
            object_path.write_text("not a directory", encoding="utf-8")
            values["DWAAR_OBJECT_ROOT"] = str(object_path)
            report = evaluate_runtime_readiness(values)
            by_code = {item.code: item for item in report.checks}
            self.assertIs(
                by_code[
                    RuntimeReadinessCode.OBJECT_STORE_ROUND_TRIP
                ].status,
                RuntimeReadinessStatus.BLOCKED,
            )

    def test_missing_ocr_runtime_blocks_readiness_without_details(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "modules.runtime_readiness._ocr_runtime_available",
                return_value=False,
            ):
                report = evaluate_runtime_readiness(env(Path(temp)))
            by_code = {item.code: item for item in report.checks}
            item = by_code[RuntimeReadinessCode.OCR_RUNTIME]
            self.assertIs(item.status, RuntimeReadinessStatus.BLOCKED)
            self.assertFalse(report.ready)
            self.assertEqual(
                item.message,
                (
                    "Scanned-PDF OCR runtime is unavailable. "
                    "Install/configure Tesseract English OCR before serving "
                    "professional traffic."
                ),
            )
            self.assertNotIn("path", item.message.lower())
            self.assertNotIn("exception", item.message.lower())

    def test_missing_llm_configuration_blocks_readiness_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "modules.runtime_readiness.llm_runtime_configuration_ready",
                return_value=False,
            ):
                report = evaluate_runtime_readiness(env(Path(temp)))
            by_code = {item.code: item for item in report.checks}
            item = by_code[RuntimeReadinessCode.LLM_CONFIGURATION]
            self.assertIs(item.status, RuntimeReadinessStatus.BLOCKED)
            self.assertFalse(report.ready)
            self.assertEqual(
                item.message,
                (
                    "AI analysis configuration is missing or invalid. "
                    "Configure at least one analysis credential before "
                    "serving professional traffic."
                ),
            )
            rendered = repr(report)
            self.assertNotIn("GEMINI_API_KEY", rendered)
            self.assertNotIn("gemini_01", rendered)

    def test_check_codes_are_unique_and_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            report = evaluate_runtime_readiness(env(Path(temp)))
            codes = [item.code for item in report.checks]
            self.assertEqual(len(codes), len(set(codes)))
            self.assertEqual(
                codes,
                [
                    RuntimeReadinessCode.DB_CONFIGURATION,
                    RuntimeReadinessCode.OBJECT_STORE_CONFIGURATION,
                    RuntimeReadinessCode.DOCUMENT_KEY_CONFIGURATION,
                    RuntimeReadinessCode.DOCUMENT_KEY_ID_CONFIGURATION,
                    RuntimeReadinessCode.OCR_RUNTIME,
                    RuntimeReadinessCode.LLM_CONFIGURATION,
                    RuntimeReadinessCode.DB_OPEN_AND_MIGRATION,
                    RuntimeReadinessCode.DB_INTEGRITY,
                    RuntimeReadinessCode.OBJECT_STORE_ROUND_TRIP,
                ],
            )


if __name__ == "__main__":
    unittest.main()
