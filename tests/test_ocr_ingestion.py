"""Tests for Phase 3A.2 selective OCR and source-trust propagation."""

import json
import unittest
from unittest import mock

from domain import fact_engine
from domain.models import (
    ClassificationConfidence,
    DocumentPageText,
    FactExtractionStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
    SupportLevel,
)
from modules import pdf_reader


def classification():
    return NoticeClassification(
        notice_family=NoticeFamily.DEMAND_ADJUDICATION,
        notice_form=NoticeForm.DRC_01,
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        support_level=SupportLevel.DEEP_WORKFLOW,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=["test"],
    )


class _TextPage:
    pass


class _OcrCapablePage:
    def __init__(self, embedded_text, ocr_text=None, ocr_error=None):
        self.embedded_text = embedded_text
        self.ocr_text = ocr_text
        self.ocr_error = ocr_error
        self.ocr_calls = []
        self.textpage = _TextPage()

    def get_text(self, *args, **kwargs):
        if "textpage" in kwargs:
            return self.ocr_text
        return self.embedded_text

    def get_textpage_ocr(self, **kwargs):
        self.ocr_calls.append(kwargs)
        if self.ocr_error is not None:
            raise self.ocr_error
        return self.textpage


class _Document:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def __iter__(self):
        return iter(self.pages)

    def close(self):
        self.closed = True


class SelectiveOcrReaderTests(unittest.TestCase):
    def test_embedded_page_is_never_ocred(self):
        page = _OcrCapablePage("native text")
        document = _Document([page])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_document_pages(b"%PDF")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].text, "native text")
        self.assertIs(pages[0].origin, SourceTextOrigin.EMBEDDED)
        self.assertIs(
            pages[0].verification,
            SourceVerificationStatus.VERIFIED,
        )
        self.assertEqual(page.ocr_calls, [])
        self.assertTrue(document.closed)

    def test_blank_page_is_ocred_once_at_300_dpi(self):
        page = _OcrCapablePage("", "recognized notice text")
        document = _Document([page])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_document_pages(b"%PDF")
        self.assertEqual(len(page.ocr_calls), 1)
        self.assertEqual(
            page.ocr_calls[0],
            {"language": "eng", "dpi": 300, "full": True},
        )
        self.assertEqual(pages[0].text, "recognized notice text")
        self.assertIs(pages[0].origin, SourceTextOrigin.OCR)
        self.assertIs(
            pages[0].verification,
            SourceVerificationStatus.REQUIRES_VERIFICATION,
        )
        self.assertEqual(pages[0].ocr_language, "eng")
        self.assertEqual(pages[0].ocr_dpi, 300)

    def test_mixed_document_preserves_physical_page_order(self):
        first = _OcrCapablePage("native page one\n")
        second = _OcrCapablePage("   ", "OCR page two")
        third = _OcrCapablePage("native page three")
        document = _Document([first, second, third])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_document_pages(b"%PDF")
        self.assertEqual([p.page_number for p in pages], [1, 2, 3])
        self.assertEqual(
            [p.origin for p in pages],
            [
                SourceTextOrigin.EMBEDDED,
                SourceTextOrigin.OCR,
                SourceTextOrigin.EMBEDDED,
            ],
        )
        self.assertEqual(
            "".join(p.text for p in pages),
            "native page one\nOCR page twonative page three",
        )

    def test_ocr_can_be_disabled_without_guessing_text(self):
        page = _OcrCapablePage("")
        document = _Document([page])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_document_pages(
                b"%PDF",
                ocr_empty_pages=False,
            )
        self.assertEqual(page.ocr_calls, [])
        self.assertEqual(pages[0].text, "")
        self.assertIs(pages[0].origin, SourceTextOrigin.UNKNOWN)
        self.assertIs(
            pages[0].verification,
            SourceVerificationStatus.REQUIRES_VERIFICATION,
        )

    def test_ocr_unavailable_raises_controlled_error(self):
        page = _OcrCapablePage(
            "",
            ocr_error=RuntimeError("private tesseract path"),
        )
        document = _Document([page])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            with self.assertRaises(RuntimeError) as caught:
                pdf_reader.extract_document_pages(b"%PDF")
        message = str(caught.exception)
        self.assertIn("OCR is required for scanned page 1", message)
        self.assertIn("Tesseract OCR", message)
        self.assertNotIn("private tesseract path", message)
        self.assertTrue(document.closed)

    def test_explicit_language_and_dpi_are_preserved(self):
        page = _OcrCapablePage("", "पहचान")
        document = _Document([page])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_document_pages(
                b"%PDF",
                ocr_language="eng+hin",
                ocr_dpi=350,
            )
        self.assertEqual(
            page.ocr_calls[0],
            {"language": "eng+hin", "dpi": 350, "full": True},
        )
        self.assertEqual(pages[0].ocr_language, "eng+hin")
        self.assertEqual(pages[0].ocr_dpi, 350)


