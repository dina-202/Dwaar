"""Focused tests for Phase 3B deadline-input provenance."""

from datetime import date
import unittest
from unittest.mock import patch

from domain import phase2_orchestrator as orchestrator
from domain.models import (
    DraftPermission,
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    SourceTextOrigin,
    SourceVerificationStatus,
)


def fact(
    fact_id,
    fact_type,
    source_text,
    *,
    role=FactRole.NONE,
    status=FactStatus.CONFIRMED,
    verified=True,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim="claim must not drive deadline mapping",
        status=status,
        source_text=source_text,
        source_page=1,
        allowed_in_draft=DraftPermission.YES,
        fact_type=fact_type,
        fact_role=role,
        source_origin=(
            SourceTextOrigin.EMBEDDED
            if verified
            else SourceTextOrigin.OCR
        ),
        source_verification=(
            SourceVerificationStatus.VERIFIED
            if verified
            else SourceVerificationStatus.REQUIRES_VERIFICATION
        ),
    )


class DeadlineInputProvenanceTests(unittest.TestCase):
    def test_all_four_inputs_map_from_exact_verified_sources(self):
        facts = [
            fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
            fact(
                "F-S",
                FactType.DOCUMENT_DETAIL,
                "Notice served on 18/08/2026",
                role=FactRole.NOTICE_SERVICE_DATE,
            ),
            fact(
                "F-P",
                FactType.DOCUMENT_DETAIL,
                "Furnish reply within 15 days of service",
                role=FactRole.RESPONSE_PERIOD,
            ),
            fact(
                "F-H",
                FactType.HEARING_DETAILS,
                "Hearing on 02/09/2026",
            ),
        ]
        values = orchestrator._build_deadline_inputs(facts)
        self.assertEqual(
            values,
            (
                date(2026, 8, 17),
                date(2026, 8, 18),
                "Furnish reply within 15 days of service",
                "Hearing on 02/09/2026",
            ),
        )

    def test_service_date_role_is_not_inferred_from_generic_date(self):
        generic = fact(
            "F-X",
            FactType.DOCUMENT_DETAIL,
            "18/08/2026",
            role=FactRole.EXPLICIT_PROCEDURAL_DATE,
        )
        self.assertIsNone(
            orchestrator._build_deadline_inputs([generic])[1]
        )

    def test_section129_notice_or_service_role_is_not_silently_service_date(self):
        ambiguous = fact(
            "F-X",
            FactType.DOCUMENT_DETAIL,
            "Notice/service date 18/08/2026",
            role=FactRole.SECTION129_NOTICE_OR_SERVICE_DATE,
        )
        self.assertIsNone(
            orchestrator._build_deadline_inputs([ambiguous])[1]
        )

    def test_response_period_is_verbatim_source_not_claim(self):
        period = fact(
            "F-P",
            FactType.DOCUMENT_DETAIL,
            "Reply within 15 days of receipt",
            role=FactRole.RESPONSE_PERIOD,
        )
        period.claim = "Model rewrote this as thirty days"
        self.assertEqual(
            orchestrator._build_deadline_inputs([period])[2],
            "Reply within 15 days of receipt",
        )

    def test_response_period_words_are_not_normalized_by_orchestrator(self):
        period = fact(
            "F-P",
            FactType.DOCUMENT_DETAIL,
            "Reply within seven working days of service",
            role=FactRole.RESPONSE_PERIOD,
        )
        self.assertEqual(
            orchestrator._build_deadline_inputs([period])[2],
            "Reply within seven working days of service",
        )

    def test_duplicate_service_or_period_candidates_fail_closed(self):
        service = [
            fact(
                "F-S1",
                FactType.DOCUMENT_DETAIL,
                "Served 18/08/2026",
                role=FactRole.NOTICE_SERVICE_DATE,
            ),
            fact(
                "F-S2",
                FactType.DOCUMENT_DETAIL,
                "Served 19/08/2026",
                role=FactRole.NOTICE_SERVICE_DATE,
            ),
        ]
        period = [
            fact(
                "F-P1",
                FactType.DOCUMENT_DETAIL,
                "Reply within 15 days",
                role=FactRole.RESPONSE_PERIOD,
            ),
            fact(
                "F-P2",
                FactType.DOCUMENT_DETAIL,
                "Reply within 30 days",
                role=FactRole.RESPONSE_PERIOD,
            ),
        ]
        self.assertIsNone(
            orchestrator._build_deadline_inputs(service)[1]
        )
        self.assertIsNone(
            orchestrator._build_deadline_inputs(period)[2]
        )

    def test_alleged_metadata_never_becomes_deadline_anchor(self):
        alleged_notice = fact(
            "F-N",
            FactType.NOTICE_DATE,
            "Issued 17/08/2026",
            status=FactStatus.ALLEGED,
        )
        alleged_service = fact(
            "F-S",
            FactType.DOCUMENT_DETAIL,
            "Served 18/08/2026",
            role=FactRole.NOTICE_SERVICE_DATE,
            status=FactStatus.ALLEGED,
        )
        values = orchestrator._build_deadline_inputs(
            [alleged_notice, alleged_service]
        )
        self.assertIsNone(values[0])
        self.assertIsNone(values[1])

    def test_unverified_ocr_inputs_are_ignored(self):
        facts = [
            fact(
                "F-S",
                FactType.DOCUMENT_DETAIL,
                "Served 18/08/2026",
                role=FactRole.NOTICE_SERVICE_DATE,
                verified=False,
            ),
            fact(
                "F-P",
                FactType.DOCUMENT_DETAIL,
                "Reply within 15 days of service",
                role=FactRole.RESPONSE_PERIOD,
                verified=False,
            ),
        ]
        self.assertEqual(
            orchestrator._build_deadline_inputs(facts),
            (None, None, None, None),
        )

    def test_service_date_parse_failure_stays_unknown(self):
        service = fact(
            "F-S",
            FactType.DOCUMENT_DETAIL,
            "Served on a date written only in prose",
            role=FactRole.NOTICE_SERVICE_DATE,
        )
        with patch.object(
            orchestrator, "_parse_date_text", return_value=None
        ) as parser:
            values = orchestrator._build_deadline_inputs([service])
        self.assertIsNone(values[1])
        parser.assert_called_once_with(
            "Served on a date written only in prose"
        )


if __name__ == "__main__":
    unittest.main()
