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


def _triage_scope(result: Phase2AnalysisResult):
    if (
        result.classification.support_level is not SupportLevel.TRIAGE_ONLY
        or result.triage_summary is None
    ):
        return None

    return {
        "requested_document": set(
            result.triage_summary.requested_document_fact_ids
        ),
        "referenced_annexure": set(
            result.triage_summary.referenced_annexure_fact_ids
        ),
    }


def build_triage_evidence_checklist(
    result: Phase2AnalysisResult,
) -> List[EvidenceChecklistItem]:
    """Build review-only evidence targets from notice-grounded triage facts.

    The adapter accepts only fact IDs already selected by deterministic
    preflight/triage. The exact notice source wording becomes the requirement
    text; model-authored claim text is never used.

    Targets cover records explicitly requested from the taxpayer and
    annexures/documents that the notice says it references.

    Every target remains UNKNOWN. Creating a target does not establish that
    the document exists, was supplied, is complete, is responsive, or
    satisfies any departmental request.
    """
    scope = _triage_scope(result)
    if scope is None:
        return []

    specs = {
        FactType.REQUESTED_DOCUMENT: (
            scope["requested_document"],
            "triage.requested_document",
            "Department-requested record: ",
        ),
        FactType.REFERENCED_ANNEXURE: (
            scope["referenced_annexure"],
            "triage.referenced_annexure",
            "Notice-referenced annexure: ",
        ),
    }

    items: List[EvidenceChecklistItem] = []
    seen = set()
    for fact in result.extraction_result.facts:
        spec = specs.get(fact.fact_type)
        if spec is None:
            continue

        allowed_ids, evidence_prefix, text_prefix = spec
        if fact.fact_id not in allowed_ids or fact.fact_id in seen:
            continue
        if fact.status is not FactStatus.CONFIRMED:
            continue
        if not isinstance(fact.source_text, str) or not fact.source_text.strip():
            continue

        seen.add(fact.fact_id)
        items.append(
            EvidenceChecklistItem(
                evidence_id=f"{evidence_prefix}.{fact.fact_id}",
                requirement_text=text_prefix + fact.source_text,
                status=EvidenceStatus.UNKNOWN,
            )
        )
    return items


def build_triage_requested_document_checklist(
    result: Phase2AnalysisResult,
) -> List[EvidenceChecklistItem]:
    """Backward-compatible requested-record-only triage checklist."""
    return [
        item
        for item in build_triage_evidence_checklist(result)
        if item.evidence_id.startswith("triage.requested_document.")
    ]