class OcrFactTrustTests(unittest.TestCase):
    def _response(self, source_text, page=1):
        return json.dumps(
            {
                "facts": [
                    {
                        "fact_type": "notice_date",
                        "fact_role": "none",
                        "claim": "Notice date stated",
                        "source_text": source_text,
                        "source_page": page,
                    }
                ]
            }
        )

    def test_embedded_fact_is_verified(self):
        pages = [
            DocumentPageText(
                page_number=1,
                text="Date: 17-08-2026",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        with mock.patch.object(
            fact_engine,
            "call_gemini",
            return_value=self._response("Date: 17-08-2026"),
        ):
            result = fact_engine.extract_facts_with_document_provenance(
                "Date: 17-08-2026",
                classification(),
                pages,
            )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        fact = result.facts[0]
        self.assertIs(fact.source_origin, SourceTextOrigin.EMBEDDED)
        self.assertIs(
            fact.source_verification,
            SourceVerificationStatus.VERIFIED,
        )

    def test_ocr_fact_preserves_fact_status_but_requires_source_review(self):
        pages = [
            DocumentPageText(
                page_number=1,
                text="Date: 17-08-2026",
                origin=SourceTextOrigin.OCR,
                verification=SourceVerificationStatus.REQUIRES_VERIFICATION,
                ocr_language="eng",
                ocr_dpi=300,
            )
        ]
        with mock.patch.object(
            fact_engine,
            "call_gemini",
            return_value=self._response("Date: 17-08-2026"),
        ):
            result = fact_engine.extract_facts_with_document_provenance(
                "Date: 17-08-2026",
                classification(),
                pages,
            )
        fact = result.facts[0]
        self.assertEqual(fact.status.value, "confirmed")
        self.assertIs(fact.source_origin, SourceTextOrigin.OCR)
        self.assertIs(
            fact.source_verification,
            SourceVerificationStatus.REQUIRES_VERIFICATION,
        )

    def test_mixed_duplicate_source_is_not_falsely_verified(self):
        pages = [
            DocumentPageText(
                page_number=1,
                text="Date: 17-08-2026",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            ),
            DocumentPageText(
                page_number=2,
                text="Date: 17-08-2026",
                origin=SourceTextOrigin.OCR,
                verification=SourceVerificationStatus.REQUIRES_VERIFICATION,
                ocr_language="eng",
                ocr_dpi=300,
            ),
        ]
        response = json.dumps(
            {
                "facts": [
                    {
                        "fact_type": "notice_date",
                        "fact_role": "none",
                        "claim": "Notice date stated",
                        "source_text": "Date: 17-08-2026",
                        "source_page": None,
                    }
                ]
            }
        )
        with mock.patch.object(
            fact_engine,
            "call_gemini",
            return_value=response,
        ):
            result = fact_engine.extract_facts_with_document_provenance(
                "Date: 17-08-2026Date: 17-08-2026",
                classification(),
                pages,
            )
        fact = result.facts[0]
        self.assertIsNone(fact.source_page)
        self.assertIs(fact.source_origin, SourceTextOrigin.MIXED)
        self.assertIs(
            fact.source_verification,
            SourceVerificationStatus.REQUIRES_VERIFICATION,
        )


if __name__ == "__main__":
    unittest.main()
