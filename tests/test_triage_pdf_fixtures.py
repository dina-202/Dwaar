"""Offline document-level regressions for recognized triage notice fixtures.

These fixtures are synthetic and contain no real taxpayer data. The tests keep
PDF ingestion and deterministic deadline semantics covered without making any
external LLM/API call.
"""

import unittest
from datetime import date
from pathlib import Path

from domain.deadline_engine import calculate_deadline
from domain.models import (
    DeadlineConfidence,
    DeadlineStatus,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from modules.pdf_reader import extract_document_pages


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "sample_notices"
TODAY = date(2026, 9, 23)


class SyntheticTriagePdfFixtureTests(unittest.TestCase):
    def _read_verified_text(self, filename):
        payload = (FIXTURES / filename).read_bytes()
        pages = extract_document_pages(payload, ocr_empty_pages=False)
        self.assertEqual(len(pages), 1)
        self.assertIs(pages[0].origin, SourceTextOrigin.EMBEDDED)
        self.assertIs(
            pages[0].verification,
            SourceVerificationStatus.VERIFIED,
        )
        self.assertIn(
            "Synthetic fixture only - no real taxpayer or proceeding data.",
            pages[0].text,
        )
        return pages[0].text

    @staticmethod
    def _response_line(text):
        matches = [
            line.strip()
            for line in text.splitlines()
            if "days" in line.lower()
            and (
                "reply" in line.lower()
                or "response" in line.lower()
                or "explanation" in line.lower()
                or "return" in line.lower()
            )
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"expected exactly one response-period line, got {matches!r}"
            )
        return matches[0]

    def test_asmt10_fixture_preserves_operational_source_text(self):
        text = self._read_verified_text(
            "NOTICE_5_ASMT10_Synthetic.pdf"
        )
        self.assertIn("FORM GST ASMT-10", text)
        self.assertIn(
            "Under Section 61, furnish an explanation within fifteen days "
            "from the date of receipt of this notice.",
            text,
        )
        for requested in (
            "1. Purchase register for FY 2025-26",
            "2. Sales register for FY 2025-26",
            "3. Electronic credit ledger for FY 2025-26",
        ):
            self.assertIn(requested, text)
        self.assertIn(
            "Reference is made to Annexure A - discrepancy computation.",
            text,
        )

    def test_asmt10_section_number_is_never_mistaken_for_reply_period(self):
        text = self._read_verified_text(
            "NOTICE_5_ASMT10_Synthetic.pdf"
        )
        response_line = self._response_line(text)

        unresolved = calculate_deadline(
            notice_date=date(2026, 9, 1),
            service_date=None,
            response_period_text=response_line,
            hearing_date_text=None,
            today=TODAY,
        )
        self.assertEqual(unresolved.response_period_days, 15)
        self.assertIsNone(unresolved.response_deadline)
        self.assertEqual(
            unresolved.deadline_confidence,
            DeadlineConfidence.UNKNOWN,
        )
        self.assertEqual(
            unresolved.deadline_status,
            DeadlineStatus.UNKNOWN,
        )

        verified_service = calculate_deadline(
            notice_date=date(2026, 9, 1),
            service_date=date(2026, 9, 3),
            response_period_text=response_line,
            hearing_date_text=None,
            today=TODAY,
        )
        self.assertEqual(verified_service.response_period_days, 15)
        self.assertEqual(
            verified_service.response_deadline,
            date(2026, 9, 18),
        )
        self.assertEqual(
            verified_service.deadline_confidence,
            DeadlineConfidence.CONFIRMED,
        )

    def test_gstr3a_fixture_preserves_receipt_based_period_without_guessing_date(self):
        text = self._read_verified_text(
            "NOTICE_6_GSTR3A_Synthetic.pdf"
        )
        self.assertIn("FORM GSTR-3A", text)
        response_line = self._response_line(text)
        self.assertEqual(
            response_line,
            "Furnish the return within 15 days from the date of receipt "
            "of this notice.",
        )

        result = calculate_deadline(
            notice_date=date(2026, 9, 2),
            service_date=None,
            response_period_text=response_line,
            hearing_date_text=None,
            today=TODAY,
        )
        self.assertEqual(result.response_period_days, 15)
        self.assertIsNone(result.response_deadline)
        self.assertEqual(result.deadline_status, DeadlineStatus.UNKNOWN)
        self.assertTrue(result.portal_verification_required)


if __name__ == "__main__":
    unittest.main()
