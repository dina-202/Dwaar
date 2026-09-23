"""Tenant-safe authorization boundary for snapshot-bound legal briefs."""

from __future__ import annotations

from datetime import datetime
from typing import List

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
)
from domain.authorization import require_firm_permission
from domain.legal_brief_models import LegalBriefRef, LoadedLegalBrief
from domain.legal_date_engine import build_legal_date_context
from domain.legal_date_models import LegalDateBasis
from domain.models import (
    DraftPermission,
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from domain.persistence_ports import (
    AccessGrantRepository,
    DocumentStore,
    LegalBriefRepository,
)
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.legal_brief_service import (
    list_legal_brief_refs,
    load_legal_brief,
    persist_legal_brief,
)
from workflows.gst.legal_research import resolve_gst_legal_brief_from_context



def _snapshot_facts(payload):
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict):
        raise ValueError("analysis snapshot extraction is invalid")
    rows = extraction.get("facts")
    if not isinstance(rows, list):
        raise ValueError("analysis snapshot facts are invalid")
    facts = []
    try:
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("analysis snapshot fact is invalid")
            facts.append(
                ExtractedFact(
                    fact_id=row["fact_id"],
                    claim=row["claim"],
                    status=FactStatus(row["status"]),
                    source_text=row["source_text"],
                    source_page=row["source_page"],
                    allowed_in_draft=DraftPermission(
                        row["allowed_in_draft"]
                    ),
                    fact_type=FactType(row["fact_type"]),
                    fact_role=FactRole(row["fact_role"]),
                    source_origin=SourceTextOrigin(row["source_origin"]),
                    source_verification=SourceVerificationStatus(
                        row["source_verification"]
                    ),
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("analysis snapshot fact is invalid") from error
    return facts


class AuthorizedLegalBriefService:
    """Authorized save/list/load for immutable legal research briefs."""

    def __init__(
        self,
        case_service: AuthorizedCaseService,
        snapshot_service: AuthorizedAnalysisSnapshotService,
        access_repository: AccessGrantRepository,
        brief_repository: LegalBriefRepository,
        document_store: DocumentStore,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._access = access_repository
        self._briefs = brief_repository
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

    def _snapshot(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> AnalysisSnapshotRef:
        history = self._snapshots.list_snapshot_history(
            principal,
            firm_id,
            case_id=case_id,
        )
        for snapshot in history:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise LookupError("analysis snapshot does not exist")

    def save_for_snapshot(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
        created_at: datetime,
    ) -> LegalBriefRef:
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        loaded = self._snapshots.load_snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot.snapshot_id,
        )
        classification = loaded.payload.get("classification")
        if not isinstance(classification, dict):
            raise ValueError("analysis snapshot classification is invalid")
        proceeding_text = classification.get("proceeding_type")
        if not isinstance(proceeding_text, str) or not proceeding_text:
            raise ValueError(
                "analysis snapshot has no proceeding type for legal research"
            )
        try:
            proceeding_type = ProceedingType(proceeding_text)
        except ValueError as error:
            raise ValueError(
                "analysis snapshot proceeding type is invalid"
            ) from error

        date_context = build_legal_date_context(
            _snapshot_facts(loaded.payload)
        )
        notice_anchor = date_context.get(LegalDateBasis.NOTICE_DATE)
        if notice_anchor is None:
            raise ValueError(
                "analysis snapshot has no unique verified notice date for "
                "legal brief metadata"
            )
        as_of_date = notice_anchor.effective_date

        # Saving durable professional history is a case mutation. The
        # snapshot read above is already CASE_READ-authorized.
        self._require(
            principal,
            firm_id,
            AccessPermission.CASE_UPDATE,
        )
        result = resolve_gst_legal_brief_from_context(
            proceeding_type,
            date_context,
        )
        return persist_legal_brief(
            self._briefs,
            self._documents,
            case_id=case.case_id,
            snapshot=snapshot,
            result=result,
            as_of_date=as_of_date,
            proceeding_type=proceeding_type,
            actor_id=principal.user_id,
            created_at=created_at,
        )

    def list_for_snapshot(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> List[LegalBriefRef]:
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=snapshot_id,
        )
        return list_legal_brief_refs(
            self._briefs,
            snapshot_id=snapshot.snapshot_id,
        )

    def load(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        legal_brief_id: str,
    ) -> LoadedLegalBrief:
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")
        brief = self._briefs.get_brief_ref(legal_brief_id)
        if brief is None or brief.case_id != case.case_id:
            raise LookupError("legal brief does not exist")
        snapshot = self._snapshot(
            principal,
            firm_id,
            case_id=case.case_id,
            snapshot_id=brief.snapshot_id,
        )
        return load_legal_brief(
            self._briefs,
            self._documents,
            legal_brief_id=brief.legal_brief_id,
            expected_snapshot=snapshot,
        )
