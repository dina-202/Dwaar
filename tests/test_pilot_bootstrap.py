"""Tests for one-time Dwaar pilot provisioning."""

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.auth_models import AccessPermission
from modules.pilot_bootstrap import (
    BootstrapRefusedError,
    bootstrap_initial_firm,
)
from modules.sqlite_access_grant_repository import (
    LocalSQLiteAccessGrantRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 17, 0, tzinfo=timezone.utc)
USER_ID = "OIDC-" + hashlib.sha256(b"issuer\0subject").hexdigest()


class PilotBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "dwaar.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bootstrap_creates_firm_and_full_explicit_grant(self):
        firm, grant = bootstrap_initial_firm(
            self.db_path,
            firm_name="  Pilot CA Firm  ",
            user_id=USER_ID,
            now=NOW,
        )
        self.assertTrue(firm.firm_id.startswith("FIRM-"))
        self.assertEqual(len(firm.firm_id), 37)
        self.assertEqual(firm.display_name, "Pilot CA Firm")
        self.assertEqual(firm.created_at, NOW)
        self.assertEqual(grant.user_id, USER_ID)
        self.assertEqual(grant.firm_id, firm.firm_id)
        self.assertEqual(
            grant.permissions,
            frozenset(AccessPermission),
        )
        self.assertTrue(grant.active)

        case_repo = LocalSQLiteCaseRepository(self.db_path)
        access_repo = LocalSQLiteAccessGrantRepository(self.db_path)
        self.assertEqual(case_repo.get_firm(firm.firm_id), firm)
        self.assertEqual(
            access_repo.get_grant(USER_ID, firm.firm_id),
            grant,
        )

    def test_second_bootstrap_is_refused_without_creating_more_firms(self):
        first, _ = bootstrap_initial_firm(
            self.db_path,
            firm_name="First Firm",
            user_id=USER_ID,
            now=NOW,
        )
        with self.assertRaises(BootstrapRefusedError):
            bootstrap_initial_firm(
                self.db_path,
                firm_name="Second Firm",
                user_id=USER_ID,
                now=NOW,
            )

        repo = LocalSQLiteCaseRepository(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT firm_id FROM firms"
            ).fetchall()
        self.assertEqual(rows, [(first.firm_id,)])
        self.assertIsNone(repo.get_firm("Second Firm"))

    def test_invalid_oidc_user_id_is_rejected_before_database_creation(self):
        for user_id in (
            "",
            "plain-user",
            "OIDC-short",
            "OIDC-" + "g" * 64,
        ):
            with self.subTest(user_id=user_id):
                path = str(
                    Path(self.temp_dir.name)
                    / (hashlib.sha256(user_id.encode()).hexdigest() + ".db")
                )
                with self.assertRaises(ValueError):
                    bootstrap_initial_firm(
                        path,
                        firm_name="Firm",
                        user_id=user_id,
                        now=NOW,
                    )
                self.assertFalse(Path(path).exists())

    def test_naive_timestamp_is_rejected_before_database_creation(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            bootstrap_initial_firm(
                self.db_path,
                firm_name="Firm",
                user_id=USER_ID,
                now=datetime(2026, 9, 22, 17, 0),
            )
        self.assertFalse(Path(self.db_path).exists())

    def test_blank_or_oversized_firm_name_is_rejected(self):
        for name in ("", "   ", "x" * 201):
            with self.subTest(name_length=len(name)):
                with self.assertRaises(ValueError):
                    bootstrap_initial_firm(
                        self.db_path,
                        firm_name=name,
                        user_id=USER_ID,
                        now=NOW,
                    )

    def test_grant_insert_failure_rolls_back_firm_insert(self):
        # Initialize schemas while leaving firms empty.
        LocalSQLiteCaseRepository(self.db_path)
        LocalSQLiteAccessGrantRepository(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_bootstrap_grant
                BEFORE INSERT ON firm_access_grants
                BEGIN
                    SELECT RAISE(ABORT, 'forced grant failure');
                END
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            bootstrap_initial_firm(
                self.db_path,
                firm_name="Firm",
                user_id=USER_ID,
                now=NOW,
            )

        with sqlite3.connect(self.db_path) as connection:
            firm_count = connection.execute(
                "SELECT COUNT(*) FROM firms"
            ).fetchone()[0]
            grant_count = connection.execute(
                "SELECT COUNT(*) FROM firm_access_grants"
            ).fetchone()[0]
        self.assertEqual(firm_count, 0)
        self.assertEqual(grant_count, 0)


if __name__ == "__main__":
    unittest.main()
