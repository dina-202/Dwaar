"""Closed GST legal-question plans over verified facts and legal research."""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

from domain.legal_date_models import LegalDateContext
from domain.legal_knowledge_models import LegalKnowledgeResult, LegalTopic
from domain.legal_question_models import (
    GstLegalQuestionSpec,
    LegalFactSelector,
    LegalQuestionPlan,
    LegalQuestionResult,
    LegalQuestionStatus,
)
from domain.models import (
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    SourceVerificationStatus,
)
from workflows.gst.legal_research import (
    GST_LEGAL_RESEARCH_PROFILES,
    resolve_gst_legal_brief_from_context,
)


def _selector(
    fact_type: FactType,
    fact_role: FactRole = FactRole.NONE,
    *accepted_statuses: FactStatus,
) -> LegalFactSelector:
    statuses = accepted_statuses or (FactStatus.CONFIRMED,)
    return LegalFactSelector(
        fact_type=fact_type,
        fact_role=fact_role,
        accepted_statuses=tuple(statuses),
    )


def _question(
    question_id: str,
    proceeding_type: ProceedingType,
    question_text: str,
    topic: LegalTopic,
    *required_facts: LegalFactSelector,
) -> GstLegalQuestionSpec:
    profile = GST_LEGAL_RESEARCH_PROFILES[proceeding_type]
    requirements = [
        item for item in profile.requirements if item.topic is topic
    ]
    if len(requirements) != 1:
        raise RuntimeError(
            "legal question topic must map to exactly one research requirement"
        )
    return GstLegalQuestionSpec(
        question_id=question_id,
        proceeding_type=proceeding_type,
        question_text=question_text,
        topic=topic,
        date_basis=requirements[0].date_basis,
        required_facts=tuple(required_facts),
    )


_COMMON_73_74 = {
    "hearing": (
        "What source-verified hearing protection applies to this proceeding?",
        LegalTopic.HEARING_RIGHT,
    ),
    "demand_scope": (
        "What source-verified limit applies to the scope of the adjudicated demand?",
        LegalTopic.DEMAND_SCOPE,
    ),
}


def _common(proceeding_type: ProceedingType):
    return (
        _question(
            f"{proceeding_type.value}.hearing",
            proceeding_type,
            _COMMON_73_74["hearing"][0],
            _COMMON_73_74["hearing"][1],
        ),
        _question(
            f"{proceeding_type.value}.demand_scope",
            proceeding_type,
            _COMMON_73_74["demand_scope"][0],
            _COMMON_73_74["demand_scope"][1],
        ),
    )


