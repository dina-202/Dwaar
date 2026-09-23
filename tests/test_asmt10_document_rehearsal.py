"""Document-level ASMT-10 specialist-workflow rehearsal.

The fixture is synthetic and contains no real taxpayer/proceeding data.
Only the external model boundary is stubbed; PDF ingestion, classifier
validation, fact provenance, deterministic deadline/preflight/validation,
controlled drafting, and legal research all run through production code.
"""

import json
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import domain.drafting_engine as drafting_engine
import domain.fact_engine as fact_engine
import domain.proceeding_classifier as proceeding_classifier
from domain.legal_knowledge_models import LegalTopic
from domain.legal_question_models import LegalQuestionStatus
from domain.models import (
    DraftGenerationStatus,
    DraftEligibility,
    FactRole,
    NoticeForm,
    ProceedingType,
    RequirementStatus,
    SupportLevel,
)
from domain.phase2_orchestrator import run_phase2_analysis_from_document_pages
from modules.pdf_reader import extract_document_pages
from workflows.gst.legal_questions import build_gst_legal_question_plan
from workflows.gst.legal_research import (
    build_gst_legal_date_context,
    resolve_gst_legal_brief_from_context,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "sample_notices" / "NOTICE_5_ASMT10_Synthetic.pdf"
TODAY = date(2026, 9, 23)


CLASSIFIER_RESPONSE = json.dumps(
    {
        "notice_form": "ASMT_10",
        "notice_family": "ASSESSMENT_SCRUTINY",
        "proceeding_type": "GST_SEC61_SCRUTINY",
        "confidence": "HIGH",
        "classification_reasons": [
            "FORM GST ASMT-10 marker present",
            "Section 61 scrutiny marker present",
            "explicit discrepancy wording present",
        ],
    }
)


FACT_RESPONSE = json.dumps(
    {
        "facts": [
            {
                "fact_type": "notice_reference",
                "fact_role": "none",
                "claim": "Notice reference is TEST-ASMT10-0001",
                "source_text": "Reference No: TEST-ASMT10-0001",
                "source_page": 1,
            },
            {
                "fact_type": "gstin",
                "fact_role": "none",
                "claim": "GSTIN stated in notice",
                "source_text": "GSTIN: 06AAAAA0000A1Z5",
                "source_page": 1,
            },
            {
                "fact_type": "notice_date",
                "fact_role": "none",
                "claim": "Notice dated 01-09-2026",
                "source_text": "Date: 01-09-2026",
                "source_page": 1,
            },
            {
                "fact_type": "tax_period",
                "fact_role": "none",
                "claim": "FY 2025-26 is the stated period",
                "source_text": "FY 2025-26",
                "source_page": 1,
            },
            {
                "fact_type": "department_allegation",
                "fact_role": "none",
                "claim": (
                    "Department states that taxable turnover reported in "
                    "GSTR-3B differs from available records"
                ),
                "source_text": (
                    "Discrepancy 1: Department states that taxable turnover "
                    "reported in GSTR-3B differs from available records."
                ),
                "source_page": 1,
            },
            {
                "fact_type": "document_detail",
                "fact_role": "response_period",
                "claim": "Notice states an explanation period",
                "source_text": (
                    "Under Section 61, furnish an explanation within fifteen "
                    "days from the date of receipt of this notice."
                ),
                "source_page": 1,
            },
            {
                "fact_type": "requested_document",
                "fact_role": "none",
                "claim": "Purchase register requested",
                "source_text": "1. Purchase register for FY 2025-26",
                "source_page": 1,
            },
            {
                "fact_type": "requested_document",
                "fact_role": "none",
                "claim": "Sales register requested",
                "source_text": "2. Sales register for FY 2025-26",
                "source_page": 1,
            },
            {
                "fact_type": "requested_document",
                "fact_role": "none",
                "claim": "Electronic credit ledger requested",
                "source_text": (
                    "3. Electronic credit ledger for FY 2025-26"
                ),
                "source_page": 1,
            },
            {
                "fact_type": "referenced_annexure",
                "fact_role": "none",
                "claim": "Annexure A is referenced",
                "source_text": (
                    "Reference is made to Annexure A - discrepancy computation."
                ),
                "source_page": 1,
            },
        ]
    }
)


DRAFT_RESPONSE = json.dumps(
    {
        "sections": [
            {
                "section_id": "sec61_scrutiny.s1",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.working_draft",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.notice_material",
                    },
                ],
            },
            {
                "section_id": "sec61_scrutiny.s2",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.records_reconcile",
                    },
                    {
                        "kind": "fact",
                        "fact_id": "F-005",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.open_items",
                    },
                ],
            },
            {
                "section_id": "sec61_scrutiny.s3",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.conditional_response",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.ca_confirm",
                    },
                ],
            },
        ]
    }
)


DRAFT_RESPONSE_OMITS_DISCREPANCY = json.dumps(
    {
        "sections": [
            {
                "section_id": "sec61_scrutiny.s1",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.working_draft",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.notice_material",
                    },
                ],
            },
            {
                "section_id": "sec61_scrutiny.s2",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.records_reconcile",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.open_items",
                    },
                ],
            },
            {
                "section_id": "sec61_scrutiny.s3",
                "blocks": [
                    {
                        "kind": "static",
                        "template_id": "static.conditional_response",
                    },
                    {
                        "kind": "static",
                        "template_id": "static.ca_confirm",
                    },
                ],
            },
        ]
    }
)


