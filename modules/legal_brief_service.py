"""Encrypted persistence for snapshot-bound legal briefs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from typing import List

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.case_models import CaseEvent, CaseEventType
from domain.legal_brief_models import (
    LEGAL_BRIEF_SCHEMA_VERSION,
    SUPPORTED_LEGAL_BRIEF_SCHEMA_VERSIONS,
    LegalBriefRef,
    LoadedLegalBrief,
)
from domain.legal_knowledge_models import LegalKnowledgeResult
from domain.legal_question_models import LegalQuestionPlan
from domain.models import ProceedingType
from domain.persistence_ports import DocumentStore, LegalBriefRepository
from modules.encrypted_document_store import generate_storage_key
from modules.legal_brief_snapshot import (
    build_legal_brief_payload,
    decode_legal_brief_payload,
    encode_legal_brief_payload,
)


class LegalBriefPersistenceError(RuntimeError):
    """Legal brief DB persistence failed and ciphertext was rolled back."""


class LegalBriefConsistencyError(LegalBriefPersistenceError):
    """Metadata persistence and encrypted-object rollback both failed."""


class LegalBriefIntegrityError(RuntimeError):
    """Legal brief metadata, hash or snapshot binding is inconsistent."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def persist_legal_brief(
    brief_repository: LegalBriefRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    snapshot: AnalysisSnapshotRef,
    result: LegalKnowledgeResult,
    as_of_date: date,
    proceeding_type: ProceedingType,
    actor_id: str,
    created_at: datetime,
    question_plan: LegalQuestionPlan | None = None,
) -> LegalBriefRef:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    if not isinstance(snapshot, AnalysisSnapshotRef):
        raise TypeError("snapshot must be an AnalysisSnapshotRef")
    if snapshot.case_id != case_id:
        raise ValueError("snapshot must belong to case_id")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")

    payload = build_legal_brief_payload(
        result,
        snapshot_id=snapshot.snapshot_id,
        as_of_date=as_of_date,
        proceeding_type=proceeding_type,
        question_plan=question_plan,
    )
    encoded = encode_legal_brief_payload(payload)
    payload_hash = hashlib.sha256(encoded).hexdigest()
    storage_key = generate_storage_key()
    brief = LegalBriefRef(
        legal_brief_id=_id("LEGAL"),
        case_id=case_id,
        snapshot_id=snapshot.snapshot_id,
        schema_version=LEGAL_BRIEF_SCHEMA_VERSION,
        catalog_version=result.catalog_version,
        as_of_date=as_of_date,
        proceeding_type=proceeding_type,
        byte_size=len(encoded),
        sha256_hex=payload_hash,
        storage_key=storage_key,
        created_at=created_at,
        created_by=actor_id,
    )
    event = CaseEvent(
        event_id=_id("EV"),
        case_id=case_id,
        event_type=CaseEventType.LEGAL_BRIEF_SAVED,
        occurred_at=created_at,
        actor_id=actor_id,
        payload={
            "legal_brief_id": brief.legal_brief_id,
            "snapshot_id": snapshot.snapshot_id,
            "catalog_version": brief.catalog_version,
            "as_of_date": brief.as_of_date.isoformat(),
            "proceeding_type": proceeding_type.value,
            "brief_sha256": payload_hash,
        },
    )

    document_store.put(storage_key, encoded)
    try:
        brief_repository.save_brief(brief, event)
    except Exception as persistence_error:
        try:
            document_store.delete(storage_key)
        except Exception as rollback_error:
            raise LegalBriefConsistencyError(
                "Legal brief metadata failed and encrypted-object rollback "
                "also failed."
            ) from rollback_error
        raise LegalBriefPersistenceError(
            "Legal brief metadata failed; encrypted object was rolled back."
        ) from persistence_error
    return brief


def load_legal_brief(
    brief_repository: LegalBriefRepository,
    document_store: DocumentStore,
    *,
    legal_brief_id: str,
    expected_snapshot: AnalysisSnapshotRef,
) -> LoadedLegalBrief:
    if not isinstance(legal_brief_id, str) or not legal_brief_id:
        raise ValueError("legal_brief_id must be non-empty")
    if not isinstance(expected_snapshot, AnalysisSnapshotRef):
        raise TypeError("expected_snapshot must be an AnalysisSnapshotRef")

    brief = brief_repository.get_brief_ref(legal_brief_id)
    if brief is None:
        raise LookupError("legal brief does not exist")
    if brief.case_id != expected_snapshot.case_id:
        raise LegalBriefIntegrityError(
            "legal brief case binding is inconsistent"
        )
    if brief.snapshot_id != expected_snapshot.snapshot_id:
        raise LegalBriefIntegrityError(
            "legal brief snapshot binding is inconsistent"
        )
    if brief.schema_version not in SUPPORTED_LEGAL_BRIEF_SCHEMA_VERSIONS:
        raise LegalBriefIntegrityError(
            "legal brief schema version is unsupported"
        )

    encoded = document_store.get(brief.storage_key)
    if len(encoded) != brief.byte_size:
        raise LegalBriefIntegrityError(
            "legal brief byte size does not match metadata"
        )
    if hashlib.sha256(encoded).hexdigest() != brief.sha256_hex:
        raise LegalBriefIntegrityError(
            "legal brief hash does not match metadata"
        )
    try:
        payload = decode_legal_brief_payload(encoded)
    except ValueError as error:
        raise LegalBriefIntegrityError(
            "legal brief JSON payload is invalid"
        ) from error

    if payload["schema_version"] != brief.schema_version:
        raise LegalBriefIntegrityError(
            "legal brief payload schema version is inconsistent"
        )
    if payload["snapshot_id"] != brief.snapshot_id:
        raise LegalBriefIntegrityError(
            "legal brief payload snapshot is inconsistent"
        )
    if payload["catalog_version"] != brief.catalog_version:
        raise LegalBriefIntegrityError(
            "legal brief payload catalog version is inconsistent"
        )
    if payload["as_of_date"] != brief.as_of_date.isoformat():
        raise LegalBriefIntegrityError(
            "legal brief payload date is inconsistent"
        )
    if payload["proceeding_type"] != brief.proceeding_type.value:
        raise LegalBriefIntegrityError(
            "legal brief payload proceeding is inconsistent"
        )
    return LoadedLegalBrief(metadata=brief, payload=payload)


def list_legal_brief_refs(
    brief_repository: LegalBriefRepository,
    *,
    snapshot_id: str,
) -> List[LegalBriefRef]:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be non-empty")
    return brief_repository.list_brief_refs(snapshot_id)
