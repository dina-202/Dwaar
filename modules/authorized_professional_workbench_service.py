"""Authorized read-only professional case cockpit for Phase 3O.2."""

from domain.auth_models import AuthenticatedPrincipal
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_draft_work_product_service import (
    AuthorizedDraftWorkProductService,
)
from modules.authorized_filing_service import AuthorizedFilingService
from modules.authorized_legal_brief_service import AuthorizedLegalBriefService
from modules.professional_workbench import build_professional_case_attention


class AuthorizedProfessionalWorkbenchService:
    def __init__(
        self,
        case_service: AuthorizedCaseService,
        snapshot_service: AuthorizedAnalysisSnapshotService,
        legal_brief_service: AuthorizedLegalBriefService,
        draft_service: AuthorizedDraftWorkProductService,
        filing_service: AuthorizedFilingService,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._legal = legal_brief_service
        self._drafts = draft_service
        self._filings = filing_service

    def get_case_attention(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ):
        """Return tenant-safe operational attention for one case."""
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")

        snapshots = self._snapshots.list_snapshot_history(
            principal,
            firm_id,
            case_id=case.case_id,
        )
        loaded_briefs = []
        if snapshots:
            latest_snapshot = max(
                snapshots,
                key=lambda item: (item.created_at, item.snapshot_id),
            )
            refs = self._legal.list_for_snapshot(
                principal,
                firm_id,
                case_id=case.case_id,
                snapshot_id=latest_snapshot.snapshot_id,
            )
            if refs:
                latest_ref = max(
                    refs,
                    key=lambda item: (
                        item.created_at,
                        item.legal_brief_id,
                    ),
                )
                loaded_briefs.append(
                    self._legal.load(
                        principal,
                        firm_id,
                        case_id=case.case_id,
                        legal_brief_id=latest_ref.legal_brief_id,
                    )
                )

        drafts = self._drafts.list_versions(
            principal,
            firm_id,
            case_id=case.case_id,
        )
        filings = self._filings.list_filings(
            principal,
            firm_id,
            case_id=case.case_id,
        )
        return build_professional_case_attention(
            case,
            snapshots=snapshots,
            legal_briefs=loaded_briefs,
            draft_versions=drafts,
            filings=filings,
        )
