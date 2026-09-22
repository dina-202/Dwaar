"""Coordinated persistence of case PDF bytes, metadata and audit event.

This service is the consistency boundary between DocumentStore and
CaseRepository. It validates PDF input, encrypts/stores bytes first, commits
metadata+audit atomically second, and compensates by deleting the encrypted
object if repository persistence fails.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

import fitz

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    StoredDocumentRef,
)
from domain.persistence_ports import CaseRepository, DocumentStore
from modules.encrypted_document_store import generate_storage_key


_MAX_FILENAME_CHARS = 255
_CONTROL_CHARS = frozenset(chr(code) for code in range(32))


class DocumentPersistenceError(RuntimeError):
    """Base error for coordinated document persistence failures."""


class DocumentValidationError(DocumentPersistenceError):
    """Uploaded payload is not an acceptable persistent PDF document."""


class DocumentPersistenceConsistencyError(DocumentPersistenceError):
    """Compensating cleanup failed after metadata transaction failure."""


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str):
        raise DocumentValidationError("filename must be a string")
    normalized = filename.strip()
    if not normalized:
        raise DocumentValidationError("filename must not be empty")
    if len(normalized) > _MAX_FILENAME_CHARS:
        raise DocumentValidationError("filename is too long")
    if "/" in normalized or "\\" in normalized:
        raise DocumentValidationError(
            "filename must not contain path separators"
        )
    if any(character in _CONTROL_CHARS for character in normalized):
        raise DocumentValidationError(
            "filename must not contain control characters"
        )
    if not normalized.lower().endswith(".pdf"):
        raise DocumentValidationError("only PDF documents are supported")
    return normalized


def _validate_pdf(payload: bytes) -> None:
    if not isinstance(payload, bytes):
        raise DocumentValidationError("document payload must be bytes")
    if not payload:
        raise DocumentValidationError("document payload must not be empty")
    if not payload.startswith(b"%PDF-"):
        raise DocumentValidationError(
            "document payload does not have a PDF signature"
        )

    doc = None
    try:
        doc = fitz.open(stream=payload, filetype="pdf")
        if getattr(doc, "needs_pass", False):
            raise DocumentValidationError(
                "password-protected PDFs are not supported"
            )
        if doc.page_count < 1:
            raise DocumentValidationError(
                "PDF must contain at least one page"
            )
        # Force at least the first page object to be resolved so obviously
        # corrupt xref/page structures fail before persistence.
        doc.load_page(0)
    except DocumentValidationError:
        raise
    except Exception as error:
        raise DocumentValidationError(
            "document payload could not be parsed as a PDF"
        ) from error
    finally:
        if doc is not None:
            doc.close()


def _new_document_id() -> str:
    return "DOC-" + uuid.uuid4().hex


def _new_event_id() -> str:
    return "EV-" + uuid.uuid4().hex


def persist_pdf_document(
    repository: CaseRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    kind: CaseDocumentKind,
    original_filename: str,
    payload: bytes,
    actor_id: Optional[str],
    created_at: datetime,
) -> StoredDocumentRef:
    """Persist one case PDF with compensated cross-store consistency.

    Success means:
      1. encrypted/object bytes exist;
      2. document metadata exists;
      3. DOCUMENT_ADDED audit event exists.

    If the repository transaction fails, the stored object is deleted. If
    that cleanup also fails, a consistency error is raised so operations can
    remediate the orphaned encrypted object explicitly.
    """
    if not isinstance(case_id, str) or not case_id.strip():
        raise DocumentValidationError("case_id must be non-empty")
    if not isinstance(kind, CaseDocumentKind):
        raise DocumentValidationError(
            "kind must be a CaseDocumentKind"
        )
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise DocumentValidationError(
            "created_at must be timezone-aware"
        )
    if actor_id is not None and (
        not isinstance(actor_id, str) or not actor_id.strip()
    ):
        raise DocumentValidationError(
            "actor_id must be a non-empty string or None"
        )

    filename = _validate_filename(original_filename)
    _validate_pdf(payload)

    # Fail before writing encrypted bytes when the target case is unknown.
    case = repository.get_case(case_id.strip())
    if case is None:
        raise DocumentValidationError("case does not exist")

    document_id = _new_document_id()
    event_id = _new_event_id()
    storage_key = generate_storage_key()
    sha256_hex = hashlib.sha256(payload).hexdigest()

    document = StoredDocumentRef(
        document_id=document_id,
        case_id=case.case_id,
        kind=kind,
        original_filename=filename,
        media_type="application/pdf",
        byte_size=len(payload),
        sha256_hex=sha256_hex,
        storage_key=storage_key,
        created_at=created_at,
    )
    event = CaseEvent(
        event_id=event_id,
        case_id=case.case_id,
        event_type=CaseEventType.DOCUMENT_ADDED,
        occurred_at=created_at,
        actor_id=actor_id.strip() if isinstance(actor_id, str) else None,
        payload={
            "document_id": document_id,
            "kind": kind.value,
            "sha256": sha256_hex,
            "byte_size": str(len(payload)),
        },
    )

    document_store.put(storage_key, payload)
    try:
        repository.add_document_with_event(document, event)
    except Exception as repository_error:
        try:
            document_store.delete(storage_key)
        except Exception as cleanup_error:
            raise DocumentPersistenceConsistencyError(
                "Document metadata persistence failed and encrypted-object "
                "rollback also failed; manual remediation is required."
            ) from cleanup_error
        raise DocumentPersistenceError(
            "Document metadata/audit persistence failed; encrypted object "
            "was rolled back."
        ) from repository_error

    return document
