"""Thin Streamlit shell for the structured Phase-2 notice analysis."""

from datetime import date, datetime, timezone

import streamlit as st

from domain.auth_models import AccessPermission
from domain.case_models import CaseDocumentKind, CaseStatus
from domain.draft_work_product_models import DraftReviewStatus
from domain.evidence_engine import propose_evidence_candidates
from domain.evidence_review import (
    create_evidence_review,
    reviewed_candidate_ids,
)
from domain.models import (
    DraftGenerationStatus,
    EvidenceReviewStatus,
    SourceTextOrigin,
    ValidationStatus,
)
from domain.phase2_orchestrator import run_phase2_analysis_from_document_pages
from modules.evidence_workspace import (
    build_evidence_documents,
    evidence_workspace_key,
    notice_analysis_key,
)
from modules.pdf_reader import extract_document_pages
from modules.runtime_persistence import (
    RuntimePersistenceConfigurationError,
    build_authorized_analysis_snapshot_service,
    build_authorized_case_service,
    build_authorized_draft_work_product_service,
    build_authorized_evidence_review_service,
    build_authorized_evidence_workspace_service,
    build_authorized_filing_service,
    build_authorized_legal_brief_service,
    build_authorized_professional_workbench_service,
)
from modules.case_reopen_service import (
    SavedCaseReopenError,
    reopen_case_analysis,
)
from modules.case_evidence_service import add_supporting_evidence_pdf
from modules.runtime_access import (
    RuntimeAccessConfigurationError,
    RuntimeAccessConsistencyError,
    database_path_from_environment,
    load_available_firms_for_permissions,
)
from modules.runtime_security import (
    AuthenticationExpiredError,
    AuthenticationNotYetValidError,
    AuthenticationRequiredError,
    principal_from_streamlit_user,
)
from workflows.gst.legal_questions import build_gst_legal_question_plan
from workflows.gst.legal_research import (
    build_gst_legal_date_context,
    resolve_gst_legal_brief_from_context,
)


def _display(value):
    if value is None:
        return "unavailable"
    enum_value = getattr(value, "value", None)
    return enum_value if enum_value is not None else str(value)


def _render_checks(checks, *, technical=False):
    if not checks:
        st.write("None.")
        return
    if technical:
        rows = [
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
        ]
    else:
        rows = [
            {
                "Status": _friendly_enum(item.status),
                "What Dwaar checked": item.message,
            }
            for item in checks
        ]
    st.dataframe(rows, hide_index=True)


def _render_legal_brief(classification, extraction):
    st.header("Verified legal sources")
    date_context = build_gst_legal_date_context(extraction.facts)
    brief = resolve_gst_legal_brief_from_context(
        classification.proceeding_type,
        date_context,
    )
    question_plan = build_gst_legal_question_plan(
        classification.proceeding_type,
        extraction.facts,
        date_context,
    )
    st.caption(
        "Source-verified propositions selected only when the required "
        "legal applicability date has verified fact provenance. This is "
        "research support, not a case-specific legal conclusion."
    )

    st.subheader("Legal research questions")
    st.caption(
        "Question status separates missing case facts, missing legal dates, "
        "uncurated authority, and source-verified research readiness. "
        "Research-ready does not mean the case-specific legal conclusion "
        "has been decided."
    )
    if question_plan.questions:
        st.dataframe(
            [
                {
                    "question_id": item.question_id,
                    "question": item.question_text,
                    "status": item.status.value,
                    "date_basis": item.date_basis.value,
                    "related_fact_ids": list(item.related_fact_ids),
                    "missing_fact_requirements": [
                        (
                            selector.fact_type.value
                            + " / "
                            + selector.fact_role.value
                        )
                        for selector in item.missing_fact_selectors
                    ],
                    "verified_rule_ids": list(item.matched_rule_ids),
                }
                for item in question_plan.questions
            ],
            hide_index=True,
        )
    else:
        st.write(
            "No closed legal-question plan exists for this proceeding."
        )

    if date_context.anchors:
        st.dataframe(
            [
                {
                    "date_basis": anchor.basis.value,
                    "effective_date": anchor.effective_date,
                    "period_start": _display(anchor.period_start),
                    "period_end": _display(anchor.period_end),
                    "source_fact_id": anchor.source_fact_id,
                    "source_page": _display(anchor.source_page),
                    "source_text": anchor.source_text,
                }
                for anchor in date_context.anchors
            ],
            hide_index=True,
        )
    else:
        st.write(
            "No provenance-bearing legal applicability date could be "
            "derived from confirmed, verified facts."
        )

    if not brief.catalog_valid:
        st.error(
            "The verified legal catalog failed validation. No legal "
            "propositions are being trusted for this analysis."
        )
        return

    if brief.matches:
        st.dataframe(
            [
                {
                    "topic": match.rule.topic.value,
                    "provision": match.rule.provision,
                    "proposition": match.rule.proposition,
                    "effective_from": match.rule.effective_from,
                    "effective_to": _display(match.rule.effective_to),
                    "source": match.source.title,
                    "official_url": match.source.official_url,
                    "verified_at": match.rule.verified_at,
                    "rule_id": match.rule.rule_id,
                }
                for match in brief.matches
            ],
            hide_index=True,
        )
    else:
        st.write("No source-verified proposition matched this workflow/date.")

    if brief.unresolved_topics:
        st.warning(
            "CA legal research is still required for: "
            + ", ".join(topic.value for topic in brief.unresolved_topics)
        )


def _classification_failed_for_display(result):
    triage = result.triage_summary
    return (
        triage is not None
        and triage.message.startswith(
            "Notice classification could not be completed"
        )
    )


def _friendly_enum(value):
    raw = _display(value)
    if raw == "unavailable":
        return raw
    return raw.replace("_", " ").strip().title()


def _notice_form_label(notice_form):
    raw = notice_form.value
    if raw == "unknown":
        return "Notice form not identified"
    return raw.replace("_", " ").upper()


def _proceeding_label(proceeding_type):
    labels = {
        "gst_sec73_itc": "Section 73 — ITC",
        "gst_sec73_general": "Section 73 — General",
        "gst_sec73_rcm": "Section 73 — RCM",
        "gst_sec74_fraud": "Section 74 — Fraud allegation",
        "gst_sec129_enforcement": "Section 129 — Enforcement",
        "unknown": "Intake",
    }
    return labels.get(proceeding_type.value, _friendly_enum(proceeding_type))


def _render_phase2_result(result):
    classification = result.classification
    extraction = result.extraction_result
    preflight = result.preflight_result
    deadline = result.deadline_result
    validation = result.validation_result
    draft = result.draft_result

    st.header("Classification and support")
    if _classification_failed_for_display(result):
        st.error(
            "AI classification could not be completed. Dwaar has not "
            "determined that this is an unknown notice; the classification "
            "step itself needs to be retried."
        )
    else:
        st.write(f"**{_notice_form_label(classification.notice_form)}**")
        st.caption(
            f"{_friendly_enum(classification.confidence)}-confidence "
            "identification."
        )
        if classification.support_level.value == "deep_workflow":
            st.write("Specialist workflow is available for this notice.")
        elif classification.support_level.value == "triage_only":
            st.warning(
                "Dwaar recognizes this notice for triage, but a specialist "
                "workflow is not yet available for this form."
            )
        else:
            st.warning(
                "Dwaar could not match this notice to a supported specialist "
                "workflow."
            )

    with st.expander("Technical details — classification"):
        st.write(
            {
                "proceeding_type": classification.proceeding_type.value,
                "support_level": classification.support_level.value,
                "notice_form": classification.notice_form.value,
                "confidence": classification.confidence.value,
                "classification_reasons": classification.classification_reasons,
            }
        )

    st.header("Fact extraction")
    if extraction.status.value == "success":
        st.write("Structured facts were extracted successfully.")
    elif extraction.status.value == "partial":
        st.warning(
            "Dwaar extracted usable facts, but rejected one or more candidate "
            "facts that could not be safely validated."
        )
    elif extraction.status.value == "failed":
        st.error(
            "Structured fact extraction could not be completed. No absence "
            "conclusions should be drawn from this result."
        )
    else:
        st.warning("No usable notice text was available for fact extraction.")

    if extraction.facts:
        st.dataframe(
            [
                {
                    "Type": _friendly_enum(fact.fact_type),
                    "Source evidence": _display(fact.source_text),
                    "Source page": _display(fact.source_page),
                    "Verification": _friendly_enum(fact.source_verification),
                }
                for fact in extraction.facts
            ],
            hide_index=True,
        )
        with st.expander("Technical details — extracted facts"):
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
    communication = preflight.communication_identifier_status.value
    if communication == "both_present":
        st.write("**Communication ID:** RFN and DIN were found in the notice.")
    elif communication == "din_present":
        st.write("**Communication ID:** DIN was found in the notice.")
    elif communication == "rfn_present":
        st.write("**Communication ID:** RFN was found in the notice.")
    elif communication == "neither_found":
        st.warning("No RFN or DIN was found in the completed extraction.")
    else:
        st.warning(
            "Communication-ID completeness cannot be concluded from the "
            "current extraction."
        )

    authority = preflight.authority_details_status.value
    if authority == "present":
        st.write("**Authority details:** Core issuing-authority details were found.")
    elif authority == "partial":
        st.warning("**Authority details:** Some issuing-authority details were found.")
    elif authority == "missing":
        st.warning("**Authority details:** No issuing-authority details were found.")
    else:
        st.warning(
            "**Authority details:** Completeness cannot be concluded from "
            "the current extraction."
        )

    if deadline.response_deadline is not None:
        st.write(
            f"**Response deadline:** {deadline.response_deadline} "
            f"({_friendly_enum(deadline.deadline_status)})"
        )
        if deadline.days_remaining is not None:
            st.caption(f"{deadline.days_remaining} day(s) remaining.")
    else:
        st.warning(
            "Exact response deadline is not available from verified inputs. "
            "Dwaar will not assume a service/receipt date."
        )
    if deadline.hearing_date is not None:
        st.write(
            f"**Hearing:** {deadline.hearing_date} "
            f"({_friendly_enum(deadline.hearing_status)})"
        )
    else:
        st.caption("No hearing date is currently available.")

    with st.expander("Technical details — preflight and deadline"):
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

    _render_legal_brief(classification, extraction)

    if result.arithmetic_results:
        st.header("Arithmetic results")
        st.dataframe(
            [
                {
                    "Calculation": _friendly_enum(item.calculation_type),
                    "Formula": item.formula,
                    "Status": _friendly_enum(item.status),
                    "Inputs": [str(value) for value in item.operand_values],
                    "Result": _display(item.result),
                    "Currency": item.currency,
                }
                for item in result.arithmetic_results
            ],
            hide_index=True,
        )
        with st.expander("Technical details — arithmetic"):
            st.dataframe(
                [
                    {
                        "calculation_type": item.calculation_type.value,
                        "formula": item.formula,
                        "status": item.status.value,
                        "operand_values": [
                            str(value) for value in item.operand_values
                        ],
                        "result": _display(item.result),
                        "currency": item.currency,
                        "source_fact_ids": item.source_fact_ids,
                    }
                    for item in result.arithmetic_results
                ],
                hide_index=True,
            )

    st.header("Validation status")
    if validation.overall_status is ValidationStatus.PASS:
        st.write("Validation checks passed for the current analysis state.")
    elif validation.overall_status is ValidationStatus.WARNING:
        st.warning(
            "The analysis can continue, but one or more items require "
            "professional attention."
        )
    else:
        st.warning(
            "The current analysis is not ready for specialist drafting."
        )
    st.caption(
        "Drafting: " + _friendly_enum(validation.draft_eligibility)
    )
    _render_checks(validation.checks)
    with st.expander("Technical details — validation"):
        st.write(
            {
                "overall_status": validation.overall_status.value,
                "draft_eligibility": validation.draft_eligibility.value,
            }
        )
        _render_checks(validation.checks, technical=True)

    st.header("Unresolved requirements")
    if draft.unresolved_requirements:
        st.dataframe(
            [
                {
                    "Requirement": item.requirement_text,
                    "Status": _friendly_enum(item.status),
                }
                for item in draft.unresolved_requirements
            ],
            hide_index=True,
        )
        with st.expander("Technical details — unresolved requirements"):
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
                    "Evidence needed": item.requirement_text,
                    "Status": _friendly_enum(item.status),
                }
                for item in draft.evidence_checklist
            ],
            hide_index=True,
        )
        with st.expander("Technical details — evidence checklist"):
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
                    "Review": _friendly_enum(item.level),
                    "Reason": item.reason,
                    "Mandatory": item.mandatory,
                }
                for item in draft.review_requirements
            ],
            hide_index=True,
        )
        with st.expander("Technical details — review requirements"):
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
        if _classification_failed_for_display(result):
            st.error(triage.message)
        else:
            st.write(triage.message)
        with st.expander("Technical details — triage"):
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
        if _classification_failed_for_display(result):
            st.warning(
                "Drafting is unavailable because notice classification did "
                "not complete successfully."
            )
        elif classification.support_level.value == "triage_only":
            st.warning(
                "Specialist drafting is not available for this triage-only "
                "notice workflow."
            )
        elif draft.status.value == "failed":
            st.warning(
                "Specialist drafting could not be completed. Review the "
                "analysis state and retry when the blocking issue is resolved."
            )
        else:
            st.warning(
                "Specialist drafting is blocked by the current validation "
                "or workflow state."
            )
        with st.expander("Technical details — drafting"):
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
                _render_checks(draft.post_validation.checks, technical=True)


