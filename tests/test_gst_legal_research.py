"""Offline tests for Phase 3N GST legal-research plans."""

import unittest
from datetime import date

from domain.legal_knowledge_models import LegalTopic
from domain.models import ProceedingType
from workflows.gst.legal_research import (
    GST_LEGAL_RESEARCH_PROFILES,
    LegalDateBasis,
    get_gst_legal_research_profile,
    resolve_gst_legal_brief,
)


class GstLegalResearchProfileTests(unittest.TestCase):
    def test_all_five_deep_workflows_have_profiles(self):
        expected = {
            ProceedingType.GST_SEC73_GENERAL,
            ProceedingType.GST_SEC73_ITC,
            ProceedingType.GST_SEC73_RCM,
            ProceedingType.GST_SEC74_FRAUD,
            ProceedingType.GST_SEC129_ENFORCE,
        }
        self.assertEqual(set(GST_LEGAL_RESEARCH_PROFILES), expected)

    def test_topic_date_bases_are_explicit(self):
        self.assertEqual(
            [
                (item.topic, item.date_basis)
                for item in GST_LEGAL_RESEARCH_PROFILES[
                    ProceedingType.GST_SEC73_ITC
                ].requirements
            ],
            [
                (LegalTopic.HEARING_RIGHT, LegalDateBasis.NOTICE_DATE),
                (LegalTopic.DEMAND_SCOPE, LegalDateBasis.NOTICE_DATE),
                (
                    LegalTopic.ITC_MISMATCH_VERIFICATION,
                    LegalDateBasis.TAX_PERIOD_END,
                ),
                (
                    LegalTopic.ITC_ELIGIBILITY,
                    LegalDateBasis.TAX_PERIOD_END,
                ),
            ],
        )
        self.assertEqual(
            {
                item.date_basis
                for item in GST_LEGAL_RESEARCH_PROFILES[
                    ProceedingType.GST_SEC129_ENFORCE
                ].requirements
            },
            {LegalDateBasis.DETENTION_OR_SEIZURE_DATE},
        )

    def test_unknown_proceeding_has_no_profile(self):
        self.assertIsNone(
            get_gst_legal_research_profile(ProceedingType.UNKNOWN)
        )

    def test_itc_brief_keeps_uncurated_itc_law_explicitly_unresolved(self):
        result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC73_ITC,
            date(2026, 9, 23),
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(
            [item.rule.topic for item in result.matches],
            [LegalTopic.HEARING_RIGHT, LegalTopic.DEMAND_SCOPE],
        )
        self.assertEqual(
            result.unresolved_topics,
            (
                LegalTopic.ITC_MISMATCH_VERIFICATION,
                LegalTopic.ITC_ELIGIBILITY,
            ),
        )

    def test_rcm_brief_keeps_applicability_unresolved(self):
        result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC73_RCM,
            date(2026, 9, 23),
        )
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.RCM_APPLICABILITY,),
        )

    def test_fraud_scope_stays_unresolved_without_tax_period_anchor(self):
        result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC74_FRAUD,
            date(2026, 9, 23),
        )
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.FRAUD_SUPPRESSION_SCOPE,),
        )

    def test_section129_historical_brief_does_not_use_2022_rules(self):
        result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC129_ENFORCE,
            date(2021, 12, 31),
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (
                LegalTopic.SECTION_129_TIMELINE,
                LegalTopic.SECTION_129_HEARING,
            ),
        )

    def test_section129_notice_date_does_not_substitute_for_detention_date(self):
        result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC129_ENFORCE,
            date(2026, 9, 23),
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (
                LegalTopic.SECTION_129_TIMELINE,
                LegalTopic.SECTION_129_HEARING,
            ),
        )

    def test_unknown_proceeding_returns_empty_non_error_brief(self):
        result = resolve_gst_legal_brief(
            ProceedingType.UNKNOWN,
            date(2026, 9, 23),
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.matches, ())
        self.assertEqual(result.unresolved_topics, ())


if __name__ == "__main__":
    unittest.main()
