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
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    TaxRegistration,
)
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import AuthorizedCaseService
from modules.case_intake_service import (
    CaseIntakeConsistencyError,
    CaseIntakePersistenceError,
    persist_existing_client_case_intake,
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
        self.assertCountEqual(
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


class ExistingClientIntakeIntegrationTests(DurableCaseIntakeIntegrationTests):
    def setUp(self):
        super().setUp()
        self.client = Client(
            "CLIENT-EXISTING",
            "F-1",
            "Existing Taxpayer",
            NOW,
        )
        self.registration = TaxRegistration(
            "REG-EXISTING",
            self.client.client_id,
            "IN-GST",
            "GSTIN",
            "06ABCDE1234F1Z5",
            NOW,
        )
        self.repo.create_client(self.client)
        self.repo.create_registration(self.registration)

    def persist_existing(self, **overrides):
        values = {
            "firm_id": "F-1",
            "client_id": self.client.client_id,
            "registration_id": self.registration.registration_id,
            "case_title": "Second notice for existing taxpayer",
            "proceeding_type": ProceedingType.GST_SEC73_ITC,
            "notice_form": NoticeForm.DRC_01,
            "response_deadline": date(2026, 10, 20),
            "notice_filename": "second-notice.pdf",
            "notice_payload": make_pdf("Second saved notice"),
            "actor_id": "OIDC-" + "a" * 64,
            "opened_at": NOW,
        }
        values.update(overrides)
        return persist_existing_client_case_intake(
            self.repo,
            self.store,
            **values,
        )

    def test_reuse_creates_case_without_duplicate_client_or_registration(self):
        payload = make_pdf("Second saved notice")
        case = self.persist_existing(notice_payload=payload)

        self.assertEqual(case.client_id, self.client.client_id)
        self.assertEqual(
            case.registration_id,
            self.registration.registration_id,
        )
        self.assertEqual(
            self.repo.list_clients("F-1"),
            [self.client],
        )
        self.assertEqual(
            self.repo.list_registrations(self.client.client_id),
            [self.registration],
        )
        self.assertEqual(
            [item.case_id for item in self.repo.list_cases("F-1")],
            [case.case_id],
        )
        documents = self.repo.list_document_refs(case.case_id)
        self.assertEqual(len(documents), 1)
        self.assertEqual(
            self.store.get(documents[0].storage_key),
            payload,
        )

    def test_existing_client_can_create_case_without_registration(self):
        case = self.persist_existing(registration_id=None)
        self.assertEqual(case.client_id, self.client.client_id)
        self.assertIsNone(case.registration_id)
        self.assertEqual(len(self.repo.list_clients("F-1")), 1)
        self.assertEqual(
            len(self.repo.list_registrations(self.client.client_id)),
            1,
        )

    def test_client_from_another_firm_fails_before_encrypted_write(self):
        self.repo.create_firm(Firm("F-2", "Other Firm", NOW))
        other = Client("CLIENT-OTHER", "F-2", "Other", NOW)
        self.repo.create_client(other)
        with mock.patch.object(self.store, "put") as put:
            with self.assertRaisesRegex(LookupError, "selected firm"):
                self.persist_existing(client_id=other.client_id)
        put.assert_not_called()
        self.assertEqual(self.repo.list_cases("F-1"), [])

    def test_registration_from_another_client_fails_before_encrypted_write(self):
        other = Client("CLIENT-OTHER", "F-1", "Other", NOW)
        self.repo.create_client(other)
        other_registration = TaxRegistration(
            "REG-OTHER",
            other.client_id,
            "IN-GST",
            "GSTIN",
            "27ABCDE1234F1Z5",
            NOW,
        )
        self.repo.create_registration(other_registration)

        with mock.patch.object(self.store, "put") as put:
            with self.assertRaisesRegex(LookupError, "selected client"):
                self.persist_existing(
                    registration_id=other_registration.registration_id
                )
        put.assert_not_called()
        self.assertEqual(self.repo.list_cases("F-1"), [])

    def test_existing_client_intake_relational_failure_rolls_back_ciphertext(self):
        with mock.patch.object(
            self.repo,
            "create_existing_client_case_intake",
            side_effect=RuntimeError("database failed"),
        ):
            with self.assertRaises(CaseIntakePersistenceError):
                self.persist_existing()
        self.assertEqual(list(Path(self.object_root).glob("*.dwaar")), [])


class ClientDiscoveryRepositoryTests(DurableCaseIntakeIntegrationTests):
    def test_clients_are_firm_scoped_and_stably_ordered(self):
        self.repo.create_firm(Firm("F-2", "Other Firm", NOW))
        alpha = Client("C-A", "F-1", "alpha", NOW)
        beta = Client("C-B", "F-1", "Beta", NOW)
        hidden = Client("C-X", "F-2", "Aardvark", NOW)
        for client in (beta, hidden, alpha):
            self.repo.create_client(client)

        self.assertEqual(
            [item.client_id for item in self.repo.list_clients("F-1")],
            ["C-A", "C-B"],
        )
        self.assertEqual(
            [item.client_id for item in self.repo.list_clients("F-2")],
            ["C-X"],
        )

    def test_registrations_are_client_scoped(self):
        one = Client("C-1", "F-1", "One", NOW)
        two = Client("C-2", "F-1", "Two", NOW)
        self.repo.create_client(one)
        self.repo.create_client(two)
        r2 = TaxRegistration(
            "R-2", "C-1", "IN-GST", "GSTIN", "27ZZZZZ9999Z1Z9", NOW
        )
        r1 = TaxRegistration(
            "R-1", "C-1", "IN-GST", "GSTIN", "06AAAAA0000A1Z5", NOW
        )
        hidden = TaxRegistration(
            "R-X", "C-2", "IN-GST", "GSTIN", "29BBBBB1111B1Z5", NOW
        )
        for registration in (r2, hidden, r1):
            self.repo.create_registration(registration)

        self.assertEqual(
            [item.registration_id for item in self.repo.list_registrations("C-1")],
            ["R-1", "R-2"],
        )
        self.assertEqual(
            [item.registration_id for item in self.repo.list_registrations("C-2")],
            ["R-X"],
        )


class ClientWorkspaceHistoryTests(DurableCaseIntakeIntegrationTests):
    def test_client_case_history_is_newest_first_and_client_scoped(self):
        client_one = Client("C-1", "F-1", "One", NOW)
        client_two = Client("C-2", "F-1", "Two", NOW)
        self.repo.create_client(client_one)
        self.repo.create_client(client_two)

        older = CaseRecord(
            "CASE-OLD",
            "F-1",
            "C-1",
            None,
            "Older",
            CaseStatus.INTAKE,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        newer = CaseRecord(
            "CASE-NEW",
            "F-1",
            "C-1",
            None,
            "Newer",
            CaseStatus.INTAKE,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        hidden = CaseRecord(
            "CASE-HIDDEN",
            "F-1",
            "C-2",
            None,
            "Hidden",
            CaseStatus.INTAKE,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        for item in (older, newer, hidden):
            self.repo.create_case(item)

        self.assertEqual(
            [
                item.case_id
                for item in self.repo.list_cases_for_client("C-1")
            ],
            ["CASE-NEW", "CASE-OLD"],
        )

    def test_authorized_client_workspace_composes_only_selected_client(self):
        case_repo = mock.Mock()
        access_repo = mock.Mock()
        document_store = mock.Mock()
        principal = AuthenticatedPrincipal("OIDC-" + "e" * 64)
        access_repo.get_grant.return_value = FirmAccessGrant(
            user_id=principal.user_id,
            firm_id="F-1",
            permissions=frozenset({AccessPermission.CASE_READ}),
            active=True,
        )
        client = Client("C-1", "F-1", "Client", NOW)
        registration = TaxRegistration(
            "R-1", "C-1", "IN-GST", "GSTIN", "06AAAAA0000A1Z5", NOW
        )
        case_repo.get_client.return_value = client
        case_repo.list_registrations.return_value = [registration]
        case_repo.list_cases_for_client.return_value = [mock.Mock()]
        service = AuthorizedCaseService(
            case_repo,
            access_repo,
            document_store,
        )

        workspace = service.get_client_workspace(
            principal,
            "F-1",
            client_id="C-1",
        )

        self.assertIs(workspace.client, client)
        self.assertEqual(workspace.registrations, [registration])
        self.assertEqual(len(workspace.cases), 1)
        case_repo.list_registrations.assert_called_once_with("C-1")
        case_repo.list_cases_for_client.assert_called_once_with("C-1")

    def test_authorized_client_workspace_rejects_other_firm_client(self):
        case_repo = mock.Mock()
        access_repo = mock.Mock()
        document_store = mock.Mock()
        principal = AuthenticatedPrincipal("OIDC-" + "e" * 64)
        access_repo.get_grant.return_value = FirmAccessGrant(
            user_id=principal.user_id,
            firm_id="F-1",
            permissions=frozenset({AccessPermission.CASE_READ}),
            active=True,
        )
        case_repo.get_client.return_value = Client(
            "C-X", "F-2", "Other Firm Client", NOW
        )
        service = AuthorizedCaseService(
            case_repo,
            access_repo,
            document_store,
        )

        with self.assertRaises(LookupError):
            service.get_client_workspace(
                principal,
                "F-1",
                client_id="C-X",
            )
        case_repo.list_registrations.assert_not_called()
        case_repo.list_cases_for_client.assert_not_called()


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


class AuthorizedClientReuseTests(unittest.TestCase):
    def _service(self, permissions):
        case_repo = mock.Mock()
        access_repo = mock.Mock()
        document_store = mock.Mock()
        principal = AuthenticatedPrincipal("OIDC-" + "e" * 64)
        access_repo.get_grant.return_value = FirmAccessGrant(
            user_id=principal.user_id,
            firm_id="F-1",
            permissions=frozenset(permissions),
            active=True,
        )
        return (
            AuthorizedCaseService(
                case_repo,
                access_repo,
                document_store,
            ),
            case_repo,
            principal,
        )

    def test_client_discovery_requires_case_read_and_is_firm_scoped(self):
        service, repo, principal = self._service(
            {AccessPermission.CASE_READ}
        )
        clients = [Client("C-1", "F-1", "Client", NOW)]
        repo.list_clients.return_value = clients
        self.assertEqual(
            service.list_clients(principal, "F-1"),
            clients,
        )
        repo.list_clients.assert_called_once_with("F-1")

    def test_registration_discovery_rejects_client_from_other_firm(self):
        service, repo, principal = self._service(
            {AccessPermission.CASE_READ}
        )
        repo.get_client.return_value = Client(
            "C-X", "F-2", "Other", NOW
        )
        with self.assertRaises(LookupError):
            service.list_registrations(
                principal,
                "F-1",
                client_id="C-X",
            )
        repo.list_registrations.assert_not_called()

    @mock.patch(
        "modules.authorized_case_service.persist_existing_client_case_intake"
    )
    def test_existing_client_intake_uses_authenticated_actor(
        self,
        persist_mock,
    ):
        service, repo, principal = self._service(
            {AccessPermission.CASE_CREATE}
        )
        client = Client("C-1", "F-1", "Client", NOW)
        registration = TaxRegistration(
            "R-1",
            client.client_id,
            "IN-GST",
            "GSTIN",
            "06AAAAA0000A1Z5",
            NOW,
        )
        repo.get_client.return_value = client
        repo.get_registration.return_value = registration
        expected = mock.Mock()
        persist_mock.return_value = expected

        result = service.create_existing_client_case_intake(
            principal,
            "F-1",
            client_id=client.client_id,
            registration_id=registration.registration_id,
            case_title="Matter",
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            response_deadline=None,
            notice_filename="notice.pdf",
            notice_payload=b"%PDF fixture",
            opened_at=NOW,
        )

        self.assertIs(result, expected)
        kwargs = persist_mock.call_args.kwargs
        self.assertEqual(kwargs["firm_id"], "F-1")
        self.assertEqual(kwargs["client_id"], "C-1")
        self.assertEqual(kwargs["registration_id"], "R-1")
        self.assertEqual(kwargs["actor_id"], principal.user_id)

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
