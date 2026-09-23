"""Deterministic adapters for the triage-only professional workspace.

These helpers do not promote workflow support or decide evidentiary sufficiency.
They translate source-grounded triage facts into temporary workspace inputs so
recognized triage notices can still be worked by a professional.
"""

from typing import List

from domain.models import (
    EvidenceChecklistItem,
    EvidenceStatus,
    FactStatus,
    FactType,
    Phase2AnalysisResult,
    SupportLevel,
)


def build_triage_requested_document_checklist(
    result: Phase2AnalysisResult,
) -> List[EvidenceChecklistItem]:
    """Build review-only evidence targets from department-requested records.

    Only fact IDs already selected by deterministic preflight/triage are
    eligible. The exact notice source wording becomes the requirement text;
    model-authored claim text is never used. These checklist items remain
    UNKNOWN and therefore do not establish that evidence exists, is sufficient,
    or satisfies the department's request.
    """
    if (
        result.classification.support_level is not SupportLevel.TRIAGE_ONLY
        or result.triage_summary is None
    ):
        return []

    requested_ids = set(result.triage_summary.requested_document_fact_ids)
    if not requested_ids:
        return []

    items: List[EvidenceChecklistItem] = []
    seen = set()
    for fact in result.extraction_result.facts:
        if fact.fact_id not in requested_ids or fact.fact_id in seen:
            continue
        if fact.fact_type is not FactType.REQUESTED_DOCUMENT:
            continue
        if fact.status is not FactStatus.CONFIRMED:
            continue
        if not isinstance(fact.source_text, str) or not fact.source_text.strip():
            continue

        seen.add(fact.fact_id)
        items.append(
            EvidenceChecklistItem(
                evidence_id=f"triage.requested_document.{fact.fact_id}",
                requirement_text=(
                    "Department-requested record: " + fact.source_text
                ),
                status=EvidenceStatus.UNKNOWN,
            )
        )
    return items
