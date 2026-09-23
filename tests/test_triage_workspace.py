"""Tests for the triage-only evidence workspace adapter."""

import unittest

from domain.models import (
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
    SpecialistDraftResult,
    SupportLevel,
    TriageSummary,
    ValidationEngineResult,
    ValidationStatus,
)
from modules.triage_workspace import build_triage_requested_document_checklist


def make_result(*, support=SupportLevel.TRIAGE_ONLY, facts=None, requested_ids=None):
    facts = list(facts or [])
    requested_ids = list(requested_ids or [])
    classification = NoticeClassification(
        notice_family=NoticeFamily.ASSESSMENT_SCRUTINY,
        notice_form=NoticeForm.ASMT_10,
        proceeding_type=ProceedingType.UNKNOWN,
        support_level=support,
        confidence=ClassificationConfidence.HIGH,
        classification_reasons=["fixture"],
    )
    extraction = FactExtractionResult(
        facts=facts,
        status=FactExtractionStatus.SUCCESS,
    )
    deadline = DeadlineResult(
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
    preflight = PreflightResult(
        fact_extraction_status=FactExtractionStatus.SUCCESS,
        communication_identifier_status=CommunicationIdentifierStatus.UNKNOWN,
        portal_verification_required=True,
        authority_details_status=AuthorityDetailsStatus.UNKNOWN,
        authority_verification_required=True,
        stated_due_date_fact_ids=[],
        parsed_stated_due_dates=[],
        unparsed_stated_due_date_fact_ids=[],
        deadline_conflict_status=DeadlineConflictStatus.CANNOT_COMPARE,
        hearing_fact_ids=[],
        requested_document_fact_ids=requested_ids,
        referenced_annexure_fact_ids=[],
    )
    validation = ValidationEngineResult(
        overall_status=ValidationStatus.WARNING,
        draft_eligibility=DraftEligibility.BLOCKED,
        case_severity=None,
        checks=[],
        requirements=[],
        evidence_checklist=[],
        review_requirements=[],
    )
    draft = SpecialistDraftResult(
        status=DraftGenerationStatus.BLOCKED,
        draft_eligibility=DraftEligibility.BLOCKED,
        sections=[],
        unresolved_requirements=[],
        evidence_checklist=[],
        review_requirements=[],
        post_validation=None,
        failure_code=None,
        error_message=None,
    )
    triage = None
    if support is SupportLevel.TRIAGE_ONLY:
        triage = TriageSummary(
            proceeding_type=ProceedingType.UNKNOWN,
            notice_form=NoticeForm.ASMT_10,
            support_level=SupportLevel.TRIAGE_ONLY,
            classification_confidence=ClassificationConfidence.HIGH,
            extraction_status=FactExtractionStatus.SUCCESS,
            portal_verification_required=True,
            authority_verification_required=True,
            communication_identifier_status=CommunicationIdentifierStatus.UNKNOWN,
            authority_details_status=AuthorityDetailsStatus.UNKNOWN,
            deadline_status=DeadlineStatus.UNKNOWN,
            hearing_status=HearingStatus.NOT_SCHEDULED,
            requested_document_fact_ids=requested_ids,
            referenced_annexure_fact_ids=[],
            message="triage",
        )
    return Phase2AnalysisResult(
        classification=classification,
        extraction_result=extraction,
        deadline_result=deadline,
        preflight_result=preflight,
        arithmetic_results=[],
        validation_result=validation,
        draft_result=draft,
        triage_summary=triage,
    )


def requested_fact(
    fact_id,
    source_text,
    *,
    status=FactStatus.CONFIRMED,
    fact_type=FactType.REQUESTED_DOCUMENT,
):
    return ExtractedFact(
        fact_id=fact_id,
        claim="MODEL CLAIM MUST NOT BE USED",
        status=status,
        source_text=source_text,
        source_page=1,
        allowed_in_draft=DraftPermission.YES,
        fact_type=fact_type,
        fact_role=FactRole.NONE,
    )


class TriageRequestedDocumentChecklistTests(unittest.TestCase):
    def test_builds_unknown_targets_from_exact_notice_source_text(self):
        result = make_result(
            facts=[
                requested_fact("F-001", "1. Purchase register"),
                requested_fact("F-002", "2. Sales register"),
            ],
            requested_ids=["F-001", "F-002"],
        )
        items = build_triage_requested_document_checklist(result)
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [item.requirement_text for item in items],
            [
                "Department-requested record: 1. Purchase register",
                "Department-requested record: 2. Sales register",
            ],
        )
        self.assertTrue(all(item.status is EvidenceStatus.UNKNOWN for item in items))
        self.assertNotIn(
            "MODEL CLAIM MUST NOT BE USED",
            repr(items),
        )

    def test_only_deterministically_selected_requested_fact_ids_are_used(self):
        result = make_result(
            facts=[
                requested_fact("F-001", "1. Purchase register"),
                requested_fact("F-002", "2. Sales register"),
            ],
            requested_ids=["F-002", "F-MISSING"],
        )
        items = build_triage_requested_document_checklist(result)
        self.assertEqual(
            [item.evidence_id for item in items],
            ["triage.requested_document.F-002"],
        )

    def test_wrong_type_or_nonconfirmed_fact_is_ignored(self):
        result = make_result(
            facts=[
                requested_fact(
                    "F-001",
                    "Department allegation text",
                    fact_type=FactType.DEPARTMENT_ALLEGATION,
                ),
                requested_fact(
                    "F-002",
                    "Requested record needing verification",
                    status=FactStatus.REQUIRES_VERIFICATION,
                ),
            ],
            requested_ids=["F-001", "F-002"],
        )
        self.assertEqual(build_triage_requested_document_checklist(result), [])

    def test_deep_workflow_never_receives_triage_targets(self):
        result = make_result(
            support=SupportLevel.DEEP_WORKFLOW,
            facts=[requested_fact("F-001", "1. Purchase register")],
            requested_ids=["F-001"],
        )
        self.assertEqual(build_triage_requested_document_checklist(result), [])


if __name__ == "__main__":
    unittest.main()
