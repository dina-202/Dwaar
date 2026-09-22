"""Authorized loading and reanalysis of one persisted intake case."""

from dataclasses import dataclass
from datetime import date

from domain.auth_models import AuthenticatedPrincipal
from domain.case_models import CaseDocumentKind, CaseRecord, StoredDocumentRef
from domain.models import Phase2AnalysisResult
from modules.authorized_case_service import AuthorizedCaseService
from modules.pdf_reader import extract_document_pages
from domain.phase2_orchestrator import run_phase2_analysis_from_document_pages


class SavedCaseReopenError(RuntimeError):
    """Persisted case cannot be safely reopened for notice analysis."""


@dataclass(frozen=True)
class ReopenedCaseAnalysis:
    case: CaseRecord
    notice_document: StoredDocumentRef
    notice_pdf_bytes: bytes
    analysis: Phase2AnalysisResult


def reopen_case_analysis(
    service: AuthorizedCaseService,
    principal: AuthenticatedPrincipal,
    firm_id: str,
    case_id: str,
    today: date,
) -> ReopenedCaseAnalysis:
    """Load one saved intake notice through authorization and reanalyze it."""
    case = service.get_case(principal, firm_id, case_id)
    if case is None:
        raise LookupError("case does not exist")

    documents = service.list_documents(
        principal,
        firm_id,
        case_id=case.case_id,
    )
    notice_documents = [
        document
        for document in documents
        if document.kind is CaseDocumentKind.NOTICE
    ]
    if len(notice_documents) != 1:
        raise SavedCaseReopenError(
            "saved case must contain exactly one notice document"
        )

    notice_document = notice_documents[0]
    loaded_document, pdf_bytes = service.read_document(
        principal,
        firm_id,
        case_id=case.case_id,
        document_id=notice_document.document_id,
    )
    if loaded_document != notice_document:
        raise SavedCaseReopenError(
            "notice document metadata changed during reopen"
        )

    try:
        document_pages = extract_document_pages(pdf_bytes)
    except Exception as error:
        raise SavedCaseReopenError(
            "saved notice could not be parsed"
        ) from error

    analysis = run_phase2_analysis_from_document_pages(
        document_pages,
        today,
    )
    return ReopenedCaseAnalysis(
        case=case,
        notice_document=notice_document,
        notice_pdf_bytes=pdf_bytes,
        analysis=analysis,
    )
