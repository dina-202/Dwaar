"""Local SQLite implementation of the Phase-3D CaseRepository port.

This repository persists structured case metadata only. It never stores raw
notice/evidence document bytes; those belong behind DocumentStore.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseSnapshot,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
    TaxRegistration,
)
from domain.models import NoticeForm, ProceedingType


_SCHEMA_VERSION = 6
_PROHIBITED_EVENT_KEYS = frozenset(
    {
        "raw_text",
        "source_text",
        "reviewer_note",
        "draft_text",
        "document_bytes",
        "payload_bytes",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "api_key",
        "authorization",
    }
)


class RepositoryConflictError(ValueError):
    """A stable identifier already exists or an immutable identity changed."""


class RepositoryNotFoundError(LookupError):
    """A required repository record does not exist."""


class LocalSQLiteCaseRepository:
    """Single-node pilot repository for structured metadata.

    A fresh sqlite3 connection is opened for each operation. This avoids
    leaking connection/thread assumptions into Streamlit or future callers.
    SQLite foreign keys are enabled on every connection.
    """

    def __init__(self, db_path: str):
        if not isinstance(db_path, str) or not db_path.strip():
            raise ValueError("db_path must be a non-empty string")
        self._db_path = str(Path(db_path))
        self._initialize()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS firms (
                    firm_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    firm_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS tax_registrations (
                    registration_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    firm_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    registration_id TEXT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proceeding_type TEXT NOT NULL,
                    notice_form TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    response_deadline TEXT,
                    assigned_to TEXT,
                    reviewer_id TEXT,
                    closed_at TEXT,
                    FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (registration_id)
                        REFERENCES tax_registrations(registration_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS ix_cases_firm_opened
                    ON cases(firm_id, opened_at DESC, case_id);

                CREATE TABLE IF NOT EXISTS case_documents (
                    document_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_hex TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    CHECK (byte_size >= 0)
                );

                CREATE INDEX IF NOT EXISTS ix_case_documents_case_created
                    ON case_documents(case_id, created_at, document_id);

                CREATE TABLE IF NOT EXISTS case_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor_id TEXT,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS ix_case_events_case_occurred
                    ON case_events(case_id, occurred_at, event_id);

                CREATE TABLE IF NOT EXISTS analysis_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    source_document_id TEXT NOT NULL,
                    source_document_sha256 TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    engine_version TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_hex TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (source_document_id)
                        REFERENCES case_documents(document_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    CHECK (byte_size >= 0)
                );

                CREATE INDEX IF NOT EXISTS ix_analysis_snapshots_case_created
                    ON analysis_snapshots(case_id, created_at, snapshot_id);

                CREATE TABLE IF NOT EXISTS evidence_reviews (
                    review_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source_page INTEGER NOT NULL,
                    source_text_sha256 TEXT NOT NULL,
                    candidate_fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_hex TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    reviewed_at TEXT NOT NULL,
                    reviewed_by TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (snapshot_id)
                        REFERENCES analysis_snapshots(snapshot_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (document_id)
                        REFERENCES case_documents(document_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    UNIQUE (snapshot_id, candidate_fingerprint),
                    CHECK (source_page >= 1),
                    CHECK (byte_size > 0)
                );

                CREATE INDEX IF NOT EXISTS ix_evidence_reviews_snapshot_time
                    ON evidence_reviews(
                        snapshot_id, reviewed_at, review_id
                    );

                CREATE TABLE IF NOT EXISTS draft_versions (
                    draft_version_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    source_snapshot_id TEXT NOT NULL,
                    parent_draft_version_id TEXT,
                    version_number INTEGER NOT NULL,
                    generated_baseline INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_hex TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    review_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    approved_at TEXT,
                    approved_by TEXT,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (source_snapshot_id)
                        REFERENCES analysis_snapshots(snapshot_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (parent_draft_version_id)
                        REFERENCES draft_versions(draft_version_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    UNIQUE (case_id, version_number),
                    CHECK (version_number >= 1),
                    CHECK (generated_baseline IN (0, 1)),
                    CHECK (byte_size > 0)
                );

                CREATE INDEX IF NOT EXISTS ix_draft_versions_case_version
                    ON draft_versions(case_id, version_number);

                CREATE TABLE IF NOT EXISTS legal_briefs (
                    legal_brief_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    catalog_version TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    proceeding_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_hex TEXT NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (snapshot_id)
                        REFERENCES analysis_snapshots(snapshot_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    CHECK (byte_size > 0)
                );

                CREATE INDEX IF NOT EXISTS ix_legal_briefs_snapshot_created
                    ON legal_briefs(snapshot_id, created_at, legal_brief_id);

                CREATE TABLE IF NOT EXISTS filing_records (
                    filing_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    approved_draft_version_id TEXT NOT NULL,
                    filed_response_document_id TEXT NOT NULL,
                    acknowledgement_document_id TEXT,
                    filing_reference TEXT NOT NULL,
                    filed_at TEXT NOT NULL,
                    filed_by TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    acknowledgement_added_at TEXT,
                    acknowledgement_added_by TEXT,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (approved_draft_version_id)
                        REFERENCES draft_versions(draft_version_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (filed_response_document_id)
                        REFERENCES case_documents(document_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (acknowledgement_document_id)
                        REFERENCES case_documents(document_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS ix_filing_records_case_time
                    ON filing_records(case_id, filed_at, filing_id);
                """
            )
            current = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if current is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(_SCHEMA_VERSION)),
                )
            else:
                current_version = int(current["value"])
                if current_version in (1, 2, 3, 4, 5):
                    # v2 analysis_snapshots; v3 evidence_reviews;
                    # v4 draft_versions; v5 filing_records;
                    # v6 snapshot-bound legal_briefs. Tables are created
                    # idempotently above; this bump records migration.
                    connection.execute(
                        """
                        UPDATE schema_meta
                        SET value = ?
                        WHERE key = 'schema_version'
                        """,
                        (str(_SCHEMA_VERSION),),
                    )
                elif current_version != _SCHEMA_VERSION:
                    raise RuntimeError(
                        "Unsupported Dwaar SQLite schema version: "
                        f"{current['value']}"
                    )

    @staticmethod
    def _dt(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("persisted datetimes must be timezone-aware")
        return value.isoformat()

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise RuntimeError("stored datetime is unexpectedly naive")
        return parsed

    @staticmethod
    def _date(value: Optional[date]) -> Optional[str]:
        return None if value is None else value.isoformat()

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[date]:
        return None if value is None else date.fromisoformat(value)

    @staticmethod
    def _execute_insert(
        connection: sqlite3.Connection,
        sql: str,
        parameters: tuple,
        label: str,
    ) -> None:
        try:
            connection.execute(sql, parameters)
        except sqlite3.IntegrityError as error:
            raise RepositoryConflictError(
                f"{label} could not be persisted due to an identity or "
                "relationship conflict."
            ) from error

    def create_firm(self, firm: Firm) -> None:
        with self._connect() as connection:
            self._execute_insert(
                connection,
                """
                INSERT INTO firms(firm_id, display_name, created_at)
                VALUES (?, ?, ?)
                """,
                (firm.firm_id, firm.display_name, self._dt(firm.created_at)),
                "Firm",
            )

    def get_firm(self, firm_id: str) -> Optional[Firm]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM firms WHERE firm_id = ?", (firm_id,)
            ).fetchone()
        if row is None:
            return None
        return Firm(
            firm_id=row["firm_id"],
            display_name=row["display_name"],
            created_at=self._parse_dt(row["created_at"]),
        )

    def create_client(self, client: Client) -> None:
        with self._connect() as connection:
            self._execute_insert(
                connection,
                """
                INSERT INTO clients(client_id, firm_id, display_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    client.client_id,
                    client.firm_id,
                    client.display_name,
                    self._dt(client.created_at),
                ),
                "Client",
            )

    def get_client(self, client_id: str) -> Optional[Client]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        if row is None:
            return None
        return Client(
            client_id=row["client_id"],
            firm_id=row["firm_id"],
            display_name=row["display_name"],
            created_at=self._parse_dt(row["created_at"]),
        )

    def list_clients(self, firm_id: str) -> List[Client]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM clients
                WHERE firm_id = ?
                ORDER BY display_name COLLATE NOCASE ASC,
                         created_at ASC, client_id ASC
                """,
                (firm_id,),
            ).fetchall()
        return [
            Client(
                client_id=row["client_id"],
                firm_id=row["firm_id"],
                display_name=row["display_name"],
                created_at=self._parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    def create_registration(self, registration: TaxRegistration) -> None:
        with self._connect() as connection:
            self._execute_insert(
                connection,
                """
                INSERT INTO tax_registrations(
                    registration_id, client_id, jurisdiction,
                    identifier_type, identifier_value, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.registration_id,
                    registration.client_id,
                    registration.jurisdiction,
                    registration.identifier_type,
                    registration.identifier_value,
                    self._dt(registration.created_at),
                ),
                "Tax registration",
            )

    def get_registration(
        self, registration_id: str
    ) -> Optional[TaxRegistration]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tax_registrations
                WHERE registration_id = ?
                """,
                (registration_id,),
            ).fetchone()
        if row is None:
            return None
        return TaxRegistration(
            registration_id=row["registration_id"],
            client_id=row["client_id"],
            jurisdiction=row["jurisdiction"],
            identifier_type=row["identifier_type"],
            identifier_value=row["identifier_value"],
            created_at=self._parse_dt(row["created_at"]),
        )

    def list_registrations(
        self, client_id: str
    ) -> List[TaxRegistration]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tax_registrations
                WHERE client_id = ?
                ORDER BY identifier_type ASC,
                         identifier_value ASC,
                         created_at ASC,
                         registration_id ASC
                """,
                (client_id,),
            ).fetchall()
        return [
            TaxRegistration(
                registration_id=row["registration_id"],
                client_id=row["client_id"],
                jurisdiction=row["jurisdiction"],
                identifier_type=row["identifier_type"],
                identifier_value=row["identifier_value"],
                created_at=self._parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    def _validate_case_relationships(
        self, connection: sqlite3.Connection, case: CaseRecord
    ) -> None:
        firm = connection.execute(
            "SELECT firm_id FROM firms WHERE firm_id = ?",
            (case.firm_id,),
        ).fetchone()
        if firm is None:
            raise RepositoryNotFoundError("Case firm does not exist.")

        client = connection.execute(
            "SELECT firm_id FROM clients WHERE client_id = ?",
            (case.client_id,),
        ).fetchone()
        if client is None:
            raise RepositoryNotFoundError("Case client does not exist.")
        if client["firm_id"] != case.firm_id:
            raise RepositoryConflictError(
                "Case client does not belong to the supplied firm."
            )

        if case.registration_id is not None:
            registration = connection.execute(
                """
                SELECT client_id FROM tax_registrations
                WHERE registration_id = ?
                """,
                (case.registration_id,),
            ).fetchone()
            if registration is None:
                raise RepositoryNotFoundError(
                    "Case tax registration does not exist."
                )
            if registration["client_id"] != case.client_id:
                raise RepositoryConflictError(
                    "Case tax registration does not belong to the client."
                )

    def create_case(self, case: CaseRecord) -> None:
        with self._connect() as connection:
            self._validate_case_relationships(connection, case)
            self._execute_insert(
                connection,
                """
                INSERT INTO cases(
                    case_id, firm_id, client_id, registration_id, title,
                    status, proceeding_type, notice_form, opened_at,
                    response_deadline, assigned_to, reviewer_id, closed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.firm_id,
                    case.client_id,
                    case.registration_id,
                    case.title,
                    case.status.value,
                    case.proceeding_type.value,
                    case.notice_form.value,
                    self._dt(case.opened_at),
                    self._date(case.response_deadline),
                    case.assigned_to,
                    case.reviewer_id,
                    (
                        None
                        if case.closed_at is None
                        else self._dt(case.closed_at)
                    ),
                ),
                "Case",
            )

    def create_case_intake(
        self,
        client: Client,
        registration: Optional[TaxRegistration],
        case: CaseRecord,
        document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        """Atomically create client/registration/case/notice metadata/events."""
        if not isinstance(client, Client):
            raise TypeError("client must be a Client")
        if registration is not None and not isinstance(
            registration, TaxRegistration
        ):
            raise TypeError(
                "registration must be a TaxRegistration or None"
            )
        if not isinstance(case, CaseRecord):
            raise TypeError("case must be a CaseRecord")
        if not isinstance(document, StoredDocumentRef):
            raise TypeError("document must be a StoredDocumentRef")
        if (
            not isinstance(events, list)
            or not events
            or any(not isinstance(event, CaseEvent) for event in events)
        ):
            raise TypeError("events must be a non-empty list of CaseEvent")

        if client.firm_id != case.firm_id:
            raise RepositoryConflictError(
                "Intake client and case must belong to the same firm."
            )
        if case.client_id != client.client_id:
            raise RepositoryConflictError(
                "Intake case must reference the supplied client."
            )
        if registration is None:
            if case.registration_id is not None:
                raise RepositoryConflictError(
                    "Case registration_id requires a supplied registration."
                )
        else:
            if registration.client_id != client.client_id:
                raise RepositoryConflictError(
                    "Registration must belong to the supplied client."
                )
            if case.registration_id != registration.registration_id:
                raise RepositoryConflictError(
                    "Case must reference the supplied registration."
                )
        if document.case_id != case.case_id:
            raise RepositoryConflictError(
                "Notice document must belong to the intake case."
            )
        if any(event.case_id != case.case_id for event in events):
            raise RepositoryConflictError(
                "All intake events must belong to the intake case."
            )

        self._validate_document_ref(document)
        for event in events:
            self._validate_event_payload(event.payload)
            self._dt(event.occurred_at)
        self._dt(client.created_at)
        self._dt(case.opened_at)
        self._dt(document.created_at)
        if registration is not None:
            self._dt(registration.created_at)

        with self._connect() as connection:
            firm = connection.execute(
                "SELECT firm_id FROM firms WHERE firm_id = ?",
                (case.firm_id,),
            ).fetchone()
            if firm is None:
                raise RepositoryNotFoundError(
                    "Intake firm does not exist."
                )

            self._execute_insert(
                connection,
                """
                INSERT INTO clients(
                    client_id, firm_id, display_name, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    client.client_id,
                    client.firm_id,
                    client.display_name,
                    self._dt(client.created_at),
                ),
                "Client",
            )

            if registration is not None:
                self._execute_insert(
                    connection,
                    """
                    INSERT INTO tax_registrations(
                        registration_id, client_id, jurisdiction,
                        identifier_type, identifier_value, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registration.registration_id,
                        registration.client_id,
                        registration.jurisdiction,
                        registration.identifier_type,
                        registration.identifier_value,
                        self._dt(registration.created_at),
                    ),
                    "Tax registration",
                )

            self._execute_insert(
                connection,
                """
                INSERT INTO cases(
                    case_id, firm_id, client_id, registration_id, title,
                    status, proceeding_type, notice_form, opened_at,
                    response_deadline, assigned_to, reviewer_id, closed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.firm_id,
                    case.client_id,
                    case.registration_id,
                    case.title,
                    case.status.value,
                    case.proceeding_type.value,
                    case.notice_form.value,
                    self._dt(case.opened_at),
                    self._date(case.response_deadline),
                    case.assigned_to,
                    case.reviewer_id,
                    (
                        None
                        if case.closed_at is None
                        else self._dt(case.closed_at)
                    ),
                ),
                "Case",
            )
            self._insert_document_ref(connection, document)
            for event in events:
                self._insert_event(connection, event)


    def create_existing_client_case_intake(
        self,
        case: CaseRecord,
        document: StoredDocumentRef,
        events: List[CaseEvent],
    ) -> None:
        """Atomically create a case/notice/events for an existing client."""
        if not isinstance(case, CaseRecord):
            raise TypeError("case must be a CaseRecord")
        if not isinstance(document, StoredDocumentRef):
            raise TypeError("document must be a StoredDocumentRef")
        if (
            not isinstance(events, list)
            or not events
            or any(not isinstance(event, CaseEvent) for event in events)
        ):
            raise TypeError("events must be a non-empty list of CaseEvent")
        if document.case_id != case.case_id:
            raise RepositoryConflictError(
                "Notice document must belong to the intake case."
            )
        if any(event.case_id != case.case_id for event in events):
            raise RepositoryConflictError(
                "All intake events must belong to the intake case."
            )

        self._validate_document_ref(document)
        self._dt(case.opened_at)
        self._dt(document.created_at)
        for event in events:
            self._validate_event_payload(event.payload)
            self._dt(event.occurred_at)

        with self._connect() as connection:
            self._validate_case_relationships(connection, case)
            self._execute_insert(
                connection,
                """
                INSERT INTO cases(
                    case_id, firm_id, client_id, registration_id, title,
                    status, proceeding_type, notice_form, opened_at,
                    response_deadline, assigned_to, reviewer_id, closed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.firm_id,
                    case.client_id,
                    case.registration_id,
                    case.title,
                    case.status.value,
                    case.proceeding_type.value,
                    case.notice_form.value,
                    self._dt(case.opened_at),
                    self._date(case.response_deadline),
                    case.assigned_to,
                    case.reviewer_id,
                    (
                        None
                        if case.closed_at is None
                        else self._dt(case.closed_at)
                    ),
                ),
                "Case",
            )
            self._insert_document_ref(connection, document)
            for event in events:
                self._insert_event(connection, event)


    @staticmethod
    def _case_from_row(row: sqlite3.Row) -> CaseRecord:
        return CaseRecord(
            case_id=row["case_id"],
            firm_id=row["firm_id"],
            client_id=row["client_id"],
            registration_id=row["registration_id"],
            title=row["title"],
            status=CaseStatus(row["status"]),
            proceeding_type=ProceedingType(row["proceeding_type"]),
            notice_form=NoticeForm(row["notice_form"]),
            opened_at=LocalSQLiteCaseRepository._parse_dt(
                row["opened_at"]
            ),
            response_deadline=LocalSQLiteCaseRepository._parse_date(
                row["response_deadline"]
            ),
            assigned_to=row["assigned_to"],
            reviewer_id=row["reviewer_id"],
            closed_at=(
                None
                if row["closed_at"] is None
                else LocalSQLiteCaseRepository._parse_dt(row["closed_at"])
            ),
        )

    def get_case(self, case_id: str) -> Optional[CaseRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return None if row is None else self._case_from_row(row)

    def list_cases(self, firm_id: str) -> List[CaseRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM cases
                WHERE firm_id = ?
                ORDER BY opened_at DESC, case_id ASC
                """,
                (firm_id,),
            ).fetchall()
        return [self._case_from_row(row) for row in rows]

    def list_cases_for_client(
        self, client_id: str
    ) -> List[CaseRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM cases
                WHERE client_id = ?
                ORDER BY opened_at DESC, case_id ASC
                """,
                (client_id,),
            ).fetchall()
        return [self._case_from_row(row) for row in rows]

    def _update_case_row(
        self,
        connection: sqlite3.Connection,
        case: CaseRecord,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM cases WHERE case_id = ?", (case.case_id,)
        ).fetchone()
        if current is None:
            raise RepositoryNotFoundError("Case does not exist.")

        existing = self._case_from_row(current)
        immutable_before = (
            existing.firm_id,
            existing.client_id,
            existing.registration_id,
            existing.proceeding_type,
            existing.notice_form,
            existing.opened_at,
        )
        immutable_after = (
            case.firm_id,
            case.client_id,
            case.registration_id,
            case.proceeding_type,
            case.notice_form,
            case.opened_at,
        )
        if immutable_before != immutable_after:
            raise RepositoryConflictError(
                "Case identity/ownership/proceeding fields are immutable."
            )

        if case.status is CaseStatus.CLOSED:
            if case.closed_at is None:
                raise RepositoryConflictError(
                    "Closed cases require closed_at."
                )
        elif case.closed_at is not None:
            raise RepositoryConflictError(
                "Only closed cases may have closed_at."
            )

        connection.execute(
            """
            UPDATE cases
            SET title = ?, status = ?, response_deadline = ?,
                assigned_to = ?, reviewer_id = ?, closed_at = ?
            WHERE case_id = ?
            """,
            (
                case.title,
                case.status.value,
                self._date(case.response_deadline),
                case.assigned_to,
                case.reviewer_id,
                (
                    None
                    if case.closed_at is None
                    else self._dt(case.closed_at)
                ),
                case.case_id,
            ),
        )

    def update_case(self, case: CaseRecord) -> None:
        with self._connect() as connection:
            self._update_case_row(connection, case)

    def update_case_with_events(
        self,
        case: CaseRecord,
        events: List[CaseEvent],
    ) -> None:
        """Atomically persist one operational case update and audit events."""
        if not isinstance(case, CaseRecord):
            raise TypeError("case must be a CaseRecord")
        if (
            not isinstance(events, list)
            or not events
            or any(not isinstance(event, CaseEvent) for event in events)
        ):
            raise TypeError("events must be a non-empty list of CaseEvent")
        if any(event.case_id != case.case_id for event in events):
            raise RepositoryConflictError(
                "Case update events must belong to the updated case."
            )
        for event in events:
            self._validate_event_payload(event.payload)
            self._dt(event.occurred_at)

        with self._connect() as connection:
            self._update_case_row(connection, case)
            for event in events:
                self._insert_event(connection, event)


    @staticmethod
    def _validate_document_ref(document: StoredDocumentRef) -> None:
        if not isinstance(document, StoredDocumentRef):
            raise TypeError("document must be a StoredDocumentRef")
        if len(document.sha256_hex) != 64:
            raise ValueError("document sha256_hex must contain 64 hex chars")
        try:
            int(document.sha256_hex, 16)
        except ValueError as error:
            raise ValueError(
                "document sha256_hex must contain 64 hex chars"
            ) from error

    def _insert_document_ref(
        self,
        connection: sqlite3.Connection,
        document: StoredDocumentRef,
    ) -> None:
        self._validate_document_ref(document)
        self._execute_insert(
            connection,
            """
            INSERT INTO case_documents(
                document_id, case_id, kind, original_filename, media_type,
                byte_size, sha256_hex, storage_key, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                document.case_id,
                document.kind.value,
                document.original_filename,
                document.media_type,
                document.byte_size,
                document.sha256_hex.lower(),
                document.storage_key,
                self._dt(document.created_at),
            ),
            "Document reference",
        )

    def add_document_ref(self, document: StoredDocumentRef) -> None:
        with self._connect() as connection:
            self._insert_document_ref(connection, document)

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> StoredDocumentRef:
        return StoredDocumentRef(
            document_id=row["document_id"],
            case_id=row["case_id"],
            kind=CaseDocumentKind(row["kind"]),
            original_filename=row["original_filename"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            sha256_hex=row["sha256_hex"],
            storage_key=row["storage_key"],
            created_at=LocalSQLiteCaseRepository._parse_dt(
                row["created_at"]
            ),
        )

    def list_document_refs(self, case_id: str) -> List[StoredDocumentRef]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM case_documents
                WHERE case_id = ?
                ORDER BY created_at ASC, document_id ASC
                """,
                (case_id,),
            ).fetchall()
        return [self._document_from_row(row) for row in rows]

    @staticmethod
    def _validate_event_payload(payload) -> str:
        if not isinstance(payload, dict):
            raise ValueError("event payload must be a dictionary")
        if len(payload) > 50:
            raise ValueError("event payload contains too many fields")

        normalized = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("event payload keys and values must be strings")
            normalized_key = key.strip()
            if not normalized_key or len(normalized_key) > 100:
                raise ValueError("event payload key is invalid")
            if normalized_key.lower() in _PROHIBITED_EVENT_KEYS:
                raise ValueError(
                    f"event payload field '{normalized_key}' is prohibited"
                )
            if len(value) > 1000:
                raise ValueError("event payload value exceeds safe metadata size")
            normalized[normalized_key] = value

        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        event: CaseEvent,
    ) -> None:
        if not isinstance(event, CaseEvent):
            raise TypeError("event must be a CaseEvent")
        payload_json = self._validate_event_payload(event.payload)
        self._execute_insert(
            connection,
            """
            INSERT INTO case_events(
                event_id, case_id, event_type, occurred_at,
                actor_id, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.case_id,
                event.event_type.value,
                self._dt(event.occurred_at),
                event.actor_id,
                payload_json,
            ),
            "Case event",
        )

    def add_document_with_event(
        self,
        document: StoredDocumentRef,
        event: CaseEvent,
    ) -> None:
        """Persist document metadata and its audit event atomically."""
        if not isinstance(document, StoredDocumentRef):
            raise TypeError("document must be a StoredDocumentRef")
        if not isinstance(event, CaseEvent):
            raise TypeError("event must be a CaseEvent")
        if document.case_id != event.case_id:
            raise RepositoryConflictError(
                "Document and audit event must belong to the same case."
            )

        # Validate outside the transaction where possible so malformed
        # metadata never begins a write transaction.
        self._validate_document_ref(document)
        self._validate_event_payload(event.payload)
        self._dt(document.created_at)
        self._dt(event.occurred_at)

        with self._connect() as connection:
            try:
                self._insert_document_ref(connection, document)
                self._insert_event(connection, event)
            except Exception:
                # sqlite context manager rolls the transaction back when
                # an exception exits this block.
                raise

    def append_event(self, event: CaseEvent) -> None:
        with self._connect() as connection:
            self._insert_event(connection, event)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> CaseEvent:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in payload.items()
        ):
            raise RuntimeError("Stored event payload is invalid.")
        return CaseEvent(
            event_id=row["event_id"],
            case_id=row["case_id"],
            event_type=CaseEventType(row["event_type"]),
            occurred_at=LocalSQLiteCaseRepository._parse_dt(
                row["occurred_at"]
            ),
            actor_id=row["actor_id"],
            payload=payload,
        )

    def list_events(self, case_id: str) -> List[CaseEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM case_events
                WHERE case_id = ?
                ORDER BY occurred_at ASC, event_id ASC
                """,
                (case_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def get_snapshot(self, case_id: str) -> Optional[CaseSnapshot]:
        case = self.get_case(case_id)
        if case is None:
            return None
        return CaseSnapshot(
            case=case,
            documents=self.list_document_refs(case_id),
            events=self.list_events(case_id),
        )
