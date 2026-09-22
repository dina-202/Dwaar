"""Contract tests for Phase 3C.1 persistent case/evidence models."""

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import inspect
import pathlib
import unittest

from domain.case_models import (
    AnalysisRunRecord,
    AnalysisRunStatus,
    CaseDocumentRecord,
    CaseEventRecord,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    ClientRecord,
    DocumentKind,
    DraftVersionRecord,
    EvidenceLinkRecord,
    EvidenceReviewStatus,
    FilingRecord,
    TaxRegistrationRecord,
)
from domain.models import NoticeForm, ProceedingType


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


EXPECTED_ENUMS = {
    CaseStatus: [
        ("INTAKE", "intake"),
        ("ANALYZING", "analyzing"),
        ("EVIDENCE_PENDING", "evidence_pending"),
        ("DRAFTING", "drafting"),
        ("REVIEW", "review"),
        ("READY_TO_FILE", "ready_to_file"),
        ("FILED", "filed"),
        ("POST_FILING", "post_filing"),
        ("CLOSED", "closed"),
    ],
    DocumentKind: [
        ("NOTICE", "notice"),
        ("NOTICE_ANNEXURE", "notice_annexure"),
        ("TAXPAYER_EVIDENCE", "taxpayer_evidence"),
        ("RECONCILIATION", "reconciliation"),
        ("DRAFT_REPLY", "draft_reply"),
        ("FINAL_REPLY", "final_reply"),
        ("FILING_ACKNOWLEDGEMENT", "filing_acknowledgement"),
        ("HEARING_DOCUMENT", "hearing_document"),
        ("ORDER", "order"),
        ("OTHER", "other"),
    ],
    EvidenceReviewStatus: [
        ("UNREVIEWED", "unreviewed"),
        ("VERIFIED", "verified"),
        ("REJECTED", "rejected"),
        ("CONFLICTING", "conflicting"),
    ],
    AnalysisRunStatus: [
        ("COMPLETED", "completed"),
        ("FAILED", "failed"),
    ],
    CaseEventType: [
        ("CASE_CREATED", "case_created"),
        ("DOCUMENT_ADDED", "document_added"),
        ("EVIDENCE_REQUESTED", "evidence_requested"),
        ("EVIDENCE_REVIEWED", "evidence_reviewed"),
        ("ANALYSIS_RUN", "analysis_run"),
        ("DRAFT_CREATED", "draft_created"),
        ("REVIEW_COMPLETED", "review_completed"),
        ("REPLY_FILED", "reply_filed"),
        ("ACKNOWLEDGEMENT_RECORDED", "acknowledgement_recorded"),
        ("HEARING_RECORDED", "hearing_recorded"),
        ("ORDER_RECORDED", "order_recorded"),
        ("STATUS_CHANGED", "status_changed"),
        ("NOTE_ADDED", "note_added"),
    ],
}


EXPECTED_FIELDS = {
    ClientRecord: [
        "tenant_id",
        "client_id",
        "display_name",
        "created_at",
        "legal_name",
        "pan",
    ],
    TaxRegistrationRecord: [
        "tenant_id",
        "registration_id",
        "client_id",
        "gstin",
        "created_at",
        "legal_name",
    ],
    CaseRecord: [
        "tenant_id",
        "case_id",
        "client_id",
        "title",
        "status",
        "created_at",
        "updated_at",
        "registration_id",
        "proceeding_type",
        "notice_form",
    ],
    CaseDocumentRecord: [
        "tenant_id",
        "document_id",
        "case_id",
        "kind",
        "original_filename",
        "content_type",
        "byte_size",
        "sha256",
        "storage_key",
        "uploaded_at",
    ],
    EvidenceLinkRecord: [
        "tenant_id",
        "evidence_link_id",
        "case_id",
        "document_id",
        "requirement_id",
        "review_status",
        "created_at",
        "reviewer_user_id",
        "reviewed_at",
        "review_note",
    ],
    AnalysisRunRecord: [
        "tenant_id",
        "analysis_run_id",
        "case_id",
        "notice_document_id",
        "engine_version",
        "status",
        "created_at",
    ],
    DraftVersionRecord: [
        "tenant_id",
        "draft_id",
        "case_id",
        "analysis_run_id",
        "version",
        "document_id",
        "created_at",
        "created_by_user_id",
    ],
    FilingRecord: [
        "tenant_id",
        "filing_id",
        "case_id",
        "final_reply_document_id",
        "filed_at",
        "portal_reference",
        "acknowledgement_document_id",
    ],
    CaseEventRecord: [
        "tenant_id",
        "event_id",
        "case_id",
        "event_type",
        "occurred_at",
        "actor_user_id",
        "related_document_id",
        "external_reference",
        "note",
    ],
}


class EnumContractTests(unittest.TestCase):
    def test_enums_are_closed_and_exact(self):
        for enum_type, expected in EXPECTED_ENUMS.items():
            with self.subTest(enum_type=enum_type.__name__):
                self.assertTrue(issubclass(enum_type, Enum))
                self.assertEqual(
                    [(member.name, member.value) for member in enum_type],
                    expected,
                )


