"""Unit tests for Phase 2 Step 7.2: the deterministic Preflight Engine.

Verifies domain/preflight_engine.py against the authoritative
ARCHITECTURE_SPEC v1.1 §18 preflight contract:

  - identifier mapping (§18.5) derived from validated FactTypes only;
  - absence-based safety (§18.3): PARTIAL / FAILED / NO_INPUT extraction
    yields UNKNOWN completeness statuses even when positive facts exist;
  - portal verification flag (§18.6) and authority verification flag
    (§18.8) are always True in Phase 2;
  - authority details mapping (§18.7): PRESENT / PARTIAL / MISSING /
    UNKNOWN;
  - pass-through fact ID indexing (§18.14) preserving accepted order;
  - deterministic stated-due-date parsing (§18.10): the five supported
    formats parse; impossible, ambiguous, two-digit-year, relative and
    US-style tokens stay unparsed;
  - deadline comparison (§18.9, §18.11–§18.12): MATCH / CONFLICT /
    CANNOT_COMPARE, including the unresolved-fact rule;
  - inputs are never mutated; behavior is identical for DEEP_WORKFLOW,
    TRIAGE_ONLY and UNKNOWN classifications;
  - non-ExtractedFact entries in facts are ignored without crashing;
  - module purity: stdlib + domain.models only, no LLM, no network, no
    Deadline Engine calls, no evidence-gap creation, no legal-validity
    output.

Every test is fully offline — no LLM call, no network.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_preflight_engine.py -v
No pytest, no external dependencies.
"""

import copy
import pathlib
import unittest
from datetime import date

from domain import preflight_engine
from domain.models import (
    AuthorityDetailsStatus,
    ClassificationConfidence,
    CommunicationIdentifierStatus,
    DeadlineConfidence,
    DeadlineConflictStatus,
    DeadlineResult,
    DeadlineStatus,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactStatus,
    FactType,
    HearingStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    PreflightResult,
    ProceedingType,
    SupportLevel,
)
from domain.preflight_engine import run_preflight

# The exact §18.13 field contract, in order (mirrors Step 7.1 models test).
EXPECTED_PREFLIGHT_FIELDS = [
    "fact_extraction_status",
    "communication_identifier_status",
    "portal_verification_required",
    "authority_details_status",
    "authority_verification_required",
    "stated_due_date_fact_ids",
    "parsed_stated_due_dates",
    "unparsed_stated_due_date_fact_ids",
    "deadline_conflict_status",
    "hearing_fact_ids",
    "requested_document_fact_ids",
    "referenced_annexure_fact_ids",
]

DUE_DATE = date(2026, 9, 17)
OTHER_DUE_DATE = date(2026, 9, 25)


def make_fact(fact_id, fact_type, source_text=None, claim=None):
    """Build a CONFIRMED ExtractedFact of the given type."""
    return ExtractedFact(
        fact_id=fact_id,
        claim=claim if claim is not None else "Document-native fact",
        status=FactStatus.CONFIRMED,
        source_text=source_text,
        fact_type=fact_type,
    )


def make_extraction_result(facts, status=FactExtractionStatus.SUCCESS):
    """Build a FactExtractionResult around the given facts."""
    return FactExtractionResult(facts=list(facts), status=status)


def make_classification(support_level=SupportLevel.DEEP_WORKFLOW):
    """Build a valid NoticeClassification, with a selectable support level."""
    return NoticeClassification(
        notice_family=NoticeFamily.DEMAND_ADJUDICATION,
        notice_form=NoticeForm.DRC_01,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        support_level=support_level,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=["form id matched"],
    )


def make_deadline(response_deadline=None):
    """Build a DeadlineResult with an optional calculated deadline."""
    return DeadlineResult(
        notice_date=date(2026, 8, 17),
        service_date=None,
        response_period_days=None,
        response_deadline=response_deadline,
        deadline_confidence=DeadlineConfidence.UNKNOWN,
        deadline_status=DeadlineStatus.UNKNOWN,
        days_remaining=None,
        hearing_date=None,
        hearing_status=HearingStatus.NOT_SCHEDULED,
        portal_verification_required=True,
        notes=[],
    )


