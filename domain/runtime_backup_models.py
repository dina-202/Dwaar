"""Immutable backup manifest contracts for Dwaar Phase 3P.2."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple


RUNTIME_BACKUP_MANIFEST_VERSION = 2
SUPPORTED_RUNTIME_BACKUP_MANIFEST_VERSIONS = (1, 2)


@dataclass(frozen=True)
class RuntimeBackupObject:
    storage_key: str
    byte_size: int
    ciphertext_sha256: str


@dataclass(frozen=True)
class RuntimeBackupManifest:
    manifest_version: int
    backup_id: str
    created_at: datetime
    source_schema_version: int
    database_byte_size: int
    database_sha256: str
    objects: Tuple[RuntimeBackupObject, ...]
    document_key_id: Optional[str] = None

    @property
    def object_count(self) -> int:
        return len(self.objects)
