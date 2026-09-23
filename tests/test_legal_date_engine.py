"""Offline tests for provenance-bearing legal applicability dates."""

import unittest
from datetime import date

from domain.legal_date_engine import (
    build_legal_date_context,
    parse_tax_period_interval,
)
from domain.legal_date_models import LegalDateBasis
from domain.models import (
    DraftPermission,
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from workflows.gst.legal_research import (
    resolve_gst_legal_brief_from_context,
)


def fact(
    fact_id,
    fact_type,
    source_text,
    *,
    role=FactRole.NONE,
    status=FactStatus.CONFIRMED,
    verification=SourceVerificationStatus.VERIFIED,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim="source-grounded fixture",
        status=status,
        source_text=source_text,
        source_page=2,
        allowed_in_draft=DraftPermission.YES,
        fact_type=fact_type,
        fact_role=role,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=verification,
    )


class TaxPeriodParserTests(unittest.TestCase):
    def test_financial_year_short_suffix(self):
        self.assertEqual(
            parse_tax_period_interval("Financial Year 2021-22"),
            (date(2021, 4, 1), date(2022, 3, 31)),
        )

    def test_fy_full_suffix(self):
        self.assertEqual(
            parse_tax_period_interval("FY: 2022-2023"),
            (date(2022, 4, 1), date(2023, 3, 31)),
        )

    def test_explicit_numeric_range(self):
        self.assertEqual(
            parse_tax_period_interval(
                "Tax period 01/07/2021 to 30/09/2021"
            ),
            (date(2021, 7, 1), date(2021, 9, 30)),
        )

    def test_bare_year_range_is_not_silently_financial_year(self):
        self.assertIsNone(parse_tax_period_interval("2021-22"))

    def test_invalid_financial_year_is_rejected(self):
        self.assertIsNone(parse_tax_period_interval("FY 2021-23"))

    def test_multiple_period_representations_are_ambiguous(self):
        self.assertIsNone(
            parse_tax_period_interval(
                "FY 2021-22, 01/04/2021 to 31/03/2022"
            )
        )


class LegalDateContextTests(unittest.TestCase):
    def test_builds_all_three_anchors_with_provenance(self):
        context = build_legal_date_context(
            [
                fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
                fact(
                    "F-T",
                    FactType.TAX_PERIOD,
                    "Financial Year 2021-22",
                ),
                fact(
                    "F-D",
                    FactType.DOCUMENT_DETAIL,
                    "Goods detained on 24/01/2022",
                    role=FactRole.DETENTION_OR_SEIZURE_DATE,
                ),
            ]
        )
        self.assertEqual(
            context.get(LegalDateBasis.NOTICE_DATE).effective_date,
            date(2026, 8, 17),
        )
        tax = context.get(LegalDateBasis.TAX_PERIOD_END)
        self.assertEqual(tax.period_start, date(2021, 4, 1))
        self.assertEqual(tax.period_end, date(2022, 3, 31))
        self.assertEqual(tax.effective_date, date(2022, 3, 31))
        self.assertEqual(tax.source_fact_id, "F-T")
        self.assertEqual(
            context.get(
                LegalDateBasis.DETENTION_OR_SEIZURE_DATE
            ).effective_date,
            date(2022, 1, 24),
        )

    def test_unverified_ocr_fact_never_becomes_anchor(self):
        context = build_legal_date_context(
            [
                fact(
                    "F-T",
                    FactType.TAX_PERIOD,
                    "FY 2021-22",
                    verification=(
                        SourceVerificationStatus.REQUIRES_VERIFICATION
                    ),
                )
            ]
        )
        self.assertIsNone(context.get(LegalDateBasis.TAX_PERIOD_END))

    def test_alleged_fact_never_becomes_anchor(self):
        context = build_legal_date_context(
            [
                fact(
                    "F-D",
                    FactType.DOCUMENT_DETAIL,
                    "Detained 24/01/2022",
                    role=FactRole.DETENTION_OR_SEIZURE_DATE,
                    status=FactStatus.ALLEGED,
                )
            ]
        )
        self.assertIsNone(
            context.get(LegalDateBasis.DETENTION_OR_SEIZURE_DATE)
        )

    def test_duplicate_basis_fails_closed(self):
        context = build_legal_date_context(
            [
                fact("F-1", FactType.TAX_PERIOD, "FY 2021-22"),
                fact("F-2", FactType.TAX_PERIOD, "FY 2022-23"),
            ]
        )
        self.assertIsNone(context.get(LegalDateBasis.TAX_PERIOD_END))

    def test_wrong_role_does_not_create_detention_anchor(self):
        context = build_legal_date_context(
            [
                fact(
                    "F-X",
                    FactType.DOCUMENT_DETAIL,
                    "24/01/2022",
                    role=FactRole.EXPLICIT_PROCEDURAL_DATE,
                )
            ]
        )
        self.assertIsNone(
            context.get(LegalDateBasis.DETENTION_OR_SEIZURE_DATE)
        )

    def test_multiple_numeric_dates_in_one_detention_fact_fail_closed(self):
        context = build_legal_date_context(
            [
                fact(
                    "F-D",
                    FactType.DOCUMENT_DETAIL,
                    "Detained 24/01/2022; released 25/01/2022",
                    role=FactRole.DETENTION_OR_SEIZURE_DATE,
                )
            ]
        )
        self.assertIsNone(
            context.get(LegalDateBasis.DETENTION_OR_SEIZURE_DATE)
        )


class ContextAwareLegalResearchTests(unittest.TestCase):
    def test_section129_uses_detention_date_not_notice_date(self):
        context = build_legal_date_context(
            [
                fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
                fact(
                    "F-D",
                    FactType.DOCUMENT_DETAIL,
                    "Goods detained on 24/01/2022",
                    role=FactRole.DETENTION_OR_SEIZURE_DATE,
                ),
            ]
        )
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC129_ENFORCE,
            context,
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(len(result.matches), 2)

    def test_pre_2022_detention_does_not_receive_post_2022_rule(self):
        context = build_legal_date_context(
            [
                fact(
                    "F-D",
                    FactType.DOCUMENT_DETAIL,
                    "Goods detained on 31/12/2021",
                    role=FactRole.DETENTION_OR_SEIZURE_DATE,
                )
            ]
        )
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC129_ENFORCE,
            context,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(len(result.unresolved_topics), 2)

    def test_section74_scope_resolves_for_fy2023_24_or_earlier(self):
        context = build_legal_date_context(
            [
                fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
                fact("F-T", FactType.TAX_PERIOD, "FY 2023-24"),
            ]
        )
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC74_FRAUD,
            context,
        )
        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(len(result.matches), 3)
        fraud = [
            item for item in result.matches
            if item.rule.topic.value == "fraud_suppression_scope"
        ][0]
        self.assertEqual(
            fraud.rule.effective_to,
            date(2024, 3, 31),
        )

    def test_section74_scope_does_not_leak_into_fy2024_25(self):
        context = build_legal_date_context(
            [
                fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
                fact("F-T", FactType.TAX_PERIOD, "FY 2024-25"),
            ]
        )
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC74_FRAUD,
            context,
        )
        self.assertEqual(len(result.matches), 2)
        self.assertEqual(
            tuple(item.value for item in result.unresolved_topics),
            ("fraud_suppression_scope",),
        )

    def test_itc_tax_period_anchor_does_not_fake_missing_itc_law(self):
        context = build_legal_date_context(
            [
                fact("F-N", FactType.NOTICE_DATE, "Issued 17/08/2026"),
                fact("F-T", FactType.TAX_PERIOD, "FY 2021-22"),
            ]
        )
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            context,
        )
        self.assertEqual(len(result.matches), 2)
        self.assertEqual(
            tuple(item.value for item in result.unresolved_topics),
            ("itc_mismatch_verification", "itc_eligibility"),
        )


if __name__ == "__main__":
    unittest.main()
