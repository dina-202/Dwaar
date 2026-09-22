"""Provenance-bearing legal applicability dates for Dwaar Phase 3N.5."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Tuple

from domain.models import FactRole, FactType


class LegalDateBasis(Enum):
    NOTICE_DATE = "notice_date"
    TAX_PERIOD_END = "tax_period_end"
    DETENTION_OR_SEIZURE_DATE = "detention_or_seizure_date"


@dataclass(frozen=True)
class LegalDateAnchor:
    """One deterministic legal-version date with source-fact provenance."""

    basis: LegalDateBasis
    effective_date: date
    period_start: Optional[date]
    period_end: Optional[date]
    source_fact_id: str
    source_page: Optional[int]
    source_text: str
    source_fact_type: FactType
    source_fact_role: FactRole


@dataclass(frozen=True)
class LegalDateContext:
    """Closed collection of available date anchors for one analysis."""

    anchors: Tuple[LegalDateAnchor, ...]

    def get(self, basis: LegalDateBasis) -> Optional[LegalDateAnchor]:
        matches = tuple(item for item in self.anchors if item.basis is basis)
        if len(matches) != 1:
            return None
        return matches[0]
