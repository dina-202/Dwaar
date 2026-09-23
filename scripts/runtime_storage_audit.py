"""Operator CLI for Dwaar live encrypted-storage consistency audit."""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.runtime_storage_audit import (
    RuntimeStorageAuditError,
    audit_runtime_storage,
)
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
)


def _key():
    value = os.environ.get("DWAAR_DOCUMENT_KEY_B64")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("document key missing")
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError as error:
        raise ValueError("document key invalid") from error


def main() -> int:
    db_path = os.environ.get("DWAAR_DB_PATH")
    object_root = os.environ.get("DWAAR_OBJECT_ROOT")
    try:
        document_key = _key()
    except ValueError:
        print(
            json.dumps(
                {"consistent": False, "error": "configuration_invalid"},
                sort_keys=True,
            )
        )
        return 2

    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in (db_path, object_root)
    ):
        print(
            json.dumps(
                {"consistent": False, "error": "configuration_invalid"},
                sort_keys=True,
            )
        )
        return 2

    try:
        report = audit_runtime_storage(
            db_path=db_path,
            object_root=object_root,
            document_key=document_key,
        )
    except (RuntimeStorageAuditError, ValueError, OSError):
        print(
            json.dumps(
                {"consistent": False, "error": "audit_failed"},
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "consistent": report.consistent,
                "storage_table_count": report.storage_table_count,
                "referenced_object_count": report.referenced_object_count,
                "object_file_count": report.object_file_count,
                "missing_object_count": report.missing_object_count,
                "orphan_object_count": report.orphan_object_count,
                "invalid_reference_count": report.invalid_reference_count,
                "invalid_object_entry_count": (
                    report.invalid_object_entry_count
                ),
                "authentication_failure_count": (
                    report.authentication_failure_count
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report.consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
