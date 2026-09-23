"""Deterministic professional case-attention projection."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.case_models import CaseRecord, CaseStatus
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
)
from domain.filing_models import FilingRecord
from domain.legal_brief_models import LoadedLegalBrief
from domain.professional_workbench_models import (
    CaseAttentionCode,
    CaseAttentionItem,
    ProfessionalCaseAttention,
)


def _latest(values: Sequence, attr: str):
    if not values:
        return None
    return max(values, key=lambda item: (getattr(item, attr), repr(item)))


def build_professional_case_attention(
    case: CaseRecord,
    *,
    snapshots: Iterable[AnalysisSnapshotRef],
    legal_briefs: Iterable[LoadedLegalBrief],
    draft_versions: Iterable[DraftVersionRef],
    filings: Iterable[FilingRecord],
) -> ProfessionalCaseAttention:
    """Build read-only operational attention facts.

    This projection does not change case state, decide legal merits, or gate
    drafting. Multiple attention items may coexist.
    """
    if not isinstance(case, CaseRecord):
        raise TypeError("case must be a CaseRecord")

    snapshots = tuple(snapshots)
    briefs = tuple(legal_briefs)
    drafts = tuple(draft_versions)
    filings = tuple(filings)

    for values, expected, label in (
        (snapshots, AnalysisSnapshotRef, "snapshots"),
        (briefs, LoadedLegalBrief, "legal_briefs"),
        (drafts, DraftVersionRef, "draft_versions"),
        (filings, FilingRecord, "filings"),
    ):
        if any(not isinstance(item, expected) for item in values):
            raise TypeError(f"{label} contains an invalid value")

    for item in snapshots:
        if item.case_id != case.case_id:
            raise ValueError("snapshot belongs to another case")
    for item in briefs:
        if item.metadata.case_id != case.case_id:
            raise ValueError("legal brief belongs to another case")
    for item in drafts:
        if item.case_id != case.case_id:
            raise ValueError("draft version belongs to another case")
    for item in filings:
        if item.case_id != case.case_id:
            raise ValueError("filing belongs to another case")

    latest_snapshot = _latest(snapshots, "created_at")
    latest_draft = _latest(drafts, "created_at")
    latest_filing = _latest(filings, "recorded_at")

    latest_brief: Optional[LoadedLegalBrief] = None
    if latest_snapshot is not None:
        snapshot_briefs = tuple(
            item
            for item in briefs
            if item.metadata.snapshot_id == latest_snapshot.snapshot_id
        )
        latest_brief = _latest(
            snapshot_briefs,
            "metadata",
        ) if False else None
        if snapshot_briefs:
            latest_brief = max(
                snapshot_briefs,
                key=lambda item: (
                    item.metadata.created_at,
                    item.metadata.legal_brief_id,
                ),
            )

    items = []
    if case.status is not CaseStatus.CLOSED:
        if latest_snapshot is None:
            items.append(
                CaseAttentionItem(
                    CaseAttentionCode.ANALYSIS_NOT_SAVED,
                    "No durable analysis snapshot has been saved.",
                )
            )
        else:
            if latest_brief is None:
                items.append(
                    CaseAttentionItem(
                        CaseAttentionCode.LEGAL_BRIEF_NOT_SAVED,
                        "No verified legal brief is preserved for the "
                        "latest analysis snapshot.",
                        latest_snapshot.snapshot_id,
                    )
                )
            elif latest_brief.payload.get("unresolved_topics"):
                items.append(
                    CaseAttentionItem(
                        CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,
                        "The latest legal brief still contains unresolved "
                        "legal research topics.",
                        latest_brief.metadata.legal_brief_id,
                    )
                )

        if latest_draft is None:
            items.append(
                CaseAttentionItem(
                    CaseAttentionCode.DRAFT_NOT_STARTED,
                    "No durable professional draft version exists.",
                )
            )
        elif latest_draft.review_status is DraftReviewStatus.WORKING:
            items.append(
                CaseAttentionItem(
                    CaseAttentionCode.DRAFT_AWAITING_REVIEW,
                    "The latest draft version is still awaiting review.",
                    latest_draft.draft_version_id,
                )
            )
        elif latest_draft.review_status is DraftReviewStatus.REVIEWED:
            items.append(
                CaseAttentionItem(
                    CaseAttentionCode.DRAFT_AWAITING_APPROVAL,
                    "The latest reviewed draft has not been approved.",
                    latest_draft.draft_version_id,
                )
            )
        elif latest_draft.review_status is DraftReviewStatus.APPROVED:
            filing_for_draft = tuple(
                item
                for item in filings
                if item.approved_draft_version_id
                == latest_draft.draft_version_id
            )
            if not filing_for_draft:
                items.append(
                    CaseAttentionItem(
                        CaseAttentionCode.APPROVED_DRAFT_NOT_FILED,
                        "The latest approved draft has no recorded filing.",
                        latest_draft.draft_version_id,
                    )
                )

        if latest_filing is not None and (
            latest_filing.acknowledgement_document_id is None
        ):
            items.append(
                CaseAttentionItem(
                    CaseAttentionCode.FILING_ACKNOWLEDGEMENT_MISSING,
                    "The latest recorded filing has no acknowledgement "
                    "document yet.",
                    latest_filing.filing_id,
                )
            )

    return ProfessionalCaseAttention(
        case_id=case.case_id,
        case_status=case.status,
        latest_snapshot_id=(
            None if latest_snapshot is None else latest_snapshot.snapshot_id
        ),
        latest_legal_brief_id=(
            None
            if latest_brief is None
            else latest_brief.metadata.legal_brief_id
        ),
        latest_draft_version_id=(
            None
            if latest_draft is None
            else latest_draft.draft_version_id
        ),
        latest_filing_id=(
            None if latest_filing is None else latest_filing.filing_id
        ),
        items=tuple(items),
    )
