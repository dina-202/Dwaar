"""Authorized read-only professional case cockpit for Phase 3O."""

from typing import Optional

from domain.auth_models import AuthenticatedPrincipal
from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_draft_work_product_service import (
    AuthorizedDraftWorkProductService,
)
from modules.authorized_evidence_review_service import (
    AuthorizedEvidenceReviewService,
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
        evidence_review_service: Optional[
            AuthorizedEvidenceReviewService
        ] = None,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._legal = legal_brief_service
        self._drafts = draft_service
        self._filings = filing_service
        self._evidence = evidence_review_service

    def get_case_attention(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
    ):
        """Return tenant-safe operational attention for one case.

        Evidence-derived attention is included only when the principal is
        already authorized through the evidence-review service. Lack of that
        permission does not weaken evidence permissions or break CASE_READ
        cockpit access.
        """
        case = self._cases.get_case(principal, firm_id, case_id)
        if case is None:
            raise LookupError("case does not exist")

        snapshots = self._snapshots.list_snapshot_history(
            principal,
            firm_id,
            case_id=case.case_id,
        )
        loaded_briefs = []
        latest_snapshot = None
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

        evidence_readiness = []
        evidence_contract_drift = False
        if latest_snapshot is not None and self._evidence is not None:
            try:
                evidence_readiness = (
                    self._evidence.legal_evidence_readiness(
                        principal,
                        firm_id,
                        case_id=case.case_id,
                        snapshot_id=latest_snapshot.snapshot_id,
                    )
                )
            except PermissionError:
                # CASE_READ must not imply EVIDENCE_REVIEW access.
                evidence_readiness = []
            except ValueError:
                # The authorized evidence service uses ValueError for
                # historical closed-checklist contract drift.
                evidence_contract_drift = True

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
            legal_evidence_readiness=evidence_readiness,
            legal_evidence_contract_drift=evidence_contract_drift,
        )
