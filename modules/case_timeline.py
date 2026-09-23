"""Deterministic projection from audit events to professional timeline items."""

from __future__ import annotations

from typing import Iterable, List

from domain.case_models import CaseEvent, CaseEventType
from domain.case_timeline_models import CaseTimelineItem, TimelineCategory


_CATEGORY = {
    CaseEventType.CASE_CREATED: TimelineCategory.CASE,
    CaseEventType.CASE_STATUS_CHANGED: TimelineCategory.CASE,
    CaseEventType.CASE_OPERATIONS_UPDATED: TimelineCategory.CASE,
    CaseEventType.DOCUMENT_ADDED: TimelineCategory.DOCUMENT,
    CaseEventType.DOCUMENT_REMOVED: TimelineCategory.DOCUMENT,
    CaseEventType.ANALYSIS_SAVED: TimelineCategory.ANALYSIS,
    CaseEventType.LEGAL_BRIEF_SAVED: TimelineCategory.ANALYSIS,
    CaseEventType.EVIDENCE_CANDIDATES_GENERATED: TimelineCategory.EVIDENCE,
    CaseEventType.EVIDENCE_REVIEWED: TimelineCategory.EVIDENCE,
    CaseEventType.FACT_REVIEWED: TimelineCategory.ANALYSIS,
    CaseEventType.DRAFT_CREATED: TimelineCategory.DRAFT,
    CaseEventType.DRAFT_REVIEWED: TimelineCategory.DRAFT,
    CaseEventType.FILING_RECORDED: TimelineCategory.FILING,
    CaseEventType.FILING_ACKNOWLEDGEMENT_RECORDED: TimelineCategory.FILING,
    CaseEventType.HEARING_RECORDED: TimelineCategory.HEARING,
    CaseEventType.ORDER_RECORDED: TimelineCategory.ORDER,
}


def _value(payload: dict[str, str], key: str, fallback: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) and value else fallback


def _render(event: CaseEvent) -> tuple[str, str]:
    p = event.payload
    t = event.event_type

    if t is CaseEventType.CASE_CREATED:
        return "Case created", (
            "Case entered Dwaar with status "
            + _value(p, "status", "recorded")
            + "."
        )
    if t is CaseEventType.CASE_STATUS_CHANGED:
        return "Case status changed", (
            _value(p, "from_status", "previous")
            + " → "
            + _value(p, "to_status", "updated")
        )
    if t is CaseEventType.CASE_OPERATIONS_UPDATED:
        return "Case operations updated", (
            "Deadline, assignment or reviewer metadata was updated."
        )
    if t is CaseEventType.DOCUMENT_ADDED:
        return "Document added", (
            "Case document recorded: "
            + _value(p, "kind", "document")
            + "."
        )
    if t is CaseEventType.DOCUMENT_REMOVED:
        return "Document removed", "A case document reference was removed."
    if t is CaseEventType.ANALYSIS_SAVED:
        return "Analysis snapshot saved", (
            "Snapshot "
            + _value(p, "snapshot_id", "recorded")
            + " was preserved."
        )
    if t is CaseEventType.LEGAL_BRIEF_SAVED:
        return "Verified legal brief saved", (
            "Legal brief "
            + _value(p, "legal_brief_id", "recorded")
            + " was preserved against analysis snapshot "
            + _value(p, "snapshot_id", "recorded")
            + "."
        )
    if t is CaseEventType.EVIDENCE_CANDIDATES_GENERATED:
        return "Evidence candidates generated", (
            "Source-grounded evidence candidates were generated for review."
        )
    if t is CaseEventType.EVIDENCE_REVIEWED:
        return "Evidence reviewed", (
            "Evidence "
            + _value(p, "evidence_id", "item")
            + " was "
            + _value(p, "decision", "reviewed")
            + "."
        )
    if t is CaseEventType.FACT_REVIEWED:
        return "Extracted fact reviewed", (
            "Fact "
            + _value(p, "fact_id", "item")
            + " was "
            + _value(p, "decision", "reviewed")
            + " by a professional."
        )
    if t is CaseEventType.DRAFT_CREATED:
        return "Draft version created", (
            "Draft version "
            + _value(p, "version_number", "recorded")
            + " was saved."
        )
    if t is CaseEventType.DRAFT_REVIEWED:
        return "Draft review state changed", (
            "Draft version "
            + _value(p, "version_number", "recorded")
            + ": "
            + _value(p, "from_status", "previous")
            + " → "
            + _value(p, "to_status", "updated")
        )
    if t is CaseEventType.FILING_RECORDED:
        return "Filing recorded", (
            "Portal / filing reference "
            + _value(p, "filing_reference", "recorded")
            + "."
        )
    if t is CaseEventType.FILING_ACKNOWLEDGEMENT_RECORDED:
        return "Filing acknowledgement recorded", (
            "Acknowledgement linked to filing "
            + _value(p, "filing_id", "recorded")
            + "."
        )
    if t is CaseEventType.HEARING_RECORDED:
        return "Hearing recorded", "A hearing event was recorded."
    if t is CaseEventType.ORDER_RECORDED:
        return "Order recorded", "An order event was recorded."

    raise ValueError("unsupported case event type")


def build_case_timeline(
    events: Iterable[CaseEvent],
) -> List[CaseTimelineItem]:
    event_list = list(events)
    if any(not isinstance(event, CaseEvent) for event in event_list):
        raise TypeError("events must contain only CaseEvent values")

    items = []
    for event in event_list:
        title, summary = _render(event)
        items.append(
            CaseTimelineItem(
                event_id=event.event_id,
                event_type=event.event_type,
                category=_CATEGORY[event.event_type],
                occurred_at=event.occurred_at,
                actor_id=event.actor_id,
                title=title,
                summary=summary,
            )
        )
    return sorted(
        items,
        key=lambda item: (item.occurred_at, item.event_id),
    )
