"""Thin Streamlit shell for the structured Phase-2 notice analysis."""

from datetime import date

import streamlit as st

from domain.models import DraftGenerationStatus, ValidationStatus
from domain.phase2_orchestrator import run_phase2_analysis_from_document_pages
from domain.models import SourceTextOrigin
from modules.pdf_reader import extract_document_pages


def _display(value):
    if value is None:
        return "unavailable"
    enum_value = getattr(value, "value", None)
    return enum_value if enum_value is not None else str(value)


def _render_checks(checks):
    if not checks:
        st.write("None.")
        return
    st.dataframe(
        [
            {
                "check_id": item.check_id,
                "status": item.status.value,
                "message": item.message,
                "related_fact_ids": item.related_fact_ids,
                "related_calculation_types": [
                    calculation_type.value
                    for calculation_type in item.related_calculation_types
                ],
            }
            for item in checks
        ],
        hide_index=True,
    )


def _render_phase2_result(result):
    classification = result.classification
    extraction = result.extraction_result
    preflight = result.preflight_result
    deadline = result.deadline_result
    validation = result.validation_result
    draft = result.draft_result

    st.header("Classification and support")
    st.write(
        {
            "proceeding_type": classification.proceeding_type.value,
            "support_level": classification.support_level.value,
            "notice_form": classification.notice_form.value,
            "confidence": classification.confidence.value,
        }
    )

    st.header("Fact extraction")
    st.write({"extraction_status": extraction.status.value})
    if extraction.facts:
        st.dataframe(
            [
                {
                    "fact_id": fact.fact_id,
                    "fact_type": fact.fact_type.value,
                    "fact_role": fact.fact_role.value,
                    "status": fact.status.value,
                    "source_text": _display(fact.source_text),
                    "source_page": _display(fact.source_page),
                    "source_origin": fact.source_origin.value,
                    "source_verification": fact.source_verification.value,
                    "allowed_in_draft": fact.allowed_in_draft.value,
                }
                for fact in extraction.facts
            ],
            hide_index=True,
        )
    else:
        st.write("No structured facts were extracted.")

    st.header("Preflight and deadline")
    st.write(
        {
            "communication_identifier_status": (
                preflight.communication_identifier_status.value
            ),
            "authority_details_status": preflight.authority_details_status.value,
            "portal_verification_required": (
                preflight.portal_verification_required
            ),
            "authority_verification_required": (
                preflight.authority_verification_required
            ),
            "deadline_status": deadline.deadline_status.value,
            "response_deadline": _display(deadline.response_deadline),
            "days_remaining": _display(deadline.days_remaining),
            "hearing_status": deadline.hearing_status.value,
            "hearing_date": _display(deadline.hearing_date),
            "deadline_conflict_status": preflight.deadline_conflict_status.value,
        }
    )

    if result.arithmetic_results:
        st.header("Arithmetic results")
        st.dataframe(
            [
                {
                    "calculation_type": item.calculation_type.value,
                    "formula": item.formula,
                    "status": item.status.value,
                    "operand_values": [str(value) for value in item.operand_values],
                    "result": _display(item.result),
                    "currency": item.currency,
                    "source_fact_ids": item.source_fact_ids,
                }
                for item in result.arithmetic_results
            ],
            hide_index=True,
        )

    st.header("Validation status")
    st.write(
        {
            "overall_status": validation.overall_status.value,
            "draft_eligibility": validation.draft_eligibility.value,
        }
    )
    _render_checks(validation.checks)

    st.header("Unresolved requirements")
    if draft.unresolved_requirements:
        st.dataframe(
            [
                {
                    "requirement_id": item.requirement_id,
                    "requirement_text": item.requirement_text,
                    "status": item.status.value,
                    "related_fact_ids": item.related_fact_ids,
                    "calculation_type": _display(item.calculation_type),
                }
                for item in draft.unresolved_requirements
            ],
            hide_index=True,
        )
    else:
        st.write("None.")

    st.header("Evidence checklist")
    if draft.evidence_checklist:
        st.dataframe(
            [
                {
                    "evidence_id": item.evidence_id,
                    "requirement_text": item.requirement_text,
                    "status": item.status.value,
                }
                for item in draft.evidence_checklist
            ],
            hide_index=True,
        )
    else:
        st.write("None.")

    st.header("Review requirements")
    if draft.review_requirements:
        st.dataframe(
            [
                {
                    "review_id": item.review_id,
                    "level": item.level.value,
                    "reason": item.reason,
                    "mandatory": item.mandatory,
                }
                for item in draft.review_requirements
            ],
            hide_index=True,
        )
    else:
        st.write("None.")

    if result.triage_summary is not None:
        triage = result.triage_summary
        st.header("Triage summary")
        st.write(triage.message)
        st.write(
            {
                "proceeding_type": triage.proceeding_type.value,
                "notice_form": triage.notice_form.value,
                "support_level": triage.support_level.value,
                "classification_confidence": (
                    triage.classification_confidence.value
                ),
                "extraction_status": triage.extraction_status.value,
                "portal_verification_required": (
                    triage.portal_verification_required
                ),
                "authority_verification_required": (
                    triage.authority_verification_required
                ),
                "communication_identifier_status": (
                    triage.communication_identifier_status.value
                ),
                "authority_details_status": (
                    triage.authority_details_status.value
                ),
                "deadline_status": triage.deadline_status.value,
                "hearing_status": triage.hearing_status.value,
                "requested_document_fact_ids": (
                    triage.requested_document_fact_ids
                ),
                "referenced_annexure_fact_ids": (
                    triage.referenced_annexure_fact_ids
                ),
            }
        )

    draft_is_displayable = (
        draft.status is DraftGenerationStatus.SUCCESS
        and draft.post_validation is not None
        and draft.post_validation.overall_status is ValidationStatus.PASS
    )
    if draft_is_displayable:
        st.header("Specialist draft")
        for section in draft.sections:
            st.subheader(section.title)
            st.markdown(section.rendered_text)
    else:
        st.header("Drafting status")
        st.write(
            {
                "status": draft.status.value,
                "failure_code": _display(draft.failure_code),
                "error_message": _display(draft.error_message),
                "draft_eligibility": draft.draft_eligibility.value,
            }
        )
        if draft.post_validation is not None:
            st.subheader("Post-validation diagnostics")
            st.write(
                {
                    "overall_status": (
                        draft.post_validation.overall_status.value
                    )
                }
            )
            _render_checks(draft.post_validation.checks)


