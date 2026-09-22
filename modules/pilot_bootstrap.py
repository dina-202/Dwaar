"""One-time pilot bootstrap for the first Dwaar firm administrator."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from domain.auth_models import AccessPermission, FirmAccessGrant
from domain.case_models import Firm
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


class BootstrapRefusedError(RuntimeError):
    """The database is not empty enough for first-tenant bootstrap."""


def _validate_oidc_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.startswith("OIDC-"):
        raise ValueError("user_id must be a Dwaar OIDC principal ID")
    digest = user_id[5:]
    if len(digest) != 64:
        raise ValueError("user_id must be a Dwaar OIDC principal ID")
    try:
        int(digest, 16)
    except ValueError as error:
        raise ValueError(
            "user_id must be a Dwaar OIDC principal ID"
        ) from error
    return user_id


def bootstrap_initial_firm(
    db_path: str,
    *,
    firm_name: str,
    user_id: str,
    now: datetime | None = None,
) -> tuple[Firm, FirmAccessGrant]:
    """Create the first firm + fully explicit initial administrator grant.

    This function intentionally refuses to run once any firm exists.
    """
    if not isinstance(db_path, str) or not db_path.strip():
        raise ValueError("db_path must be a non-empty string")
    if not isinstance(firm_name, str) or not firm_name.strip():
        raise ValueError("firm_name must be a non-empty string")
    display_name = firm_name.strip()
    if len(display_name) > 200:
        raise ValueError("firm_name is too long")
    resolved_user_id = _validate_oidc_user_id(user_id)

    created_at = now or datetime.now(timezone.utc)
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    # Initialize the shared schema through authoritative repository classes.
    case_repository = LocalSQLiteCaseRepository(db_path)
    LocalSQLiteAccessGrantRepository(db_path)

    path = str(Path(db_path))
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    firm = Firm(
        firm_id=f"FIRM-{uuid.uuid4().hex}",
        display_name=display_name,
        created_at=created_at,
    )
    grant = FirmAccessGrant(
        user_id=resolved_user_id,
        firm_id=firm.firm_id,
        permissions=frozenset(AccessPermission),
        active=True,
    )
    permissions_json = json.dumps(
        sorted(permission.value for permission in grant.permissions),
        separators=(",", ":"),
    )

    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_firm = connection.execute(
            "SELECT firm_id FROM firms LIMIT 1"
        ).fetchone()
        if existing_firm is not None:
            raise BootstrapRefusedError(
                "pilot bootstrap is only allowed before the first firm exists"
            )

        connection.execute(
            """
            INSERT INTO firms(firm_id, display_name, created_at)
            VALUES (?, ?, ?)
            """,
            (
                firm.firm_id,
                firm.display_name,
                firm.created_at.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO firm_access_grants(
                user_id, firm_id, permissions_json, active
            )
            VALUES (?, ?, ?, 1)
            """,
            (
                grant.user_id,
                grant.firm_id,
                permissions_json,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    # Read back through public repositories so bootstrap cannot silently
    # succeed with a shape the product itself cannot consume.
    persisted_firm = case_repository.get_firm(firm.firm_id)
    persisted_grant = LocalSQLiteAccessGrantRepository(
        db_path
    ).get_grant(grant.user_id, grant.firm_id)
    if persisted_firm != firm or persisted_grant != grant:
        raise RuntimeError("bootstrap verification failed")

    return firm, grant
