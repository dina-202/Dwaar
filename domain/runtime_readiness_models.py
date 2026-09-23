"""Sanitized production-readiness contracts for Dwaar Phase 3P.1."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class RuntimeReadinessStatus(Enum):
    PASS = "pass"
    BLOCKED = "blocked"


class RuntimeReadinessCode(Enum):
    DB_CONFIGURATION = "db_configuration"
    OBJECT_STORE_CONFIGURATION = "object_store_configuration"
    DOCUMENT_KEY_CONFIGURATION = "document_key_configuration"
    DOCUMENT_KEY_ID_CONFIGURATION = "document_key_id_configuration"
    OCR_RUNTIME = "ocr_runtime"
    LLM_CONFIGURATION = "llm_configuration"
    DB_OPEN_AND_MIGRATION = "db_open_and_migration"
    DB_INTEGRITY = "db_integrity"
    OBJECT_STORE_ROUND_TRIP = "object_store_round_trip"


@dataclass(frozen=True)
class RuntimeReadinessCheck:
    code: RuntimeReadinessCode
    status: RuntimeReadinessStatus
    message: str


@dataclass(frozen=True)
class RuntimeReadinessReport:
    checks: Tuple[RuntimeReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(
            item.status is RuntimeReadinessStatus.PASS
            for item in self.checks
        )
