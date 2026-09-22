"""Authorized snapshot-bound evidence review service."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.authorization import require_firm_permission
from domain.case_models import CaseDocumentKind
from domain.evidence_review_models import (
    EvidenceReviewRef,
    LoadedEvidenceReview,
)
from domain.models import (
    EvidenceCandidate,
    EvidenceReviewStatus,
)
from domain.persistence_ports import (
    AccessGrantRepository,
    DocumentStore,
    EvidenceReviewRepository,
)
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.evidence_review_persistence_service import (
    list_evidence_review_refs,
    load_evidence_review,
    persist_evidence_review,
)
from modules.pdf_reader import extract_document_pages


class AuthorizedEvidenceReviewService:
    """Tenant-safe human evidence decisions bound to saved analysis history."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        snapshot_service: AuthorizedAnalysisSnapshotService,
        access_repository: AccessGrantRepository,
        review_repository: EvidenceReviewRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._access = access_repository
        self._reviews = review_repository
        self._documents = document_store

    def _require_review(
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
            AccessPermission.EVIDENCE_REVIEW,
        )

    @staticmethod
    def _snapshot_evidence_ids(payload: dict) -> set[str]:
        draft = payload.get("draft")
        if not isinstance(draft, dict):
            return set()
        checklist = draft.get("evidence_checklist")
        if not isinstance(checklist, list):
            return set()
        return {
            item.get("evidence_id")
            for item in checklist
            if isinstance(item, dict)
            and isinstance(item.get("evidence_id"), str)
            and item.get("evidence_id")
        }

    def save_review(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
        candidate: EvidenceCandidate,
        decision: EvidenceReviewStatus,
        reviewer_note: Optional[str],
        reviewed_at: datetime,
    ) -> EvidenceReviewRef:
        self._require_review(principal, firm_id)
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")

        snapshot = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        if candidate.evidence_id not in self._snapshot_evidence_ids(
            snapshot.payload
        ):
            raise ValueError(
                "candidate evidence_id is not present in the selected "
                "analysis snapshot"
            )

        document, payload = self._cases.read_document(
            principal,
            firm_id,
            case_id=case.case_id,
            document_id=candidate.document_id,
        )
        if document.kind is not CaseDocumentKind.SUPPORTING_EVIDENCE:
            raise ValueError(
                "candidate document is not persisted supporting evidence"
            )

        try:
            pages = extract_document_pages(payload)
        except Exception as error:
            raise ValueError(
                "candidate supporting evidence could not be parsed"
            ) from error

        matches = [
            page
            for page in pages
            if page.page_number == candidate.source_page
            and candidate.source_text in page.text
        ]
        if len(matches) != 1:
            raise ValueError(
                "candidate source quote is not grounded on the persisted "
                "supporting evidence page"
            )
        source_page = matches[0]
        if source_page.origin is not candidate.source_origin:
            raise ValueError(
                "candidate source origin does not match persisted evidence"
            )
        if (
            source_page.verification
            is not candidate.source_verification
        ):
            raise ValueError(
                "candidate source verification does not match persisted "
                "evidence"
            )

        return persist_evidence_review(
            self._reviews,
            self._documents,
            case_id=case.case_id,
            snapshot_id=snapshot.metadata.snapshot_id,
            candidate=candidate,
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
    ) -> List[EvidenceReviewRef]:
        self._require_review(principal, firm_id)
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        snapshot = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        return list_evidence_review_refs(
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
    ) -> LoadedEvidenceReview:
        self._require_review(principal, firm_id)
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        snapshot = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        review = self._reviews.get_review_ref(review_id)
        if (
            review is None
            or review.case_id != case.case_id
            or review.snapshot_id != snapshot.metadata.snapshot_id
        ):
            raise LookupError("evidence review does not exist")
        return load_evidence_review(
            self._reviews,
            self._documents,
            review_id=review.review_id,
        )
