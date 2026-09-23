"""Closed GST legal-research plans for Phase 3N.

This module chooses research TOPICS and their legal applicability date basis,
not legal outcomes. Only topics whose required date basis is explicitly
available may enter the trusted resolver.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple

from domain.legal_date_models import LegalDateBasis, LegalDateContext
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
        if len(resolved.matches) != 1:
            unresolved.append(requirement.topic)
            continue
        matches.extend(resolved.matches)

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
