"""Runtime firm-access discovery for authenticated Dwaar users."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterable, List, Mapping, Optional

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
)
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


class RuntimeAccessConfigurationError(RuntimeError):
    """Required pilot persistence configuration is unavailable."""


class RuntimeAccessConsistencyError(RuntimeError):
    """Persisted authorization state is inconsistent with firm metadata."""


@dataclass(frozen=True)
class AvailableFirmAccess:
    firm_id: str
    display_name: str
    permissions: FrozenSet[AccessPermission] = frozenset()


def database_path_from_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve the configured local pilot database path."""
    source = os.environ if environment is None else environment
    value = source.get("DWAAR_DB_PATH")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeAccessConfigurationError(
            "DWAAR_DB_PATH is not configured"
        )
    return str(Path(value.strip()).expanduser())


def load_available_firms(
    principal: AuthenticatedPrincipal,
    db_path: str,
    required_permission: AccessPermission,
) -> List[AvailableFirmAccess]:
    """Backward-compatible one-permission firm discovery."""
    return load_available_firms_for_permissions(
        principal,
        db_path,
        {required_permission},
    )


def load_available_firms_for_permissions(
    principal: AuthenticatedPrincipal,
    db_path: str,
    required_permissions: Iterable[AccessPermission],
) -> List[AvailableFirmAccess]:
    """Return active firms having at least one requested permission."""
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")
    if not isinstance(db_path, str) or not db_path.strip():
        raise ValueError("db_path must be a non-empty string")
    permissions = frozenset(required_permissions)
    if (
        not permissions
        or any(
            not isinstance(permission, AccessPermission)
            for permission in permissions
        )
    ):
        raise TypeError(
            "required_permissions must contain AccessPermission values"
        )

    access_repository = LocalSQLiteAccessGrantRepository(db_path)
    case_repository = LocalSQLiteCaseRepository(db_path)

    available = []
    for grant in access_repository.list_grants_for_user(principal.user_id):
        if not grant.active:
            continue
        matching = grant.permissions.intersection(permissions)
        if not matching:
            continue

        firm = case_repository.get_firm(grant.firm_id)
        if firm is None:
            raise RuntimeAccessConsistencyError(
                "access grant references a missing firm"
            )
        available.append(
            AvailableFirmAccess(
                firm_id=firm.firm_id,
                display_name=firm.display_name,
                permissions=grant.permissions,
            )
        )

    return sorted(
        available,
        key=lambda item: (
            item.display_name.casefold(),
            item.firm_id,
        ),
    )
