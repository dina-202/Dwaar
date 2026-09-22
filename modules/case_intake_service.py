"""Durable first-case intake coordination for Dwaar Phase 3F.1."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime
from pathlib import PurePath
from typing import Optional

import fitz

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    StoredDocumentRef,
    TaxRegistration,
)
from domain.models import NoticeForm, ProceedingType
from domain.persistence_ports import CaseRepository, DocumentStore
from modules.encrypted_document_store import generate_storage_key


_GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
)


class CaseIntakePersistenceError(RuntimeError):
    """Durable intake failed and encrypted bytes were rolled back."""


class CaseIntakeConsistencyError(CaseIntakePersistenceError):
    """Database failed and encrypted-object rollback also failed."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _display_text(value: str, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field} is too long")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _filename(value: str) -> str:
    normalized = _display_text(value, "notice_filename", 255)
    if "/" in normalized or "\\" in normalized:
        raise ValueError("notice_filename must not contain path separators")
    name = PurePath(normalized).name
    if name != normalized or not name.lower().endswith(".pdf"):
        raise ValueError("notice_filename must be a plain .pdf filename")
    return name


def _gstin(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("gstin must be a string or None")
    normalized = value.strip().upper()
    if not normalized:
        return None
    if not _GSTIN_PATTERN.fullmatch(normalized):
        raise ValueError(
            "gstin must match the standard 15-character GSTIN structure"
        )
    return normalized


def _validate_pdf(payload: bytes) -> None:
    if not isinstance(payload, bytes):
        raise TypeError("notice_payload must be bytes")
    if not payload:
        raise ValueError("notice_payload must not be empty")
    if not payload.startswith(b"%PDF-"):
        raise ValueError("notice_payload is not a PDF")

    document = None
    try:
        document = fitz.open(stream=payload, filetype="pdf")
        if document.needs_pass:
            raise ValueError("password-protected PDFs are not supported")
        if document.page_count < 1:
            raise ValueError("notice PDF must contain at least one page")
        document.load_page(0)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("notice_payload is not a readable PDF") from error
    finally:
        if document is not None:
            document.close()


def persist_new_case_intake(
    repository: CaseRepository,
    document_store: DocumentStore,
    *,
    firm_id: str,
    client_name: str,
    gstin: Optional[str],
    case_title: str,
    proceeding_type: ProceedingType,
    notice_form: NoticeForm,
    response_deadline: Optional[date],
    notice_filename: str,
    notice_payload: bytes,
    actor_id: str,
    opened_at: datetime,
) -> CaseRecord:
    """Persist a new client + intake case + encrypted notice atomically."""
    if not isinstance(firm_id, str) or not firm_id.strip():
        raise ValueError("firm_id must be a non-empty string")
    if repository.get_firm(firm_id) is None:
        raise LookupError("firm does not exist")
    if not isinstance(proceeding_type, ProceedingType):
        raise TypeError("proceeding_type must be a ProceedingType")
    if not isinstance(notice_form, NoticeForm):
        raise TypeError("notice_form must be a NoticeForm")
    if response_deadline is not None and not isinstance(
        response_deadline, date
    ):
        raise TypeError("response_deadline must be a date or None")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be a non-empty string")
    if not isinstance(opened_at, datetime) or opened_at.tzinfo is None:
        raise ValueError("opened_at must be timezone-aware")

    normalized_client_name = _display_text(
        client_name, "client_name", 200
    )
    normalized_case_title = _display_text(
        case_title, "case_title", 250
    )
    normalized_filename = _filename(notice_filename)
    normalized_gstin = _gstin(gstin)
    _validate_pdf(notice_payload)

    client = Client(
        client_id=_id("CLIENT"),
        firm_id=firm_id,
        display_name=normalized_client_name,
        created_at=opened_at,
    )
    registration = (
        None
        if normalized_gstin is None
        else TaxRegistration(
            registration_id=_id("REG"),
            client_id=client.client_id,
            jurisdiction="IN-GST",
            identifier_type="GSTIN",
            identifier_value=normalized_gstin,
            created_at=opened_at,
        )
    )
    case = CaseRecord(
        case_id=_id("CASE"),
        firm_id=firm_id,
        client_id=client.client_id,
        registration_id=(
            None
            if registration is None
            else registration.registration_id
        ),
        title=normalized_case_title,
        status=CaseStatus.INTAKE,
        proceeding_type=proceeding_type,
        notice_form=notice_form,
        opened_at=opened_at,
        response_deadline=response_deadline,
    )

    storage_key = generate_storage_key()
    sha256_hex = hashlib.sha256(notice_payload).hexdigest()
    document = StoredDocumentRef(
        document_id=_id("DOC"),
        case_id=case.case_id,
        kind=CaseDocumentKind.NOTICE,
        original_filename=normalized_filename,
        media_type="application/pdf",
        byte_size=len(notice_payload),
        sha256_hex=sha256_hex,
        storage_key=storage_key,
        created_at=opened_at,
    )
    events = [
        CaseEvent(
            event_id=_id("EV"),
            case_id=case.case_id,
            event_type=CaseEventType.CASE_CREATED,
            occurred_at=opened_at,
            actor_id=actor_id,
            payload={
                "status": CaseStatus.INTAKE.value,
                "client_id": client.client_id,
                "proceeding_type": proceeding_type.value,
                "notice_form": notice_form.value,
            },
        ),
        CaseEvent(
            event_id=_id("EV"),
            case_id=case.case_id,
            event_type=CaseEventType.DOCUMENT_ADDED,
            occurred_at=opened_at,
            actor_id=actor_id,
            payload={
                "document_id": document.document_id,
                "kind": document.kind.value,
                "byte_size": str(document.byte_size),
                "sha256": sha256_hex,
            },
        ),
    ]

    document_store.put(storage_key, notice_payload)
    try:
        repository.create_case_intake(
            client,
            registration,
            case,
            document,
            events,
        )
    except Exception as persistence_error:
        try:
            document_store.delete(storage_key)
        except Exception as rollback_error:
            raise CaseIntakeConsistencyError(
                "Case intake metadata failed and encrypted notice rollback "
                "also failed."
            ) from rollback_error
        raise CaseIntakePersistenceError(
            "Case intake metadata failed; encrypted notice was rolled back."
        ) from persistence_error

    return case
