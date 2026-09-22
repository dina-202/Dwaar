"""Offline tests for the UI-independent Phase-2 orchestrator (§24)."""

import copy
from dataclasses import MISSING, fields
from datetime import date
import inspect
import pathlib
import re
import unittest
from unittest.mock import Mock, patch
from typing import List, Optional

from domain import phase2_orchestrator as orchestrator
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
    DraftFailureCode,
    DraftGenerationStatus,
    DocumentPageText,
    DraftPermission,
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
    RequirementKind,
    SourceTextOrigin,
    SourceVerificationStatus,
    SpecialistDraftResult,
    SupportLevel,
    TriageSummary,
    ValidationEngineResult,
    ValidationStatus,
    WorkflowRequirementSpec,
    WorkflowValidationProfile,
)


MODULE_PATH = pathlib.Path(orchestrator.__file__)


def make_classification(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    support_level=SupportLevel.DEEP_WORKFLOW,
    notice_form=NoticeForm.DRC_01,
    confidence=ClassificationConfidence.HIGH,
):
    return NoticeClassification(
        notice_family=NoticeFamily.DEMAND_ADJUDICATION,
        notice_form=notice_form,
        proceeding_type=proceeding_type,
        support_level=support_level,
        confidence=confidence,
        classification_reasons=["fixture"],
    )


def make_fact(
    fact_id,
    fact_type,
    source_text,
    *,
    role=FactRole.NONE,
    status=FactStatus.CONFIRMED,
    claim="CLAIM MUST NOT BE USED",
):
    return ExtractedFact(
        fact_id=fact_id,
        claim=claim,
        status=status,
        source_text=source_text,
        fact_type=fact_type,
        fact_role=role,
    )


def make_extraction(facts=None, status=FactExtractionStatus.SUCCESS):
    return FactExtractionResult(facts=list(facts or []), status=status)


def make_deadline():
    return DeadlineResult(
        notice_date=None,
        service_date=None,
        response_period_days=None,
        response_deadline=None,
        deadline_confidence=DeadlineConfidence.UNKNOWN,
        deadline_status=DeadlineStatus.UNKNOWN,
        days_remaining=None,
        hearing_date=None,
        hearing_status=HearingStatus.NOT_SCHEDULED,
        portal_verification_required=True,
        notes=[],
    )


def make_preflight(extraction_status=FactExtractionStatus.SUCCESS):
    return PreflightResult(
        fact_extraction_status=extraction_status,
        communication_identifier_status=(
            CommunicationIdentifierStatus.NEITHER_FOUND
        ),
        portal_verification_required=True,
        authority_details_status=AuthorityDetailsStatus.MISSING,
        authority_verification_required=True,
        stated_due_date_fact_ids=[],
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
        hearing_fact_ids=[],
        requested_document_fact_ids=["F-REQ"],
        referenced_annexure_fact_ids=["F-ANN"],
    )


def make_validation():
    return ValidationEngineResult(
        overall_status=ValidationStatus.WARNING,
        draft_eligibility=DraftEligibility.BLOCKED,
        case_severity=None,
        checks=[],
        requirements=[],
        evidence_checklist=[],
        review_requirements=[],
    )


def make_draft():
    return SpecialistDraftResult(
        status=DraftGenerationStatus.BLOCKED,
        draft_eligibility=DraftEligibility.BLOCKED,
        sections=[],
        unresolved_requirements=[],
        evidence_checklist=[],
        review_requirements=[],
        post_validation=None,
        failure_code=DraftFailureCode.DRAFT_BLOCKED,
        error_message="blocked",
    )


def make_requirement(kind, calculation_type=None, suffix="1"):
    return WorkflowRequirementSpec(
        requirement_id=f"r{suffix}",
        requirement_text=f"requirement {suffix}",
        kind=kind,
        calculation_type=calculation_type,
    )


def make_profile(requirements):
    return WorkflowValidationProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        requirement_specs=list(requirements),
        special_rule_handling={},
        review_rules={},
    )


def make_itc_facts():
    return [
        make_fact(
            "F-L",
            FactType.STATED_AMOUNT,
            "GSTR-3B ITC: Rs. 10,00,000.50",
            role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        ),
        make_fact(
            "F-R",
            FactType.STATED_AMOUNT,
            "GSTR-2B ITC: INR 8,50,000.25",
            role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
        ),
    ]


