"""Adversarial tests for Phase 3A.1 page-aware document provenance."""

import inspect
import json
import unittest
from unittest import mock

from domain import fact_engine, phase2_orchestrator
from domain.models import (
    ClassificationConfidence,
    FactExtractionResult,
    FactExtractionStatus,
    NoticeClassification,
    NoticeFamily,
    NoticeForm,
    ProceedingType,
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


def candidate(source_text, source_page=None):
    return {
        "fact_type": "notice_reference",
        "fact_role": "none",
        "claim": "Notice reference",
        "source_text": source_text,
        "source_page": source_page,
    }


def response(*items):
    return json.dumps({"facts": list(items)})


class _FakePage:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text


class _FakeDocument:
    def __init__(self, texts):
        self.pages = [_FakePage(text) for text in texts]
        self.closed = False

    def __iter__(self):
        return iter(self.pages)

    def close(self):
        self.closed = True


class PdfPageExtractionTests(unittest.TestCase):
    def test_page_order_is_preserved(self):
        document = _FakeDocument(["page one\n", "page two\n", "page three"])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_page_texts(b"%PDF")
        self.assertEqual(pages, ["page one\n", "page two\n", "page three"])
        self.assertTrue(document.closed)

    def test_legacy_flattened_text_is_exact_join_of_pages(self):
        document = _FakeDocument(["A", "B\n", "C"])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            text = pdf_reader.extract_text(b"%PDF")
        self.assertEqual(text, "AB\nC")
        self.assertTrue(document.closed)

    def test_empty_embedded_text_is_preserved_per_page(self):
        document = _FakeDocument(["text", "", "more"])
        with mock.patch.object(pdf_reader.fitz, "open", return_value=document):
            pages = pdf_reader.extract_page_texts(b"%PDF")
        self.assertEqual(pages, ["text", "", "more"])

    def test_reader_error_is_wrapped_and_safe(self):
        with mock.patch.object(
            pdf_reader.fitz, "open", side_effect=ValueError("broken")
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not read this PDF"):
                pdf_reader.extract_page_texts(b"bad")


class FactPageProvenanceTests(unittest.TestCase):
    def run_page_extraction(self, pages, item):
        raw_text = "".join(pages)
        with mock.patch.object(
            fact_engine, "call_gemini", return_value=response(item)
        ) as llm:
            result = fact_engine.extract_facts_with_page_provenance(
                raw_text,
                classification(),
                pages,
            )
        return result, llm

    def test_unique_page_is_assigned_when_model_returns_null(self):
        pages = ["first page\n", "Reference No. ABC-123\nsecond page"]
        result, llm = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", None),
        )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        self.assertEqual(result.facts[0].source_page, 2)
        self.assertEqual(llm.call_count, 1)

    def test_correct_model_claimed_page_is_accepted(self):
        pages = ["first", "Reference No. ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", 2),
        )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        self.assertEqual(result.facts[0].source_page, 2)

    def test_wrong_model_claimed_page_is_rejected_not_repaired(self):
        pages = ["first page", "Reference No. ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", 1),
        )
        self.assertIs(result.status, FactExtractionStatus.PARTIAL)
        self.assertEqual(result.facts, [])
        self.assertEqual(result.rejected_item_count, 1)

    def test_out_of_range_model_page_is_rejected(self):
        pages = ["Reference No. ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", 99),
        )
        self.assertIs(result.status, FactExtractionStatus.PARTIAL)
        self.assertEqual(result.facts, [])

    def test_duplicate_quote_with_null_page_stays_unresolved(self):
        pages = ["Reference No. ABC-123", "Reference No. ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", None),
        )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        self.assertIsNone(result.facts[0].source_page)

    def test_duplicate_quote_accepts_specific_matching_page(self):
        pages = ["Reference No. ABC-123", "Reference No. ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", 2),
        )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        self.assertEqual(result.facts[0].source_page, 2)

    def test_quote_spanning_page_boundary_is_rejected(self):
        pages = ["Reference No. ", "ABC-123"]
        result, _ = self.run_page_extraction(
            pages,
            candidate("Reference No. ABC-123", None),
        )
        self.assertIs(result.status, FactExtractionStatus.PARTIAL)
        self.assertEqual(result.facts, [])

    def test_page_marker_text_cannot_satisfy_provenance(self):
        pages = ["actual notice text"]
        result, _ = self.run_page_extraction(
            pages,
            candidate('<PAGE number="1">', 1),
        )
        self.assertIs(result.status, FactExtractionStatus.PARTIAL)
        self.assertEqual(result.facts, [])

    def test_prompt_contains_machine_owned_page_markers(self):
        pages = ["first page", "Reference No. ABC-123"]
        with mock.patch.object(
            fact_engine,
            "call_gemini",
            return_value=response(),
        ) as llm:
            result = fact_engine.extract_facts_with_page_provenance(
                "".join(pages),
                classification(),
                pages,
            )
        self.assertIs(result.status, FactExtractionStatus.SUCCESS)
        prompt = llm.call_args.args[0]
        self.assertIn('<PAGE number="1">', prompt)
        self.assertIn('<PAGE number="2">', prompt)
        self.assertIn("Reference No. ABC-123", prompt)

    def test_raw_text_page_mismatch_fails_before_llm(self):
        with mock.patch.object(fact_engine, "call_gemini") as llm:
            result = fact_engine.extract_facts_with_page_provenance(
                "different raw text",
                classification(),
                ["page one"],
            )
        self.assertIs(result.status, FactExtractionStatus.FAILED)
        self.assertEqual(result.facts, [])
        llm.assert_not_called()

    def test_invalid_page_container_fails_before_llm(self):
        for pages in (None, (), ["ok", 3]):
            with self.subTest(pages=pages):
                with mock.patch.object(fact_engine, "call_gemini") as llm:
                    result = fact_engine.extract_facts_with_page_provenance(
                        "ok",
                        classification(),
                        pages,
                    )
                self.assertIs(result.status, FactExtractionStatus.FAILED)
                llm.assert_not_called()

    def test_legacy_public_signatures_are_unchanged(self):
        self.assertEqual(
            list(inspect.signature(fact_engine.extract_facts).parameters),
            ["raw_text", "classification"],
        )
        self.assertEqual(
            list(
                inspect.signature(
                    fact_engine.extract_facts_with_status
                ).parameters
            ),
            ["raw_text", "classification"],
        )


