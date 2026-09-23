"""Closed GST legal-research plans for Phase 3N.

This module chooses research TOPICS and their legal applicability date basis,
not legal outcomes. Only topics whose required date basis is explicitly
available may enter the trusted resolver.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple

from domain.legal_date_engine import build_legal_date_context
from domain.legal_date_models import LegalDateBasis, LegalDateContext
from domain.legal_knowledge import (
    resolve_legal_knowledge,
    resolve_legal_knowledge_interval,
)
from domain.legal_knowledge_models import (
    LegalKnowledgeIntervalQuery,
    LegalKnowledgeQuery,
    LegalKnowledgeResult,
    LegalTopic,
)
from domain.models import ProceedingType
from workflows.gst.legal_knowledge import (
    GST_LEGAL_CATALOG_VERSION,
    GST_LEGAL_RULES,
    GST_LEGAL_SOURCES,
)


@dataclass(frozen=True)
class GstLegalResearchRequirement:
    topic: LegalTopic
    date_basis: LegalDateBasis
    required_rule_keys: Tuple[str, ...]


@dataclass(frozen=True)
class GstLegalResearchProfile:
    proceeding_type: ProceedingType
    requirements: Tuple[GstLegalResearchRequirement, ...]

    @property
    def topics(self) -> Tuple[LegalTopic, ...]:
        return tuple(item.topic for item in self.requirements)


def _r(
    topic: LegalTopic,
    date_basis: LegalDateBasis,
    *required_rule_keys: str,
) -> GstLegalResearchRequirement:
    if len(required_rule_keys) != len(set(required_rule_keys)):
        raise ValueError("required_rule_keys must be unique")
    if any(not isinstance(key, str) or not key for key in required_rule_keys):
        raise ValueError("required_rule_keys must be non-empty strings")
    return GstLegalResearchRequirement(
        topic=topic,
        date_basis=date_basis,
        required_rule_keys=tuple(required_rule_keys),
    )


GST_LEGAL_RESEARCH_PROFILES: Dict[
    ProceedingType, GstLegalResearchProfile
] = {
    ProceedingType.GST_SEC73_GENERAL: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_GENERAL,
        requirements=(
            _r(
                LegalTopic.HEARING_RIGHT,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.4.hearing",
            ),
            _r(
                LegalTopic.DEMAND_SCOPE,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.7.demand_scope",
            ),
        ),
    ),
    ProceedingType.GST_SEC73_ITC: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        requirements=(
            _r(
                LegalTopic.HEARING_RIGHT,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.4.hearing",
            ),
            _r(
                LegalTopic.DEMAND_SCOPE,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.7.demand_scope",
            ),
            _r(
                LegalTopic.ITC_MISMATCH_VERIFICATION,
                LegalDateBasis.TAX_PERIOD_END,
                "cbic.itc_mismatch_verification",
            ),
            _r(
                LegalTopic.ITC_ELIGIBILITY,
                LegalDateBasis.TAX_PERIOD_END,
            ),
        ),
    ),
    ProceedingType.GST_SEC73_RCM: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_RCM,
        requirements=(
            _r(
                LegalTopic.HEARING_RIGHT,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.4.hearing",
            ),
            _r(
                LegalTopic.DEMAND_SCOPE,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.7.demand_scope",
            ),
            _r(
                LegalTopic.RCM_APPLICABILITY,
                LegalDateBasis.TAX_PERIOD_END,
            ),
        ),
    ),
    ProceedingType.GST_SEC74_FRAUD: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC74_FRAUD,
        requirements=(
            _r(
                LegalTopic.HEARING_RIGHT,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.4.hearing",
            ),
            _r(
                LegalTopic.DEMAND_SCOPE,
                LegalDateBasis.NOTICE_DATE,
                "cgst.s75.7.demand_scope",
            ),
            _r(
                LegalTopic.FRAUD_SUPPRESSION_SCOPE,
                LegalDateBasis.TAX_PERIOD_END,
                "cgst.s74.fraud_scope",
            ),
        ),
    ),
    ProceedingType.GST_SEC129_ENFORCE: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
        requirements=(
            _r(
                LegalTopic.SECTION_129_TIMELINE,
                LegalDateBasis.DETENTION_OR_SEIZURE_DATE,
                "cgst.s129.3.timeline",
            ),
            _r(
                LegalTopic.SECTION_129_HEARING,
                LegalDateBasis.DETENTION_OR_SEIZURE_DATE,
                "cgst.s129.4.hearing",
            ),
        ),
    ),
}


def build_gst_legal_date_context(facts) -> LegalDateContext:
    """Workflow-owned facade for deterministic legal date provenance."""
    return build_legal_date_context(facts)


def get_gst_legal_research_profile(
    proceeding_type: ProceedingType,
):
    return GST_LEGAL_RESEARCH_PROFILES.get(proceeding_type)


def resolve_gst_legal_brief_from_context(
    proceeding_type: ProceedingType,
    date_context: LegalDateContext,
) -> LegalKnowledgeResult:
    """Resolve each topic only against its own provenance-bearing date."""
    profile = get_gst_legal_research_profile(proceeding_type)
    if profile is None:
        return LegalKnowledgeResult(
            matches=(),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version=GST_LEGAL_CATALOG_VERSION,
        )
    if not isinstance(date_context, LegalDateContext):
        raise TypeError("date_context must be a LegalDateContext")

    matches = []
    unresolved = []
    catalog_valid = True
    for requirement in profile.requirements:
        anchor = date_context.get(requirement.date_basis)
        if anchor is None:
            unresolved.append(requirement.topic)
            continue
        if (
            requirement.date_basis is LegalDateBasis.TAX_PERIOD_END
            and anchor.period_start is not None
            and anchor.period_end is not None
        ):
            resolved = resolve_legal_knowledge_interval(
                LegalKnowledgeIntervalQuery(
                    period_start=anchor.period_start,
                    period_end=anchor.period_end,
                    proceeding_type=proceeding_type,
                    topics=(requirement.topic,),
                ),
                catalog_version=GST_LEGAL_CATALOG_VERSION,
                sources=GST_LEGAL_SOURCES,
                rules=GST_LEGAL_RULES,
            )
        else:
            resolved = resolve_legal_knowledge(
                LegalKnowledgeQuery(
                    as_of_date=anchor.effective_date,
                    proceeding_type=proceeding_type,
                    topics=(requirement.topic,),
                ),
                catalog_version=GST_LEGAL_CATALOG_VERSION,
                sources=GST_LEGAL_SOURCES,
                rules=GST_LEGAL_RULES,
            )
        if not resolved.catalog_valid:
            catalog_valid = False
            unresolved.append(requirement.topic)
            continue

        # A topic is complete only when its closed workflow bundle is
        # represented exactly by the effective source-verified rules.
        # Empty bundles deliberately remain unresolved until curated.
        if not requirement.required_rule_keys:
            unresolved.append(requirement.topic)
            continue
        by_key = {}
        duplicate_key = False
        for match in resolved.matches:
            key = match.rule.rule_key
            if key in by_key:
                duplicate_key = True
                break
            by_key[key] = match
        required = tuple(requirement.required_rule_keys)
        if duplicate_key or set(by_key) != set(required):
            unresolved.append(requirement.topic)
            continue
        matches.extend(by_key[key] for key in required)

    return LegalKnowledgeResult(
        matches=tuple(matches),
        unresolved_topics=tuple(unresolved),
        catalog_valid=catalog_valid,
        catalog_version=GST_LEGAL_CATALOG_VERSION,
    )


def resolve_gst_legal_brief(
    proceeding_type: ProceedingType,
    as_of_date: date,
) -> LegalKnowledgeResult:
    """Backward-compatible notice-date-only legal research.

    New analysis paths should prefer resolve_gst_legal_brief_from_context
    once provenance-bearing legal date anchors are available.
    """
    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be a date")
    from domain.legal_date_models import LegalDateAnchor
    from domain.models import FactRole, FactType

    context = LegalDateContext(
        anchors=(
            LegalDateAnchor(
                basis=LegalDateBasis.NOTICE_DATE,
                effective_date=as_of_date,
                period_start=None,
                period_end=None,
                source_fact_id="legacy-notice-date",
                source_page=None,
                source_text=as_of_date.isoformat(),
                source_fact_type=FactType.NOTICE_DATE,
                source_fact_role=FactRole.NONE,
            ),
        )
    )
    return resolve_gst_legal_brief_from_context(
        proceeding_type,
        context,
    )
