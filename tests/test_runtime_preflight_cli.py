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


class RuntimePreflightCliTests(unittest.TestCase):
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
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ready"])
        self.assertEqual(len(payload["checks"]), 6)
        rendered = completed.stdout
        self.assertNotIn(str(root), rendered)
        self.assertNotIn(environment["DWAAR_DOCUMENT_KEY_B64"], rendered)

    def test_missing_runtime_configuration_returns_one(self):
        environment = dict(os.environ)
        for name in (
            "DWAAR_DB_PATH",
            "DWAAR_OBJECT_ROOT",
            "DWAAR_DOCUMENT_KEY_B64",
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
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ready"])
        self.assertEqual(
            {item["status"] for item in payload["checks"]},
            {"blocked"},
        )
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
