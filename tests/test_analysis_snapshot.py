"""Tests for explicit, encrypted, versioned analysis snapshots."""

import hashlib
import inspect
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.analysis_snapshot_models import (
    ANALYSIS_ENGINE_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisSnapshotRef,
)
from domain.case_models import (
    CaseDocumentKind,
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
    Client,
    Firm,
    StoredDocumentRef,
)
from domain.models import (
    ArithmeticCalculationType,
    ArithmeticResult,
    ArithmeticStatus,
    AuthorityDetailsStatus,
    ClassificationConfidence,
    CommunicationIdentifierStatus,
    DeadlineConfidence,
    DeadlineConflictStatus,
    DeadlineResult,
    DeadlineStatus,
    DraftEligibility,
    DraftGenerationStatus,
    DraftPermission,
    DraftPostValidationResult,
    DraftSection,
    EvidenceChecklistItem,
    EvidenceStatus,
    ExtractedFact,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    Phase2AnalysisResult,
    PreflightResult,
    ProceedingType,
    RequirementResult,
    RequirementStatus,
    ReviewLevel,
    ReviewRequirement,
    SourceTextOrigin,
    SourceVerificationStatus,
    SpecialistDraftResult,
    SupportLevel,
    TriageSummary,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
)
from modules.analysis_snapshot import (
    build_snapshot_payload,
    decode_snapshot_payload,
    encode_snapshot_payload,
)
from modules.analysis_snapshot_service import (
    AnalysisSnapshotIntegrityError,
    AnalysisSnapshotPersistenceError,
    load_analysis_snapshot,
    persist_analysis_snapshot,
)
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 18, 30, tzinfo=timezone.utc)
SOURCE_QUOTE = "Exact taxpayer-sensitive source quote ₹1000"
RENDERED_DRAFT = "Rendered specialist draft with source-bound content."