class PageAwareOrchestratorTests(unittest.TestCase):
    def test_page_path_classifies_legacy_join_and_uses_page_extractor(self):
        pages = ["PAGE-1\n", "PAGE-2"]
        raw_text = "".join(pages)
        fake_classification = classification()
        fake_extraction = FactExtractionResult(
            facts=[],
            status=FactExtractionStatus.SUCCESS,
        )
        sentinel = object()

        with (
            mock.patch.object(
                phase2_orchestrator,
                "classify_notice",
                return_value=fake_classification,
            ) as classifier,
            mock.patch.object(
                phase2_orchestrator,
                "extract_facts_with_page_provenance",
                return_value=fake_extraction,
            ) as extractor,
            mock.patch.object(
                phase2_orchestrator,
                "_assemble_phase2_result",
                return_value=sentinel,
            ) as assembler,
        ):
            result = phase2_orchestrator.run_phase2_analysis_from_pages(
                pages,
                mock.sentinel.today,
            )

        self.assertIs(result, sentinel)
        classifier.assert_called_once_with(raw_text)
        extractor.assert_called_once_with(
            raw_text,
            fake_classification,
            pages,
        )
        assembler.assert_called_once_with(
            fake_classification,
            fake_extraction,
            mock.sentinel.today,
        )

    def test_invalid_page_container_becomes_fail_closed_no_input_path(self):
        fake_classification = classification()
        fake_extraction = FactExtractionResult(
            facts=[],
            status=FactExtractionStatus.FAILED,
        )
        sentinel = object()

        with (
            mock.patch.object(
                phase2_orchestrator,
                "classify_notice",
                return_value=fake_classification,
            ) as classifier,
            mock.patch.object(
                phase2_orchestrator,
                "extract_facts_with_page_provenance",
                return_value=fake_extraction,
            ) as extractor,
            mock.patch.object(
                phase2_orchestrator,
                "_assemble_phase2_result",
                return_value=sentinel,
            ),
        ):
            result = phase2_orchestrator.run_phase2_analysis_from_pages(
                None,
                mock.sentinel.today,
            )

        self.assertIs(result, sentinel)
        classifier.assert_called_once_with("")
        extractor.assert_called_once_with(
            "",
            fake_classification,
            [],
        )


if __name__ == "__main__":
    unittest.main()