_NOTICE_KEY = "_dwaar_notice_analysis_key"
_NOTICE_RESULT = "_dwaar_notice_analysis_result"
_NOTICE_PAGES = "_dwaar_notice_document_pages"
_NOTICE_RAW_TEXT = "_dwaar_notice_raw_text"

_EVIDENCE_KEY = "_dwaar_evidence_workspace_key"
_EVIDENCE_INTAKE = "_dwaar_evidence_intake_result"
_EVIDENCE_REVIEWS = "_dwaar_evidence_reviews"
_ACTIVE_FIRM_KEY = "_dwaar_active_firm_id"
_SAVED_INTAKES = "_dwaar_saved_intake_cases"
_OPENED_CASE_ID = "_dwaar_opened_case_id"
_OPENED_CASE_ANALYSIS = "_dwaar_opened_case_analysis"
_OPENED_SNAPSHOT_ID = "_dwaar_opened_snapshot_id"
_OPENED_SNAPSHOT = "_dwaar_opened_snapshot"
_FOCUSED_CASE_ID = "_dwaar_focused_case_id"


def _uploaded_bytes(uploaded_file):
    getvalue = getattr(uploaded_file, "getvalue", None)
    if callable(getvalue):
        return getvalue()
    return uploaded_file.read()


def _reset_evidence_workspace():
    for key in (_EVIDENCE_KEY, _EVIDENCE_INTAKE, _EVIDENCE_REVIEWS):
        st.session_state.pop(key, None)


def _reset_notice_workspace():
    for key in (
        _NOTICE_KEY,
        _NOTICE_RESULT,
        _NOTICE_PAGES,
        _NOTICE_RAW_TEXT,
        _SAVED_INTAKES,
        _OPENED_CASE_ID,
        _OPENED_CASE_ANALYSIS,
        _OPENED_SNAPSHOT_ID,
        _OPENED_SNAPSHOT,
        _FOCUSED_CASE_ID,
    ):
        st.session_state.pop(key, None)
    _reset_evidence_workspace()


def _select_active_firm(firms):
    if len(firms) == 1:
        return firms[0]

    labels = {
        f"{firm.display_name} ({firm.firm_id})": firm
        for firm in firms
    }
    selected_label = st.selectbox(
        "Firm",
        list(labels),
        key="dwaar_active_firm_selector",
    )
    return labels[selected_label]


def _require_app_access():
    user = getattr(st, "user", None)
    if user is None or not hasattr(user, "is_logged_in"):
        st.error(
            "Dwaar authentication is not configured on this deployment."
        )
        st.stop()

    if not user.is_logged_in:
        st.title("📋 Dwaar")
        st.write(
            "Sign in to access the GST notice workspace."
        )
        if st.button("Sign in", key="dwaar_sign_in"):
            st.login()
        st.stop()

    try:
        principal = principal_from_streamlit_user(user)
    except AuthenticationExpiredError:
        st.warning(
            "Your sign-in session has expired. Please sign in again."
        )
        if st.button("Sign in again", key="dwaar_sign_in_again"):
            st.logout()
        st.stop()
    except AuthenticationNotYetValidError:
        st.error(
            "Your sign-in session is not valid yet. Please sign in again."
        )
        if st.button("Sign in again", key="dwaar_sign_in_not_yet_valid"):
            st.logout()
        st.stop()
    except AuthenticationRequiredError:
        st.error(
            "Dwaar could not verify the authenticated identity."
        )
        if st.button("Sign in again", key="dwaar_sign_in_invalid"):
            st.logout()
        st.stop()

    try:
        db_path = database_path_from_environment()
        firms = load_available_firms_for_permissions(
            principal,
            db_path,
            {
                AccessPermission.CASE_CREATE,
                AccessPermission.CASE_READ,
            },
        )
    except RuntimeAccessConfigurationError:
        st.error(
            "Dwaar case storage is not configured on this deployment."
        )
        st.stop()
    except RuntimeAccessConsistencyError:
        st.error(
            "Dwaar access configuration is inconsistent. "
            "Please contact the administrator."
        )
        st.stop()
    except Exception:
        st.error(
            "Dwaar could not load your firm access."
        )
        st.stop()

    if not firms:
        st.error(
            "Your account is signed in but is not provisioned to access "
            "cases in Dwaar."
        )
        st.caption(f"Account ID: {principal.user_id}")
        if st.button("Log out", key="dwaar_logout_unprovisioned"):
            st.logout()
        st.stop()

    active_firm = _select_active_firm(firms)
    previous_firm_id = st.session_state.get(_ACTIVE_FIRM_KEY)
    if previous_firm_id != active_firm.firm_id:
        _reset_notice_workspace()
        st.session_state[_ACTIVE_FIRM_KEY] = active_firm.firm_id

    if st.button("Log out", key="dwaar_logout"):
        _reset_notice_workspace()
        st.session_state.pop(_ACTIVE_FIRM_KEY, None)
        st.logout()
        st.stop()

    st.caption(
        f"Active firm: {active_firm.display_name} "
        f"({active_firm.firm_id})"
    )
    return principal, active_firm


def _render_historical_snapshot(snapshot):
    payload = snapshot.payload
    metadata = snapshot.metadata

    st.subheader("Historical analysis snapshot")
    st.warning(
        "Historical record only. This snapshot is not the current live "
        "analysis and must not be used as a substitute for recomputation "
        "with the current engine."
    )
    st.write(
        {
            "snapshot_id": metadata.snapshot_id,
            "created_at": metadata.created_at.isoformat(),
            "schema_version": metadata.schema_version,
            "engine_version": metadata.engine_version,
            "source_document_id": metadata.source_document_id,
            "source_document_sha256": metadata.source_document_sha256,
        }
    )

    classification = payload["classification"]
    st.write(
        {
            "historical_notice_form": classification["notice_form"],
            "historical_proceeding_type": (
                classification["proceeding_type"]
            ),
            "historical_support_level": classification["support_level"],
            "historical_confidence": classification["confidence"],
        }
    )

    extraction = payload["extraction"]
    historical_facts = extraction["facts"]
    if historical_facts:
        st.dataframe(historical_facts, hide_index=True)
    else:
        st.write("Historical snapshot contains no extracted facts.")

    deadline = payload["deadline"]
    st.write(
        {
            "historical_response_deadline": deadline["response_deadline"],
            "historical_deadline_status": deadline["deadline_status"],
            "historical_days_remaining": deadline["days_remaining"],
            "historical_hearing_date": deadline["hearing_date"],
            "historical_hearing_status": deadline["hearing_status"],
        }
    )

    validation = payload["validation"]
    st.write(
        {
            "historical_validation_status": validation["overall_status"],
            "historical_draft_eligibility": (
                validation["draft_eligibility"]
            ),
        }
    )

    draft = payload["draft"]
    st.write(
        {
            "historical_draft_status": draft["status"],
            "historical_draft_eligibility": (
                draft["draft_eligibility"]
            ),
        }
    )
    if draft["sections"]:
        st.caption(
            "Historical draft text below is preserved for audit/history "
            "only."
        )
        for section in draft["sections"]:
            st.subheader(
                "Historical — " + section["title"]
            )
            st.markdown(section["rendered_text"])


