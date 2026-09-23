"""SQLite metadata repository for encrypted snapshot-bound fact reviews."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from domain.case_models import CaseEvent, CaseEventType
from domain.fact_review_models import FactReviewDecision, FactReviewRef
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


class LocalSQLiteFactReviewRepository:
    """Fact-review metadata/audit persistence against the shared Dwaar DB."""

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
    def _validate_review(cls, review: FactReviewRef) -> None:
        if not isinstance(review, FactReviewRef):
            raise TypeError("review must be a FactReviewRef")
        for label, value in (
            ("review_id", review.review_id),
            ("case_id", review.case_id),
            ("snapshot_id", review.snapshot_id),
            ("fact_id", review.fact_id),
            ("storage_key", review.storage_key),
            ("reviewed_by", review.reviewed_by),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be non-empty")
        if review.byte_size <= 0:
            raise ValueError("byte_size must be positive")
        cls._hash("fact_fingerprint", review.fact_fingerprint)
        cls._hash("source_text_sha256", review.source_text_sha256)
        cls._hash("sha256_hex", review.sha256_hex)
        if review.decision not in (
            FactReviewDecision.CONFIRMED,
            FactReviewDecision.REJECTED,
        ):
            raise ValueError("decision must be CONFIRMED or REJECTED")
        LocalSQLiteCaseRepository._dt(review.reviewed_at)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FactReviewRef:
        return FactReviewRef(
            review_id=row["review_id"],
            case_id=row["case_id"],
            snapshot_id=row["snapshot_id"],
            fact_id=row["fact_id"],
            fact_fingerprint=row["fact_fingerprint"],
            source_text_sha256=row["source_text_sha256"],
            decision=FactReviewDecision(row["decision"]),
            byte_size=row["byte_size"],
            sha256_hex=row["sha256_hex"],
            storage_key=row["storage_key"],
            reviewed_at=LocalSQLiteCaseRepository._parse_dt(
                row["reviewed_at"]
            ),
            reviewed_by=row["reviewed_by"],
        )

    def save_review(
        self,
        review: FactReviewRef,
        event: CaseEvent,
    ) -> None:
        self._validate_review(review)
        if not isinstance(event, CaseEvent):
            raise TypeError("event must be a CaseEvent")
        if event.case_id != review.case_id:
            raise RepositoryConflictError(
                "Fact review and event must belong to the same case."
            )
        if event.event_type is not CaseEventType.FACT_REVIEWED:
            raise ValueError("fact-review audit event must be FACT_REVIEWED")
        if event.actor_id != review.reviewed_by:
            raise RepositoryConflictError(
                "Fact-review actor and audit actor must match."
            )
        LocalSQLiteCaseRepository._validate_event_payload(event.payload)
        LocalSQLiteCaseRepository._dt(event.occurred_at)

        with self._connect() as connection:
            snapshot = connection.execute(
                """
                SELECT case_id
                FROM analysis_snapshots
                WHERE snapshot_id = ?
                """,
                (review.snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise RepositoryNotFoundError(
                    "Fact-review snapshot does not exist."
                )
            if snapshot["case_id"] != review.case_id:
                raise RepositoryConflictError(
                    "Fact-review snapshot belongs to another case."
                )
            try:
                connection.execute(
                    """
                    INSERT INTO fact_reviews(
                        review_id, case_id, snapshot_id, fact_id,
                        fact_fingerprint, source_text_sha256, decision,
                        byte_size, sha256_hex, storage_key, reviewed_at,
                        reviewed_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review.review_id,
                        review.case_id,
                        review.snapshot_id,
                        review.fact_id,
                        review.fact_fingerprint.lower(),
                        review.source_text_sha256.lower(),
                        review.decision.value,
                        review.byte_size,
                        review.sha256_hex.lower(),
                        review.storage_key,
                        LocalSQLiteCaseRepository._dt(review.reviewed_at),
                        review.reviewed_by,
                    ),
                )
                self._cases._insert_event(connection, event)
            except sqlite3.IntegrityError as error:
                raise RepositoryConflictError(
                    "Fact review could not be persisted due to an identity "
                    "or relationship conflict."
                ) from error

    def get_review_ref(
        self,
        review_id: str,
    ) -> Optional[FactReviewRef]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fact_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_review_refs(
        self,
        snapshot_id: str,
    ) -> List[FactReviewRef]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM fact_reviews
                WHERE snapshot_id = ?
                ORDER BY reviewed_at ASC, review_id ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]
