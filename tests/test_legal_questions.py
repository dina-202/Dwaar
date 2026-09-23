"""Tests for deterministic GST legal-question planning."""

import unittest

from domain.legal_date_engine import build_legal_date_context
from domain.legal_question_models import LegalQuestionStatus
from domain.models import (
    DraftPermission,
    ExtractedFact,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    SourceTextOrigin,
    SourceVerificationStatus,
)
from workflows.gst.legal_questions import (
    GST_LEGAL_QUESTION_PLANS,
    build_gst_legal_question_plan,
)


def fact(
    fact_id,
    fact_type,
    source_text,
    *,
    role=FactRole.NONE,
    status=FactStatus.CONFIRMED,
    verified=True,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim="fixture",
        status=status,
        source_text=source_text,
        source_page=1,
        allowed_in_draft=DraftPermission.CONDITIONAL,
        fact_type=fact_type,
        fact_role=role,
        source_origin=(
            SourceTextOrigin.EMBEDDED
            if verified
            else SourceTextOrigin.OCR
        ),
        source_verification=(
            SourceVerificationStatus.VERIFIED
            if verified
            else SourceVerificationStatus.REQUIRES_VERIFICATION
        ),
    )


def notice_date():
    return fact("F-N", FactType.NOTICE_DATE, "Notice dated 15/05/2024")


def tax_period():
    return fact("F-T", FactType.TAX_PERIOD, "FY 2023-24")


