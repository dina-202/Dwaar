"""Sanitized operator health and backup posture for Dwaar."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping, Optional

from domain.operator_health_models import (
    OperatorHealthCheck,
    OperatorHealthCode,
    OperatorHealthReport,
    OperatorHealthStatus,
)
from modules.runtime_backup import RuntimeBackupError, verify_runtime_backup
from modules.runtime_readiness import evaluate_runtime_readiness
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
)


def _check(
    code: OperatorHealthCode,
    ok: bool,
    pass_message: str,
    fail_message: str,
) -> OperatorHealthCheck:
    return OperatorHealthCheck(
        code=code,
        status=(
            OperatorHealthStatus.PASS
            if ok
            else OperatorHealthStatus.BLOCKED
        ),
        message=pass_message if ok else fail_message,
    )


def _document_key(
    environment: Optional[Mapping[str, str]],
) -> bytes | None:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_DOCUMENT_KEY_B64")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError:
        return None


def evaluate_operator_health(
    *,
    backup_dir: str,
    max_backup_age_hours: float,
    now: datetime,
    environment: Optional[Mapping[str, str]] = None,
) -> OperatorHealthReport:
    """Evaluate runtime + one nominated backup without leaking identifiers."""
    if not isinstance(backup_dir, str) or not backup_dir.strip():
        raise ValueError("backup_dir must be non-empty")
    if (
        not isinstance(max_backup_age_hours, (int, float))
        or isinstance(max_backup_age_hours, bool)
        or max_backup_age_hours <= 0
    ):
        raise ValueError("max_backup_age_hours must be positive")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    runtime = evaluate_runtime_readiness(environment)
    checks = [
        _check(
            OperatorHealthCode.RUNTIME_PREFLIGHT,
            runtime.ready,
            "Runtime preflight passed.",
            "Runtime preflight is blocked.",
        )
    ]

    key = _document_key(environment)
    manifest = None
    if key is not None:
        try:
            manifest = verify_runtime_backup(
                backup_dir,
                document_key=key,
            )
        except (RuntimeBackupError, ValueError, OSError):
            manifest = None

    checks.append(
        _check(
            OperatorHealthCode.BACKUP_VERIFICATION,
            manifest is not None,
            "Nominated backup verification passed.",
            "Nominated backup verification is blocked.",
        )
    )

    age_hours = None
    fresh = False
    if manifest is not None:
        created_at = manifest.created_at.astimezone(timezone.utc)
        current = now.astimezone(timezone.utc)
        age_seconds = (current - created_at).total_seconds()
        if age_seconds >= 0:
            age_hours = age_seconds / 3600.0
            fresh = age_hours <= float(max_backup_age_hours)

    checks.append(
        _check(
            OperatorHealthCode.BACKUP_FRESHNESS,
            fresh,
            "Nominated backup is within the configured age policy.",
            "Nominated backup is outside the configured age policy.",
        )
    )

    return OperatorHealthReport(
        checks=tuple(checks),
        backup_age_hours=age_hours,
    )
