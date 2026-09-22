"""Read-only unified case timeline contracts for Dwaar Phase 3M."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from domain.case_models import CaseEventType


class TimelineCategory(Enum):
    CASE = "case"
    DOCUMENT = "document"
    ANALYSIS = "analysis"
    EVIDENCE = "evidence"
    DRAFT = "draft"
    FILING = "filing"
    HEARING = "hearing"
    ORDER = "order"


@dataclass(frozen=True)
class CaseTimelineItem:
    event_id: str
    event_type: CaseEventType
    category: TimelineCategory
    occurred_at: datetime
    actor_id: Optional[str]
    title: str
    summary: str