def run_preflight_on(
    facts,
    status=FactExtractionStatus.SUCCESS,
    deadline_result=None,
    classification=None,
):
    """Run preflight over the given facts with default-friendly inputs."""
    return run_preflight(
        extraction_result=make_extraction_result(facts, status=status),
        classification=(
            classification
            if classification is not None
            else make_classification()
        ),
        deadline_result=deadline_result,
    )


class IdentifierMappingTests(unittest.TestCase):
    """§18.5: RFN/DIN presence from FactTypes, SUCCESS only."""

    def test_rfn_only_maps_to_rfn_present(self):
        result = run_preflight_on([make_fact("F-001", FactType.RFN)])
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )

    def test_din_only_maps_to_din_present(self):
        result = run_preflight_on([make_fact("F-001", FactType.DIN)])
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.DIN_PRESENT,
        )

    def test_both_maps_to_both_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.DIN),
            ]
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.BOTH_PRESENT,
        )

    def test_neither_maps_to_neither_found(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.NOTICE_REFERENCE)]
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.NEITHER_FOUND,
        )

    def test_duplicate_rfn_facts_still_rfn_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.RFN),
            ]
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )

    def test_mapping_relies_on_fact_type_not_claim_text(self):
        # An RFN-typed fact stays an RFN fact even when its claim talks
        # about DIN ...
        result = run_preflight_on(
            [
                make_fact(
                    "F-001",
                    FactType.RFN,
                    claim="RFN present; no DIN appears in this notice",
                )
            ]
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )
        # ... and a fact whose claim mentions an RFN is NOT an RFN fact
        # unless its FactType says so.
        result = run_preflight_on(
            [
                make_fact(
                    "F-001",
                    FactType.OTHER_NOTICE_FACT,
                    claim="RFN: RFN-2026-0001 is printed on page 1",
                )
            ]
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.NEITHER_FOUND,
        )


class ExtractionStatusSafetyTests(unittest.TestCase):
    """§18.3: no absence-based conclusions from non-SUCCESS extraction."""

    def test_partial_extraction_identifier_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.PARTIAL
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.UNKNOWN,
        )

    def test_failed_extraction_identifier_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.FAILED
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.UNKNOWN,
        )

    def test_no_input_extraction_identifier_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.NO_INPUT
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.UNKNOWN,
        )

    def test_partial_with_positive_rfn_reports_rfn_present(self):
        # PARTIAL blocks absence conclusions, not positive observations.
        result = run_preflight_on(
            [make_fact("F-001", FactType.RFN)],
            status=FactExtractionStatus.PARTIAL,
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )

    def test_partial_with_positive_din_reports_din_present(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.DIN)],
            status=FactExtractionStatus.PARTIAL,
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.DIN_PRESENT,
        )

    def test_partial_with_both_identifiers_reports_both_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.DIN),
            ],
            status=FactExtractionStatus.PARTIAL,
        )
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.BOTH_PRESENT,
        )


class PortalVerificationTests(unittest.TestCase):
    """§18.6: portal_verification_required is always True in Phase 2."""

    def test_portal_verification_true_for_rfn_present(self):
        result = run_preflight_on([make_fact("F-001", FactType.RFN)])
        self.assertIs(result.portal_verification_required, True)

    def test_portal_verification_true_for_din_present(self):
        result = run_preflight_on([make_fact("F-001", FactType.DIN)])
        self.assertIs(result.portal_verification_required, True)

    def test_portal_verification_true_for_both_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.DIN),
            ]
        )
        self.assertIs(result.portal_verification_required, True)

    def test_portal_verification_true_for_neither_found(self):
        result = run_preflight_on([])
        self.assertIs(result.portal_verification_required, True)

    def test_portal_verification_true_for_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.PARTIAL
        )
        self.assertIs(result.portal_verification_required, True)


