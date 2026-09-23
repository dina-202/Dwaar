"""Tests for authorized snapshot-bound legal brief workspace."""

import unittest
from datetime import date, datetime, timezone
from unittest import mock

from domain.analysis_snapshot_models import AnalysisSnapshotRef, LoadedAnalysisSnapshot
from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import CaseRecord, CaseStatus
from domain.legal_brief_models import LegalBriefRef, LoadedLegalBrief
from domain.models import NoticeForm, ProceedingType
from modules.authorized_legal_brief_service import AuthorizedLegalBriefService


NOW = datetime(2026, 9, 23, 2, 0, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "b" * 64)


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
        sha256_hex="c" * 64,
        storage_key="objects/" + "d" * 32,
        created_at=NOW,
        created_by=PRINCIPAL.user_id,
    )


def grant(*permissions):
    return FirmAccessGrant(
        user_id=PRINCIPAL.user_id,
        firm_id="F-1",
        permissions=frozenset(permissions),
        active=True,
    )


def loaded_snapshot(notice_date="2026-08-01"):
    return LoadedAnalysisSnapshot(
        metadata=snapshot(),
        payload={
            "deadline": {"notice_date": notice_date},
            "classification": {
                "proceeding_type": ProceedingType.GST_SEC73_ITC.value
            },
            "extraction": {
                "facts": [] if notice_date is None else [
                    {
                        "fact_id": "F-N",
                        "claim": "Notice date",
                        "status": "confirmed",
                        "source_text": (
                            "Issued " + notice_date[8:10] + "/"
                            + notice_date[5:7] + "/" + notice_date[0:4]
                        ),
                        "source_page": 1,
                        "allowed_in_draft": "yes",
                        "fact_type": "notice_date",
                        "fact_role": "none",
                        "source_origin": "embedded",
                        "source_verification": "verified",
                    }
                ]
            },
        },
    )


def brief_ref():
    return LegalBriefRef(
        legal_brief_id="LEGAL-1",
        case_id="CASE-1",
        snapshot_id="SNAP-1",
        schema_version=1,
        catalog_version="gst-legal.v1.2026-09-23",
        as_of_date=date(2026, 8, 1),
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        byte_size=10,
        sha256_hex="e" * 64,
        storage_key="objects/" + "f" * 32,
        created_at=NOW,
        created_by=PRINCIPAL.user_id,
    )


