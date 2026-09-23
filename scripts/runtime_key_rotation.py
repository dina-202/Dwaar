"""Operator CLI for clean-target Dwaar document-key rotation rehearsal."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.runtime_key_rotation import (
    RuntimeKeyRotationError,
    rehearse_document_key_rotation,
)
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
    validate_document_key_id,
)


def _key(name: str):
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("key configuration missing")
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("key configuration invalid") from error


def _key_id(name: str):
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("key ID configuration missing")
    try:
        return validate_document_key_id(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("key ID configuration invalid") from error


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rehearse Dwaar document-key rotation into a clean target."
    )
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--target-objects", required=True)
    args = parser.parse_args(argv)

    source_db = os.environ.get("DWAAR_DB_PATH")
    source_objects = os.environ.get("DWAAR_OBJECT_ROOT")
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in (source_db, source_objects)
    ):
        _emit({"ok": False, "error": "configuration_invalid"})
        return 2

    try:
        old_key = _key("DWAAR_DOCUMENT_KEY_B64")
        old_id = _key_id("DWAAR_DOCUMENT_KEY_ID")
        new_key = _key("DWAAR_NEW_DOCUMENT_KEY_B64")
        new_id = _key_id("DWAAR_NEW_DOCUMENT_KEY_ID")
    except ValueError:
        _emit({"ok": False, "error": "configuration_invalid"})
        return 2

    try:
        report = rehearse_document_key_rotation(
            source_db_path=source_db,
            source_object_root=source_objects,
            old_document_key=old_key,
            old_document_key_id=old_id,
            new_document_key=new_key,
            new_document_key_id=new_id,
            target_db_path=args.target_db,
            target_object_root=args.target_objects,
        )
    except (RuntimeKeyRotationError, ValueError, OSError):
        _emit({"ok": False, "error": "rotation_rehearsal_failed"})
        return 1

    _emit(
        {
            "ok": True,
            "operation": "key_rotation_rehearsal",
            "old_key_id": report.old_key_id,
            "new_key_id": report.new_key_id,
            "object_count": report.object_count,
            "schema_version": report.schema_version,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