class AuthorityMappingTests(unittest.TestCase):
    """§18.7: PRESENT / PARTIAL / MISSING from authority FactTypes."""

    def test_designation_and_office_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.AUTHORITY_DESIGNATION),
                make_fact("F-002", FactType.AUTHORITY_OFFICE),
            ]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PRESENT
        )

    def test_designation_only_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.AUTHORITY_DESIGNATION)]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )

    def test_office_only_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.AUTHORITY_OFFICE)]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )

    def test_name_only_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.AUTHORITY_NAME)]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )

    def test_jurisdiction_only_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.JURISDICTION_TEXT)]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )

    def test_no_authority_facts_missing(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.NOTICE_REFERENCE)]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.MISSING
        )

    def test_core_plus_supplementary_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.AUTHORITY_DESIGNATION),
                make_fact("F-002", FactType.AUTHORITY_OFFICE),
                make_fact("F-003", FactType.AUTHORITY_NAME),
                make_fact("F-004", FactType.JURISDICTION_TEXT),
            ]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PRESENT
        )

    def test_mapping_relies_on_fact_type_not_claim_text(self):
        # An authority-worded claim on a non-authority FactType does not
        # count as authority presence ...
        result = run_preflight_on(
            [
                make_fact(
                    "F-001",
                    FactType.OTHER_NOTICE_FACT,
                    claim="Joint Commissioner, CGST, Pune",
                )
            ]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.MISSING
        )
        # ... and a designation fact whose claim mentions an office still
        # provides designation only.
        result = run_preflight_on(
            [
                make_fact(
                    "F-001",
                    FactType.AUTHORITY_DESIGNATION,
                    claim="Joint Commissioner, CGST, Pune office",
                )
            ]
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )


class AuthorityExtractionSafetyTests(unittest.TestCase):
    """§18.3/§18.7: partial extraction preserves positive authority facts."""

    def test_partial_extraction_authority_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.PARTIAL
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.UNKNOWN
        )

    def test_failed_extraction_authority_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.FAILED
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.UNKNOWN
        )

    def test_no_input_extraction_authority_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.NO_INPUT
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.UNKNOWN
        )

    def test_partial_with_core_facts_reports_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.AUTHORITY_DESIGNATION),
                make_fact("F-002", FactType.AUTHORITY_OFFICE),
            ],
            status=FactExtractionStatus.PARTIAL,
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PRESENT
        )

    def test_partial_with_one_authority_fact_reports_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.AUTHORITY_DESIGNATION)],
            status=FactExtractionStatus.PARTIAL,
        )
        self.assertIs(
            result.authority_details_status, AuthorityDetailsStatus.PARTIAL
        )


class AuthorityVerificationTests(unittest.TestCase):
    """§18.8: authority_verification_required is always True in Phase 2."""

    def test_authority_verification_true_for_present(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.AUTHORITY_DESIGNATION),
                make_fact("F-002", FactType.AUTHORITY_OFFICE),
            ]
        )
        self.assertIs(result.authority_verification_required, True)

    def test_authority_verification_true_for_partial(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.AUTHORITY_DESIGNATION)]
        )
        self.assertIs(result.authority_verification_required, True)

    def test_authority_verification_true_for_missing(self):
        result = run_preflight_on([])
        self.assertIs(result.authority_verification_required, True)

    def test_authority_verification_true_for_unknown(self):
        result = run_preflight_on(
            [], status=FactExtractionStatus.PARTIAL
        )
        self.assertIs(result.authority_verification_required, True)


