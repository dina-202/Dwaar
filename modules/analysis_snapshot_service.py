"""Encrypted persistence and safe loading for versioned analysis snapshots."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import List

from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisSnapshotRef,
    LoadedAnalysisSnapshot,
)
from domain.case_models import CaseEvent, CaseEventType, StoredDocumentRef
from domain.models import Phase2AnalysisResult
from domain.persistence_ports import AnalysisSnapshotRepository, DocumentStore
from modules.analysis_snapshot import (
    build_snapshot_payload,
    decode_snapshot_payload,
    encode_snapshot_payload,
)
from modules.encrypted_document_store import generate_storage_key


class AnalysisSnapshotPersistenceError(RuntimeError):
    """Snapshot DB persistence failed and ciphertext was rolled back."""


class AnalysisSnapshotConsistencyError(AnalysisSnapshotPersistenceError):
    """Snapshot DB failed and ciphertext rollback also failed."""


class AnalysisSnapshotIntegrityError(RuntimeError):
    """Encrypted snapshot bytes/metadata/source binding are inconsistent."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def persist_analysis_snapshot(
    snapshot_repository: AnalysisSnapshotRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    source_document: StoredDocumentRef,
    analysis: Phase2AnalysisResult,
    actor_id: str,
    created_at: datetime,
) -> AnalysisSnapshotRef:
    """Persist one historical analysis snapshot bound to one notice."""
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    if not isinstance(source_document, StoredDocumentRef):
        raise TypeError("source_document must be a StoredDocumentRef")
    if source_document.case_id != case_id:
        raise ValueError("source_document must belong to case_id")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")

    payload = build_snapshot_payload(
        analysis,
        source_document_id=source_document.document_id,
        source_document_sha256=source_document.sha256_hex,
    )
    encoded = encode_snapshot_payload(payload)
    payload_hash = hashlib.sha256(encoded).hexdigest()
    storage_key = generate_storage_key()

    snapshot = AnalysisSnapshotRef(
        snapshot_id=_id("SNAP"),
        case_id=case_id,
        source_document_id=source_document.document_id,
        source_document_sha256=source_document.sha256_hex.lower(),
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        engine_version=ANALYSIS_ENGINE_VERSION,
        byte_size=len(encoded),
        sha256_hex=payload_hash,
        storage_key=storage_key,
        created_at=created_at,
        created_by=actor_id,
    )
    event = CaseEvent(
        event_id=_id("EV"),
        case_id=case_id,
        event_type=CaseEventType.ANALYSIS_SAVED,
        occurred_at=created_at,
        actor_id=actor_id,
        payload={
            "snapshot_id": snapshot.snapshot_id,
            "source_document_id": source_document.document_id,
            "source_document_sha256": (
                source_document.sha256_hex.lower()
            ),
            "schema_version": str(SNAPSHOT_SCHEMA_VERSION),
            "engine_version": ANALYSIS_ENGINE_VERSION,
            "snapshot_sha256": payload_hash,
            "byte_size": str(len(encoded)),
        },
    )

    document_store.put(storage_key, encoded)
    try:
        snapshot_repository.save_snapshot(snapshot, event)
    except Exception as persistence_error:
        try:
            document_store.delete(storage_key)
        except Exception as rollback_error:
            raise AnalysisSnapshotConsistencyError(
                "Analysis snapshot metadata failed and encrypted snapshot "
                "rollback also failed."
            ) from rollback_error
        raise AnalysisSnapshotPersistenceError(
            "Analysis snapshot metadata failed; encrypted snapshot was "
            "rolled back."
        ) from persistence_error

    return snapshot


def load_analysis_snapshot(
    snapshot_repository: AnalysisSnapshotRepository,
    document_store: DocumentStore,
    *,
    snapshot_id: str,
    expected_source_document: StoredDocumentRef,
) -> LoadedAnalysisSnapshot:
    """Load/verify historical JSON without constructing live domain objects."""
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    if not isinstance(expected_source_document, StoredDocumentRef):
        raise TypeError(
            "expected_source_document must be a StoredDocumentRef"
        )

    snapshot = snapshot_repository.get_snapshot_ref(snapshot_id)
    if snapshot is None:
        raise LookupError("analysis snapshot does not exist")
    if snapshot.case_id != expected_source_document.case_id:
        raise AnalysisSnapshotIntegrityError(
            "snapshot case/source relationship is inconsistent"
        )
    if snapshot.source_document_id != expected_source_document.document_id:
        raise AnalysisSnapshotIntegrityError(
            "snapshot source document identity is inconsistent"
        )
    if (
        snapshot.source_document_sha256.lower()
        != expected_source_document.sha256_hex.lower()
    ):
        raise AnalysisSnapshotIntegrityError(
            "snapshot source document hash is inconsistent"
        )
    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise AnalysisSnapshotIntegrityError(
            "snapshot schema version is unsupported"
        )
    if snapshot.engine_version != ANALYSIS_ENGINE_VERSION:
        raise AnalysisSnapshotIntegrityError(
            "snapshot engine version is unsupported"
        )

    encoded = document_store.get(snapshot.storage_key)
    if len(encoded) != snapshot.byte_size:
        raise AnalysisSnapshotIntegrityError(
            "snapshot byte size does not match metadata"
        )
    if hashlib.sha256(encoded).hexdigest() != snapshot.sha256_hex:
        raise AnalysisSnapshotIntegrityError(
            "snapshot hash does not match metadata"
        )

    try:
        payload = decode_snapshot_payload(encoded)
    except ValueError as error:
        raise AnalysisSnapshotIntegrityError(
            "snapshot JSON payload is invalid"
        ) from error

    source = payload["source"]
    if source["document_id"] != snapshot.source_document_id:
        raise AnalysisSnapshotIntegrityError(
            "snapshot payload source document is inconsistent"
        )
    if source["sha256"].lower() != snapshot.source_document_sha256.lower():
        raise AnalysisSnapshotIntegrityError(
            "snapshot payload source hash is inconsistent"
        )

    return LoadedAnalysisSnapshot(
        metadata=snapshot,
        payload=payload,
    )


def list_analysis_snapshot_refs(
    snapshot_repository: AnalysisSnapshotRepository,
    *,
    case_id: str,
) -> List[AnalysisSnapshotRef]:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    return snapshot_repository.list_snapshot_refs(case_id)
