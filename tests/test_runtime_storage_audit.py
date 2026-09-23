"""Tests for Phase 3P.6 live encrypted-storage consistency audit."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
)
from domain.models import NoticeForm, ProceedingType
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.runtime_backup import create_runtime_backup, verify_runtime_backup
from modules.runtime_storage_audit import (
    audit_runtime_storage,
    discover_storage_key_tables,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)
KEY = b"s" * 32
PRIMARY_KEY = "objects/" + "1" * 32
EXTRA_KEY = "objects/" + "2" * 32


class RuntimeStorageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "dwaar.db"
        self.objects = self.root / "objects"
        self.backups = self.root / "backups"

        self.repo = LocalSQLiteCaseRepository(str(self.db))
        self.repo.create_firm(Firm("F-1", "Firm", NOW))
        self.repo.create_client(Client("C-1", "F-1", "Client", NOW))
        self.repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.INTAKE,
                proceeding_type=ProceedingType.GST_SEC73_GENERAL,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        self.store = EncryptedLocalDocumentStore(
            str(self.objects),
            KEY,
        )
        self.store.put(PRIMARY_KEY, b"notice payload")
        self.repo.add_document_ref(
            StoredDocumentRef(
                document_id="DOC-1",
                case_id="CASE-1",
                kind=CaseDocumentKind.NOTICE,
                original_filename="notice.pdf",
                media_type="application/pdf",
                byte_size=len(b"notice payload"),
                sha256_hex="a" * 64,
                storage_key=PRIMARY_KEY,
                created_at=NOW,
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, key=KEY):
        return audit_runtime_storage(
            db_path=str(self.db),
            object_root=str(self.objects),
            document_key=key,
        )

    def test_clean_runtime_is_consistent(self):
        report = self.audit()
        self.assertTrue(report.consistent)
        self.assertEqual(report.storage_table_count, 6)
        self.assertEqual(report.referenced_object_count, 1)
        self.assertEqual(report.object_file_count, 1)
        self.assertEqual(report.missing_object_count, 0)
        self.assertEqual(report.orphan_object_count, 0)
        self.assertEqual(report.invalid_reference_count, 0)
        self.assertEqual(report.invalid_object_entry_count, 0)
        self.assertEqual(report.authentication_failure_count, 0)

    def test_storage_tables_are_discovered_from_schema(self):
        with sqlite3.connect(str(self.db)) as connection:
            self.assertEqual(
                discover_storage_key_tables(connection),
                (
                    "analysis_snapshots",
                    "case_documents",
                    "draft_versions",
                    "evidence_reviews",
                    "fact_reviews",
                    "legal_briefs",
                ),
            )

    def test_missing_referenced_object_is_reported(self):
        self.store.delete(PRIMARY_KEY)
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.missing_object_count, 1)
        self.assertEqual(report.orphan_object_count, 0)

    def test_orphan_encrypted_object_is_reported(self):
        self.store.put(EXTRA_KEY, b"orphan payload")
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.orphan_object_count, 1)
        self.assertEqual(report.missing_object_count, 0)

    def test_invalid_object_entry_is_reported_without_name_leak(self):
        (self.objects / "unexpected.txt").write_text(
            "opaque",
            encoding="utf-8",
        )
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.invalid_object_entry_count, 1)
        self.assertNotIn("unexpected.txt", repr(report))

    def test_wrong_key_is_an_authentication_failure(self):
        report = self.audit(key=b"x" * 32)
        self.assertFalse(report.consistent)
        self.assertEqual(report.authentication_failure_count, 1)
        self.assertEqual(report.missing_object_count, 0)

    def test_invalid_database_reference_stops_orphan_inference(self):
        with sqlite3.connect(str(self.db)) as connection:
            connection.execute(
                """
                UPDATE case_documents
                SET storage_key = 'unsafe/path'
                WHERE document_id = 'DOC-1'
                """
            )
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.invalid_reference_count, 1)
        self.assertEqual(report.missing_object_count, 0)
        self.assertEqual(report.orphan_object_count, 0)

    def test_duplicate_reference_across_tables_fails_reference_inventory(self):
        with sqlite3.connect(str(self.db)) as connection:
            connection.execute(
                """
                CREATE TABLE custom_payloads(
                    item_id TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO custom_payloads(item_id, storage_key)
                VALUES ('I-1', ?)
                """,
                (PRIMARY_KEY,),
            )
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.invalid_reference_count, 1)
        self.assertEqual(report.storage_table_count, 7)

    def test_new_storage_table_is_audited_and_backed_up_automatically(self):
        self.store.put(EXTRA_KEY, b"future artifact")
        with sqlite3.connect(str(self.db)) as connection:
            connection.execute(
                """
                CREATE TABLE custom_payloads(
                    item_id TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                """
                INSERT INTO custom_payloads(item_id, storage_key)
                VALUES ('I-1', ?)
                """,
                (EXTRA_KEY,),
            )

        report = self.audit()
        self.assertTrue(report.consistent)
        self.assertEqual(report.storage_table_count, 7)
        self.assertEqual(report.referenced_object_count, 2)

        manifest = create_runtime_backup(
            db_path=str(self.db),
            object_root=str(self.objects),
            backup_root=str(self.backups),
            backup_id="dynamic-storage",
            created_at=NOW,
            document_key=KEY,
            document_key_id="doc-key-storage-a",
        )
        self.assertEqual(manifest.object_count, 2)
        self.assertEqual(
            [item.storage_key for item in manifest.objects],
            [PRIMARY_KEY, EXTRA_KEY],
        )
        verify_runtime_backup(
            str(self.backups / "dynamic-storage"),
            document_key=KEY,
            expected_document_key_id="doc-key-storage-a",
        )

    def test_subdirectory_inside_object_store_is_invalid_entry(self):
        (self.objects / "unexpected-dir").mkdir()
        report = self.audit()
        self.assertFalse(report.consistent)
        self.assertEqual(report.invalid_object_entry_count, 1)


if __name__ == "__main__":
    unittest.main()
