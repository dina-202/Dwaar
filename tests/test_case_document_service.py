"""Tests for coordinated encrypted case-document persistence."""

import hashlib
import unittest
from datetime import datetime, timezone
from unittest import mock

import fitz

from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
)
from domain.models import NoticeForm, ProceedingType
from modules import case_document_service
from modules.case_document_service import (
    DocumentPersistenceConsistencyError,
    DocumentPersistenceError,
    DocumentValidationError,
    persist_pdf_document,
)


NOW = datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc)


def valid_pdf_bytes():
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "Dwaar test PDF")
        return doc.tobytes()
    finally:
        doc.close()


def case_record(case_id="CASE-001"):
    return CaseRecord(
        case_id=case_id,
        firm_id="F-001",
        client_id="C-001",
        registration_id=None,
        title="Matter",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


class FakeRepository:
    def __init__(self, case=None, add_error=None):
        self.case = case_record() if case is None else case
        self.add_error = add_error
        self.get_case_calls = []
        self.add_calls = []

    def get_case(self, case_id):
        self.get_case_calls.append(case_id)
        return self.case

    def add_document_with_event(self, document, event):
        self.add_calls.append((document, event))
        if self.add_error is not None:
            raise self.add_error


class FakeStore:
    def __init__(self, put_error=None, delete_error=None):
        self.put_error = put_error
        self.delete_error = delete_error
        self.put_calls = []
        self.delete_calls = []

    def put(self, storage_key, payload):
        self.put_calls.append((storage_key, payload))
        if self.put_error is not None:
            raise self.put_error

    def delete(self, storage_key):
        self.delete_calls.append(storage_key)
        if self.delete_error is not None:
            raise self.delete_error

    def get(self, storage_key):
        raise AssertionError("not used")

    def exists(self, storage_key):
        raise AssertionError("not used")


class PersistenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.payload = valid_pdf_bytes()
        self.storage_key = "objects/" + "a" * 32

    def persist(self, repository=None, store=None, **overrides):
        repository = repository or FakeRepository()
        store = store or FakeStore()
        arguments = {
            "case_id": "CASE-001",
            "kind": CaseDocumentKind.NOTICE,
            "original_filename": "notice.pdf",
            "payload": self.payload,
            "actor_id": "USER-001",
            "created_at": NOW,
        }
        arguments.update(overrides)
        with mock.patch.object(
            case_document_service,
            "generate_storage_key",
            return_value=self.storage_key,
        ):
            result = persist_pdf_document(
                repository,
                store,
                **arguments,
            )
        return result, repository, store

    def test_happy_path_stores_bytes_then_metadata_and_event(self):
        result, repository, store = self.persist()
        self.assertEqual(
            store.put_calls,
            [(self.storage_key, self.payload)],
        )
        self.assertEqual(len(repository.add_calls), 1)
        document, event = repository.add_calls[0]
        self.assertEqual(result, document)
        self.assertEqual(document.case_id, "CASE-001")
        self.assertEqual(document.kind, CaseDocumentKind.NOTICE)
        self.assertEqual(document.original_filename, "notice.pdf")
        self.assertEqual(document.media_type, "application/pdf")
        self.assertEqual(document.byte_size, len(self.payload))
        self.assertEqual(
            document.sha256_hex,
            hashlib.sha256(self.payload).hexdigest(),
        )
        self.assertEqual(document.storage_key, self.storage_key)
        self.assertEqual(event.case_id, "CASE-001")
        self.assertEqual(event.event_type.value, "document_added")
        self.assertEqual(event.occurred_at, NOW)
        self.assertEqual(event.actor_id, "USER-001")
        self.assertEqual(
            event.payload,
            {
                "document_id": document.document_id,
                "kind": "notice",
                "sha256": document.sha256_hex,
                "byte_size": str(len(self.payload)),
            },
        )
        self.assertEqual(store.delete_calls, [])

    def test_audit_event_does_not_contain_filename_or_raw_content(self):
        _, repository, _ = self.persist(
            original_filename="Very Sensitive Client Notice.pdf"
        )
        _, event = repository.add_calls[0]
        rendered = repr(event.payload).lower()
        self.assertNotIn("filename", rendered)
        self.assertNotIn("very sensitive", rendered)
        self.assertNotIn("raw_text", rendered)
        self.assertNotIn("source_text", rendered)

    def test_storage_key_is_application_generated_not_filename(self):
        result, _, _ = self.persist(
            original_filename="client notice 2026.pdf"
        )
        self.assertEqual(result.storage_key, self.storage_key)
        self.assertNotIn("client", result.storage_key)

    def test_unknown_case_fails_before_object_write(self):
        repository = FakeRepository(case=None)
        repository.case = None
        store = FakeStore()
        with self.assertRaisesRegex(
            DocumentValidationError, "case does not exist"
        ):
            self.persist(repository=repository, store=store)
        self.assertEqual(store.put_calls, [])
        self.assertEqual(repository.add_calls, [])

    def test_fake_pdf_signature_fails_before_repository_lookup(self):
        repository = FakeRepository()
        store = FakeStore()
        with self.assertRaisesRegex(DocumentValidationError, "PDF signature"):
            self.persist(
                repository=repository,
                store=store,
                payload=b"not a pdf",
            )
        self.assertEqual(repository.get_case_calls, [])
        self.assertEqual(store.put_calls, [])

    def test_corrupt_pdf_with_signature_is_rejected(self):
        repository = FakeRepository()
        store = FakeStore()
        with self.assertRaises(DocumentValidationError):
            self.persist(
                repository=repository,
                store=store,
                payload=b"%PDF-1.7 broken",
            )
        self.assertEqual(store.put_calls, [])

    def test_non_pdf_filename_is_rejected(self):
        with self.assertRaisesRegex(DocumentValidationError, "only PDF"):
            self.persist(original_filename="notice.txt")

    def test_filename_path_separator_is_rejected(self):
        for filename in (
            "../notice.pdf",
            "folder/notice.pdf",
            r"folder\notice.pdf",
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(
                    DocumentValidationError,
                    "path separators",
                ):
                    self.persist(original_filename=filename)

    def test_control_character_filename_is_rejected(self):
        with self.assertRaisesRegex(
            DocumentValidationError,
            "control characters",
        ):
            self.persist(original_filename="notice\n.pdf")

    def test_blank_actor_is_rejected(self):
        with self.assertRaisesRegex(DocumentValidationError, "actor_id"):
            self.persist(actor_id="   ")

    def test_none_actor_is_allowed(self):
        _, repository, _ = self.persist(actor_id=None)
        _, event = repository.add_calls[0]
        self.assertIsNone(event.actor_id)

    def test_naive_created_at_is_rejected(self):
        with self.assertRaisesRegex(
            DocumentValidationError,
            "timezone-aware",
        ):
            self.persist(
                created_at=datetime(2026, 9, 22, 13, 0)
            )

    def test_non_enum_kind_is_rejected(self):
        with self.assertRaisesRegex(DocumentValidationError, "CaseDocumentKind"):
            self.persist(kind="notice")

    def test_object_store_failure_never_calls_repository(self):
        repository = FakeRepository()
        store = FakeStore(put_error=RuntimeError("storage unavailable"))
        with self.assertRaisesRegex(RuntimeError, "storage unavailable"):
            self.persist(repository=repository, store=store)
        self.assertEqual(repository.add_calls, [])
        self.assertEqual(store.delete_calls, [])

    def test_repository_failure_deletes_encrypted_object(self):
        repository = FakeRepository(add_error=RuntimeError("db failed"))
        store = FakeStore()
        with self.assertRaises(DocumentPersistenceError) as caught:
            self.persist(repository=repository, store=store)
        self.assertNotIsInstance(
            caught.exception,
            DocumentPersistenceConsistencyError,
        )
        self.assertEqual(store.put_calls[0][0], self.storage_key)
        self.assertEqual(store.delete_calls, [self.storage_key])
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)

    def test_cleanup_failure_raises_consistency_error(self):
        repository = FakeRepository(add_error=RuntimeError("db failed"))
        store = FakeStore(delete_error=RuntimeError("delete failed"))
        with self.assertRaises(
            DocumentPersistenceConsistencyError
        ) as caught:
            self.persist(repository=repository, store=store)
        self.assertEqual(store.delete_calls, [self.storage_key])
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)

    def test_document_and_event_ids_are_opaque_uuid_style(self):
        result, repository, _ = self.persist()
        _, event = repository.add_calls[0]
        self.assertTrue(result.document_id.startswith("DOC-"))
        self.assertEqual(len(result.document_id), 36)
        int(result.document_id[4:], 16)
        self.assertTrue(event.event_id.startswith("EV-"))
        self.assertEqual(len(event.event_id), 35)
        int(event.event_id[3:], 16)


class PdfValidationTests(unittest.TestCase):
    def test_empty_payload_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            case_document_service._validate_pdf(b"")

    def test_non_bytes_payload_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            case_document_service._validate_pdf("not bytes")

    def test_valid_pdf_is_accepted(self):
        case_document_service._validate_pdf(valid_pdf_bytes())


if __name__ == "__main__":
    unittest.main()
