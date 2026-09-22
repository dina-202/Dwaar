"""Closed GST legal-research plans for Phase 3N.

This module chooses research TOPICS, not legal outcomes. It delegates all
source/version/date trust decisions to domain.legal_knowledge.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple

from domain.legal_knowledge import resolve_legal_knowledge
from domain.legal_knowledge_models import (
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
class GstLegalResearchProfile:
    proceeding_type: ProceedingType
    topics: Tuple[LegalTopic, ...]


GST_LEGAL_RESEARCH_PROFILES: Dict[
    ProceedingType, GstLegalResearchProfile
] = {
    ProceedingType.GST_SEC73_GENERAL: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_GENERAL,
        topics=(
            LegalTopic.HEARING_RIGHT,
            LegalTopic.DEMAND_SCOPE,
        ),
    ),
    ProceedingType.GST_SEC73_ITC: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        topics=(
            LegalTopic.HEARING_RIGHT,
            LegalTopic.DEMAND_SCOPE,
            LegalTopic.ITC_ELIGIBILITY,
        ),
    ),
    ProceedingType.GST_SEC73_RCM: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC73_RCM,
        topics=(
            LegalTopic.HEARING_RIGHT,
            LegalTopic.DEMAND_SCOPE,
            LegalTopic.RCM_APPLICABILITY,
        ),
    ),
    ProceedingType.GST_SEC74_FRAUD: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC74_FRAUD,
        topics=(
            LegalTopic.HEARING_RIGHT,
            LegalTopic.DEMAND_SCOPE,
            LegalTopic.FRAUD_SUPPRESSION_SCOPE,
        ),
    ),
    ProceedingType.GST_SEC129_ENFORCE: GstLegalResearchProfile(
        proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
        topics=(
            LegalTopic.SECTION_129_TIMELINE,
            LegalTopic.SECTION_129_HEARING,
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
    profile = get_gst_legal_research_profile(proceeding_type)
    if profile is None:
        return LegalKnowledgeResult(
            matches=(),
            unresolved_topics=(),
            catalog_valid=True,
            catalog_version=GST_LEGAL_CATALOG_VERSION,
        )
    from domain.legal_knowledge_models import LegalKnowledgeQuery

    return resolve_legal_knowledge(
        LegalKnowledgeQuery(
            as_of_date=as_of_date,
            proceeding_type=proceeding_type,
            topics=profile.topics,
        ),
        catalog_version=GST_LEGAL_CATALOG_VERSION,
        sources=GST_LEGAL_SOURCES,
        rules=GST_LEGAL_RULES,
    )