def _render_snapshot_history(
    principal,
    active_firm,
    reopened,
):
    st.header("Analysis history")
    try:
        snapshot_service = build_authorized_analysis_snapshot_service()
        history = snapshot_service.list_snapshot_history(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Analysis history storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view analysis "
            "history for this case."
        )
        return
    except Exception:
        st.error("Analysis history could not be loaded.")
        return

    if AccessPermission.CASE_UPDATE in active_firm.permissions:
        if st.button(
            "Save current analysis snapshot",
            key=f"save_snapshot_{reopened.case.case_id}",
        ):
            try:
                saved = snapshot_service.save_current_analysis(
                    principal,
                    active_firm.firm_id,
                    case_id=reopened.case.case_id,
                    analysis=reopened.analysis,
                    created_at=datetime.now(timezone.utc),
                )
            except PermissionError:
                st.error(
                    "Your account is no longer authorized to save "
                    "analysis history for this case."
                )
            except Exception:
                st.error("The analysis snapshot could not be saved.")
            else:
                st.write(
                    {
                        "saved_snapshot_id": saved.snapshot_id,
                        "engine_version": saved.engine_version,
                    }
                )
                try:
                    history = snapshot_service.list_snapshot_history(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                    )
                except Exception:
                    st.error(
                        "The snapshot was saved, but analysis history "
                        "could not be refreshed."
                    )
                    return

    if not history:
        st.write("No saved analysis snapshots yet.")
        return

    st.dataframe(
        [
            {
                "snapshot_id": item.snapshot_id,
                "created_at": item.created_at.isoformat(),
                "schema_version": item.schema_version,
                "engine_version": item.engine_version,
                "source_document_id": item.source_document_id,
            }
            for item in history
        ],
        hide_index=True,
    )

    labels = {
        (
            f"{item.created_at.isoformat()} — "
            f"{item.engine_version} — {item.snapshot_id}"
        ): item
        for item in history
    }
    selected_label = st.selectbox(
        "Historical snapshot",
        list(labels),
        key=f"snapshot_selector_{reopened.case.case_id}",
    )
    selected = labels[selected_label]

    st.subheader("Legal research history")
    try:
        legal_brief_service = build_authorized_legal_brief_service()
        legal_briefs = legal_brief_service.list_for_snapshot(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
            snapshot_id=selected.snapshot_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Legal research history storage is not fully configured on "
            "this deployment."
        )
        legal_briefs = None
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view legal research "
            "history for this case."
        )
        legal_briefs = None
    except Exception:
        st.error("Legal research history could not be loaded.")
        legal_briefs = None

    if legal_briefs is not None:
        if AccessPermission.CASE_UPDATE in active_firm.permissions:
            if st.button(
                "Save verified legal brief for snapshot",
                key=f"save_legal_brief_{selected.snapshot_id}",
            ):
                try:
                    saved_brief = legal_brief_service.save_for_snapshot(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        snapshot_id=selected.snapshot_id,
                        created_at=datetime.now(timezone.utc),
                    )
                except PermissionError:
                    st.error(
                        "Your account is no longer authorized to save legal "
                        "research history for this case."
                    )
                except ValueError as error:
                    st.error(str(error))
                except Exception:
                    st.error("The verified legal brief could not be saved.")
                else:
                    st.write(
                        {
                            "saved_legal_brief_id": (
                                saved_brief.legal_brief_id
                            ),
                            "catalog_version": saved_brief.catalog_version,
                            "legal_as_of_date": (
                                saved_brief.as_of_date.isoformat()
                            ),
                        }
                    )
                    try:
                        legal_briefs = legal_brief_service.list_for_snapshot(
                            principal,
                            active_firm.firm_id,
                            case_id=reopened.case.case_id,
                            snapshot_id=selected.snapshot_id,
                        )
                    except Exception:
                        st.error(
                            "The legal brief was saved, but legal research "
                            "history could not be refreshed."
                        )
                        legal_briefs = None

        if legal_briefs:
            st.dataframe(
                [
                    {
                        "legal_brief_id": item.legal_brief_id,
                        "created_at": item.created_at.isoformat(),
                        "catalog_version": item.catalog_version,
                        "as_of_date": item.as_of_date.isoformat(),
                        "proceeding_type": item.proceeding_type.value,
                    }
                    for item in legal_briefs
                ],
                hide_index=True,
            )
            brief_labels = {
                (
                    f"{item.created_at.isoformat()} — "
                    f"{item.catalog_version} — {item.legal_brief_id}"
                ): item
                for item in legal_briefs
            }
            brief_label = st.selectbox(
                "Saved legal brief",
                list(brief_labels),
                key=f"legal_brief_selector_{selected.snapshot_id}",
            )
            selected_brief = brief_labels[brief_label]
            if st.button(
                "View saved legal brief",
                key=f"view_legal_brief_{selected_brief.legal_brief_id}",
            ):
                try:
                    loaded_brief = legal_brief_service.load(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        legal_brief_id=selected_brief.legal_brief_id,
                    )
                except PermissionError:
                    st.error(
                        "Your account is no longer authorized to view this "
                        "legal brief."
                    )
                except LookupError:
                    st.error(
                        "The selected legal brief is no longer available."
                    )
                except Exception:
                    st.error("The saved legal brief could not be loaded.")
                else:
                    st.caption(
                        "Historical verified legal research. Preserved for "
                        "audit/history; it does not update with the current "
                        "catalog."
                    )
                    historical_questions = loaded_brief.payload.get(
                        "questions"
                    )
                    if historical_questions is not None:
                        st.subheader(
                            "Historical legal research questions"
                        )
                        if historical_questions:
                            st.dataframe(
                                historical_questions,
                                hide_index=True,
                            )
                        else:
                            st.write(
                                "No legal-question state was preserved in "
                                "this v2 brief."
                            )
                    else:
                        st.caption(
                            "This v1 legal brief predates preserved legal-"
                            "question state. Its original law/source payload "
                            "is shown without reconstructing missing history."
                        )

                    if loaded_brief.payload["matches"]:
                        st.dataframe(
                            loaded_brief.payload["matches"],
                            hide_index=True,
                        )
                    else:
                        st.write(
                            "No verified legal proposition was preserved."
                        )
                    if loaded_brief.payload["unresolved_topics"]:
                        st.warning(
                            "CA legal research remained required for: "
                            + ", ".join(
                                loaded_brief.payload[
                                    "unresolved_topics"
                                ]
                            )
                        )
        elif legal_briefs == []:
            st.write(
                "No saved legal brief for this analysis snapshot yet."
            )

    if st.button(
        "View historical snapshot",
        key=f"view_snapshot_{selected.snapshot_id}",
    ):
        try:
            loaded = snapshot_service.load_snapshot(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
                snapshot_id=selected.snapshot_id,
            )
        except PermissionError:
            st.error(
                "Your account is no longer authorized to view this "
                "analysis snapshot."
            )
            return
        except LookupError:
            st.error("The selected analysis snapshot is no longer available.")
            return
        except Exception:
            st.error("The historical analysis snapshot could not be loaded.")
            return
        st.session_state[_OPENED_SNAPSHOT_ID] = selected.snapshot_id
        st.session_state[_OPENED_SNAPSHOT] = loaded

    if st.session_state.get(_OPENED_SNAPSHOT_ID) != selected.snapshot_id:
        return

    loaded = st.session_state.get(_OPENED_SNAPSHOT)
    if loaded is None:
        return
    _render_historical_snapshot(loaded)


