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


_SCHEMA_VERSION = 1
_PROHIBITED_EVENT_KEYS = frozenset(
    {
        "raw_text",
        "source_text",
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
            elif int(current["value"]) != _SCHEMA_VERSION:
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

    def update_case(self, case: CaseRecord) -> None:
        with self._connect() as connection:
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

    def add_document_ref(self, document: StoredDocumentRef) -> None:
        if len(document.sha256_hex) != 64:
            raise ValueError("document sha256_hex must contain 64 hex chars")
        try:
            int(document.sha256_hex, 16)
        except ValueError as error:
            raise ValueError(
                "document sha256_hex must contain 64 hex chars"
            ) from error

        with self._connect() as connection:
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

    def append_event(self, event: CaseEvent) -> None:
        payload_json = self._validate_event_payload(event.payload)
        with self._connect() as connection:
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
