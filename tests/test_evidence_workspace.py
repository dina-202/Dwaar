"""Tests for temporary evidence workspace helpers."""

import unittest
from unittest import mock

from domain.models import (
    DocumentPageText,
    EvidenceDocument,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from modules import evidence_workspace


class NoticeAnalysisKeyTests(unittest.TestCase):
    def test_same_notice_bytes_produce_same_key(self):
        self.assertEqual(
            evidence_workspace.notice_analysis_key(b"notice"),
            evidence_workspace.notice_analysis_key(b"notice"),
        )

    def test_notice_byte_change_invalidates_key(self):
        self.assertNotEqual(
            evidence_workspace.notice_analysis_key(b"notice-a"),
            evidence_workspace.notice_analysis_key(b"notice-b"),
        )


class EvidenceWorkspaceKeyTests(unittest.TestCase):
    def test_same_inputs_produce_same_key(self):
        files = [("a.pdf", b"A"), ("b.pdf", b"B")]
        ids = ["e1", "e2"]
        first = evidence_workspace.evidence_workspace_key(
            b"notice", files, ids
        )
        second = evidence_workspace.evidence_workspace_key(
            b"notice", files, ids
        )
        self.assertEqual(first, second)

    def test_notice_change_invalidates_key(self):
        files = [("a.pdf", b"A")]
        ids = ["e1"]
        self.assertNotEqual(
            evidence_workspace.evidence_workspace_key(
                b"notice-1", files, ids
            ),
            evidence_workspace.evidence_workspace_key(
                b"notice-2", files, ids
            ),
        )

    def test_supporting_file_content_change_invalidates_key(self):
        ids = ["e1"]
        self.assertNotEqual(
            evidence_workspace.evidence_workspace_key(
                b"notice", [("a.pdf", b"A")], ids
            ),
            evidence_workspace.evidence_workspace_key(
                b"notice", [("a.pdf", b"B")], ids
            ),
        )

    def test_supporting_filename_change_invalidates_key(self):
        ids = ["e1"]
        self.assertNotEqual(
            evidence_workspace.evidence_workspace_key(
                b"notice", [("a.pdf", b"A")], ids
            ),
            evidence_workspace.evidence_workspace_key(
                b"notice", [("renamed.pdf", b"A")], ids
            ),
        )

    def test_supporting_file_order_change_invalidates_key(self):
        ids = ["e1"]
        self.assertNotEqual(
            evidence_workspace.evidence_workspace_key(
                b"notice",
                [("a.pdf", b"A"), ("b.pdf", b"B")],
                ids,
            ),
            evidence_workspace.evidence_workspace_key(
                b"notice",
                [("b.pdf", b"B"), ("a.pdf", b"A")],
                ids,
            ),
        )

    def test_checklist_change_invalidates_key(self):
        files = [("a.pdf", b"A")]
        self.assertNotEqual(
            evidence_workspace.evidence_workspace_key(
                b"notice", files, ["e1"]
            ),
            evidence_workspace.evidence_workspace_key(
                b"notice", files, ["e1", "e2"]
            ),
        )


class BuildEvidenceDocumentsTests(unittest.TestCase):
    def test_builds_stable_ordered_document_ids(self):
        pages_a = [
            DocumentPageText(
                page_number=1,
                text="A",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        pages_b = [
            DocumentPageText(
                page_number=1,
                text="B",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        with mock.patch.object(
            evidence_workspace,
            "extract_document_pages",
            side_effect=[pages_a, pages_b],
        ) as extractor:
            result = evidence_workspace.build_evidence_documents(
                [("a.pdf", b"A"), ("b.pdf", b"B")]
            )

        self.assertEqual(
            [document.document_id for document in result],
            ["D-001", "D-002"],
        )
        self.assertEqual(
            [document.filename for document in result],
            ["a.pdf", "b.pdf"],
        )
        self.assertEqual(result[0].pages, pages_a)
        self.assertEqual(result[1].pages, pages_b)
        self.assertEqual(
            extractor.call_args_list,
            [mock.call(b"A"), mock.call(b"B")],
        )

    def test_empty_filename_is_rejected(self):
        with self.assertRaises(ValueError):
            evidence_workspace.build_evidence_documents(
                [("", b"A")]
            )

    def test_empty_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            evidence_workspace.build_evidence_documents(
                [("a.pdf", b"")]
            )

    def test_returns_fresh_evidence_document_objects(self):
        pages = [
            DocumentPageText(
                page_number=1,
                text="A",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            )
        ]
        with mock.patch.object(
            evidence_workspace,
            "extract_document_pages",
            return_value=pages,
        ):
            first = evidence_workspace.build_evidence_documents(
                [("a.pdf", b"A")]
            )
            second = evidence_workspace.build_evidence_documents(
                [("a.pdf", b"A")]
            )
        self.assertIsInstance(first[0], EvidenceDocument)
        self.assertIsNot(first[0], second[0])


if __name__ == "__main__":
    unittest.main()
