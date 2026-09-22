"""Encrypted persistence and lineage services for professional draft versions."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime
from typing import List

from domain.analysis_snapshot_models import LoadedAnalysisSnapshot
from domain.case_models import CaseEvent, CaseEventType
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
    LoadedDraftVersion,
)
from domain.persistence_ports import DocumentStore, DraftVersionRepository
from modules.draft_work_product_payload import (
    build_draft_payload,
    decode_draft_payload,
    draft_content_sha256,
    encode_draft_payload,
)
from modules.encrypted_document_store import generate_storage_key


class DraftPersistenceError(RuntimeError):
    """Draft metadata failed and encrypted payload was rolled back."""


class DraftConsistencyError(DraftPersistenceError):
    """Draft metadata failed and encrypted rollback also failed."""


class DraftIntegrityError(RuntimeError):
    """Stored draft metadata/payload binding is inconsistent."""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def baseline_text_from_snapshot(
    snapshot: LoadedAnalysisSnapshot,
) -> str:
    """Render the validated generated draft into editable professional text."""
    if not isinstance(snapshot, LoadedAnalysisSnapshot):
        raise TypeError("snapshot must be a LoadedAnalysisSnapshot")
    draft = snapshot.payload.get("draft")
    if not isinstance(draft, dict):
        raise ValueError("snapshot draft section is invalid")
    if draft.get("status") != "success":
        raise ValueError("snapshot does not contain a successful draft")
    post_validation = draft.get("post_validation")
    if (
        not isinstance(post_validation, dict)
        or post_validation.get("overall_status") != "pass"
    ):
        raise ValueError("snapshot draft did not pass post-validation")
    sections = draft.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("snapshot draft contains no sections")

    rendered = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("snapshot draft section is invalid")
        title = section.get("title")
        text = section.get("rendered_text")
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("snapshot draft section is invalid")
        rendered.append(f"## {title.strip()}\n\n{text.strip()}")
    return "\n\n".join(rendered).strip()


def persist_draft_version(
    repository: DraftVersionRepository,
    document_store: DocumentStore,
    *,
    case_id: str,
    source_snapshot_id: str,
    parent_draft_version_id: str | None,
    version_number: int,
    generated_baseline: bool,
    draft_text: str,
    actor_id: str,
    created_at: datetime,
) -> DraftVersionRef:
    payload = build_draft_payload(
        case_id=case_id,
        source_snapshot_id=source_snapshot_id,
        parent_draft_version_id=parent_draft_version_id,
        version_number=version_number,
        generated_baseline=generated_baseline,
        draft_text=draft_text,
        created_at=created_at,
        created_by=actor_id,
    )
    encoded = encode_draft_payload(payload)
    storage_key = generate_storage_key()
    payload_hash = hashlib.sha256(encoded).hexdigest()
    content_hash = draft_content_sha256(draft_text)

    version = DraftVersionRef(
        draft_version_id=_id("DRAFT"),
        case_id=case_id,
        source_snapshot_id=source_snapshot_id,
        parent_draft_version_id=parent_draft_version_id,
        version_number=version_number,
        generated_baseline=generated_baseline,
        content_sha256=content_hash,
        byte_size=len(encoded),
        sha256_hex=payload_hash,
        storage_key=storage_key,
        review_status=DraftReviewStatus.WORKING,
        created_at=created_at,
        created_by=actor_id,
    )
    event = CaseEvent(
        event_id=_id("EV"),
        case_id=case_id,
        event_type=CaseEventType.DRAFT_CREATED,
        occurred_at=created_at,
        actor_id=actor_id,
        payload={
            "draft_version_id": version.draft_version_id,
            "source_snapshot_id": source_snapshot_id,
            "parent_draft_version_id": (
                "none"
                if parent_draft_version_id is None
                else parent_draft_version_id
            ),
            "version_number": str(version_number),
            "generated_baseline": str(generated_baseline).lower(),
            "content_sha256": content_hash,
            "draft_payload_sha256": payload_hash,
            "byte_size": str(len(encoded)),
        },
    )

    document_store.put(storage_key, encoded)
    try:
        repository.save_version(version, event)
    except Exception as persistence_error:
        try:
            document_store.delete(storage_key)
        except Exception as rollback_error:
            raise DraftConsistencyError(
                "Draft metadata failed and encrypted payload rollback "
                "also failed."
            ) from rollback_error
        raise DraftPersistenceError(
            "Draft metadata failed; encrypted payload was rolled back."
        ) from persistence_error
    return version


def load_draft_version(
    repository: DraftVersionRepository,
    document_store: DocumentStore,
    *,
    draft_version_id: str,
) -> LoadedDraftVersion:
    if not isinstance(draft_version_id, str) or not draft_version_id:
        raise ValueError("draft_version_id must be non-empty")
    version = repository.get_version_ref(draft_version_id)
    if version is None:
        raise LookupError("draft version does not exist")

    encoded = document_store.get(version.storage_key)
    if len(encoded) != version.byte_size:
        raise DraftIntegrityError(
            "draft byte size does not match metadata"
        )
    if hashlib.sha256(encoded).hexdigest() != version.sha256_hex:
        raise DraftIntegrityError(
            "draft payload hash does not match metadata"
        )
    try:
        payload = decode_draft_payload(encoded)
    except ValueError as error:
        raise DraftIntegrityError("draft payload is invalid") from error

    exact_pairs = (
        ("case_id", version.case_id),
        ("source_snapshot_id", version.source_snapshot_id),
        ("parent_draft_version_id", version.parent_draft_version_id),
        ("version_number", version.version_number),
        ("generated_baseline", version.generated_baseline),
        ("created_at", version.created_at.isoformat()),
        ("created_by", version.created_by),
    )
    for key, expected in exact_pairs:
        if payload[key] != expected:
            raise DraftIntegrityError(
                f"draft payload {key} is inconsistent"
            )
    if draft_content_sha256(payload["draft_text"]) != version.content_sha256:
        raise DraftIntegrityError(
            "draft content hash does not match metadata"
        )
    return LoadedDraftVersion(metadata=version, payload=payload)


def list_draft_versions(
    repository: DraftVersionRepository,
    *,
    case_id: str,
) -> List[DraftVersionRef]:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty")
    return repository.list_version_refs(case_id)


def transition_draft_review_status(
    repository: DraftVersionRepository,
    *,
    version: DraftVersionRef,
    target_status: DraftReviewStatus,
    actor_id: str,
    occurred_at: datetime,
) -> DraftVersionRef:
    if not isinstance(version, DraftVersionRef):
        raise TypeError("version must be a DraftVersionRef")
    if not isinstance(target_status, DraftReviewStatus):
        raise TypeError("target_status must be DraftReviewStatus")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")

    if (
        version.review_status is DraftReviewStatus.WORKING
        and target_status is DraftReviewStatus.REVIEWED
    ):
        updated = replace(
            version,
            review_status=DraftReviewStatus.REVIEWED,
            reviewed_at=occurred_at,
            reviewed_by=actor_id,
        )
    elif (
        version.review_status is DraftReviewStatus.REVIEWED
        and target_status is DraftReviewStatus.APPROVED
    ):
        updated = replace(
            version,
            review_status=DraftReviewStatus.APPROVED,
            approved_at=occurred_at,
            approved_by=actor_id,
        )
    else:
        raise ValueError("draft review status transition is not allowed")

    event = CaseEvent(
        event_id=_id("EV"),
        case_id=version.case_id,
        event_type=CaseEventType.DRAFT_REVIEWED,
        occurred_at=occurred_at,
        actor_id=actor_id,
        payload={
            "draft_version_id": version.draft_version_id,
            "version_number": str(version.version_number),
            "from_status": version.review_status.value,
            "to_status": updated.review_status.value,
            "content_sha256": version.content_sha256,
        },
    )
    repository.transition_review_status(updated, event)
    return updated