def make_analysis():
    fact = ExtractedFact(
        fact_id="F-001",
        claim="Notice states ITC amount",
        status=FactStatus.CONFIRMED,
        source_text=SOURCE_QUOTE,
        source_page=2,
        allowed_in_draft=DraftPermission.YES,
        fact_type=FactType.STATED_AMOUNT,
        fact_role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        source_origin=SourceTextOrigin.EMBEDDED,
        source_verification=SourceVerificationStatus.VERIFIED,
    )
    calculation = ArithmeticResult(
        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        status=ArithmeticStatus.PASS,
        source_fact_ids=["F-001"],
        operand_values=[Decimal("1000.50"), Decimal("900.25")],
        result=Decimal("100.25"),
        formula="claimed - available",
        currency="INR",
        allowed_in_draft=DraftPermission.CONDITIONAL,
    )
    check = ValidationItem(
        check_id="check.one",
        status=ValidationStatus.WARNING,
        message="Review required",
        related_fact_ids=["F-001"],
        related_calculation_types=[
            ArithmeticCalculationType.ITC_DIFFERENCE
        ],
    )
    requirement = RequirementResult(
        requirement_id="requirement.one",
        requirement_text="Provide reconciliation",
        status=RequirementStatus.REQUIRES_VERIFICATION,
        related_fact_ids=["F-001"],
        calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
    )
    evidence = EvidenceChecklistItem(
        evidence_id="evidence.one",
        requirement_text="Purchase register",
        status=EvidenceStatus.UNKNOWN,
    )
    review = ReviewRequirement(
        review_id="review.one",
        level=ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        reason="Professional review required",
        mandatory=True,
    )
    return Phase2AnalysisResult(
        classification=NoticeClassification(
            notice_family=NoticeFamily.DEMAND_ADJUDICATION,
            notice_form=NoticeForm.DRC_01,
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            support_level=SupportLevel.DEEP_WORKFLOW,
            confidence=ClassificationConfidence.HIGH,
            classification_reasons=["DRC-01 marker", "Section 73 marker"],
        ),
        extraction_result=FactExtractionResult(
            facts=[fact],
            status=FactExtractionStatus.SUCCESS,
        ),
        deadline_result=DeadlineResult(
            notice_date=date(2026, 8, 1),
            service_date=date(2026, 8, 2),
            response_period_days=30,
            response_deadline=date(2026, 9, 1),
            deadline_confidence=DeadlineConfidence.CONFIRMED,
            deadline_status=DeadlineStatus.PASSED,
            days_remaining=-21,
            hearing_date=None,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            portal_verification_required=True,
            notes=["deadline fixture"],
        ),
        preflight_result=PreflightResult(
            fact_extraction_status=FactExtractionStatus.SUCCESS,
            communication_identifier_status=(
                CommunicationIdentifierStatus.RFN_PRESENT
            ),
            portal_verification_required=True,
            authority_details_status=AuthorityDetailsStatus.PARTIAL,
            authority_verification_required=True,
            stated_due_date_fact_ids=["F-DUE"],
            parsed_stated_due_dates=[date(2026, 9, 1)],
            unparsed_stated_due_date_fact_ids=[],
            deadline_conflict_status=DeadlineConflictStatus.MATCH,
            hearing_fact_ids=[],
            requested_document_fact_ids=["F-REQ"],
            referenced_annexure_fact_ids=["F-ANN"],
        ),
        arithmetic_results=[calculation],
        validation_result=ValidationEngineResult(
            overall_status=ValidationStatus.WARNING,
            draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
            case_severity=None,
            checks=[check],
            requirements=[requirement],
            evidence_checklist=[evidence],
            review_requirements=[review],
        ),
        draft_result=SpecialistDraftResult(
            status=DraftGenerationStatus.SUCCESS,
            draft_eligibility=DraftEligibility.REVIEW_REQUIRED,
            sections=[
                DraftSection(
                    section_id="S-001",
                    title="Facts and response",
                    rendered_text=RENDERED_DRAFT,
                )
            ],
            unresolved_requirements=[requirement],
            evidence_checklist=[evidence],
            review_requirements=[review],
            post_validation=DraftPostValidationResult(
                overall_status=ValidationStatus.PASS,
                checks=[check],
            ),
            failure_code=None,
            error_message=None,
        ),
        triage_summary=TriageSummary(
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            notice_form=NoticeForm.DRC_01,
            support_level=SupportLevel.DEEP_WORKFLOW,
            classification_confidence=ClassificationConfidence.HIGH,
            extraction_status=FactExtractionStatus.SUCCESS,
            portal_verification_required=True,
            authority_verification_required=True,
            communication_identifier_status=(
                CommunicationIdentifierStatus.RFN_PRESENT
            ),
            authority_details_status=AuthorityDetailsStatus.PARTIAL,
            deadline_status=DeadlineStatus.PASSED,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            requested_document_fact_ids=["F-REQ"],
            referenced_annexure_fact_ids=["F-ANN"],
            message="Structured triage summary.",
        ),
    )


def notice_ref(case_id="CASE-1"):
    return StoredDocumentRef(
        document_id="DOC-NOTICE",
        case_id=case_id,
        kind=CaseDocumentKind.NOTICE,
        original_filename="notice.pdf",
        media_type="application/pdf",
        byte_size=123,
        sha256_hex="a" * 64,
        storage_key="objects/" + "b" * 32,
        created_at=NOW,
    )


