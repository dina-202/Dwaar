"""Versioned analysis-snapshot contracts for Dwaar Phase 3F.4."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict


SNAPSHOT_SCHEMA_VERSION = 1
ANALYSIS_ENGINE_VERSION = "phase2-contract-2026.09.22.1"


@dataclass(frozen=True)
class AnalysisSnapshotRef:
    snapshot_id: str
    case_id: str
    source_document_id: str
    source_document_sha256: str
    schema_version: int
    engine_version: str
    byte_size: int
    sha256_hex: str
    storage_key: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True)
class LoadedAnalysisSnapshot:
    metadata: AnalysisSnapshotRef
    payload: Dict[str, object]
