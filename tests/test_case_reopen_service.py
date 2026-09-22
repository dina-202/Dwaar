"""Tests for authorized saved-case notice reopening and reanalysis."""

import unittest
from datetime import date, datetime, timezone
from unittest import mock

from domain.auth_models import AuthenticatedPrincipal
from domain.case_models import (
    CaseDocumentKind,
    CaseRecord,
    CaseStatus,
    StoredDocumentRef,
)
from domain.models import NoticeForm, ProceedingType
from modules import case_reopen_service


NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 22)


def case_record():
    return CaseRecord(
        case_id="CASE-1",
        firm_id="F-1",
        client_id="C-1",
        registration_id=None,
        title="Saved matter",
        status=CaseStatus.INTAKE,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
    )


def document(
    document_id="DOC-NOTICE",
    kind=CaseDocumentKind.NOTICE,
):
    return StoredDocumentRef(
        document_id=document_id,
        case_id="CASE-1",
        kind=kind,
        original_filename="notice.pdf",
        media_type="application/pdf",
        byte_size=10,
        sha256_hex="a" * 64,
        storage_key="objects/" + "b" * 32,
        created_at=NOW,
    )


class ReopenSavedCaseTests(unittest.TestCase):
    def setUp(self):
        self.principal = AuthenticatedPrincipal("OIDC-" + "c" * 64)
        self.service = mock.Mock()
        self.service.get_case.return_value = case_record()
        self.service.list_documents.return_value = [document()]
        self.service.read_document.return_value = (
            document(),
            b"%PDF saved notice",
        )

    def test_success_uses_authorized_case_and_document_services(self):
        pages = [mock.Mock(text="page one")]
        analysis = mock.sentinel.analysis
        with (
            mock.patch.object(
                case_reopen_service,
                "extract_document_pages",
                return_value=pages,
            ) as extractor,
            mock.patch.object(
                case_reopen_service,
                "run_phase2_analysis_from_document_pages",
                return_value=analysis,
            ) as runner,
        ):
            result = case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )

        self.assertEqual(result.case, case_record())
        self.assertEqual(result.notice_document, document())
        self.assertEqual(result.notice_pdf_bytes, b"%PDF saved notice")
        self.assertEqual(result.document_pages, pages)
        self.assertEqual(result.raw_text, "page one")
        self.assertIs(result.analysis, analysis)

        self.service.get_case.assert_called_once_with(
            self.principal,
            "F-1",
            "CASE-1",
        )
        self.service.list_documents.assert_called_once_with(
            self.principal,
            "F-1",
            case_id="CASE-1",
        )
        self.service.read_document.assert_called_once_with(
            self.principal,
            "F-1",
            case_id="CASE-1",
            document_id="DOC-NOTICE",
        )
        extractor.assert_called_once_with(b"%PDF saved notice")
        runner.assert_called_once_with(pages, TODAY)

    def test_missing_case_is_unavailable(self):
        self.service.get_case.return_value = None
        with self.assertRaisesRegex(LookupError, "case does not exist"):
            case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )
        self.service.list_documents.assert_not_called()
        self.service.read_document.assert_not_called()

    def test_zero_notice_documents_is_rejected(self):
        self.service.list_documents.return_value = [
            document("DOC-EVIDENCE", CaseDocumentKind.SUPPORTING_EVIDENCE)
        ]
        with self.assertRaisesRegex(
            case_reopen_service.SavedCaseReopenError,
            "exactly one notice",
        ):
            case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )
        self.service.read_document.assert_not_called()

    def test_multiple_notice_documents_is_rejected(self):
        self.service.list_documents.return_value = [
            document("DOC-1"),
            document("DOC-2"),
        ]
        with self.assertRaisesRegex(
            case_reopen_service.SavedCaseReopenError,
            "exactly one notice",
        ):
            case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )
        self.service.read_document.assert_not_called()

    def test_document_metadata_change_during_open_is_rejected(self):
        changed = document()
        changed = StoredDocumentRef(
            document_id=changed.document_id,
            case_id=changed.case_id,
            kind=changed.kind,
            original_filename="renamed.pdf",
            media_type=changed.media_type,
            byte_size=changed.byte_size,
            sha256_hex=changed.sha256_hex,
            storage_key=changed.storage_key,
            created_at=changed.created_at,
        )
        self.service.read_document.return_value = (
            changed,
            b"%PDF saved notice",
        )
        with self.assertRaisesRegex(
            case_reopen_service.SavedCaseReopenError,
            "metadata changed",
        ):
            case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )

    def test_pdf_parse_failure_is_wrapped(self):
        with mock.patch.object(
            case_reopen_service,
            "extract_document_pages",
            side_effect=RuntimeError("private parser detail"),
        ):
            with self.assertRaisesRegex(
                case_reopen_service.SavedCaseReopenError,
                "could not be parsed",
            ) as caught:
                case_reopen_service.reopen_case_analysis(
                    self.service,
                    self.principal,
                    "F-1",
                    "CASE-1",
                    TODAY,
                )
        self.assertNotIn("private parser detail", str(caught.exception))

    def test_authorization_error_from_case_service_propagates(self):
        self.service.get_case.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            case_reopen_service.reopen_case_analysis(
                self.service,
                self.principal,
                "F-1",
                "CASE-1",
                TODAY,
            )


if __name__ == "__main__":
    unittest.main()
