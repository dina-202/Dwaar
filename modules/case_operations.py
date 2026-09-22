"""Deterministic case-operations rules for Dwaar Phase 3J."""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List

from domain.case_models import CaseRecord, CaseStatus, Client
from domain.case_operations_models import (
    CaseOperationsUpdate,
    CaseWorkItem,
    WorkQueueDeadlineStatus,
)


_DUE_SOON_DAYS = 7

_ALLOWED_STATUS_TRANSITIONS = {
    CaseStatus.INTAKE: frozenset(
        {
            CaseStatus.ANALYZED,
            CaseStatus.EVIDENCE_COLLECTION,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.ANALYZED: frozenset(
        {
            CaseStatus.EVIDENCE_COLLECTION,
            CaseStatus.DRAFT_REVIEW,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.EVIDENCE_COLLECTION: frozenset(
        {
            CaseStatus.ANALYZED,
            CaseStatus.DRAFT_REVIEW,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.DRAFT_REVIEW: frozenset(
        {
            CaseStatus.EVIDENCE_COLLECTION,
            CaseStatus.FILED,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.FILED: frozenset(
        {
            CaseStatus.HEARING,
            CaseStatus.ORDER_RECEIVED,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.HEARING: frozenset(
        {
            CaseStatus.FILED,
            CaseStatus.ORDER_RECEIVED,
            CaseStatus.CLOSED,
        }
    ),
    CaseStatus.ORDER_RECEIVED: frozenset({CaseStatus.CLOSED}),
    CaseStatus.CLOSED: frozenset(),
}


def allowed_status_targets(current: CaseStatus) -> tuple[CaseStatus, ...]:
    if not isinstance(current, CaseStatus):
        raise TypeError("current must be a CaseStatus")
    return (current,) + tuple(
        sorted(
            _ALLOWED_STATUS_TRANSITIONS[current],
            key=lambda item: list(CaseStatus).index(item),
        )
    )


def validate_status_transition(
    current: CaseStatus,
    target: CaseStatus,
) -> None:
    if not isinstance(current, CaseStatus):
        raise TypeError("current must be a CaseStatus")
    if not isinstance(target, CaseStatus):
        raise TypeError("target must be a CaseStatus")
    if target is current:
        return
    if target not in _ALLOWED_STATUS_TRANSITIONS[current]:
        raise ValueError(
            f"case status transition {current.value} -> "
            f"{target.value} is not allowed"
        )


def normalize_operations_update(
    *,
    status: CaseStatus,
    response_deadline,
    assigned_to,
    reviewer_id,
) -> CaseOperationsUpdate:
    if not isinstance(status, CaseStatus):
        raise TypeError("status must be a CaseStatus")
    if response_deadline is not None and not isinstance(
        response_deadline, date
    ):
        raise TypeError("response_deadline must be a date or None")

    def _identity(value, label):
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a string or None")
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 256:
            raise ValueError(f"{label} is too long")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError(f"{label} contains control characters")
        return normalized

    return CaseOperationsUpdate(
        status=status,
        response_deadline=response_deadline,
        assigned_to=_identity(assigned_to, "assigned_to"),
        reviewer_id=_identity(reviewer_id, "reviewer_id"),
    )


def deadline_status_for_case(
    case: CaseRecord,
    today: date,
) -> tuple[WorkQueueDeadlineStatus, int | None]:
    if not isinstance(case, CaseRecord):
        raise TypeError("case must be a CaseRecord")
    if not isinstance(today, date):
        raise TypeError("today must be a date")

    if case.status is CaseStatus.CLOSED:
        return WorkQueueDeadlineStatus.CLOSED, None
    if case.response_deadline is None:
        return WorkQueueDeadlineStatus.NO_DEADLINE, None

    days = (case.response_deadline - today).days
    if days < 0:
        return WorkQueueDeadlineStatus.OVERDUE, days
    if days == 0:
        return WorkQueueDeadlineStatus.DUE_TODAY, 0
    if days <= _DUE_SOON_DAYS:
        return WorkQueueDeadlineStatus.DUE_SOON, days
    return WorkQueueDeadlineStatus.UPCOMING, days


def build_case_work_queue(
    cases: Iterable[CaseRecord],
    clients: Iterable[Client],
    today: date,
) -> List[CaseWorkItem]:
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    case_list = list(cases)
    client_list = list(clients)
    if any(not isinstance(item, CaseRecord) for item in case_list):
        raise TypeError("cases must contain only CaseRecord values")
    if any(not isinstance(item, Client) for item in client_list):
        raise TypeError("clients must contain only Client values")

    clients_by_id: Dict[str, Client] = {}
    for client in client_list:
        if client.client_id in clients_by_id:
            raise ValueError("duplicate client_id in work queue input")
        clients_by_id[client.client_id] = client

    items = []
    for case in case_list:
        client = clients_by_id.get(case.client_id)
        if client is None:
            raise ValueError(
                "work queue case references unavailable client"
            )
        deadline_status, days_remaining = deadline_status_for_case(
            case,
            today,
        )
        items.append(
            CaseWorkItem(
                case_id=case.case_id,
                client_id=case.client_id,
                client_name=client.display_name,
                title=case.title,
                status=case.status,
                response_deadline=case.response_deadline,
                days_remaining=days_remaining,
                deadline_status=deadline_status,
                assigned_to=case.assigned_to,
                reviewer_id=case.reviewer_id,
            )
        )

    priority = {
        WorkQueueDeadlineStatus.OVERDUE: 0,
        WorkQueueDeadlineStatus.DUE_TODAY: 1,
        WorkQueueDeadlineStatus.DUE_SOON: 2,
        WorkQueueDeadlineStatus.UPCOMING: 3,
        WorkQueueDeadlineStatus.NO_DEADLINE: 4,
        WorkQueueDeadlineStatus.CLOSED: 5,
    }

    def _sort_key(item: CaseWorkItem):
        deadline = (
            item.response_deadline.toordinal()
            if item.response_deadline is not None
            else 10**9
        )
        return (
            priority[item.deadline_status],
            deadline,
            item.client_name.casefold(),
            item.case_id,
        )

    return sorted(items, key=_sort_key)
