"""Tenant-safe authorization boundary for analysis snapshot history."""

from __future__ import annotations

from datetime import datetime
from typing import List

from domain.analysis_snapshot_models import (
    AnalysisSnapshotRef,
    LoadedAnalysisSnapshot,
)
from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.case_models import CaseDocumentKind, StoredDocumentRef
from domain.models import Phase2AnalysisResult
from domain.persistence_ports import (
    AccessGrantRepository,
    AnalysisSnapshotRepository,
    DocumentStore,
)
from domain.authorization import require_firm_permission
from modules.analysis_snapshot_service import (
    list_analysis_snapshot_refs,
    load_analysis_snapshot,
    persist_analysis_snapshot,
)
from modules.authorized_case_service import AuthorizedCaseService


class AuthorizedAnalysisSnapshotService:
    """Authorized case-bound save/list/load operations for snapshots."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        access_repository: AccessGrantRepository,
        snapshot_repository: AnalysisSnapshotRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_service
        self._access = access_repository
        self._snapshots = snapshot_repository
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

    def _notice_document(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        case_id: str,
    ) -> StoredDocumentRef:
        documents = self._cases.list_documents(
            principal,
            firm_id,
            case_id=case_id,
        )
        notices = [
            document
            for document in documents
            if document.kind is CaseDocumentKind.NOTICE
        ]
        if len(notices) != 1:
            raise LookupError(
                "case must contain exactly one notice document"
            )
        return notices[0]

    def save_current_analysis(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        analysis: Phase2AnalysisResult,
        created_at: datetime,
    ) -> AnalysisSnapshotRef:
        # Reading the case and source document are separately authorized,
        # then CASE_UPDATE authorizes changing durable case analysis history.
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        notice = self._notice_document(
            principal,
            firm_id,
            case.case_id,
        )
        self._require(
            principal,
            firm_id,
            AccessPermission.CASE_UPDATE,
        )
        return persist_analysis_snapshot(
            self._snapshots,
            self._documents,
            case_id=case.case_id,
            source_document=notice,
            analysis=analysis,
            actor_id=principal.user_id,
            created_at=created_at,
        )

    def list_snapshot_history(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ) -> List[AnalysisSnapshotRef]:
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        return list_analysis_snapshot_refs(
            self._snapshots,
            case_id=case.case_id,
        )

    def load_snapshot(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> LoadedAnalysisSnapshot:
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        notice = self._notice_document(
            principal,
            firm_id,
            case.case_id,
        )

        snapshot = self._snapshots.get_snapshot_ref(snapshot_id)
        if snapshot is None or snapshot.case_id != case.case_id:
            raise LookupError("analysis snapshot does not exist")

        return load_analysis_snapshot(
            self._snapshots,
            self._documents,
            snapshot_id=snapshot.snapshot_id,
            expected_source_document=notice,
        )
