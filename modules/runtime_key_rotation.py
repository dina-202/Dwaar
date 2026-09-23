"""Clean-target document-master-key rotation rehearsal for Dwaar."""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    validate_document_key_id,
)
from modules.runtime_storage_audit import (
    RuntimeStorageAuditError,
    audit_runtime_storage,
    referenced_storage_keys,
)


class RuntimeKeyRotationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeKeyRotationReport:
    old_key_id: str
    new_key_id: str
    object_count: int
    schema_version: int


_SUPPORTED_SCHEMA_VERSION = 7


def _validate_key(value: bytes, label: str) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{label} must be exactly 32 bytes")


def _validate_id(value: str, label: str) -> str:
    try:
        return validate_document_key_id(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError(f"{label} is invalid") from error


def _validate_database(connection: sqlite3.Connection) -> int:
    quick = connection.execute("PRAGMA quick_check").fetchone()
    if quick is None or quick[0] != "ok":
        raise RuntimeKeyRotationError("database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeKeyRotationError("database foreign-key check failed")
    row = connection.execute(
        """
        SELECT value FROM schema_meta
        WHERE key = 'schema_version'
        """
    ).fetchone()
    if row is None:
        raise RuntimeKeyRotationError("database schema metadata is missing")
    try:
        version = int(row[0])
    except (TypeError, ValueError) as error:
        raise RuntimeKeyRotationError(
            "database schema version is invalid"
        ) from error
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise RuntimeKeyRotationError(
            "database schema version is unsupported"
        )
    return version


def rehearse_document_key_rotation(
    *,
    source_db_path: str,
    source_object_root: str,
    old_document_key: bytes,
    old_document_key_id: str,
    new_document_key: bytes,
    new_document_key_id: str,
    target_db_path: str,
    target_object_root: str,
) -> RuntimeKeyRotationReport:
    """Re-encrypt one consistent runtime snapshot into a clean target.

    The source runtime is read-only. Publication uses the target database as
    the completion marker and refuses pre-existing target state.
    """
    for value, label in (
        (source_db_path, "source_db_path"),
        (source_object_root, "source_object_root"),
        (target_db_path, "target_db_path"),
        (target_object_root, "target_object_root"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be non-empty")
    _validate_key(old_document_key, "old_document_key")
    _validate_key(new_document_key, "new_document_key")
    old_document_key_id = _validate_id(
        old_document_key_id,
        "old_document_key_id",
    )
    new_document_key_id = _validate_id(
        new_document_key_id,
        "new_document_key_id",
    )
    if old_document_key == new_document_key:
        raise ValueError("new document key must differ from old document key")
    if old_document_key_id == new_document_key_id:
        raise ValueError("new document key ID must differ from old key ID")

    source_db = Path(source_db_path).expanduser().resolve()
    source_objects = Path(source_object_root).expanduser().resolve()
    target_db = Path(target_db_path).expanduser().resolve()
    target_objects = Path(target_object_root).expanduser().resolve()
    if not source_db.is_file():
        raise RuntimeKeyRotationError("source database is unavailable")
    if not source_objects.is_dir():
        raise RuntimeKeyRotationError("source object store is unavailable")
    if target_db.exists():
        raise RuntimeKeyRotationError("target database already exists")
    if target_objects.exists():
        if not target_objects.is_dir():
            raise RuntimeKeyRotationError(
                "target object path is not a directory"
            )
        if any(target_objects.iterdir()):
            raise RuntimeKeyRotationError(
                "target object directory is not empty"
            )

    try:
        source_audit = audit_runtime_storage(
            db_path=str(source_db),
            object_root=str(source_objects),
            document_key=old_document_key,
        )
    except (RuntimeStorageAuditError, ValueError, OSError) as error:
        raise RuntimeKeyRotationError(
            "source runtime storage audit failed"
        ) from error
    if not source_audit.consistent:
        raise RuntimeKeyRotationError(
            "source runtime storage is inconsistent"
        )

    target_db.parent.mkdir(parents=True, exist_ok=True)
    target_objects.parent.mkdir(parents=True, exist_ok=True)
    stage_id = uuid.uuid4().hex
    staged_db = target_db.parent / f".dwaar-rotate-{stage_id}.sqlite3"
    staged_objects = (
        target_objects.parent / f".dwaar-rotate-{stage_id}-objects"
    )
    published_objects = False
    published_db = False

    try:
        try:
            source_connection = sqlite3.connect(
                f"file:{source_db}?mode=ro",
                uri=True,
                timeout=10,
            )
        except sqlite3.Error as error:
            raise RuntimeKeyRotationError(
                "source database cannot be opened"
            ) from error
        try:
            _validate_database(source_connection)
            with sqlite3.connect(str(staged_db), timeout=10) as target:
                source_connection.backup(target)
        finally:
            source_connection.close()

        with sqlite3.connect(str(staged_db), timeout=10) as snapshot:
            schema_version = _validate_database(snapshot)
            try:
                storage_keys = referenced_storage_keys(snapshot)
            except RuntimeStorageAuditError as error:
                raise RuntimeKeyRotationError(
                    "database storage references are invalid"
                ) from error

        staged_objects.mkdir(parents=False, exist_ok=False)
        source_store = EncryptedLocalDocumentStore(
            str(source_objects),
            old_document_key,
        )
        rotated_store = EncryptedLocalDocumentStore(
            str(staged_objects),
            new_document_key,
        )
        for storage_key in storage_keys:
            try:
                plaintext = source_store.get(storage_key)
            except Exception as error:
                raise RuntimeKeyRotationError(
                    "source encrypted object authentication failed"
                ) from error
            try:
                rotated_store.put(storage_key, plaintext)
                if rotated_store.get(storage_key) != plaintext:
                    raise RuntimeKeyRotationError(
                        "rotated object plaintext verification failed"
                    )
            except Exception as error:
                if isinstance(error, RuntimeKeyRotationError):
                    raise
                raise RuntimeKeyRotationError(
                    "rotated encrypted object publication failed"
                ) from error

        staged_audit = audit_runtime_storage(
            db_path=str(staged_db),
            object_root=str(staged_objects),
            document_key=new_document_key,
        )
        if not staged_audit.consistent:
            raise RuntimeKeyRotationError(
                "rotated runtime storage audit failed"
            )
        if staged_audit.referenced_object_count != len(storage_keys):
            raise RuntimeKeyRotationError(
                "rotated runtime object count is inconsistent"
            )

        if target_objects.exists():
            target_objects.rmdir()
        staged_objects.rename(target_objects)
        published_objects = True
        staged_db.rename(target_db)
        published_db = True

        final_audit = audit_runtime_storage(
            db_path=str(target_db),
            object_root=str(target_objects),
            document_key=new_document_key,
        )
        if not final_audit.consistent:
            raise RuntimeKeyRotationError(
                "published rotated runtime audit failed"
            )

        return RuntimeKeyRotationReport(
            old_key_id=old_document_key_id,
            new_key_id=new_document_key_id,
            object_count=final_audit.referenced_object_count,
            schema_version=schema_version,
        )
    except Exception:
        if published_db:
            try:
                target_db.unlink(missing_ok=True)
            except OSError:
                pass
        if published_objects:
            shutil.rmtree(target_objects, ignore_errors=True)
        raise
    finally:
        try:
            staged_db.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(staged_objects, ignore_errors=True)
