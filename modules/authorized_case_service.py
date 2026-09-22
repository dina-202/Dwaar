"""Authorized application services for persistent Dwaar case operations."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime
from typing import List, Optional, Tuple

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
    FirmAccessGrant,
)
from domain.authorization import require_firm_permission
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    Client,
    StoredDocumentRef,
    TaxRegistration,
)
from domain.models import NoticeForm, ProceedingType
from domain.persistence_ports import (
    AccessGrantRepository,
    CaseRepository,
    DocumentStore,
)
from modules.case_document_service import persist_pdf_document
from modules.case_intake_service import (
    persist_existing_client_case_intake,
    persist_new_case_intake,
)


class StoredDocumentConsistencyError(RuntimeError):
    """Decrypted bytes do not match persisted document metadata."""


class AuthorizedCaseService:
    """Tenant-safe application boundary over case/document persistence."""

    def __init__(
        self,
        case_repository: CaseRepository,
        access_repository: AccessGrantRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_repository
        self._access = access_repository
        self._documents = document_store

    def _grant(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        permission: AccessPermission,
    ) -> FirmAccessGrant:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")
        grant = self._access.get_grant(principal.user_id, firm_id)
        if grant is None:
            raise AuthorizationError("access denied")
        require_firm_permission(
            principal,
            grant,
            firm_id,
            permission,
        )
        return grant

    def _case_in_firm(
        self,
        firm_id: str,
        case_id: str,
    ) -> Optional[CaseRecord]:
        case = self._cases.get_case(case_id)
        if case is None or case.firm_id != firm_id:
            return None
        return case

    def list_cases(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
    ) -> List[CaseRecord]:
        self._grant(principal, firm_id, AccessPermission.CASE_READ)
        return self._cases.list_cases(firm_id)

    def get_case(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        case_id: str,
    ) -> Optional[CaseRecord]:
        self._grant(principal, firm_id, AccessPermission.CASE_READ)
        return self._case_in_firm(firm_id, case_id)

    def list_clients(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
    ) -> List[Client]:
        """List clients visible inside one authorized firm."""
        self._grant(principal, firm_id, AccessPermission.CASE_READ)
        return self._cases.list_clients(firm_id)

    def list_registrations(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        client_id: str,
    ) -> List[TaxRegistration]:
        """List tax registrations for one client in the selected firm."""
        self._grant(principal, firm_id, AccessPermission.CASE_READ)
        client = self._case_client_in_firm(firm_id, client_id)
        if client is None:
            raise LookupError("client does not exist")
        return self._cases.list_registrations(client.client_id)

    def _case_client_in_firm(
        self,
        firm_id: str,
        client_id: str,
    ) -> Optional[Client]:
        client = self._cases.get_client(client_id)
        if client is None or client.firm_id != firm_id:
            return None
        return client

    def create_case(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        case: CaseRecord,
    ) -> None:
        self._grant(principal, firm_id, AccessPermission.CASE_CREATE)
        if not isinstance(case, CaseRecord):
            raise TypeError("case must be a CaseRecord")
        if case.firm_id != firm_id:
            raise AuthorizationError("access denied")
        self._cases.create_case(case)

    def create_case_intake(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        client_name: str,
        gstin: Optional[str],
        case_title: str,
        proceeding_type: ProceedingType,
        notice_form: NoticeForm,
        response_deadline: Optional[date],
        notice_filename: str,
        notice_payload: bytes,
        opened_at: datetime,
    ) -> CaseRecord:
        """Create a new durable intake case under one authorized firm."""
        self._grant(principal, firm_id, AccessPermission.CASE_CREATE)
        return persist_new_case_intake(
            self._cases,
            self._documents,
            firm_id=firm_id,
            client_name=client_name,
            gstin=gstin,
            case_title=case_title,
            proceeding_type=proceeding_type,
            notice_form=notice_form,
            response_deadline=response_deadline,
            notice_filename=notice_filename,
            notice_payload=notice_payload,
            actor_id=principal.user_id,
            opened_at=opened_at,
        )

    def create_existing_client_case_intake(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        client_id: str,
        registration_id: Optional[str],
        case_title: str,
        proceeding_type: ProceedingType,
        notice_form: NoticeForm,
        response_deadline: Optional[date],
        notice_filename: str,
        notice_payload: bytes,
        opened_at: datetime,
    ) -> CaseRecord:
        """Create a durable intake case for an explicitly selected client."""
        self._grant(principal, firm_id, AccessPermission.CASE_CREATE)
        client = self._case_client_in_firm(firm_id, client_id)
        if client is None:
            raise LookupError("client does not exist")
        if registration_id is not None:
            registration = self._cases.get_registration(registration_id)
            if (
                registration is None
                or registration.client_id != client.client_id
            ):
                raise LookupError(
                    "registration does not exist for the selected client"
                )

        return persist_existing_client_case_intake(
            self._cases,
            self._documents,
            firm_id=firm_id,
            client_id=client.client_id,
            registration_id=registration_id,
            case_title=case_title,
            proceeding_type=proceeding_type,
            notice_form=notice_form,
            response_deadline=response_deadline,
            notice_filename=notice_filename,
            notice_payload=notice_payload,
            actor_id=principal.user_id,
            opened_at=opened_at,
        )

    def update_case(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        case: CaseRecord,
    ) -> None:
        self._grant(principal, firm_id, AccessPermission.CASE_UPDATE)
        if not isinstance(case, CaseRecord):
            raise TypeError("case must be a CaseRecord")
        existing = self._case_in_firm(firm_id, case.case_id)
        if existing is None:
            raise LookupError("case does not exist")
        if case.firm_id != firm_id:
            raise AuthorizationError("access denied")
        self._cases.update_case(case)

    def list_documents(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ) -> List[StoredDocumentRef]:
        """List document metadata for one authorized case."""
        self._grant(principal, firm_id, AccessPermission.DOCUMENT_READ)
        case = self._case_in_firm(firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        return self._cases.list_document_refs(case.case_id)

    def add_pdf_document(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        kind: CaseDocumentKind,
        original_filename: str,
        payload: bytes,
        created_at: datetime,
    ) -> StoredDocumentRef:
        self._grant(principal, firm_id, AccessPermission.DOCUMENT_ADD)
        case = self._case_in_firm(firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")

        return persist_pdf_document(
            self._cases,
            self._documents,
            case_id=case.case_id,
            kind=kind,
            original_filename=original_filename,
            payload=payload,
            actor_id=principal.user_id,
            created_at=created_at,
        )

    def read_document(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        document_id: str,
    ) -> Tuple[StoredDocumentRef, bytes]:
        self._grant(principal, firm_id, AccessPermission.DOCUMENT_READ)
        case = self._case_in_firm(firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")

        matching = [
            document
            for document in self._cases.list_document_refs(case.case_id)
            if document.document_id == document_id
        ]
        if len(matching) != 1:
            raise LookupError("document does not exist")

        document = matching[0]
        payload = self._documents.get(document.storage_key)
        if len(payload) != document.byte_size:
            raise StoredDocumentConsistencyError(
                "stored document byte size does not match metadata"
            )
        if hashlib.sha256(payload).hexdigest() != document.sha256_hex:
            raise StoredDocumentConsistencyError(
                "stored document hash does not match metadata"
            )
        return document, payload
