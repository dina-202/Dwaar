"""Tests for deterministic firm/case authorization."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    AuthorizationError,
    FirmAccessGrant,
)
from domain.authorization import (
    require_case_permission,
    require_firm_permission,
)
from domain.case_models import CaseRecord, CaseStatus
from domain.models import NoticeForm, ProceedingType


NOW = datetime(2026, 9, 22, 14, 0, tzinfo=timezone.utc)


def principal(user_id="U-1"):
    return AuthenticatedPrincipal(user_id=user_id)


def grant(
    user_id="U-1",
    firm_id="F-1",
    permissions=None,
    active=True,
):
    return FirmAccessGrant(
        user_id=user_id,
        firm_id=firm_id,
        permissions=frozenset(
            permissions
            if permissions is not None
            else {AccessPermission.CASE_READ}
        ),
        active=active,
    )


def case_record(firm_id="F-1"):
    return CaseRecord(
        case_id="CASE-1",
        firm_id=firm_id,
        client_id="C-1",
        registration_id=None,
        title="Matter",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


class AuthorizationContractTests(unittest.TestCase):
    def test_exact_permission_vocabulary(self):
        self.assertEqual(
            [item.value for item in AccessPermission],
            [
                "case_read",
                "case_create",
                "case_update",
                "document_read",
                "document_add",
                "evidence_review",
                "fact_review",
                "draft_review",
                "filing_record",
                "firm_admin",
            ],
        )

    def test_principal_is_frozen(self):
        value = principal()
        with self.assertRaises(FrozenInstanceError):
            value.user_id = "U-2"

    def test_grant_permissions_are_explicit_frozenset(self):
        value = grant(
            permissions={
                AccessPermission.CASE_READ,
                AccessPermission.DOCUMENT_READ,
            }
        )
        self.assertIsInstance(value.permissions, frozenset)
        self.assertEqual(
            value.permissions,
            frozenset(
                {
                    AccessPermission.CASE_READ,
                    AccessPermission.DOCUMENT_READ,
                }
            ),
        )


class FirmAuthorizationTests(unittest.TestCase):
    def test_explicit_permission_allows(self):
        require_firm_permission(
            principal(),
            grant(permissions={AccessPermission.CASE_CREATE}),
            "F-1",
            AccessPermission.CASE_CREATE,
        )

    def test_missing_permission_denies(self):
        with self.assertRaisesRegex(
            AuthorizationError, "not granted"
        ):
            require_firm_permission(
                principal(),
                grant(permissions={AccessPermission.CASE_READ}),
                "F-1",
                AccessPermission.CASE_UPDATE,
            )

    def test_wrong_user_denies(self):
        with self.assertRaisesRegex(
            AuthorizationError, "does not belong"
        ):
            require_firm_permission(
                principal("U-1"),
                grant(user_id="U-2"),
                "F-1",
                AccessPermission.CASE_READ,
            )

    def test_wrong_firm_denies(self):
        with self.assertRaisesRegex(
            AuthorizationError, "another firm"
        ):
            require_firm_permission(
                principal(),
                grant(firm_id="F-2"),
                "F-1",
                AccessPermission.CASE_READ,
            )

    def test_inactive_grant_denies(self):
        with self.assertRaisesRegex(AuthorizationError, "inactive"):
            require_firm_permission(
                principal(),
                grant(active=False),
                "F-1",
                AccessPermission.CASE_READ,
            )

    def test_firm_admin_does_not_implicitly_grant_case_read(self):
        with self.assertRaises(AuthorizationError):
            require_firm_permission(
                principal(),
                grant(permissions={AccessPermission.FIRM_ADMIN}),
                "F-1",
                AccessPermission.CASE_READ,
            )

    def test_permission_type_is_closed(self):
        with self.assertRaises(TypeError):
            require_firm_permission(
                principal(),
                grant(),
                "F-1",
                "case_read",
            )


class CaseAuthorizationTests(unittest.TestCase):
    def test_same_firm_case_and_permission_allows(self):
        require_case_permission(
            principal(),
            grant(permissions={AccessPermission.DOCUMENT_READ}),
            case_record("F-1"),
            AccessPermission.DOCUMENT_READ,
        )

    def test_cross_firm_case_denies_even_with_permission(self):
        with self.assertRaises(AuthorizationError):
            require_case_permission(
                principal(),
                grant(
                    firm_id="F-1",
                    permissions={AccessPermission.DOCUMENT_READ},
                ),
                case_record("F-2"),
                AccessPermission.DOCUMENT_READ,
            )

    def test_case_permission_does_not_accept_non_case(self):
        with self.assertRaises(TypeError):
            require_case_permission(
                principal(),
                grant(),
                object(),
                AccessPermission.CASE_READ,
            )


if __name__ == "__main__":
    unittest.main()
