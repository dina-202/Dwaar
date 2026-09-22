"""Tests for SQLite firm access grant persistence."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from domain.auth_models import AccessPermission, FirmAccessGrant
from domain.case_models import Firm
from modules.sqlite_access_grant_repository import (
    AccessGrantConflictError,
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from datetime import datetime, timezone


NOW = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)


class SQLiteAccessGrantRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "dwaar.db")
        self.case_repo = LocalSQLiteCaseRepository(self.db_path)
        self.case_repo.create_firm(Firm("F-1", "Firm One", NOW))
        self.case_repo.create_firm(Firm("F-2", "Firm Two", NOW))
        self.repo = LocalSQLiteAccessGrantRepository(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def grant(
        self,
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
                else {
                    AccessPermission.CASE_READ,
                    AccessPermission.DOCUMENT_READ,
                }
            ),
            active=active,
        )

    def test_round_trip(self):
        value = self.grant()
        self.repo.save_grant(value)
        self.assertEqual(self.repo.get_grant("U-1", "F-1"), value)

    def test_save_replaces_permissions_and_active_state(self):
        self.repo.save_grant(self.grant())
        updated = self.grant(
            permissions={AccessPermission.CASE_UPDATE},
            active=False,
        )
        self.repo.save_grant(updated)
        self.assertEqual(self.repo.get_grant("U-1", "F-1"), updated)

    def test_missing_grant_returns_none(self):
        self.assertIsNone(self.repo.get_grant("U-X", "F-1"))

    def test_list_grants_is_user_scoped_and_firm_sorted(self):
        self.repo.save_grant(self.grant(firm_id="F-2"))
        self.repo.save_grant(self.grant(firm_id="F-1"))
        self.repo.save_grant(self.grant(user_id="U-2", firm_id="F-1"))
        self.assertEqual(
            [g.firm_id for g in self.repo.list_grants_for_user("U-1")],
            ["F-1", "F-2"],
        )

    def test_unknown_firm_is_rejected(self):
        with self.assertRaises(AccessGrantConflictError):
            self.repo.save_grant(self.grant(firm_id="MISSING"))

    def test_permissions_are_serialized_deterministically(self):
        value = self.grant(
            permissions={
                AccessPermission.DOCUMENT_READ,
                AccessPermission.CASE_READ,
                AccessPermission.CASE_UPDATE,
            }
        )
        self.repo.save_grant(value)
        with sqlite3.connect(self.db_path) as connection:
            raw = connection.execute(
                """
                SELECT permissions_json
                FROM firm_access_grants
                WHERE user_id = ? AND firm_id = ?
                """,
                ("U-1", "F-1"),
            ).fetchone()[0]
        self.assertEqual(
            raw,
            '["case_read","case_update","document_read"]',
        )

    def test_unknown_persisted_permission_fails_closed(self):
        self.repo.save_grant(self.grant())
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE firm_access_grants
                SET permissions_json = ?
                WHERE user_id = ? AND firm_id = ?
                """,
                ('["case_read","future_unknown_permission"]', "U-1", "F-1"),
            )
        with self.assertRaisesRegex(RuntimeError, "unknown permission"):
            self.repo.get_grant("U-1", "F-1")

    def test_duplicate_persisted_permission_is_rejected(self):
        self.repo.save_grant(self.grant())
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE firm_access_grants
                SET permissions_json = ?
                WHERE user_id = ? AND firm_id = ?
                """,
                ('["case_read","case_read"]', "U-1", "F-1"),
            )
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            self.repo.get_grant("U-1", "F-1")

    def test_invalid_grant_permission_type_is_rejected(self):
        bad = FirmAccessGrant(
            user_id="U-1",
            firm_id="F-1",
            permissions=frozenset({"case_read"}),
            active=True,
        )
        with self.assertRaises(TypeError):
            self.repo.save_grant(bad)

    def test_repository_recreation_preserves_grants(self):
        value = self.grant()
        self.repo.save_grant(value)
        reopened = LocalSQLiteAccessGrantRepository(self.db_path)
        self.assertEqual(reopened.get_grant("U-1", "F-1"), value)


if __name__ == "__main__":
    unittest.main()
