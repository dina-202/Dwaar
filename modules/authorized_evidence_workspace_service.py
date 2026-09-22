"""Tenant-safe authorization boundary for persisted evidence workspace."""

from __future__ import annotations

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.models import EvidenceChecklistItem
from domain.persistence_ports import AccessGrantRepository
from domain.authorization import require_firm_permission
from modules.authorized_case_service import AuthorizedCaseService
from modules.case_evidence_service import (
    PersistedEvidenceWorkspace,
    analyze_persisted_evidence,
)


class AuthorizedEvidenceWorkspaceService:
    """Authorized evidence-candidate analysis over persisted case documents."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        access_repository: AccessGrantRepository,
    ):
        self._cases = case_service
        self._access = access_repository

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

    def analyze_case_evidence(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        evidence_checklist: list[EvidenceChecklistItem],
    ) -> PersistedEvidenceWorkspace:
        self._require_review(principal, firm_id)
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        return analyze_persisted_evidence(
            self._cases,
            principal,
            firm_id,
            case_id=case.case_id,
            evidence_checklist=evidence_checklist,
        )
