"""Process-level test for Dwaar's product tour-readiness CLI."""

import json
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "product_tour_rehearsal.py"


class ProductTourRehearsalCliTests(unittest.TestCase):
    def test_cli_reports_tour_ready_with_closed_check_set(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 1, completed.stdout)
        payload = json.loads(lines[0])
        self.assertTrue(payload["tour_ready"])
        self.assertEqual(
            [item["code"] for item in payload["checks"]],
            [
                "encrypted_intake",
                "analysis_snapshot",
                "verified_legal_research",
                "legal_uncertainty_preserved",
                "human_evidence_review",
                "unapproved_filing_blocked",
                "draft_review_approval",
                "filing_acknowledgement",
                "unified_timeline",
                "live_storage",
                "wrong_key_blocked",
                "backup_recovery",
                "key_rotation",
            ],
        )
        self.assertEqual(
            {item["status"] for item in payload["checks"]},
            {"pass"},
        )
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