class ModelContractTests(unittest.TestCase):
    def test_triage_summary_exact_fields_order_and_no_defaults(self):
        expected = [
            "proceeding_type",
            "notice_form",
            "support_level",
            "classification_confidence",
            "extraction_status",
            "portal_verification_required",
            "authority_verification_required",
            "communication_identifier_status",
            "authority_details_status",
            "deadline_status",
            "hearing_status",
            "requested_document_fact_ids",
            "referenced_annexure_fact_ids",
            "message",
        ]
        actual = fields(TriageSummary)
        self.assertEqual([field.name for field in actual], expected)
        self.assertEqual(len(actual), 14)
        for field in actual:
            self.assertIs(field.default, MISSING)
            self.assertIs(field.default_factory, MISSING)

    def test_phase2_result_exact_fields_order_and_no_defaults(self):
        expected = [
            "classification",
            "extraction_result",
            "deadline_result",
            "preflight_result",
            "arithmetic_results",
            "validation_result",
            "draft_result",
            "triage_summary",
        ]
        actual = fields(Phase2AnalysisResult)
        self.assertEqual([field.name for field in actual], expected)
        self.assertEqual(len(actual), 8)
        for field in actual:
            self.assertIs(field.default, MISSING)
            self.assertIs(field.default_factory, MISSING)

    def test_phase2_result_exact_annotations_and_only_triage_optional(self):
        annotations = Phase2AnalysisResult.__annotations__
        self.assertIs(annotations["classification"], NoticeClassification)
        self.assertIs(annotations["extraction_result"], FactExtractionResult)
        self.assertIs(annotations["deadline_result"], DeadlineResult)
        self.assertIs(annotations["preflight_result"], PreflightResult)
        self.assertEqual(annotations["arithmetic_results"], List[ArithmeticResult])
        self.assertIs(annotations["validation_result"], ValidationEngineResult)
        self.assertIs(annotations["draft_result"], SpecialistDraftResult)
        self.assertEqual(annotations["triage_summary"], Optional[TriageSummary])

    def test_result_has_no_prohibited_payload_fields(self):
        names = {field.name for field in fields(Phase2AnalysisResult)}
        for prohibited in (
            "raw_text", "pdf", "pdf_bytes", "error", "error_dict",
            "prompt", "provider_response",
        ):
            self.assertNotIn(prohibited, names)

    def test_existing_model_enum_counts_unchanged(self):
        self.assertEqual(len(DraftGenerationStatus), 3)
        self.assertEqual(len(DraftFailureCode), 6)
        self.assertEqual(len(FactRole), 22)


