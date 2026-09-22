"""Coordinated filing/acknowledgement persistence for Dwaar Phase 3L."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Optional

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    StoredDocumentRef,
)
from domain.draft_work_product_models import DraftReviewStatus
from domain.filing_models import FilingRecord
from domain.persistence_ports import (
    DocumentStore,
    DraftVersionRepository,
    FilingRepository,
)
from modules.case_document_service import _validate_filename, _validate_pdf
from modules.draft_work_product_service import load_draft_version
from modules.encrypted_document_store import generate_storage_key


class FilingPersistenceError(RuntimeError):
    """Filing metadata failed and stored filing artifacts were rolled back."""


class FilingConsistencyError(FilingPersistenceError):
    """Filing metadata failed and one or more object rollbacks also failed."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _reference(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("filing_reference must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > 200:
        raise ValueError("filing_reference is too long")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError("filing_reference contains control characters")
    return normalized


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _document(
    *,
    case_id: str,
    kind: CaseDocumentKind,
    filename: str,
    payload: bytes,
    created_at: datetime,
) -> StoredDocumentRef:
    normalized_filename = _validate_filename(filename)
    _validate_pdf(payload)
    return StoredDocumentRef(
        document_id=_id("DOC"),
        case_id=case_id,
        kind=kind,
        original_filename=normalized_filename,
        media_type="application/pdf",
        byte_size=len(payload),
        sha256_hex=hashlib.sha256(payload).hexdigest(),
        storage_key=generate_storage_key(),
        created_at=created_at,
    )


def _document_event(
    document: StoredDocumentRef,
    *,
    actor_id: str,
) -> CaseEvent:
    return CaseEvent(
        event_id=_id("EV"),
        case_id=document.case_id,
        event_type=CaseEventType.DOCUMENT_ADDED,
        occurred_at=document.created_at,
        actor_id=actor_id,
        payload={
            "document_id": document.document_id,
            "kind": document.kind.value,
            "sha256": document.sha256_hex,
            "byte_size": str(document.byte_size),
        },
    )


def _cleanup_objects(
    document_store: DocumentStore,
    storage_keys: list[str],
) -> None:
    failures = []
    for key in reversed(storage_keys):
        try:
            document_store.delete(key)
        except Exception as error:
            failures.append(error)
    if failures:
        raise FilingConsistencyError(
            "Filing metadata failed and encrypted artifact rollback also "
            "failed."
        ) from failures[0]