GST_LEGAL_QUESTION_PLANS: Dict[
    ProceedingType, Tuple[GstLegalQuestionSpec, ...]
] = {
    ProceedingType.GST_SEC61_SCRUTINY: (
        _question(
            "gst_sec61_scrutiny.process",
            ProceedingType.GST_SEC61_SCRUTINY,
            (
                "What source-verified Section 61 / Rule 99 scrutiny process "
                "and response forms apply to this ASMT-10?"
            ),
            LegalTopic.SCRUTINY_PROCESS,
        ),
    ),
    ProceedingType.GST_SEC73_GENERAL: _common(
        ProceedingType.GST_SEC73_GENERAL
    ),
    ProceedingType.GST_SEC73_ITC: _common(
        ProceedingType.GST_SEC73_ITC
    )
    + (
        _question(
            "gst_sec73_itc.mismatch_verification",
            ProceedingType.GST_SEC73_ITC,
            (
                "Which source-verified GSTR-3B versus supplier-statement "
                "mismatch-verification regime governs the relevant period?"
            ),
            LegalTopic.ITC_MISMATCH_VERIFICATION,
            _selector(FactType.TAX_PERIOD),
        ),
        _question(
            "gst_sec73_itc.eligibility",
            ProceedingType.GST_SEC73_ITC,
            (
                "Which source-verified ITC eligibility rules govern the "
                "relevant period before applying them to the taxpayer's "
                "invoice-level facts?"
            ),
            LegalTopic.ITC_ELIGIBILITY,
            _selector(FactType.TAX_PERIOD),
            _selector(
                FactType.STATED_AMOUNT,
                FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            _selector(
                FactType.STATED_AMOUNT,
                FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
        ),
    ),
    ProceedingType.GST_SEC73_RCM: _common(
        ProceedingType.GST_SEC73_RCM
    )
    + (
        _question(
            "gst_sec73_rcm.applicability",
            ProceedingType.GST_SEC73_RCM,
            (
                "Which source-verified RCM authorities govern the alleged "
                "supply category and period?"
            ),
            LegalTopic.RCM_APPLICABILITY,
            _selector(FactType.TAX_PERIOD),
            _selector(
                FactType.DEPARTMENT_ALLEGATION,
                FactRole.RCM_CATEGORY_ALLEGED,
                FactStatus.ALLEGED,
            ),
        ),
    ),
    ProceedingType.GST_SEC74_FRAUD: _common(
        ProceedingType.GST_SEC74_FRAUD
    )
    + (
        _question(
            "gst_sec74_fraud.period_scope",
            ProceedingType.GST_SEC74_FRAUD,
            (
                "Which source-verified fraud/suppression demand provision "
                "governs the alleged period?"
            ),
            LegalTopic.FRAUD_SUPPRESSION_SCOPE,
            _selector(FactType.TAX_PERIOD),
            _selector(
                FactType.DEPARTMENT_ALLEGATION,
                FactRole.FRAUD_BASIS_ALLEGED,
                FactStatus.ALLEGED,
            ),
        ),
    ),
    ProceedingType.GST_SEC129_ENFORCE: (
        _question(
            "gst_sec129.timeline",
            ProceedingType.GST_SEC129_ENFORCE,
            (
                "Which source-verified Section 129 notice/order timing rule "
                "governs the detention or seizure date?"
            ),
            LegalTopic.SECTION_129_TIMELINE,
            _selector(
                FactType.DOCUMENT_DETAIL,
                FactRole.DETENTION_OR_SEIZURE_DATE,
            ),
        ),
        _question(
            "gst_sec129.hearing",
            ProceedingType.GST_SEC129_ENFORCE,
            (
                "Which source-verified hearing protection applies to the "
                "Section 129 penalty determination?"
            ),
            LegalTopic.SECTION_129_HEARING,
            _selector(
                FactType.DOCUMENT_DETAIL,
                FactRole.DETENTION_OR_SEIZURE_DATE,
            ),
        ),
    ),
}


def _fact_matches(
    fact: ExtractedFact,
    selector: LegalFactSelector,
) -> bool:
    return (
        fact.fact_type is selector.fact_type
        and fact.fact_role is selector.fact_role
        and fact.status in selector.accepted_statuses
        and fact.source_verification is SourceVerificationStatus.VERIFIED
        and isinstance(fact.source_text, str)
        and bool(fact.source_text.strip())
    )


def build_gst_legal_question_plan(
    proceeding_type: ProceedingType,
    facts: Iterable[ExtractedFact],
    date_context: LegalDateContext,
) -> LegalQuestionPlan:
    if not isinstance(proceeding_type, ProceedingType):
        raise TypeError("proceeding_type must be a ProceedingType")
    if not isinstance(date_context, LegalDateContext):
        raise TypeError("date_context must be a LegalDateContext")
    fact_list = tuple(facts)
    if any(not isinstance(item, ExtractedFact) for item in fact_list):
        raise TypeError("facts must contain only ExtractedFact values")

    specs = GST_LEGAL_QUESTION_PLANS.get(proceeding_type, ())
    legal_result = resolve_gst_legal_brief_from_context(
        proceeding_type,
        date_context,
    )
    matches_by_topic = {}
    for match in legal_result.matches:
        matches_by_topic.setdefault(match.rule.topic, []).append(match)

    results = []
    for spec in specs:
        related_ids = []
        missing = []
        for selector in spec.required_facts:
            matched = [
                fact for fact in fact_list
                if _fact_matches(fact, selector)
            ]
            if len(matched) != 1:
                missing.append(selector)
                continue
            related_ids.append(matched[0].fact_id)

        if missing:
            status = LegalQuestionStatus.MISSING_FACTS
            rule_ids = ()
        elif date_context.get(spec.date_basis) is None:
            status = LegalQuestionStatus.MISSING_DATE
            rule_ids = ()
        else:
            topic_matches = tuple(matches_by_topic.get(spec.topic, ()))
            if spec.topic in legal_result.unresolved_topics or not topic_matches:
                status = LegalQuestionStatus.AUTHORITY_UNCURATED
                rule_ids = ()
            else:
                status = LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY
                rule_ids = tuple(item.rule.rule_id for item in topic_matches)

        results.append(
            LegalQuestionResult(
                question_id=spec.question_id,
                question_text=spec.question_text,
                topic=spec.topic,
                date_basis=spec.date_basis,
                status=status,
                related_fact_ids=tuple(related_ids),
                missing_fact_selectors=tuple(missing),
                matched_rule_ids=rule_ids,
            )
        )

    return LegalQuestionPlan(
        proceeding_type=proceeding_type,
        questions=tuple(results),
        catalog_version=legal_result.catalog_version,
    )
