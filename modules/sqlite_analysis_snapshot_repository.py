"""SQLite metadata repository for encrypted versioned analysis snapshots."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from domain.analysis_snapshot_models import AnalysisSnapshotRef
from domain.case_models import CaseEvent, CaseEventType, CaseStatus
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


class LocalSQLiteAnalysisSnapshotRepository:
    """Snapshot metadata/audit persistence against the shared Dwaar DB."""

    def __init__(self, db_path: str):
        # Authoritative case repository performs schema initialization/migration.
        self._cases = LocalSQLiteCaseRepository(db_path)
        self._db_path = self._cases.db_path

    def _connect(self) -> sqlite3.Connection:
        return self._cases._connect()

    @staticmethod
    def _validate_snapshot(snapshot: AnalysisSnapshotRef) -> None:
        if not isinstance(snapshot, AnalysisSnapshotRef):
            raise TypeError("snapshot must be an AnalysisSnapshotRef")
        if snapshot.schema_version <= 0:
            raise ValueError("snapshot schema_version must be positive")
        if not snapshot.engine_version:
            raise ValueError("snapshot engine_version must be non-empty")
        if snapshot.byte_size <= 0:
            raise ValueError("snapshot byte_size must be positive")
        for label, value in (
            ("source_document_sha256", snapshot.source_document_sha256),
            ("sha256_hex", snapshot.sha256_hex),
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{label} must contain 64 hex chars")
            try:
                int(value, 16)
            except ValueError as error:
                raise ValueError(
                    f"{label} must contain 64 hex chars"
                ) from error
        if not isinstance(snapshot.created_by, str) or not snapshot.created_by:
            raise ValueError("snapshot created_by must be non-empty")
        LocalSQLiteCaseRepository._dt(snapshot.created_at)

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> AnalysisSnapshotRef:
        return AnalysisSnapshotRef(
            snapshot_id=row["snapshot_id"],
            case_id=row["case_id"],
            source_document_id=row["source_document_id"],
            source_document_sha256=row["source_document_sha256"],
            schema_version=row["schema_version"],
            engine_version=row["engine_version"],
            byte_size=row["byte_size"],
            sha256_hex=row["sha256_hex"],
            storage_key=row["storage_key"],
            created_at=LocalSQLiteCaseRepository._parse_dt(
                row["created_at"]
            ),
            created_by=row["created_by"],
        )

    def save_snapshot(
        self,
        snapshot: AnalysisSnapshotRef,
        event: CaseEvent,
    ) -> None:
        """Atomically store snapshot metadata, event and case-status update."""
        self._validate_snapshot(snapshot)
        if not isinstance(event, CaseEvent):
            raise TypeError("event must be a CaseEvent")
        if event.case_id != snapshot.case_id:
            raise RepositoryConflictError(
                "Snapshot and audit event must belong to the same case."
            )
        if event.event_type is not CaseEventType.ANALYSIS_SAVED:
            raise ValueError("snapshot audit event must be ANALYSIS_SAVED")
        if event.actor_id != snapshot.created_by:
            raise RepositoryConflictError(
                "Snapshot creator and audit actor must match."
            )

        # Validate event before entering the transaction.
        LocalSQLiteCaseRepository._validate_event_payload(event.payload)
        LocalSQLiteCaseRepository._dt(event.occurred_at)

        with self._connect() as connection:
            case_row = connection.execute(
                "SELECT status FROM cases WHERE case_id = ?",
                (snapshot.case_id,),
            ).fetchone()
            if case_row is None:
                raise RepositoryNotFoundError("Case does not exist.")

            document_row = connection.execute(
                """
                SELECT case_id, sha256_hex
                FROM case_documents
                WHERE document_id = ?
                """,
                (snapshot.source_document_id,),
            ).fetchone()
            if document_row is None:
                raise RepositoryNotFoundError(
                    "Snapshot source document does not exist."
                )
            if document_row["case_id"] != snapshot.case_id:
                raise RepositoryConflictError(
                    "Snapshot source document belongs to another case."
                )
            if (
                document_row["sha256_hex"].lower()
                != snapshot.source_document_sha256.lower()
            ):
                raise RepositoryConflictError(
                    "Snapshot source document hash does not match metadata."
                )

            try:
                connection.execute(
                    """
                    INSERT INTO analysis_snapshots(
                        snapshot_id, case_id, source_document_id,
                        source_document_sha256, schema_version,
                        engine_version, byte_size, sha256_hex,
                        storage_key, created_at, created_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.case_id,
                        snapshot.source_document_id,
                        snapshot.source_document_sha256.lower(),
                        snapshot.schema_version,
                        snapshot.engine_version,
                        snapshot.byte_size,
                        snapshot.sha256_hex.lower(),
                        snapshot.storage_key,
                        LocalSQLiteCaseRepository._dt(
                            snapshot.created_at
                        ),
                        snapshot.created_by,
                    ),
                )
                self._cases._insert_event(connection, event)

                if case_row["status"] == CaseStatus.INTAKE.value:
                    connection.execute(
                        """
                        UPDATE cases
                        SET status = ?
                        WHERE case_id = ?
                        """,
                        (
                            CaseStatus.ANALYZED.value,
                            snapshot.case_id,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise RepositoryConflictError(
                    "Analysis snapshot could not be persisted due to an "
                    "identity or relationship conflict."
                ) from error

    def get_snapshot_ref(
        self,
        snapshot_id: str,
    ) -> Optional[AnalysisSnapshotRef]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        return None if row is None else self._snapshot_from_row(row)

    def list_snapshot_refs(
        self,
        case_id: str,
    ) -> List[AnalysisSnapshotRef]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_snapshots
                WHERE case_id = ?
                ORDER BY created_at ASC, snapshot_id ASC
                """,
                (case_id,),
            ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]
