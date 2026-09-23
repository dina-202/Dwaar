"""Firm-scoped authorization contracts for Dwaar Phase 3E."""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class AccessPermission(Enum):
    CASE_READ = "case_read"
    CASE_CREATE = "case_create"
    CASE_UPDATE = "case_update"
    DOCUMENT_READ = "document_read"
    DOCUMENT_ADD = "document_add"
    EVIDENCE_REVIEW = "evidence_review"
    FACT_REVIEW = "fact_review"
    DRAFT_REVIEW = "draft_review"
    FILING_RECORD = "filing_record"
    FIRM_ADMIN = "firm_admin"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Identity asserted by an external authentication provider."""

    user_id: str


@dataclass(frozen=True)
class FirmAccessGrant:
    """Explicit permissions for one user inside one firm."""

    user_id: str
    firm_id: str
    permissions: FrozenSet[AccessPermission]
    active: bool = True


class AuthorizationError(PermissionError):
    """Requested operation is outside the caller's explicit firm grant."""