class PublicApiAndPurityTests(unittest.TestCase):
    def test_exact_public_function_surface(self):
        public_functions = [
            name for name, value in vars(orchestrator).items()
            if not name.startswith("_")
            and inspect.isfunction(value)
            and value.__module__ == orchestrator.__name__
        ]
        self.assertEqual(
            public_functions,
            [
                "run_phase2_analysis",
                "run_phase2_analysis_from_pages",
                "run_phase2_analysis_from_document_pages",
            ],
        )

    def test_exact_signature_and_required_today(self):
        signature = inspect.signature(orchestrator.run_phase2_analysis)
        self.assertEqual(list(signature.parameters), ["raw_text", "today"])
        self.assertIs(signature.parameters["raw_text"].annotation, str)
        self.assertIs(signature.parameters["today"].annotation, date)
        self.assertIs(signature.parameters["today"].default, inspect.Parameter.empty)
        self.assertIs(signature.return_annotation, Phase2AnalysisResult)

    def test_page_aware_signature_is_additive_and_exact(self):
        signature = inspect.signature(orchestrator.run_phase2_analysis_from_pages)
        self.assertEqual(list(signature.parameters), ["page_texts", "today"])
        self.assertEqual(str(signature.parameters["page_texts"].annotation), "typing.List[str]")
        self.assertIs(signature.parameters["today"].annotation, date)
        self.assertIs(signature.return_annotation, Phase2AnalysisResult)

    def test_document_page_signature_is_additive_and_exact(self):
        signature = inspect.signature(
            orchestrator.run_phase2_analysis_from_document_pages
        )
        self.assertEqual(
            list(signature.parameters),
            ["document_pages", "today"],
        )
        self.assertIs(signature.parameters["today"].annotation, date)
        self.assertIs(signature.return_annotation, Phase2AnalysisResult)

    def test_no_extra_api_parameters(self):
        names = set(inspect.signature(orchestrator.run_phase2_analysis).parameters)
        for prohibited in (
            "pdf_bytes", "workflow", "workflow_override", "prompt",
            "prompt_override", "context", "session_state",
        ):
            self.assertNotIn(prohibited, names)

    def test_downstream_private_helpers_do_not_accept_raw_text(self):
        for name, value in vars(orchestrator).items():
            if (
                name.startswith("_")
                and inspect.isfunction(value)
                and value.__module__ == orchestrator.__name__
            ):
                self.assertNotIn("raw_text", inspect.signature(value).parameters, name)

    def test_source_has_no_clock_access(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("date.today()", source)
        self.assertNotIn("datetime.now()", source)
        self.assertNotIn("time.time()", source)

    def test_source_has_no_legacy_pdf_ui_or_provider_dependency(self):
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        for prohibited in (
            "notice_explainer", "explain_notice", "build_notice_prompt",
            "notice_prompt.txt", "pdf_reader", "streamlit", "session_state",
            "call_gemini", "modules.llm_client", "gemini",
        ):
            self.assertNotIn(prohibited, source)

    def test_exact_amount_regex_and_search_contract(self):
        expected = (
            r"(?<![A-Za-z0-9])(-?)(?:₹|rs\.?|inr)?\s*"
            r"(?:\d{1,2}(?:,\d{2})*(?:,\d{3})(?:\.\d{1,2})?"
            r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
            r"|\d+(?:\.\d{1,2})?)(?![A-Za-z0-9])"
        )
        self.assertEqual(orchestrator._AMOUNT_TOKEN_REGEX, expected)
        self.assertEqual(orchestrator._AMOUNT_TOKEN_PATTERN.flags, re.IGNORECASE | re.UNICODE)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("_re.finditer", source)
        self.assertIn("group(0)", source)


class PipelineTests(unittest.TestCase):
    def _run_pipeline(self, classification=None, extraction=None):
        classification = classification or make_classification()
        extraction = extraction or make_extraction()
        deadline = make_deadline()
        preflight = make_preflight(extraction.status)
        arithmetic = []
        validation = make_validation()
        draft = make_draft()
        order = []

        classifier = Mock(side_effect=lambda value: (
            order.append("classification"), classification
        )[1])
        fact_engine = Mock(side_effect=lambda text, classified: (
            order.append("extraction"), extraction
        )[1])
        deadline_engine = Mock(side_effect=lambda **kwargs: (
            order.append("deadline"), deadline
        )[1])
        preflight_engine = Mock(side_effect=lambda *args: (
            order.append("preflight"), preflight
        )[1])
        arithmetic_builder = Mock(side_effect=lambda *args: (
            order.append("arithmetic"), arithmetic
        )[1])
        validation_engine = Mock(side_effect=lambda *args: (
            order.append("validation"), validation
        )[1])
        drafting_engine = Mock(side_effect=lambda *args: (
            order.append("drafting"), draft
        )[1])

        patches = (
            patch.object(orchestrator, "classify_notice", classifier),
            patch.object(orchestrator, "extract_facts_with_status", fact_engine),
            patch.object(orchestrator, "calculate_deadline", deadline_engine),
            patch.object(orchestrator, "run_preflight", preflight_engine),
            patch.object(orchestrator, "_build_arithmetic_results", arithmetic_builder),
            patch.object(orchestrator, "run_validation", validation_engine),
            patch.object(orchestrator, "generate_specialist_draft", drafting_engine),
        )
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

        supplied_today = date(2026, 8, 30)
        result = orchestrator.run_phase2_analysis("RAW SENTINEL", supplied_today)
        mocks = {
            "classifier": classifier,
            "fact_engine": fact_engine,
            "deadline": deadline_engine,
            "preflight": preflight_engine,
            "arithmetic": arithmetic_builder,
            "validation": validation_engine,
            "drafting": drafting_engine,
        }
        objects = {
            "classification": classification,
            "extraction": extraction,
            "deadline": deadline,
            "preflight": preflight,
            "arithmetic": arithmetic,
            "validation": validation,
            "draft": draft,
            "today": supplied_today,
        }
        return result, mocks, objects, order

    def test_exact_pipeline_order(self):
        _, _, _, order = self._run_pipeline()
        self.assertEqual(
            order,
            ["classification", "extraction", "deadline", "preflight",
             "arithmetic", "validation", "drafting"],
        )

    def test_classifier_and_fact_engine_receive_raw_text_exactly_once(self):
        _, mocks, objects, _ = self._run_pipeline()
        mocks["classifier"].assert_called_once_with("RAW SENTINEL")
        mocks["fact_engine"].assert_called_once_with(
            "RAW SENTINEL", objects["classification"]
        )

    def test_raw_text_never_reaches_downstream_calls(self):
        _, mocks, _, _ = self._run_pipeline()
        for name in ("deadline", "preflight", "arithmetic", "validation", "drafting"):
            call = mocks[name].call_args
            self.assertNotIn("RAW SENTINEL", call.args, name)
            self.assertNotIn("RAW SENTINEL", call.kwargs.values(), name)

    def test_deadline_exact_keywords_and_today_identity(self):
        extraction = make_extraction([
            make_fact("F-D", FactType.NOTICE_DATE, "Issued 17/08/2026"),
            make_fact("F-H", FactType.HEARING_DETAILS, "Hearing 02-09-2026"),
        ])
        _, mocks, objects, _ = self._run_pipeline(extraction=extraction)
        mocks["deadline"].assert_called_once_with(
            notice_date=date(2026, 8, 17),
            service_date=None,
            response_period_text=None,
            hearing_date_text="Hearing 02-09-2026",
            today=objects["today"],
        )
        self.assertIs(mocks["deadline"].call_args.kwargs["today"], objects["today"])

    def test_preflight_validation_and_drafting_exact_calls(self):
        _, mocks, objects, _ = self._run_pipeline()
        mocks["preflight"].assert_called_once_with(
            objects["extraction"], objects["classification"], objects["deadline"]
        )
        mocks["validation"].assert_called_once_with(
            objects["classification"], objects["extraction"],
            objects["preflight"], objects["arithmetic"], objects["deadline"],
        )
        mocks["drafting"].assert_called_once_with(
            objects["classification"], objects["extraction"],
            objects["preflight"], objects["arithmetic"],
            objects["validation"], objects["deadline"],
        )

    def test_result_envelope_exact_objects_and_no_raw_text(self):
        result, _, objects, _ = self._run_pipeline()
        self.assertIs(type(result), Phase2AnalysisResult)
        self.assertIs(result.classification, objects["classification"])
        self.assertIs(result.extraction_result, objects["extraction"])
        self.assertIs(result.deadline_result, objects["deadline"])
        self.assertIs(result.preflight_result, objects["preflight"])
        self.assertIs(result.arithmetic_results, objects["arithmetic"])
        self.assertIs(result.validation_result, objects["validation"])
        self.assertIs(result.draft_result, objects["draft"])
        self.assertIsNone(result.triage_summary)
        self.assertFalse(hasattr(result, "raw_text"))

    def test_validation_and_drafting_called_for_every_branch(self):
        cases = [
            (SupportLevel.TRIAGE_ONLY, ProceedingType.GST_SEC73_ITC, FactExtractionStatus.SUCCESS),
            (SupportLevel.UNKNOWN, ProceedingType.UNKNOWN, FactExtractionStatus.SUCCESS),
            (SupportLevel.DEEP_WORKFLOW, ProceedingType.GST_SEC73_ITC, FactExtractionStatus.FAILED),
            (SupportLevel.DEEP_WORKFLOW, ProceedingType.GST_SEC73_ITC, FactExtractionStatus.NO_INPUT),
            (SupportLevel.DEEP_WORKFLOW, ProceedingType.GST_SEC73_ITC, FactExtractionStatus.PARTIAL),
        ]
        for support, proceeding, status in cases:
            with self.subTest(support=support, proceeding=proceeding, status=status):
                classification = make_classification(proceeding, support)
                extraction = make_extraction(status=status)
                _, mocks, _, _ = self._run_pipeline(classification, extraction)
                mocks["validation"].assert_called_once()
                mocks["drafting"].assert_called_once()

    def test_four_reference_proceeding_paths_are_preserved(self):
        expected = (
            ProceedingType.GST_SEC73_ITC,
            ProceedingType.GST_SEC74_FRAUD,
            ProceedingType.GST_SEC129_ENFORCE,
            ProceedingType.GST_SEC73_RCM,
        )
        for proceeding in expected:
            with self.subTest(proceeding=proceeding):
                result, _, _, _ = self._run_pipeline(
                    make_classification(proceeding), make_extraction()
                )
                self.assertIs(result.classification.proceeding_type, proceeding)

    def test_inputs_are_not_mutated(self):
        classification = make_classification()
        extraction = make_extraction([
            make_fact("F-1", FactType.NOTICE_DATE, "17/08/2026")
        ])
        snapshots = (copy.deepcopy(classification), copy.deepcopy(extraction))
        self._run_pipeline(classification, extraction)
        self.assertEqual(classification, snapshots[0])
        self.assertEqual(extraction, snapshots[1])


class DeadlineMappingTests(unittest.TestCase):
    def test_notice_date_zero_candidate_is_none(self):
        self.assertEqual(orchestrator._build_deadline_inputs([]), (None, None))

    def test_notice_date_confirmed_and_alleged_are_eligible(self):
        for status in (FactStatus.CONFIRMED, FactStatus.ALLEGED):
            with self.subTest(status=status):
                fact = make_fact(
                    "F-D", FactType.NOTICE_DATE, "Notice 31.08.2026", status=status
                )
                with patch.object(orchestrator, "_parse_date_text", return_value=date(2026, 8, 31)) as parser:
                    notice_date, _ = orchestrator._build_deadline_inputs([fact])
                self.assertEqual(notice_date, date(2026, 8, 31))
                parser.assert_called_once_with("Notice 31.08.2026")

    def test_notice_date_untrusted_statuses_are_ignored(self):
        for status in (
            FactStatus.REQUIRES_VERIFICATION,
            FactStatus.UNKNOWN,
            FactStatus.INFERRED,
        ):
            with self.subTest(status=status):
                fact = make_fact(
                    "F-D", FactType.NOTICE_DATE, "31/08/2026", status=status
                )
                with patch.object(orchestrator, "_parse_date_text") as parser:
                    notice_date, _ = orchestrator._build_deadline_inputs([fact])
                self.assertIsNone(notice_date)
                parser.assert_not_called()

    def test_multiple_notice_dates_are_ambiguous(self):
        facts = [
            make_fact("F-1", FactType.NOTICE_DATE, "01/08/2026"),
            make_fact("F-2", FactType.NOTICE_DATE, "02/08/2026", status=FactStatus.ALLEGED),
        ]
        with patch.object(orchestrator, "_parse_date_text") as parser:
            notice_date, _ = orchestrator._build_deadline_inputs(facts)
        self.assertIsNone(notice_date)
        parser.assert_not_called()

    def test_malformed_notice_date_uses_parser_none_without_fallback(self):
        fact = make_fact("F-D", FactType.NOTICE_DATE, "not a numeric date")
        with patch.object(orchestrator, "_parse_date_text", return_value=None) as parser:
            notice_date, _ = orchestrator._build_deadline_inputs([fact])
        self.assertIsNone(notice_date)
        parser.assert_called_once_with("not a numeric date")

    def test_notice_claim_is_ignored(self):
        fact = make_fact(
            "F-D", FactType.NOTICE_DATE, "source sentinel",
            claim="Claim says 01/01/2020",
        )
        with patch.object(orchestrator, "_parse_date_text", return_value=None) as parser:
            orchestrator._build_deadline_inputs([fact])
        parser.assert_called_once_with("source sentinel")

    def test_hearing_zero_one_multiple_and_exact_source(self):
        one = make_fact(
            "F-H", FactType.HEARING_DETAILS, "Appear on 04/09/2026",
            status=FactStatus.ALLEGED,
            claim="Claim says another hearing",
        )
        self.assertIsNone(orchestrator._build_deadline_inputs([])[1])
        with patch.object(orchestrator, "_parse_date_text") as parser:
            self.assertEqual(
                orchestrator._build_deadline_inputs([one])[1],
                "Appear on 04/09/2026",
            )
            parser.assert_not_called()
        two = [
            one,
            make_fact("F-H2", FactType.HEARING_DETAILS, "05/09/2026"),
        ]
        self.assertIsNone(orchestrator._build_deadline_inputs(two)[1])

    def test_hearing_untrusted_statuses_and_empty_source_are_ignored(self):
        facts = [
            make_fact("F-1", FactType.HEARING_DETAILS, "01/01/2027", status=FactStatus.UNKNOWN),
            make_fact("F-2", FactType.HEARING_DETAILS, "", status=FactStatus.CONFIRMED),
        ]
        self.assertIsNone(orchestrator._build_deadline_inputs(facts)[1])


class SourceVerificationInputSafetyTests(unittest.TestCase):
    def test_unverified_ocr_notice_date_is_not_deadline_input(self):
        fact = make_fact(
            "F-OCR-DATE",
            FactType.NOTICE_DATE,
            "Date: 17-08-2026",
        )
        fact.source_origin = SourceTextOrigin.OCR
        fact.source_verification = (
            SourceVerificationStatus.REQUIRES_VERIFICATION
        )
        with patch.object(orchestrator, "_parse_date_text") as parser:
            notice_date, _ = orchestrator._build_deadline_inputs([fact])
        self.assertIsNone(notice_date)
        parser.assert_not_called()

    def test_unverified_ocr_amount_is_not_arithmetic_operand(self):
        left, right = make_itc_facts()
        left.source_origin = SourceTextOrigin.OCR
        left.source_verification = (
            SourceVerificationStatus.REQUIRES_VERIFICATION
        )
        profile = make_profile([
            make_requirement(
                RequirementKind.DERIVED,
                ArithmeticCalculationType.ITC_DIFFERENCE,
            )
        ])
        with (
            patch.object(
                orchestrator,
                "get_validation_profile",
                return_value=profile,
            ),
            patch.object(orchestrator, "run_arithmetic") as runner,
        ):
            results = orchestrator._build_arithmetic_results(
                make_classification(),
                make_extraction([left, right]),
            )
        runner.assert_not_called()
        self.assertIs(
            results[0].status,
            ArithmeticStatus.INSUFFICIENT_DATA,
        )
        self.assertEqual(results[0].source_fact_ids, ["F-R"])


class DocumentPageOrchestrationTests(unittest.TestCase):
    def test_document_pages_preserve_origin_into_fact_extractor(self):
        pages = [
            DocumentPageText(
                page_number=1,
                text="embedded\n",
                origin=SourceTextOrigin.EMBEDDED,
                verification=SourceVerificationStatus.VERIFIED,
            ),
            DocumentPageText(
                page_number=2,
                text="recognized",
                origin=SourceTextOrigin.OCR,
                verification=(
                    SourceVerificationStatus.REQUIRES_VERIFICATION
                ),
                ocr_language="eng",
                ocr_dpi=300,
            ),
        ]
        raw_text = "embedded\nrecognized"
        fake_classification = make_classification()
        fake_extraction = make_extraction()
        sentinel = object()
        with (
            patch.object(
                orchestrator,
                "classify_notice",
                return_value=fake_classification,
            ) as classifier,
            patch.object(
                orchestrator,
                "extract_facts_with_document_provenance",
                return_value=fake_extraction,
            ) as extractor,
            patch.object(
                orchestrator,
                "_assemble_phase2_result",
                return_value=sentinel,
            ) as assembler,
        ):
            result = orchestrator.run_phase2_analysis_from_document_pages(
                pages,
                date(2026, 9, 22),
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
            date(2026, 9, 22),
        )


class ArithmeticDiscoveryTests(unittest.TestCase):
    def test_no_profile_and_no_derived_produce_fresh_empty_lists(self):
        classification = make_classification()
        extraction = make_extraction()
        with patch.object(orchestrator, "get_validation_profile", return_value=None):
            first = orchestrator._build_arithmetic_results(classification, extraction)
            second = orchestrator._build_arithmetic_results(classification, extraction)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertIsNot(first, second)

        profile = make_profile([make_requirement(RequirementKind.FACT)])
        with patch.object(orchestrator, "get_validation_profile", return_value=profile):
            self.assertEqual(
                orchestrator._build_arithmetic_results(classification, extraction), []
            )

    def test_nonderived_calculation_type_is_ignored(self):
        profile = make_profile([
            make_requirement(
                RequirementKind.FACT,
                ArithmeticCalculationType.ITC_DIFFERENCE,
            )
        ])
        with patch.object(orchestrator, "get_validation_profile", return_value=profile), patch.object(orchestrator, "run_arithmetic") as runner:
            results = orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(make_itc_facts())
            )
        self.assertEqual(results, [])
        runner.assert_not_called()

    def test_duplicate_calculation_first_occurrence_only(self):
        profile = make_profile([
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.ITC_DIFFERENCE, "1"),
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.ITC_DIFFERENCE, "2"),
        ])
        expected = ArithmeticResult(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            status=ArithmeticStatus.PASS,
            source_fact_ids=["F-L", "F-R"],
            operand_values=[], result=None,
            formula="GSTR-3B ITC - GSTR-2B ITC",
        )
        with patch.object(orchestrator, "get_validation_profile", return_value=profile), patch.object(orchestrator, "run_arithmetic", return_value=expected) as runner:
            results = orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(make_itc_facts())
            )
        self.assertEqual(results, [expected])
        runner.assert_called_once()

    def test_requirement_order_defines_result_order(self):
        profile = make_profile([
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE, "1"),
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.ITC_DIFFERENCE, "2"),
        ])
        facts = make_itc_facts() + [
            make_fact("F-O-L", FactType.STATED_AMOUNT, "GSTR-1: 900", role=FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT),
            make_fact("F-O-R", FactType.STATED_AMOUNT, "GSTR-3B: 800", role=FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT),
        ]
        def execute(request, supplied_facts):
            return ArithmeticResult(
                calculation_type=request.calculation_type,
                status=ArithmeticStatus.PASS,
                source_fact_ids=[], operand_values=[], result=None,
                formula="formula",
            )
        with patch.object(orchestrator, "get_validation_profile", return_value=profile), patch.object(orchestrator, "run_arithmetic", side_effect=execute):
            results = orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(facts)
            )
        self.assertEqual(
            [result.calculation_type for result in results],
            [ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
             ArithmeticCalculationType.ITC_DIFFERENCE],
        )

    def test_triage_and_unknown_force_empty_arithmetic(self):
        cases = [
            make_classification(support_level=SupportLevel.TRIAGE_ONLY),
            make_classification(ProceedingType.UNKNOWN, SupportLevel.UNKNOWN),
        ]
        for classification in cases:
            with self.subTest(classification=classification):
                with patch.object(orchestrator, "get_validation_profile") as profile:
                    result = orchestrator._build_arithmetic_results(
                        classification, make_extraction(make_itc_facts())
                    )
                self.assertEqual(result, [])
                profile.assert_not_called()

    def test_profile_is_not_mutated(self):
        profile = make_profile([
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.ITC_DIFFERENCE)
        ])
        snapshot = copy.deepcopy(profile)
        with patch.object(orchestrator, "get_validation_profile", return_value=profile), patch.object(orchestrator, "run_arithmetic", return_value=Mock()):
            orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(make_itc_facts())
            )
        self.assertEqual(profile, snapshot)


