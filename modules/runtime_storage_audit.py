"""Live SQLite/object-store consistency audit for Dwaar.

The audit exposes counts only. It never returns storage keys, paths, decrypted
payloads, client metadata, or underlying cryptographic exception text.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Tuple

from domain.runtime_storage_audit_models import RuntimeStorageAuditReport
from modules.encrypted_document_store import EncryptedLocalDocumentStore


_STORAGE_KEY = re.compile(r"^objects/([0-9a-f]{32})$")
_OBJECT_FILE = re.compile(r"^([0-9a-f]{32})\.dwaar$")
_SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RuntimeStorageAuditError(RuntimeError):
    pass


def discover_storage_key_tables(
    connection: sqlite3.Connection,
) -> Tuple[str, ...]:
    """Discover every user table with an exact storage_key column."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name ASC
            """
        ).fetchall()
    except sqlite3.Error as error:
        raise RuntimeStorageAuditError(
            "database schema inventory is unavailable"
        ) from error

    tables = []
    for row in rows:
        name = row[0]
        if not isinstance(name, str) or _SAFE_TABLE.fullmatch(name) is None:
            raise RuntimeStorageAuditError(
                "database contains an unsupported table identifier"
            )
        try:
            columns = connection.execute(
                f'PRAGMA table_info("{name}")'
            ).fetchall()
        except sqlite3.Error as error:
            raise RuntimeStorageAuditError(
                "database table metadata is unavailable"
            ) from error
        column_names = {column[1] for column in columns}
        if "storage_key" in column_names:
            tables.append(name)
    return tuple(tables)


def referenced_storage_keys(
    connection: sqlite3.Connection,
) -> Tuple[str, ...]:
    """Return the unique sorted encrypted-object reference set.

    Malformed or duplicate references fail closed. The backup subsystem uses
    this same function so backup coverage follows the live schema.
    """
    keys = []
    for table in discover_storage_key_tables(connection):
        try:
            rows = connection.execute(
                f'SELECT storage_key FROM "{table}" ORDER BY storage_key ASC'
            ).fetchall()
        except sqlite3.Error as error:
            raise RuntimeStorageAuditError(
                "database storage references are unavailable"
            ) from error
        for row in rows:
            value = row[0]
            if (
                not isinstance(value, str)
                or _STORAGE_KEY.fullmatch(value) is None
            ):
                raise RuntimeStorageAuditError(
                    "database contains an invalid encrypted storage reference"
                )
            keys.append(value)

    if len(keys) != len(set(keys)):
        raise RuntimeStorageAuditError(
            "database contains duplicate encrypted storage references"
        )
    return tuple(sorted(keys))


def audit_runtime_storage(
    *,
    db_path: str,
    object_root: str,
    document_key: bytes,
) -> RuntimeStorageAuditReport:
    """Audit live referenced objects and ciphertext authentication."""
    if not isinstance(db_path, str) or not db_path.strip():
        raise ValueError("db_path must be non-empty")
    if not isinstance(object_root, str) or not object_root.strip():
        raise ValueError("object_root must be non-empty")
    if not isinstance(document_key, bytes) or len(document_key) != 32:
        raise ValueError("document_key must be exactly 32 bytes")

    database = Path(db_path).expanduser().resolve()
    objects = Path(object_root).expanduser().resolve()
    if not database.is_file():
        raise RuntimeStorageAuditError("database file is unavailable")
    if not objects.is_dir():
        raise RuntimeStorageAuditError(
            "encrypted object directory is unavailable"
        )

    try:
        connection = sqlite3.connect(
            f"file:{database}?mode=ro",
            uri=True,
            timeout=10,
        )
    except sqlite3.Error as error:
        raise RuntimeStorageAuditError(
            "database cannot be opened for storage audit"
        ) from error

    invalid_reference_count = 0
    try:
        tables = discover_storage_key_tables(connection)
        try:
            refs = referenced_storage_keys(connection)
        except RuntimeStorageAuditError:
            # The detailed keys must never escape through the report.
            invalid_reference_count = 1
            refs = ()
    finally:
        connection.close()

    object_keys = set()
    invalid_object_entry_count = 0
    for entry in objects.iterdir():
        if not entry.is_file():
            invalid_object_entry_count += 1
            continue
        match = _OBJECT_FILE.fullmatch(entry.name)
        if match is None:
            invalid_object_entry_count += 1
            continue
        object_keys.add("objects/" + match.group(1))

    ref_set = set(refs)
    if invalid_reference_count:
        missing = set()
        orphan = set()
    else:
        missing = ref_set - object_keys
        orphan = object_keys - ref_set

    authentication_failure_count = 0
    if invalid_reference_count == 0:
        store = EncryptedLocalDocumentStore(
            str(objects),
            document_key,
        )
        for storage_key in sorted(ref_set & object_keys):
            try:
                store.get(storage_key)
            except Exception:
                authentication_failure_count += 1

    return RuntimeStorageAuditReport(
        storage_table_count=len(tables),
        referenced_object_count=len(ref_set),
        object_file_count=len(object_keys),
        missing_object_count=len(missing),
        orphan_object_count=len(orphan),
        invalid_reference_count=invalid_reference_count,
        invalid_object_entry_count=invalid_object_entry_count,
        authentication_failure_count=authentication_failure_count,
    )
