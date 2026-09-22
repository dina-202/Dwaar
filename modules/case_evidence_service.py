"""Authorized persisted supporting-evidence workspace helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence, Tuple

from domain.auth_models import AuthenticatedPrincipal
from domain.case_models import CaseDocumentKind, StoredDocumentRef
from domain.models import (
    EvidenceDocument,
    EvidenceIntakeResult,
    EvidenceChecklistItem,
)
from modules.authorized_case_service import AuthorizedCaseService
from domain.evidence_engine import propose_evidence_candidates
from modules.pdf_reader import extract_document_pages


@dataclass(frozen=True)
class PersistedEvidenceWorkspace:
    """Persisted supporting docs plus a fresh candidate-matching result."""

    document_refs: List[StoredDocumentRef]
    evidence_documents: List[EvidenceDocument]
    intake_result: EvidenceIntakeResult


def add_supporting_evidence_pdfs(
    service: AuthorizedCaseService,
    principal: AuthenticatedPrincipal,
    firm_id: str,
    *,
    case_id: str,
    files: Sequence[Tuple[str, bytes]],
    created_at: datetime,
) -> List[StoredDocumentRef]:
    """Persist supporting PDFs one-by-one through authorized document storage."""
    if not isinstance(files, Sequence) or not files:
        raise ValueError("files must contain at least one supporting PDF")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")

    persisted: List[StoredDocumentRef] = []
    for filename, payload in files:
        persisted.append(
            service.add_pdf_document(
                principal,
                firm_id,
                case_id=case_id,
                kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
                original_filename=filename,
                payload=payload,
                created_at=created_at,
            )
        )
    return persisted


def load_supporting_evidence_documents(
    service: AuthorizedCaseService,
    principal: AuthenticatedPrincipal,
    firm_id: str,
    *,
    case_id: str,
) -> tuple[List[StoredDocumentRef], List[EvidenceDocument]]:
    """Load/decrypt persisted supporting evidence and recover page provenance."""
    refs = [
        item
        for item in service.list_documents(
            principal,
            firm_id,
            case_id=case_id,
        )
        if item.kind is CaseDocumentKind.SUPPORTING_EVIDENCE
    ]

    evidence_documents: List[EvidenceDocument] = []
    for ref in refs:
        loaded_ref, payload = service.read_document(
            principal,
            firm_id,
            case_id=case_id,
            document_id=ref.document_id,
        )
        if loaded_ref != ref:
            raise RuntimeError(
                "supporting evidence metadata changed during load"
            )
        try:
            pages = extract_document_pages(payload)
        except Exception as error:
            raise RuntimeError(
                "supporting evidence PDF could not be parsed"
            ) from error

        evidence_documents.append(
            EvidenceDocument(
                document_id=ref.document_id,
                filename=ref.original_filename,
                pages=pages,
            )
        )

    return refs, evidence_documents


def analyze_persisted_evidence(
    service: AuthorizedCaseService,
    principal: AuthenticatedPrincipal,
    firm_id: str,
    *,
    case_id: str,
    evidence_checklist: List[EvidenceChecklistItem],
) -> PersistedEvidenceWorkspace:
    """Run candidate matching against only persisted case evidence documents."""
    refs, documents = load_supporting_evidence_documents(
        service,
        principal,
        firm_id,
        case_id=case_id,
    )
    intake_result = propose_evidence_candidates(
        evidence_checklist,
        documents,
    )
    return PersistedEvidenceWorkspace(
        document_refs=refs,
        evidence_documents=documents,
        intake_result=intake_result,
    )