def _render_draft_work_product_workspace(
    principal,
    active_firm,
    reopened,
):
    st.header("Draft work product")
    st.caption(
        "Draft content is stored as immutable encrypted versions. "
        "Generated baselines are bound to saved analysis snapshots; "
        "professional edits create new versions. Approval does not "
        "record filing."
    )

    try:
        draft_service = build_authorized_draft_work_product_service()
        versions = draft_service.list_versions(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Draft work-product storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view draft history "
            "for this case."
        )
        return
    except Exception:
        st.error("Draft work-product history could not be loaded.")
        return

    if versions:
        st.dataframe(
            [
                {
                    "draft_version_id": item.draft_version_id,
                    "version_number": item.version_number,
                    "source_snapshot_id": item.source_snapshot_id,
                    "parent_draft_version_id": _display(
                        item.parent_draft_version_id
                    ),
                    "generated_baseline": item.generated_baseline,
                    "review_status": item.review_status.value,
                    "created_at": item.created_at.isoformat(),
                    "created_by": item.created_by,
                    "reviewed_at": _display(item.reviewed_at),
                    "reviewed_by": _display(item.reviewed_by),
                    "approved_at": _display(item.approved_at),
                    "approved_by": _display(item.approved_by),
                }
                for item in versions
            ],
            hide_index=True,
        )
    else:
        st.write("No durable draft work-product versions yet.")

    if AccessPermission.CASE_UPDATE in active_firm.permissions:
        try:
            snapshot_service = build_authorized_analysis_snapshot_service()
            snapshots = snapshot_service.list_snapshot_history(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
            )
        except RuntimePersistenceConfigurationError:
            st.error(
                "Analysis history storage is not fully configured on this "
                "deployment."
            )
            return
        except PermissionError:
            st.error(
                "Your account is no longer authorized to use analysis "
                "history for draft creation."
            )
            return
        except Exception:
            st.error(
                "Analysis history could not be loaded for draft creation."
            )
            return

        if snapshots:
            snapshot_labels = {
                (
                    f"{item.created_at.isoformat()} — "
                    f"{item.engine_version} — {item.snapshot_id}"
                ): item
                for item in reversed(snapshots)
            }
            selected_snapshot_label = st.selectbox(
                "Draft baseline analysis snapshot",
                list(snapshot_labels),
                key=f"draft_baseline_snapshot_{reopened.case.case_id}",
            )
            selected_snapshot = snapshot_labels[
                selected_snapshot_label
            ]
            already_seeded = any(
                item.generated_baseline
                and item.source_snapshot_id
                == selected_snapshot.snapshot_id
                for item in versions
            )
            if already_seeded:
                st.caption(
                    "This analysis snapshot already has a generated "
                    "draft baseline."
                )
            elif st.button(
                "Create generated draft baseline",
                key=(
                    f"create_draft_baseline_"
                    f"{reopened.case.case_id}_"
                    f"{selected_snapshot.snapshot_id}"
                ),
            ):
                try:
                    created = draft_service.create_generated_baseline(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        snapshot_id=selected_snapshot.snapshot_id,
                        created_at=datetime.now(timezone.utc),
                    )
                except ValueError:
                    st.error(
                        "The selected snapshot cannot seed a professional "
                        "draft baseline. Its generated draft may be absent, "
                        "failed, or not post-validated."
                    )
                except PermissionError:
                    st.error(
                        "Your account is no longer authorized to create "
                        "draft versions for this case."
                    )
                except Exception:
                    st.error(
                        "The generated draft baseline could not be saved."
                    )
                else:
                    versions = draft_service.list_versions(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                    )
                    st.write(
                        {
                            "created_draft_version_id": (
                                created.draft_version_id
                            ),
                            "version_number": created.version_number,
                            "source_snapshot_id": (
                                created.source_snapshot_id
                            ),
                        }
                    )
        else:
            st.warning(
                "Save an analysis snapshot before creating a durable "
                "draft work product."
            )

    if not versions:
        return

    labels = {
        (
            f"v{item.version_number} — "
            f"{item.review_status.value} — {item.draft_version_id}"
        ): item
        for item in reversed(versions)
    }
    selected_label = st.selectbox(
        "Draft version",
        list(labels),
        key=f"draft_version_selector_{reopened.case.case_id}",
    )
    selected = labels[selected_label]

    try:
        loaded = draft_service.load_version(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
            draft_version_id=selected.draft_version_id,
        )
    except PermissionError:
        st.error(
            "Your account is no longer authorized to read this draft "
            "version."
        )
        return
    except LookupError:
        st.error("The selected draft version is no longer available.")
        return
    except Exception:
        st.error("The selected draft version could not be loaded.")
        return

    st.write(
        {
            "draft_version_id": selected.draft_version_id,
            "version_number": selected.version_number,
            "source_snapshot_id": selected.source_snapshot_id,
            "review_status": selected.review_status.value,
            "content_sha256": selected.content_sha256,
        }
    )

    latest = versions[-1]
    is_latest = latest.draft_version_id == selected.draft_version_id
    draft_text = loaded.payload["draft_text"]

    if AccessPermission.CASE_UPDATE in active_firm.permissions and is_latest:
        edited_text = st.text_area(
            "Professional draft text",
            value=draft_text,
            height=420,
            key=f"draft_editor_{selected.draft_version_id}",
        )
        if st.button(
            "Save edited draft as new version",
            key=f"save_draft_edit_{selected.draft_version_id}",
        ):
            try:
                created = draft_service.create_edited_version(
                    principal,
                    active_firm.firm_id,
                    case_id=reopened.case.case_id,
                    parent_draft_version_id=selected.draft_version_id,
                    draft_text=edited_text,
                    created_at=datetime.now(timezone.utc),
                )
            except (ValueError, TypeError) as error:
                st.error(str(error))
            except PermissionError:
                st.error(
                    "Your account is no longer authorized to create "
                    "draft versions for this case."
                )
            except Exception:
                st.error("The edited draft version could not be saved.")
            else:
                st.write(
                    {
                        "created_draft_version_id": (
                            created.draft_version_id
                        ),
                        "version_number": created.version_number,
                        "parent_draft_version_id": (
                            created.parent_draft_version_id
                        ),
                        "review_status": created.review_status.value,
                    }
                )
    else:
        st.text_area(
            "Professional draft text",
            value=draft_text,
            height=420,
            disabled=True,
            key=f"draft_view_{selected.draft_version_id}",
        )
        if not is_latest:
            st.caption(
                "Historical draft versions are immutable. Select the "
                "latest version to create a new edit."
            )

    if AccessPermission.DRAFT_REVIEW in active_firm.permissions:
        target_status = None
        action_label = None
        if selected.review_status is DraftReviewStatus.WORKING:
            target_status = DraftReviewStatus.REVIEWED
            action_label = "Mark draft reviewed"
        elif selected.review_status is DraftReviewStatus.REVIEWED:
            target_status = DraftReviewStatus.APPROVED
            action_label = "Approve draft"

        if target_status is not None and st.button(
            action_label,
            key=(
                f"draft_review_{selected.draft_version_id}_"
                f"{target_status.value}"
            ),
        ):
            try:
                updated = draft_service.transition_review(
                    principal,
                    active_firm.firm_id,
                    case_id=reopened.case.case_id,
                    draft_version_id=selected.draft_version_id,
                    target_status=target_status,
                    occurred_at=datetime.now(timezone.utc),
                )
            except (ValueError, TypeError) as error:
                st.error(str(error))
            except PermissionError:
                st.error(
                    "Your account is no longer authorized to review this "
                    "draft."
                )
            except Exception:
                st.error("The draft review state could not be saved.")
            else:
                selected = updated
                st.write(
                    {
                        "reviewed_draft_version_id": (
                            updated.draft_version_id
                        ),
                        "review_status": updated.review_status.value,
                    }
                )

    if selected.review_status in {
        DraftReviewStatus.REVIEWED,
        DraftReviewStatus.APPROVED,
    }:
        try:
            docx_bytes = draft_service.export_version_docx(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
                draft_version_id=selected.draft_version_id,
            )
        except PermissionError:
            st.error(
                "Your account is no longer authorized to export this draft."
            )
        except Exception:
            st.error("The reviewed draft DOCX could not be prepared.")
        else:
            st.download_button(
                "Download reviewed draft DOCX",
                data=docx_bytes,
                file_name=(
                    f"{reopened.case.case_id}-"
                    f"draft-v{selected.version_number}.docx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                key=f"download_draft_{selected.draft_version_id}",
            )


def _render_filing_workspace(
    principal,
    active_firm,
    reopened,
):
    st.header("Filing & acknowledgement")
    st.caption(
        "Filing records describe what was actually submitted to the portal. "
        "The selected APPROVED draft is recorded as the filing basis; Dwaar "
        "does not claim the uploaded filed PDF is textually identical to "
        "that draft."
    )

    try:
        filing_service = build_authorized_filing_service()
        filings = filing_service.list_filings(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Filing storage is not fully configured on this deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view filing history "
            "for this case."
        )
        return
    except Exception:
        st.error("Filing history could not be loaded.")
        return

    if filings:
        st.dataframe(
            [
                {
                    "filing_id": item.filing_id,
                    "filing_reference": item.filing_reference,
                    "approved_draft_version_id": (
                        item.approved_draft_version_id
                    ),
                    "filed_response_document_id": (
                        item.filed_response_document_id
                    ),
                    "acknowledgement_document_id": _display(
                        item.acknowledgement_document_id
                    ),
                    "filed_at": item.filed_at.isoformat(),
                    "filed_by": item.filed_by,
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in filings
            ],
            hide_index=True,
        )
    else:
        st.write("No filing records yet.")

    can_record = (
        AccessPermission.FILING_RECORD in active_firm.permissions
        and AccessPermission.DOCUMENT_ADD in active_firm.permissions
    )
    if not can_record:
        st.caption(
            "Recording filings/acknowledgements requires FILING_RECORD "
            "and DOCUMENT_ADD."
        )
        return

    if reopened.case.status not in {
        CaseStatus.DRAFT_REVIEW,
        CaseStatus.FILED,
        CaseStatus.HEARING,
    }:
        st.caption(
            "The current case status does not permit recording a filing."
        )
    else:
        try:
            draft_service = build_authorized_draft_work_product_service()
            draft_versions = draft_service.list_versions(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
            )
        except Exception:
            st.error(
                "Approved draft history could not be loaded for filing."
            )
            return

        approved_versions = [
            item
            for item in draft_versions
            if item.review_status is DraftReviewStatus.APPROVED
        ]
        if not approved_versions:
            st.warning(
                "An APPROVED immutable draft version is required before "
                "a filing can be recorded."
            )
        else:
            draft_labels = {
                (
                    f"v{item.version_number} — "
                    f"{item.draft_version_id}"
                ): item
                for item in reversed(approved_versions)
            }
            draft_label = st.selectbox(
                "Approved filing-basis draft",
                list(draft_labels),
                key=f"filing_draft_{reopened.case.case_id}",
            )
            selected_draft = draft_labels[draft_label]

            filing_reference = st.text_input(
                "Portal / filing reference",
                key=f"filing_reference_{reopened.case.case_id}",
            )
            filed_at_text = st.text_input(
                "Actually filed at (ISO 8601 with timezone)",
                value=datetime.now(timezone.utc).isoformat(
                    timespec="minutes"
                ),
                key=f"filing_time_{reopened.case.case_id}",
            )
            filed_response = st.file_uploader(
                "Upload the actual filed response PDF",
                type="pdf",
                key=f"filed_response_{reopened.case.case_id}",
            )
            acknowledgement = st.file_uploader(
                "Upload acknowledgement PDF (optional)",
                type="pdf",
                key=f"filing_ack_{reopened.case.case_id}",
            )

            if st.button(
                "Record filing",
                key=f"record_filing_{reopened.case.case_id}",
            ):
                if filed_response is None:
                    st.error(
                        "Upload the actual filed response PDF before "
                        "recording the filing."
                    )
                else:
                    try:
                        filed_at = datetime.fromisoformat(
                            filed_at_text.strip()
                        )
                        if filed_at.tzinfo is None:
                            raise ValueError
                    except (TypeError, ValueError):
                        st.error(
                            "Filed time must be ISO 8601 and include a "
                            "timezone offset."
                        )
                    else:
                        recorded_at = datetime.now(timezone.utc)
                        try:
                            saved = filing_service.record_filing(
                                principal,
                                active_firm.firm_id,
                                case_id=reopened.case.case_id,
                                approved_draft_version_id=(
                                    selected_draft.draft_version_id
                                ),
                                filing_reference=filing_reference,
                                filed_response_filename=(
                                    filed_response.name
                                ),
                                filed_response_payload=_uploaded_bytes(
                                    filed_response
                                ),
                                acknowledgement_filename=(
                                    None
                                    if acknowledgement is None
                                    else acknowledgement.name
                                ),
                                acknowledgement_payload=(
                                    None
                                    if acknowledgement is None
                                    else _uploaded_bytes(
                                        acknowledgement
                                    )
                                ),
                                filed_at=filed_at,
                                recorded_at=recorded_at,
                            )
                        except (ValueError, TypeError) as error:
                            st.error(str(error))
                        except PermissionError:
                            st.error(
                                "Your account is no longer authorized to "
                                "record this filing."
                            )
                        except Exception:
                            st.error("The filing could not be recorded.")
                        else:
                            filings = filing_service.list_filings(
                                principal,
                                active_firm.firm_id,
                                case_id=reopened.case.case_id,
                            )
                            st.write(
                                {
                                    "recorded_filing_id": (
                                        saved.filing_id
                                    ),
                                    "filing_reference": (
                                        saved.filing_reference
                                    ),
                                    "filed_response_document_id": (
                                        saved.filed_response_document_id
                                    ),
                                    "acknowledgement_document_id": (
                                        saved.acknowledgement_document_id
                                    ),
                                }
                            )

    missing_ack = [
        item
        for item in filings
        if item.acknowledgement_document_id is None
    ]
    if not missing_ack:
        return

    st.subheader("Attach acknowledgement later")
    filing_labels = {
        (
            f"{item.filing_reference} — "
            f"{item.filing_id}"
        ): item
        for item in missing_ack
    }
    selected_label = st.selectbox(
        "Filing awaiting acknowledgement",
        list(filing_labels),
        key=f"filing_ack_target_{reopened.case.case_id}",
    )
    selected_filing = filing_labels[selected_label]
    later_ack = st.file_uploader(
        "Upload acknowledgement PDF for selected filing",
        type="pdf",
        key=f"late_filing_ack_{selected_filing.filing_id}",
    )
    if st.button(
        "Attach acknowledgement",
        key=f"attach_filing_ack_{selected_filing.filing_id}",
    ):
        if later_ack is None:
            st.error("Upload an acknowledgement PDF first.")
            return
        try:
            updated = filing_service.attach_acknowledgement(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
                filing_id=selected_filing.filing_id,
                acknowledgement_filename=later_ack.name,
                acknowledgement_payload=_uploaded_bytes(later_ack),
                added_at=datetime.now(timezone.utc),
            )
        except (ValueError, TypeError) as error:
            st.error(str(error))
        except PermissionError:
            st.error(
                "Your account is no longer authorized to attach this "
                "acknowledgement."
            )
        except Exception:
            st.error("The acknowledgement could not be attached.")
        else:
            st.write(
                {
                    "updated_filing_id": updated.filing_id,
                    "acknowledgement_document_id": (
                        updated.acknowledgement_document_id
                    ),
                }
            )


def _render_persisted_evidence_workspace(
    principal,
    active_firm,
    reopened,
    case_service,
):
    st.header("Persisted supporting evidence")
    st.caption(
        "Supporting PDFs are encrypted case documents. Durable human "
        "Confirm/Reject decisions are bound to a selected saved analysis "
        "snapshot so their checklist context remains historically stable."
    )

    try:
        attached = [
            item
            for item in case_service.list_documents(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
            )
            if item.kind is CaseDocumentKind.SUPPORTING_EVIDENCE
        ]
    except PermissionError:
        st.error(
            "Your account is no longer authorized to read supporting "
            "evidence for this case."
        )
        return
    except Exception:
        st.error("Supporting evidence attachments could not be loaded.")
        return

    if attached:
        st.dataframe(
            [
                {
                    "document_id": item.document_id,
                    "filename": item.original_filename,
                    "byte_size": item.byte_size,
                    "sha256": item.sha256_hex,
                    "created_at": item.created_at.isoformat(),
                }
                for item in attached
            ],
            hide_index=True,
        )
    else:
        st.write("No supporting evidence attached yet.")

    if AccessPermission.DOCUMENT_ADD in active_firm.permissions:
        uploads = st.file_uploader(
            "Attach supporting evidence PDFs",
            type="pdf",
            accept_multiple_files=True,
            key=f"persisted_evidence_uploads_{reopened.case.case_id}",
        )
        if uploads and st.button(
            "Attach selected evidence",
            key=f"attach_evidence_{reopened.case.case_id}",
        ):
            successes = []
            failures = []
            for uploaded_file in uploads:
                try:
                    saved = add_supporting_evidence_pdf(
                        case_service,
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        filename=uploaded_file.name,
                        payload=_uploaded_bytes(uploaded_file),
                        created_at=datetime.now(timezone.utc),
                    )
                except Exception:
                    failures.append(uploaded_file.name)
                else:
                    successes.append(saved)

            _reset_evidence_workspace()
            if successes:
                st.write(
                    {
                        "attached_document_ids": [
                            item.document_id for item in successes
                        ]
                    }
                )
            if failures:
                st.error(
                    "Some supporting evidence files could not be attached: "
                    + ", ".join(failures)
                )
            return
    else:
        st.caption(
            "Attaching supporting evidence requires DOCUMENT_ADD."
        )

    if not attached:
        return

    if AccessPermission.EVIDENCE_REVIEW not in active_firm.permissions:
        st.caption(
            "Evidence matching/review requires EVIDENCE_REVIEW."
        )
        return

    try:
        snapshot_service = build_authorized_analysis_snapshot_service()
        review_service = build_authorized_evidence_review_service()
        snapshot_history = snapshot_service.list_snapshot_history(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Evidence review storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to review evidence "
            "for this case."
        )
        return
    except Exception:
        st.error("Evidence review history could not be loaded.")
        return

    if not snapshot_history:
        st.warning(
            "Save the current analysis as an analysis snapshot before "
            "creating durable evidence review decisions."
        )
        return

    snapshot_labels = {
        (
            f"{item.created_at.isoformat()} — "
            f"{item.engine_version} — {item.snapshot_id}"
        ): item
        for item in reversed(snapshot_history)
    }
    snapshot_label = st.selectbox(
        "Evidence review snapshot",
        list(snapshot_labels),
        key=f"evidence_review_snapshot_{reopened.case.case_id}",
    )
    selected_snapshot = snapshot_labels[snapshot_label]

    try:
        snapshot_checklist = review_service.snapshot_evidence_checklist(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
            snapshot_id=selected_snapshot.snapshot_id,
        )
        durable_reviews = review_service.list_reviews(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
            snapshot_id=selected_snapshot.snapshot_id,
        )
    except PermissionError:
        st.error(
            "Your account is no longer authorized to review evidence "
            "for this snapshot."
        )
        return
    except Exception:
        st.error("The selected evidence review context could not be loaded.")
        return

    st.write(
        {
            "review_snapshot_id": selected_snapshot.snapshot_id,
            "review_engine_version": selected_snapshot.engine_version,
            "review_checklist_items": len(snapshot_checklist),
        }
    )

    context_prefix = (
        f"persisted:{reopened.case.case_id}:"
        f"{selected_snapshot.snapshot_id}:"
    )
    existing_workspace_key = st.session_state.get(_EVIDENCE_KEY)
    if (
        existing_workspace_key is not None
        and not str(existing_workspace_key).startswith(context_prefix)
    ):
        _reset_evidence_workspace()

    analyze_key = (
        f"analyze_persisted_evidence_{reopened.case.case_id}_"
        f"{selected_snapshot.snapshot_id}"
    )
    if st.button(
        "Analyze attached evidence for selected snapshot",
        key=analyze_key,
    ):
        try:
            evidence_service = build_authorized_evidence_workspace_service()
            with st.spinner(
                "Matching persisted evidence to snapshot checklist..."
            ):
                workspace = evidence_service.analyze_case_evidence(
                    principal,
                    active_firm.firm_id,
                    case_id=reopened.case.case_id,
                    evidence_checklist=snapshot_checklist,
                )
        except RuntimePersistenceConfigurationError:
            st.error(
                "Evidence storage is not fully configured on this deployment."
            )
            return
        except PermissionError:
            st.error(
                "Your account is no longer authorized to review evidence "
                "for this case."
            )
            return
        except Exception:
            st.error("Persisted evidence could not be analyzed.")
            return

        st.session_state[_EVIDENCE_KEY] = (
            context_prefix
            + ":".join(
                item.document_id
                for item in workspace.document_refs
            )
        )
        st.session_state[_EVIDENCE_INTAKE] = workspace.intake_result
        st.session_state[_EVIDENCE_REVIEWS] = []

    intake_result = st.session_state.get(_EVIDENCE_INTAKE)
    if intake_result is not None:
        st.write(
            {
                "evidence_intake_status": intake_result.status.value,
                "candidate_count": len(intake_result.candidates),
                "rejected_candidate_count": (
                    intake_result.rejected_candidate_count
                ),
            }
        )

        if intake_result.candidates:
            st.dataframe(
                [
                    {
                        "candidate_id": candidate.candidate_id,
                        "evidence_id": candidate.evidence_id,
                        "document_id": candidate.document_id,
                        "source_page": candidate.source_page,
                        "source_text": candidate.source_text,
                        "source_origin": candidate.source_origin.value,
                        "source_verification": (
                            candidate.source_verification.value
                        ),
                        "review_status": candidate.review_status.value,
                    }
                    for candidate in intake_result.candidates
                ],
                hide_index=True,
            )
        else:
            st.write(
                "No source-grounded evidence candidates were proposed."
            )

        workspace_key = st.session_state.get(
            _EVIDENCE_KEY,
            context_prefix,
        )
        for candidate in intake_result.candidates:
            st.subheader(f"Review {candidate.candidate_id}")
            st.write(
                {
                    "evidence_id": candidate.evidence_id,
                    "document_id": candidate.document_id,
                    "source_page": candidate.source_page,
                    "source_text": candidate.source_text,
                    "source_origin": candidate.source_origin.value,
                    "source_verification": (
                        candidate.source_verification.value
                    ),
                }
            )
            note = st.text_input(
                "Reviewer note (optional)",
                key=(
                    f"durable_evidence_note_{workspace_key}_"
                    f"{candidate.candidate_id}"
                ),
            )

            decision = None
            if st.button(
                f"Confirm {candidate.candidate_id}",
                key=(
                    f"durable_confirm_{workspace_key}_"
                    f"{candidate.candidate_id}"
                ),
            ):
                decision = EvidenceReviewStatus.CONFIRMED
            elif st.button(
                f"Reject {candidate.candidate_id}",
                key=(
                    f"durable_reject_{workspace_key}_"
                    f"{candidate.candidate_id}"
                ),
            ):
                decision = EvidenceReviewStatus.REJECTED

            if decision is not None:
                try:
                    saved_review = review_service.save_review(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        snapshot_id=selected_snapshot.snapshot_id,
                        candidate=candidate,
                        decision=decision,
                        reviewer_note=note,
                        reviewed_at=datetime.now(timezone.utc),
                    )
                except ValueError:
                    st.error(
                        "This evidence candidate is no longer valid for "
                        "the selected snapshot or persisted document."
                    )
                except PermissionError:
                    st.error(
                        "Your account is no longer authorized to save "
                        "this evidence review."
                    )
                except Exception:
                    st.error(
                        "This evidence review could not be saved. It may "
                        "already have been reviewed for this snapshot."
                    )
                else:
                    st.write(
                        {
                            "saved_evidence_review_id": (
                                saved_review.review_id
                            ),
                            "decision": saved_review.decision.value,
                            "snapshot_id": saved_review.snapshot_id,
                        }
                    )
                    durable_reviews = review_service.list_reviews(
                        principal,
                        active_firm.firm_id,
                        case_id=reopened.case.case_id,
                        snapshot_id=selected_snapshot.snapshot_id,
                    )

    st.subheader("Legal evidence readiness")
    st.caption(
        "This shows whether the closed supporting-evidence set for a legal "
        "research question has human-confirmed review records. It does not "
        "decide whether the legal condition or ITC claim is satisfied."
    )
    try:
        legal_evidence = review_service.legal_evidence_readiness(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
            snapshot_id=selected_snapshot.snapshot_id,
        )
    except ValueError:
        st.caption(
            "This snapshot predates or does not match the current closed "
            "legal-evidence requirement set."
        )
    except Exception:
        st.error("Legal evidence readiness could not be loaded.")
    else:
        if legal_evidence:
            st.dataframe(
                [
                    {
                        "question_id": item.question_id,
                        "status": item.status.value,
                        "required_evidence_ids": list(
                            item.required_evidence_ids
                        ),
                        "confirmed_evidence_ids": list(
                            item.confirmed_evidence_ids
                        ),
                        "missing_evidence_ids": list(
                            item.missing_evidence_ids
                        ),
                        "confirmed_review_ids": list(
                            item.confirmed_review_ids
                        ),
                    }
                    for item in legal_evidence
                ],
                hide_index=True,
            )
        else:
            st.write(
                "No closed legal-evidence readiness plan exists for this "
                "workflow yet."
            )

    st.subheader("Durable evidence review history")
    if not durable_reviews:
        st.write("No durable review decisions for this snapshot yet.")
        return

    st.dataframe(
        [
            {
                "review_id": item.review_id,
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "source_page": item.source_page,
                "decision": item.decision.value,
                "reviewed_at": item.reviewed_at.isoformat(),
                "reviewed_by": item.reviewed_by,
            }
            for item in durable_reviews
        ],
        hide_index=True,
    )

    review_labels = {
        (
            f"{item.reviewed_at.isoformat()} — "
            f"{item.decision.value} — {item.review_id}"
        ): item
        for item in durable_reviews
    }
    selected_review_label = st.selectbox(
        "Evidence review record",
        list(review_labels),
        key=(
            f"evidence_review_record_{reopened.case.case_id}_"
            f"{selected_snapshot.snapshot_id}"
        ),
    )
    selected_review = review_labels[selected_review_label]
    if st.button(
        "View encrypted review details",
        key=f"view_evidence_review_{selected_review.review_id}",
    ):
        try:
            loaded_review = review_service.load_review(
                principal,
                active_firm.firm_id,
                case_id=reopened.case.case_id,
                snapshot_id=selected_snapshot.snapshot_id,
                review_id=selected_review.review_id,
            )
        except Exception:
            st.error("The evidence review details could not be loaded.")
        else:
            st.write(
                {
                    "review_id": loaded_review.metadata.review_id,
                    "snapshot_id": loaded_review.metadata.snapshot_id,
                    "evidence_id": loaded_review.metadata.evidence_id,
                    "document_id": loaded_review.metadata.document_id,
                    "source_page": loaded_review.metadata.source_page,
                    "decision": loaded_review.metadata.decision.value,
                    "source_text": (
                        loaded_review.payload["candidate"]["source_text"]
                    ),
                    "source_origin": (
                        loaded_review.payload["candidate"]["source_origin"]
                    ),
                    "source_verification": (
                        loaded_review.payload["candidate"][
                            "source_verification"
                        ]
                    ),
                    "reviewer_note": _display(
                        loaded_review.payload["reviewer_note"]
                    ),
                    "reviewed_at": loaded_review.payload["reviewed_at"],
                    "reviewed_by": loaded_review.payload["reviewed_by"],
                }
            )


def _render_case_work_queue(principal, active_firm):
    if AccessPermission.CASE_READ not in active_firm.permissions:
        return

    st.header("Case work queue")
    try:
        service = build_authorized_case_service()
        workbench_service = build_authorized_professional_workbench_service()
        professional_queue = workbench_service.list_case_attention_queue(
            principal,
            active_firm.firm_id,
            today=date.today(),
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Durable case storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to read the case queue."
        )
        return
    except Exception:
        st.error("The case work queue could not be loaded.")
        return

    if not professional_queue:
        st.write("No saved cases in the work queue yet.")
        return

    st.caption(
        "Deadline ordering is preserved from the case work queue. "
        "Attention shows deterministic unresolved workflow state and its "
        "owning workspace; it is not a priority score or legal verdict."
    )
    st.dataframe(
        [
            {
                "Client": row.work_item.client_name,
                "Matter": row.work_item.title,
                "Status": _friendly_enum(row.work_item.status),
                "Deadline": _display(row.work_item.response_deadline),
                "Deadline state": _friendly_enum(
                    row.work_item.deadline_status
                ),
                "Days remaining": _display(row.work_item.days_remaining),
                "Assignee": _display(row.work_item.assigned_to),
                "Reviewer": _display(row.work_item.reviewer_id),
                "Needs attention": row.attention_count,
            }
            for row in professional_queue
        ],
        hide_index=True,
    )
    with st.expander("Technical details — work queue"):
        st.dataframe(
            [
                {
                    "case_id": row.work_item.case_id,
                    "status": row.work_item.status.value,
                    "deadline_status": row.work_item.deadline_status.value,
                    "attention_codes": [
                        code.value for code in row.attention_codes
                    ],
                    "attention_workspaces": [
                        workspace.value
                        for workspace in row.attention_workspaces
                    ],
                }
                for row in professional_queue
            ],
            hide_index=True,
        )

    labels = {
        (
            f"{row.work_item.deadline_status.value} — "
            f"{row.work_item.client_name} — "
            f"{row.work_item.title} — {row.work_item.case_id}"
        ): row
        for row in professional_queue
    }
    selected_label = st.selectbox(
        "Queue case",
        list(labels),
        key="dwaar_case_work_queue_selector",
    )
    selected_row = labels[selected_label]
    selected = selected_row.work_item

    if selected_row.attention_codes:
        st.write(
            "**Needs attention:** "
            + ", ".join(
                _friendly_enum(code)
                for code in selected_row.attention_codes
            )
        )
        st.caption(
            "Continue in: "
            + ", ".join(
                _friendly_enum(workspace)
                for workspace in selected_row.attention_workspaces
            )
        )
    else:
        st.caption(
            "No closed professional-attention condition is currently "
            "emitted for the selected case."
        )

    if st.button(
        "Focus queue case in Saved cases",
        key=f"focus_queue_case_{selected.case_id}",
    ):
        st.session_state[_FOCUSED_CASE_ID] = selected.case_id
        st.write("Case selected. Use **Open saved case** below.")
        with st.expander("Technical details — selected queue case"):
            st.write({"focused_case_id": selected.case_id})

    if AccessPermission.CASE_UPDATE not in active_firm.permissions:
        st.caption(
            "This access can view the work queue but cannot update case "
            "operations."
        )
        return

    if selected.status is CaseStatus.CLOSED:
        st.caption(
            "Closed cases are terminal. Operational edits are disabled."
        )
        return

    try:
        status_targets = service.allowed_case_status_targets(
            principal,
            active_firm.firm_id,
            case_id=selected.case_id,
        )
        assignable_users = service.list_assignable_user_ids(
            principal,
            active_firm.firm_id,
        )
    except PermissionError:
        st.error(
            "Your account is no longer authorized to update this case."
        )
        return
    except Exception:
        st.error("Case update options could not be loaded.")
        return

    status_labels = {
        status.value: status
        for status in status_targets
    }
    status_label = st.selectbox(
        "Operational status",
        list(status_labels),
        key=f"case_ops_status_{selected.case_id}",
    )
    target_status = status_labels[status_label]

    deadline_text = st.text_input(
        "Response deadline (YYYY-MM-DD, blank to clear)",
        value=(
            ""
            if selected.response_deadline is None
            else selected.response_deadline.isoformat()
        ),
        key=f"case_ops_deadline_{selected.case_id}",
    )

    member_labels = {"Unassigned": None}
    member_labels.update({user_id: user_id for user_id in assignable_users})
    assignee_default = (
        "Unassigned"
        if selected.assigned_to is None
        else selected.assigned_to
    )
    reviewer_default = (
        "Unassigned"
        if selected.reviewer_id is None
        else selected.reviewer_id
    )
    # Persisted historical identities may no longer be active/assignable.
    if assignee_default not in member_labels:
        member_labels[assignee_default] = selected.assigned_to
    if reviewer_default not in member_labels:
        member_labels[reviewer_default] = selected.reviewer_id

    assignee_label = st.selectbox(
        "Assignee",
        list(member_labels),
        index=list(member_labels).index(assignee_default),
        key=f"case_ops_assignee_{selected.case_id}",
    )
    reviewer_label = st.selectbox(
        "Reviewer",
        list(member_labels),
        index=list(member_labels).index(reviewer_default),
        key=f"case_ops_reviewer_{selected.case_id}",
    )

    if not st.button(
        "Save case operations",
        key=f"save_case_ops_{selected.case_id}",
    ):
        return

    try:
        normalized_deadline = (
            None
            if not deadline_text.strip()
            else date.fromisoformat(deadline_text.strip())
        )
    except ValueError:
        st.error(
            "Response deadline must use YYYY-MM-DD, or be left blank."
        )
        return

    try:
        updated = service.update_case_operations(
            principal,
            active_firm.firm_id,
            case_id=selected.case_id,
            status=target_status,
            response_deadline=normalized_deadline,
            assigned_to=member_labels[assignee_label],
            reviewer_id=member_labels[reviewer_label],
            updated_at=datetime.now(timezone.utc),
        )
    except (ValueError, TypeError) as error:
        st.error(str(error))
        return
    except LookupError:
        st.error("The selected case is no longer available.")
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to update this case."
        )
        return
    except Exception:
        st.error("The case operations update could not be saved.")
        return

    st.session_state[_FOCUSED_CASE_ID] = updated.case_id
    st.write(
        f"Case operations saved. Status: **{_friendly_enum(updated.status)}**."
    )
    st.caption(
        "Response deadline: "
        + _display(updated.response_deadline)
        + " · Assignee: "
        + _display(updated.assigned_to)
        + " · Reviewer: "
        + _display(updated.reviewer_id)
    )
    with st.expander("Technical details — case operations"):
        st.write({"updated_case_id": updated.case_id})


def _render_client_workspace(principal, active_firm):
    if AccessPermission.CASE_READ not in active_firm.permissions:
        return

    st.header("Client workspace")
    try:
        service = build_authorized_case_service()
        clients = service.list_clients(
            principal,
            active_firm.firm_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Durable case storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to read clients in "
            "this firm."
        )
        return
    except Exception:
        st.error("Client workspace could not be loaded.")
        return

    if not clients:
        st.write("No saved clients yet.")
        return

    labels = {
        f"{client.display_name} — {client.client_id}": client
        for client in clients
    }
    selected_label = st.selectbox(
        "Client",
        list(labels),
        key="dwaar_client_workspace_selector",
    )
    selected_client = labels[selected_label]

    try:
        workspace = service.get_client_workspace(
            principal,
            active_firm.firm_id,
            client_id=selected_client.client_id,
        )
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view this client."
        )
        return
    except LookupError:
        st.error("The selected client is no longer available.")
        return
    except Exception:
        st.error("Client history could not be loaded.")
        return

    st.write(f"**{workspace.client.display_name}**")
    st.caption(
        f"{len(workspace.registrations)} tax registration(s) · "
        f"{len(workspace.cases)} saved matter(s)"
    )
    with st.expander("Technical details — client"):
        st.write({"client_id": workspace.client.client_id})

    st.subheader("Tax registrations")
    if workspace.registrations:
        st.dataframe(
            [
                {
                    "Jurisdiction": item.jurisdiction,
                    "Identifier": item.identifier_type,
                    "Value": item.identifier_value,
                }
                for item in workspace.registrations
            ],
            hide_index=True,
        )
        with st.expander("Technical details — tax registrations"):
            st.dataframe(
                [
                    {
                        "registration_id": item.registration_id,
                        "identifier_value": item.identifier_value,
                    }
                    for item in workspace.registrations
                ],
                hide_index=True,
            )
    else:
        st.write("No tax registrations saved for this client.")

    st.subheader("Notice history")
    if not workspace.cases:
        st.write("No saved cases for this client yet.")
        return

    st.dataframe(
        [
            {
                "Matter": case.title,
                "Status": _friendly_enum(case.status),
                "Notice": _notice_form_label(case.notice_form),
                "Proceeding": _proceeding_label(case.proceeding_type),
                "Opened": case.opened_at.date().isoformat(),
                "Response deadline": _display(case.response_deadline),
            }
            for case in workspace.cases
        ],
        hide_index=True,
    )
    with st.expander("Technical details — client case history"):
        st.dataframe(
            [
                {
                    "case_id": case.case_id,
                    "registration_id": _display(case.registration_id),
                    "proceeding_type": case.proceeding_type.value,
                }
                for case in workspace.cases
            ],
            hide_index=True,
        )

    case_labels = {
        f"{case.title} — {case.case_id}": case
        for case in workspace.cases
    }
    selected_case_label = st.selectbox(
        "Client case",
        list(case_labels),
        key=f"dwaar_client_case_selector_{selected_client.client_id}",
    )
    selected_case = case_labels[selected_case_label]

    if st.button(
        "Focus this case in Saved cases",
        key=f"focus_client_case_{selected_case.case_id}",
    ):
        st.session_state[_FOCUSED_CASE_ID] = selected_case.case_id
        st.write("Case selected. Use **Open saved case** below.")
        with st.expander("Technical details — selected client case"):
            st.write({"focused_case_id": selected_case.case_id})


