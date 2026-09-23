"""Immutable contracts for Dwaar Phase 3N verified legal knowledge."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Tuple

from domain.models import ProceedingType


class LegalAuthorityType(Enum):
    ACT = "act"
    RULE = "rule"
    NOTIFICATION = "notification"
    CIRCULAR = "circular"
    ORDER = "order"
    JUDGMENT = "judgment"


class LegalVerificationStatus(Enum):
    SOURCE_VERIFIED = "source_verified"
    REQUIRES_VERIFICATION = "requires_verification"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class LegalTopic(Enum):
    HEARING_RIGHT = "hearing_right"
    DEMAND_SCOPE = "demand_scope"
    SECTION_129_TIMELINE = "section_129_timeline"
    SECTION_129_HEARING = "section_129_hearing"
    ITC_ELIGIBILITY = "itc_eligibility"
    ITC_MISMATCH_VERIFICATION = "itc_mismatch_verification"
    RCM_APPLICABILITY = "rcm_applicability"
    FRAUD_SUPPRESSION_SCOPE = "fraud_suppression_scope"


@dataclass(frozen=True)
class LegalSourceRef:
    source_id: str
    authority_type: LegalAuthorityType
    title: str
    issuer: str
    official_url: str
    official_domain: str
    version_label: str
    publication_date: Optional[date]
    retrieved_at: date
    verification_status: LegalVerificationStatus


@dataclass(frozen=True)
class LegalRule:
    rule_id: str
    rule_key: str
    source_id: str
    provision: str
    proposition: str
    effective_from: date
    effective_to: Optional[date]
    jurisdiction: str
    topic: LegalTopic
    proceeding_types: Tuple[ProceedingType, ...]
    verified_at: date
    verification_status: LegalVerificationStatus


@dataclass(frozen=True)
class LegalKnowledgeQuery:
    as_of_date: date
    proceeding_type: ProceedingType
    topics: Tuple[LegalTopic, ...]


@dataclass(frozen=True)
class LegalKnowledgeIntervalQuery:
    period_start: date
    period_end: date
    proceeding_type: ProceedingType
    topics: Tuple[LegalTopic, ...]


@dataclass(frozen=True)
class LegalRuleMatch:
    rule: LegalRule
    source: LegalSourceRef


@dataclass(frozen=True)
class LegalKnowledgeResult:
    matches: Tuple[LegalRuleMatch, ...]
    unresolved_topics: Tuple[LegalTopic, ...]
    catalog_valid: bool
    catalog_version: str