class FactIdIndexingTests(unittest.TestCase):
    """§18.14: pass-through indexing preserves accepted fact order."""

    def test_stated_due_date_ids_preserve_order(self):
        result = run_preflight_on(
            [
                make_fact("F-009", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-011", FactType.STATED_DUE_DATE, "17-09-2026"),
            ]
        )
        self.assertEqual(
            result.stated_due_date_fact_ids, ["F-009", "F-002", "F-011"]
        )

    def test_hearing_ids_preserve_order(self):
        result = run_preflight_on(
            [
                make_fact("F-004", FactType.HEARING_DETAILS),
                make_fact("F-001", FactType.HEARING_DETAILS),
                make_fact("F-007", FactType.HEARING_DETAILS),
            ]
        )
        self.assertEqual(
            result.hearing_fact_ids, ["F-004", "F-001", "F-007"]
        )

    def test_requested_document_ids_preserve_order(self):
        result = run_preflight_on(
            [
                make_fact("F-006", FactType.REQUESTED_DOCUMENT),
                make_fact("F-003", FactType.REQUESTED_DOCUMENT),
            ]
        )
        self.assertEqual(
            result.requested_document_fact_ids, ["F-006", "F-003"]
        )

    def test_referenced_annexure_ids_preserve_order(self):
        result = run_preflight_on(
            [
                make_fact("F-008", FactType.REFERENCED_ANNEXURE),
                make_fact("F-005", FactType.REFERENCED_ANNEXURE),
                make_fact("F-002", FactType.REFERENCED_ANNEXURE),
            ]
        )
        self.assertEqual(
            result.referenced_annexure_fact_ids, ["F-008", "F-005", "F-002"]
        )

    def test_unrelated_facts_not_indexed(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.NOTICE_REFERENCE),
                make_fact("F-002", FactType.TAXPAYER_NAME),
                make_fact("F-003", FactType.STATED_AMOUNT),
                make_fact("F-004", FactType.STATUTORY_SECTION),
                make_fact("F-005", FactType.DEPARTMENT_ALLEGATION),
                make_fact("F-006", FactType.HEARING_DETAILS),
            ]
        )
        self.assertEqual(result.hearing_fact_ids, ["F-006"])
        self.assertEqual(result.requested_document_fact_ids, [])
        self.assertEqual(result.referenced_annexure_fact_ids, [])
        self.assertEqual(result.stated_due_date_fact_ids, [])


class DateParsingValidTests(unittest.TestCase):
    """§18.10: each supported format parses to the expected date."""

    def assert_parsed(self, source_text, expected):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, source_text)]
        )
        self.assertEqual(result.parsed_stated_due_dates, [expected])
        self.assertEqual(result.unparsed_stated_due_date_fact_ids, [])

    def test_dd_mm_yyyy_dashes(self):
        self.assert_parsed("17-09-2026", date(2026, 9, 17))

    def test_dd_mm_yyyy_slashes_day_first(self):
        self.assert_parsed("17/09/2026", date(2026, 9, 17))

    def test_yyyy_mm_dd(self):
        self.assert_parsed("2026-09-17", date(2026, 9, 17))

    def test_dd_month_yyyy(self):
        self.assert_parsed("17 September 2026", date(2026, 9, 17))

    def test_dd_mon_yyyy(self):
        self.assert_parsed("17 Sep 2026", date(2026, 9, 17))

    def test_surrounding_prose_accepted(self):
        self.assert_parsed("Reply on or before 17-09-2026.", date(2026, 9, 17))

    def test_leap_day_accepted(self):
        self.assert_parsed("29-02-2028", date(2028, 2, 29))

    def test_repeated_same_date_token_resolves_to_one_date(self):
        # Two tokens of the same date resolve to ONE distinct date: the
        # fact parses successfully and contributes a single parsed entry.
        result = run_preflight_on(
            [
                make_fact(
                    "F-001",
                    FactType.STATED_DUE_DATE,
                    "Reply by 17-09-2026 or 17/09/2026",
                )
            ]
        )
        self.assertEqual(result.parsed_stated_due_dates, [date(2026, 9, 17)])
        self.assertEqual(result.unparsed_stated_due_date_fact_ids, [])


