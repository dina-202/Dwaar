"""Deterministic authorization checks for firm and case access."""

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
    FirmAccessGrant,
)
from domain.case_models import CaseRecord


def require_firm_permission(
    principal: AuthenticatedPrincipal,
    grant: FirmAccessGrant,
    firm_id: str,
    permission: AccessPermission,
) -> None:
    """Require one explicit permission inside exactly one firm."""
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")
    if not isinstance(grant, FirmAccessGrant):
        raise TypeError("grant must be a FirmAccessGrant")
    if not isinstance(permission, AccessPermission):
        raise TypeError("permission must be an AccessPermission")
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id must be a non-empty string")

    if not grant.active:
        raise AuthorizationError("firm access grant is inactive")
    if grant.user_id != principal.user_id:
        raise AuthorizationError("firm access grant does not belong to user")
    if grant.firm_id != firm_id:
        raise AuthorizationError("firm access grant is for another firm")
    if permission not in grant.permissions:
        raise AuthorizationError("required permission is not granted")


def require_case_permission(
    principal: AuthenticatedPrincipal,
    grant: FirmAccessGrant,
    case: CaseRecord,
    permission: AccessPermission,
) -> None:
    """Require permission and prove the case belongs to the same firm."""
    if not isinstance(case, CaseRecord):
        raise TypeError("case must be a CaseRecord")

    require_firm_permission(
        principal,
        grant,
        case.firm_id,
        permission,
    )
