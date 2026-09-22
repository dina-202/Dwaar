"""Persistence ports for Dwaar Phase 3D.

These Protocols isolate domain/product code from the database and binary
storage backend. Implementations may use SQLite/PostgreSQL and local or
cloud object storage without changing domain callers.
"""

from typing import List, Optional, Protocol

from domain.case_models import (
    CaseEvent,
    CaseRecord,
    CaseSnapshot,
    Client,
    Firm,
    StoredDocumentRef,
    TaxRegistration,
)


class CaseRepository(Protocol):
    def create_firm(self, firm: Firm) -> None:
        ...

    def get_firm(self, firm_id: str) -> Optional[Firm]:
        ...

    def create_client(self, client: Client) -> None:
        ...

    def get_client(self, client_id: str) -> Optional[Client]:
        ...

    def create_registration(self, registration: TaxRegistration) -> None:
        ...

    def get_registration(
        self, registration_id: str
    ) -> Optional[TaxRegistration]:
        ...

    def create_case(self, case: CaseRecord) -> None:
        ...

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        ...

    def list_cases(self, firm_id: str) -> List[CaseRecord]:
        ...

    def update_case(self, case: CaseRecord) -> None:
        ...

    def add_document_ref(self, document: StoredDocumentRef) -> None:
        ...

    def list_document_refs(self, case_id: str) -> List[StoredDocumentRef]:
        ...

    def add_document_with_event(
        self,
        document: StoredDocumentRef,
        event: CaseEvent,
    ) -> None:
        ...

    def append_event(self, event: CaseEvent) -> None:
        ...

    def list_events(self, case_id: str) -> List[CaseEvent]:
        ...

    def get_snapshot(self, case_id: str) -> Optional[CaseSnapshot]:
        ...


class DocumentStore(Protocol):
    """Binary-store boundary.

    Implementations must not expose user-controlled filenames as storage
    keys and must enforce authorization outside this low-level port.
    """

    def put(self, storage_key: str, payload: bytes) -> None:
        ...

    def get(self, storage_key: str) -> bytes:
        ...

    def delete(self, storage_key: str) -> None:
        ...

    def exists(self, storage_key: str) -> bool:
        ...