class DateParsingUnsupportedTests(unittest.TestCase):
    """§18.10: unsupported or ambiguous text stays unparsed."""

    def assert_unparsed(self, source_text):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, source_text)]
        )
        self.assertEqual(result.parsed_stated_due_dates, [])
        self.assertEqual(
            result.unparsed_stated_due_date_fact_ids, ["F-001"]
        )
        return result

    def test_impossible_date_unparsed(self):
        result = self.assert_unparsed("31-02-2026")
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_two_digit_year_unparsed(self):
        self.assert_unparsed("17-09-26")

    def test_relative_date_unparsed(self):
        self.assert_unparsed("Reply within 7 days")

    def test_no_date_unparsed(self):
        self.assert_unparsed("Please submit your reply at the earliest")

    def test_multiple_distinct_dates_in_one_fact_unparsed(self):
        # Two distinct supported dates in one fact: ambiguous, unparsed
        # rather than arbitrarily choosing one (§18.10).
        self.assert_unparsed("Reply by 17-09-2026 or 25-09-2026")

    def test_us_style_slash_rejected_as_invalid_day_first(self):
        # 09/17/2026 is invalid under the Indian day-first convention
        # (month 17) and must NOT be reinterpreted as 17 September.
        self.assert_unparsed("09/17/2026")


class MultipleDueDateFactsTests(unittest.TestCase):
    """§18.9/§18.11: multiple due-date facts and comparison safety."""

    def test_two_facts_same_date_preserved_in_parsed_list(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "17-09-2026"),
            ],
            deadline_result=make_deadline(DUE_DATE),
        )
        # Both entries preserved, in fact order — no deduplication.
        self.assertEqual(
            result.parsed_stated_due_dates, [DUE_DATE, DUE_DATE]
        )
        self.assertEqual(result.unparsed_stated_due_date_fact_ids, [])
        # One unique date -> still comparable.
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )

    def test_two_facts_distinct_dates_cannot_compare(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "25-09-2026"),
            ],
            deadline_result=make_deadline(DUE_DATE),
        )
        self.assertEqual(
            result.parsed_stated_due_dates, [DUE_DATE, OTHER_DUE_DATE]
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_one_parsed_one_unparsed_cannot_compare(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "Reply soon"),
            ],
            deadline_result=make_deadline(DUE_DATE),
        )
        self.assertEqual(result.parsed_stated_due_dates, [DUE_DATE])
        self.assertEqual(
            result.unparsed_stated_due_date_fact_ids, ["F-002"]
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_only_unparsed_cannot_compare(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.STATED_DUE_DATE, "Reply soon"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "tomorrow"),
            ],
            deadline_result=make_deadline(DUE_DATE),
        )
        self.assertEqual(result.parsed_stated_due_dates, [])
        self.assertEqual(
            result.unparsed_stated_due_date_fact_ids, ["F-001", "F-002"]
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )


class DeadlineComparisonTests(unittest.TestCase):
    """§18.12: MATCH / CONFLICT / CANNOT_COMPARE."""

    def test_unique_stated_date_matching_deadline_matches(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026")],
            deadline_result=make_deadline(date(2026, 9, 17)),
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )

    def test_unique_stated_date_different_deadline_conflicts(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026")],
            deadline_result=make_deadline(date(2026, 9, 20)),
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.CONFLICT
        )

    def test_no_deadline_result_cannot_compare(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026")],
            deadline_result=None,
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_none_response_deadline_cannot_compare(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026")],
            deadline_result=make_deadline(None),
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_no_stated_due_date_cannot_compare(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.NOTICE_REFERENCE)],
            deadline_result=make_deadline(date(2026, 9, 17)),
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )

    def test_unresolved_due_date_fact_forces_cannot_compare(self):
        # One parsed fact that matches the deadline is still NOT enough
        # when another due-date fact could not be resolved (§18.11).
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026"),
                make_fact("F-002", FactType.STATED_DUE_DATE, "Reply soon"),
            ],
            deadline_result=make_deadline(date(2026, 9, 17)),
        )
        self.assertIs(
            result.deadline_conflict_status,
            DeadlineConflictStatus.CANNOT_COMPARE,
        )


