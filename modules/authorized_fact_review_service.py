"""Authorized snapshot-bound professional fact-review service."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.authorization import require_firm_permission
from domain.fact_review_models import (
    FactReviewDecision,
    FactReviewRef,
    LoadedFactReview,
)
from domain.persistence_ports import (
    AccessGrantRepository,
    DocumentStore,
    FactReviewRepository,
)
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.fact_review_persistence_service import (
    list_fact_review_refs,
    load_fact_review,
    persist_fact_review,
)


_REVIEW_FACT_KEYS = (
    "fact_id",
    "fact_type",
    "fact_role",
    "status",
    "source_text",
    "source_page",
    "source_origin",
    "source_verification",
    "allowed_in_draft",
)


class AuthorizedFactReviewService:
    """Tenant-safe professional decisions over immutable extracted facts."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        snapshot_service: AuthorizedAnalysisSnapshotService,
        access_repository: AccessGrantRepository,
        review_repository: FactReviewRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._access = access_repository
        self._reviews = review_repository
        self._documents = document_store

    def _require(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
    ) -> None:
        grant = self._access.get_grant(principal.user_id, firm_id)
        if grant is None:
            raise AuthorizationError("access denied")
        require_firm_permission(
            principal,
            grant,
            firm_id,
            AccessPermission.FACT_REVIEW,
        )

    @staticmethod
    def _facts_from_payload(payload: dict) -> List[Dict[str, object]]:
        extraction = payload.get("extraction")
        if not isinstance(extraction, dict):
            raise ValueError("analysis snapshot extraction is invalid")
        rows = extraction.get("facts")
        if not isinstance(rows, list):
            raise ValueError("analysis snapshot facts are invalid")

        facts = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("analysis snapshot fact is invalid")
            try:
                fact = {key: row[key] for key in _REVIEW_FACT_KEYS}
            except KeyError as error:
                raise ValueError("analysis snapshot fact is invalid") from error
            fact_id = fact["fact_id"]
            if (
                not isinstance(fact_id, str)
                or not fact_id
                or fact_id in seen
            ):
                raise ValueError("analysis snapshot fact identity is invalid")
            if not isinstance(fact["source_text"], str) or not fact[
                "source_text"
            ]:
                raise ValueError(
                    "analysis snapshot fact has no reviewable source text"
                )
            seen.add(fact_id)
            facts.append(fact)
        return facts

    def _snapshot(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ):
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        loaded = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        return case, loaded

    def list_reviewable_facts(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> List[Dict[str, object]]:
        _, snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case_id,
            snapshot_id=snapshot_id,
        )
        return self._facts_from_payload(snapshot.payload)

    def save_review(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
        fact_id: str,
        decision: FactReviewDecision,
        reviewer_note: Optional[str],
        reviewed_at: datetime,
    ) -> FactReviewRef:
        self._require(principal, firm_id)
        case, snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case_id,
            snapshot_id=snapshot_id,
        )
        matches = [
            fact
            for fact in self._facts_from_payload(snapshot.payload)
            if fact["fact_id"] == fact_id
        ]
        if len(matches) != 1:
            raise LookupError("fact does not exist in selected analysis")
        return persist_fact_review(
            self._reviews,
            self._documents,
            case_id=case.case_id,
            snapshot_id=snapshot.metadata.snapshot_id,
            fact=matches[0],
            decision=decision,
            reviewer_note=reviewer_note,
            actor_id=principal.user_id,
            reviewed_at=reviewed_at,
        )

    def list_reviews(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> List[FactReviewRef]:
        _, snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case_id,
            snapshot_id=snapshot_id,
        )
        return list_fact_review_refs(
            self._reviews,
            snapshot_id=snapshot.metadata.snapshot_id,
        )

    def load_review(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
        review_id: str,
    ) -> LoadedFactReview:
        _, snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case_id,
            snapshot_id=snapshot_id,
        )
        review = self._reviews.get_review_ref(review_id)
        if (
            review is None
            or review.case_id != case_id
            or review.snapshot_id != snapshot.metadata.snapshot_id
        ):
            raise LookupError("fact review does not exist")
        return load_fact_review(
            self._reviews,
            self._documents,
            review_id=review.review_id,
        )

    def rejected_fact_ids(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> set[str]:
        return {
            review.fact_id
            for review in self.list_reviews(
                principal,
                firm_id,
                case_id=case_id,
                snapshot_id=snapshot_id,
            )
            if review.decision is FactReviewDecision.REJECTED
        }
