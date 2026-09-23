"""Consistent encrypted-runtime backup and verification for Dwaar.

Backups operate on the current single-node SQLite + encrypted object-store
runtime. No professional document is decrypted during backup or verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from domain.runtime_backup_models import (
    RUNTIME_BACKUP_MANIFEST_VERSION,
    RuntimeBackupManifest,
    RuntimeBackupObject,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore


_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STORAGE_KEY = re.compile(r"^objects/([0-9a-f]{32})$")
_SUPPORTED_SCHEMA_VERSION = 6
_DB_BACKUP_MAGIC = b"DWAARBKP1\x00"
_NONCE_BYTES = 12
_BACKUP_KEY_INFO = b"DWAAR-RUNTIME-BACKUP-DB-V1"
_STORAGE_TABLES = (
    "case_documents",
    "analysis_snapshots",
    "evidence_reviews",
    "draft_versions",
    "legal_briefs",
)
_MANIFEST_KEYS = frozenset(
    {
        "manifest_version",
        "backup_id",
        "created_at",
        "source_schema_version",
        "database_byte_size",
        "database_sha256",
        "objects",
    }
)
_OBJECT_KEYS = frozenset(
    {"storage_key", "byte_size", "ciphertext_sha256"}
)


class RuntimeBackupError(RuntimeError):
    pass


def _validate_document_key(document_key: bytes) -> None:
    if not isinstance(document_key, bytes) or len(document_key) != 32:
        raise ValueError("document_key must be exactly 32 bytes")


def _backup_database_key(document_key: bytes) -> bytes:
    _validate_document_key(document_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_BACKUP_KEY_INFO,
    ).derive(document_key)


def _database_aad(backup_id: str) -> bytes:
    return _BACKUP_KEY_INFO + b"\x00" + backup_id.encode("utf-8")


def _encrypt_database_backup(
    plaintext_path: Path,
    encrypted_path: Path,
    *,
    document_key: bytes,
    backup_id: str,
) -> None:
    plaintext = plaintext_path.read_bytes()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(
        _backup_database_key(document_key)
    ).encrypt(
        nonce,
        plaintext,
        _database_aad(backup_id),
    )
    encrypted_path.write_bytes(
        _DB_BACKUP_MAGIC + nonce + ciphertext
    )
    try:
        os.chmod(encrypted_path, 0o600)
    except OSError:
        pass


def _decrypt_database_backup(
    encrypted_path: Path,
    *,
    document_key: bytes,
    backup_id: str,
) -> bytes:
    encoded = encrypted_path.read_bytes()
    minimum = len(_DB_BACKUP_MAGIC) + _NONCE_BYTES + 16
    if len(encoded) < minimum or not encoded.startswith(_DB_BACKUP_MAGIC):
        raise RuntimeBackupError(
            "encrypted backup database envelope is invalid"
        )
    start = len(_DB_BACKUP_MAGIC)
    nonce = encoded[start:start + _NONCE_BYTES]
    ciphertext = encoded[start + _NONCE_BYTES:]
    try:
        return AESGCM(
            _backup_database_key(document_key)
        ).decrypt(
            nonce,
            ciphertext,
            _database_aad(backup_id),
        )
    except InvalidTag as error:
        raise RuntimeBackupError(
            "encrypted backup database authentication failed"
        ) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT value FROM schema_meta
        WHERE key = 'schema_version'
        """
    ).fetchone()
    if row is None:
        raise RuntimeBackupError("backup source schema metadata is missing")
    try:
        version = int(row[0])
    except (TypeError, ValueError) as error:
        raise RuntimeBackupError(
            "backup source schema version is invalid"
        ) from error
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise RuntimeBackupError(
            "backup source schema version is unsupported"
        )
    return version


def _validate_database(connection: sqlite3.Connection) -> int:
    quick = connection.execute("PRAGMA quick_check").fetchone()
    if quick is None or quick[0] != "ok":
        raise RuntimeBackupError("database integrity check failed")
    foreign_key_rows = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if foreign_key_rows:
        raise RuntimeBackupError("database foreign-key check failed")
    return _schema_version(connection)


