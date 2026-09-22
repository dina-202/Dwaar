"""Authorized durable draft work-product service for Dwaar Phase 3K."""

from __future__ import annotations

from datetime import datetime
from typing import List

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.authorization import require_firm_permission
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
    LoadedDraftVersion,
)
from domain.persistence_ports import (
    AccessGrantRepository,
    DocumentStore,
    DraftVersionRepository,
)
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.draft_work_product_service import (
    baseline_text_from_snapshot,
    list_draft_versions,
    load_draft_version,
    persist_draft_version,
    transition_draft_review_status,
)


class AuthorizedDraftWorkProductService:
    """Tenant-safe immutable draft versions and controlled review state."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        snapshot_service: AuthorizedAnalysisSnapshotService,
        access_repository: AccessGrantRepository,
        draft_repository: DraftVersionRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._access = access_repository
        self._drafts = draft_repository
        self._documents = document_store

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
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        return case

    def list_versions(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ) -> List[DraftVersionRef]:
        case = self._case(principal, firm_id, case_id)
        return list_draft_versions(
            self._drafts,
            case_id=case.case_id,
        )

    def load_version(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        draft_version_id: str,
    ) -> LoadedDraftVersion:
        case = self._case(principal, firm_id, case_id)
        self._require(
            principal,
            firm_id,
            AccessPermission.DOCUMENT_READ,
        )
        ref = self._drafts.get_version_ref(draft_version_id)
        if ref is None or ref.case_id != case.case_id:
            raise LookupError("draft version does not exist")
        return load_draft_version(
            self._drafts,
            self._documents,
            draft_version_id=ref.draft_version_id,
        )

    def create_generated_baseline(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
        created_at: datetime,
    ) -> DraftVersionRef:
        case = self._case(principal, firm_id, case_id)
        self._require(
            principal,
            firm_id,
            AccessPermission.CASE_UPDATE,
        )
        snapshot = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        draft_text = baseline_text_from_snapshot(snapshot)

        history = list_draft_versions(
            self._drafts,
            case_id=case.case_id,
        )
        if any(
            item.generated_baseline
            and item.source_snapshot_id == snapshot.metadata.snapshot_id
            for item in history
        ):
            raise ValueError(
                "this analysis snapshot already has a generated draft "
                "baseline"
            )
        version_number = (
            1 if not history else history[-1].version_number + 1
        )

        return persist_draft_version(
            self._drafts,
            self._documents,
            case_id=case.case_id,
            source_snapshot_id=snapshot.metadata.snapshot_id,
            parent_draft_version_id=None,
            version_number=version_number,
            generated_baseline=True,
            draft_text=draft_text,
            actor_id=principal.user_id,
            created_at=created_at,
        )

    def create_edited_version(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        parent_draft_version_id: str,
        draft_text: str,
        created_at: datetime,
    ) -> DraftVersionRef:
        case = self._case(principal, firm_id, case_id)
        self._require(
            principal,
            firm_id,
            AccessPermission.CASE_UPDATE,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.DOCUMENT_READ,
        )
        parent = self._drafts.get_version_ref(parent_draft_version_id)
        if parent is None or parent.case_id != case.case_id:
            raise LookupError("parent draft version does not exist")

        history = list_draft_versions(
            self._drafts,
            case_id=case.case_id,
        )
        if not history or history[-1].draft_version_id != parent.draft_version_id:
            raise ValueError(
                "edited draft must be based on the latest case draft version"
            )

        # Loading verifies the parent encrypted payload before lineage advances.
        load_draft_version(
            self._drafts,
            self._documents,
            draft_version_id=parent.draft_version_id,
        )

        return persist_draft_version(
            self._drafts,
            self._documents,
            case_id=case.case_id,
            source_snapshot_id=parent.source_snapshot_id,
            parent_draft_version_id=parent.draft_version_id,
            version_number=parent.version_number + 1,
            generated_baseline=False,
            draft_text=draft_text,
            actor_id=principal.user_id,
            created_at=created_at,
        )

    def transition_review(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        draft_version_id: str,
        target_status: DraftReviewStatus,
        occurred_at: datetime,
    ) -> DraftVersionRef:
        case = self._case(principal, firm_id, case_id)
        self._require(
            principal,
            firm_id,
            AccessPermission.DRAFT_REVIEW,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.DOCUMENT_READ,
        )
        version = self._drafts.get_version_ref(draft_version_id)
        if version is None or version.case_id != case.case_id:
            raise LookupError("draft version does not exist")

        # Review applies to verified immutable content, not only metadata.
        load_draft_version(
            self._drafts,
            self._documents,
            draft_version_id=version.draft_version_id,
        )
        return transition_draft_review_status(
            self._drafts,
            version=version,
            target_status=target_status,
            actor_id=principal.user_id,
            occurred_at=occurred_at,
        )