class AuthorizedLegalBriefServiceTests(unittest.TestCase):
    def build(self, permissions):
        case_service = mock.Mock()
        case_service.get_case.return_value = case()
        snapshot_service = mock.Mock()
        snapshot_service.list_snapshot_history.return_value = [snapshot()]
        snapshot_service.load_snapshot.return_value = loaded_snapshot()
        access_repository = mock.Mock()
        access_repository.get_grant.return_value = grant(*permissions)
        brief_repository = mock.Mock()
        document_store = mock.Mock()
        service = AuthorizedLegalBriefService(
            case_service,
            snapshot_service,
            access_repository,
            brief_repository,
            document_store,
        )
        return (
            service,
            case_service,
            snapshot_service,
            access_repository,
            brief_repository,
            document_store,
        )

    @mock.patch(
        "modules.authorized_legal_brief_service.persist_legal_brief"
    )
    def test_save_derives_legal_binding_from_saved_snapshot(
        self,
        persist_mock,
    ):
        service, _, snapshot_service, _, _, _ = self.build(
            {AccessPermission.CASE_READ, AccessPermission.CASE_UPDATE}
        )
        persist_mock.return_value = mock.sentinel.brief

        result = service.save_for_snapshot(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            created_at=NOW,
        )

        self.assertIs(result, mock.sentinel.brief)
        kwargs = persist_mock.call_args.kwargs
        self.assertEqual(kwargs["as_of_date"], date(2026, 8, 1))
        self.assertIs(
            kwargs["proceeding_type"],
            ProceedingType.GST_SEC73_ITC,
        )
        self.assertEqual(kwargs["snapshot"], snapshot())
        self.assertEqual(kwargs["actor_id"], PRINCIPAL.user_id)
        question_plan = kwargs["question_plan"]
        self.assertIs(
            question_plan.proceeding_type,
            ProceedingType.GST_SEC73_ITC,
        )
        self.assertEqual(
            [item.status.value for item in question_plan.questions],
            [
                "source_verified_research_ready",
                "source_verified_research_ready",
                "missing_facts",
                "missing_facts",
            ],
        )
        snapshot_service.load_snapshot.assert_called_once()

    @mock.patch(
        "modules.authorized_legal_brief_service.persist_legal_brief"
    )
    def test_save_without_case_update_never_persists(self, persist_mock):
        service, *_ = self.build({AccessPermission.CASE_READ})
        with self.assertRaises(PermissionError):
            service.save_for_snapshot(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                created_at=NOW,
            )
        persist_mock.assert_not_called()

    @mock.patch(
        "modules.authorized_legal_brief_service.persist_legal_brief"
    )
    def test_snapshot_tax_period_is_available_to_legal_resolver(
        self,
        persist_mock,
    ):
        service, _, snapshot_service, *_ = self.build(
            {AccessPermission.CASE_READ, AccessPermission.CASE_UPDATE}
        )
        payload = loaded_snapshot().payload
        payload["extraction"]["facts"].append(
            {
                "fact_id": "F-T",
                "claim": "Tax period",
                "status": "confirmed",
                "source_text": "FY 2021-22",
                "source_page": 2,
                "allowed_in_draft": "yes",
                "fact_type": "tax_period",
                "fact_role": "none",
                "source_origin": "embedded",
                "source_verification": "verified",
            }
        )
        snapshot_service.load_snapshot.return_value = LoadedAnalysisSnapshot(
            metadata=snapshot(),
            payload=payload,
        )
        persist_mock.return_value = mock.sentinel.brief
        service.save_for_snapshot(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            created_at=NOW,
        )
        result = persist_mock.call_args.kwargs["result"]
        self.assertEqual(
            tuple(item.value for item in result.unresolved_topics),
            ("itc_mismatch_verification", "itc_eligibility"),
        )

    @mock.patch(
        "modules.authorized_legal_brief_service.persist_legal_brief"
    )
    def test_missing_notice_date_fails_closed(self, persist_mock):
        service, _, snapshot_service, *_ = self.build(
            {AccessPermission.CASE_READ, AccessPermission.CASE_UPDATE}
        )
        snapshot_service.load_snapshot.return_value = loaded_snapshot(None)
        with self.assertRaisesRegex(
            ValueError, "no unique verified notice date"
        ):
            service.save_for_snapshot(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                created_at=NOW,
            )
        persist_mock.assert_not_called()

    @mock.patch(
        "modules.authorized_legal_brief_service.list_legal_brief_refs"
    )
    def test_list_is_case_and_snapshot_scoped(self, list_mock):
        service, *_ = self.build({AccessPermission.CASE_READ})
        list_mock.return_value = [brief_ref()]
        result = service.list_for_snapshot(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(result, [brief_ref()])
        list_mock.assert_called_once_with(
            service._briefs,
            snapshot_id="SNAP-1",
        )

    @mock.patch(
        "modules.authorized_legal_brief_service.load_legal_brief"
    )
    def test_load_uses_expected_snapshot_binding(self, load_mock):
        service, _, _, _, brief_repository, _ = self.build(
            {AccessPermission.CASE_READ}
        )
        brief_repository.get_brief_ref.return_value = brief_ref()
        expected = LoadedLegalBrief(
            metadata=brief_ref(),
            payload={"fixture": "value"},
        )
        load_mock.return_value = expected
        result = service.load(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            legal_brief_id="LEGAL-1",
        )
        self.assertEqual(result, expected)
        self.assertEqual(
            load_mock.call_args.kwargs["expected_snapshot"],
            snapshot(),
        )

    @mock.patch(
        "modules.authorized_legal_brief_service.load_legal_brief"
    )
    def test_cross_case_brief_is_hidden(self, load_mock):
        service, _, _, _, brief_repository, _ = self.build(
            {AccessPermission.CASE_READ}
        )
        other = LegalBriefRef(
            **{**brief_ref().__dict__, "case_id": "CASE-OTHER"}
        )
        brief_repository.get_brief_ref.return_value = other
        with self.assertRaises(LookupError):
            service.load(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                legal_brief_id="LEGAL-1",
            )
        load_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
