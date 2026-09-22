"""Tests for persisted supporting-evidence workspace services."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from domain.auth_models import AuthenticatedPrincipal
from domain.case_models import CaseDocumentKind, StoredDocumentRef
from domain.models import (
    DocumentPageText,
    EvidenceChecklistItem,
    EvidenceDocument,
    EvidenceIntakeResult,
    EvidenceIntakeStatus,
    EvidenceStatus,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from modules import case_evidence_service


NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def ref(
    document_id="DOC-E-1",
    *,
    kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
    filename="gstr2b.pdf",
):
    return StoredDocumentRef(
        document_id=document_id,
        case_id="CASE-1",
        kind=kind,
        original_filename=filename,
        media_type="application/pdf",
        byte_size=10,
        sha256_hex="b" * 64,
        storage_key="objects/" + "c" * 32,
        created_at=NOW,
    )


def page(text="GSTR-2B April 2026"):
    return DocumentPageText(
        page_number=1,
        text=text,
        origin=SourceTextOrigin.EMBEDDED,
        verification=SourceVerificationStatus.VERIFIED,
    )


def checklist():
    return [
        EvidenceChecklistItem(
            evidence_id="evidence.e1",
            requirement_text="GSTR-2B for relevant period",
            status=EvidenceStatus.UNKNOWN,
        )
    ]


class SupportingEvidencePersistenceTests(unittest.TestCase):
    def test_add_one_pdf_uses_supporting_evidence_kind(self):
        service = mock.Mock()
        expected = ref()
        service.add_pdf_document.return_value = expected

        result = case_evidence_service.add_supporting_evidence_pdf(
            service,
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            filename="gstr2b.pdf",
            payload=b"%PDF fixture",
            created_at=NOW,
        )

        self.assertEqual(result, expected)
        service.add_pdf_document.assert_called_once_with(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            kind=CaseDocumentKind.SUPPORTING_EVIDENCE,
            original_filename="gstr2b.pdf",
            payload=b"%PDF fixture",
            created_at=NOW,
        )

    def test_naive_timestamp_fails_before_persistence(self):
        service = mock.Mock()
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            case_evidence_service.add_supporting_evidence_pdf(
                service,
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                filename="gstr2b.pdf",
                payload=b"%PDF fixture",
                created_at=datetime(2026, 9, 22, 18, 0),
            )
        service.add_pdf_document.assert_not_called()


class PersistedEvidenceLoadTests(unittest.TestCase):
    def test_only_supporting_evidence_documents_are_loaded(self):
        service = mock.Mock()
        evidence_ref = ref("DOC-E-1")
        notice_ref = ref(
            "DOC-N-1",
            kind=CaseDocumentKind.NOTICE,
            filename="notice.pdf",
        )
        service.list_documents.return_value = [notice_ref, evidence_ref]
        service.read_document.return_value = (
            evidence_ref,
            b"%PDF evidence",
        )

        with mock.patch.object(
            case_evidence_service,
            "extract_document_pages",
            return_value=[page()],
        ) as extractor:
            refs, documents = (
                case_evidence_service.load_supporting_evidence_documents(
                    service,
                    PRINCIPAL,
                    "F-1",
                    case_id="CASE-1",
                )
            )

        self.assertEqual(refs, [evidence_ref])
        self.assertEqual(
            documents,
            [
                EvidenceDocument(
                    document_id="DOC-E-1",
                    filename="gstr2b.pdf",
                    pages=[page()],
                )
            ],
        )
        service.read_document.assert_called_once_with(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            document_id="DOC-E-1",
        )
        extractor.assert_called_once_with(b"%PDF evidence")

    def test_persisted_document_id_becomes_evidence_document_id(self):
        service = mock.Mock()
        evidence_ref = ref("DOC-PERSISTED-ABC")
        service.list_documents.return_value = [evidence_ref]
        service.read_document.return_value = (
            evidence_ref,
            b"%PDF evidence",
        )
        with mock.patch.object(
            case_evidence_service,
            "extract_document_pages",
            return_value=[page()],
        ):
            _, documents = (
                case_evidence_service.load_supporting_evidence_documents(
                    service,
                    PRINCIPAL,
                    "F-1",
                    case_id="CASE-1",
                )
            )
        self.assertEqual(
            documents[0].document_id,
            "DOC-PERSISTED-ABC",
        )

    def test_metadata_change_during_read_fails_closed(self):
        service = mock.Mock()
        original = ref("DOC-E-1")
        changed = ref("DOC-E-1", filename="changed.pdf")
        service.list_documents.return_value = [original]
        service.read_document.return_value = (
            changed,
            b"%PDF evidence",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "metadata changed",
        ):
            case_evidence_service.load_supporting_evidence_documents(
                service,
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
            )

    def test_parse_failure_is_wrapped_without_parser_detail(self):
        service = mock.Mock()
        evidence_ref = ref()
        service.list_documents.return_value = [evidence_ref]
        service.read_document.return_value = (
            evidence_ref,
            b"%PDF evidence",
        )
        with mock.patch.object(
            case_evidence_service,
            "extract_document_pages",
            side_effect=RuntimeError("private OCR/parser detail"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "could not be parsed",
            ) as caught:
                case_evidence_service.load_supporting_evidence_documents(
                    service,
                    PRINCIPAL,
                    "F-1",
                    case_id="CASE-1",
                )
        self.assertNotIn("private OCR/parser detail", str(caught.exception))

    def test_no_supporting_documents_returns_empty_lists(self):
        service = mock.Mock()
        service.list_documents.return_value = [
            ref("DOC-N", kind=CaseDocumentKind.NOTICE)
        ]
        refs, documents = (
            case_evidence_service.load_supporting_evidence_documents(
                service,
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
            )
        )
        self.assertEqual(refs, [])
        self.assertEqual(documents, [])
        service.read_document.assert_not_called()


class PersistedEvidenceAnalysisTests(unittest.TestCase):
    def test_analysis_uses_only_persisted_evidence_documents(self):
        service = mock.Mock()
        evidence_ref = ref()
        evidence_doc = EvidenceDocument(
            document_id=evidence_ref.document_id,
            filename=evidence_ref.original_filename,
            pages=[page()],
        )
        expected = EvidenceIntakeResult(
            status=EvidenceIntakeStatus.SUCCESS,
            candidates=[],
        )

        with (
            mock.patch.object(
                case_evidence_service,
                "load_supporting_evidence_documents",
                return_value=([evidence_ref], [evidence_doc]),
            ) as loader,
            mock.patch.object(
                case_evidence_service,
                "propose_evidence_candidates",
                return_value=expected,
            ) as proposer,
        ):
            workspace = case_evidence_service.analyze_persisted_evidence(
                service,
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                evidence_checklist=checklist(),
            )

        loader.assert_called_once_with(
            service,
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
        )
        proposer.assert_called_once_with(
            checklist(),
            [evidence_doc],
        )
        self.assertEqual(workspace.document_refs, [evidence_ref])
        self.assertEqual(workspace.evidence_documents, [evidence_doc])
        self.assertIs(workspace.intake_result, expected)

    def test_no_persisted_documents_preserves_no_input_semantics(self):
        service = mock.Mock()
        with mock.patch.object(
            case_evidence_service,
            "load_supporting_evidence_documents",
            return_value=([], []),
        ):
            workspace = case_evidence_service.analyze_persisted_evidence(
                service,
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                evidence_checklist=checklist(),
            )
        self.assertIs(
            workspace.intake_result.status,
            EvidenceIntakeStatus.NO_INPUT,
        )


if __name__ == "__main__":
    unittest.main()