class DataclassContractTests(unittest.TestCase):
    def test_records_are_frozen_dataclasses_with_exact_fields(self):
        for record_type, expected in EXPECTED_FIELDS.items():
            with self.subTest(record_type=record_type.__name__):
                self.assertTrue(is_dataclass(record_type))
                self.assertEqual(
                    [item.name for item in fields(record_type)],
                    expected,
                )
                self.assertTrue(
                    record_type.__dataclass_params__.frozen
                )

    def test_every_tenant_owned_record_starts_with_tenant_id(self):
        for record_type in EXPECTED_FIELDS:
            with self.subTest(record_type=record_type.__name__):
                self.assertEqual(
                    fields(record_type)[0].name,
                    "tenant_id",
                )

    def test_case_defaults_are_operational_not_legal(self):
        case = CaseRecord(
            tenant_id="tenant-1",
            case_id="case-1",
            client_id="client-1",
            title="DRC-01 matter",
            status=CaseStatus.INTAKE,
            created_at=NOW,
            updated_at=NOW,
        )
        self.assertIs(case.proceeding_type, ProceedingType.UNKNOWN)
        self.assertIs(case.notice_form, NoticeForm.UNKNOWN)

    def test_evidence_upload_does_not_default_to_verified(self):
        link = EvidenceLinkRecord(
            tenant_id="tenant-1",
            evidence_link_id="e-1",
            case_id="case-1",
            document_id="doc-1",
            requirement_id="gst_sec73_itc.r1",
            review_status=EvidenceReviewStatus.UNREVIEWED,
            created_at=NOW,
        )
        self.assertIs(
            link.review_status,
            EvidenceReviewStatus.UNREVIEWED,
        )
        self.assertIsNone(link.reviewer_user_id)
        self.assertIsNone(link.reviewed_at)

    def test_analysis_run_pins_engine_and_notice_document(self):
        run = AnalysisRunRecord(
            tenant_id="tenant-1",
            analysis_run_id="run-1",
            case_id="case-1",
            notice_document_id="doc-notice",
            engine_version="phase3c-test",
            status=AnalysisRunStatus.COMPLETED,
            created_at=NOW,
        )
        self.assertEqual(run.notice_document_id, "doc-notice")
        self.assertEqual(run.engine_version, "phase3c-test")

    def test_draft_version_pins_analysis_run(self):
        draft = DraftVersionRecord(
            tenant_id="tenant-1",
            draft_id="draft-1",
            case_id="case-1",
            analysis_run_id="run-1",
            version=1,
            document_id="doc-draft-1",
            created_at=NOW,
        )
        self.assertEqual(draft.analysis_run_id, "run-1")
        self.assertEqual(draft.version, 1)

    def test_filing_record_can_link_acknowledgement(self):
        filing = FilingRecord(
            tenant_id="tenant-1",
            filing_id="filing-1",
            case_id="case-1",
            final_reply_document_id="doc-final",
            filed_at=NOW,
            portal_reference="ARN-EXAMPLE",
            acknowledgement_document_id="doc-ack",
        )
        self.assertEqual(
            filing.acknowledgement_document_id,
            "doc-ack",
        )


class ConfidentialityBoundaryTests(unittest.TestCase):
    def test_document_record_has_no_raw_bytes_or_raw_text_field(self):
        names = set(EXPECTED_FIELDS[CaseDocumentRecord])
        for prohibited in (
            "bytes",
            "content",
            "raw_bytes",
            "raw_text",
            "document_bytes",
            "file_bytes",
        ):
            self.assertNotIn(prohibited, names)

    def test_document_record_keeps_hash_and_storage_reference(self):
        names = set(EXPECTED_FIELDS[CaseDocumentRecord])
        self.assertIn("sha256", names)
        self.assertIn("storage_key", names)

    def test_evidence_is_many_to_many_link_not_document_flag(self):
        evidence_fields = set(EXPECTED_FIELDS[EvidenceLinkRecord])
        document_fields = set(EXPECTED_FIELDS[CaseDocumentRecord])
        self.assertIn("requirement_id", evidence_fields)
        self.assertIn("document_id", evidence_fields)
        self.assertNotIn("requirement_id", document_fields)

    def test_tenant_id_is_not_described_as_authorization_proof(self):
        source = pathlib.Path(
            inspect.getsourcefile(ClientRecord)
        ).read_text(encoding="utf-8")
        self.assertIn(
            "tenant_id is data scope, never authorization proof",
            source,
        )


class ModulePurityTests(unittest.TestCase):
    def test_only_standard_library_and_domain_models_imported(self):
        source = pathlib.Path(
            inspect.getsourcefile(ClientRecord)
        ).read_text(encoding="utf-8")
        for forbidden in (
            "streamlit",
            "sqlalchemy",
            "psycopg",
            "sqlite3",
            "requests",
            "google",
            "boto",
            "supabase",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_no_filesystem_or_database_behavior(self):
        source = pathlib.Path(
            inspect.getsourcefile(ClientRecord)
        ).read_text(encoding="utf-8")
        for forbidden in (
            "open(",
            "execute(",
            "commit(",
            "rollback(",
            "session_state",
            "st.connection",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
