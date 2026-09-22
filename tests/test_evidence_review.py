"""Tests for deterministic evidence human-review transitions."""

import copy
import unittest

from domain.evidence_review import (
    create_evidence_review,
    reviewed_candidate_ids,
)
from domain.models import (
    EvidenceCandidate,
    EvidenceReviewRecord,
    EvidenceReviewStatus,
    SourceTextOrigin,
    SourceVerificationStatus,
)


def candidate(
    candidate_id="EC-001",
    evidence_id="sec73_itc.e1",
    document_id="D-001",
):
    return EvidenceCandidate(
        candidate_id=candidate_id,
        evidence_id=evidence_id,
        document_id=document_id,
        source_text="GSTR-2B April 2026 Total ITC 125000",
        source_page=2,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )


class EvidenceReviewTests(unittest.TestCase):
    def test_confirm_creates_record_without_mutating_candidate(self):
        item = candidate()
        before = copy.deepcopy(item)
        review = create_evidence_review(
            item,
            EvidenceReviewStatus.CONFIRMED,
            [],
            "Checked against uploaded return",
        )
        self.assertEqual(item, before)
        self.assertEqual(review.review_id, "ER-001")
        self.assertEqual(review.candidate_id, "EC-001")
        self.assertIs(review.decision, EvidenceReviewStatus.CONFIRMED)
        self.assertEqual(
            review.reviewer_note,
            "Checked against uploaded return",
        )

    def test_reject_creates_terminal_record(self):
        review = create_evidence_review(
            candidate(),
            EvidenceReviewStatus.REJECTED,
            [],
        )
        self.assertIs(review.decision, EvidenceReviewStatus.REJECTED)
        self.assertIsNone(review.reviewer_note)

    def test_pending_review_cannot_be_human_decision(self):
        with self.assertRaisesRegex(ValueError, "CONFIRMED or REJECTED"):
            create_evidence_review(
                candidate(),
                EvidenceReviewStatus.PENDING_REVIEW,
                [],
            )

    def test_second_review_same_candidate_is_rejected(self):
        first = create_evidence_review(
            candidate(),
            EvidenceReviewStatus.CONFIRMED,
            [],
        )
        with self.assertRaisesRegex(ValueError, "already been reviewed"):
            create_evidence_review(
                candidate(),
                EvidenceReviewStatus.REJECTED,
                [first],
            )

    def test_review_id_is_append_order_based(self):
        first = create_evidence_review(
            candidate("EC-001"),
            EvidenceReviewStatus.CONFIRMED,
            [],
        )
        second = create_evidence_review(
            candidate("EC-002"),
            EvidenceReviewStatus.REJECTED,
            [first],
        )
        self.assertEqual(first.review_id, "ER-001")
        self.assertEqual(second.review_id, "ER-002")

    def test_source_snapshot_is_copied_into_record(self):
        item = candidate()
        review = create_evidence_review(
            item,
            EvidenceReviewStatus.CONFIRMED,
            [],
        )
        self.assertEqual(review.evidence_id, item.evidence_id)
        self.assertEqual(review.document_id, item.document_id)
        self.assertEqual(review.source_text, item.source_text)
        self.assertEqual(review.source_page, item.source_page)
        self.assertIs(review.source_origin, item.source_origin)
        self.assertIs(review.source_verification, item.source_verification)

    def test_note_is_trimmed(self):
        review = create_evidence_review(
            candidate(),
            EvidenceReviewStatus.CONFIRMED,
            [],
            "  verified manually  ",
        )
        self.assertEqual(review.reviewer_note, "verified manually")

    def test_blank_note_normalizes_to_none(self):
        review = create_evidence_review(
            candidate(),
            EvidenceReviewStatus.CONFIRMED,
            [],
            "   ",
        )
        self.assertIsNone(review.reviewer_note)

    def test_non_string_note_is_rejected(self):
        with self.assertRaises(TypeError):
            create_evidence_review(
                candidate(),
                EvidenceReviewStatus.CONFIRMED,
                [],
                123,
            )

    def test_non_candidate_is_rejected(self):
        with self.assertRaises(TypeError):
            create_evidence_review(
                object(),
                EvidenceReviewStatus.CONFIRMED,
                [],
            )

    def test_reviewed_candidate_ids_preserve_order_and_dedup(self):
        records = [
            EvidenceReviewRecord(
                review_id="ER-001",
                candidate_id="EC-002",
                evidence_id="e1",
                document_id="D-1",
                source_text="a",
                source_page=1,
                source_origin=SourceTextOrigin.EMBEDDED,
                source_verification=SourceVerificationStatus.VERIFIED,
                decision=EvidenceReviewStatus.CONFIRMED,
            ),
            EvidenceReviewRecord(
                review_id="ER-002",
                candidate_id="EC-001",
                evidence_id="e2",
                document_id="D-2",
                source_text="b",
                source_page=1,
                source_origin=SourceTextOrigin.EMBEDDED,
                source_verification=SourceVerificationStatus.VERIFIED,
                decision=EvidenceReviewStatus.REJECTED,
            ),
            EvidenceReviewRecord(
                review_id="ER-003",
                candidate_id="EC-002",
                evidence_id="e1",
                document_id="D-1",
                source_text="a",
                source_page=1,
                source_origin=SourceTextOrigin.EMBEDDED,
                source_verification=SourceVerificationStatus.VERIFIED,
                decision=EvidenceReviewStatus.CONFIRMED,
            ),
        ]
        self.assertEqual(
            reviewed_candidate_ids(records),
            ["EC-002", "EC-001"],
        )


if __name__ == "__main__":
    unittest.main()
