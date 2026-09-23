"""Sanitized runtime preflight for Dwaar production readiness."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pymupdf as fitz
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
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
    validate_document_key_id,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


def _object_root_from_environment(
    environment: Optional[Mapping[str, str]],
) -> str:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_OBJECT_ROOT")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("object root is not configured")
    return str(Path(value.strip()).expanduser())


def _document_key_id_from_environment(
    environment: Optional[Mapping[str, str]],
) -> str:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_DOCUMENT_KEY_ID")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("document key ID is not configured")
    try:
        return validate_document_key_id(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("document key ID is invalid") from error


def _document_key_from_environment(
    environment: Optional[Mapping[str, str]],
) -> bytes:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_DOCUMENT_KEY_B64")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("document key is not configured")
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("document key is invalid") from error


def _ocr_runtime_available() -> bool:
    """Exercise the same PyMuPDF/Tesseract path used for scanned notices.

    The probe document is generated in memory and contains no user data.
    Exception details are deliberately discarded because readiness output is
    operator-safe and must not leak runtime paths or library internals.
    """
    document = None
    try:
        document = fitz.open()
        page = document.new_page(width=300, height=120)
        page.insert_text(
            fitz.Point(24, 64),
            "Dwaar OCR readiness probe",
            fontsize=18,
        )
        text_page = page.get_textpage_ocr(
            language="eng",
            dpi=150,
            full=True,
        )
        return text_page is not None
    except Exception:
        return False
    finally:
        if document is not None:
            document.close()


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
        object_root = _object_root_from_environment(environment)
    except ValueError:
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
        document_key = _document_key_from_environment(environment)
    except ValueError:
        pass
    checks.append(
        _check(
            RuntimeReadinessCode.DOCUMENT_KEY_CONFIGURATION,
            document_key is not None,
            "Document encryption-key configuration is valid.",
            "Document encryption-key configuration is missing or invalid.",
        )
    )

    document_key_id = None
    try:
        document_key_id = _document_key_id_from_environment(environment)
    except ValueError:
        pass
    checks.append(
        _check(
            RuntimeReadinessCode.DOCUMENT_KEY_ID_CONFIGURATION,
            document_key_id is not None,
            "Document key identity configuration is valid.",
            "Document key identity configuration is missing or invalid.",
        )
    )

    ocr_runtime_ok = _ocr_runtime_available()
    checks.append(
        _check(
            RuntimeReadinessCode.OCR_RUNTIME,
            ocr_runtime_ok,
            "Scanned-PDF OCR runtime is available.",
            (
                "Scanned-PDF OCR runtime is unavailable. "
                "Install/configure Tesseract English OCR before serving "
                "professional traffic."
            ),
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
