"""Tests for authorized snapshot-bound evidence review decisions."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from domain.analysis_snapshot_models import (
    AnalysisSnapshotRef,
    LoadedAnalysisSnapshot,
)
from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    StoredDocumentRef,
)
from domain.evidence_review_models import EvidenceReviewRef
from domain.models import (
    EvidenceCandidate,
    EvidenceReviewStatus,
    NoticeForm,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from modules.authorized_evidence_review_service import (
    AuthorizedEvidenceReviewService,
)


NOW = datetime(2026, 9, 22, 19, 30, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def case():
    return CaseRecord(
        case_id="CASE-1",
        firm_id="F-1",
        client_id="CLIENT-1",
        registration_id=None,
        title="Matter",
        status=CaseStatus.ANALYZED,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


def document(kind=CaseDocumentKind.SUPPORTING_EVIDENCE):
    return StoredDocumentRef(
        document_id="DOC-EVIDENCE",
        case_id="CASE-1",
        kind=kind,
        original_filename="gstr2b.pdf",
        media_type="application/pdf",
        byte_size=123,
        sha256_hex="b" * 64,
        storage_key="objects/" + "b" * 32,
        created_at=NOW,
    )


def candidate(
    *,
    evidence_id="evidence.one",
    source_text="GSTR-2B April 2026 Total ITC 125000",
    page=2,
    origin=SourceTextOrigin.EMBEDDED,
    verification=SourceVerificationStatus.VERIFIED,
):
    return EvidenceCandidate(
        candidate_id="EC-001",
        evidence_id=evidence_id,
        document_id="DOC-EVIDENCE",
        source_text=source_text,
        source_page=page,
        source_origin=origin,
        source_verification=verification,
    )


def snapshot(evidence_id="evidence.one"):
    metadata = AnalysisSnapshotRef(
        snapshot_id="SNAP-1",
        case_id="CASE-1",
        source_document_id="DOC-NOTICE",
        source_document_sha256="a" * 64,
        schema_version=1,
        engine_version="phase2-contract-2026.09.22.1",
        byte_size=10,
        sha256_hex="c" * 64,
        storage_key="objects/" + "c" * 32,
        created_at=NOW,
        created_by=PRINCIPAL.user_id,
    )
    return LoadedAnalysisSnapshot(
        metadata=metadata,
        payload={
            "draft": {
                "evidence_checklist": [
                    {
                        "evidence_id": evidence_id,
                        "requirement_text": "GSTR-2B",
                        "status": "unknown",
                    }
                ]
            }
        },
    )


class AuthorizedEvidenceReviewTests(unittest.TestCase):
    def build(self, permissions=None):
        case_service = mock.Mock()
        case_service.get_case.return_value = case()
        case_service.read_document.return_value = (
            document(),
            b"%PDF evidence",
        )
        snapshot_service = mock.Mock()
        snapshot_service.load_snapshot.return_value = snapshot()
        access = mock.Mock()
        access.get_grant.return_value = FirmAccessGrant(
            user_id=PRINCIPAL.user_id,
            firm_id="F-1",
            permissions=frozenset(
                {AccessPermission.EVIDENCE_REVIEW}
                if permissions is None
                else permissions
            ),
            active=True,
        )
        reviews = mock.Mock()
        store = mock.Mock()
        service = AuthorizedEvidenceReviewService(
            case_service,
            snapshot_service,
            access,
            reviews,
            store,
        )
        return service, case_service, snapshot_service, access, reviews, store

    def test_snapshot_evidence_checklist_uses_selected_snapshot_contract(self):
        service, _, snapshot_service, *_ = self.build()
        snapshot_service.load_snapshot.return_value = snapshot("evidence.one")
        checklist = service.snapshot_evidence_checklist(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(len(checklist), 1)
        self.assertEqual(checklist[0].evidence_id, "evidence.one")
        self.assertEqual(checklist[0].requirement_text, "GSTR-2B")
        self.assertEqual(checklist[0].status.value, "unknown")

    def test_snapshot_evidence_checklist_fails_closed_on_duplicate_ids(self):
        service, _, snapshot_service, *_ = self.build()
        loaded = snapshot()
        loaded.payload["draft"]["evidence_checklist"].append(
            dict(loaded.payload["draft"]["evidence_checklist"][0])
        )
        snapshot_service.load_snapshot.return_value = loaded
        with self.assertRaisesRegex(ValueError, "item is invalid"):
            service.snapshot_evidence_checklist(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
            )

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    @mock.patch(
        "modules.authorized_evidence_review_service.extract_document_pages"
    )
    def test_valid_review_reverifies_persisted_quote_and_uses_principal_actor(
        self,
        parse,
        persist,
    ):
        from domain.models import DocumentPageText

        parse.return_value = [
            DocumentPageText(
                page_number=2,
                text="Header\nGSTR-2B April 2026 Total ITC 125000\nFooter",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        expected = mock.Mock()
        persist.return_value = expected
        service, case_service, snapshot_service, *_ = self.build()

        result = service.save_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            candidate=candidate(),
            decision=EvidenceReviewStatus.CONFIRMED,
            reviewer_note="Checked",
            reviewed_at=NOW,
        )

        self.assertIs(result, expected)
        case_service.get_case.assert_called_once_with(
            PRINCIPAL, "F-1", "CASE-1"
        )
        snapshot_service.load_snapshot.assert_called_once_with(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        case_service.read_document.assert_called_once_with(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            document_id="DOC-EVIDENCE",
        )
        persist.assert_called_once()
        kwargs = persist.call_args.kwargs
        self.assertEqual(kwargs["case_id"], "CASE-1")
        self.assertEqual(kwargs["snapshot_id"], "SNAP-1")
        self.assertEqual(kwargs["actor_id"], PRINCIPAL.user_id)
        self.assertEqual(kwargs["reviewer_note"], "Checked")

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    def test_missing_evidence_review_permission_blocks_before_case_lookup(
        self,
        persist,
    ):
        service, case_service, *_ = self.build(
            permissions={AccessPermission.CASE_READ}
        )
        with self.assertRaises(PermissionError):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        case_service.get_case.assert_not_called()
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    def test_candidate_requirement_must_exist_in_selected_snapshot(
        self,
        persist,
    ):
        service, _, snapshot_service, *_ = self.build()
        snapshot_service.load_snapshot.return_value = snapshot("other.evidence")
        with self.assertRaisesRegex(ValueError, "not present"):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    def test_candidate_document_must_be_supporting_evidence(self, persist):
        service, case_service, *_ = self.build()
        case_service.read_document.return_value = (
            document(CaseDocumentKind.NOTICE),
            b"%PDF notice",
        )
        with self.assertRaisesRegex(ValueError, "not persisted supporting"):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    @mock.patch(
        "modules.authorized_evidence_review_service.extract_document_pages"
    )
    def test_fabricated_or_wrong_page_quote_is_rejected(self, parse, persist):
        from domain.models import DocumentPageText

        parse.return_value = [
            DocumentPageText(
                page_number=1,
                text="Different page",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        service, *_ = self.build()
        with self.assertRaisesRegex(ValueError, "not grounded"):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        persist.assert_not_called()

    @mock.patch(
        "modules.authorized_evidence_review_service.persist_evidence_review"
    )
    @mock.patch(
        "modules.authorized_evidence_review_service.extract_document_pages"
    )
    def test_source_origin_and_verification_must_match_reparsed_page(
        self,
        parse,
        persist,
    ):
        from domain.models import DocumentPageText

        parse.return_value = [
            DocumentPageText(
                page_number=2,
                text="GSTR-2B April 2026 Total ITC 125000",
                origin=SourceTextOrigin.OCR,
                verification=(
                    SourceVerificationStatus.REQUIRES_VERIFICATION
                ),
            )
        ]
        service, *_ = self.build()
        with self.assertRaisesRegex(ValueError, "source origin"):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                candidate=candidate(),
                decision=EvidenceReviewStatus.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        persist.assert_not_called()

    def test_list_reviews_is_scoped_through_case_and_snapshot(self):
        service, case_service, snapshot_service, _, reviews, _ = self.build()
        expected = [mock.Mock()]
        reviews.list_review_refs.return_value = expected
        result = service.list_reviews(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(result, expected)
        case_service.get_case.assert_called_once()
        snapshot_service.load_snapshot.assert_called_once()
        reviews.list_review_refs.assert_called_once_with("SNAP-1")

    @mock.patch(
        "modules.authorized_evidence_review_service.load_evidence_review"
    )
    def test_load_review_rejects_review_from_another_snapshot(self, load):
        service, _, _, _, reviews, _ = self.build()
        reviews.get_review_ref.return_value = EvidenceReviewRef(
            review_id="EREV-1",
            case_id="CASE-1",
            snapshot_id="SNAP-OTHER",
            evidence_id="evidence.one",
            document_id="DOC-EVIDENCE",
            source_page=2,
            source_text_sha256="d" * 64,
            candidate_fingerprint="e" * 64,
            decision=EvidenceReviewStatus.CONFIRMED,
            byte_size=10,
            sha256_hex="f" * 64,
            storage_key="objects/" + "f" * 32,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        with self.assertRaises(LookupError):
            service.load_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                review_id="EREV-1",
            )
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