class ReadOnlyBehaviorTests(unittest.TestCase):
    """Preflight never mutates any of its inputs."""

    def test_deadline_result_not_mutated(self):
        deadline_result = make_deadline(date(2026, 9, 17))
        before = copy.deepcopy(deadline_result)
        result = run_preflight_on(
            [make_fact("F-001", FactType.STATED_DUE_DATE, "17-09-2026")],
            deadline_result=deadline_result,
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )
        self.assertEqual(deadline_result, before)

    def test_classification_not_mutated(self):
        classification = make_classification()
        before = copy.deepcopy(classification)
        run_preflight_on(
            [make_fact("F-001", FactType.RFN)],
            classification=classification,
        )
        self.assertEqual(classification, before)

    def test_extracted_fact_objects_not_mutated(self):
        facts = [
            make_fact("F-001", FactType.RFN),
            make_fact("F-002", FactType.STATED_DUE_DATE, "17-09-2026"),
        ]
        before = copy.deepcopy(facts)
        run_preflight_on(facts)
        self.assertEqual(facts, before)

    def test_fact_extraction_result_not_mutated(self):
        extraction_result = make_extraction_result(
            [make_fact("F-001", FactType.RFN)]
        )
        before = copy.deepcopy(extraction_result)
        run_preflight(
            extraction_result=extraction_result,
            classification=make_classification(),
        )
        self.assertEqual(extraction_result, before)


class SupportLevelNeutralityTests(unittest.TestCase):
    """§18.4: identical behavior for every support level."""

    def _result_for(self, support_level):
        return run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.STATED_DUE_DATE, "17-09-2026"),
            ],
            deadline_result=make_deadline(date(2026, 9, 17)),
            classification=make_classification(support_level),
        )

    def test_deep_workflow(self):
        result = self._result_for(SupportLevel.DEEP_WORKFLOW)
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )
        self.assertEqual(result.parsed_stated_due_dates, [DUE_DATE])

    def test_triage_only(self):
        result = self._result_for(SupportLevel.TRIAGE_ONLY)
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )
        self.assertEqual(result.parsed_stated_due_dates, [DUE_DATE])

    def test_unknown(self):
        result = self._result_for(SupportLevel.UNKNOWN)
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )
        self.assertIs(
            result.deadline_conflict_status, DeadlineConflictStatus.MATCH
        )
        self.assertEqual(result.parsed_stated_due_dates, [DUE_DATE])

    def test_all_support_levels_produce_identical_results(self):
        deep = self._result_for(SupportLevel.DEEP_WORKFLOW)
        triage = self._result_for(SupportLevel.TRIAGE_ONLY)
        unknown = self._result_for(SupportLevel.UNKNOWN)
        self.assertEqual(deep, triage)
        self.assertEqual(triage, unknown)


class RuntimeToleranceTests(unittest.TestCase):
    """Non-ExtractedFact entries are ignored without crashing."""

    def test_non_extracted_fact_items_ignored_without_crash(self):
        result = run_preflight_on(
            [
                make_fact("F-001", FactType.RFN),
                make_fact("F-002", FactType.STATED_DUE_DATE, "17-09-2026"),
                "not a fact",
                None,
                42,
                {"fact_type": "din"},
            ]
        )
        # The junk DIN-like dict is ignored: identifier mapping sees only
        # the real RFN fact.
        self.assertIs(
            result.communication_identifier_status,
            CommunicationIdentifierStatus.RFN_PRESENT,
        )
        # Junk entries contribute no IDs and do not disturb parsing.
        self.assertEqual(
            result.stated_due_date_fact_ids, ["F-002"]
        )
        self.assertEqual(result.parsed_stated_due_dates, [DUE_DATE])
        self.assertEqual(result.hearing_fact_ids, [])
        self.assertEqual(result.requested_document_fact_ids, [])
        self.assertEqual(result.referenced_annexure_fact_ids, [])


