"""Persistence ports for Dwaar Phase 3D.

These Protocols isolate domain/product code from the database and binary
storage backend. Implementations may use SQLite/PostgreSQL and local or
cloud object storage without changing domain callers.
"""

from typing import List, Optional, Protocol

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.evidence_review_models import EvidenceReviewRef
from domain.fact_review_models import FactReviewRef
from domain.draft_work_product_models import DraftVersionRef
from domain.filing_models import FilingRecord
from domain.legal_brief_models import LegalBriefRef
from domain.auth_models import FirmAccessGrant
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

    def list_clients(self, firm_id: str) -> List[Client]:
        ...

    def create_registration(self, registration: TaxRegistration) -> None:
        ...

    def get_registration(
        self, registration_id: str
    ) -> Optional[TaxRegistration]:
        ...

    def list_registrations(
        self, client_id: str
    ) -> List[TaxRegistration]:
        ...

    def create_case(self, case: CaseRecord) -> None:
        ...

    def create_case_intake(
        self,
        client: Client,
        registration: Optional[TaxRegistration],
        case: CaseRecord,
        document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        ...

    def create_existing_client_case_intake(
        self,
        case: CaseRecord,
        document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        ...

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        ...

    def list_cases(self, firm_id: str) -> List[CaseRecord]:
        ...

    def list_cases_for_client(
        self, client_id: str
    ) -> List[CaseRecord]:
        ...

    def update_case(self, case: CaseRecord) -> None:
        ...

    def update_case_with_events(
        self,
        case: CaseRecord,
        events: List[CaseEvent],
    ) -> None:
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


class AnalysisSnapshotRepository(Protocol):
    """Persistent metadata/audit boundary for encrypted analysis snapshots."""

    def save_snapshot(
        self,
        snapshot: AnalysisSnapshotRef,
        event: CaseEvent,
    ) -> None:
        ...

    def get_snapshot_ref(
        self,
        snapshot_id: str,
    ) -> Optional[AnalysisSnapshotRef]:
        ...

    def list_snapshot_refs(
        self,
        case_id: str,
    ) -> List[AnalysisSnapshotRef]:
        ...


class LegalBriefRepository(Protocol):
    """Persistent metadata/audit boundary for encrypted legal briefs."""

    def save_brief(
        self,
        brief: LegalBriefRef,
        event: CaseEvent,
    ) -> None:
        ...

    def get_brief_ref(
        self,
        legal_brief_id: str,
    ) -> Optional[LegalBriefRef]:
        ...

    def list_brief_refs(
        self,
        snapshot_id: str,
    ) -> List[LegalBriefRef]:
        ...


class FilingRepository(Protocol):
    """Persistent filing metadata and atomic case/document/audit boundary."""

    def save_filing(
        self,
        filing: FilingRecord,
        filed_document: StoredDocumentRef,
        acknowledgement_document: Optional[StoredDocumentRef],
        updated_case: CaseRecord,
        events: List[CaseEvent],
    ) -> None:
        ...

    def get_filing(
        self,
        filing_id: str,
    ) -> Optional[FilingRecord]:
        ...

    def list_filings(
        self,
        case_id: str,
    ) -> List[FilingRecord]:
        ...

    def attach_acknowledgement(
        self,
        filing: FilingRecord,
        acknowledgement_document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        ...


class DraftVersionRepository(Protocol):
    """Persistent metadata/audit boundary for encrypted draft versions."""

    def save_version(
        self,
        version: DraftVersionRef,
        event: CaseEvent,
    ) -> None:
        ...

    def get_version_ref(
        self,
        draft_version_id: str,
    ) -> Optional[DraftVersionRef]:
        ...

    def list_version_refs(
        self,
        case_id: str,
    ) -> List[DraftVersionRef]:
        ...

    def transition_review_status(
        self,
        version: DraftVersionRef,
        event: CaseEvent,
    ) -> None:
        ...


class EvidenceReviewRepository(Protocol):
    """Persistent metadata/audit boundary for encrypted evidence reviews."""

    def save_review(
        self,
        review: EvidenceReviewRef,
        event: CaseEvent,
    ) -> None:
        ...

    def get_review_ref(
        self,
        review_id: str,
    ) -> Optional[EvidenceReviewRef]:
        ...

    def list_review_refs(
        self,
        snapshot_id: str,
    ) -> List[EvidenceReviewRef]:
        ...


class FactReviewRepository(Protocol):
    """Persistent metadata/audit boundary for encrypted fact reviews."""

    def save_review(
        self,
        review: FactReviewRef,
        event: CaseEvent,
    ) -> None:
        ...

    def get_review_ref(
        self,
        review_id: str,
    ) -> Optional[FactReviewRef]:
        ...

    def list_review_refs(
        self,
        snapshot_id: str,
    ) -> List[FactReviewRef]:
        ...


class AccessGrantRepository(Protocol):
    """Persistent firm-access grant lookup boundary."""

    def save_grant(self, grant: FirmAccessGrant) -> None:
        ...

    def get_grant(
        self,
        user_id: str,
        firm_id: str,
    ) -> Optional[FirmAccessGrant]:
        ...

    def list_grants_for_user(
        self,
        user_id: str,
    ) -> List[FirmAccessGrant]:
        ...

    def list_grants_for_firm(
        self,
        firm_id: str,
    ) -> List[FirmAccessGrant]:
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
