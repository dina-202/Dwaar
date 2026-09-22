"""Offline tests for Phase 3N verified legal knowledge."""

import unittest
from dataclasses import replace
from datetime import date

from domain.legal_knowledge import (
    APPROVED_OFFICIAL_DOMAINS,
    resolve_legal_knowledge,
    validate_catalog,
)
from domain.legal_knowledge_models import (
    LegalAuthorityType,
    LegalKnowledgeQuery,
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


class LegalKnowledgeTests(unittest.TestCase):
    def query(self, as_of, proceeding_type, *topics):
        return LegalKnowledgeQuery(
            as_of_date=as_of,
            proceeding_type=proceeding_type,
            topics=tuple(topics),
        )

    def test_initial_catalog_is_structurally_valid(self):
        self.assertTrue(validate_catalog(GST_LEGAL_SOURCES, GST_LEGAL_RULES))

    def test_initial_sources_are_closed_to_approved_official_domains(self):
        for source in GST_LEGAL_SOURCES:
            self.assertIn(source.official_domain, APPROVED_OFFICIAL_DOMAINS)
            self.assertTrue(source.official_url.startswith("https://"))
            self.assertIs(
                source.verification_status,
                LegalVerificationStatus.SOURCE_VERIFIED,
            )

    def test_demand_workflow_resolves_hearing_and_demand_scope(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_ITC,
                LegalTopic.HEARING_RIGHT,
                LegalTopic.DEMAND_SCOPE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.unresolved_topics, ())
        self.assertEqual(
            [match.rule.rule_id for match in result.matches],
            [
                "cgst.s75.4.hearing.v1",
                "cgst.s75.7.demand_scope.v1",
            ],
        )

    def test_section129_post_2022_rules_resolve(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC129_ENFORCE,
                LegalTopic.SECTION_129_TIMELINE,
                LegalTopic.SECTION_129_HEARING,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(
            [match.rule.rule_id for match in result.matches],
            [
                "cgst.s129.3.timeline.2022.v1",
                "cgst.s129.4.hearing.2022.v1",
            ],
        )
        self.assertEqual(result.unresolved_topics, ())

    def test_section129_post_2022_rule_does_not_leak_into_historical_query(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2021, 12, 31),
                ProceedingType.GST_SEC129_ENFORCE,
                LegalTopic.SECTION_129_TIMELINE,
                LegalTopic.SECTION_129_HEARING,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (
                LegalTopic.SECTION_129_TIMELINE,
                LegalTopic.SECTION_129_HEARING,
            ),
        )

    def test_wrong_proceeding_type_cannot_reuse_section129_rules(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_GENERAL,
                LegalTopic.SECTION_129_TIMELINE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.SECTION_129_TIMELINE,),
        )

    def test_uncurated_rcm_topic_stays_unresolved(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_RCM,
                LegalTopic.RCM_APPLICABILITY,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.RCM_APPLICABILITY,),
        )

    def test_duplicate_query_topics_are_deduplicated_preserving_order(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_GENERAL,
                LegalTopic.DEMAND_SCOPE,
                LegalTopic.HEARING_RIGHT,
                LegalTopic.DEMAND_SCOPE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertEqual(
            [match.rule.topic for match in result.matches],
            [LegalTopic.DEMAND_SCOPE, LegalTopic.HEARING_RIGHT],
        )

    def test_non_https_source_invalidates_entire_catalog(self):
        bad_source = replace(
            GST_LEGAL_SOURCES[0],
            official_url="http://www.indiacode.nic.in/indiacode/handle/123456789/15689",
        )
        self.assertFalse(validate_catalog((bad_source,), GST_LEGAL_RULES))

    def test_unapproved_domain_invalidates_entire_catalog(self):
        bad_source = replace(
            GST_LEGAL_SOURCES[0],
            official_url="https://example.com/cgst",
            official_domain="example.com",
        )
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_GENERAL,
                LegalTopic.DEMAND_SCOPE,
            ),
            catalog_version=GST_LEGAL_CATALOG_VERSION,
            sources=(bad_source,),
            rules=GST_LEGAL_RULES,
        )
        self.assertFalse(result.catalog_valid)
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.DEMAND_SCOPE,),
        )

    def test_domain_string_must_equal_url_hostname(self):
        bad_source = replace(
            GST_LEGAL_SOURCES[0],
            official_domain="indiacode.nic.in",
        )
        self.assertFalse(validate_catalog((bad_source,), GST_LEGAL_RULES))

    def test_source_verified_rule_requires_source_verified_source(self):
        bad_source = replace(
            GST_LEGAL_SOURCES[0],
            verification_status=LegalVerificationStatus.REQUIRES_VERIFICATION,
        )
        self.assertFalse(validate_catalog((bad_source,), GST_LEGAL_RULES))

    def test_missing_source_reference_invalidates_catalog(self):
        bad_rule = replace(GST_LEGAL_RULES[0], source_id="src.missing")
        self.assertFalse(validate_catalog(GST_LEGAL_SOURCES, (bad_rule,)))

    def test_duplicate_source_id_invalidates_catalog(self):
        duplicate = replace(
            GST_LEGAL_SOURCES[0],
            title="Duplicate source record",
        )
        self.assertFalse(
            validate_catalog(
                (GST_LEGAL_SOURCES[0], duplicate),
                GST_LEGAL_RULES,
            )
        )

    def test_duplicate_rule_id_invalidates_catalog(self):
        duplicate = replace(
            GST_LEGAL_RULES[0],
            proposition="Duplicate rule record.",
        )
        self.assertFalse(
            validate_catalog(
                GST_LEGAL_SOURCES,
                (GST_LEGAL_RULES[0], duplicate),
            )
        )

    def test_invalid_effective_period_invalidates_catalog(self):
        bad_rule = replace(
            GST_LEGAL_RULES[0],
            effective_from=date(2026, 1, 2),
            effective_to=date(2026, 1, 1),
        )
        self.assertFalse(validate_catalog(GST_LEGAL_SOURCES, (bad_rule,)))

    def test_overlapping_verified_versions_of_same_rule_key_fail_closed(self):
        first = LegalRule(
            rule_id="test.rule.v1",
            rule_key="test.rule",
            source_id=GST_LEGAL_SOURCES[0].source_id,
            provision="Test provision",
            proposition="Version one.",
            effective_from=date(2020, 1, 1),
            effective_to=date(2024, 12, 31),
            jurisdiction="India",
            topic=LegalTopic.DEMAND_SCOPE,
            proceeding_types=(ProceedingType.GST_SEC73_GENERAL,),
            verified_at=date(2026, 9, 23),
            verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
        )
        second = replace(
            first,
            rule_id="test.rule.v2",
            proposition="Version two.",
            effective_from=date(2024, 12, 31),
            effective_to=None,
        )
        self.assertFalse(
            validate_catalog(GST_LEGAL_SOURCES, (first, second))
        )

    def test_adjacent_non_overlapping_versions_are_valid(self):
        first = LegalRule(
            rule_id="test.rule.v1",
            rule_key="test.rule",
            source_id=GST_LEGAL_SOURCES[0].source_id,
            provision="Test provision",
            proposition="Version one.",
            effective_from=date(2020, 1, 1),
            effective_to=date(2024, 12, 31),
            jurisdiction="India",
            topic=LegalTopic.DEMAND_SCOPE,
            proceeding_types=(ProceedingType.GST_SEC73_GENERAL,),
            verified_at=date(2026, 9, 23),
            verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
        )
        second = replace(
            first,
            rule_id="test.rule.v2",
            proposition="Version two.",
            effective_from=date(2025, 1, 1),
            effective_to=None,
        )
        self.assertTrue(validate_catalog(GST_LEGAL_SOURCES, (first, second)))

    def test_unverified_rule_never_matches(self):
        unverified = replace(
            GST_LEGAL_RULES[0],
            rule_id="test.unverified",
            rule_key="test.unverified",
            verification_status=LegalVerificationStatus.REQUIRES_VERIFICATION,
        )
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_GENERAL,
                LegalTopic.HEARING_RIGHT,
            ),
            catalog_version="test",
            sources=GST_LEGAL_SOURCES,
            rules=(unverified,),
        )
        self.assertTrue(result.catalog_valid)
        self.assertEqual(result.matches, ())
        self.assertEqual(
            result.unresolved_topics,
            (LegalTopic.HEARING_RIGHT,),
        )

    def test_empty_catalog_version_fails_closed(self):
        result = resolve_legal_knowledge(
            self.query(
                date(2026, 9, 23),
                ProceedingType.GST_SEC73_GENERAL,
                LegalTopic.DEMAND_SCOPE,
            ),
            catalog_version="",
            sources=GST_LEGAL_SOURCES,
            rules=GST_LEGAL_RULES,
        )
        self.assertFalse(result.catalog_valid)
        self.assertEqual(result.matches, ())

    def test_contracts_are_frozen(self):
        with self.assertRaises(Exception):
            GST_LEGAL_SOURCES[0].title = "Changed"


if __name__ == "__main__":
    unittest.main()
