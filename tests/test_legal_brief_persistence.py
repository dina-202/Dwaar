"""Tests for encrypted snapshot-bound legal briefs."""

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.analysis_snapshot_models import AnalysisSnapshotRef
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
from domain.legal_brief_models import LEGAL_BRIEF_SCHEMA_VERSION
from domain.models import NoticeForm, ProceedingType
from modules.encrypted_document_store import EncryptedLocalDocumentStore
from modules.legal_brief_service import (
    LegalBriefIntegrityError,
    load_legal_brief,
    persist_legal_brief,
)
from modules.legal_brief_snapshot import (
    build_legal_brief_payload,
    decode_legal_brief_payload,
    encode_legal_brief_payload,
)
from modules.sqlite_analysis_snapshot_repository import (
    LocalSQLiteAnalysisSnapshotRepository,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository
from modules.sqlite_legal_brief_repository import (
    LocalSQLiteLegalBriefRepository,
)
from workflows.gst.legal_research import resolve_gst_legal_brief


NOW = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)
ACTOR = "OIDC-" + "a" * 64


class LegalBriefPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = str(root / "dwaar.db")
        self.object_root = root / "objects"

        self.cases = LocalSQLiteCaseRepository(self.db_path)
        self.cases.create_firm(Firm("F-1", "Firm", NOW))
        self.cases.create_client(Client("C-1", "F-1", "Client", NOW))
        self.cases.create_case(
            CaseRecord(
                case_id="CASE-1",
                firm_id="F-1",
                client_id="C-1",
                registration_id=None,
                title="Matter",
                status=CaseStatus.ANALYZED,
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                notice_form=NoticeForm.DRC_01,
                opened_at=NOW,
            )
        )
        self.notice = StoredDocumentRef(
            document_id="DOC-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.NOTICE,
            original_filename="notice.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256_hex="a" * 64,
            storage_key="objects/" + "b" * 32,
            created_at=NOW,
        )
        self.cases.add_document_ref(self.notice)

        self.snapshots = LocalSQLiteAnalysisSnapshotRepository(self.db_path)
        self.snapshot = AnalysisSnapshotRef(
            snapshot_id="SNAP-1",
            case_id="CASE-1",
            source_document_id="DOC-1",
            source_document_sha256="a" * 64,
            schema_version=1,
            engine_version="phase2-contract-2026.09.22.1",
            byte_size=1,
            sha256_hex=hashlib.sha256(b"x").hexdigest(),
            storage_key="objects/" + "c" * 32,
            created_at=NOW,
            created_by=ACTOR,
        )
        self.snapshots.save_snapshot(
            self.snapshot,
            CaseEvent(
                event_id="EV-SNAP",
                case_id="CASE-1",
                event_type=CaseEventType.ANALYSIS_SAVED,
                occurred_at=NOW,
                actor_id=ACTOR,
                payload={
                    "snapshot_id": "SNAP-1",
                    "schema_version": "1",
                },
            ),
        )

        self.briefs = LocalSQLiteLegalBriefRepository(self.db_path)
        self.store = EncryptedLocalDocumentStore(
            str(self.object_root),
            AESGCM.generate_key(bit_length=256),
            max_bytes=2 * 1024 * 1024,
        )
        self.result = resolve_gst_legal_brief(
            ProceedingType.GST_SEC73_ITC,
            date(2026, 8, 1),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_payload_round_trip_is_plain_data_and_deterministic(self):
        payload = build_legal_brief_payload(
            self.result,
            snapshot_id="SNAP-1",
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
        )
        self.assertEqual(payload["schema_version"], LEGAL_BRIEF_SCHEMA_VERSION)
        self.assertEqual(payload["snapshot_id"], "SNAP-1")
        self.assertEqual(payload["catalog_version"], self.result.catalog_version)
        first = encode_legal_brief_payload(payload)
        self.assertEqual(first, encode_legal_brief_payload(payload))
        self.assertEqual(decode_legal_brief_payload(first), payload)

    def test_save_load_round_trip_is_snapshot_and_catalog_bound(self):
        brief = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW,
        )
        self.assertTrue(self.store.exists(brief.storage_key))

        loaded = load_legal_brief(
            self.briefs,
            self.store,
            legal_brief_id=brief.legal_brief_id,
            expected_snapshot=self.snapshot,
        )
        self.assertEqual(loaded.metadata, brief)
        self.assertEqual(
            loaded.payload["catalog_version"],
            self.result.catalog_version,
        )
        self.assertEqual(loaded.payload["snapshot_id"], "SNAP-1")
        self.assertEqual(
            loaded.payload["unresolved_topics"],
            ["itc_eligibility"],
        )

    def test_ciphertext_does_not_contain_legal_proposition_plaintext(self):
        brief = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW,
        )
        proposition = self.result.matches[0].rule.proposition.encode("utf-8")
        object_id = brief.storage_key.split("/", 1)[1]
        ciphertext = (self.object_root / f"{object_id}.dwaar").read_bytes()
        self.assertNotIn(proposition, ciphertext)

    def test_event_contains_metadata_not_proposition_text(self):
        brief = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW,
        )
        events = self.cases.list_events("CASE-1")
        saved = [
            event for event in events
            if event.event_type is CaseEventType.LEGAL_BRIEF_SAVED
        ]
        self.assertEqual(len(saved), 1)
        event_text = repr(saved[0].payload)
        self.assertIn(brief.legal_brief_id, event_text)
        for match in self.result.matches:
            self.assertNotIn(match.rule.proposition, event_text)

    def test_wrong_expected_snapshot_fails_closed(self):
        brief = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW,
        )
        wrong = AnalysisSnapshotRef(
            **{**self.snapshot.__dict__, "snapshot_id": "SNAP-OTHER"}
        )
        with self.assertRaises(LegalBriefIntegrityError):
            load_legal_brief(
                self.briefs,
                self.store,
                legal_brief_id=brief.legal_brief_id,
                expected_snapshot=wrong,
            )

    def test_invalid_catalog_result_cannot_be_persisted(self):
        from dataclasses import replace

        invalid = replace(self.result, catalog_valid=False)
        with self.assertRaises(ValueError):
            persist_legal_brief(
                self.briefs,
                self.store,
                case_id="CASE-1",
                snapshot=self.snapshot,
                result=invalid,
                as_of_date=date(2026, 8, 1),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                actor_id=ACTOR,
                created_at=NOW,
            )
        self.assertEqual(self.briefs.list_brief_refs("SNAP-1"), [])

    def test_metadata_failure_rolls_back_encrypted_object(self):
        from dataclasses import replace

        missing_snapshot = replace(
            self.snapshot,
            snapshot_id="SNAP-MISSING",
        )
        with self.assertRaises(Exception):
            persist_legal_brief(
                self.briefs,
                self.store,
                case_id="CASE-1",
                snapshot=missing_snapshot,
                result=self.result,
                as_of_date=date(2026, 8, 1),
                proceeding_type=ProceedingType.GST_SEC73_ITC,
                actor_id=ACTOR,
                created_at=NOW,
            )
        self.assertEqual(
            list(self.object_root.glob("*.dwaar")),
            [],
        )
        self.assertEqual(
            self.briefs.list_brief_refs("SNAP-MISSING"),
            [],
        )

    def test_schema_v5_migrates_to_v6_with_legal_brief_table(self):
        legacy_path = str(Path(self.temp_dir.name) / "legacy-v5.db")
        LocalSQLiteCaseRepository(legacy_path)
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                UPDATE schema_meta SET value = '5'
                WHERE key = 'schema_version'
                """
            )
            connection.execute("DROP TABLE legal_briefs")
        LocalSQLiteCaseRepository(legacy_path)
        with sqlite3.connect(legacy_path) as connection:
            version = connection.execute(
                """
                SELECT value FROM schema_meta
                WHERE key = 'schema_version'
                """
            ).fetchone()[0]
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='legal_briefs'
                """
            ).fetchone()
        self.assertEqual(version, "6")
        self.assertEqual(table[0], "legal_briefs")

    def test_list_is_snapshot_scoped_and_stable(self):
        first = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW,
        )
        later = persist_legal_brief(
            self.briefs,
            self.store,
            case_id="CASE-1",
            snapshot=self.snapshot,
            result=self.result,
            as_of_date=date(2026, 8, 1),
            proceeding_type=ProceedingType.GST_SEC73_ITC,
            actor_id=ACTOR,
            created_at=NOW.replace(minute=1),
        )
        self.assertEqual(
            self.briefs.list_brief_refs("SNAP-1"),
            [first, later],
        )


if __name__ == "__main__":
    unittest.main()