def _render_professional_case_attention(
    principal,
    active_firm,
    reopened,
):
    st.header("Case attention")
    try:
        workbench = build_authorized_professional_workbench_service()
        attention = workbench.get_case_attention(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Professional case workspace storage is not fully configured "
            "on this deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view professional "
            "case attention."
        )
        return
    except Exception:
        st.error("Professional case attention could not be loaded.")
        return

    if attention.items:
        st.dataframe(
            [
                {
                    "Attention": _friendly_enum(item.code),
                    "Continue in": _friendly_enum(item.code.workspace),
                    "What needs attention": item.message,
                }
                for item in attention.items
            ],
            hide_index=True,
        )
    else:
        st.write(
            "No operational attention item is currently identified by "
            "the deterministic workbench projection."
        )

    with st.expander("Technical details — case attention"):
        st.write(
            {
                "latest_snapshot_id": _display(
                    attention.latest_snapshot_id
                ),
                "latest_legal_brief_id": _display(
                    attention.latest_legal_brief_id
                ),
                "latest_draft_version_id": _display(
                    attention.latest_draft_version_id
                ),
                "latest_filing_id": _display(
                    attention.latest_filing_id
                ),
            }
        )
        if attention.items:
            st.dataframe(
                [
                    {
                        "attention_code": item.code.value,
                        "workspace": item.code.workspace.value,
                        "related_id": _display(item.related_id),
                    }
                    for item in attention.items
                ],
                hide_index=True,
            )