def persist_filing(
    filing_repository: FilingRepository,
    draft_repository: DraftVersionRepository,
    document_store: DocumentStore,
    *,
    case: CaseRecord,
    approved_draft_version_id: str,
    filing_reference: str,
    filed_response_filename: str,
    filed_response_payload: bytes,
    acknowledgement_filename: Optional[str],
    acknowledgement_payload: Optional[bytes],
    filed_at: datetime,
    recorded_at: datetime,
    actor_id: str,
) -> FilingRecord:
    """Persist one actual filing and optional acknowledgement atomically."""
    if not isinstance(case, CaseRecord):
        raise TypeError("case must be a CaseRecord")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty")
    if not isinstance(approved_draft_version_id, str) or not approved_draft_version_id:
        raise ValueError("approved_draft_version_id must be non-empty")
    filed_at = _aware(filed_at, "filed_at")
    recorded_at = _aware(recorded_at, "recorded_at")
    if filed_at > recorded_at:
        raise ValueError("filed_at cannot be later than recorded_at")
    reference = _reference(filing_reference)

    if case.status not in {
        CaseStatus.DRAFT_REVIEW,
        CaseStatus.FILED,
        CaseStatus.HEARING,
    }:
        raise ValueError(
            "case status does not permit recording a filing"
        )

    draft = draft_repository.get_version_ref(
        approved_draft_version_id
    )
    if draft is None or draft.case_id != case.case_id:
        raise LookupError("approved draft version does not exist")
    if draft.review_status is not DraftReviewStatus.APPROVED:
        raise ValueError("filing requires an approved draft version")

    # Verify the immutable encrypted work product before linking a filing.
    load_draft_version(
        draft_repository,
        document_store,
        draft_version_id=draft.draft_version_id,
    )

    for existing in filing_repository.list_filings(case.case_id):
        if existing.filing_reference == reference:
            raise ValueError(
                "this filing reference is already recorded for the case"
            )

    if (acknowledgement_filename is None) != (
        acknowledgement_payload is None
    ):
        raise ValueError(
            "acknowledgement filename and payload must be supplied together"
        )

    filed_document = _document(
        case_id=case.case_id,
        kind=CaseDocumentKind.FILED_RESPONSE,
        filename=filed_response_filename,
        payload=filed_response_payload,
        created_at=recorded_at,
    )
    acknowledgement_document = (
        None
        if acknowledgement_payload is None
        else _document(
            case_id=case.case_id,
            kind=CaseDocumentKind.ACKNOWLEDGEMENT,
            filename=acknowledgement_filename,
            payload=acknowledgement_payload,
            created_at=recorded_at,
        )
    )

    filing = FilingRecord(
        filing_id=_id("FILING"),
        case_id=case.case_id,
        approved_draft_version_id=draft.draft_version_id,
        filed_response_document_id=filed_document.document_id,
        acknowledgement_document_id=(
            None
            if acknowledgement_document is None
            else acknowledgement_document.document_id
        ),
        filing_reference=reference,
        filed_at=filed_at,
        filed_by=actor_id,
        recorded_at=recorded_at,
        acknowledgement_added_at=(
            None if acknowledgement_document is None else recorded_at
        ),
        acknowledgement_added_by=(
            None if acknowledgement_document is None else actor_id
        ),
    )

    updated_case = (
        replace(case, status=CaseStatus.FILED, closed_at=None)
        if case.status is CaseStatus.DRAFT_REVIEW
        else case
    )

    events = [
        _document_event(filed_document, actor_id=actor_id),
    ]
    if acknowledgement_document is not None:
        events.append(
            _document_event(
                acknowledgement_document,
                actor_id=actor_id,
            )
        )
    if case.status is CaseStatus.DRAFT_REVIEW:
        events.append(
            CaseEvent(
                event_id=_id("EV"),
                case_id=case.case_id,
                event_type=CaseEventType.CASE_STATUS_CHANGED,
                occurred_at=recorded_at,
                actor_id=actor_id,
                payload={
                    "from_status": CaseStatus.DRAFT_REVIEW.value,
                    "to_status": CaseStatus.FILED.value,
                },
            )
        )
    events.append(
        CaseEvent(
            event_id=_id("EV"),
            case_id=case.case_id,
            event_type=CaseEventType.FILING_RECORDED,
            occurred_at=recorded_at,
            actor_id=actor_id,
            payload={
                "filing_id": filing.filing_id,
                "approved_draft_version_id": (
                    filing.approved_draft_version_id
                ),
                "filed_response_document_id": (
                    filing.filed_response_document_id
                ),
                "acknowledgement_document_id": (
                    "none"
                    if filing.acknowledgement_document_id is None
                    else filing.acknowledgement_document_id
                ),
                "filing_reference": filing.filing_reference,
                "filed_at": filing.filed_at.isoformat(),
            },
        )
    )

    stored_keys: list[str] = []
    try:
        document_store.put(
            filed_document.storage_key,
            filed_response_payload,
        )
        stored_keys.append(filed_document.storage_key)
        if acknowledgement_document is not None:
            document_store.put(
                acknowledgement_document.storage_key,
                acknowledgement_payload,
            )
            stored_keys.append(acknowledgement_document.storage_key)
    except Exception:
        if stored_keys:
            _cleanup_objects(document_store, stored_keys)
        raise

    try:
        filing_repository.save_filing(
            filing,
            filed_document,
            acknowledgement_document,
            updated_case,
            events,
        )
    except Exception as persistence_error:
        try:
            _cleanup_objects(document_store, stored_keys)
        except FilingConsistencyError:
            raise
        raise FilingPersistenceError(
            "Filing metadata failed; encrypted filing artifacts were "
            "rolled back."
        ) from persistence_error

    return filing


def attach_filing_acknowledgement(
    filing_repository: FilingRepository,
    document_store: DocumentStore,
    *,
    filing: FilingRecord,
    acknowledgement_filename: str,
    acknowledgement_payload: bytes,
    actor_id: str,
    added_at: datetime,
) -> FilingRecord:
    """Attach exactly one acknowledgement to an existing filing."""
    if not isinstance(filing, FilingRecord):
        raise TypeError("filing must be a FilingRecord")
    if filing.acknowledgement_document_id is not None:
        raise ValueError("filing already has an acknowledgement")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty")
    added_at = _aware(added_at, "added_at")
    if added_at < filing.recorded_at:
        raise ValueError(
            "acknowledgement cannot be recorded before filing record"
        )

    document = _document(
        case_id=filing.case_id,
        kind=CaseDocumentKind.ACKNOWLEDGEMENT,
        filename=acknowledgement_filename,
        payload=acknowledgement_payload,
        created_at=added_at,
    )
    updated = replace(
        filing,
        acknowledgement_document_id=document.document_id,
        acknowledgement_added_at=added_at,
        acknowledgement_added_by=actor_id,
    )
    events = [
        _document_event(document, actor_id=actor_id),
        CaseEvent(
            event_id=_id("EV"),
            case_id=filing.case_id,
            event_type=CaseEventType.FILING_ACKNOWLEDGEMENT_RECORDED,
            occurred_at=added_at,
            actor_id=actor_id,
            payload={
                "filing_id": filing.filing_id,
                "acknowledgement_document_id": document.document_id,
            },
        ),
    ]

    document_store.put(
        document.storage_key,
        acknowledgement_payload,
    )
    try:
        filing_repository.attach_acknowledgement(
            updated,
            document,
            events,
        )
    except Exception as persistence_error:
        try:
            _cleanup_objects(
                document_store,
                [document.storage_key],
            )
        except FilingConsistencyError:
            raise
        raise FilingPersistenceError(
            "Acknowledgement metadata failed; encrypted acknowledgement "
            "was rolled back."
        ) from persistence_error
    return updated