class Asmt10DocumentRehearsalTests(unittest.TestCase):
    def test_synthetic_asmt10_runs_full_specialist_path(self):
        pages = extract_document_pages(
            FIXTURE.read_bytes(),
            ocr_empty_pages=False,
        )

        with (
            mock.patch.object(
                proceeding_classifier,
                "call_gemini",
                return_value=CLASSIFIER_RESPONSE,
            ) as classifier_call,
            mock.patch.object(
                fact_engine,
                "call_gemini",
                return_value=FACT_RESPONSE,
            ) as fact_call,
            mock.patch.object(
                drafting_engine,
                "call_gemini",
                return_value=DRAFT_RESPONSE,
            ) as draft_call,
        ):
            result = run_phase2_analysis_from_document_pages(pages, TODAY)

        classifier_call.assert_called_once()
        fact_call.assert_called_once()
        draft_call.assert_called_once()

        self.assertIs(result.classification.notice_form, NoticeForm.ASMT_10)
        self.assertIs(
            result.classification.proceeding_type,
            ProceedingType.GST_SEC61_SCRUTINY,
        )
        self.assertIs(
            result.classification.support_level,
            SupportLevel.DEEP_WORKFLOW,
        )
        self.assertIsNone(result.triage_summary)

        self.assertEqual(len(result.extraction_result.facts), 10)
        discrepancy = [
            fact
            for fact in result.extraction_result.facts
            if fact.fact_type.value == "department_allegation"
        ]
        self.assertEqual(len(discrepancy), 1)
        self.assertEqual(discrepancy[0].status.value, "alleged")

        response_period = [
            fact
            for fact in result.extraction_result.facts
            if fact.fact_role is FactRole.RESPONSE_PERIOD
        ]
        self.assertEqual(len(response_period), 1)
        self.assertEqual(result.deadline_result.response_period_days, 15)
        self.assertIsNone(result.deadline_result.response_deadline)
        self.assertEqual(result.deadline_result.deadline_status.value, "unknown")

        requested = result.preflight_result.requested_document_fact_ids
        self.assertEqual(requested, ["F-007", "F-008", "F-009"])
        self.assertEqual(
            result.preflight_result.referenced_annexure_fact_ids,
            ["F-010"],
        )

        self.assertEqual(
            [item.status for item in result.validation_result.requirements],
            [
                RequirementStatus.SATISFIED,
                RequirementStatus.SATISFIED,
                RequirementStatus.SATISFIED,
            ],
        )
        self.assertEqual(len(result.validation_result.evidence_checklist), 4)
        self.assertIs(
            result.validation_result.draft_eligibility,
            DraftEligibility.REVIEW_REQUIRED,
        )

        self.assertIs(
            result.draft_result.status,
            DraftGenerationStatus.SUCCESS,
        )
        self.assertEqual(
            [section.title for section in result.draft_result.sections],
            [
                "Scrutiny working paper",
                "Discrepancy-by-discrepancy response matrix",
                "Reviewable ASMT-11 explanation",
            ],
        )
        rendered_text = "\n".join(
            section.rendered_text for section in result.draft_result.sections
        )
        rendered = rendered_text.lower()
        self.assertIn(
            "Discrepancy 1: Department states that taxable turnover "
            "reported in GSTR-3B differs from available records.",
            rendered_text,
        )
        self.assertNotIn("drc-06", rendered)
        self.assertNotIn("15 days", rendered)
        self.assertNotIn("30 days", rendered)

        date_context = build_gst_legal_date_context(
            result.extraction_result.facts
        )
        legal = resolve_gst_legal_brief_from_context(
            ProceedingType.GST_SEC61_SCRUTINY,
            date_context,
        )
        self.assertEqual(legal.unresolved_topics, ())
        self.assertEqual(
            {match.rule.rule_key for match in legal.matches},
            {
                "cgst.s61.scrutiny_process",
                "cgst.r99.asmt_forms",
            },
        )
        legal_text = " ".join(
            match.rule.proposition for match in legal.matches
        ).lower()
        for forbidden in (
            "15 days",
            "fifteen days",
            "30 days",
            "thirty days",
        ):
            self.assertNotIn(forbidden, legal_text)

        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC61_SCRUTINY,
            result.extraction_result.facts,
            date_context,
        )
        self.assertEqual(len(plan.questions), 1)
        self.assertIs(
            plan.questions[0].status,
            LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
        )
        self.assertIs(plan.questions[0].topic, LegalTopic.SCRUTINY_PROCESS)


    def test_specialist_draft_fails_if_known_discrepancy_is_omitted(self):
        pages = extract_document_pages(
            FIXTURE.read_bytes(),
            ocr_empty_pages=False,
        )

        with (
            mock.patch.object(
                proceeding_classifier,
                "call_gemini",
                return_value=CLASSIFIER_RESPONSE,
            ),
            mock.patch.object(
                fact_engine,
                "call_gemini",
                return_value=FACT_RESPONSE,
            ),
            mock.patch.object(
                drafting_engine,
                "call_gemini",
                return_value=DRAFT_RESPONSE_OMITS_DISCREPANCY,
            ),
        ):
            result = run_phase2_analysis_from_document_pages(pages, TODAY)

        self.assertIs(
            result.draft_result.status,
            DraftGenerationStatus.FAILED,
        )
        self.assertEqual(result.draft_result.sections, [])
        checks = {
            item.check_id: item
            for item in result.draft_result.post_validation.checks
        }
        fact_check = checks["draft.blocks.fact_resolution"]
        self.assertEqual(fact_check.status.value, "fail")
        self.assertEqual(fact_check.related_fact_ids, ["F-005"])
        self.assertIn(
            "missing from the discrepancy-by-discrepancy response matrix",
            fact_check.message,
        )



if __name__ == "__main__":
    unittest.main()
