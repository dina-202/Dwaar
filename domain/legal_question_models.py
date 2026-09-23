"""Deterministic legal-question planning contracts for Dwaar Phase 3N.8."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from domain.legal_date_models import LegalDateBasis
from domain.legal_knowledge_models import LegalTopic
from domain.models import FactRole, FactStatus, FactType, ProceedingType


class LegalQuestionStatus(Enum):
    MISSING_FACTS = "missing_facts"
    MISSING_DATE = "missing_date"
    AUTHORITY_UNCURATED = "authority_uncurated"
    SOURCE_VERIFIED_RESEARCH_READY = "source_verified_research_ready"


@dataclass(frozen=True)
class LegalFactSelector:
    fact_type: FactType
    fact_role: FactRole
    accepted_statuses: Tuple[FactStatus, ...]


@dataclass(frozen=True)
class GstLegalQuestionSpec:
    question_id: str
    proceeding_type: ProceedingType
    question_text: str
    topic: LegalTopic
    date_basis: LegalDateBasis
    required_facts: Tuple[LegalFactSelector, ...]


@dataclass(frozen=True)
class LegalQuestionResult:
    question_id: str
    question_text: str
    topic: LegalTopic
    date_basis: LegalDateBasis
    status: LegalQuestionStatus
    related_fact_ids: Tuple[str, ...]
    missing_fact_selectors: Tuple[LegalFactSelector, ...]
    matched_rule_ids: Tuple[str, ...]


@dataclass(frozen=True)
class LegalQuestionPlan:
    proceeding_type: ProceedingType
    questions: Tuple[LegalQuestionResult, ...]
    catalog_version: Optional[str]