def _referenced_storage_keys(
    connection: sqlite3.Connection,
) -> Tuple[str, ...]:
    keys = []
    for table in _STORAGE_TABLES:
        try:
            rows = connection.execute(
                f"SELECT storage_key FROM {table} ORDER BY storage_key ASC"
            ).fetchall()
        except sqlite3.Error as error:
            raise RuntimeBackupError(
                "required storage metadata table is unavailable"
            ) from error
        for row in rows:
            value = row[0]
            if not isinstance(value, str) or _STORAGE_KEY.fullmatch(value) is None:
                raise RuntimeBackupError(
                    "database contains an invalid encrypted storage key"
                )
            keys.append(value)
    if len(keys) != len(set(keys)):
        raise RuntimeBackupError(
            "database contains duplicate encrypted storage keys"
        )
    return tuple(sorted(keys))


def _object_path(root: Path, storage_key: str) -> Path:
    match = _STORAGE_KEY.fullmatch(storage_key)
    if match is None:
        raise RuntimeBackupError("encrypted storage key is invalid")
    return root / f"{match.group(1)}.dwaar"


def _manifest_payload(
    manifest: RuntimeBackupManifest,
) -> dict:
    return {
        "manifest_version": manifest.manifest_version,
        "backup_id": manifest.backup_id,
        "created_at": manifest.created_at.isoformat(),
        "source_schema_version": manifest.source_schema_version,
        "database_byte_size": manifest.database_byte_size,
        "database_sha256": manifest.database_sha256,
        "objects": [
            {
                "storage_key": item.storage_key,
                "byte_size": item.byte_size,
                "ciphertext_sha256": item.ciphertext_sha256,
            }
            for item in manifest.objects
        ],
    }


