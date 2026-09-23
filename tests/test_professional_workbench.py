"""Tests for Phase 3O.1 professional case attention."""

import unittest
from datetime import date, datetime, timezone

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.case_models import CaseRecord, CaseStatus
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
)
from domain.filing_models import FilingRecord
from domain.legal_brief_models import LegalBriefRef, LoadedLegalBrief
from domain.legal_evidence_models import (
    LegalEvidenceReadiness,
    LegalEvidenceReadinessStatus,
)
from domain.models import NoticeForm, ProceedingType
from domain.professional_workbench_models import CaseAttentionCode
from modules.professional_workbench import build_professional_case_attention


NOW = datetime(2026, 9, 23, 5, 0, tzinfo=timezone.utc)


def case(status=CaseStatus.ANALYZED):
    return CaseRecord(
        case_id="CASE-1",
        firm_id="F-1",
        client_id="C-1",
        registration_id=None,
        title="Matter",
        status=status,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


def snapshot(snapshot_id="SNAP-1", minute=0):
    return AnalysisSnapshotRef(
        snapshot_id=snapshot_id,
        case_id="CASE-1",
        source_document_id="DOC-1",
        source_document_sha256="a" * 64,
        schema_version=1,
        engine_version="phase2-contract-2026.09.22.1",
        byte_size=10,
        sha256_hex="b" * 64,
        storage_key="objects/" + snapshot_id,
        created_at=NOW.replace(minute=minute),
        created_by="OIDC-" + "c" * 64,
    )


def brief(snapshot_id="SNAP-1", unresolved=()):
    ref = LegalBriefRef(
        legal_brief_id="LEGAL-" + snapshot_id,
        case_id="CASE-1",
        snapshot_id=snapshot_id,
        schema_version=1,
        catalog_version="gst-legal.v2.2026-09-23",
        as_of_date=date(2026, 8, 1),
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        byte_size=10,
        sha256_hex="d" * 64,
        storage_key="objects/legal-" + snapshot_id,
        created_at=NOW,
        created_by="OIDC-" + "c" * 64,
    )
    return LoadedLegalBrief(
        metadata=ref,
        payload={"unresolved_topics": list(unresolved)},
    )


def draft(status=DraftReviewStatus.WORKING, version=1):
    return DraftVersionRef(
        draft_version_id=f"DRAFT-{version}",
        case_id="CASE-1",
        source_snapshot_id="SNAP-1",
        parent_draft_version_id=None,
        version_number=version,
        generated_baseline=True,
        content_sha256="e" * 64,
        byte_size=10,
        sha256_hex="f" * 64,
        storage_key=f"objects/draft-{version}",
        review_status=status,
        created_at=NOW.replace(minute=version),
        created_by="OIDC-" + "c" * 64,
    )


def filing(ack=None):
    return FilingRecord(
        filing_id="FILE-1",
        case_id="CASE-1",
        approved_draft_version_id="DRAFT-1",
        filed_response_document_id="DOC-FILED",
        acknowledgement_document_id=ack,
        filing_reference="REF-1",
        filed_at=NOW,
        filed_by="OIDC-" + "c" * 64,
        recorded_at=NOW,
    )


def codes(result):
    return tuple(item.code for item in result.items)


class ProfessionalCaseAttentionTests(unittest.TestCase):
    def test_empty_active_case_surfaces_analysis_and_draft_attention(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[],
            legal_briefs=[],
            draft_versions=[],
            filings=[],
        )
        self.assertEqual(
            codes(result),
            (
                CaseAttentionCode.ANALYSIS_NOT_SAVED,
                CaseAttentionCode.DRAFT_NOT_STARTED,
            ),
        )

    def test_latest_snapshot_without_brief_is_visible(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot("SNAP-1", 0), snapshot("SNAP-2", 1)],
            legal_briefs=[brief("SNAP-1")],
            draft_versions=[],
            filings=[],
        )
        self.assertEqual(result.latest_snapshot_id, "SNAP-2")
        self.assertIn(
            CaseAttentionCode.LEGAL_BRIEF_NOT_SAVED,
            codes(result),
        )

    def test_unresolved_legal_research_is_attention_not_gate(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief(unresolved=("itc_eligibility",))],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing("DOC-ACK")],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.LEGAL_RESEARCH_UNRESOLVED,),
        )

    def test_incomplete_legal_evidence_is_attention_not_legal_verdict(self):
        readiness = LegalEvidenceReadiness(
            question_id="gst_sec73_itc.eligibility",
            status=(
                LegalEvidenceReadinessStatus.PARTIAL_CONFIRMED_EVIDENCE
            ),
            required_evidence_ids=(
                "sec73_itc.e3",
                "sec73_itc.e4",
                "sec73_itc.e5",
            ),
            confirmed_evidence_ids=("sec73_itc.e3",),
            missing_evidence_ids=("sec73_itc.e4", "sec73_itc.e5"),
            confirmed_review_ids=("ER-1",),
        )
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing("DOC-ACK")],
            legal_evidence_readiness=[readiness],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE,),
        )
        self.assertEqual(
            result.items[0].related_id,
            "gst_sec73_itc.eligibility",
        )
        self.assertNotIn("eligible", result.items[0].message.lower())

    def test_fully_confirmed_legal_evidence_adds_no_attention(self):
        readiness = LegalEvidenceReadiness(
            question_id="gst_sec73_itc.eligibility",
            status=(
                LegalEvidenceReadinessStatus.REQUIRED_EVIDENCE_CONFIRMED
            ),
            required_evidence_ids=(
                "sec73_itc.e3",
                "sec73_itc.e4",
                "sec73_itc.e5",
            ),
            confirmed_evidence_ids=(
                "sec73_itc.e3",
                "sec73_itc.e4",
                "sec73_itc.e5",
            ),
            missing_evidence_ids=(),
            confirmed_review_ids=("ER-1", "ER-2", "ER-3"),
        )
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing("DOC-ACK")],
            legal_evidence_readiness=[readiness],
        )
        self.assertEqual(result.items, ())

    def test_legal_evidence_contract_drift_is_explicit_attention(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing("DOC-ACK")],
            legal_evidence_contract_drift=True,
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.LEGAL_EVIDENCE_CONTRACT_DRIFT,),
        )
        self.assertEqual(result.items[0].related_id, "SNAP-1")

    def test_working_draft_awaits_review(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.WORKING)],
            filings=[],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.DRAFT_AWAITING_REVIEW,),
        )

    def test_reviewed_draft_awaits_approval(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.REVIEWED)],
            filings=[],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.DRAFT_AWAITING_APPROVAL,),
        )

    def test_approved_draft_without_filing_is_visible(self):
        result = build_professional_case_attention(
            case(),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.APPROVED_DRAFT_NOT_FILED,),
        )

    def test_filing_without_acknowledgement_is_visible(self):
        result = build_professional_case_attention(
            case(CaseStatus.FILED),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing()],
        )
        self.assertEqual(
            codes(result),
            (CaseAttentionCode.FILING_ACKNOWLEDGEMENT_MISSING,),
        )

    def test_complete_filing_has_no_attention_from_this_projection(self):
        result = build_professional_case_attention(
            case(CaseStatus.FILED),
            snapshots=[snapshot()],
            legal_briefs=[brief()],
            draft_versions=[draft(DraftReviewStatus.APPROVED)],
            filings=[filing("DOC-ACK")],
        )
        self.assertEqual(result.items, ())

    def test_closed_case_is_read_only_and_has_no_operational_attention(self):
        result = build_professional_case_attention(
            case(CaseStatus.CLOSED),
            snapshots=[],
            legal_briefs=[],
            draft_versions=[],
            filings=[],
        )
        self.assertEqual(result.items, ())

    def test_cross_case_artifact_fails_closed(self):
        other = snapshot()
        object.__setattr__(other, "case_id", "CASE-OTHER")
        with self.assertRaisesRegex(ValueError, "another case"):
            build_professional_case_attention(
                case(),
                snapshots=[other],
                legal_briefs=[],
                draft_versions=[],
                filings=[],
            )


if __name__ == "__main__":
    unittest.main()