st.set_page_config(
    page_title="CA Notice AI",
    page_icon="📋",
    layout="centered",
)

st.title("📋 CA Notice AI")
st.write("Upload a GST notice PDF for structured Phase-2 analysis.")
st.caption("Phase-2 outputs require professional review before use.")

uploaded = st.file_uploader("Upload notice PDF", type="pdf")

if uploaded:
    pdf_bytes = uploaded.read()
    try:
        document_pages = extract_document_pages(pdf_bytes)
        raw_text = "".join(page.text for page in document_pages)
    except RuntimeError as error:
        st.error(str(error))
    else:
        today = date.today()
        try:
            with st.spinner("Analyzing notice..."):
                result = run_phase2_analysis_from_document_pages(
                    document_pages, today
                )
        except Exception:
            st.error("Phase-2 analysis could not be completed.")
        else:
            ocr_pages = [
                page.page_number
                for page in document_pages
                if page.origin is SourceTextOrigin.OCR
            ]
            if ocr_pages:
                st.warning(
                    "OCR was used on scanned page(s): "
                    + ", ".join(str(page) for page in ocr_pages)
                    + ". OCR-derived facts require verification and block "
                    "specialist drafting until reviewed."
                )
            _render_phase2_result(result)
            with st.expander("Extracted notice text"):
                st.text(raw_text)
