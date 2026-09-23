"""Tests for legal-question evidence readiness."""

import unittest
from datetime import datetime, timezone

from domain.evidence_review_models import EvidenceReviewRef
from domain.legal_evidence_models import LegalEvidenceReadinessStatus
from domain.models import EvidenceReviewStatus, ProceedingType
from workflows.gst.legal_evidence import (
    GST_LEGAL_EVIDENCE_REQUIREMENTS,
    build_legal_evidence_readiness,
)


NOW = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)


def review(review_id, evidence_id, decision=EvidenceReviewStatus.CONFIRMED, snapshot_id="SNAP-1"):
    return EvidenceReviewRef(
        review_id=review_id,
        case_id="CASE-1",
        snapshot_id=snapshot_id,
        evidence_id=evidence_id,
        document_id=f"DOC-{review_id}",
        source_page=1,
        source_text_sha256="a" * 64,
        candidate_fingerprint=("b" * 63) + review_id[-1],
        decision=decision,
        byte_size=10,
        sha256_hex="c" * 64,
        storage_key="objects/" + (review_id.lower().replace("-", "") + "0" * 32)[:32],
        reviewed_at=NOW,
        reviewed_by="OIDC-" + "d" * 64,
    )


class LegalEvidenceReadinessTests(unittest.TestCase):
    def test_itc_eligibility_requires_closed_supporting_evidence_set(self):
        req = GST_LEGAL_EVIDENCE_REQUIREMENTS[
            ProceedingType.GST_SEC73_ITC
        ][0]
        self.assertEqual(req.question_id, "gst_sec73_itc.eligibility")
        self.assertEqual(
            req.required_evidence_ids,
            ("sec73_itc.e3", "sec73_itc.e4", "sec73_itc.e5"),
        )

    def test_no_reviews_means_no_confirmed_evidence(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[],
        )[0]
        self.assertIs(
            result.status,
            LegalEvidenceReadinessStatus.NO_CONFIRMED_EVIDENCE,
        )
        self.assertEqual(result.confirmed_evidence_ids, ())
        self.assertEqual(
            result.missing_evidence_ids,
            ("sec73_itc.e3", "sec73_itc.e4", "sec73_itc.e5"),
        )

    def test_partial_confirmed_evidence_is_distinct(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[
                review("ER-1", "sec73_itc.e3"),
                review("ER-2", "sec73_itc.e4"),
            ],
        )[0]
        self.assertIs(
            result.status,
            LegalEvidenceReadinessStatus.PARTIAL_CONFIRMED_EVIDENCE,
        )
        self.assertEqual(
            result.confirmed_evidence_ids,
            ("sec73_itc.e3", "sec73_itc.e4"),
        )
        self.assertEqual(result.missing_evidence_ids, ("sec73_itc.e5",))
        self.assertEqual(result.confirmed_review_ids, ("ER-1", "ER-2"))

    def test_all_required_confirmed_evidence_is_ready_not_eligibility(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[
                review("ER-1", "sec73_itc.e3"),
                review("ER-2", "sec73_itc.e4"),
                review("ER-3", "sec73_itc.e5"),
            ],
        )[0]
        self.assertIs(
            result.status,
            LegalEvidenceReadinessStatus.REQUIRED_EVIDENCE_CONFIRMED,
        )
        self.assertEqual(result.missing_evidence_ids, ())
        self.assertNotIn("eligible", result.status.value)

    def test_rejected_review_never_counts(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[
                review(
                    "ER-1",
                    "sec73_itc.e3",
                    EvidenceReviewStatus.REJECTED,
                )
            ],
        )[0]
        self.assertIs(
            result.status,
            LegalEvidenceReadinessStatus.NO_CONFIRMED_EVIDENCE,
        )
        self.assertEqual(
            result.missing_evidence_ids,
            ("sec73_itc.e3", "sec73_itc.e4", "sec73_itc.e5"),
        )

    def test_cross_snapshot_review_is_ignored(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[
                review("ER-1", "sec73_itc.e3", snapshot_id="SNAP-OTHER"),
                review("ER-2", "sec73_itc.e4"),
            ],
        )[0]
        self.assertEqual(result.confirmed_evidence_ids, ("sec73_itc.e4",))
        self.assertEqual(
            result.missing_evidence_ids,
            ("sec73_itc.e3", "sec73_itc.e5"),
        )

    def test_irrelevant_confirmed_evidence_does_not_change_readiness(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[review("ER-1", "sec73_itc.e1")],
        )[0]
        self.assertIs(
            result.status,
            LegalEvidenceReadinessStatus.NO_CONFIRMED_EVIDENCE,
        )

    def test_duplicate_confirmed_evidence_is_deduplicated_for_requirement(self):
        result = build_legal_evidence_readiness(
            ProceedingType.GST_SEC73_ITC,
            snapshot_id="SNAP-1",
            reviews=[
                review("ER-1", "sec73_itc.e3"),
                review("ER-2", "sec73_itc.e3"),
            ],
        )[0]
        self.assertEqual(result.confirmed_evidence_ids, ("sec73_itc.e3",))
        self.assertEqual(result.confirmed_review_ids, ("ER-1", "ER-2"))

    def test_other_workflows_have_no_invented_evidence_plan(self):
        self.assertEqual(
            build_legal_evidence_readiness(
                ProceedingType.GST_SEC73_RCM,
                snapshot_id="SNAP-1",
                reviews=[],
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
