"""Integration tests for the local SQLite case metadata repository."""

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
    TaxRegistration,
)
from domain.models import NoticeForm, ProceedingType
from modules.sqlite_case_repository import (
    LocalSQLiteCaseRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


NOW = datetime(2026, 9, 22, 12, 30, tzinfo=timezone.utc)


def firm(firm_id="F-001"):
    return Firm(firm_id, "Sangwan & Co", NOW)


def client(client_id="C-001", firm_id="F-001"):
    return Client(client_id, firm_id, "Example Client", NOW)


def registration(
    registration_id="R-001",
    client_id="C-001",
):
    return TaxRegistration(
        registration_id,
        client_id,
        "IN-HR-GST",
        "GSTIN",
        "06ABCDE1234F1Z5",
        NOW,
    )


def case_record(
    case_id="CASE-001",
    firm_id="F-001",
    client_id="C-001",
    registration_id="R-001",
    opened_at=NOW,
):
    return CaseRecord(
        case_id=case_id,
        firm_id=firm_id,
        client_id=client_id,
        registration_id=registration_id,
        title="DRC-01 ITC mismatch",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=opened_at,
    )


class RepositoryFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "dwaar.db")
        self.repo = LocalSQLiteCaseRepository(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def seed_case(self):
        self.repo.create_firm(firm())
        self.repo.create_client(client())
        self.repo.create_registration(registration())
        self.repo.create_case(case_record())


class SchemaAndRestartTests(RepositoryFixture):
    def test_database_file_is_created(self):
        self.assertTrue(Path(self.db_path).exists())

    def test_records_survive_repository_recreation(self):
        self.seed_case()
        reopened = LocalSQLiteCaseRepository(self.db_path)
        self.assertEqual(reopened.get_firm("F-001"), firm())
        self.assertEqual(reopened.get_client("C-001"), client())
        self.assertEqual(
            reopened.get_registration("R-001"),
            registration(),
        )
        self.assertEqual(
            reopened.get_case("CASE-001"),
            case_record(),
        )


class HierarchyTests(RepositoryFixture):
    def test_create_and_read_full_hierarchy(self):
        self.seed_case()
        self.assertEqual(self.repo.get_firm("F-001"), firm())
        self.assertEqual(self.repo.get_client("C-001"), client())
        self.assertEqual(
            self.repo.get_registration("R-001"), registration()
        )
        self.assertEqual(self.repo.get_case("CASE-001"), case_record())

    def test_missing_values_return_none(self):
        self.assertIsNone(self.repo.get_firm("missing"))
        self.assertIsNone(self.repo.get_client("missing"))
        self.assertIsNone(self.repo.get_registration("missing"))
        self.assertIsNone(self.repo.get_case("missing"))
        self.assertIsNone(self.repo.get_snapshot("missing"))

    def test_client_requires_existing_firm(self):
        with self.assertRaises(RepositoryConflictError):
            self.repo.create_client(client())

    def test_registration_requires_existing_client(self):
        with self.assertRaises(RepositoryConflictError):
            self.repo.create_registration(registration())

    def test_case_requires_existing_firm(self):
        with self.assertRaises(RepositoryNotFoundError):
            self.repo.create_case(case_record())

    def test_case_client_must_belong_to_same_firm(self):
        self.repo.create_firm(firm("F-001"))
        self.repo.create_firm(firm("F-002"))
        self.repo.create_client(client(firm_id="F-002"))
        with self.assertRaisesRegex(
            RepositoryConflictError, "does not belong"
        ):
            self.repo.create_case(
                case_record(registration_id=None)
            )

    def test_case_registration_must_belong_to_client(self):
        self.repo.create_firm(firm())
        self.repo.create_client(client("C-001"))
        self.repo.create_client(client("C-002"))
        self.repo.create_registration(
            registration(client_id="C-002")
        )
        with self.assertRaisesRegex(
            RepositoryConflictError, "does not belong"
        ):
            self.repo.create_case(case_record())

    def test_case_can_exist_without_registration(self):
        self.repo.create_firm(firm())
        self.repo.create_client(client())
        value = case_record(registration_id=None)
        self.repo.create_case(value)
        self.assertEqual(self.repo.get_case(value.case_id), value)

    def test_duplicate_ids_raise_controlled_conflict(self):
        self.repo.create_firm(firm())
        with self.assertRaises(RepositoryConflictError):
            self.repo.create_firm(firm())


class CaseUpdateTests(RepositoryFixture):
    def setUp(self):
        super().setUp()
        self.seed_case()

    def test_operational_fields_can_update(self):
        current = self.repo.get_case("CASE-001")
        updated = replace(
            current,
            title="Updated title",
            status=CaseStatus.EVIDENCE_COLLECTION,
            response_deadline=date(2026, 10, 5),
            assigned_to="USER-A",
            reviewer_id="USER-B",
        )
        self.repo.update_case(updated)
        self.assertEqual(self.repo.get_case("CASE-001"), updated)

    def test_close_timestamp_can_update(self):
        current = self.repo.get_case("CASE-001")
        updated = replace(
            current,
            status=CaseStatus.CLOSED,
            closed_at=NOW + timedelta(days=10),
        )
        self.repo.update_case(updated)
        self.assertEqual(self.repo.get_case("CASE-001"), updated)

    def test_identity_fields_cannot_change(self):
        current = self.repo.get_case("CASE-001")
        mutations = [
            replace(current, firm_id="OTHER"),
            replace(current, client_id="OTHER"),
            replace(current, registration_id=None),
            replace(
                current,
                proceeding_type=ProceedingType.GST_SEC74_FRAUD,
            ),
            replace(current, notice_form=NoticeForm.UNKNOWN),
            replace(current, opened_at=NOW + timedelta(seconds=1)),
        ]
        for value in mutations:
            with self.subTest(value=value):
                with self.assertRaises(RepositoryConflictError):
                    self.repo.update_case(value)

    def test_update_missing_case_raises_not_found(self):
        with self.assertRaises(RepositoryNotFoundError):
            self.repo.update_case(
                replace(case_record(), case_id="MISSING")
            )


class CaseOrderingTests(RepositoryFixture):
    def test_list_cases_is_firm_scoped_and_newest_first(self):
        self.repo.create_firm(firm("F-001"))
        self.repo.create_firm(firm("F-002"))
        self.repo.create_client(client("C-001", "F-001"))
        self.repo.create_client(client("C-002", "F-002"))

        older = case_record(
            "CASE-OLD",
            registration_id=None,
            opened_at=NOW,
        )
        newer = case_record(
            "CASE-NEW",
            registration_id=None,
            opened_at=NOW + timedelta(days=1),
        )
        other = case_record(
            "CASE-OTHER",
            firm_id="F-002",
            client_id="C-002",
            registration_id=None,
            opened_at=NOW + timedelta(days=2),
        )
        self.repo.create_case(older)
        self.repo.create_case(newer)
        self.repo.create_case(other)

        self.assertEqual(
            [item.case_id for item in self.repo.list_cases("F-001")],
            ["CASE-NEW", "CASE-OLD"],
        )
        self.assertEqual(
            [item.case_id for item in self.repo.list_cases("F-002")],
            ["CASE-OTHER"],
        )


class DocumentReferenceTests(RepositoryFixture):
    def setUp(self):
        super().setUp()
        self.seed_case()

    def document(self, document_id="DOC-001", created_at=NOW):
        return StoredDocumentRef(
            document_id=document_id,
            case_id="CASE-001",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=1234,
            sha256_hex="a" * 64,
            storage_key=f"opaque/{document_id}",
            created_at=created_at,
        )

    def test_document_metadata_round_trip(self):
        value = self.document()
        self.repo.add_document_ref(value)
        self.assertEqual(
            self.repo.list_document_refs("CASE-001"),
            [value],
        )

    def test_raw_bytes_are_not_stored_by_api(self):
        value = self.document()
        self.assertFalse(hasattr(value, "payload"))
        self.repo.add_document_ref(value)
        loaded = self.repo.list_document_refs("CASE-001")[0]
        self.assertFalse(hasattr(loaded, "payload"))

    def test_invalid_sha256_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.add_document_ref(
                replace(self.document(), sha256_hex="not-a-hash")
            )

    def test_duplicate_storage_key_is_rejected(self):
        first = self.document("DOC-001")
        second = replace(
            self.document("DOC-002"),
            storage_key=first.storage_key,
        )
        self.repo.add_document_ref(first)
        with self.assertRaises(RepositoryConflictError):
            self.repo.add_document_ref(second)

    def test_document_requires_existing_case(self):
        with self.assertRaises(RepositoryConflictError):
            self.repo.add_document_ref(
                replace(self.document(), case_id="MISSING")
            )

    def test_document_order_is_created_then_id(self):
        later = self.document(
            "DOC-LATER", NOW + timedelta(minutes=1)
        )
        earlier = self.document("DOC-EARLY", NOW)
        self.repo.add_document_ref(later)
        self.repo.add_document_ref(earlier)
        self.assertEqual(
            [
                item.document_id
                for item in self.repo.list_document_refs("CASE-001")
            ],
            ["DOC-EARLY", "DOC-LATER"],
        )


class EventTests(RepositoryFixture):
    def setUp(self):
        super().setUp()
        self.seed_case()

    def event(
        self,
        event_id="EV-001",
        occurred_at=NOW,
        payload=None,
    ):
        return CaseEvent(
            event_id=event_id,
            case_id="CASE-001",
            event_type=CaseEventType.CASE_CREATED,
            occurred_at=occurred_at,
            actor_id="USER-001",
            payload={"status": "intake"} if payload is None else payload,
        )

    def test_event_round_trip(self):
        value = self.event()
        self.repo.append_event(value)
        self.assertEqual(self.repo.list_events("CASE-001"), [value])

    def test_events_are_ordered_chronologically(self):
        later = self.event(
            "EV-LATER", NOW + timedelta(seconds=1)
        )
        earlier = self.event("EV-EARLY", NOW)
        self.repo.append_event(later)
        self.repo.append_event(earlier)
        self.assertEqual(
            [item.event_id for item in self.repo.list_events("CASE-001")],
            ["EV-EARLY", "EV-LATER"],
        )

    def test_event_requires_existing_case(self):
        value = replace(self.event(), case_id="MISSING")
        with self.assertRaises(RepositoryConflictError):
            self.repo.append_event(value)

    def test_duplicate_event_id_is_rejected(self):
        self.repo.append_event(self.event())
        with self.assertRaises(RepositoryConflictError):
            self.repo.append_event(self.event())

    def test_sensitive_payload_fields_are_rejected(self):
        for key in (
            "raw_text",
            "source_text",
            "access_token",
            "password",
            "secret",
            "api_key",
            "authorization",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.repo.append_event(
                        self.event(payload={key: "sensitive"})
                    )

    def test_non_string_event_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.append_event(
                self.event(payload={"count": 3})
            )

    def test_oversized_payload_value_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.append_event(
                self.event(payload={"note": "x" * 1001})
            )

    def test_event_payload_json_is_deterministic_after_roundtrip(self):
        value = self.event(payload={"z": "last", "a": "first"})
        self.repo.append_event(value)
        self.assertEqual(self.repo.list_events("CASE-001")[0], value)


class SnapshotTests(RepositoryFixture):
    def test_snapshot_combines_case_documents_and_events(self):
        self.seed_case()
        document = StoredDocumentRef(
            "DOC-1",
            "CASE-001",
            CaseDocumentKind.NOTICE,
            "notice.pdf",
            "application/pdf",
            10,
            "b" * 64,
            "opaque/doc-1",
            NOW,
        )
        event = CaseEvent(
            "EV-1",
            "CASE-001",
            CaseEventType.CASE_CREATED,
            NOW,
            "USER-1",
            {"status": "intake"},
        )
        self.repo.add_document_ref(document)
        self.repo.append_event(event)

        snapshot = self.repo.get_snapshot("CASE-001")
        self.assertEqual(snapshot.case, case_record())
        self.assertEqual(snapshot.documents, [document])
        self.assertEqual(snapshot.events, [event])


class DatetimeSafetyTests(RepositoryFixture):
    def test_naive_datetime_is_rejected(self):
        naive = datetime(2026, 9, 22, 12, 30)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.repo.create_firm(Firm("F-X", "Firm", naive))


if __name__ == "__main__":
    unittest.main()
