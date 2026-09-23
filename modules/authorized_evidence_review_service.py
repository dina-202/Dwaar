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
from domain.legal_evidence_models import LegalEvidenceReadiness
from domain.models import (
    EvidenceCandidate,
    EvidenceChecklistItem,
    EvidenceReviewStatus,
    EvidenceStatus,
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
from workflows.gst.legal_evidence import (
    GST_LEGAL_EVIDENCE_REQUIREMENTS,
    build_legal_evidence_readiness,
)


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
    def _specialist_snapshot_evidence_checklist(
        payload: dict,
    ) -> List[EvidenceChecklistItem]:
        draft = payload.get("draft")
        if not isinstance(draft, dict):
            raise ValueError("snapshot draft section is invalid")
        raw_checklist = draft.get("evidence_checklist")
        if not isinstance(raw_checklist, list):
            raise ValueError("snapshot evidence checklist is invalid")

        checklist: List[EvidenceChecklistItem] = []
        seen = set()
        for item in raw_checklist:
            if not isinstance(item, dict) or set(item) != {
                "evidence_id",
                "requirement_text",
                "status",
            }:
                raise ValueError(
                    "snapshot evidence checklist item is invalid"
                )
            evidence_id = item["evidence_id"]
            requirement_text = item["requirement_text"]
            if (
                not isinstance(evidence_id, str)
                or not evidence_id
                or evidence_id in seen
                or not isinstance(requirement_text, str)
                or not requirement_text
            ):
                raise ValueError(
                    "snapshot evidence checklist item is invalid"
                )
            try:
                status = EvidenceStatus(item["status"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "snapshot evidence checklist status is invalid"
                ) from error
            seen.add(evidence_id)
            checklist.append(
                EvidenceChecklistItem(
                    evidence_id=evidence_id,
                    requirement_text=requirement_text,
                    status=status,
                )
            )
        return checklist

    @staticmethod
    def _notice_grounded_evidence_targets(
        payload: dict,
        *,
        requested_ids,
        annexure_ids,
        evidence_namespace: str,
    ) -> List[EvidenceChecklistItem]:
        """Resolve saved notice-selected evidence facts without inference.

        The caller supplies only fact IDs already selected by deterministic
        preflight/triage. Exact confirmed source_text becomes the review target;
        model-authored claims are never used.
        """
        extraction = payload.get("extraction")
        if not isinstance(extraction, dict):
            raise ValueError("snapshot evidence context is invalid")
        facts = extraction.get("facts")
        if not isinstance(facts, list):
            raise ValueError("snapshot evidence context is invalid")
        if (
            not isinstance(requested_ids, list)
            or not isinstance(annexure_ids, list)
            or any(
                not isinstance(value, str) or not value
                for value in requested_ids
            )
            or any(
                not isinstance(value, str) or not value
                for value in annexure_ids
            )
            or len(requested_ids) != len(set(requested_ids))
            or len(annexure_ids) != len(set(annexure_ids))
        ):
            raise ValueError("snapshot evidence references are invalid")

        requested = set(requested_ids)
        annexures = set(annexure_ids)
        target_ids = requested | annexures
        if not target_ids:
            return []

        checklist: List[EvidenceChecklistItem] = []
        resolved = set()
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fact_id = fact.get("fact_id")
            if fact_id not in target_ids:
                continue
            if fact_id in resolved:
                raise ValueError(
                    "snapshot evidence reference is ambiguous"
                )

            fact_type = fact.get("fact_type")
            if fact_id in requested:
                expected_type = "requested_document"
                evidence_kind = "requested_document"
                text_prefix = "Department-requested record: "
            else:
                expected_type = "referenced_annexure"
                evidence_kind = "referenced_annexure"
                text_prefix = "Notice-referenced annexure: "

            source_text = fact.get("source_text")
            if (
                fact_type != expected_type
                or fact.get("status") != "confirmed"
                or not isinstance(source_text, str)
                or not source_text.strip()
            ):
                raise ValueError(
                    "snapshot evidence reference is invalid"
                )

            resolved.add(fact_id)
            checklist.append(
                EvidenceChecklistItem(
                    evidence_id=(
                        f"{evidence_namespace}.{evidence_kind}.{fact_id}"
                    ),
                    requirement_text=text_prefix + source_text,
                    status=EvidenceStatus.UNKNOWN,
                )
            )

        if resolved != target_ids:
            raise ValueError("snapshot evidence reference is unresolved")
        return checklist

    @classmethod
    def _triage_snapshot_evidence_checklist(
        cls,
        payload: dict,
    ) -> List[EvidenceChecklistItem]:
        classification = payload.get("classification")
        if (
            not isinstance(classification, dict)
            or classification.get("support_level") != "triage_only"
        ):
            return []

        triage = payload.get("triage_summary")
        if not isinstance(triage, dict):
            raise ValueError("triage snapshot evidence context is invalid")

        requested_ids = triage.get("requested_document_fact_ids")
        annexure_ids = triage.get("referenced_annexure_fact_ids")
        try:
            return cls._notice_grounded_evidence_targets(
                payload,
                requested_ids=requested_ids,
                annexure_ids=annexure_ids,
                evidence_namespace="triage",
            )
        except ValueError as error:
            raise ValueError(
                str(error).replace(
                    "snapshot evidence", "triage snapshot evidence"
                )
            ) from error

    @classmethod
    def _section61_operational_evidence_checklist(
        cls,
        payload: dict,
    ) -> List[EvidenceChecklistItem]:
        """Preserve per-record ASMT-10 evidence targets after deep promotion."""
        classification = payload.get("classification")
        if not isinstance(classification, dict):
            return []
        if (
            classification.get("support_level") != "deep_workflow"
            or classification.get("proceeding_type")
            != "gst_sec61_scrutiny"
        ):
            return []

        preflight = payload.get("preflight")
        if not isinstance(preflight, dict):
            raise ValueError(
                "Section 61 snapshot evidence context is invalid"
            )
        requested_ids = preflight.get("requested_document_fact_ids")
        annexure_ids = preflight.get("referenced_annexure_fact_ids")
        try:
            return cls._notice_grounded_evidence_targets(
                payload,
                requested_ids=requested_ids,
                annexure_ids=annexure_ids,
                evidence_namespace="sec61_scrutiny.notice",
            )
        except ValueError as error:
            raise ValueError(
                "Section 61 " + str(error)
            ) from error

    @classmethod
    def _snapshot_evidence_checklist_from_payload(
        cls,
        payload: dict,
    ) -> List[EvidenceChecklistItem]:
        specialist = cls._specialist_snapshot_evidence_checklist(payload)
        section61_operational = (
            cls._section61_operational_evidence_checklist(payload)
        )
        if specialist:
            specialist_ids = {item.evidence_id for item in specialist}
            if any(
                item.evidence_id in specialist_ids
                for item in section61_operational
            ):
                raise ValueError(
                    "snapshot evidence checklist IDs are ambiguous"
                )
            return specialist + section61_operational
        return cls._triage_snapshot_evidence_checklist(payload)

    @classmethod
    def _snapshot_evidence_ids(cls, payload: dict) -> set[str]:
        return {
            item.evidence_id
            for item in cls._snapshot_evidence_checklist_from_payload(payload)
        }

    def snapshot_evidence_checklist(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> List[EvidenceChecklistItem]:
        """Return the selected historical snapshot's closed evidence list."""
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
        return self._snapshot_evidence_checklist_from_payload(
            snapshot.payload
        )

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

    def legal_evidence_readiness(
        self,
        principal: AuthenticatedPrincipal,
        firm_id: str,
        *,
        case_id: str,
        snapshot_id: str,
    ) -> List[LegalEvidenceReadiness]:
        """Return snapshot-scoped legal evidence readiness.

        The projection uses only persisted human review metadata. Closed
        legal evidence IDs must also exist in the selected snapshot's
        historical evidence checklist; architecture drift fails closed.
        """
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

        required_ids = {
            evidence_id
            for requirement in GST_LEGAL_EVIDENCE_REQUIREMENTS.get(
                case.proceeding_type, ()
            )
            for evidence_id in requirement.required_evidence_ids
        }
        snapshot_ids = self._snapshot_evidence_ids(snapshot.payload)
        if not required_ids.issubset(snapshot_ids):
            raise ValueError(
                "legal evidence requirements are not present in the "
                "selected analysis snapshot"
            )

        refs = list_evidence_review_refs(
            self._reviews,
            snapshot_id=snapshot.metadata.snapshot_id,
        )
        return list(
            build_legal_evidence_readiness(
                case.proceeding_type,
                snapshot_id=snapshot.metadata.snapshot_id,
                reviews=refs,
            )
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
