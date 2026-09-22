"""Closed GST legal-research plans for Phase 3N.

This module chooses research TOPICS and their legal applicability date basis,
not legal outcomes. Only topics whose required date basis is explicitly
available may enter the trusted resolver.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, Tuple

from domain.legal_knowledge import resolve_legal_knowledge
from domain.legal_knowledge_models import (
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


class LegalDateBasis(Enum):
    NOTICE_DATE = "notice_date"
    TAX_PERIOD_END = "tax_period_end"
    DETENTION_OR_SEIZURE_DATE = "detention_or_seizure_date"


@dataclass(frozen=True)
class GstLegalResearchRequirement:
    topic: LegalTopic
    date_basis: LegalDateBasis


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
) -> GstLegalResearchRequirement:
    return GstLegalResearchRequirement(topic=topic, date_basis=date_basis)


GST_LEGAL_RESEARCH_PROFILES: Dict[
    ProceedingType, GstLegalResearchProfile
] = {
    ProceedingType.GST_SEC73_GENERAL: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_GENERAL,
        requirements=(
            _r(LegalTopic.HEARING_RIGHT, LegalDateBasis.NOTICE_DATE),
            _r(LegalTopic.DEMAND_SCOPE, LegalDateBasis.NOTICE_DATE),
        ),
    ),
    ProceedingType.GST_SEC73_ITC: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        requirements=(
            _r(LegalTopic.HEARING_RIGHT, LegalDateBasis.NOTICE_DATE),
            _r(LegalTopic.DEMAND_SCOPE, LegalDateBasis.NOTICE_DATE),
            _r(LegalTopic.ITC_ELIGIBILITY, LegalDateBasis.TAX_PERIOD_END),
        ),
    ),
    ProceedingType.GST_SEC73_RCM: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_RCM,
        requirements=(
            _r(LegalTopic.HEARING_RIGHT, LegalDateBasis.NOTICE_DATE),
            _r(LegalTopic.DEMAND_SCOPE, LegalDateBasis.NOTICE_DATE),
            _r(
                LegalTopic.RCM_APPLICABILITY,
                LegalDateBasis.TAX_PERIOD_END,
            ),
        ),
    ),
    ProceedingType.GST_SEC74_FRAUD: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC74_FRAUD,
        requirements=(
            _r(LegalTopic.HEARING_RIGHT, LegalDateBasis.NOTICE_DATE),
            _r(LegalTopic.DEMAND_SCOPE, LegalDateBasis.NOTICE_DATE),
            _r(
                LegalTopic.FRAUD_SUPPRESSION_SCOPE,
                LegalDateBasis.TAX_PERIOD_END,
            ),
        ),
    ),
    ProceedingType.GST_SEC129_ENFORCE: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
        requirements=(
            _r(
                LegalTopic.SECTION_129_TIMELINE,
                LegalDateBasis.DETENTION_OR_SEIZURE_DATE,
            ),
            _r(
                LegalTopic.SECTION_129_HEARING,
                LegalDateBasis.DETENTION_OR_SEIZURE_DATE,
            ),
        ),
    ),
}


def get_gst_legal_research_profile(
    proceeding_type: ProceedingType,
):
    return GST_LEGAL_RESEARCH_PROFILES.get(proceeding_type)


def resolve_gst_legal_brief(
    proceeding_type: ProceedingType,
    as_of_date: date,
) -> LegalKnowledgeResult:
    """Resolve only NOTICE_DATE-basis topics.

    The current call contract receives exactly one date: the verified notice
    date. Topics requiring a tax-period end or detention/seizure date remain
    explicitly unresolved until those dates have their own deterministic,
    provenance-bearing contracts.
    """
    profile = get_gst_legal_research_profile(proceeding_type)
    if profile is None:
        return LegalKnowledgeResult(
            matches=(),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version=GST_LEGAL_CATALOG_VERSION,
        )
    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be a date")

    notice_topics = tuple(
        item.topic
        for item in profile.requirements
        if item.date_basis is LegalDateBasis.NOTICE_DATE
    )
    resolved = resolve_legal_knowledge(
        LegalKnowledgeQuery(
            as_of_date=as_of_date,
            proceeding_type=proceeding_type,
            topics=notice_topics,
        ),
        catalog_version=GST_LEGAL_CATALOG_VERSION,
        sources=GST_LEGAL_SOURCES,
        rules=GST_LEGAL_RULES,
    )
    matched_topics = {item.rule.topic for item in resolved.matches}
    unresolved = tuple(
        item.topic
        for item in profile.requirements
        if item.topic not in matched_topics
    )
    return LegalKnowledgeResult(
        matches=resolved.matches,
        unresolved_topics=unresolved,
        catalog_valid=resolved.catalog_valid,
        catalog_version=resolved.catalog_version,
    )
