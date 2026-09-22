"""Thin Streamlit shell for the structured Phase-2 notice analysis."""

from datetime import date, datetime, timezone

import streamlit as st

from domain.auth_models import AccessPermission
from domain.case_models import CaseDocumentKind
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
    build_authorized_evidence_review_service,
    build_authorized_evidence_workspace_service,
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


def _render_persisted_evidence_workspace(
    principal,
    active_firm,
    reopened,
    case_service,
):
    live_checklist = reopened.analysis.draft_result.evidence_checklist
    if not live_checklist:
        return

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

    st.dataframe(
        [
            {
                "case_id": case.case_id,
                "title": case.title,
                "status": case.status.value,
                "notice_form": case.notice_form.value,
                "proceeding_type": case.proceeding_type.value,
                "response_deadline": _display(case.response_deadline),
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
    st.write(
        {
            "case_id": reopened.case.case_id,
            "title": reopened.case.title,
            "status": reopened.case.status.value,
            "notice_filename": reopened.notice_document.original_filename,
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
        "This saves the client, case metadata and encrypted notice. "
        "The current analysis is not yet persisted and will be recomputed "
        "when the case is reopened."
    )

    notice_key = notice_analysis_key(notice_pdf_bytes)
    save_key = f"{active_firm.firm_id}:{notice_key}"
    saved_intakes = st.session_state.setdefault(_SAVED_INTAKES, {})
    existing_case_id = saved_intakes.get(save_key)
    if existing_case_id:
        st.write(
            {
                "saved_case_id": existing_case_id,
                "status": "intake",
            }
        )
        return

    client_name = st.text_input(
        "Client name",
        key=f"intake_client_{save_key}",
    )
    gstin = st.text_input(
        "GSTIN (optional)",
        key=f"intake_gstin_{save_key}",
    )
    notice_form_label = (
        result.classification.notice_form.value.upper().replace("_", "-")
    )
    default_title = (
        f"{notice_form_label} — "
        f"{result.classification.proceeding_type.value}"
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
        service = build_authorized_case_service()
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
        {
            "saved_case_id": saved_case.case_id,
            "status": saved_case.status.value,
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
        st.write("No source-grounded evidence candidates were proposed.")

    reviewed_ids = set(reviewed_candidate_ids(reviews))
    for candidate in intake_result.candidates:
        if candidate.candidate_id in reviewed_ids:
            continue

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
                    "review_id": review.review_id,
                    "candidate_id": review.candidate_id,
                    "evidence_id": review.evidence_id,
                    "document_id": review.document_id,
                    "source_page": review.source_page,
                    "decision": review.decision.value,
                    "source_origin": review.source_origin.value,
                    "source_verification": (
                        review.source_verification.value
                    ),
                    "reviewer_note": _display(review.reviewer_note),
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
