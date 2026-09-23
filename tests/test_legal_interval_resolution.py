"""Tests for full-period legal applicability safety."""

import unittest
from dataclasses import replace
from datetime import date

from domain.legal_knowledge import (
    resolve_legal_knowledge_interval,
)
from domain.legal_knowledge_models import (
    LegalAuthorityType,
    LegalKnowledgeIntervalQuery,
    LegalRule,
    LegalSourceRef,
    LegalTopic,
    LegalVerificationStatus,
)
from domain.models import ProceedingType
from workflows.gst.legal_knowledge import (
    GST_LEGAL_CATALOG_VERSION,
    GST_LEGAL_RULES,
    GST_LEGAL_SOURCES,
)


class LegalIntervalResolutionTests(unittest.TestCase):
    def query(self, start, end, *topics):
        return LegalKnowledgeIntervalQuery(
            period_start=start,
            period_end=end,
            proceeding_type=ProceedingType.GST_SEC74_FRAUD,
            topics=tuple(topics),
        )

    def test_section74_rule_covers_entire_fy2023_24(self):
        result = resolve_legal_knowledge_interval(
            self.query(
                date(2023, 4, 1),
                date(2024, 3, 31),
                LegalTopic.FRAUD_SUPPRESSION_SCOPE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(
            [item.rule.rule_id for item in result.matches],
            ["cgst.s74.fraud_scope.fy2017_2023.v1"],
        )

    def test_section74_rule_does_not_cover_period_crossing_fy_boundary(self):
        result = resolve_legal_knowledge_interval(
            self.query(
                date(2023, 4, 1),
                date(2024, 4, 1),
                LegalTopic.FRAUD_SUPPRESSION_SCOPE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.FRAUD_SUPPRESSION_SCOPE,),
        )

    def test_rule_starting_mid_period_does_not_cover_whole_interval(self):
        source = GST_LEGAL_SOURCES[0]
        rule = LegalRule(
            rule_id="test.midyear.v1",
            rule_key="test.midyear",
            source_id=source.source_id,
            provision="Test",
            proposition="Mid-year rule.",
            effective_from=date(2021, 1, 1),
            effective_to=None,
            jurisdiction="India",
            topic=LegalTopic.ITC_ELIGIBILITY,
            proceeding_types=(ProceedingType.GST_SEC73_ITC,),
            verified_at=date(2026, 9, 23),
            verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
        )
        result = resolve_legal_knowledge_interval(
            LegalKnowledgeIntervalQuery(
                period_start=date(2020, 4, 1),
                period_end=date(2021, 3, 31),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                topics=(LegalTopic.ITC_ELIGIBILITY,),
            ),
            catalog_version="test",
            sources=(source,),
            rules=(rule,),
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.ITC_ELIGIBILITY,),
        )

    def test_rule_ending_mid_period_does_not_cover_whole_interval(self):
        source = GST_LEGAL_SOURCES[0]
        rule = LegalRule(
            rule_id="test.ends.v1",
            rule_key="test.ends",
            source_id=source.source_id,
            provision="Test",
            proposition="Ending rule.",
            effective_from=date(2019, 1, 1),
            effective_to=date(2020, 12, 31),
            jurisdiction="India",
            topic=LegalTopic.ITC_ELIGIBILITY,
            proceeding_types=(ProceedingType.GST_SEC73_ITC,),
            verified_at=date(2026, 9, 23),
            verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
        )
        result = resolve_legal_knowledge_interval(
            LegalKnowledgeIntervalQuery(
                period_start=date(2020, 4, 1),
                period_end=date(2021, 3, 31),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                topics=(LegalTopic.ITC_ELIGIBILITY,),
            ),
            catalog_version="test",
            sources=(source,),
            rules=(rule,),
        )
        self.assertEqual(result.matches, ())

    def test_adjacent_versions_cannot_be_combined_to_fake_full_period(self):
        source = GST_LEGAL_SOURCES[0]
        first = LegalRule(
            rule_id="test.split.v1",
            rule_key="test.split",
            source_id=source.source_id,
            provision="Test",
            proposition="First version.",
            effective_from=date(2020, 4, 1),
            effective_to=date(2020, 12, 31),
            jurisdiction="India",
            topic=LegalTopic.ITC_ELIGIBILITY,
            proceeding_types=(ProceedingType.GST_SEC73_ITC,),
            verified_at=date(2026, 9, 23),
            verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
        )
        second = replace(
            first,
            rule_id="test.split.v2",
            proposition="Second version.",
            effective_from=date(2021, 1, 1),
            effective_to=None,
        )
        result = resolve_legal_knowledge_interval(
            LegalKnowledgeIntervalQuery(
                period_start=date(2020, 4, 1),
                period_end=date(2021, 3, 31),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                topics=(LegalTopic.ITC_ELIGIBILITY,),
            ),
            catalog_version="test",
            sources=(source,),
            rules=(first, second),
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.ITC_ELIGIBILITY,),
        )

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_legal_knowledge_interval(
                self.query(
                    date(2024, 4, 1),
                    date(2024, 3, 31),
                    LegalTopic.FRAUD_SUPPRESSION_SCOPE,
                ),
                catalog_version=GST_LEGAL_CATALOG_VERSION,
                sources=GST_LEGAL_SOURCES,
                rules=GST_LEGAL_RULES,
            )


if __name__ == "__main__":
    unittest.main()