class SnapshotSerializerTests(unittest.TestCase):
    def test_exact_top_level_schema(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "engine_version",
                "source",
                "classification",
                "extraction",
                "deadline",
                "preflight",
                "arithmetic",
                "validation",
                "draft",
                "triage_summary",
            },
        )
        self.assertEqual(
            payload["schema_version"],
            SNAPSHOT_SCHEMA_VERSION,
        )
        self.assertEqual(
            payload["engine_version"],
            ANALYSIS_ENGINE_VERSION,
        )

    def test_sensitive_fact_and_rendered_draft_are_preserved_in_payload(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        self.assertEqual(
            payload["extraction"]["facts"][0]["source_text"],
            SOURCE_QUOTE,
        )
        self.assertEqual(
            payload["draft"]["sections"][0]["rendered_text"],
            RENDERED_DRAFT,
        )

    def test_decimal_and_date_values_use_stable_strings(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        self.assertEqual(
            payload["arithmetic"][0]["operand_values"],
            ["1000.50", "900.25"],
        )
        self.assertEqual(
            payload["arithmetic"][0]["result"],
            "100.25",
        )
        self.assertEqual(
            payload["deadline"]["response_deadline"],
            "2026-09-01",
        )

    def test_encoding_is_deterministic(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        self.assertEqual(
            encode_snapshot_payload(payload),
            encode_snapshot_payload(payload),
        )

    def test_decode_returns_plain_data_not_domain_objects(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        loaded = decode_snapshot_payload(
            encode_snapshot_payload(payload)
        )
        self.assertIsInstance(loaded, dict)
        self.assertIsInstance(loaded["classification"], dict)
        self.assertIsInstance(loaded["extraction"]["facts"][0], dict)
        self.assertNotIsInstance(loaded, Phase2AnalysisResult)

    def test_wrong_schema_or_engine_fails_closed(self):
        payload = build_snapshot_payload(
            make_analysis(),
            source_document_id="DOC-NOTICE",
            source_document_sha256="a" * 64,
        )
        for key, value in (
            ("schema_version", 999),
            ("engine_version", "future-engine"),
        ):
            modified = dict(payload)
            modified[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    encode_snapshot_payload(modified)

    def test_pickle_like_bytes_are_not_deserialized(self):
        with self.assertRaises(ValueError):
            decode_snapshot_payload(
                b"cos\\nsystem\\n(S'echo should-never-run'\\ntR."
            )

    def test_serializer_source_has_no_pickle_or_object_hook(self):
        import modules.analysis_snapshot as module

        tree_source = inspect.getsource(module)
        self.assertNotIn("import pickle", tree_source)
        self.assertNotIn("pickle.loads", tree_source)
        self.assertNotIn("object_hook=", tree_source)
        self.assertNotIn("yaml.load(", tree_source)


class SnapshotRepositoryAndEncryptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = str(root / "objects")
        self.case_repo = LocalSQLiteCaseRepository(self.db_path)
        self.case_repo.create_firm(Firm("F-1", "Firm", NOW))
        self.case_repo.create_client(
            Client("C-1", "F-1", "Client", NOW)
        )
        self.case_repo.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.INTAKE,
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        self.notice = notice_ref()
        self.case_repo.add_document_ref(self.notice)
        self.snapshot_repo = LocalSQLiteAnalysisSnapshotRepository(
            self.db_path
        )
        self.store = EncryptedLocalDocumentStore(
            self.object_root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=2 * 1024 * 1024,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_load_round_trip_encrypted_and_promotes_intake(self):
        snapshot = persist_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            case_id="CASE-1",
            source_document=self.notice,
            analysis=make_analysis(),
            actor_id="OIDC-" + "c" * 64,
            created_at=NOW,
        )
        self.assertEqual(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.ANALYZED,
        )
        self.assertTrue(self.store.exists(snapshot.storage_key))

        loaded = load_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            snapshot_id=snapshot.snapshot_id,
            expected_source_document=self.notice,
        )
        self.assertEqual(loaded.metadata, snapshot)
        self.assertEqual(
            loaded.payload["source"]["document_id"],
            self.notice.document_id,
        )
        self.assertEqual(
            loaded.payload["extraction"]["facts"][0]["source_text"],
            SOURCE_QUOTE,
        )

        object_id = snapshot.storage_key.split("/", 1)[1]
        ciphertext = (
            Path(self.object_root) / f"{object_id}.dwaar"
        ).read_bytes()
        self.assertNotIn(SOURCE_QUOTE.encode("utf-8"), ciphertext)
        self.assertNotIn(RENDERED_DRAFT.encode("utf-8"), ciphertext)

    def test_snapshot_event_contains_metadata_not_analysis_text(self):
        snapshot = persist_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            case_id="CASE-1",
            source_document=self.notice,
            analysis=make_analysis(),
            actor_id="OIDC-" + "d" * 64,
            created_at=NOW,
        )
        events = self.case_repo.list_events("CASE-1")
        saved = [
            event
            for event in events
            if event.event_type is CaseEventType.ANALYSIS_SAVED
        ]
        self.assertEqual(len(saved), 1)
        text = repr(saved[0].payload)
        self.assertIn(snapshot.snapshot_id, text)
        self.assertNotIn(SOURCE_QUOTE, text)
        self.assertNotIn(RENDERED_DRAFT, text)

    def test_source_document_hash_mismatch_rolls_back_ciphertext(self):
        wrong_notice = StoredDocumentRef(
            **{
                **self.notice.__dict__,
                "sha256_hex": "f" * 64,
            }
        )
        with self.assertRaises(AnalysisSnapshotPersistenceError):
            persist_analysis_snapshot(
                self.snapshot_repo,
                self.store,
                case_id="CASE-1",
                source_document=wrong_notice,
                analysis=make_analysis(),
                actor_id="OIDC-" + "e" * 64,
                created_at=NOW,
            )
        self.assertEqual(
            self.snapshot_repo.list_snapshot_refs("CASE-1"),
            [],
        )
        self.assertEqual(
            list(Path(self.object_root).glob("*.dwaar")),
            [],
        )
        self.assertEqual(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.INTAKE,
        )

    def test_later_case_status_is_never_demoted_to_analyzed(self):
        existing = self.case_repo.get_case("CASE-1")
        self.case_repo.update_case(
            CaseRecord(
                **{
                    **existing.__dict__,
                    "status": CaseStatus.DRAFT_REVIEW,
                }
            )
        )
        persist_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            case_id="CASE-1",
            source_document=self.notice,
            analysis=make_analysis(),
            actor_id="OIDC-" + "f" * 64,
            created_at=NOW,
        )
        self.assertIs(
            self.case_repo.get_case("CASE-1").status,
            CaseStatus.DRAFT_REVIEW,
        )

    def test_load_rejects_expected_source_hash_change(self):
        snapshot = persist_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            case_id="CASE-1",
            source_document=self.notice,
            analysis=make_analysis(),
            actor_id="OIDC-" + "1" * 64,
            created_at=NOW,
        )
        changed = StoredDocumentRef(
            **{
                **self.notice.__dict__,
                "sha256_hex": "e" * 64,
            }
        )
        with self.assertRaises(AnalysisSnapshotIntegrityError):
            load_analysis_snapshot(
                self.snapshot_repo,
                self.store,
                snapshot_id=snapshot.snapshot_id,
                expected_source_document=changed,
            )

    def test_load_rejects_metadata_byte_size_tamper(self):
        snapshot = persist_analysis_snapshot(
            self.snapshot_repo,
            self.store,
            case_id="CASE-1",
            source_document=self.notice,
            analysis=make_analysis(),
            actor_id="OIDC-" + "2" * 64,
            created_at=NOW,
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE analysis_snapshots
                SET byte_size = byte_size + 1
                WHERE snapshot_id = ?
                """,
                (snapshot.snapshot_id,),
            )
        with self.assertRaisesRegex(
            AnalysisSnapshotIntegrityError,
            "byte size",
        ):
            load_analysis_snapshot(
                self.snapshot_repo,
                self.store,
                snapshot_id=snapshot.snapshot_id,
                expected_source_document=self.notice,
            )

    def test_schema_v1_database_migrates_to_v5(self):
        other_path = str(Path(self.temp_dir.name) / "legacy.db")
        legacy = LocalSQLiteCaseRepository(other_path)
        with sqlite3.connect(other_path) as connection:
            connection.execute(
                """
                UPDATE schema_meta
                SET value = '1'
                WHERE key = 'schema_version'
                """
            )
            connection.execute("DROP TABLE analysis_snapshots")
        migrated = LocalSQLiteCaseRepository(other_path)
        self.assertIsNotNone(migrated)
        with sqlite3.connect(other_path) as connection:
            version = connection.execute(
                """
                SELECT value FROM schema_meta
                WHERE key = 'schema_version'
                """
            ).fetchone()[0]
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='analysis_snapshots'
                """
            ).fetchone()
        self.assertEqual(version, "5")
        self.assertEqual(table[0], "analysis_snapshots")
        with sqlite3.connect(other_path) as connection:
            review_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='evidence_reviews'
                """
            ).fetchone()
        self.assertEqual(review_table[0], "evidence_reviews")
        with sqlite3.connect(other_path) as connection:
            draft_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='draft_versions'
                """
            ).fetchone()
        self.assertEqual(draft_table[0], "draft_versions")
        with sqlite3.connect(other_path) as connection:
            filing_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='filing_records'
                """
            ).fetchone()
        self.assertEqual(filing_table[0], "filing_records")


if __name__ == "__main__":
    unittest.main()
