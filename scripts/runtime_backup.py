"""Operator CLI for Dwaar runtime backup creation and verification."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.runtime_backup import (
    RuntimeBackupError,
    create_runtime_backup,
    restore_runtime_backup,
    verify_runtime_backup,
)
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
)


def _document_key():
    value = os.environ.get("DWAAR_DOCUMENT_KEY_B64")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("document key missing")
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("document key invalid") from error


def _backup_id(now: datetime) -> str:
    return (
        "backup-"
        + now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify a Dwaar single-node runtime backup."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument(
        "--backup-root",
        default=None,
        help="Backup root; defaults to DWAAR_BACKUP_ROOT.",
    )
    create.add_argument(
        "--backup-id",
        default=None,
        help="Optional safe backup identifier.",
    )

    verify = sub.add_parser("verify")
    verify.add_argument("backup_dir")

    restore = sub.add_parser("restore")
    restore.add_argument("backup_dir")
    restore.add_argument(
        "--target-db",
        required=True,
        help="Clean target database path.",
    )
    restore.add_argument(
        "--target-objects",
        required=True,
        help="Clean target encrypted-object directory.",
    )
    return parser


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        key = _document_key()
    except ValueError:
        _emit({"ok": False, "error": "configuration_invalid"})
        return 2

    if args.command == "create":
        db_path = os.environ.get("DWAAR_DB_PATH")
        object_root = os.environ.get("DWAAR_OBJECT_ROOT")
        backup_root = args.backup_root or os.environ.get("DWAAR_BACKUP_ROOT")
        if not all(
            isinstance(value, str) and bool(value.strip())
            for value in (db_path, object_root, backup_root)
        ):
            _emit({"ok": False, "error": "configuration_invalid"})
            return 2

        created_at = datetime.now(timezone.utc)
        backup_id = args.backup_id or _backup_id(created_at)
        try:
            manifest = create_runtime_backup(
                db_path=db_path,
                object_root=object_root,
                backup_root=backup_root,
                backup_id=backup_id,
                created_at=created_at,
                document_key=key,
            )
        except (RuntimeBackupError, ValueError, OSError):
            _emit({"ok": False, "error": "backup_failed"})
            return 1

        _emit(
            {
                "ok": True,
                "operation": "create",
                "backup_id": manifest.backup_id,
                "source_schema_version": manifest.source_schema_version,
                "object_count": manifest.object_count,
            }
        )
        return 0

    if args.command == "verify":
        try:
            manifest = verify_runtime_backup(
                args.backup_dir,
                document_key=key,
            )
        except (RuntimeBackupError, ValueError, OSError):
            _emit({"ok": False, "error": "verification_failed"})
            return 1

        _emit(
            {
                "ok": True,
                "operation": "verify",
                "backup_id": manifest.backup_id,
                "source_schema_version": manifest.source_schema_version,
                "object_count": manifest.object_count,
            }
        )
        return 0

    try:
        manifest = restore_runtime_backup(
            args.backup_dir,
            target_db_path=args.target_db,
            target_object_root=args.target_objects,
            document_key=key,
        )
    except (RuntimeBackupError, ValueError, OSError):
        _emit({"ok": False, "error": "restore_failed"})
        return 1

    _emit(
        {
            "ok": True,
            "operation": "restore",
            "backup_id": manifest.backup_id,
            "source_schema_version": manifest.source_schema_version,
            "object_count": manifest.object_count,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
