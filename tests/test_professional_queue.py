"""Tests for Phase 3O.5 attention-enriched case queue."""

import unittest
from datetime import date, datetime, timezone

from domain.case_models import CaseStatus
from domain.case_operations_models import CaseWorkItem, WorkQueueDeadlineStatus
from domain.professional_workbench_models import (
    CaseAttentionCode,
    CaseAttentionItem,
    ProfessionalCaseAttention,
)
from modules.professional_queue import build_professional_case_queue


NOW = datetime(2026, 9, 23, 6, 30, tzinfo=timezone.utc)


def work(case_id, deadline_status):
    return CaseWorkItem(
        case_id=case_id,
        client_id="C-1",
        client_name="Client",
        title=case_id,
        status=CaseStatus.ANALYZED,
        response_deadline=date(2026, 9, 30),
        days_remaining=7,
        deadline_status=deadline_status,
        assigned_to=None,
        reviewer_id=None,
    )


def attention(case_id, *codes):
    return ProfessionalCaseAttention(
        case_id=case_id,
        case_status=CaseStatus.ANALYZED,
        latest_snapshot_id=None,
        latest_legal_brief_id=None,
        latest_draft_version_id=None,
        latest_filing_id=None,
        items=tuple(
            CaseAttentionItem(code, code.value)
            for code in codes
        ),
    )


class ProfessionalQueueTests(unittest.TestCase):
    def test_enrichment_preserves_input_queue_order_exactly(self):
        queue = [
            work("OVERDUE", WorkQueueDeadlineStatus.OVERDUE),
            work("TODAY", WorkQueueDeadlineStatus.DUE_TODAY),
            work("NO-DATE", WorkQueueDeadlineStatus.NO_DEADLINE),
        ]
        attentions = [
            attention("NO-DATE", CaseAttentionCode.DRAFT_NOT_STARTED),
            attention(
                "OVERDUE",
                CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,
                CaseAttentionCode.DRAFT_AWAITING_REVIEW,
            ),
            attention("TODAY"),
        ]
        result = build_professional_case_queue(queue, attentions)
        self.assertEqual(
            [item.work_item.case_id for item in result],
            ["OVERDUE", "TODAY", "NO-DATE"],
        )

    def test_attention_codes_and_workspaces_preserve_attention_order(self):
        queue = [work("CASE-1", WorkQueueDeadlineStatus.UPCOMING)]
        result = build_professional_case_queue(
            queue,
            [
                attention(
                    "CASE-1",
                    CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,
                    CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE,
                    CaseAttentionCode.DRAFT_AWAITING_REVIEW,
                    CaseAttentionCode.DRAFT_AWAITING_APPROVAL,
                )
            ],
        )[0]
        self.assertEqual(
            result.attention_codes,
            (
                CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,
                CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE,
                CaseAttentionCode.DRAFT_AWAITING_REVIEW,
                CaseAttentionCode.DRAFT_AWAITING_APPROVAL,
            ),
        )
        self.assertEqual(
            tuple(item.value for item in result.attention_workspaces),
            ("legal_research", "evidence", "draft"),
        )
        self.assertEqual(result.attention_count, 4)

    def test_missing_attention_projection_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            build_professional_case_queue(
                [
                    work("CASE-1", WorkQueueDeadlineStatus.UPCOMING),
                    work("CASE-2", WorkQueueDeadlineStatus.UPCOMING),
                ],
                [attention("CASE-1")],
            )

    def test_duplicate_attention_projection_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_professional_case_queue(
                [work("CASE-1", WorkQueueDeadlineStatus.UPCOMING)],
                [attention("CASE-1"), attention("CASE-1")],
            )

    def test_attention_cannot_inject_case_not_in_work_queue(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            build_professional_case_queue(
                [work("CASE-1", WorkQueueDeadlineStatus.UPCOMING)],
                [attention("CASE-1"), attention("CASE-X")],
            )


if __name__ == "__main__":
    unittest.main()