def _render_case_timeline(
    principal,
    active_firm,
    reopened,
    case_service,
):
    st.header("Case timeline")
    try:
        items = case_service.get_case_timeline(
            principal,
            active_firm.firm_id,
            case_id=reopened.case.case_id,
        )
    except PermissionError:
        st.error(
            "Your account is no longer authorized to view this case timeline."
        )
        return
    except LookupError:
        st.error("The case timeline is no longer available.")
        return
    except Exception:
        st.error("The case timeline could not be loaded.")
        return

    if not items:
        st.write("No case activity has been recorded yet.")
        return

    st.dataframe(
        [
            {
                "When": item.occurred_at.isoformat(timespec="minutes"),
                "Category": _friendly_enum(item.category),
                "Activity": item.title,
                "Details": item.summary,
            }
            for item in items
        ],
        hide_index=True,
    )
    with st.expander("Technical details — case timeline"):
        st.dataframe(
            [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type.value,
                    "actor_id": _display(item.actor_id),
                }
                for item in items
            ],
            hide_index=True,
        )


def _render_saved_cases_workspace(principal, active_firm):
    if AccessPermission.CASE_READ not in active_firm.permissions:
        return

    st.header("Saved cases")
    try:
        service = build_authorized_case_service()
        cases = service.list_cases(
            principal,
            active_firm.firm_id,
        )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Durable case storage is not fully configured on this "
            "deployment."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to read cases in "
            "this firm."
        )
        return
    except Exception:
        st.error("Saved cases could not be loaded.")
        return

    if not cases:
        st.write("No saved cases yet.")
        return

    focused_case_id = st.session_state.get(_FOCUSED_CASE_ID)
    if focused_case_id is not None:
        cases = sorted(
            cases,
            key=lambda item: (
                item.case_id != focused_case_id,
                -item.opened_at.timestamp(),
                item.case_id,
            ),
        )

    st.dataframe(
        [
            {
                "Matter": case.title,
                "Status": _friendly_enum(case.status),
                "Notice": _notice_form_label(case.notice_form),
                "Proceeding": _proceeding_label(case.proceeding_type),
                "Response deadline": _display(case.response_deadline),
            }
            for case in cases
        ],
        hide_index=True,
    )
    with st.expander("Technical details — saved cases"):
        st.dataframe(
            [
                {
                    "case_id": case.case_id,
                    "status": case.status.value,
                    "notice_form": case.notice_form.value,
                    "proceeding_type": case.proceeding_type.value,
                }
                for case in cases
            ],
            hide_index=True,
        )

    labels = {
        f"{case.title} — {case.case_id}": case
        for case in cases
    }
    selected_label = st.selectbox(
        "Saved case",
        list(labels),
        key="dwaar_saved_case_selector",
    )
    selected_case = labels[selected_label]

    can_open_notice = (
        AccessPermission.DOCUMENT_READ in active_firm.permissions
    )
    if not can_open_notice:
        st.caption(
            "You can view case metadata but do not have permission to "
            "read stored notice documents."
        )
        return

    open_clicked = st.button(
        "Open saved case",
        key=f"open_saved_case_{selected_case.case_id}",
    )
    cached_case_id = st.session_state.get(_OPENED_CASE_ID)
    if open_clicked and cached_case_id != selected_case.case_id:
        try:
            with st.spinner("Opening saved case and reanalyzing notice..."):
                reopened = reopen_case_analysis(
                    service,
                    principal,
                    active_firm.firm_id,
                    selected_case.case_id,
                    date.today(),
                )
        except PermissionError:
            st.error(
                "Your account is no longer authorized to open this case."
            )
            return
        except LookupError:
            st.error("The saved case is no longer available.")
            return
        except SavedCaseReopenError:
            st.error(
                "The saved notice could not be safely reopened."
            )
            return
        except Exception:
            st.error("The saved case could not be opened.")
            return

        st.session_state[_OPENED_CASE_ID] = selected_case.case_id
        st.session_state[_OPENED_CASE_ANALYSIS] = reopened
        st.session_state.pop(_OPENED_SNAPSHOT_ID, None)
        st.session_state.pop(_OPENED_SNAPSHOT, None)
        _reset_evidence_workspace()

    if st.session_state.get(_OPENED_CASE_ID) != selected_case.case_id:
        return

    reopened = st.session_state.get(_OPENED_CASE_ANALYSIS)
    if reopened is None:
        return

    if st.button(
        "Re-run with current engine",
        key=f"rerun_saved_case_{selected_case.case_id}",
    ):
        try:
            with st.spinner("Re-running saved notice with current engine..."):
                reopened = reopen_case_analysis(
                    service,
                    principal,
                    active_firm.firm_id,
                    selected_case.case_id,
                    date.today(),
                )
        except PermissionError:
            st.error(
                "Your account is no longer authorized to re-run this case."
            )
            return
        except LookupError:
            st.error("The saved case is no longer available.")
            return
        except SavedCaseReopenError:
            st.error(
                "The saved notice could not be safely re-run."
            )
            return
        except Exception:
            st.error("The saved case could not be re-run.")
            return

        st.session_state[_OPENED_CASE_ANALYSIS] = reopened
        st.session_state.pop(_OPENED_SNAPSHOT_ID, None)
        st.session_state.pop(_OPENED_SNAPSHOT, None)
        _reset_evidence_workspace()

    st.subheader("Opened case")
    st.write(f"**{reopened.case.title}**")
    st.caption(
        f"{_friendly_enum(reopened.case.status)} · "
        f"{reopened.notice_document.original_filename}"
    )
    with st.expander("Technical details — opened case"):
        st.write(
            {
                "case_id": reopened.case.case_id,
                "analysis_source": "recomputed_from_encrypted_notice",
            }
        )
    st.caption(
        "The persisted notice was decrypted and integrity-checked, then "
        "the current analysis engine recomputed this live result. Saved "
        "historical snapshots, when present, are shown separately below."
    )

    ocr_pages = [
        page.page_number
        for page in reopened.document_pages
        if page.origin is SourceTextOrigin.OCR
    ]
    if ocr_pages:
        st.warning(
            "OCR was used on scanned page(s): "
            + ", ".join(str(page) for page in ocr_pages)
            + ". OCR-derived facts require verification."
        )

    _render_professional_case_attention(
        principal,
        active_firm,
        reopened,
    )
    _render_case_timeline(
        principal,
        active_firm,
        reopened,
        service,
    )
    _render_phase2_result(reopened.analysis)
    _render_snapshot_history(
        principal,
        active_firm,
        reopened,
    )
    _render_persisted_evidence_workspace(
        principal,
        active_firm,
        reopened,
        service,
    )
    _render_draft_work_product_workspace(
        principal,
        active_firm,
        reopened,
    )
    _render_filing_workspace(
        principal,
        active_firm,
        reopened,
    )
    with st.expander("Extracted saved notice text"):
        st.text(reopened.raw_text)


