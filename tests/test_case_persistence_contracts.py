"""Contract tests for Phase 3D persistent case domain."""

import inspect
import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseSnapshot,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
    TaxRegistration,
    utc_now,
)
from domain.models import NoticeForm, ProceedingType
from domain.persistence_ports import (
    AccessGrantRepository,
    AnalysisSnapshotRepository,
    CaseRepository,
    DocumentStore,
    EvidenceReviewRepository,
)


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class EnumContractTests(unittest.TestCase):
    def test_case_status_exact(self):
        self.assertEqual(
            [(m.name, m.value) for m in CaseStatus],
            [
                ("INTAKE", "intake"),
                ("ANALYZED", "analyzed"),
                ("EVIDENCE_COLLECTION", "evidence_collection"),
                ("DRAFT_REVIEW", "draft_review"),
                ("FILED", "filed"),
                ("HEARING", "hearing"),
                ("ORDER_RECEIVED", "order_received"),
                ("CLOSED", "closed"),
            ],
        )

    def test_document_kind_exact(self):
        self.assertEqual(
            [m.value for m in CaseDocumentKind],
            [
                "notice",
                "annexure",
                "supporting_evidence",
                "draft",
                "filed_response",
                "acknowledgement",
                "hearing_document",
                "order",
                "other",
            ],
        )

    def test_event_type_exact(self):
        self.assertEqual(
            [m.value for m in CaseEventType],
            [
                "case_created",
                "case_status_changed",
                "case_operations_updated",
                "document_added",
                "document_removed",
                "analysis_saved",
                "evidence_candidates_generated",
                "evidence_reviewed",
                "draft_created",
                "draft_reviewed",
                "filing_recorded",
                "hearing_recorded",
                "order_recorded",
            ],
        )


class ImmutableContractTests(unittest.TestCase):
    def _assert_frozen(self, value, field_name):
        self.assertTrue(is_dataclass(value))
        with self.assertRaises(FrozenInstanceError):
            setattr(value, field_name, "mutated")

    def test_firm_is_frozen(self):
        self._assert_frozen(Firm("F-1", "Firm", NOW), "display_name")

    def test_client_is_frozen(self):
        self._assert_frozen(Client("C-1", "F-1", "Client", NOW), "display_name")

    def test_registration_is_frozen(self):
        self._assert_frozen(
            TaxRegistration("R-1", "C-1", "IN-GST", "GSTIN", "TEST", NOW),
            "identifier_value",
        )

    def test_case_record_is_frozen(self):
        value = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            "R-1",
            "DRC-01 Aug 2026",
            CaseStatus.INTAKE,
            ProceedingType.GST_SEC73_ITC,
            NoticeForm.DRC_01,
            NOW,
        )
        self._assert_frozen(value, "title")

    def test_document_ref_contains_metadata_not_bytes(self):
        names = [item.name for item in fields(StoredDocumentRef)]
        self.assertEqual(
            names,
            [
                "document_id",
                "case_id",
                "kind",
                "original_filename",
                "media_type",
                "byte_size",
                "sha256_hex",
                "storage_key",
                "created_at",
            ],
        )
        self.assertNotIn("payload", names)
        self.assertNotIn("content", names)
        self.assertNotIn("bytes", names)

    def test_case_event_payload_is_metadata_map(self):
        event = CaseEvent(
            "EV-1",
            "CASE-1",
            CaseEventType.CASE_CREATED,
            NOW,
            "USER-1",
            {"status": "intake"},
        )
        self.assertEqual(event.payload, {"status": "intake"})
        self._assert_frozen(event, "actor_id")

    def test_snapshot_aggregate(self):
        case = CaseRecord(
            "CASE-1",
            "F-1",
            "C-1",
            None,
            "Matter",
            CaseStatus.ANALYZED,
            ProceedingType.GST_SEC73_GENERAL,
            NoticeForm.DRC_01,
            NOW,
            response_deadline=date(2026, 10, 1),
        )
        snapshot = CaseSnapshot(case=case, documents=[], events=[])
        self.assertIs(snapshot.case, case)


class TimeContractTests(unittest.TestCase):
    def test_utc_now_is_timezone_aware_utc(self):
        value = utc_now()
        self.assertIsNotNone(value.tzinfo)
        self.assertEqual(value.utcoffset().total_seconds(), 0)


class PersistencePortTests(unittest.TestCase):
    def test_case_repository_is_protocol(self):
        self.assertTrue(issubclass(CaseRepository, Protocol))

    def test_analysis_snapshot_repository_is_protocol(self):
        self.assertTrue(
            issubclass(AnalysisSnapshotRepository, Protocol)
        )

    def test_analysis_snapshot_repository_methods_exact(self):
        methods = [
            name
            for name, member in inspect.getmembers(
                AnalysisSnapshotRepository,
                predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        ]
        self.assertEqual(
            methods,
            [
                "get_snapshot_ref",
                "list_snapshot_refs",
                "save_snapshot",
            ],
        )

    def test_evidence_review_repository_is_protocol(self):
        self.assertTrue(
            issubclass(EvidenceReviewRepository, Protocol)
        )

    def test_evidence_review_repository_methods_exact(self):
        methods = [
            name
            for name, member in inspect.getmembers(
                EvidenceReviewRepository,
                predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        ]
        self.assertEqual(
            methods,
            [
                "get_review_ref",
                "list_review_refs",
                "save_review",
            ],
        )

    def test_access_grant_repository_is_protocol(self):
        self.assertTrue(issubclass(AccessGrantRepository, Protocol))

    def test_access_grant_repository_methods_exact(self):
        methods = [
            name
            for name, member in inspect.getmembers(
                AccessGrantRepository, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        ]
        self.assertEqual(
            methods,
            [
                "get_grant",
                "list_grants_for_firm",
                "list_grants_for_user",
                "save_grant",
            ],
        )

    def test_document_store_is_protocol(self):
        self.assertTrue(issubclass(DocumentStore, Protocol))

    def test_repository_public_methods_exact(self):
        methods = [
            name
            for name, member in inspect.getmembers(
                CaseRepository, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        ]
        self.assertEqual(
            methods,
            [
                "add_document_ref",
                "add_document_with_event",
                "append_event",
                "create_case",
                "create_case_intake",
                "create_client",
                "create_existing_client_case_intake",
                "create_firm",
                "create_registration",
                "get_case",
                "get_client",
                "get_firm",
                "get_registration",
                "get_snapshot",
                "list_cases",
                "list_cases_for_client",
                "list_clients",
                "list_document_refs",
                "list_events",
                "list_registrations",
                "update_case",
                "update_case_with_events",
            ],
        )

    def test_document_store_methods_exact(self):
        methods = [
            name
            for name, member in inspect.getmembers(
                DocumentStore, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        ]
        self.assertEqual(methods, ["delete", "exists", "get", "put"])


if __name__ == "__main__":
    unittest.main()
