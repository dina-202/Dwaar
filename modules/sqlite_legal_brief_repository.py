"""SQLite metadata repository for snapshot-bound legal briefs."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from domain.case_models import CaseEvent, CaseEventType
from domain.legal_brief_models import LegalBriefRef
from domain.models import ProceedingType
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


class LocalSQLiteLegalBriefRepository:
    def __init__(self, db_path: str):
        self._cases = LocalSQLiteCaseRepository(db_path)
        self._db_path = self._cases.db_path

    def _connect(self) -> sqlite3.Connection:
        return self._cases._connect()

    @staticmethod
    def _validate_brief(brief: LegalBriefRef) -> None:
        if not isinstance(brief, LegalBriefRef):
            raise TypeError("brief must be a LegalBriefRef")
        if brief.schema_version <= 0:
            raise ValueError("legal brief schema_version must be positive")
        if not brief.catalog_version:
            raise ValueError("legal brief catalog_version must be non-empty")
        if brief.byte_size <= 0:
            raise ValueError("legal brief byte_size must be positive")
        if not isinstance(brief.proceeding_type, ProceedingType):
            raise TypeError("legal brief proceeding_type is invalid")
        if not isinstance(brief.created_by, str) or not brief.created_by:
            raise ValueError("legal brief created_by must be non-empty")
        if not isinstance(brief.sha256_hex, str) or len(brief.sha256_hex) != 64:
            raise ValueError("legal brief sha256_hex must contain 64 hex chars")
        try:
            int(brief.sha256_hex, 16)
        except ValueError as error:
            raise ValueError(
                "legal brief sha256_hex must contain 64 hex chars"
            ) from error
        LocalSQLiteCaseRepository._dt(brief.created_at)
        LocalSQLiteCaseRepository._date(brief.as_of_date)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LegalBriefRef:
        return LegalBriefRef(
            legal_brief_id=row["legal_brief_id"],
            case_id=row["case_id"],
            snapshot_id=row["snapshot_id"],
            schema_version=row["schema_version"],
            catalog_version=row["catalog_version"],
            as_of_date=LocalSQLiteCaseRepository._parse_date(
                row["as_of_date"]
            ),
            proceeding_type=ProceedingType(row["proceeding_type"]),
            byte_size=row["byte_size"],
            sha256_hex=row["sha256_hex"],
            storage_key=row["storage_key"],
            created_at=LocalSQLiteCaseRepository._parse_dt(
                row["created_at"]
            ),
            created_by=row["created_by"],
        )

    def save_brief(self, brief: LegalBriefRef, event: CaseEvent) -> None:
        self._validate_brief(brief)
        if not isinstance(event, CaseEvent):
            raise TypeError("event must be a CaseEvent")
        if event.case_id != brief.case_id:
            raise RepositoryConflictError(
                "Legal brief and audit event must belong to the same case."
            )
        if event.event_type is not CaseEventType.LEGAL_BRIEF_SAVED:
            raise ValueError("legal brief event must be LEGAL_BRIEF_SAVED")
        if event.actor_id != brief.created_by:
            raise RepositoryConflictError(
                "Legal brief creator and audit actor must match."
            )
        LocalSQLiteCaseRepository._validate_event_payload(event.payload)
        LocalSQLiteCaseRepository._dt(event.occurred_at)

        with self._connect() as connection:
            snapshot = connection.execute(
                """
                SELECT case_id FROM analysis_snapshots
                WHERE snapshot_id = ?
                """,
                (brief.snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise RepositoryNotFoundError(
                    "Legal brief analysis snapshot does not exist."
                )
            if snapshot["case_id"] != brief.case_id:
                raise RepositoryConflictError(
                    "Legal brief snapshot belongs to another case."
                )
            try:
                connection.execute(
                    """
                    INSERT INTO legal_briefs(
                        legal_brief_id, case_id, snapshot_id,
                        schema_version, catalog_version, as_of_date,
                        proceeding_type, byte_size, sha256_hex,
                        storage_key, created_at, created_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        brief.legal_brief_id,
                        brief.case_id,
                        brief.snapshot_id,
                        brief.schema_version,
                        brief.catalog_version,
                        LocalSQLiteCaseRepository._date(brief.as_of_date),
                        brief.proceeding_type.value,
                        brief.byte_size,
                        brief.sha256_hex.lower(),
                        brief.storage_key,
                        LocalSQLiteCaseRepository._dt(brief.created_at),
                        brief.created_by,
                    ),
                )
                self._cases._insert_event(connection, event)
            except sqlite3.IntegrityError as error:
                raise RepositoryConflictError(
                    "Legal brief could not be persisted due to an identity "
                    "or relationship conflict."
                ) from error

    def get_brief_ref(
        self,
        legal_brief_id: str,
    ) -> Optional[LegalBriefRef]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM legal_briefs
                WHERE legal_brief_id = ?
                """,
                (legal_brief_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_brief_refs(self, snapshot_id: str) -> List[LegalBriefRef]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM legal_briefs
                WHERE snapshot_id = ?
                ORDER BY created_at ASC, legal_brief_id ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]
