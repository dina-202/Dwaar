"""Unit tests for domain/deadline_engine.py (ARCHITECTURE_SPEC_v1.md §7 STEP 2).

Exactly the 8 cases required by the architecture specification, in order:
  (1) service date known, deadline future
  (2) service date known, deadline passed
  (3) service date unknown, "from date of service"
  (4) service date unknown, "from date of issue"
  (5) hearing date upcoming
  (6) hearing date passed
  (7) deadline within 7 days -> CRITICAL
  (8) no date information at all

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_deadline_engine.py -v
No pytest, no external dependencies, no LLM calls, no network.
"""

import unittest
from datetime import date

from domain.deadline_engine import calculate_deadline
from domain.models import (
    DeadlineConfidence,
    DeadlineStatus,
    HearingStatus,
)

TODAY = date(2026, 8, 28)


class DeadlineEngineSpecCases(unittest.TestCase):
    """The 8 cases required by ARCHITECTURE_SPEC_v1.md §7 STEP 2."""

    def test_01_service_date_known_deadline_future(self):
        result = calculate_deadline(
            notice_date=date(2026, 8, 20),
            service_date=date(2026, 8, 22),
            response_period_text="21 days from the date of service",
            hearing_date_text="04-09-2026",
            today=TODAY,
        )
        self.assertEqual(result.response_period_days, 21)
        self.assertEqual(result.response_deadline, date(2026, 9, 12))
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.CONFIRMED)
        self.assertEqual(result.deadline_status, DeadlineStatus.UPCOMING)
        self.assertEqual(result.days_remaining, 15)
        self.assertEqual(result.hearing_date, date(2026, 9, 4))
        self.assertEqual(result.hearing_status, HearingStatus.UPCOMING)
        self.assertFalse(result.portal_verification_required)
        self.assertEqual(result.notes, [])

    def test_02_service_date_known_deadline_passed(self):
        result = calculate_deadline(
            notice_date=date(2026, 7, 20),
            service_date=date(2026, 7, 22),
            response_period_text="30 days from the date of service",
            hearing_date_text="04-09-2026",
            today=TODAY,
        )
        self.assertEqual(result.response_deadline, date(2026, 8, 21))
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.CONFIRMED)
        self.assertEqual(result.deadline_status, DeadlineStatus.PASSED)
        self.assertLess(result.days_remaining, 0)
        self.assertEqual(result.hearing_status, HearingStatus.UPCOMING)
        self.assertTrue(result.portal_verification_required)

    def test_03_service_date_unknown_from_date_of_service(self):
        result = calculate_deadline(
            notice_date=date(2026, 8, 20),
            service_date=None,
            response_period_text="30 days from the date of service",
            hearing_date_text="22-09-2026",
            today=TODAY,
        )
        self.assertEqual(result.response_period_days, 30)
        self.assertIsNone(result.response_deadline)
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.UNKNOWN)
        self.assertEqual(result.deadline_status, DeadlineStatus.UNKNOWN)
        self.assertIsNone(result.days_remaining)
        self.assertTrue(result.portal_verification_required)
        self.assertTrue(result.notes)

    def test_04_service_date_unknown_from_date_of_issue(self):
        result = calculate_deadline(
            notice_date=date(2026, 8, 20),
            service_date=None,
            response_period_text="30 days from the date of issue",
            hearing_date_text="22-09-2026",
            today=TODAY,
        )
        self.assertEqual(result.response_deadline, date(2026, 9, 19))
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.ESTIMATED)
        self.assertEqual(result.deadline_status, DeadlineStatus.UPCOMING)
        self.assertEqual(result.days_remaining, 22)
        self.assertFalse(result.portal_verification_required)
        self.assertTrue(result.notes)

    def test_05_hearing_date_upcoming(self):
        result = calculate_deadline(
            notice_date=date(2026, 8, 20),
            service_date=date(2026, 8, 22),
            response_period_text="21 days from the date of service",
            hearing_date_text="30-08-2026",
            today=TODAY,
        )
        self.assertEqual(result.hearing_date, date(2026, 8, 30))
        self.assertEqual(result.hearing_status, HearingStatus.UPCOMING)

    def test_06_hearing_date_passed(self):
        result = calculate_deadline(
            notice_date=date(2026, 7, 20),
            service_date=date(2026, 7, 22),
            response_period_text="21 days from the date of service",
            hearing_date_text="10-08-2026",
            today=TODAY,
        )
        self.assertEqual(result.hearing_date, date(2026, 8, 10))
        self.assertEqual(result.hearing_status, HearingStatus.PASSED)

    def test_07_deadline_within_7_days_critical(self):
        result = calculate_deadline(
            notice_date=date(2026, 8, 20),
            service_date=date(2026, 8, 25),
            response_period_text="7 days from the date of service",
            hearing_date_text="",
            today=TODAY,
        )
        self.assertEqual(result.response_deadline, date(2026, 9, 1))
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.CONFIRMED)
        self.assertEqual(result.deadline_status, DeadlineStatus.CRITICAL)
        self.assertEqual(result.days_remaining, 4)
        self.assertIsNone(result.hearing_date)
        self.assertEqual(result.hearing_status, HearingStatus.NOT_SCHEDULED)
        self.assertFalse(result.portal_verification_required)

    def test_08_no_date_information_at_all(self):
        result = calculate_deadline(
            notice_date=None,
            service_date=None,
            response_period_text=None,
            hearing_date_text=None,
            today=TODAY,
        )
        self.assertIsNone(result.notice_date)
        self.assertIsNone(result.service_date)
        self.assertIsNone(result.response_period_days)
        self.assertIsNone(result.response_deadline)
        self.assertEqual(result.deadline_confidence, DeadlineConfidence.UNKNOWN)
        self.assertEqual(result.deadline_status, DeadlineStatus.UNKNOWN)
        self.assertIsNone(result.days_remaining)
        self.assertIsNone(result.hearing_date)
        self.assertEqual(result.hearing_status, HearingStatus.NOT_SCHEDULED)
        self.assertTrue(result.portal_verification_required)
        self.assertTrue(result.notes)


if __name__ == "__main__":
    unittest.main()
