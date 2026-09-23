"""Authorized filing and acknowledgement lifecycle for Dwaar Phase 3L."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.authorization import require_firm_permission
from domain.filing_models import FilingRecord
from domain.fact_review_models import (
    FactReviewDecision,
    latest_fact_reviews,
)
from domain.persistence_ports import (
    AccessGrantRepository,
    DocumentStore,
    DraftVersionRepository,
    FactReviewRepository,
    FilingRepository,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.filing_service import (
    attach_filing_acknowledgement,
    persist_filing,
)


class FilingSourceFactReviewBlockedError(ValueError):
    """Approved filing basis became unsafe after professional fact review."""


class AuthorizedFilingService:
    """Tenant-safe filing/acknowledgement application boundary."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        access_repository: AccessGrantRepository,
        filing_repository: FilingRepository,
        draft_repository: DraftVersionRepository,
        document_store: DocumentStore,
        fact_review_repository: Optional[FactReviewRepository] = None,
    ):
        self._cases = case_service
        self._access = access_repository
        self._filings = filing_repository
        self._drafts = draft_repository
        self._documents = document_store
        self._fact_reviews = fact_review_repository

    def _require(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        permission: AccessPermission,
    ) -> None:
        grant = self._access.get_grant(principal.user_id, firm_id)
        if grant is None:
            raise AuthorizationError("access denied")
        require_firm_permission(
            principal,
            grant,
            firm_id,
            permission,
        )

    def _case(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        case_id: str,
    ):
        case = self._cases.get_case(
            principal,
            firm_id,
            case_id,
        )
        if case is None:
            raise LookupError("case does not exist")
        return case

    def list_filings(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ) -> List[FilingRecord]:
        case = self._case(
            principal,
            firm_id,
            case_id,
        )
        return self._filings.list_filings(case.case_id)

    def record_filing(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        approved_draft_version_id: str,
        filing_reference: str,
        filed_response_filename: str,
        filed_response_payload: bytes,
        acknowledgement_filename: Optional[str],
        acknowledgement_payload: Optional[bytes],
        filed_at: datetime,
        recorded_at: datetime,
    ) -> FilingRecord:
        case = self._case(
            principal,
            firm_id,
            case_id,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.FILING_RECORD,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.DOCUMENT_ADD,
        )

        if self._fact_reviews is not None:
            draft = self._drafts.get_version_ref(
                approved_draft_version_id
            )
            if draft is not None and draft.case_id == case.case_id:
                latest_reviews = latest_fact_reviews(
                    self._fact_reviews.list_review_refs(
                        draft.source_snapshot_id
                    )
                )
                if any(
                    review.decision is FactReviewDecision.REJECTED
                    for review in latest_reviews.values()
                ):
                    raise FilingSourceFactReviewBlockedError(
                        "filing is blocked because the approved draft's "
                        "source analysis contains a professionally rejected "
                        "extracted fact"
                    )

        return persist_filing(
            self._filings,
            self._drafts,
            self._documents,
            case=case,
            approved_draft_version_id=approved_draft_version_id,
            filing_reference=filing_reference,
            filed_response_filename=filed_response_filename,
            filed_response_payload=filed_response_payload,
            acknowledgement_filename=acknowledgement_filename,
            acknowledgement_payload=acknowledgement_payload,
            filed_at=filed_at,
            recorded_at=recorded_at,
            actor_id=principal.user_id,
        )

    def attach_acknowledgement(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        filing_id: str,
        acknowledgement_filename: str,
        acknowledgement_payload: bytes,
        added_at: datetime,
    ) -> FilingRecord:
        case = self._case(
            principal,
            firm_id,
            case_id,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.FILING_RECORD,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.DOCUMENT_ADD,
        )

        filing = self._filings.get_filing(filing_id)
        if filing is None or filing.case_id != case.case_id:
            raise LookupError("filing does not exist")

        return attach_filing_acknowledgement(
            self._filings,
            self._documents,
            filing=filing,
            acknowledgement_filename=acknowledgement_filename,
            acknowledgement_payload=acknowledgement_payload,
            actor_id=principal.user_id,
            added_at=added_at,
        )
