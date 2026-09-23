"""Tests for closed multi-authority GST legal research bundles."""

import unittest
from datetime import date
from unittest.mock import patch

from domain.legal_date_models import (
    LegalDateAnchor,
    LegalDateBasis,
    LegalDateContext,
)
from domain.legal_knowledge_models import (
    LegalAuthorityType,
    LegalKnowledgeResult,
    LegalRule,
    LegalRuleMatch,
    LegalSourceRef,
    LegalTopic,
    LegalVerificationStatus,
)
from domain.models import FactRole, FactType, ProceedingType
from workflows.gst.legal_research import (
    GST_LEGAL_RESEARCH_PROFILES,
    GstLegalResearchProfile,
    GstLegalResearchRequirement,
    resolve_gst_legal_brief_from_context,
)


TODAY = date(2026, 9, 23)


def source():
    return LegalSourceRef(
        source_id="src.test",
        authority_type=LegalAuthorityType.ACT,
        title="Official test source",
        issuer="Test authority",
        official_url="https://www.indiacode.nic.in/test",
        official_domain="www.indiacode.nic.in",
        version_label="test",
        publication_date=None,
        retrieved_at=TODAY,
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    )


def match(rule_key, rule_id):
    rule = LegalRule(
        rule_id=rule_id,
        rule_key=rule_key,
        source_id="src.test",
        provision=rule_key,
        proposition=f"Proposition for {rule_key}",
        effective_from=date(2017, 7, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.ITC_ELIGIBILITY,
        proceeding_types=(ProceedingType.GST_SEC73_ITC,),
        verified_at=TODAY,
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    )
    return LegalRuleMatch(rule=rule, source=source())


def context():
    return LegalDateContext(
        anchors=(
            LegalDateAnchor(
                basis=LegalDateBasis.TAX_PERIOD_END,
                effective_date=date(2024, 3, 31),
                period_start=date(2023, 4, 1),
                period_end=date(2024, 3, 31),
                source_fact_id="F-TAX",
                source_page=2,
                source_text="FY 2023-24",
                source_fact_type=FactType.TAX_PERIOD,
                source_fact_role=FactRole.NONE,
            ),
        )
    )


def profile():
    return GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        requirements=(
            GstLegalResearchRequirement(
                topic=LegalTopic.ITC_ELIGIBILITY,
                date_basis=LegalDateBasis.TAX_PERIOD_END,
                required_rule_keys=("rule.a", "rule.b"),
            ),
        ),
    )


class LegalRuleBundleTests(unittest.TestCase):
    def test_current_workflow_bundles_pin_existing_verified_authorities(self):
        scrutiny = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC61_SCRUTINY
        ]
        self.assertEqual(
            [item.required_rule_keys for item in scrutiny.requirements],
            [
                (
                    "cgst.s61.scrutiny_process",
                    "cgst.r99.asmt_forms",
                ),
            ],
        )
        general = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC73_GENERAL
        ]
        self.assertEqual(
            [item.required_rule_keys for item in general.requirements],
            [
                ("cgst.s75.4.hearing",),
                ("cgst.s75.7.demand_scope",),
            ],
        )
        fraud = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC74_FRAUD
        ]
        self.assertEqual(
            fraud.requirements[-1].required_rule_keys,
            ("cgst.s74.fraud_scope",),
        )
        sec129 = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC129_ENFORCE
        ]
        self.assertEqual(
            [item.required_rule_keys for item in sec129.requirements],
            [
                ("cgst.s129.3.timeline",),
                ("cgst.s129.4.hearing",),
            ],
        )

    def test_uncurated_topics_have_empty_bundles_and_remain_unresolved(self):
        itc = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC73_ITC
        ]
        rcm = GST_LEGAL_RESEARCH_PROFILES[
            ProceedingType.GST_SEC73_RCM
        ]
        self.assertEqual(itc.requirements[-1].required_rule_keys, ())
        self.assertEqual(rcm.requirements[-1].required_rule_keys, ())

    @patch("workflows.gst.legal_research.get_gst_legal_research_profile")
    @patch("workflows.gst.legal_research.resolve_legal_knowledge_interval")
    def test_complete_two_rule_bundle_resolves(
        self,
        resolve_mock,
        profile_mock,
    ):
        profile_mock.return_value = profile()
        a = match("rule.a", "rule.a.v1")
        b = match("rule.b", "rule.b.v1")
        resolve_mock.return_value = LegalKnowledgeResult(
            matches=(b, a),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version="test",
        )

        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            context(),
        )

        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(
            [item.rule.rule_key for item in result.matches],
            ["rule.a", "rule.b"],
        )

    @patch("workflows.gst.legal_research.get_gst_legal_research_profile")
    @patch("workflows.gst.legal_research.resolve_legal_knowledge_interval")
    def test_missing_required_rule_keeps_topic_unresolved(
        self,
        resolve_mock,
        profile_mock,
    ):
        profile_mock.return_value = profile()
        resolve_mock.return_value = LegalKnowledgeResult(
            matches=(match("rule.a", "rule.a.v1"),),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version="test",
        )

        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            context(),
        )

        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.ITC_ELIGIBILITY,),
        )

    @patch("workflows.gst.legal_research.get_gst_legal_research_profile")
    @patch("workflows.gst.legal_research.resolve_legal_knowledge_interval")
    def test_unexpected_extra_rule_requires_explicit_bundle_update(
        self,
        resolve_mock,
        profile_mock,
    ):
        profile_mock.return_value = profile()
        resolve_mock.return_value = LegalKnowledgeResult(
            matches=(
                match("rule.a", "rule.a.v1"),
                match("rule.b", "rule.b.v1"),
                match("rule.c", "rule.c.v1"),
            ),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version="test",
        )

        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            context(),
        )

        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.ITC_ELIGIBILITY,),
        )

    @patch("workflows.gst.legal_research.get_gst_legal_research_profile")
    @patch("workflows.gst.legal_research.resolve_legal_knowledge_interval")
    def test_duplicate_effective_rule_key_fails_topic_closed(
        self,
        resolve_mock,
        profile_mock,
    ):
        profile_mock.return_value = profile()
        resolve_mock.return_value = LegalKnowledgeResult(
            matches=(
                match("rule.a", "rule.a.v1"),
                match("rule.a", "rule.a.v2"),
                match("rule.b", "rule.b.v1"),
            ),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version="test",
        )

        result = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC73_ITC,
            context(),
        )

        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.ITC_ELIGIBILITY,),
        )


if __name__ == "__main__":
    unittest.main()
