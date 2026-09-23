"""Deterministic professional overlay for the existing case work queue."""

from __future__ import annotations

from typing import Iterable, List

from domain.case_operations_models import CaseWorkItem
from domain.professional_queue_models import ProfessionalQueueItem
from domain.professional_workbench_models import ProfessionalCaseAttention


def build_professional_case_queue(
    work_items: Iterable[CaseWorkItem],
    attentions: Iterable[ProfessionalCaseAttention],
) -> List[ProfessionalQueueItem]:
    """Enrich the existing queue without changing its ordering."""
    queue = tuple(work_items)
    attention_list = tuple(attentions)

    if any(not isinstance(item, CaseWorkItem) for item in queue):
        raise TypeError("work_items must contain only CaseWorkItem values")
    if any(
        not isinstance(item, ProfessionalCaseAttention)
        for item in attention_list
    ):
        raise TypeError(
            "attentions must contain only ProfessionalCaseAttention values"
        )

    queue_ids = [item.case_id for item in queue]
    if len(queue_ids) != len(set(queue_ids)):
        raise ValueError("work queue contains duplicate case_id")

    attention_by_case = {}
    for attention in attention_list:
        if attention.case_id in attention_by_case:
            raise ValueError("duplicate case attention in queue input")
        attention_by_case[attention.case_id] = attention

    if set(attention_by_case) != set(queue_ids):
        raise ValueError(
            "professional queue requires exactly one attention projection "
            "per work-queue case"
        )

    rows = []
    for work_item in queue:
        attention = attention_by_case[work_item.case_id]
        workspaces = []
        seen_workspaces = set()
        for item in attention.items:
            workspace = item.code.workspace
            if workspace in seen_workspaces:
                continue
            seen_workspaces.add(workspace)
            workspaces.append(workspace)

        rows.append(
            ProfessionalQueueItem(
                work_item=work_item,
                attention_codes=tuple(
                    item.code for item in attention.items
                ),
                attention_workspaces=tuple(workspaces),
            )
        )
    return rows
