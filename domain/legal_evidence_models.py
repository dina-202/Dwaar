"""Legal evidence-readiness contracts for Dwaar Phase 3N.14."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class LegalEvidenceReadinessStatus(Enum):
    NO_CONFIRMED_EVIDENCE = "no_confirmed_evidence"
    PARTIAL_CONFIRMED_EVIDENCE = "partial_confirmed_evidence"
    REQUIRED_EVIDENCE_CONFIRMED = "required_evidence_confirmed"


@dataclass(frozen=True)
class LegalEvidenceRequirement:
    question_id: str
    required_evidence_ids: Tuple[str, ...]


@dataclass(frozen=True)
class LegalEvidenceReadiness:
    question_id: str
    status: LegalEvidenceReadinessStatus
    required_evidence_ids: Tuple[str, ...]
    confirmed_evidence_ids: Tuple[str, ...]
    missing_evidence_ids: Tuple[str, ...]
    confirmed_review_ids: Tuple[str, ...]
