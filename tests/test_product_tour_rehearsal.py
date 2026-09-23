"""Tour-readiness tests for the deterministic Dwaar product rehearsal."""

import tempfile
import unittest

from modules.product_rehearsal import run_product_rehearsal


EXPECTED_CODES = (
    "encrypted_intake",
    "analysis_snapshot",
    "verified_legal_research",
    "human_evidence_review",
    "draft_review_approval",
    "filing_acknowledgement",
    "unified_timeline",
    "live_storage",
    "backup_recovery",
    "key_rotation",
)


class ProductTourRehearsalTests(unittest.TestCase):
    def test_full_offline_product_rehearsal_is_tour_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_product_rehearsal(temp)

        self.assertTrue(report.tour_ready)
        self.assertEqual(
            tuple(item.code for item in report.checks),
            EXPECTED_CODES,
        )
        self.assertTrue(all(item.passed for item in report.checks))
        self.assertTrue(all(item.detail for item in report.checks))

    def test_report_contains_no_secret_key_material(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_product_rehearsal(temp)

        rendered = repr(report)
        self.assertNotIn("YWFhYWFhYWFh", rendered)
        self.assertNotIn("YmJiYmJiYmJi", rendered)
        self.assertNotIn("professional notice payload", rendered)


if __name__ == "__main__":
    unittest.main()