class LegalQuestionPlanTests(unittest.TestCase):
    def test_all_five_deep_workflows_have_closed_question_plans(self):
        self.assertEqual(
            set(GST_LEGAL_QUESTION_PLANS),
            {
                ProceedingType.GST_SEC73_GENERAL,
                ProceedingType.GST_SEC73_ITC,
                ProceedingType.GST_SEC73_RCM,
                ProceedingType.GST_SEC74_FRAUD,
                ProceedingType.GST_SEC129_ENFORCE,
            },
        )
        question_ids = [
            spec.question_id
            for specs in GST_LEGAL_QUESTION_PLANS.values()
            for spec in specs
        ]
        self.assertEqual(len(question_ids), len(set(question_ids)))

    def test_general_hearing_and_demand_questions_are_research_ready(self):
        facts = [notice_date()]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_GENERAL,
            facts,
            build_legal_date_context(facts),
        )
        self.assertEqual(
            [item.status for item in plan.questions],
            [
                LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
                LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
            ],
        )
        self.assertEqual(
            [item.matched_rule_ids for item in plan.questions],
            [
                ("cgst.s75.4.hearing.v1",),
                ("cgst.s75.7.demand_scope.v1",),
            ],
        )

    def test_missing_notice_date_is_distinct_from_uncurated_authority(self):
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_GENERAL,
            [],
            build_legal_date_context([]),
        )
        self.assertEqual(
            [item.status for item in plan.questions],
            [
                LegalQuestionStatus.MISSING_DATE,
                LegalQuestionStatus.MISSING_DATE,
            ],
        )

    def test_itc_question_requires_period_and_both_mismatch_amount_facts(self):
        facts = [
            notice_date(),
            tax_period(),
            fact(
                "F-3B",
                FactType.STATED_AMOUNT,
                "GSTR-3B ITC claimed ₹100000",
                role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_ITC,
            facts,
            build_legal_date_context(facts),
        )
        itc = plan.questions[-1]
        self.assertIs(itc.status, LegalQuestionStatus.MISSING_FACTS)
        self.assertEqual(itc.related_fact_ids, ("F-T", "F-3B"))
        self.assertEqual(len(itc.missing_fact_selectors), 1)
        self.assertIs(
            itc.missing_fact_selectors[0].fact_role,
            FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
        )

    def test_complete_itc_notice_facts_still_show_authority_uncurated(self):
        facts = [
            notice_date(),
            tax_period(),
            fact(
                "F-3B",
                FactType.STATED_AMOUNT,
                "GSTR-3B ITC claimed ₹100000",
                role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
            ),
            fact(
                "F-2B",
                FactType.STATED_AMOUNT,
                "GSTR-2B ITC reflected ₹90000",
                role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_ITC,
            facts,
            build_legal_date_context(facts),
        )
        itc = plan.questions[-1]
        self.assertIs(
            itc.status,
            LegalQuestionStatus.AUTHORITY_UNCURATED,
        )
        self.assertEqual(
            itc.related_fact_ids,
            ("F-T", "F-3B", "F-2B"),
        )
        self.assertEqual(itc.matched_rule_ids, ())

    def test_unverified_ocr_fact_does_not_satisfy_question(self):
        facts = [
            notice_date(),
            tax_period(),
            fact(
                "F-CAT",
                FactType.DEPARTMENT_ALLEGATION,
                "Department alleges legal services attract RCM",
                role=FactRole.RCM_CATEGORY_ALLEGED,
                status=FactStatus.ALLEGED,
                verified=False,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_RCM,
            facts,
            build_legal_date_context(facts),
        )
        rcm = plan.questions[-1]
        self.assertIs(rcm.status, LegalQuestionStatus.MISSING_FACTS)
        self.assertEqual(len(rcm.missing_fact_selectors), 1)

    def test_verified_section74_period_question_is_research_ready(self):
        facts = [
            notice_date(),
            tax_period(),
            fact(
                "F-FRAUD",
                FactType.DEPARTMENT_ALLEGATION,
                "Department alleges wilful misstatement",
                role=FactRole.FRAUD_BASIS_ALLEGED,
                status=FactStatus.ALLEGED,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC74_FRAUD,
            facts,
            build_legal_date_context(facts),
        )
        fraud = plan.questions[-1]
        self.assertIs(
            fraud.status,
            LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
        )
        self.assertEqual(
            fraud.matched_rule_ids,
            ("cgst.s74.fraud_scope.fy2017_2023.v1",),
        )

    def test_section74_fy2024_25_authority_remains_unresolved(self):
        facts = [
            notice_date(),
            fact("F-T", FactType.TAX_PERIOD, "FY 2024-25"),
            fact(
                "F-FRAUD",
                FactType.DEPARTMENT_ALLEGATION,
                "Department alleges suppression",
                role=FactRole.FRAUD_BASIS_ALLEGED,
                status=FactStatus.ALLEGED,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC74_FRAUD,
            facts,
            build_legal_date_context(facts),
        )
        self.assertIs(
            plan.questions[-1].status,
            LegalQuestionStatus.AUTHORITY_UNCURATED,
        )

    def test_post_2022_section129_questions_use_verified_detention_date(self):
        facts = [
            fact(
                "F-D",
                FactType.DOCUMENT_DETAIL,
                "Goods detained on 10/08/2026",
                role=FactRole.DETENTION_OR_SEIZURE_DATE,
            )
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC129_ENFORCE,
            facts,
            build_legal_date_context(facts),
        )
        self.assertEqual(
            [item.status for item in plan.questions],
            [
                LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
                LegalQuestionStatus.SOURCE_VERIFIED_RESEARCH_READY,
            ],
        )

    def test_duplicate_required_fact_is_ambiguous_and_fails_closed(self):
        facts = [
            notice_date(),
            tax_period(),
            fact(
                "F-C1",
                FactType.DEPARTMENT_ALLEGATION,
                "Department alleges legal services attract RCM",
                role=FactRole.RCM_CATEGORY_ALLEGED,
                status=FactStatus.ALLEGED,
            ),
            fact(
                "F-C2",
                FactType.DEPARTMENT_ALLEGATION,
                "Department alleges director services attract RCM",
                role=FactRole.RCM_CATEGORY_ALLEGED,
                status=FactStatus.ALLEGED,
            ),
        ]
        plan = build_gst_legal_question_plan(
            ProceedingType.GST_SEC73_RCM,
            facts,
            build_legal_date_context(facts),
        )
        rcm = plan.questions[-1]
        self.assertIs(rcm.status, LegalQuestionStatus.MISSING_FACTS)
        self.assertEqual(rcm.related_fact_ids, ("F-T",))


if __name__ == "__main__":
    unittest.main()