def _write_manifest(path: Path, manifest: RuntimeBackupManifest) -> None:
    path.write_text(
        json.dumps(
            _manifest_payload(manifest),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _parse_manifest(path: Path) -> RuntimeBackupManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeBackupError("backup manifest is unreadable") from error
    if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
        raise RuntimeBackupError("backup manifest schema is invalid")
    if payload.get("manifest_version") != RUNTIME_BACKUP_MANIFEST_VERSION:
        raise RuntimeBackupError("backup manifest version is unsupported")

    backup_id = payload.get("backup_id")
    if (
        not isinstance(backup_id, str)
        or _BACKUP_ID.fullmatch(backup_id) is None
    ):
        raise RuntimeBackupError("backup manifest ID is invalid")
    try:
        created_at = datetime.fromisoformat(payload["created_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeBackupError("backup manifest timestamp is invalid") from error
    if created_at.tzinfo is None:
        raise RuntimeBackupError("backup manifest timestamp must be timezone-aware")

    if payload.get("source_schema_version") != _SUPPORTED_SCHEMA_VERSION:
        raise RuntimeBackupError("backup schema version is unsupported")
    db_size = payload.get("database_byte_size")
    db_hash = payload.get("database_sha256")
    if (
        not isinstance(db_size, int)
        or isinstance(db_size, bool)
        or db_size <= 0
        or not isinstance(db_hash, str)
        or len(db_hash) != 64
    ):
        raise RuntimeBackupError("backup database metadata is invalid")
    try:
        int(db_hash, 16)
    except ValueError as error:
        raise RuntimeBackupError("backup database hash is invalid") from error

    raw_objects = payload.get("objects")
    if not isinstance(raw_objects, list):
        raise RuntimeBackupError("backup object manifest is invalid")
    objects = []
    seen = set()
    for raw in raw_objects:
        if not isinstance(raw, dict) or set(raw) != _OBJECT_KEYS:
            raise RuntimeBackupError("backup object entry is invalid")
        storage_key = raw.get("storage_key")
        byte_size = raw.get("byte_size")
        digest = raw.get("ciphertext_sha256")
        if (
            not isinstance(storage_key, str)
            or _STORAGE_KEY.fullmatch(storage_key) is None
            or storage_key in seen
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise RuntimeBackupError("backup object entry is invalid")
        try:
            int(digest, 16)
        except ValueError as error:
            raise RuntimeBackupError("backup object hash is invalid") from error
        seen.add(storage_key)
        objects.append(
            RuntimeBackupObject(
                storage_key=storage_key,
                byte_size=byte_size,
                ciphertext_sha256=digest.lower(),
            )
        )

    if tuple(item.storage_key for item in objects) != tuple(
        sorted(item.storage_key for item in objects)
    ):
        raise RuntimeBackupError("backup object manifest order is invalid")

    return RuntimeBackupManifest(
        manifest_version=RUNTIME_BACKUP_MANIFEST_VERSION,
        backup_id=backup_id,
        created_at=created_at,
        source_schema_version=_SUPPORTED_SCHEMA_VERSION,
        database_byte_size=db_size,
        database_sha256=db_hash.lower(),
        objects=tuple(objects),
    )


def create_runtime_backup(
    *,
    db_path: str,
    object_root: str,
    backup_root: str,
    backup_id: str,
    created_at: datetime,
    document_key: bytes,
) -> RuntimeBackupManifest:
    """Create and atomically publish a verified runtime backup."""
    if not isinstance(db_path, str) or not db_path.strip():
        raise ValueError("db_path must be non-empty")
    if not isinstance(object_root, str) or not object_root.strip():
        raise ValueError("object_root must be non-empty")
    if not isinstance(backup_root, str) or not backup_root.strip():
        raise ValueError("backup_root must be non-empty")
    if not isinstance(backup_id, str) or _BACKUP_ID.fullmatch(backup_id) is None:
        raise ValueError("backup_id contains unsupported characters")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    _validate_document_key(document_key)

    source_db = Path(db_path).expanduser().resolve()
    source_objects = Path(object_root).expanduser().resolve()
    destination_root = Path(backup_root).expanduser().resolve()
    if not source_db.is_file():
        raise RuntimeBackupError("configured database file does not exist")
    if not source_objects.is_dir():
        raise RuntimeBackupError("configured object store does not exist")
    if source_objects == destination_root or source_objects in destination_root.parents:
        raise RuntimeBackupError(
            "backup root must not be inside the live object store"
        )

    destination_root.mkdir(parents=True, exist_ok=True)
    final_dir = destination_root / backup_id
    if final_dir.exists():
        raise RuntimeBackupError("backup ID already exists")
    temp_dir = destination_root / f".tmp-{backup_id}-{uuid.uuid4().hex}"
    temp_objects = temp_dir / "objects"
    plaintext_db = temp_dir / ".dwaar.sqlite3.tmp"
    backup_db = temp_dir / "dwaar.sqlite3.enc"
    manifest_path = temp_dir / "manifest.json"

    try:
        temp_objects.mkdir(parents=True, exist_ok=False)
        try:
            source_connection = sqlite3.connect(
                f"file:{source_db}?mode=ro",
                uri=True,
                timeout=10,
            )
        except sqlite3.Error as error:
            raise RuntimeBackupError("database backup source cannot open") from error

        try:
            _validate_database(source_connection)
            with sqlite3.connect(str(plaintext_db), timeout=10) as target:
                source_connection.backup(target)
        finally:
            source_connection.close()

        with sqlite3.connect(str(plaintext_db), timeout=10) as snapshot:
            source_schema_version = _validate_database(snapshot)
            storage_keys = _referenced_storage_keys(snapshot)

        _encrypt_database_backup(
            plaintext_db,
            backup_db,
            document_key=document_key,
            backup_id=backup_id,
        )
        plaintext_db.unlink()

        object_entries = []
        for storage_key in storage_keys:
            source_path = _object_path(source_objects, storage_key)
            if not source_path.is_file():
                raise RuntimeBackupError(
                    "database references a missing encrypted object"
                )
            target_path = _object_path(temp_objects, storage_key)
            shutil.copyfile(source_path, target_path)
            if not target_path.is_file():
                raise RuntimeBackupError("encrypted object copy failed")
            object_entries.append(
                RuntimeBackupObject(
                    storage_key=storage_key,
                    byte_size=target_path.stat().st_size,
                    ciphertext_sha256=_sha256(target_path),
                )
            )

        manifest = RuntimeBackupManifest(
            manifest_version=RUNTIME_BACKUP_MANIFEST_VERSION,
            backup_id=backup_id,
            created_at=created_at,
            source_schema_version=source_schema_version,
            database_byte_size=backup_db.stat().st_size,
            database_sha256=_sha256(backup_db),
            objects=tuple(object_entries),
        )
        _write_manifest(manifest_path, manifest)
        verify_runtime_backup(
            str(temp_dir),
            expected_backup_id=backup_id,
            document_key=document_key,
        )
        temp_dir.rename(final_dir)
        return manifest
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def verify_runtime_backup(
    backup_dir: str,
    *,
    document_key: bytes,
    expected_backup_id: str | None = None,
) -> RuntimeBackupManifest:
    """Verify a published or temporary backup without decrypting objects."""
    if not isinstance(backup_dir, str) or not backup_dir.strip():
        raise ValueError("backup_dir must be non-empty")
    _validate_document_key(document_key)
    root = Path(backup_dir).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeBackupError("backup directory does not exist")

    manifest = _parse_manifest(root / "manifest.json")
    if (
        expected_backup_id is not None
        and manifest.backup_id != expected_backup_id
    ):
        raise RuntimeBackupError("backup ID does not match expectation")
    if root.name.startswith(".tmp-"):
        pass
    elif root.name != manifest.backup_id:
        raise RuntimeBackupError(
            "backup directory name does not match manifest ID"
        )

    database = root / "dwaar.sqlite3.enc"
    if (
        not database.is_file()
        or database.stat().st_size != manifest.database_byte_size
        or _sha256(database) != manifest.database_sha256
    ):
        raise RuntimeBackupError("backup database hash or size mismatch")

    plaintext = _decrypt_database_backup(
        database,
        document_key=document_key,
        backup_id=manifest.backup_id,
    )
    temp_database = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".dwaar-backup-verify-",
            suffix=".sqlite3",
            delete=False,
        ) as handle:
            temp_database = Path(handle.name)
            try:
                os.chmod(temp_database, 0o600)
            except OSError:
                pass
            handle.write(plaintext)
            handle.flush()
            os.fsync(handle.fileno())
        with sqlite3.connect(str(temp_database), timeout=10) as connection:
            schema_version = _validate_database(connection)
            storage_keys = _referenced_storage_keys(connection)
    finally:
        if temp_database is not None:
            try:
                temp_database.unlink(missing_ok=True)
            except OSError:
                pass
    if schema_version != manifest.source_schema_version:
        raise RuntimeBackupError("backup database schema binding mismatch")

    manifest_keys = tuple(item.storage_key for item in manifest.objects)
    if storage_keys != manifest_keys:
        raise RuntimeBackupError(
            "backup object manifest does not match database references"
        )

    objects_root = root / "objects"
    if not objects_root.is_dir():
        raise RuntimeBackupError("backup object directory is missing")
    authenticated_store = EncryptedLocalDocumentStore(
        str(objects_root),
        document_key,
    )
    expected_files = set()
    for item in manifest.objects:
        object_path = _object_path(objects_root, item.storage_key)
        expected_files.add(object_path.name)
        if (
            not object_path.is_file()
            or object_path.stat().st_size != item.byte_size
            or _sha256(object_path) != item.ciphertext_sha256
        ):
            raise RuntimeBackupError(
                "backup encrypted object hash or size mismatch"
            )
        try:
            authenticated_store.get(item.storage_key)
        except Exception as error:
            raise RuntimeBackupError(
                "backup encrypted object authentication failed"
            ) from error

    actual_files = {
        path.name
        for path in objects_root.iterdir()
        if path.is_file()
    }
    if actual_files != expected_files:
        raise RuntimeBackupError(
            "backup object directory contains an unexpected file set"
        )
    return manifest



def restore_runtime_backup(
    backup_dir: str,
    *,
    target_db_path: str,
    target_object_root: str,
    document_key: bytes,
) -> RuntimeBackupManifest:
    """Restore a verified backup only into an empty runtime target.

    The function never overwrites an existing database and never restores
    into a non-empty object directory. All database/object validation occurs
    in staging paths before the targets are published.
    """
    if not isinstance(target_db_path, str) or not target_db_path.strip():
        raise ValueError("target_db_path must be non-empty")
    if not isinstance(target_object_root, str) or not target_object_root.strip():
        raise ValueError("target_object_root must be non-empty")
    _validate_document_key(document_key)

    manifest = verify_runtime_backup(
        backup_dir,
        document_key=document_key,
    )
    backup_root = Path(backup_dir).expanduser().resolve()
    target_db = Path(target_db_path).expanduser().resolve()
    target_objects = Path(target_object_root).expanduser().resolve()

    if target_db.exists():
        raise RuntimeBackupError(
            "restore target database already exists"
        )
    if target_objects.exists():
        if not target_objects.is_dir():
            raise RuntimeBackupError(
                "restore target object path is not a directory"
            )
        if any(target_objects.iterdir()):
            raise RuntimeBackupError(
                "restore target object directory is not empty"
            )

    db_parent = target_db.parent
    object_parent = target_objects.parent
    db_parent.mkdir(parents=True, exist_ok=True)
    object_parent.mkdir(parents=True, exist_ok=True)

    stage_id = uuid.uuid4().hex
    staged_db = db_parent / f".dwaar-restore-{stage_id}.sqlite3"
    staged_objects = object_parent / f".dwaar-restore-{stage_id}-objects"
    backup_database = backup_root / "dwaar.sqlite3.enc"
    backup_objects = backup_root / "objects"

    published_objects = False
    published_db = False
    try:
        plaintext = _decrypt_database_backup(
            backup_database,
            document_key=document_key,
            backup_id=manifest.backup_id,
        )
        with staged_db.open("xb") as handle:
            try:
                os.chmod(staged_db, 0o600)
            except OSError:
                pass
            handle.write(plaintext)
            handle.flush()
            os.fsync(handle.fileno())

        staged_objects.mkdir(parents=False, exist_ok=False)
        try:
            os.chmod(staged_objects, 0o700)
        except OSError:
            pass

        for item in manifest.objects:
            source = _object_path(backup_objects, item.storage_key)
            target = _object_path(staged_objects, item.storage_key)
            shutil.copyfile(source, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass

        with sqlite3.connect(str(staged_db), timeout=10) as connection:
            schema_version = _validate_database(connection)
            storage_keys = _referenced_storage_keys(connection)
        if schema_version != manifest.source_schema_version:
            raise RuntimeBackupError(
                "restored database schema binding mismatch"
            )
        manifest_keys = tuple(item.storage_key for item in manifest.objects)
        if storage_keys != manifest_keys:
            raise RuntimeBackupError(
                "restored database object references do not match backup"
            )

        restored_store = EncryptedLocalDocumentStore(
            str(staged_objects),
            document_key,
        )
        for item in manifest.objects:
            path = _object_path(staged_objects, item.storage_key)
            if (
                path.stat().st_size != item.byte_size
                or _sha256(path) != item.ciphertext_sha256
            ):
                raise RuntimeBackupError(
                    "restored encrypted object hash or size mismatch"
                )
            try:
                restored_store.get(item.storage_key)
            except Exception as error:
                raise RuntimeBackupError(
                    "restored encrypted object authentication failed"
                ) from error

        if target_objects.exists():
            # The caller supplied an empty directory. Remove it immediately
            # before atomically replacing it with the validated staged tree.
            target_objects.rmdir()
        staged_objects.rename(target_objects)
        published_objects = True

        # Publish the database last. Its presence is the completion marker
        # for this clean-target restore operation.
        staged_db.rename(target_db)
        published_db = True

        with sqlite3.connect(str(target_db), timeout=10) as connection:
            _validate_database(connection)
            if _referenced_storage_keys(connection) != manifest_keys:
                raise RuntimeBackupError(
                    "published restore object references are inconsistent"
                )
        published_store = EncryptedLocalDocumentStore(
            str(target_objects),
            document_key,
        )
        for item in manifest.objects:
            published_store.get(item.storage_key)
        return manifest
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
