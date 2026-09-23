"""Runtime construction of Dwaar's authorized pilot persistence stack."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_draft_work_product_service import (
    AuthorizedDraftWorkProductService,
)
from modules.authorized_filing_service import (
    AuthorizedFilingService,
    FilingSourceFactReviewBlockedError,
)
from modules.authorized_fact_review_service import AuthorizedFactReviewService
from modules.authorized_legal_brief_service import AuthorizedLegalBriefService
from modules.authorized_professional_workbench_service import (
    AuthorizedProfessionalWorkbenchService,
)
from modules.authorized_evidence_review_service import (
    AuthorizedEvidenceReviewService,
)
from modules.authorized_evidence_workspace_service import (
    AuthorizedEvidenceWorkspaceService,
)
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
from modules.sqlite_draft_version_repository import (
    LocalSQLiteDraftVersionRepository,
)
from modules.sqlite_evidence_review_repository import (
    LocalSQLiteEvidenceReviewRepository,
)
from modules.sqlite_filing_repository import LocalSQLiteFilingRepository
from modules.sqlite_fact_review_repository import LocalSQLiteFactReviewRepository
from modules.sqlite_legal_brief_repository import (
    LocalSQLiteLegalBriefRepository,
)


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


def build_authorized_evidence_workspace_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedEvidenceWorkspaceService:
    """Build authorized analysis over persisted supporting evidence."""
    (
        _,
        case_repository,
        access_repository,
        document_store,
    ) = _build_runtime_components(environment)
    case_service = AuthorizedCaseService(
        case_repository,
        access_repository,
        document_store,
    )
    return AuthorizedEvidenceWorkspaceService(
        case_service,
        access_repository,
    )


def build_authorized_filing_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedFilingService:
    """Build authorized filing/acknowledgement lifecycle service."""
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
    filing_repository = LocalSQLiteFilingRepository(db_path)
    draft_repository = LocalSQLiteDraftVersionRepository(db_path)
    return AuthorizedFilingService(
        case_service,
        access_repository,
        filing_repository,
        draft_repository,
        document_store,
        fact_review_repository=LocalSQLiteFactReviewRepository(db_path),
    )


def build_authorized_draft_work_product_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedDraftWorkProductService:
    """Build encrypted immutable draft version/review service."""
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
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(db_path)
    snapshot_service = AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
    draft_repository = LocalSQLiteDraftVersionRepository(db_path)
    fact_review_repository = LocalSQLiteFactReviewRepository(db_path)
    return AuthorizedDraftWorkProductService(
        case_service,
        snapshot_service,
        access_repository,
        draft_repository,
        document_store,
        fact_review_repository=fact_review_repository,
    )


def build_authorized_evidence_review_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedEvidenceReviewService:
    """Build encrypted snapshot-bound evidence review service."""
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
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(db_path)
    snapshot_service = AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
    review_repository = LocalSQLiteEvidenceReviewRepository(db_path)
    return AuthorizedEvidenceReviewService(
        case_service,
        snapshot_service,
        access_repository,
        review_repository,
        document_store,
    )


def build_authorized_fact_review_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedFactReviewService:
    """Build encrypted snapshot-bound professional fact-review service."""
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
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(db_path)
    snapshot_service = AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
    review_repository = LocalSQLiteFactReviewRepository(db_path)
    return AuthorizedFactReviewService(
        case_service,
        snapshot_service,
        access_repository,
        review_repository,
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


def build_authorized_legal_brief_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedLegalBriefService:
    """Build authorized snapshot-bound legal research history."""
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
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(db_path)
    snapshot_service = AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
    brief_repository = LocalSQLiteLegalBriefRepository(db_path)
    return AuthorizedLegalBriefService(
        case_service,
        snapshot_service,
        access_repository,
        brief_repository,
        document_store,
    )


def build_authorized_professional_workbench_service(
    environment: Optional[Mapping[str, str]] = None,
) -> AuthorizedProfessionalWorkbenchService:
    """Build tenant-safe read-only professional case cockpit."""
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
    snapshot_repository = LocalSQLiteAnalysisSnapshotRepository(db_path)
    snapshot_service = AuthorizedAnalysisSnapshotService(
        case_service,
        access_repository,
        snapshot_repository,
        document_store,
    )
    legal_service = AuthorizedLegalBriefService(
        case_service,
        snapshot_service,
        access_repository,
        LocalSQLiteLegalBriefRepository(db_path),
        document_store,
    )
    draft_service = AuthorizedDraftWorkProductService(
        case_service,
        snapshot_service,
        access_repository,
        LocalSQLiteDraftVersionRepository(db_path),
        document_store,
        fact_review_repository=LocalSQLiteFactReviewRepository(db_path),
    )
    filing_service = AuthorizedFilingService(
        case_service,
        access_repository,
        LocalSQLiteFilingRepository(db_path),
        LocalSQLiteDraftVersionRepository(db_path),
        document_store,
        fact_review_repository=LocalSQLiteFactReviewRepository(db_path),
    )
    evidence_review_service = AuthorizedEvidenceReviewService(
        case_service,
        snapshot_service,
        access_repository,
        LocalSQLiteEvidenceReviewRepository(db_path),
        document_store,
    )
    fact_review_service = AuthorizedFactReviewService(
        case_service,
        snapshot_service,
        access_repository,
        LocalSQLiteFactReviewRepository(db_path),
        document_store,
    )
    return AuthorizedProfessionalWorkbenchService(
        case_service,
        snapshot_service,
        legal_service,
        draft_service,
        filing_service,
        evidence_review_service,
        fact_review_service,
    )
