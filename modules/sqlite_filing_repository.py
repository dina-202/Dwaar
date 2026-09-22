"""SQLite metadata repository for filing and acknowledgement history."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    StoredDocumentRef,
)
from domain.draft_work_product_models import DraftReviewStatus
from domain.filing_models import FilingRecord
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


class LocalSQLiteFilingRepository:
    """Atomic filing metadata/document/audit persistence on the shared DB."""

    def __init__(self, db_path: str):
        self._cases = LocalSQLiteCaseRepository(db_path)
        self._db_path = self._cases.db_path

    def _connect(self) -> sqlite3.Connection:
        return self._cases._connect()

    @staticmethod
    def _validate_filing(value: FilingRecord) -> None:
        if not isinstance(value, FilingRecord):
            raise TypeError("filing must be a FilingRecord")
        for label, item in (
            ("filing_id", value.filing_id),
            ("case_id", value.case_id),
            ("approved_draft_version_id", value.approved_draft_version_id),
            ("filed_response_document_id", value.filed_response_document_id),
            ("filing_reference", value.filing_reference),
            ("filed_by", value.filed_by),
        ):
            if not isinstance(item, str) or not item:
                raise ValueError(f"{label} must be non-empty")
        if value.acknowledgement_document_id is not None and (
            not isinstance(value.acknowledgement_document_id, str)
            or not value.acknowledgement_document_id
        ):
            raise ValueError(
                "acknowledgement_document_id must be non-empty or None"
            )
        LocalSQLiteCaseRepository._dt(value.filed_at)
        LocalSQLiteCaseRepository._dt(value.recorded_at)
        if value.filed_at > value.recorded_at:
            raise ValueError("filed_at cannot be later than recorded_at")

        if value.acknowledgement_document_id is None:
            if (
                value.acknowledgement_added_at is not None
                or value.acknowledgement_added_by is not None
            ):
                raise ValueError(
                    "acknowledgement metadata requires a document"
                )
        else:
            if (
                value.acknowledgement_added_at is None
                or not value.acknowledgement_added_by
            ):
                raise ValueError(
                    "acknowledgement document requires actor/time metadata"
                )
            LocalSQLiteCaseRepository._dt(
                value.acknowledgement_added_at
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FilingRecord:
        return FilingRecord(
            filing_id=row["filing_id"],
            case_id=row["case_id"],
            approved_draft_version_id=row[
                "approved_draft_version_id"
            ],
            filed_response_document_id=row[
                "filed_response_document_id"
            ],
            acknowledgement_document_id=row[
                "acknowledgement_document_id"
            ],
            filing_reference=row["filing_reference"],
            filed_at=LocalSQLiteCaseRepository._parse_dt(
                row["filed_at"]
            ),
            filed_by=row["filed_by"],
            recorded_at=LocalSQLiteCaseRepository._parse_dt(
                row["recorded_at"]
            ),
            acknowledgement_added_at=(
                None
                if row["acknowledgement_added_at"] is None
                else LocalSQLiteCaseRepository._parse_dt(
                    row["acknowledgement_added_at"]
                )
            ),
            acknowledgement_added_by=row[
                "acknowledgement_added_by"
            ],
        )

    @staticmethod
    def _validate_document(
        document: StoredDocumentRef,
        *,
        case_id: str,
        kind: CaseDocumentKind,
    ) -> None:
        if not isinstance(document, StoredDocumentRef):
            raise TypeError("document must be StoredDocumentRef")
        if document.case_id != case_id:
            raise RepositoryConflictError(
                "Filing document belongs to another case."
            )
        if document.kind is not kind:
            raise RepositoryConflictError(
                f"Filing document must be {kind.value}."
            )
        LocalSQLiteCaseRepository._validate_document_ref(document)

    @staticmethod
    def _validate_events(
        events: List[CaseEvent],
        *,
        case_id: str,
    ) -> None:
        if (
            not isinstance(events, list)
            or not events
            or any(not isinstance(event, CaseEvent) for event in events)
        ):
            raise TypeError("events must be a non-empty CaseEvent list")
        if any(event.case_id != case_id for event in events):
            raise RepositoryConflictError(
                "Filing events belong to another case."
            )
        for event in events:
            LocalSQLiteCaseRepository._validate_event_payload(
                event.payload
            )
            LocalSQLiteCaseRepository._dt(event.occurred_at)

    def save_filing(
        self,
        filing: FilingRecord,
        filed_document: StoredDocumentRef,
        acknowledgement_document: Optional[StoredDocumentRef],
        updated_case: CaseRecord,
        events: List[CaseEvent],
    ) -> None:
        self._validate_filing(filing)
        self._validate_document(
            filed_document,
            case_id=filing.case_id,
            kind=CaseDocumentKind.FILED_RESPONSE,
        )
        if filing.filed_response_document_id != filed_document.document_id:
            raise RepositoryConflictError(
                "Filing response document identity is inconsistent."
            )

        if acknowledgement_document is None:
            if filing.acknowledgement_document_id is not None:
                raise RepositoryConflictError(
                    "Filing acknowledgement metadata is inconsistent."
                )
        else:
            self._validate_document(
                acknowledgement_document,
                case_id=filing.case_id,
                kind=CaseDocumentKind.ACKNOWLEDGEMENT,
            )
            if (
                filing.acknowledgement_document_id
                != acknowledgement_document.document_id
            ):
                raise RepositoryConflictError(
                    "Filing acknowledgement identity is inconsistent."
                )

        if not isinstance(updated_case, CaseRecord):
            raise TypeError("updated_case must be a CaseRecord")
        if updated_case.case_id != filing.case_id:
            raise RepositoryConflictError(
                "Filing case identity is inconsistent."
            )
        self._validate_events(events, case_id=filing.case_id)

        with self._connect() as connection:
            current_case = connection.execute(
                "SELECT * FROM cases WHERE case_id = ?",
                (filing.case_id,),
            ).fetchone()
            if current_case is None:
                raise RepositoryNotFoundError("Filing case does not exist.")

            draft = connection.execute(
                """
                SELECT case_id, review_status
                FROM draft_versions
                WHERE draft_version_id = ?
                """,
                (filing.approved_draft_version_id,),
            ).fetchone()
            if draft is None:
                raise RepositoryNotFoundError(
                    "Approved draft version does not exist."
                )
            if draft["case_id"] != filing.case_id:
                raise RepositoryConflictError(
                    "Approved draft belongs to another case."
                )
            if draft["review_status"] != DraftReviewStatus.APPROVED.value:
                raise RepositoryConflictError(
                    "Filing draft version is not approved."
                )

            self._cases._insert_document_ref(
                connection,
                filed_document,
            )
            if acknowledgement_document is not None:
                self._cases._insert_document_ref(
                    connection,
                    acknowledgement_document,
                )

            try:
                connection.execute(
                    """
                    INSERT INTO filing_records(
                        filing_id, case_id, approved_draft_version_id,
                        filed_response_document_id,
                        acknowledgement_document_id,
                        filing_reference, filed_at, filed_by, recorded_at,
                        acknowledgement_added_at,
                        acknowledgement_added_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        filing.filing_id,
                        filing.case_id,
                        filing.approved_draft_version_id,
                        filing.filed_response_document_id,
                        filing.acknowledgement_document_id,
                        filing.filing_reference,
                        LocalSQLiteCaseRepository._dt(
                            filing.filed_at
                        ),
                        filing.filed_by,
                        LocalSQLiteCaseRepository._dt(
                            filing.recorded_at
                        ),
                        (
                            None
                            if filing.acknowledgement_added_at is None
                            else LocalSQLiteCaseRepository._dt(
                                filing.acknowledgement_added_at
                            )
                        ),
                        filing.acknowledgement_added_by,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise RepositoryConflictError(
                    "Filing record could not be persisted due to an "
                    "identity or relationship conflict."
                ) from error

            self._cases._update_case_row(connection, updated_case)
            for event in events:
                self._cases._insert_event(connection, event)

    def get_filing(
        self,
        filing_id: str,
    ) -> Optional[FilingRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM filing_records
                WHERE filing_id = ?
                """,
                (filing_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_filings(
        self,
        case_id: str,
    ) -> List[FilingRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM filing_records
                WHERE case_id = ?
                ORDER BY filed_at ASC, filing_id ASC
                """,
                (case_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def attach_acknowledgement(
        self,
        filing: FilingRecord,
        acknowledgement_document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        self._validate_filing(filing)
        if filing.acknowledgement_document_id is None:
            raise RepositoryConflictError(
                "Updated filing must reference acknowledgement."
            )
        self._validate_document(
            acknowledgement_document,
            case_id=filing.case_id,
            kind=CaseDocumentKind.ACKNOWLEDGEMENT,
        )
        if (
            filing.acknowledgement_document_id
            != acknowledgement_document.document_id
        ):
            raise RepositoryConflictError(
                "Acknowledgement identity is inconsistent."
            )
        self._validate_events(events, case_id=filing.case_id)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM filing_records
                WHERE filing_id = ?
                """,
                (filing.filing_id,),
            ).fetchone()
            if row is None:
                raise RepositoryNotFoundError("Filing does not exist.")
            existing = self._from_row(row)
            if existing.case_id != filing.case_id:
                raise RepositoryConflictError(
                    "Filing belongs to another case."
                )
            if existing.acknowledgement_document_id is not None:
                raise RepositoryConflictError(
                    "Filing already has an acknowledgement."
                )

            immutable_before = (
                existing.approved_draft_version_id,
                existing.filed_response_document_id,
                existing.filing_reference,
                existing.filed_at,
                existing.filed_by,
                existing.recorded_at,
            )
            immutable_after = (
                filing.approved_draft_version_id,
                filing.filed_response_document_id,
                filing.filing_reference,
                filing.filed_at,
                filing.filed_by,
                filing.recorded_at,
            )
            if immutable_before != immutable_after:
                raise RepositoryConflictError(
                    "Core filing metadata is immutable."
                )

            self._cases._insert_document_ref(
                connection,
                acknowledgement_document,
            )
            connection.execute(
                """
                UPDATE filing_records
                SET acknowledgement_document_id = ?,
                    acknowledgement_added_at = ?,
                    acknowledgement_added_by = ?
                WHERE filing_id = ?
                """,
                (
                    filing.acknowledgement_document_id,
                    LocalSQLiteCaseRepository._dt(
                        filing.acknowledgement_added_at
                    ),
                    filing.acknowledgement_added_by,
                    filing.filing_id,
                ),
            )
            for event in events:
                self._cases._insert_event(connection, event)
