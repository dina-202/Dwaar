"""Tests for source-verified historical ITC mismatch regimes."""

import unittest
from datetime import date

from domain.legal_date_engine import build_legal_date_context
from domain.legal_knowledge import resolve_legal_knowledge_interval
from domain.legal_knowledge_models import (
    LegalKnowledgeIntervalQuery,
    LegalTopic,
)
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
from workflows.gst.legal_knowledge import (
    CIRCULAR_183_CBIC,
    CIRCULAR_193_GST_COUNCIL,
    GST_LEGAL_CATALOG_VERSION,
    GST_LEGAL_RULES,
    GST_LEGAL_SOURCES,
)
from workflows.gst.legal_research import resolve_gst_legal_brief_from_context


def tax_period(text):
    fact = ExtractedFact(
        fact_id="F-T",
        claim="Tax period",
        status=FactStatus.CONFIRMED,
        source_text=text,
        source_page=1,
        allowed_in_draft=DraftPermission.YES,
        fact_type=FactType.TAX_PERIOD,
        fact_role=FactRole.NONE,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )
    return build_legal_date_context([fact])


class ItcMismatchKnowledgeTests(unittest.TestCase):
    def test_circular_sources_are_official_and_versioned(self):
        self.assertEqual(
            CIRCULAR_183_CBIC.official_domain,
            "cbic-gst.gov.in",
        )
        self.assertEqual(
            CIRCULAR_183_CBIC.publication_date,
            date(2022, 12, 27),
        )
        self.assertEqual(
            CIRCULAR_193_GST_COUNCIL.official_domain,
            "gstcouncil.gov.in",
        )
        self.assertEqual(
            CIRCULAR_193_GST_COUNCIL.publication_date,
            date(2023, 7, 17),
        )

    def test_fy2017_18_and_2018_19_use_circular_183_version(self):
        for text in ("FY 2017-18", "FY 2018-19"):
            with self.subTest(text=text):
                result = resolve_gst_legal_brief_from_context(
                    ProceedingType.GST_SEC73_ITC,
                    tax_period(text),
                )
                matches = [
                    item for item in result.matches
                    if item.rule.topic
                    is LegalTopic.ITC_MISMATCH_VERIFICATION
                ]
                self.assertEqual(
                    [item.rule.rule_id for item in matches],
                    ["cbic.itc_mismatch_verification.fy2017_2018.v1"],
                )

    def test_fy2019_20_and_2020_21_use_circular_193_version(self):
        for text in ("FY 2019-20", "FY 2020-21"):
            with self.subTest(text=text):
                result = resolve_gst_legal_brief_from_context(
                    ProceedingType.GST_SEC73_ITC,
                    tax_period(text),
                )
                matches = [
                    item for item in result.matches
                    if item.rule.topic
                    is LegalTopic.ITC_MISMATCH_VERIFICATION
                ]
                self.assertEqual(
                    [item.rule.rule_id for item in matches],
                    ["cbic.itc_mismatch_verification.2019_2021.v2"],
                )

    def test_fy2021_22_is_not_treated_as_fully_covered(self):
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            tax_period("FY 2021-22"),
        )
        self.assertIn(
            LegalTopic.ITC_MISMATCH_VERIFICATION,
            result.unresolved_topics,
        )
        self.assertFalse(
            any(
                item.rule.topic is LegalTopic.ITC_MISMATCH_VERIFICATION
                for item in result.matches
            )
        )

    def test_exact_period_ending_31_december_2021_is_covered(self):
        result = resolve_legal_knowledge_interval(
            LegalKnowledgeIntervalQuery(
                period_start=date(2021, 4, 1),
                period_end=date(2021, 12, 31),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                topics=(LegalTopic.ITC_MISMATCH_VERIFICATION,),
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(
            [item.rule.rule_id for item in result.matches],
            ["cbic.itc_mismatch_verification.2019_2021.v2"],
        )

    def test_post_2021_period_uses_post2022_mismatch_regime(self):
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            tax_period("FY 2022-23"),
        )
        self.assertNotIn(
            LegalTopic.ITC_MISMATCH_VERIFICATION,
            result.unresolved_topics,
        )
        matches = [
            item for item in result.matches
            if item.rule.topic is LegalTopic.ITC_MISMATCH_VERIFICATION
        ]
        self.assertEqual(
            [item.rule.rule_id for item in matches],
            ["cbic.itc_mismatch_verification.post2022.v3"],
        )

    def test_final_itc_eligibility_still_remains_unresolved(self):
        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            tax_period("FY 2019-20"),
        )
        self.assertIn(
            LegalTopic.ITC_ELIGIBILITY,
            result.unresolved_topics,
        )


if __name__ == "__main__":
    unittest.main()
