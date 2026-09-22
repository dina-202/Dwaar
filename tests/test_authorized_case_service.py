"""Tests for tenant-safe authorized case services."""

import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest import mock

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    StoredDocumentRef,
)
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import (
    AuthorizedCaseService,
    StoredDocumentConsistencyError,
)


NOW = datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc)


def case_record(case_id="CASE-1", firm_id="F-1"):
    return CaseRecord(
        case_id=case_id,
        firm_id=firm_id,
        client_id="C-1",
        registration_id=None,
        title="Matter",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


class FakeCaseRepository:
    def __init__(self, cases=None, documents=None):
        self.cases = {
            case.case_id: case for case in (cases or [])
        }
        self.documents = documents or {}
        self.created = []
        self.updated = []

    def list_cases(self, firm_id):
        return [
            case for case in self.cases.values()
            if case.firm_id == firm_id
        ]

    def get_case(self, case_id):
        return self.cases.get(case_id)

    def create_case(self, case):
        self.created.append(case)
        self.cases[case.case_id] = case

    def update_case(self, case):
        self.updated.append(case)
        self.cases[case.case_id] = case

    def list_document_refs(self, case_id):
        return list(self.documents.get(case_id, []))


class FakeAccessRepository:
    def __init__(self, grants=None):
        self.grants = {
            (grant.user_id, grant.firm_id): grant
            for grant in (grants or [])
        }

    def get_grant(self, user_id, firm_id):
        return self.grants.get((user_id, firm_id))


class FakeDocumentStore:
    def __init__(self, payloads=None):
        self.payloads = payloads or {}

    def get(self, storage_key):
        return self.payloads[storage_key]


def grant(
    user_id="U-1",
    firm_id="F-1",
    permissions=None,
    active=True,
):
    return FirmAccessGrant(
        user_id=user_id,
        firm_id=firm_id,
        permissions=frozenset(permissions or set()),
        active=active,
    )


class AuthorizedCaseServiceTests(unittest.TestCase):
    def service(
        self,
        *,
        cases=None,
        documents=None,
        grants=None,
        payloads=None,
    ):
        return AuthorizedCaseService(
            FakeCaseRepository(cases, documents),
            FakeAccessRepository(grants),
            FakeDocumentStore(payloads),
        )

    def test_list_cases_requires_case_read(self):
        service = self.service(
            cases=[case_record()],
            grants=[
                grant(permissions={AccessPermission.CASE_READ})
            ],
        )
        result = service.list_cases(
            AuthenticatedPrincipal("U-1"),
            "F-1",
        )
        self.assertEqual([item.case_id for item in result], ["CASE-1"])

    def test_missing_grant_denies(self):
        service = self.service(cases=[case_record()])
        with self.assertRaises(AuthorizationError):
            service.list_cases(
                AuthenticatedPrincipal("U-1"),
                "F-1",
            )

    def test_missing_permission_denies(self):
        service = self.service(
            cases=[case_record()],
            grants=[grant(permissions={AccessPermission.DOCUMENT_READ})],
        )
        with self.assertRaises(AuthorizationError):
            service.list_cases(
                AuthenticatedPrincipal("U-1"),
                "F-1",
            )

    def test_get_cross_firm_case_returns_none(self):
        service = self.service(
            cases=[case_record("CASE-B", "F-2")],
            grants=[
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.CASE_READ},
                )
            ],
        )
        result = service.get_case(
            AuthenticatedPrincipal("U-1"),
            "F-1",
            "CASE-B",
        )
        self.assertIsNone(result)

    def test_create_case_must_match_authorized_firm(self):
        service = self.service(
            grants=[
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.CASE_CREATE},
                )
            ]
        )
        with self.assertRaises(AuthorizationError):
            service.create_case(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                case_record("CASE-B", "F-2"),
            )

    def test_update_cross_firm_case_is_not_found(self):
        existing = case_record("CASE-B", "F-2")
        service = self.service(
            cases=[existing],
            grants=[
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.CASE_UPDATE},
                )
            ],
        )
        with self.assertRaisesRegex(LookupError, "does not exist"):
            service.update_case(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                replace(existing, title="Changed"),
            )

    @mock.patch("modules.authorized_case_service.persist_pdf_document")
    def test_add_document_uses_authenticated_user_as_actor(
        self,
        persist_mock,
    ):
        case = case_record()
        service = self.service(
            cases=[case],
            grants=[
                grant(
                    permissions={AccessPermission.DOCUMENT_ADD}
                )
            ],
        )
        expected = StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=4,
            sha256_hex="a" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=NOW,
        )
        persist_mock.return_value = expected

        result = service.add_pdf_document(
            AuthenticatedPrincipal("U-1"),
            "F-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            payload=b"%PDF",
            created_at=NOW,
        )

        self.assertEqual(result, expected)
        self.assertEqual(
            persist_mock.call_args.kwargs["actor_id"],
            "U-1",
        )
        self.assertEqual(
            persist_mock.call_args.kwargs["case_id"],
            "CASE-1",
        )

    @mock.patch("modules.authorized_case_service.persist_pdf_document")
    def test_add_document_cross_firm_case_never_calls_persistence(
        self,
        persist_mock,
    ):
        service = self.service(
            cases=[case_record("CASE-B", "F-2")],
            grants=[
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.DOCUMENT_ADD},
                )
            ],
        )
        with self.assertRaises(LookupError):
            service.add_pdf_document(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                case_id="CASE-B",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                payload=b"%PDF",
                created_at=NOW,
            )
        persist_mock.assert_not_called()

    def test_read_document_returns_verified_bytes(self):
        payload = b"secret pdf bytes"
        document = StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(payload),
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            storage_key="objects/" + "c" * 32,
            created_at=NOW,
        )
        service = self.service(
            cases=[case_record()],
            documents={"CASE-1": [document]},
            grants=[
                grant(
                    permissions={AccessPermission.DOCUMENT_READ}
                )
            ],
            payloads={document.storage_key: payload},
        )

        loaded_document, loaded_payload = service.read_document(
            AuthenticatedPrincipal("U-1"),
            "F-1",
            case_id="CASE-1",
            document_id="DOC-1",
        )
        self.assertEqual(loaded_document, document)
        self.assertEqual(loaded_payload, payload)

    def test_read_cross_firm_document_is_unavailable(self):
        payload = b"secret"
        document = StoredDocumentRef(
            document_id="DOC-B",
            case_id="CASE-B",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(payload),
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            storage_key="objects/" + "d" * 32,
            created_at=NOW,
        )
        service = self.service(
            cases=[case_record("CASE-B", "F-2")],
            documents={"CASE-B": [document]},
            grants=[
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.DOCUMENT_READ},
                )
            ],
            payloads={document.storage_key: payload},
        )
        with self.assertRaises(LookupError):
            service.read_document(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                case_id="CASE-B",
                document_id="DOC-B",
            )

    def test_read_detects_byte_size_mismatch(self):
        payload = b"actual payload"
        document = StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(payload) + 1,
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            storage_key="objects/" + "e" * 32,
            created_at=NOW,
        )
        service = self.service(
            cases=[case_record()],
            documents={"CASE-1": [document]},
            grants=[
                grant(
                    permissions={AccessPermission.DOCUMENT_READ}
                )
            ],
            payloads={document.storage_key: payload},
        )
        with self.assertRaisesRegex(
            StoredDocumentConsistencyError,
            "byte size",
        ):
            service.read_document(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                case_id="CASE-1",
                document_id="DOC-1",
            )

    def test_read_detects_hash_mismatch(self):
        payload = b"actual payload"
        document = StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=len(payload),
            sha256_hex="f" * 64,
            storage_key="objects/" + "f" * 32,
            created_at=NOW,
        )
        service = self.service(
            cases=[case_record()],
            documents={"CASE-1": [document]},
            grants=[
                grant(
                    permissions={AccessPermission.DOCUMENT_READ}
                )
            ],
            payloads={document.storage_key: payload},
        )
        with self.assertRaisesRegex(
            StoredDocumentConsistencyError,
            "hash",
        ):
            service.read_document(
                AuthenticatedPrincipal("U-1"),
                "F-1",
                case_id="CASE-1",
                document_id="DOC-1",
            )


if __name__ == "__main__":
    unittest.main()
