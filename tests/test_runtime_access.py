"""Tests for runtime firm-access discovery."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import Firm
from modules.runtime_access import (
    RuntimeAccessConfigurationError,
    database_path_from_environment,
    load_available_firms,
)
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)


class RuntimeDatabasePathTests(unittest.TestCase):
    def test_configured_path_is_returned(self):
        self.assertEqual(
            database_path_from_environment(
                {"DWAAR_DB_PATH": "  ./pilot.db  "}
            ),
            "pilot.db",
        )

    def test_missing_path_fails_closed(self):
        for environment in ({}, {"DWAAR_DB_PATH": "   "}):
            with self.subTest(environment=environment):
                with self.assertRaises(
                    RuntimeAccessConfigurationError
                ):
                    database_path_from_environment(environment)


class RuntimeFirmAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "dwaar.db")
        self.case_repo = LocalSQLiteCaseRepository(self.db_path)
        self.case_repo.create_firm(
            Firm("F-1", "Alpha & Co", NOW)
        )
        self.case_repo.create_firm(
            Firm("F-2", "Beta & Co", NOW)
        )
        self.case_repo.create_firm(
            Firm("F-3", "Gamma & Co", NOW)
        )
        self.access_repo = LocalSQLiteAccessGrantRepository(
            self.db_path
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def save(
        self,
        firm_id,
        permissions,
        *,
        active=True,
        user_id="U-1",
    ):
        self.access_repo.save_grant(
            FirmAccessGrant(
                user_id=user_id,
                firm_id=firm_id,
                permissions=frozenset(permissions),
                active=active,
            )
        )

    def test_only_active_grants_with_exact_permission_are_returned(self):
        self.save(
            "F-1",
            {AccessPermission.CASE_CREATE},
        )
        self.save(
            "F-2",
            {AccessPermission.CASE_READ},
        )
        self.save(
            "F-3",
            {AccessPermission.CASE_CREATE},
            active=False,
        )

        result = load_available_firms(
            AuthenticatedPrincipal("U-1"),
            self.db_path,
            AccessPermission.CASE_CREATE,
        )
        self.assertEqual(
            result,
            [
                result[0].__class__(
                    firm_id="F-1",
                    display_name="Alpha & Co",
                )
            ],
        )

    def test_other_users_grants_are_not_returned(self):
        self.save(
            "F-1",
            {AccessPermission.CASE_CREATE},
            user_id="U-2",
        )
        self.assertEqual(
            load_available_firms(
                AuthenticatedPrincipal("U-1"),
                self.db_path,
                AccessPermission.CASE_CREATE,
            ),
            [],
        )

    def test_multiple_firms_are_sorted_by_display_name(self):
        self.save(
            "F-2",
            {AccessPermission.CASE_CREATE},
        )
        self.save(
            "F-1",
            {AccessPermission.CASE_CREATE},
        )
        result = load_available_firms(
            AuthenticatedPrincipal("U-1"),
            self.db_path,
            AccessPermission.CASE_CREATE,
        )
        self.assertEqual(
            [item.firm_id for item in result],
            ["F-1", "F-2"],
        )

    def test_permission_type_is_closed(self):
        with self.assertRaises(TypeError):
            load_available_firms(
                AuthenticatedPrincipal("U-1"),
                self.db_path,
                "case_create",
            )


if __name__ == "__main__":
    unittest.main()
