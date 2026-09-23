"""Authorized read-only professional case cockpit for Phase 3O."""

from datetime import date
from typing import Optional

from domain.auth_models import AuthenticatedPrincipal
from domain.models import EvidenceReviewStatus
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
from modules.authorized_fact_review_service import (
    AuthorizedFactReviewService,
)
from modules.authorized_legal_brief_service import AuthorizedLegalBriefService
from modules.professional_queue import build_professional_case_queue
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
        fact_review_service: Optional[
            AuthorizedFactReviewService
        ] = None,
    ):
        self._cases = case_service
        self._snapshots = snapshot_service
        self._legal = legal_brief_service
        self._drafts = draft_service
        self._filings = filing_service
        self._evidence = evidence_review_service
        self._fact_reviews = fact_review_service

    def list_case_attention_queue(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        today: date,
    ):
        """Return the existing deadline-ordered queue enriched with attention."""
        work_items = self._cases.list_case_work_queue(
            principal,
            firm_id,
            today=today,
        )
        attentions = [
            self.get_case_attention(
                principal,
                firm_id,
                case_id=item.case_id,
            )
            for item in work_items
        ]
        return build_professional_case_queue(
            work_items,
            attentions,
        )

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
        specialist_workflow_available = True
        if snapshots:
            latest_snapshot = max(
                snapshots,
                key=lambda item: (item.created_at, item.snapshot_id),
            )
            loaded_snapshot = self._snapshots.load_snapshot(
                principal,
                firm_id,
                case_id=case.case_id,
                snapshot_id=latest_snapshot.snapshot_id,
            )
            classification = loaded_snapshot.payload.get("classification")
            support_level = (
                classification.get("support_level")
                if isinstance(classification, dict)
                else None
            )
            proceeding_type = (
                classification.get("proceeding_type")
                if isinstance(classification, dict)
                else None
            )
            if support_level in {"triage_only", "unknown"}:
                specialist_workflow_available = False

            if specialist_workflow_available:
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
        triage_evidence_review_pending = False
        notice_evidence_review_pending = False
        fact_review_rejected = False
        if latest_snapshot is not None and self._evidence is not None:
            if specialist_workflow_available:
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
                    # Historical specialist checklist contract drift.
                    evidence_contract_drift = True

                if proceeding_type == "gst_sec61_scrutiny":
                    try:
                        notice_checklist = (
                            self._evidence.snapshot_evidence_checklist(
                                principal,
                                firm_id,
                                case_id=case.case_id,
                                snapshot_id=latest_snapshot.snapshot_id,
                            )
                        )
                        notice_reviews = self._evidence.list_reviews(
                            principal,
                            firm_id,
                            case_id=case.case_id,
                            snapshot_id=latest_snapshot.snapshot_id,
                        )
                    except (PermissionError, ValueError):
                        # CASE_READ does not imply evidence-review access,
                        # and malformed historical evidence context fails
                        # closed without creating a false completion signal.
                        notice_checklist = []
                        notice_reviews = []

                    confirmed_notice_ids = {
                        item.evidence_id
                        for item in notice_reviews
                        if item.decision is EvidenceReviewStatus.CONFIRMED
                    }
                    notice_evidence_review_pending = any(
                        item.evidence_id.startswith(
                            "sec61_scrutiny.notice."
                        )
                        and item.evidence_id not in confirmed_notice_ids
                        for item in notice_checklist
                    )
            else:
                try:
                    triage_checklist = (
                        self._evidence.snapshot_evidence_checklist(
                            principal,
                            firm_id,
                            case_id=case.case_id,
                            snapshot_id=latest_snapshot.snapshot_id,
                        )
                    )
                    triage_reviews = self._evidence.list_reviews(
                        principal,
                        firm_id,
                        case_id=case.case_id,
                        snapshot_id=latest_snapshot.snapshot_id,
                    )
                except (PermissionError, ValueError):
                    # Do not weaken EVIDENCE_REVIEW permissions and do not
                    # turn historical contract problems into legal claims.
                    triage_checklist = []
                    triage_reviews = []

                confirmed_ids = {
                    item.evidence_id
                    for item in triage_reviews
                    if item.decision is EvidenceReviewStatus.CONFIRMED
                }
                triage_evidence_review_pending = any(
                    item.evidence_id not in confirmed_ids
                    for item in triage_checklist
                )

        if latest_snapshot is not None and self._fact_reviews is not None:
            try:
                fact_review_rejected = bool(
                    self._fact_reviews.rejected_fact_ids(
                        principal,
                        firm_id,
                        case_id=case.case_id,
                        snapshot_id=latest_snapshot.snapshot_id,
                    )
                )
            except PermissionError:
                # CASE_READ must not imply FACT_REVIEW visibility.
                fact_review_rejected = False

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
            specialist_workflow_available=specialist_workflow_available,
            triage_evidence_review_pending=triage_evidence_review_pending,
            notice_evidence_review_pending=notice_evidence_review_pending,
            fact_review_rejected=fact_review_rejected,
        )
