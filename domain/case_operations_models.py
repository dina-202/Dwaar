"""Case-operations contracts for Dwaar Phase 3J."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from domain.case_models import CaseStatus


class WorkQueueDeadlineStatus(Enum):
    OVERDUE = "overdue"
    DUE_TODAY = "due_today"
    DUE_SOON = "due_soon"
    UPCOMING = "upcoming"
    NO_DEADLINE = "no_deadline"
    CLOSED = "closed"


@dataclass(frozen=True)
class CaseWorkItem:
    case_id: str
    client_id: str
    client_name: str
    title: str
    status: CaseStatus
    response_deadline: Optional[date]
    days_remaining: Optional[int]
    deadline_status: WorkQueueDeadlineStatus
    assigned_to: Optional[str]
    reviewer_id: Optional[str]


@dataclass(frozen=True)
class CaseOperationsUpdate:
    status: CaseStatus
    response_deadline: Optional[date]
    assigned_to: Optional[str]
    reviewer_id: Optional[str]