class ArithmeticOperandAndAmountTests(unittest.TestCase):
    def _itc_profile(self):
        return make_profile([
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.ITC_DIFFERENCE)
        ])

    def _build(self, facts, runner=None):
        runner = runner or Mock()
        with patch.object(orchestrator, "get_validation_profile", return_value=self._itc_profile()), patch.object(orchestrator, "run_arithmetic", runner):
            results = orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(facts)
            )
        return results, runner

    def test_itc_request_exact_roles_direction_ids_values_and_fact_identity(self):
        facts = make_itc_facts()
        returned = ArithmeticResult(
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
            status=ArithmeticStatus.MISMATCH,
            source_fact_ids=["F-L", "F-R"], operand_values=[], result=None,
            formula="GSTR-3B ITC - GSTR-2B ITC",
        )
        extraction = make_extraction(facts)
        runner = Mock(return_value=returned)
        with patch.object(orchestrator, "get_validation_profile", return_value=self._itc_profile()), patch.object(orchestrator, "run_arithmetic", runner):
            results = orchestrator._build_arithmetic_results(
                make_classification(), extraction
            )
        self.assertEqual(results, [returned])
        runner.assert_called_once()
        request, supplied_facts = runner.call_args.args
        self.assertIs(request.calculation_type, ArithmeticCalculationType.ITC_DIFFERENCE)
        self.assertEqual(request.left_operand.source_fact_id, "F-L")
        self.assertEqual(request.left_operand.value_text, "Rs. 10,00,000.50")
        self.assertEqual(request.right_operand.source_fact_id, "F-R")
        self.assertEqual(request.right_operand.value_text, "INR 8,50,000.25")
        self.assertIs(supplied_facts, extraction.facts)

    def test_output_request_exact_direction(self):
        profile = make_profile([
            make_requirement(RequirementKind.DERIVED, ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE)
        ])
        facts = [
            make_fact("F-G1", FactType.STATED_AMOUNT, "Declared liability Rs. 500", role=FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT),
            make_fact("F-G3B", FactType.STATED_AMOUNT, "GSTR-3B liability Rs. 450", role=FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT),
        ]
        with patch.object(orchestrator, "get_validation_profile", return_value=profile), patch.object(orchestrator, "run_arithmetic", return_value=Mock()) as runner:
            orchestrator._build_arithmetic_results(
                make_classification(), make_extraction(facts)
            )
        request = runner.call_args.args[0]
        self.assertEqual(request.left_operand.source_fact_id, "F-G1")
        self.assertEqual(request.right_operand.source_fact_id, "F-G3B")

    def test_candidate_requires_stated_amount_confirmed_and_exact_role(self):
        valid_right = make_itc_facts()[1]
        invalid_lefts = [
            make_fact("F-TYPE", FactType.DOCUMENT_DETAIL, "Rs. 100", role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
            make_fact("F-ROLE", FactType.STATED_AMOUNT, "Rs. 100", role=FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT),
            make_fact("F-STATUS", FactType.STATED_AMOUNT, "Rs. 100", role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT, status=FactStatus.ALLEGED),
        ]
        results, runner = self._build(invalid_lefts + [valid_right])
        runner.assert_not_called()
        self.assertIs(results[0].status, ArithmeticStatus.INSUFFICIENT_DATA)
        self.assertEqual(results[0].source_fact_ids, ["F-R"])

    def test_missing_or_ambiguous_operand_never_calls_engine(self):
        cases = [
            make_itc_facts()[1:],
            make_itc_facts()[:1],
            [make_itc_facts()[0], copy.deepcopy(make_itc_facts()[0]), make_itc_facts()[1]],
            [make_itc_facts()[0], make_itc_facts()[1], copy.deepcopy(make_itc_facts()[1])],
        ]
        for facts in cases:
            with self.subTest(ids=[fact.fact_id for fact in facts]):
                results, runner = self._build(facts)
                runner.assert_not_called()
                self.assertIs(results[0].status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_zero_or_multiple_amount_tokens_are_unresolved(self):
        for source in ("No amount stated", "Amounts Rs. 100 and INR 50"):
            with self.subTest(source=source):
                facts = make_itc_facts()
                facts[0].source_text = source
                results, runner = self._build(facts)
                runner.assert_not_called()
                self.assertIs(results[0].status, ArithmeticStatus.INSUFFICIENT_DATA)

    def test_amount_token_preserves_supported_verbatim_forms(self):
        cases = [
            ("Value ₹1,50,000", "₹1,50,000"),
            ("Value Rs. 1,50,000.50", "Rs. 1,50,000.50"),
            ("Value INR   -150000", "-150000"),
            ("Value -INR 150000.5", "-INR 150000.5"),
            ("Value rs 150,000", "rs 150,000"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                fact = make_fact("F", FactType.STATED_AMOUNT, source)
                self.assertEqual(orchestrator._value_text(fact), expected)

    def test_gstr_identifier_digits_are_not_amounts_and_grouping_is_one_token(self):
        fact = make_fact(
            "F", FactType.STATED_AMOUNT,
            "GSTR-3B reconciliation amount is 1,50,000",
        )
        self.assertEqual(orchestrator._value_text(fact), "1,50,000")

    def test_claim_is_never_amount_source(self):
        fact = make_fact(
            "F", FactType.STATED_AMOUNT, "No token",
            claim="Claim includes Rs. 1,50,000",
        )
        self.assertIsNone(orchestrator._value_text(fact))

    def test_insufficient_result_exact_shape_and_formulas(self):
        for calculation_type, formula in (
            (ArithmeticCalculationType.ITC_DIFFERENCE, "GSTR-3B ITC - GSTR-2B ITC"),
            (ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE, "GSTR-1 liability - GSTR-3B liability"),
        ):
            with self.subTest(calculation_type=calculation_type):
                result = orchestrator._insufficient_arithmetic_result(
                    calculation_type, [], []
                )
                self.assertIs(result.calculation_type, calculation_type)
                self.assertIs(result.status, ArithmeticStatus.INSUFFICIENT_DATA)
                self.assertEqual(result.source_fact_ids, [])
                self.assertEqual(result.operand_values, [])
                self.assertIsNone(result.result)
                self.assertEqual(result.formula, formula)
                self.assertEqual(result.currency, "INR")
                self.assertIs(result.allowed_in_draft, DraftPermission.CONDITIONAL)

    def test_insufficient_source_ids_left_then_right_order_and_dedup(self):
        left = [
            make_fact("F-002", FactType.STATED_AMOUNT, "100"),
            make_fact("F-007", FactType.STATED_AMOUNT, "200"),
            make_fact("F-SAME", FactType.STATED_AMOUNT, "300"),
        ]
        right = [
            make_fact("F-004", FactType.STATED_AMOUNT, "400"),
            make_fact("F-SAME", FactType.STATED_AMOUNT, "500"),
            make_fact("F-009", FactType.STATED_AMOUNT, "600"),
        ]
        self.assertEqual(
            orchestrator._ordered_candidate_ids(left, right),
            ["F-002", "F-007", "F-SAME", "F-004", "F-009"],
        )
        self.assertEqual(orchestrator._ordered_candidate_ids([], []), [])
        self.assertEqual(orchestrator._ordered_candidate_ids(left, []), ["F-002", "F-007", "F-SAME"])
        self.assertEqual(orchestrator._ordered_candidate_ids([], right), ["F-004", "F-SAME", "F-009"])

    def test_global_interleaving_does_not_override_side_order(self):
        facts = [
            make_fact("F-004", FactType.STATED_AMOUNT, "100", role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT),
            make_fact("F-002", FactType.STATED_AMOUNT, "200", role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
            make_fact("F-007", FactType.STATED_AMOUNT, "300", role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT),
            make_fact("F-009", FactType.STATED_AMOUNT, "400", role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT),
        ]
        results, runner = self._build(facts)
        runner.assert_not_called()
        self.assertEqual(
            results[0].source_fact_ids,
            ["F-002", "F-007", "F-004", "F-009"],
        )


class TriageSummaryTests(unittest.TestCase):
    def _summary(self, status, support, proceeding):
        classification = make_classification(proceeding, support)
        extraction = make_extraction(status=status)
        preflight = make_preflight(status)
        deadline = make_deadline()
        summary = orchestrator._build_triage_summary(
            classification, extraction, preflight, deadline
        )
        return summary, classification, extraction, preflight, deadline

    def test_normal_success_and_deep_partial_have_no_summary(self):
        for status in (FactExtractionStatus.SUCCESS, FactExtractionStatus.PARTIAL):
            with self.subTest(status=status):
                summary, *_ = self._summary(
                    status, SupportLevel.DEEP_WORKFLOW,
                    ProceedingType.GST_SEC73_ITC,
                )
                self.assertIsNone(summary)

    def test_presence_and_exact_messages(self):
        cases = [
            (FactExtractionStatus.NO_INPUT, SupportLevel.DEEP_WORKFLOW, ProceedingType.GST_SEC73_ITC, "No usable notice text was available for Phase-2 analysis."),
            (FactExtractionStatus.FAILED, SupportLevel.DEEP_WORKFLOW, ProceedingType.GST_SEC73_ITC, "Fact extraction failed, so specialist drafting is blocked."),
            (FactExtractionStatus.SUCCESS, SupportLevel.UNKNOWN, ProceedingType.GST_SEC73_ITC, "This notice could not be matched to an approved deep specialist workflow."),
            (FactExtractionStatus.SUCCESS, SupportLevel.DEEP_WORKFLOW, ProceedingType.UNKNOWN, "This notice could not be matched to an approved deep specialist workflow."),
            (FactExtractionStatus.SUCCESS, SupportLevel.TRIAGE_ONLY, ProceedingType.GST_SEC73_ITC, "This notice is recognized for triage, but no approved deep specialist workflow is available."),
        ]
        for status, support, proceeding, message in cases:
            with self.subTest(status=status, support=support, proceeding=proceeding):
                summary, *_ = self._summary(status, support, proceeding)
                self.assertIsInstance(summary, TriageSummary)
                self.assertEqual(summary.message, message)

    def test_message_precedence(self):
        cases = [
            (FactExtractionStatus.NO_INPUT, SupportLevel.TRIAGE_ONLY, ProceedingType.UNKNOWN, orchestrator._NO_INPUT_MESSAGE),
            (FactExtractionStatus.FAILED, SupportLevel.TRIAGE_ONLY, ProceedingType.UNKNOWN, orchestrator._FAILED_MESSAGE),
            (FactExtractionStatus.SUCCESS, SupportLevel.TRIAGE_ONLY, ProceedingType.UNKNOWN, orchestrator._UNKNOWN_MESSAGE),
        ]
        for status, support, proceeding, expected in cases:
            with self.subTest(status=status):
                summary, *_ = self._summary(status, support, proceeding)
                self.assertEqual(summary.message, expected)

    def test_exact_fourteen_structured_values_are_copied(self):
        summary, classification, extraction, preflight, deadline = self._summary(
            FactExtractionStatus.FAILED,
            SupportLevel.UNKNOWN,
            ProceedingType.UNKNOWN,
        )
        self.assertIs(summary.proceeding_type, classification.proceeding_type)
        self.assertIs(summary.notice_form, classification.notice_form)
        self.assertIs(summary.support_level, classification.support_level)
        self.assertIs(summary.classification_confidence, classification.confidence)
        self.assertIs(summary.extraction_status, extraction.status)
        self.assertIs(summary.portal_verification_required, preflight.portal_verification_required)
        self.assertIs(summary.authority_verification_required, preflight.authority_verification_required)
        self.assertIs(summary.communication_identifier_status, preflight.communication_identifier_status)
        self.assertIs(summary.authority_details_status, preflight.authority_details_status)
        self.assertIs(summary.deadline_status, deadline.deadline_status)
        self.assertIs(summary.hearing_status, deadline.hearing_status)
        self.assertIs(summary.requested_document_fact_ids, preflight.requested_document_fact_ids)
        self.assertIs(summary.referenced_annexure_fact_ids, preflight.referenced_annexure_fact_ids)
        self.assertFalse(hasattr(summary, "raw_text"))
        self.assertFalse(hasattr(summary, "claim"))


if __name__ == "__main__":
    unittest.main()
