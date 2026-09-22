"""Pure-ish helpers for the temporary Streamlit evidence workspace.

No Streamlit dependency. This module converts uploaded supporting PDF bytes
into EvidenceDocument objects and computes a content-bound workspace key.
"""

import hashlib
from typing import Iterable, List, Sequence, Tuple

from domain.models import EvidenceDocument
from modules.pdf_reader import extract_document_pages


def notice_analysis_key(notice_pdf_bytes: bytes) -> str:
    """Return a deterministic key for one uploaded notice payload."""
    digest = hashlib.sha256()
    digest.update(b"DWAAR-NOTICE-ANALYSIS-V1\0")
    digest.update(notice_pdf_bytes)
    return digest.hexdigest()


def evidence_workspace_key(
    notice_pdf_bytes: bytes,
    supporting_files: Sequence[Tuple[str, bytes]],
    evidence_ids: Iterable[str],
) -> str:
    """Return a deterministic key bound to notice, files, order and checklist."""
    digest = hashlib.sha256()
    digest.update(b"DWAAR-EVIDENCE-WORKSPACE-V1\0")
    digest.update(notice_pdf_bytes)
    digest.update(b"\0CHECKLIST\0")
    for evidence_id in evidence_ids:
        digest.update(evidence_id.encode("utf-8"))
        digest.update(b"\0")
    digest.update(b"FILES\0")
    for filename, payload in supporting_files:
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def build_evidence_documents(
    supporting_files: Sequence[Tuple[str, bytes]],
) -> List[EvidenceDocument]:
    """Create ordered EvidenceDocument objects from uploaded PDF payloads."""
    documents: List[EvidenceDocument] = []
    for position, (filename, payload) in enumerate(supporting_files, start=1):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("supporting filename must be non-empty")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("supporting PDF payload must be non-empty bytes")
        documents.append(
            EvidenceDocument(
                document_id=f"D-{position:03d}",
                filename=filename,
                pages=extract_document_pages(payload),
            )
        )
    return documents