def _notice_analysis(pdf_bytes):
    analysis_key = notice_analysis_key(pdf_bytes)
    if st.session_state.get(_NOTICE_KEY) != analysis_key:
        document_pages = extract_document_pages(pdf_bytes)
        raw_text = "".join(page.text for page in document_pages)
        today = date.today()
        with st.spinner("Analyzing notice..."):
            result = run_phase2_analysis_from_document_pages(
                document_pages, today
            )
        st.session_state[_NOTICE_KEY] = analysis_key
        st.session_state[_NOTICE_RESULT] = result
        st.session_state[_NOTICE_PAGES] = document_pages
        st.session_state[_NOTICE_RAW_TEXT] = raw_text
        _reset_evidence_workspace()

    return (
        st.session_state[_NOTICE_RESULT],
        st.session_state[_NOTICE_PAGES],
        st.session_state[_NOTICE_RAW_TEXT],
    )


def _render_save_intake_workspace(
    principal,
    active_firm,
    uploaded_file,
    notice_pdf_bytes,
    result,
):
    st.header("Save as intake case")
    st.caption(
        "Save this notice under a new client or explicitly reuse an "
        "existing firm client. Dwaar never auto-merges clients by name "
        "or GSTIN."
    )

    notice_key = notice_analysis_key(notice_pdf_bytes)
    save_key = f"{active_firm.firm_id}:{notice_key}"
    saved_intakes = st.session_state.setdefault(_SAVED_INTAKES, {})
    existing_case_id = saved_intakes.get(save_key)
    if existing_case_id:
        st.write("This notice is already saved as an intake case.")
        with st.expander("Technical details — saved intake"):
            st.write(
                {
                    "saved_case_id": existing_case_id,
                    "status": "intake",
                }
            )
        return

    service = None
    existing_clients = []
    if AccessPermission.CASE_READ in active_firm.permissions:
        try:
            service = build_authorized_case_service()
            existing_clients = service.list_clients(
                principal,
                active_firm.firm_id,
            )
        except RuntimePersistenceConfigurationError:
            st.error(
                "Durable case storage is not fully configured on this "
                "deployment."
            )
            return
        except PermissionError:
            st.error(
                "Your account is no longer authorized to read clients "
                "in this firm."
            )
            return
        except Exception:
            st.error("Existing clients could not be loaded.")
            return

    mode_options = ["New client"]
    if existing_clients:
        mode_options.append("Existing client")
    client_mode = st.selectbox(
        "Client handling",
        mode_options,
        key=f"intake_client_mode_{save_key}",
    )

    selected_client = None
    selected_registration = None
    client_name = None
    gstin = None

    if client_mode == "Existing client":
        client_labels = {
            f"{client.display_name} — {client.client_id}": client
            for client in existing_clients
        }
        selected_client_label = st.selectbox(
            "Existing client",
            list(client_labels),
            key=f"intake_existing_client_{save_key}",
        )
        selected_client = client_labels[selected_client_label]

        try:
            registrations = service.list_registrations(
                principal,
                active_firm.firm_id,
                client_id=selected_client.client_id,
            )
        except PermissionError:
            st.error(
                "Your account is no longer authorized to read client "
                "registrations."
            )
            return
        except Exception:
            st.error("Client registrations could not be loaded.")
            return

        registration_labels = {"No registration": None}
        for registration in registrations:
            registration_labels[
                (
                    f"{registration.identifier_type}: "
                    f"{registration.identifier_value} — "
                    f"{registration.registration_id}"
                )
            ] = registration
        selected_registration_label = st.selectbox(
            "Tax registration",
            list(registration_labels),
            key=f"intake_existing_registration_{save_key}",
        )
        selected_registration = registration_labels[
            selected_registration_label
        ]
        st.caption(
            "Using existing client: " + selected_client.display_name
        )
        with st.expander("Technical details — selected client"):
            st.write(
                {
                    "selected_client_id": selected_client.client_id,
                    "selected_registration_id": (
                        None
                        if selected_registration is None
                        else selected_registration.registration_id
                    ),
                }
            )
    else:
        client_name = st.text_input(
            "Client name",
            key=f"intake_client_{save_key}",
        )
        gstin = st.text_input(
            "GSTIN (optional)",
            key=f"intake_gstin_{save_key}",
        )
        if (
            AccessPermission.CASE_READ in active_firm.permissions
            and not existing_clients
        ):
            st.caption("No existing clients are saved in this firm yet.")

    notice_form_label = (
        result.classification.notice_form.value.upper().replace("_", "-")
    )
    default_title = (
        f"{notice_form_label} — "
        f"{_proceeding_label(result.classification.proceeding_type)}"
    )
    case_title = st.text_input(
        "Case title",
        value=default_title,
        key=f"intake_title_{save_key}",
    )

    if not st.button(
        "Save as intake",
        key=f"save_intake_{save_key}",
    ):
        return

    try:
        if service is None:
            service = build_authorized_case_service()

        if client_mode == "Existing client":
            saved_case = service.create_existing_client_case_intake(
                principal,
                active_firm.firm_id,
                client_id=selected_client.client_id,
                registration_id=(
                    None
                    if selected_registration is None
                    else selected_registration.registration_id
                ),
                case_title=case_title,
                proceeding_type=result.classification.proceeding_type,
                notice_form=result.classification.notice_form,
                response_deadline=result.deadline_result.response_deadline,
                notice_filename=getattr(
                    uploaded_file,
                    "name",
                    "notice.pdf",
                ),
                notice_payload=notice_pdf_bytes,
                opened_at=datetime.now(timezone.utc),
            )
        else:
            saved_case = service.create_case_intake(
                principal,
                active_firm.firm_id,
                client_name=client_name,
                gstin=(gstin or None),
                case_title=case_title,
                proceeding_type=result.classification.proceeding_type,
                notice_form=result.classification.notice_form,
                response_deadline=result.deadline_result.response_deadline,
                notice_filename=getattr(
                    uploaded_file,
                    "name",
                    "notice.pdf",
                ),
                notice_payload=notice_pdf_bytes,
                opened_at=datetime.now(timezone.utc),
            )
    except RuntimePersistenceConfigurationError:
        st.error(
            "Durable case storage is not fully configured on this "
            "deployment."
        )
        return
    except (ValueError, TypeError) as error:
        st.error(str(error))
        return
    except LookupError:
        st.error(
            "The selected client or registration is no longer available."
        )
        return
    except PermissionError:
        st.error(
            "Your account is no longer authorized to create cases in "
            "this firm."
        )
        return
    except Exception:
        st.error("The intake case could not be saved.")
        return

    saved_intakes[save_key] = saved_case.case_id
    st.write(
        "Intake case saved successfully. It is now available in Saved cases."
    )
    with st.expander("Technical details — saved intake"):
        st.write(
            {
                "saved_case_id": saved_case.case_id,
                "status": saved_case.status.value,
                "client_id": saved_case.client_id,
                "registration_id": saved_case.registration_id,
            }
        )


