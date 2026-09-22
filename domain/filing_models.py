"""Durable filing and acknowledgement contracts for Dwaar Phase 3L."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FilingRecord:
    """Metadata linking an actual portal filing to approved work product."""

    filing_id: str
    case_id: str
    approved_draft_version_id: str
    filed_response_document_id: str
    acknowledgement_document_id: Optional[str]
    filing_reference: str
    filed_at: datetime
    filed_by: str
    recorded_at: datetime
    acknowledgement_added_at: Optional[datetime] = None
    acknowledgement_added_by: Optional[str] = None
