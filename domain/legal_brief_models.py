"""Snapshot-bound legal brief contracts for Dwaar Phase 3N.2."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict

from domain.models import ProceedingType


LEGAL_BRIEF_SCHEMA_VERSION = 2
SUPPORTED_LEGAL_BRIEF_SCHEMA_VERSIONS = (1, 2)


@dataclass(frozen=True)
class LegalBriefRef:
    legal_brief_id: str
    case_id: str
    snapshot_id: str
    schema_version: int
    catalog_version: str
    as_of_date: date
    proceeding_type: ProceedingType
    byte_size: int
    sha256_hex: str
    storage_key: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True)
class LoadedLegalBrief:
    metadata: LegalBriefRef
    payload: Dict[str, object]