def _render_evidence_workspace(notice_pdf_bytes, result):
    evidence_checklist = result.draft_result.evidence_checklist
    if not evidence_checklist:
        return

    st.header("Supporting evidence workspace")
    st.caption(
        "Temporary session workspace. AI suggestions are candidates only; "
        "Confirm/Reject creates an audit record and does not change taxpayer "
        "facts or draft eligibility."
    )
    supporting_uploads = st.file_uploader(
        "Upload supporting evidence PDFs",
        type="pdf",
        accept_multiple_files=True,
        key="supporting_evidence_pdfs",
    )
    if not supporting_uploads:
        st.write("No supporting evidence PDFs uploaded.")
        return

    supporting_payloads = [
        (uploaded_file.name, _uploaded_bytes(uploaded_file))
        for uploaded_file in supporting_uploads
    ]
    workspace_key = evidence_workspace_key(
        notice_pdf_bytes,
        supporting_payloads,
        [item.evidence_id for item in evidence_checklist],
    )

    if st.session_state.get(_EVIDENCE_KEY) != workspace_key:
        try:
            documents = build_evidence_documents(supporting_payloads)
            with st.spinner("Matching evidence to checklist..."):
                intake_result = propose_evidence_candidates(
                    evidence_checklist,
                    documents,
                )
        except RuntimeError as error:
            st.error(str(error))
            return
        except Exception:
            st.error("Supporting evidence could not be analyzed.")
            return

        st.session_state[_EVIDENCE_KEY] = workspace_key
        st.session_state[_EVIDENCE_INTAKE] = intake_result
        st.session_state[_EVIDENCE_REVIEWS] = []

    intake_result = st.session_state[_EVIDENCE_INTAKE]
    reviews = st.session_state.setdefault(_EVIDENCE_REVIEWS, [])

    st.write(
        f"{len(intake_result.candidates)} evidence candidate(s) proposed "
        f"for professional review."
    )
    if intake_result.rejected_candidate_count:
        st.warning(
            f"{intake_result.rejected_candidate_count} candidate(s) were "
            "rejected by Dwaar's deterministic validation."
        )

    if intake_result.candidates:
        requirement_text_by_id = {
            item.evidence_id: item.requirement_text
            for item in evidence_checklist
        }
        st.dataframe(
            [
                {
                    "Evidence requirement": requirement_text_by_id.get(
                        candidate.evidence_id,
                        "Evidence requirement",
                    ),
                    "Source page": candidate.source_page,
                    "Source evidence": candidate.source_text,
                    "Verification": _friendly_enum(
                        candidate.source_verification
                    ),
                    "Review": _friendly_enum(candidate.review_status),
                }
                for candidate in intake_result.candidates
            ],
            hide_index=True,
        )
        with st.expander("Technical details — evidence candidates"):
            st.write(
                {
                    "evidence_intake_status": intake_result.status.value,
                    "rejected_candidate_count": (
                        intake_result.rejected_candidate_count
                    ),
                }
            )
            st.dataframe(
                [
                    {
                        "candidate_id": candidate.candidate_id,
                        "evidence_id": candidate.evidence_id,
                        "document_id": candidate.document_id,
                        "source_origin": candidate.source_origin.value,
                    }
                    for candidate in intake_result.candidates
                ],
                hide_index=True,
            )
    else:
        st.write("No source-grounded evidence candidates were proposed.")

    reviewed_ids = set(reviewed_candidate_ids(reviews))
    for candidate in intake_result.candidates:
        if candidate.candidate_id in reviewed_ids:
            continue

        st.subheader("Review evidence candidate")
        st.write(candidate.source_text)
        st.caption(
            f"Page {candidate.source_page} · "
            f"{_friendly_enum(candidate.source_verification)}"
        )
        with st.expander(
            f"Technical details — evidence candidate {candidate.candidate_id}"
        ):
            st.write(
                {
                    "candidate_id": candidate.candidate_id,
                    "evidence_id": candidate.evidence_id,
                    "document_id": candidate.document_id,
                    "source_origin": candidate.source_origin.value,
                }
            )
        note = st.text_input(
            "Reviewer note (optional)",
            key=f"evidence_note_{workspace_key}_{candidate.candidate_id}",
        )
        if st.button(
            f"Confirm {candidate.candidate_id}",
            key=f"confirm_{workspace_key}_{candidate.candidate_id}",
        ):
            reviews.append(
                create_evidence_review(
                    candidate,
                    EvidenceReviewStatus.CONFIRMED,
                    reviews,
                    note,
                )
            )
            reviewed_ids.add(candidate.candidate_id)

        if (
            candidate.candidate_id not in reviewed_ids
            and st.button(
                f"Reject {candidate.candidate_id}",
                key=f"reject_{workspace_key}_{candidate.candidate_id}",
            )
        ):
            reviews.append(
                create_evidence_review(
                    candidate,
                    EvidenceReviewStatus.REJECTED,
                    reviews,
                    note,
                )
            )
            reviewed_ids.add(candidate.candidate_id)

    if reviews:
        st.subheader("Evidence review records")
        st.dataframe(
            [
                {
                    "Decision": _friendly_enum(review.decision),
                    "Source page": review.source_page,
                    "Reviewer note": _display(review.reviewer_note),
                }
                for review in reviews
            ],
            hide_index=True,
        )
        with st.expander("Technical details — evidence review records"):
            st.dataframe(
                [
                    {
                        "review_id": review.review_id,
                        "candidate_id": review.candidate_id,
                        "evidence_id": review.evidence_id,
                        "document_id": review.document_id,
                        "source_origin": review.source_origin.value,
                        "source_verification": (
                            review.source_verification.value
                        ),
                    }
                    for review in reviews
                ],
                hide_index=True,
            )


st.set_page_config(
    page_title="Dwaar — GST Notice Workspace",
    page_icon="📋",
    layout="centered",
)

_principal, _active_firm = _require_app_access()

st.title("📋 Dwaar")
st.caption("GST notice workspace for professional review.")

_render_case_work_queue(_principal, _active_firm)
_render_client_workspace(_principal, _active_firm)
_render_saved_cases_workspace(_principal, _active_firm)

if AccessPermission.CASE_CREATE in _active_firm.permissions:
    st.header("New notice intake")
    st.write("Upload a GST notice PDF for structured Phase-2 analysis.")
    st.caption("Phase-2 outputs require professional review before use.")

    uploaded = st.file_uploader(
        "Upload notice PDF",
        type="pdf",
        key="notice_pdf",
    )

    if uploaded:
        pdf_bytes = _uploaded_bytes(uploaded)
        try:
            result, document_pages, raw_text = _notice_analysis(pdf_bytes)
        except RuntimeError as error:
            st.error(str(error))
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
            _render_save_intake_workspace(
                _principal,
                _active_firm,
                uploaded,
                pdf_bytes,
                result,
            )
            _render_evidence_workspace(pdf_bytes, result)
            with st.expander("Extracted notice text"):
                st.text(raw_text)
else:
    st.caption(
        "This firm access is read-only for case intake; new notice upload "
        "requires CASE_CREATE."
    )
