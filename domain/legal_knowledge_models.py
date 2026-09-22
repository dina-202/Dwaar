"""Typed verified legal-knowledge contracts for Dwaar Phase 3N."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Tuple

from domain.models import ProceedingType


class LegalAuthorityKind(Enum):
    ACT_SECTION = "act_section"
    RULE = "rule"
    NOTIFICATION = "notification"
    CIRCULAR = "circular"
    ORDER = "order"
    INSTRUCTION_GUIDELINE = "instruction_guideline"


class OfficialLegalSource(Enum):
    CBIC_TAX_INFORMATION = "cbic_tax_information"
    INDIA_CODE = "india_code"


class LegalAuthorityStatus(Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    RESCINDED = "rescinded"
    UNKNOWN = "unknown"


class LegalApplicabilityStatus(Enum):
    APPLICABLE = "applicable"
    REQUIRES_PERIOD_VERIFICATION = "requires_period_verification"
    OUTSIDE_REGISTERED_PERIOD = "outside_registered_period"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class LegalAuthorityRef:
    authority_id: str
    kind: LegalAuthorityKind
    citation: str
    title: str
    source_provider: OfficialLegalSource
    source_url: str
    source_locator: str
    status: LegalAuthorityStatus
    verified_on: date
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    applies_from_fy: Optional[int] = None
    applies_through_fy: Optional[int] = None
    amendment_history_available: bool = False
    tags: Tuple[str, ...] = ()
    verification_notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowLegalAuthoritySpec:
    proceeding_type: ProceedingType
    required_authority_ids: Tuple[str, ...]
    supporting_authority_ids: Tuple[str, ...] = ()
    safety_authority_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LegalAuthorityMatch:
    authority: LegalAuthorityRef
    applicability: LegalApplicabilityStatus
    reason: str
    relationship: str


@dataclass(frozen=True)
class LegalResearchBundle:
    proceeding_type: ProceedingType
    tax_period_fiscal_years: Tuple[int, ...]
    matches: Tuple[LegalAuthorityMatch, ...]
    warnings: Tuple[str, ...]
    ca_legal_research_required: bool
