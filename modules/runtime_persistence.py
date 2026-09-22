"""Runtime construction of Dwaar's authorized pilot persistence stack."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.runtime_access import (
    RuntimeAccessConfigurationError,
    database_path_from_environment,
)
from modules.runtime_security import (
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
)
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


class RuntimePersistenceConfigurationError(RuntimeError):
    """Pilot persistent case/document runtime is not fully configured."""


def object_root_from_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_OBJECT_ROOT")
    if not isinstance(value, str) or not value.strip():
        raise RuntimePersistenceConfigurationError(
            "DWAAR_OBJECT_ROOT is not configured"
        )
    return str(Path(value.strip()).expanduser())


def document_key_from_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> bytes:
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_DOCUMENT_KEY_B64")
    if not isinstance(value, str) or not value.strip():
        raise RuntimePersistenceConfigurationError(
            "DWAAR_DOCUMENT_KEY_B64 is not configured"
        )
    try:
        return decode_document_master_key(value)
    except RuntimeSecurityConfigurationError as error:
        raise RuntimePersistenceConfigurationError(
            "DWAAR_DOCUMENT_KEY_B64 is invalid"
        ) from error


def _build_runtime_components(
    environment: Optional[Mapping[str, str]] = None,
):
    try:
        db_path = database_path_from_environment(environment)
    except RuntimeAccessConfigurationError as error:
        raise RuntimePersistenceConfigurationError(
            "DWAAR_DB_PATH is not configured"
        ) from error

    object_root = object_root_from_environment(environment)
    key = document_key_from_environment(environment)

    case_repository = LocalSQLiteCaseRepository(db_path)
    access_repository = LocalSQLiteAccessGrantRepository(db_path)
    document_store = EncryptedLocalDocumentStore(
        object_root,
        key,
    )
    return (
        db_path,
        case_repository,
        access_repository,
        document_store,
    )


def build_authorized_case_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedCaseService:
    """Build the pilot persistence service from server-side configuration."""
    (
        _,
        case_repository,
        access_repository,
        document_store,
    ) = _build_runtime_components(environment)
    return AuthorizedCaseService(
        case_repository,
        access_repository,
        document_store,
    )


def build_authorized_analysis_snapshot_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedAnalysisSnapshotService:
    """Build the authorized encrypted analysis-history service."""
    (
        db_path,
        case_repository,
        access_repository,
        document_store,
    ) = _build_runtime_components(environment)
    case_service = AuthorizedCaseService(
        case_repository,
        access_repository,
        document_store,
    )
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(
        db_path
    )
    return AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
