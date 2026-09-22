"""End-to-end tests for durable new-case intake."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import fitz
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseEventType,
    CaseStatus,
    Firm,
)
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import AuthorizedCaseService
from modules.case_intake_service import (
    CaseIntakeConsistencyError,
    CaseIntakePersistenceError,
    persist_new_case_intake,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)


def make_pdf(text="Durable intake notice") -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


class DurableCaseIntakeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")
        self.repo = LocalSQLiteCaseRepository(self.db_path)
        self.repo.create_firm(
            Firm("F-1", "Pilot CA Firm", NOW)
        )
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=2 * 1024 * 1024,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def persist(self, **overrides):
        values = {
            "firm_id": "F-1",
            "client_name": "Example Private Limited",
            "gstin": "06abcde1234f1z5",
            "case_title": "DRC-01 ITC mismatch",
            "proceeding_type": ProceedingType.GST_SEC73_ITC,
            "notice_form": NoticeForm.DRC_01,
            "response_deadline": date(2026, 10, 10),
            "notice_filename": "notice.pdf",
            "notice_payload": make_pdf(),
            "actor_id": "OIDC-" + "a" * 64,
            "opened_at": NOW,
        }
        values.update(overrides)
        return persist_new_case_intake(
            self.repo,
            self.store,
            **values,
        )

    def test_full_intake_persists_client_registration_case_notice_and_events(self):
        payload = make_pdf("GST notice integration sentinel")
        case = self.persist(notice_payload=payload)

        self.assertIs(case.status, CaseStatus.INTAKE)
        self.assertEqual(case.firm_id, "F-1")
        self.assertEqual(case.response_deadline, date(2026, 10, 10))
        self.assertTrue(case.case_id.startswith("CASE-"))

        client = self.repo.get_client(case.client_id)
        self.assertEqual(client.display_name, "Example Private Limited")
        self.assertEqual(client.firm_id, "F-1")

        registration = self.repo.get_registration(
            case.registration_id
        )
        self.assertEqual(
            registration.identifier_value,
            "06ABCDE1234F1Z5",
        )
        self.assertEqual(registration.identifier_type, "GSTIN")
        self.assertEqual(registration.jurisdiction, "IN-GST")

        documents = self.repo.list_document_refs(case.case_id)
        self.assertEqual(len(documents), 1)
        notice = documents[0]
        self.assertEqual(notice.original_filename, "notice.pdf")
        self.assertEqual(self.store.get(notice.storage_key), payload)

        events = self.repo.list_events(case.case_id)
        self.assertEqual(
            [event.event_type for event in events],
            [
                CaseEventType.CASE_CREATED,
                CaseEventType.DOCUMENT_ADDED,
            ],
        )
        self.assertEqual(
            {event.actor_id for event in events},
            {"OIDC-" + "a" * 64},
        )
        self.assertNotIn(
            "Example Private Limited",
            repr([event.payload for event in events]),
        )
        self.assertNotIn(
            "06ABCDE1234F1Z5",
            repr([event.payload for event in events]),
        )

    def test_blank_gstin_creates_case_without_registration(self):
        case = self.persist(gstin="   ")
        self.assertIsNone(case.registration_id)
        self.assertIsNone(
            self.repo.get_registration("REG-does-not-exist")
        )

    def test_invalid_gstin_fails_before_encrypted_write(self):
        with mock.patch.object(self.store, "put") as put:
            with self.assertRaisesRegex(ValueError, "GSTIN"):
                self.persist(gstin="INVALID")
        put.assert_not_called()
        self.assertEqual(self.repo.list_cases("F-1"), [])

    def test_invalid_pdf_fails_before_encrypted_write(self):
        with mock.patch.object(self.store, "put") as put:
            with self.assertRaisesRegex(ValueError, "not a PDF"):
                self.persist(notice_payload=b"not-pdf")
        put.assert_not_called()
        self.assertEqual(self.repo.list_cases("F-1"), [])

    def test_database_failure_rolls_back_entire_bundle_and_ciphertext(self):
        payload = make_pdf("rollback sentinel")
        id_sequence = [
            "CLIENT-1",
            "REG-1",
            "CASE-1",
            "DOC-1",
            "EV-DUP",
            "EV-DUP",
        ]
        with (
            mock.patch(
                "modules.case_intake_service._id",
                side_effect=id_sequence,
            ),
            mock.patch(
                "modules.case_intake_service.generate_storage_key",
                return_value="objects/" + "b" * 32,
            ),
        ):
            with self.assertRaises(CaseIntakePersistenceError):
                self.persist(notice_payload=payload)

        self.assertEqual(self.repo.list_cases("F-1"), [])
        self.assertIsNone(self.repo.get_client("CLIENT-1"))
        self.assertIsNone(self.repo.get_registration("REG-1"))
        self.assertFalse(
            self.store.exists("objects/" + "b" * 32)
        )

        with self.repo._connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM case_documents"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM case_events"
                ).fetchone()[0],
                0,
            )

    def test_unknown_firm_fails_before_encrypted_write(self):
        with mock.patch.object(self.store, "put") as put:
            with self.assertRaisesRegex(LookupError, "firm"):
                self.persist(firm_id="F-MISSING")
        put.assert_not_called()


class IntakeFailureBoundaryTests(unittest.TestCase):
    def test_repository_failure_deletes_encrypted_object(self):
        repository = mock.Mock()
        repository.get_firm.return_value = object()
        repository.create_case_intake.side_effect = RuntimeError(
            "database failed"
        )
        store = mock.Mock()
        payload = make_pdf()

        with mock.patch(
            "modules.case_intake_service.generate_storage_key",
            return_value="objects/" + "c" * 32,
        ):
            with self.assertRaises(CaseIntakePersistenceError):
                persist_new_case_intake(
                    repository,
                    store,
                    firm_id="F-1",
                    client_name="Client",
                    gstin=None,
                    case_title="Matter",
                    proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                    notice_form=NoticeForm.DRC_01,
                    response_deadline=None,
                    notice_filename="notice.pdf",
                    notice_payload=payload,
                    actor_id="U-1",
                    opened_at=NOW,
                )

        store.put.assert_called_once()
        store.delete.assert_called_once_with(
            "objects/" + "c" * 32
        )

    def test_rollback_failure_is_distinct_consistency_error(self):
        repository = mock.Mock()
        repository.get_firm.return_value = object()
        repository.create_case_intake.side_effect = RuntimeError(
            "database failed"
        )
        store = mock.Mock()
        store.delete.side_effect = RuntimeError("delete failed")

        with mock.patch(
            "modules.case_intake_service.generate_storage_key",
            return_value="objects/" + "d" * 32,
        ):
            with self.assertRaises(CaseIntakeConsistencyError):
                persist_new_case_intake(
                    repository,
                    store,
                    firm_id="F-1",
                    client_name="Client",
                    gstin=None,
                    case_title="Matter",
                    proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                    notice_form=NoticeForm.DRC_01,
                    response_deadline=None,
                    notice_filename="notice.pdf",
                    notice_payload=make_pdf(),
                    actor_id="U-1",
                    opened_at=NOW,
                )


class AuthorizedDurableIntakeTests(unittest.TestCase):
    @mock.patch("modules.authorized_case_service.persist_new_case_intake")
    def test_case_create_permission_and_principal_actor_are_used(
        self,
        persist_mock,
    ):
        case_repo = mock.Mock()
        access_repo = mock.Mock()
        document_store = mock.Mock()
        principal = AuthenticatedPrincipal("OIDC-" + "e" * 64)
        access_repo.get_grant.return_value = FirmAccessGrant(
            user_id=principal.user_id,
            firm_id="F-1",
            permissions=frozenset({AccessPermission.CASE_CREATE}),
            active=True,
        )
        expected = mock.Mock()
        persist_mock.return_value = expected
        service = AuthorizedCaseService(
            case_repo,
            access_repo,
            document_store,
        )

        result = service.create_case_intake(
            principal,
            "F-1",
            client_name="Client",
            gstin=None,
            case_title="Matter",
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            response_deadline=None,
            notice_filename="notice.pdf",
            notice_payload=b"%PDF-1.7 fixture",
            opened_at=NOW,
        )

        self.assertIs(result, expected)
        self.assertEqual(
            persist_mock.call_args.kwargs["actor_id"],
            principal.user_id,
        )
        self.assertEqual(
            persist_mock.call_args.kwargs["firm_id"],
            "F-1",
        )

    @mock.patch("modules.authorized_case_service.persist_new_case_intake")
    def test_missing_case_create_permission_never_calls_intake(
        self,
        persist_mock,
    ):
        case_repo = mock.Mock()
        access_repo = mock.Mock()
        document_store = mock.Mock()
        principal = AuthenticatedPrincipal("OIDC-" + "f" * 64)
        access_repo.get_grant.return_value = FirmAccessGrant(
            user_id=principal.user_id,
            firm_id="F-1",
            permissions=frozenset({AccessPermission.CASE_READ}),
            active=True,
        )
        service = AuthorizedCaseService(
            case_repo,
            access_repo,
            document_store,
        )

        with self.assertRaises(PermissionError):
            service.create_case_intake(
                principal,
                "F-1",
                client_name="Client",
                gstin=None,
                case_title="Matter",
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                response_deadline=None,
                notice_filename="notice.pdf",
                notice_payload=b"%PDF-1.7 fixture",
                opened_at=NOW,
            )
        persist_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
