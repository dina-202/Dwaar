"""Process-level tests for the runtime preflight command."""

import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "runtime_preflight.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.runtime_readiness import _ocr_runtime_available


class RuntimePreflightCliTests(unittest.TestCase):
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

    def test_valid_runtime_returns_zero_and_sanitized_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            environment = dict(os.environ)
            environment.update(
                {
                    "DWAAR_DB_PATH": str(root / "dwaar.db"),
                    "DWAAR_OBJECT_ROOT": str(root / "objects"),
                    "DWAAR_DOCUMENT_KEY_B64": base64.b64encode(
                        b"q" * 32
                    ).decode("ascii"),
                    "DWAAR_DOCUMENT_KEY_ID": "doc-key-2026-cli",
                }
            )
            completed = subprocess.run(
                [sys.executable, str(SCRIPT)],
                cwd=str(ROOT),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        payload = self.payload(completed)
        ocr_available = _ocr_runtime_available()
        self.assertEqual(
            completed.returncode,
            0 if ocr_available else 1,
            completed.stderr,
        )
        self.assertIs(payload["ready"], ocr_available)
        self.assertEqual(len(payload["checks"]), 8)
        ocr_checks = [
            item for item in payload["checks"]
            if item["code"] == "ocr_runtime"
        ]
        self.assertEqual(len(ocr_checks), 1)
        self.assertEqual(
            ocr_checks[0]["status"],
            "pass" if ocr_available else "blocked",
        )
        rendered = completed.stdout
        self.assertNotIn(str(root), rendered)
        self.assertNotIn(environment["DWAAR_DOCUMENT_KEY_B64"], rendered)

    def test_missing_runtime_configuration_returns_one(self):
        environment = dict(os.environ)
        for name in (
            "DWAAR_DB_PATH",
            "DWAAR_OBJECT_ROOT",
            "DWAAR_DOCUMENT_KEY_B64",
            "DWAAR_DOCUMENT_KEY_ID",
        ):
            environment.pop(name, None)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(ROOT),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        payload = self.payload(completed)
        self.assertFalse(payload["ready"])
        by_code = {item["code"]: item for item in payload["checks"]}
        for code in (
            "db_configuration",
            "object_store_configuration",
            "document_key_configuration",
            "document_key_id_configuration",
            "db_open_and_migration",
            "db_integrity",
            "object_store_round_trip",
        ):
            self.assertEqual(by_code[code]["status"], "blocked")
        self.assertIn(by_code["ocr_runtime"]["status"], {"pass", "blocked"})
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
