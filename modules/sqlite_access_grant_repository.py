"""SQLite persistence for firm-scoped access grants."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from domain.auth_models import AccessPermission, FirmAccessGrant


class AccessGrantConflictError(ValueError):
    """Grant could not be persisted because its firm relationship is invalid."""


class LocalSQLiteAccessGrantRepository:
    """Persistent access grants stored alongside the Dwaar case database."""

    def __init__(self, db_path: str):
        if not isinstance(db_path, str) or not db_path.strip():
            raise ValueError("db_path must be a non-empty string")
        self._db_path = str(Path(db_path))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS firm_access_grants (
                    user_id TEXT NOT NULL,
                    firm_id TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    PRIMARY KEY (user_id, firm_id),
                    FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT,
                    CHECK (active IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_firm_access_grants_user
                ON firm_access_grants(user_id, firm_id)
                """
            )

    @staticmethod
    def _validate_grant(grant: FirmAccessGrant) -> None:
        if not isinstance(grant, FirmAccessGrant):
            raise TypeError("grant must be a FirmAccessGrant")
        if not isinstance(grant.user_id, str) or not grant.user_id:
            raise ValueError("grant user_id must be non-empty")
        if not isinstance(grant.firm_id, str) or not grant.firm_id:
            raise ValueError("grant firm_id must be non-empty")
        if not isinstance(grant.permissions, frozenset):
            raise TypeError("grant permissions must be a frozenset")
        if any(
            not isinstance(permission, AccessPermission)
            for permission in grant.permissions
        ):
            raise TypeError(
                "grant permissions must contain only AccessPermission values"
            )
        if not isinstance(grant.active, bool):
            raise TypeError("grant active must be boolean")

    @staticmethod
    def _serialize_permissions(grant: FirmAccessGrant) -> str:
        return json.dumps(
            sorted(permission.value for permission in grant.permissions),
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize_permissions(raw: str) -> frozenset:
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "stored access grant permissions are invalid JSON"
            ) from error
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise RuntimeError(
                "stored access grant permissions are malformed"
            )
        if len(values) != len(set(values)):
            raise RuntimeError(
                "stored access grant permissions contain duplicates"
            )
        try:
            return frozenset(AccessPermission(value) for value in values)
        except ValueError as error:
            raise RuntimeError(
                "stored access grant contains an unknown permission"
            ) from error

    def save_grant(self, grant: FirmAccessGrant) -> None:
        self._validate_grant(grant)
        permissions_json = self._serialize_permissions(grant)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO firm_access_grants(
                        user_id, firm_id, permissions_json, active
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, firm_id) DO UPDATE SET
                        permissions_json = excluded.permissions_json,
                        active = excluded.active
                    """,
                    (
                        grant.user_id,
                        grant.firm_id,
                        permissions_json,
                        1 if grant.active else 0,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise AccessGrantConflictError(
                "access grant could not be persisted because the firm "
                "relationship is invalid"
            ) from error

    def get_grant(
        self,
        user_id: str,
        firm_id: str,
    ) -> Optional[FirmAccessGrant]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be non-empty")
        if not isinstance(firm_id, str) or not firm_id:
            raise ValueError("firm_id must be non-empty")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, firm_id, permissions_json, active
                FROM firm_access_grants
                WHERE user_id = ? AND firm_id = ?
                """,
                (user_id, firm_id),
            ).fetchone()

        if row is None:
            return None
        return FirmAccessGrant(
            user_id=row["user_id"],
            firm_id=row["firm_id"],
            permissions=self._deserialize_permissions(
                row["permissions_json"]
            ),
            active=bool(row["active"]),
        )

    def list_grants_for_firm(
        self,
        firm_id: str,
    ) -> List[FirmAccessGrant]:
        if not isinstance(firm_id, str) or not firm_id:
            raise ValueError("firm_id must be non-empty")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, firm_id, permissions_json, active
                FROM firm_access_grants
                WHERE firm_id = ?
                ORDER BY user_id ASC
                """,
                (firm_id,),
            ).fetchall()

        return [
            FirmAccessGrant(
                user_id=row["user_id"],
                firm_id=row["firm_id"],
                permissions=self._deserialize_permissions(
                    row["permissions_json"]
                ),
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def list_grants_for_user(
        self,
        user_id: str,
    ) -> List[FirmAccessGrant]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be non-empty")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, firm_id, permissions_json, active
                FROM firm_access_grants
                WHERE user_id = ?
                ORDER BY firm_id ASC
                """,
                (user_id,),
            ).fetchall()

        return [
            FirmAccessGrant(
                user_id=row["user_id"],
                firm_id=row["firm_id"],
                permissions=self._deserialize_permissions(
                    row["permissions_json"]
                ),
                active=bool(row["active"]),
            )
            for row in rows
        ]
