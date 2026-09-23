"""Sanitized operator-health contracts for Dwaar Phase 3P.4."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class OperatorHealthStatus(Enum):
    PASS = "pass"
    BLOCKED = "blocked"


class OperatorHealthCode(Enum):
    RUNTIME_PREFLIGHT = "runtime_preflight"
    BACKUP_VERIFICATION = "backup_verification"
    BACKUP_FRESHNESS = "backup_freshness"


@dataclass(frozen=True)
class OperatorHealthCheck:
    code: OperatorHealthCode
    status: OperatorHealthStatus
    message: str


@dataclass(frozen=True)
class OperatorHealthReport:
    checks: Tuple[OperatorHealthCheck, ...]
    backup_age_hours: float | None

    @property
    def healthy(self) -> bool:
        return bool(self.checks) and all(
            item.status is OperatorHealthStatus.PASS
            for item in self.checks
        )
