"""Tests for authorized professional case cockpit."""

import unittest
from datetime import date, datetime, timezone
from unittest import mock

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.case_models import CaseRecord, CaseStatus
from domain.case_operations_models import (
    CaseWorkItem,
    WorkQueueDeadlineStatus,
)
from domain.legal_evidence_models import (
    LegalEvidenceReadiness,
    LegalEvidenceReadinessStatus,
)
from domain.models import (
    EvidenceReviewStatus,
    NoticeForm,
    ProceedingType,
)
from domain.professional_workbench_models import CaseAttentionCode
from modules.authorized_professional_workbench_service import (
    AuthorizedProfessionalWorkbenchService,
)


NOW = datetime(2026, 9, 23, 5, 30, tzinfo=timezone.utc)


def case():
    return CaseRecord(
        case_id="CASE-1",
        firm_id="F-1",
        client_id="C-1",
        registration_id=None,
        title="Matter",
        status=CaseStatus.ANALYZED,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


def snapshot():
    return AnalysisSnapshotRef(
        snapshot_id="SNAP-1",
        case_id="CASE-1",
        source_document_id="DOC-1",
        source_document_sha256="a" * 64,
        schema_version=1,
        engine_version="phase2-contract-2026.09.22.1",
        byte_size=10,
        sha256_hex="b" * 64,
        storage_key="objects/snap",
        created_at=NOW,
        created_by="OIDC-" + "c" * 64,
    )


class AuthorizedProfessionalWorkbenchTests(unittest.TestCase):
    def build(self):
        cases = mock.Mock()
        snapshots = mock.Mock()
        legal = mock.Mock()
        drafts = mock.Mock()
        filings = mock.Mock()
        cases.get_case.return_value = case()
        snapshots.list_snapshot_history.return_value = [snapshot()]
        snapshots.load_snapshot.return_value = mock.Mock(
            payload={
                "classification": {
                    "support_level": "deep_workflow",
                }
            }
        )
        legal.list_for_snapshot.return_value = []
        drafts.list_versions.return_value = []
        filings.list_filings.return_value = []
        service = AuthorizedProfessionalWorkbenchService(
            cases, snapshots, legal, drafts, filings
        )
        return service, cases, snapshots, legal, drafts, filings

    def test_attention_queue_preserves_authorized_work_queue_order(self):
        service, cases, *_ = self.build()
        cases.list_case_work_queue.return_value = [
            CaseWorkItem(
                case_id="CASE-1",
                client_id="C-1",
                client_name="Client",
                title="Matter",
                status=CaseStatus.ANALYZED,
                response_deadline=date(2026, 9, 24),
                days_remaining=1,
                deadline_status=WorkQueueDeadlineStatus.DUE_SOON,
                assigned_to=None,
                reviewer_id=None,
            )
        ]
        result = service.list_case_attention_queue(
            mock.sentinel.principal,
            "F-1",
            today=date(2026, 9, 23),
        )
        self.assertEqual([item.work_item.case_id for item in result], ["CASE-1"])
        self.assertEqual(result[0].attention_count, 2)
        cases.list_case_work_queue.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            today=date(2026, 9, 23),
        )

    def test_reads_all_artifacts_through_authorized_services(self):
        service, cases, snapshots, legal, drafts, filings = self.build()
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(result.case_id, "CASE-1")
        cases.get_case.assert_called_once_with(
            mock.sentinel.principal, "F-1", "CASE-1"
        )
        snapshots.list_snapshot_history.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        snapshots.load_snapshot.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        legal.list_for_snapshot.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        drafts.list_versions.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        filings.list_filings.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )

    def test_triage_snapshot_skips_unavailable_specialist_attention(self):
        service, cases, snapshots, legal, drafts, filings = self.build()
        snapshots.load_snapshot.return_value = mock.Mock(
            payload={
                "classification": {
                    "support_level": "triage_only",
                }
            }
        )

        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )

        self.assertEqual(result.items, ())
        legal.list_for_snapshot.assert_not_called()
        legal.load.assert_not_called()
        drafts.list_versions.assert_called_once()
        filings.list_filings.assert_called_once()

    def test_triage_pending_evidence_requires_confirmed_review(self):
        cases = mock.Mock()
        snapshots = mock.Mock()
        legal = mock.Mock()
        drafts = mock.Mock()
        filings = mock.Mock()
        evidence = mock.Mock()
        cases.get_case.return_value = case()
        snapshots.list_snapshot_history.return_value = [snapshot()]
        snapshots.load_snapshot.return_value = mock.Mock(
            payload={
                "classification": {
                    "support_level": "triage_only",
                }
            }
        )
        drafts.list_versions.return_value = []
        filings.list_filings.return_value = []

        first = mock.Mock(evidence_id="triage.requested_document.F-1")
        second = mock.Mock(evidence_id="triage.referenced_annexure.F-2")
        evidence.snapshot_evidence_checklist.return_value = [first, second]
        evidence.list_reviews.return_value = [
            mock.Mock(
                evidence_id=first.evidence_id,
                decision=EvidenceReviewStatus.CONFIRMED,
            ),
            mock.Mock(
                evidence_id=second.evidence_id,
                decision=EvidenceReviewStatus.REJECTED,
            ),
        ]

        service = AuthorizedProfessionalWorkbenchService(
            cases, snapshots, legal, drafts, filings, evidence
        )
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(
            tuple(item.code for item in result.items),
            (CaseAttentionCode.TRIAGE_EVIDENCE_REVIEW_PENDING,),
        )
        legal.list_for_snapshot.assert_not_called()
        evidence.legal_evidence_readiness.assert_not_called()

        evidence.list_reviews.return_value = [
            mock.Mock(
                evidence_id=first.evidence_id,
                decision=EvidenceReviewStatus.CONFIRMED,
            ),
            mock.Mock(
                evidence_id=second.evidence_id,
                decision=EvidenceReviewStatus.CONFIRMED,
            ),
        ]
        resolved = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(resolved.items, ())

    def test_missing_case_stops_before_artifact_reads(self):
        service, cases, snapshots, legal, drafts, filings = self.build()
        cases.get_case.return_value = None
        with self.assertRaises(LookupError):
            service.get_case_attention(
                mock.sentinel.principal,
                "F-1",
                case_id="CASE-X",
            )
        snapshots.list_snapshot_history.assert_not_called()
        legal.list_for_snapshot.assert_not_called()
        drafts.list_versions.assert_not_called()
        filings.list_filings.assert_not_called()

    def test_no_snapshot_does_not_query_legal_briefs(self):
        service, _, snapshots, legal, _, _ = self.build()
        snapshots.list_snapshot_history.return_value = []
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        legal.list_for_snapshot.assert_not_called()
        self.assertIsNone(result.latest_snapshot_id)

    def test_evidence_review_permission_adds_incomplete_attention(self):
        cases = mock.Mock()
        snapshots = mock.Mock()
        legal = mock.Mock()
        drafts = mock.Mock()
        filings = mock.Mock()
        evidence = mock.Mock()
        cases.get_case.return_value = case()
        snapshots.list_snapshot_history.return_value = [snapshot()]
        legal.list_for_snapshot.return_value = []
        drafts.list_versions.return_value = []
        filings.list_filings.return_value = []
        evidence.legal_evidence_readiness.return_value = [
            LegalEvidenceReadiness(
                question_id="gst_sec73_itc.eligibility",
                status=(
                    LegalEvidenceReadinessStatus
                    .PARTIAL_CONFIRMED_EVIDENCE
                ),
                required_evidence_ids=(
                    "sec73_itc.e3",
                    "sec73_itc.e4",
                    "sec73_itc.e5",
                ),
                confirmed_evidence_ids=("sec73_itc.e3",),
                missing_evidence_ids=(
                    "sec73_itc.e4",
                    "sec73_itc.e5",
                ),
                confirmed_review_ids=("ER-1",),
            )
        ]
        service = AuthorizedProfessionalWorkbenchService(
            cases, snapshots, legal, drafts, filings, evidence
        )
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertIn(
            CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE,
            tuple(item.code for item in result.items),
        )
        evidence.legal_evidence_readiness.assert_called_once_with(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )

    def test_missing_evidence_review_permission_does_not_break_cockpit(self):
        cases = mock.Mock()
        snapshots = mock.Mock()
        legal = mock.Mock()
        drafts = mock.Mock()
        filings = mock.Mock()
        evidence = mock.Mock()
        cases.get_case.return_value = case()
        snapshots.list_snapshot_history.return_value = [snapshot()]
        legal.list_for_snapshot.return_value = []
        drafts.list_versions.return_value = []
        filings.list_filings.return_value = []
        evidence.legal_evidence_readiness.side_effect = PermissionError(
            "access denied"
        )
        service = AuthorizedProfessionalWorkbenchService(
            cases, snapshots, legal, drafts, filings, evidence
        )
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertNotIn(
            CaseAttentionCode.LEGAL_EVIDENCE_INCOMPLETE,
            tuple(item.code for item in result.items),
        )
        self.assertIn(
            CaseAttentionCode.LEGAL_BRIEF_NOT_SAVED,
            tuple(item.code for item in result.items),
        )

    def test_evidence_contract_drift_is_attention_when_authorized(self):
        cases = mock.Mock()
        snapshots = mock.Mock()
        legal = mock.Mock()
        drafts = mock.Mock()
        filings = mock.Mock()
        evidence = mock.Mock()
        cases.get_case.return_value = case()
        snapshots.list_snapshot_history.return_value = [snapshot()]
        legal.list_for_snapshot.return_value = []
        drafts.list_versions.return_value = []
        filings.list_filings.return_value = []
        evidence.legal_evidence_readiness.side_effect = ValueError(
            "requirements are not present"
        )
        service = AuthorizedProfessionalWorkbenchService(
            cases, snapshots, legal, drafts, filings, evidence
        )
        result = service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertIn(
            CaseAttentionCode.LEGAL_EVIDENCE_CONTRACT_DRIFT,
            tuple(item.code for item in result.items),
        )

    def test_only_latest_snapshot_legal_history_is_loaded(self):
        service, _, snapshots, legal, _, _ = self.build()
        older = snapshot()
        newer = AnalysisSnapshotRef(
            **{
                **snapshot().__dict__,
                "snapshot_id": "SNAP-2",
                "created_at": NOW.replace(minute=31),
            }
        )
        snapshots.list_snapshot_history.return_value = [newer, older]
        legal.list_for_snapshot.return_value = []
        service.get_case_attention(
            mock.sentinel.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(
            legal.list_for_snapshot.call_args.kwargs["snapshot_id"],
            "SNAP-2",
        )


if __name__ == "__main__":
    unittest.main()
