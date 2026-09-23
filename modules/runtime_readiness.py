"""Sanitized runtime preflight for Dwaar production readiness."""

from __future__ import annotations

import sqlite3
from typing import Mapping, Optional

from domain.runtime_readiness_models import (
    RuntimeReadinessCheck,
    RuntimeReadinessCode,
    RuntimeReadinessReport,
    RuntimeReadinessStatus,
)
from modules.encrypted_document_store import (
    EncryptedLocalDocumentStore,
    generate_storage_key,
)
from modules.runtime_access import (
    RuntimeAccessConfigurationError,
    database_path_from_environment,
)
from modules.runtime_persistence import (
    RuntimePersistenceConfigurationError,
    document_key_from_environment,
    object_root_from_environment,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


def _check(
    code: RuntimeReadinessCode,
    ok: bool,
    pass_message: str,
    fail_message: str,
) -> RuntimeReadinessCheck:
    return RuntimeReadinessCheck(
        code=code,
        status=(
            RuntimeReadinessStatus.PASS
            if ok
            else RuntimeReadinessStatus.BLOCKED
        ),
        message=pass_message if ok else fail_message,
    )


def evaluate_runtime_readiness(
    environment: Optional[Mapping[str, str]] = None,
) -> RuntimeReadinessReport:
    """Validate configured local runtime without exposing secret values.

    The storage probes use only an opaque temporary object and an empty/new
    SQLite database when the configured database does not yet exist.
    """
    checks = []

    db_path = None
    try:
        db_path = database_path_from_environment(environment)
    except RuntimeAccessConfigurationError:
        pass
    checks.append(
        _check(
            RuntimeReadinessCode.DB_CONFIGURATION,
            db_path is not None,
            "Database configuration is present.",
            "Database configuration is missing or invalid.",
        )
    )

    object_root = None
    try:
        object_root = object_root_from_environment(environment)
    except RuntimePersistenceConfigurationError:
        pass
    checks.append(
        _check(
            RuntimeReadinessCode.OBJECT_STORE_CONFIGURATION,
            object_root is not None,
            "Object-store configuration is present.",
            "Object-store configuration is missing or invalid.",
        )
    )

    document_key = None
    try:
        document_key = document_key_from_environment(environment)
    except RuntimePersistenceConfigurationError:
        pass
    checks.append(
        _check(
            RuntimeReadinessCode.DOCUMENT_KEY_CONFIGURATION,
            document_key is not None,
            "Document encryption-key configuration is valid.",
            "Document encryption-key configuration is missing or invalid.",
        )
    )

    db_open_ok = False
    db_integrity_ok = False
    if db_path is not None:
        try:
            repository = LocalSQLiteCaseRepository(db_path)
            db_open_ok = bool(repository.db_path)
        except Exception:
            db_open_ok = False

        if db_open_ok:
            try:
                with sqlite3.connect(db_path, timeout=10) as connection:
                    result = connection.execute(
                        "PRAGMA quick_check"
                    ).fetchone()
                    schema_row = connection.execute(
                        """
                        SELECT value FROM schema_meta
                        WHERE key = 'schema_version'
                        """
                    ).fetchone()
                db_integrity_ok = (
                    result is not None
                    and result[0] == "ok"
                    and schema_row is not None
                    and isinstance(schema_row[0], str)
                    and bool(schema_row[0])
                )
            except Exception:
                db_integrity_ok = False

    checks.append(
        _check(
            RuntimeReadinessCode.DB_OPEN_AND_MIGRATION,
            db_open_ok,
            "Database can open and initialize the supported schema.",
            "Database cannot open or initialize the supported schema.",
        )
    )
    checks.append(
        _check(
            RuntimeReadinessCode.DB_INTEGRITY,
            db_integrity_ok,
            "Database integrity check passed.",
            "Database integrity check did not pass.",
        )
    )

    object_round_trip_ok = False
    if object_root is not None and document_key is not None:
        storage_key = None
        store = None
        try:
            store = EncryptedLocalDocumentStore(
                object_root,
                document_key,
            )
            storage_key = generate_storage_key()
            payload = b"Dwaar runtime readiness probe"
            store.put(storage_key, payload)
            object_round_trip_ok = store.get(storage_key) == payload
        except Exception:
            object_round_trip_ok = False
        finally:
            if store is not None and storage_key is not None:
                try:
                    if store.exists(storage_key):
                        store.delete(storage_key)
                except Exception:
                    object_round_trip_ok = False

    checks.append(
        _check(
            RuntimeReadinessCode.OBJECT_STORE_ROUND_TRIP,
            object_round_trip_ok,
            "Encrypted object-store round trip passed.",
            "Encrypted object-store round trip did not pass.",
        )
    )

    return RuntimeReadinessReport(checks=tuple(checks))