class OutputContractTests(unittest.TestCase):
    """§18.13: exactly a PreflightResult, fully populated."""

    def test_result_is_preflight_result(self):
        result = run_preflight_on([make_fact("F-001", FactType.RFN)])
        self.assertIs(type(result), PreflightResult)

    def test_fact_extraction_status_copied_exactly(self):
        for status in FactExtractionStatus:
            with self.subTest(status=status):
                result = run_preflight_on(
                    [make_fact("F-001", FactType.RFN)], status=status
                )
                self.assertIs(result.fact_extraction_status, status)

    def test_all_twelve_fields_populated(self):
        result = run_preflight_on(
            [make_fact("F-001", FactType.RFN)],
            status=FactExtractionStatus.PARTIAL,
        )
        for name in EXPECTED_PREFLIGHT_FIELDS:
            self.assertIsNotNone(getattr(result, name), name)


class ModulePurityTests(unittest.TestCase):
    """preflight_engine.py stays stdlib + domain.models, deterministic."""

    ALLOWED_IMPORT_ROOTS = {"re", "datetime", "typing", "domain"}

    FORBIDDEN_TOKENS = (
        "llm_client",
        "gemini",
        "google",
        "workflows",
        "requests",
        "urllib",
        "socket",
        "arithmetic",
        "calculate_deadline",
        "deadline_engine",
        "EvidenceGap",
        "notice_valid",
        "notice_invalid",
        "jurisdiction_valid",
        "officer_competent",
    )

    NETWORK_ROOTS = {"requests", "urllib", "socket", "http"}

    @classmethod
    def _source(cls) -> str:
        return pathlib.Path(preflight_engine.__file__).read_text(
            encoding="utf-8"
        )

    @classmethod
    def _import_roots(cls) -> set:
        roots = set()
        for line in cls._source().splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                module_name = stripped.split()[1]
                if module_name.startswith("."):
                    continue
                roots.add(module_name.split(".")[0])
            elif stripped.startswith("import "):
                roots.add(stripped.split()[1].split(".")[0])
        return roots

    def test_no_llm_import(self):
        roots = self._import_roots()
        self.assertTrue(
            roots <= self.ALLOWED_IMPORT_ROOTS,
            f"unexpected import roots {sorted(roots)}",
        )
        self.assertNotIn("modules", roots)

    def test_no_llm_client_module(self):
        self.assertNotIn("llm_client", self._source())

    def test_no_workflows_import(self):
        self.assertNotIn("workflows", self._source())

    def test_no_network_imports(self):
        roots = self._import_roots()
        self.assertTrue(
            roots.isdisjoint(self.NETWORK_ROOTS),
            f"network import roots {sorted(roots)}",
        )

    def test_no_arithmetic_engine_coupling(self):
        self.assertNotIn("arithmetic", self._source())

    def test_no_call_to_calculate_deadline(self):
        self.assertNotIn("calculate_deadline", self._source())

    def test_no_evidence_gap_creation(self):
        self.assertNotIn("EvidenceGap", self._source())

    def test_no_legal_validity_output(self):
        source = self._source()
        for token in (
            "notice_valid",
            "notice_invalid",
            "jurisdiction_valid",
            "officer_competent",
        ):
            self.assertNotIn(token, source, token)
        result = run_preflight_on([make_fact("F-001", FactType.RFN)])
        for name in (
            "notice_valid",
            "notice_invalid",
            "jurisdiction_valid",
            "officer_competent",
        ):
            self.assertFalse(hasattr(result, name), name)


if __name__ == "__main__":
    unittest.main()
