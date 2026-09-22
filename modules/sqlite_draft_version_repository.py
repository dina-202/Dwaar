"""SQLite metadata repository for encrypted draft work-product versions."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from domain.case_models import CaseEvent, CaseEventType
from domain.draft_work_product_models import (
    DraftReviewStatus,
    DraftVersionRef,
)
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


class LocalSQLiteDraftVersionRepository:
    """Draft metadata/review persistence against the shared Dwaar DB."""

    def __init__(self, db_path: str):
        self._cases = LocalSQLiteCaseRepository(db_path)
        self._db_path = self._cases.db_path

    def _connect(self) -> sqlite3.Connection:
        return self._cases._connect()

    @staticmethod
    def _hash(label: str, value: str) -> None:
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"{label} must contain 64 hex chars")
        try:
            int(value, 16)
        except ValueError as error:
            raise ValueError(
                f"{label} must contain 64 hex chars"
            ) from error

    @classmethod
    def _validate_version(cls, value: DraftVersionRef) -> None:
        if not isinstance(value, DraftVersionRef):
            raise TypeError("version must be a DraftVersionRef")
        for label, item in (
            ("draft_version_id", value.draft_version_id),
            ("case_id", value.case_id),
            ("source_snapshot_id", value.source_snapshot_id),
            ("storage_key", value.storage_key),
            ("created_by", value.created_by),
        ):
            if not isinstance(item, str) or not item:
                raise ValueError(f"{label} must be non-empty")
        if value.parent_draft_version_id is not None and (
            not isinstance(value.parent_draft_version_id, str)
            or not value.parent_draft_version_id
        ):
            raise ValueError(
                "parent_draft_version_id must be non-empty or None"
            )
        if value.version_number < 1:
            raise ValueError("version_number must be positive")
        if not isinstance(value.generated_baseline, bool):
            raise TypeError("generated_baseline must be bool")
        if value.byte_size <= 0:
            raise ValueError("byte_size must be positive")
        cls._hash("content_sha256", value.content_sha256)
        cls._hash("sha256_hex", value.sha256_hex)
        LocalSQLiteCaseRepository._dt(value.created_at)

        if value.review_status is DraftReviewStatus.WORKING:
            if any(
                item is not None
                for item in (
                    value.reviewed_at,
                    value.reviewed_by,
                    value.approved_at,
                    value.approved_by,
                )
            ):
                raise ValueError(
                    "working draft must not contain review metadata"
                )
        elif value.review_status is DraftReviewStatus.REVIEWED:
            if (
                value.reviewed_at is None
                or not value.reviewed_by
                or value.approved_at is not None
                or value.approved_by is not None
            ):
                raise ValueError(
                    "reviewed draft metadata is inconsistent"
                )
            LocalSQLiteCaseRepository._dt(value.reviewed_at)
        elif value.review_status is DraftReviewStatus.APPROVED:
            if (
                value.reviewed_at is None
                or not value.reviewed_by
                or value.approved_at is None
                or not value.approved_by
            ):
                raise ValueError(
                    "approved draft metadata is inconsistent"
                )
            LocalSQLiteCaseRepository._dt(value.reviewed_at)
            LocalSQLiteCaseRepository._dt(value.approved_at)
        else:
            raise TypeError("review_status must be DraftReviewStatus")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DraftVersionRef:
        def _dt(value):
            return (
                None
                if value is None
                else LocalSQLiteCaseRepository._parse_dt(value)
            )

        return DraftVersionRef(
            draft_version_id=row["draft_version_id"],
            case_id=row["case_id"],
            source_snapshot_id=row["source_snapshot_id"],
            parent_draft_version_id=row["parent_draft_version_id"],
            version_number=row["version_number"],
            generated_baseline=bool(row["generated_baseline"]),
            content_sha256=row["content_sha256"],
            byte_size=row["byte_size"],
            sha256_hex=row["sha256_hex"],
            storage_key=row["storage_key"],
            review_status=DraftReviewStatus(row["review_status"]),
            created_at=LocalSQLiteCaseRepository._parse_dt(
                row["created_at"]
            ),
            created_by=row["created_by"],
            reviewed_at=_dt(row["reviewed_at"]),
            reviewed_by=row["reviewed_by"],
            approved_at=_dt(row["approved_at"]),
            approved_by=row["approved_by"],
        )

    def save_version(
        self,
        version: DraftVersionRef,
        event: CaseEvent,
    ) -> None:
        self._validate_version(version)
        if event.event_type is not CaseEventType.DRAFT_CREATED:
            raise ValueError("draft create event must be DRAFT_CREATED")
        if event.case_id != version.case_id:
            raise RepositoryConflictError(
                "Draft and event must belong to the same case."
            )
        if event.actor_id != version.created_by:
            raise RepositoryConflictError(
                "Draft creator and audit actor must match."
            )
        LocalSQLiteCaseRepository._validate_event_payload(event.payload)
        LocalSQLiteCaseRepository._dt(event.occurred_at)

        with self._connect() as connection:
            snapshot = connection.execute(
                """
                SELECT case_id FROM analysis_snapshots
                WHERE snapshot_id = ?
                """,
                (version.source_snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise RepositoryNotFoundError(
                    "Draft source snapshot does not exist."
                )
            if snapshot["case_id"] != version.case_id:
                raise RepositoryConflictError(
                    "Draft source snapshot belongs to another case."
                )

            previous = connection.execute(
                """
                SELECT MAX(version_number) AS max_version
                FROM draft_versions
                WHERE case_id = ?
                """,
                (version.case_id,),
            ).fetchone()
            expected_next = (
                1
                if previous["max_version"] is None
                else previous["max_version"] + 1
            )
            if version.version_number != expected_next:
                raise RepositoryConflictError(
                    "Draft version number must be next for the case."
                )

            if version.parent_draft_version_id is None:
                if not version.generated_baseline:
                    raise RepositoryConflictError(
                        "Root draft version must be generated baseline."
                    )
            else:
                parent = connection.execute(
                    """
                    SELECT case_id, source_snapshot_id, version_number
                    FROM draft_versions
                    WHERE draft_version_id = ?
                    """,
                    (version.parent_draft_version_id,),
                ).fetchone()
                if parent is None:
                    raise RepositoryNotFoundError(
                        "Parent draft version does not exist."
                    )
                if (
                    parent["case_id"] != version.case_id
                    or parent["source_snapshot_id"]
                    != version.source_snapshot_id
                ):
                    raise RepositoryConflictError(
                        "Parent draft belongs to another lineage."
                    )
                if version.generated_baseline:
                    raise RepositoryConflictError(
                        "Child draft version cannot be generated baseline."
                    )
                if version.version_number != parent["version_number"] + 1:
                    raise RepositoryConflictError(
                        "Child draft version number must follow parent."
                    )

            try:
                connection.execute(
                    """
                    INSERT INTO draft_versions(
                        draft_version_id, case_id, source_snapshot_id,
                        parent_draft_version_id, version_number,
                        generated_baseline, content_sha256, byte_size,
                        sha256_hex, storage_key, review_status,
                        created_at, created_by, reviewed_at, reviewed_by,
                        approved_at, approved_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.draft_version_id,
                        version.case_id,
                        version.source_snapshot_id,
                        version.parent_draft_version_id,
                        version.version_number,
                        int(version.generated_baseline),
                        version.content_sha256.lower(),
                        version.byte_size,
                        version.sha256_hex.lower(),
                        version.storage_key,
                        version.review_status.value,
                        LocalSQLiteCaseRepository._dt(
                            version.created_at
                        ),
                        version.created_by,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                self._cases._insert_event(connection, event)
            except sqlite3.IntegrityError as error:
                raise RepositoryConflictError(
                    "Draft version could not be persisted due to an "
                    "identity, lineage or version conflict."
                ) from error

    def get_version_ref(
        self,
        draft_version_id: str,
    ) -> Optional[DraftVersionRef]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM draft_versions
                WHERE draft_version_id = ?
                """,
                (draft_version_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_version_refs(
        self,
        case_id: str,
    ) -> List[DraftVersionRef]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM draft_versions
                WHERE case_id = ?
                ORDER BY version_number ASC, draft_version_id ASC
                """,
                (case_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def transition_review_status(
        self,
        version: DraftVersionRef,
        event: CaseEvent,
    ) -> None:
        self._validate_version(version)
        if event.event_type is not CaseEventType.DRAFT_REVIEWED:
            raise ValueError("draft review event must be DRAFT_REVIEWED")
        if event.case_id != version.case_id:
            raise RepositoryConflictError(
                "Draft review event belongs to another case."
            )
        if event.actor_id not in {
            version.reviewed_by,
            version.approved_by,
        }:
            raise RepositoryConflictError(
                "Draft review audit actor is inconsistent."
            )
        LocalSQLiteCaseRepository._validate_event_payload(event.payload)
        LocalSQLiteCaseRepository._dt(event.occurred_at)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM draft_versions
                WHERE draft_version_id = ?
                """,
                (version.draft_version_id,),
            ).fetchone()
            if row is None:
                raise RepositoryNotFoundError(
                    "Draft version does not exist."
                )
            existing = self._from_row(row)

            immutable_before = (
                existing.case_id,
                existing.source_snapshot_id,
                existing.parent_draft_version_id,
                existing.version_number,
                existing.generated_baseline,
                existing.content_sha256,
                existing.byte_size,
                existing.sha256_hex,
                existing.storage_key,
                existing.created_at,
                existing.created_by,
            )
            immutable_after = (
                version.case_id,
                version.source_snapshot_id,
                version.parent_draft_version_id,
                version.version_number,
                version.generated_baseline,
                version.content_sha256,
                version.byte_size,
                version.sha256_hex,
                version.storage_key,
                version.created_at,
                version.created_by,
            )
            if immutable_before != immutable_after:
                raise RepositoryConflictError(
                    "Draft content/version identity is immutable."
                )

            allowed = {
                DraftReviewStatus.WORKING: DraftReviewStatus.REVIEWED,
                DraftReviewStatus.REVIEWED: DraftReviewStatus.APPROVED,
            }
            if allowed.get(existing.review_status) is not version.review_status:
                raise RepositoryConflictError(
                    "Draft review status transition is not allowed."
                )

            connection.execute(
                """
                UPDATE draft_versions
                SET review_status = ?, reviewed_at = ?, reviewed_by = ?,
                    approved_at = ?, approved_by = ?
                WHERE draft_version_id = ?
                """,
                (
                    version.review_status.value,
                    (
                        None
                        if version.reviewed_at is None
                        else LocalSQLiteCaseRepository._dt(
                            version.reviewed_at
                        )
                    ),
                    version.reviewed_by,
                    (
                        None
                        if version.approved_at is None
                        else LocalSQLiteCaseRepository._dt(
                            version.approved_at
                        )
                    ),
                    version.approved_by,
                    version.draft_version_id,
                ),
            )
            self._cases._insert_event(connection, event)
