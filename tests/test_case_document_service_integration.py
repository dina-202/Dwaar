"""End-to-end integration test for case PDF persistence."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import fitz
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.case_models import (
    CaseDocumentKind,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
)
from domain.models import NoticeForm, ProceedingType
from modules.case_document_service import persist_pdf_document
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 13, 30, tzinfo=timezone.utc)


def make_pdf() -> bytes:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "Dwaar durable document integration test")
        return doc.tobytes()
    finally:
        doc.close()


class CaseDocumentPersistenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")
        self.repo = LocalSQLiteCaseRepository(self.db_path)
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=2 * 1024 * 1024,
        )

        self.repo.create_firm(
            Firm("F-001", "Pilot CA Firm", NOW)
        )
        self.repo.create_client(
            Client("C-001", "F-001", "Pilot Client", NOW)
        )
        self.repo.create_case(
            CaseRecord(
                case_id="CASE-001",
                firm_id="F-001",
                client_id="C-001",
                registration_id=None,
                title="DRC-01 pilot matter",
                status=CaseStatus.INTAKE,
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_document_persistence_survives_repository_restart(self):
        payload = make_pdf()

        document = persist_pdf_document(
            self.repo,
            self.store,
            case_id="CASE-001",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            payload=payload,
            actor_id="USER-001",
            created_at=NOW,
        )

        self.assertTrue(self.store.exists(document.storage_key))
        self.assertEqual(self.store.get(document.storage_key), payload)

        reopened = LocalSQLiteCaseRepository(self.db_path)
        documents = reopened.list_document_refs("CASE-001")
        events = reopened.list_events("CASE-001")

        self.assertEqual(documents, [document])
        self.assertEqual(len(events), 1)
        self.assertIs(
            events[0].event_type,
            CaseEventType.DOCUMENT_ADDED,
        )
        self.assertEqual(
            events[0].payload["document_id"],
            document.document_id,
        )
        self.assertEqual(
            events[0].payload["sha256"],
            document.sha256_hex,
        )

        object_files = list(Path(self.object_root).glob("*.dwaar"))
        self.assertEqual(len(object_files), 1)
        encrypted_bytes = object_files[0].read_bytes()
        self.assertNotIn(payload, encrypted_bytes)
        self.assertNotIn(b"Dwaar durable document", encrypted_bytes)


if __name__ == "__main__":
    unittest.main()
