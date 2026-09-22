"""Tests for tenant-safe analysis snapshot authorization."""

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
from domain.models import NoticeForm, ProceedingType
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)


NOW = datetime(2026, 9, 22, 19, 0, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def case():
    return CaseRecord(
        case_id="CASE-1",
        firm_id="F-1",
        client_id="C-1",
        registration_id=None,
        title="Matter",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


def notice():
    return StoredDocumentRef(
        document_id="DOC-1",
        case_id="CASE-1",
        kind=CaseDocumentKind.NOTICE,
        original_filename="notice.pdf",
        media_type="application/pdf",
        byte_size=10,
        sha256_hex="a" * 64,
        storage_key="objects/" + "b" * 32,
        created_at=NOW,
    )


def grant(*permissions):
    return FirmAccessGrant(
        user_id=PRINCIPAL.user_id,
        firm_id="F-1",
        permissions=frozenset(permissions),
        active=True,
    )


class AuthorizedSnapshotServiceTests(unittest.TestCase):
    def build(self, permissions):
        case_service = mock.Mock()
        case_service.get_case.return_value = case()
        case_service.list_documents.return_value = [notice()]
        access_repository = mock.Mock()
        access_repository.get_grant.return_value = grant(*permissions)
        snapshot_repository = mock.Mock()
        document_store = mock.Mock()
        service = AuthorizedAnalysisSnapshotService(
            case_service,
            access_repository,
            snapshot_repository,
            document_store,
        )
        return (
            service,
            case_service,
            access_repository,
            snapshot_repository,
            document_store,
        )

    @mock.patch(
        "modules.authorized_analysis_snapshot_service.persist_analysis_snapshot"
    )
    def test_save_requires_case_read_document_read_and_case_update(
        self,
        persist_mock,
    ):
        service, *_ = self.build(
            {
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
                AccessPermission.CASE_UPDATE,
            }
        )
        expected = mock.sentinel.snapshot
        persist_mock.return_value = expected
        analysis = mock.Mock()

        result = service.save_current_analysis(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            analysis=analysis,
            created_at=NOW,
        )

        self.assertIs(result, expected)
        self.assertEqual(
            persist_mock.call_args.kwargs["actor_id"],
            PRINCIPAL.user_id,
        )
        self.assertEqual(
            persist_mock.call_args.kwargs["source_document"],
            notice(),
        )

    @mock.patch(
        "modules.authorized_analysis_snapshot_service.persist_analysis_snapshot"
    )
    def test_save_without_case_update_never_persists(self, persist_mock):
        service, *_ = self.build(
            {
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        with self.assertRaises(PermissionError):
            service.save_current_analysis(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                analysis=mock.Mock(),
                created_at=NOW,
            )
        persist_mock.assert_not_called()

    @mock.patch(
        "modules.authorized_analysis_snapshot_service.persist_analysis_snapshot"
    )
    def test_save_without_document_read_never_persists(self, persist_mock):
        service, case_service, *_ = self.build(
            {
                AccessPermission.CASE_READ,
                AccessPermission.CASE_UPDATE,
            }
        )
        case_service.list_documents.side_effect = PermissionError(
            "document denied"
        )
        with self.assertRaises(PermissionError):
            service.save_current_analysis(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                analysis=mock.Mock(),
                created_at=NOW,
            )
        persist_mock.assert_not_called()

    def test_history_list_requires_case_read_but_not_document_read(self):
        service, _, _, snapshot_repo, _ = self.build(
            {AccessPermission.CASE_READ}
        )
        snapshot_repo.list_snapshot_refs.return_value = [
            mock.sentinel.snapshot
        ]
        result = service.list_snapshot_history(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(result, [mock.sentinel.snapshot])

    @mock.patch(
        "modules.authorized_analysis_snapshot_service.load_analysis_snapshot"
    )
    def test_load_requires_document_read_and_same_case_snapshot(
        self,
        load_mock,
    ):
        (
            service,
            _,
            _,
            snapshot_repo,
            _,
        ) = self.build(
            {
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        ref = AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id="DOC-1",
            source_document_sha256="a" * 64,
            schema_version=1,
            engine_version="phase2-contract-2026.09.22.1",
            byte_size=100,
            sha256_hex="c" * 64,
            storage_key="objects/" + "d" * 32,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
        )
        snapshot_repo.get_snapshot_ref.return_value = ref
        expected = LoadedAnalysisSnapshot(
            metadata=ref,
            payload={"fixture": "data"},
        )
        load_mock.return_value = expected

        result = service.load_snapshot(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(result, expected)
        load_mock.assert_called_once()

    @mock.patch(
        "modules.authorized_analysis_snapshot_service.load_analysis_snapshot"
    )
    def test_snapshot_from_other_case_is_unavailable(self, load_mock):
        service, _, _, snapshot_repo, _ = self.build(
            {
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        snapshot_repo.get_snapshot_ref.return_value = AnalysisSnapshotRef(
            snapshot_id="SNAP-X",
            case_id="CASE-OTHER",
            source_document_id="DOC-1",
            source_document_sha256="a" * 64,
            schema_version=1,
            engine_version="phase2-contract-2026.09.22.1",
            byte_size=1,
            sha256_hex="c" * 64,
            storage_key="objects/" + "d" * 32,
            created_at=NOW,
            created_by=PRINCIPAL.user_id,
        )
        with self.assertRaises(LookupError):
            service.load_snapshot(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-X",
            )
        load_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
