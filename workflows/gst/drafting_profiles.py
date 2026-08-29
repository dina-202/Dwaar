"""Drafting profiles for the five deep GST workflows
(ARCHITECTURE_SPEC_v1_1 §20.19, §20.21, §20.22).

Deterministic static registry mapping each approved deep ProceedingType to
its architecture-owned WorkflowDraftingProfile: an ordered tuple of
DraftSectionSpec machine IDs and titles plus a closed prompt key. Section
titles correspond one-for-one and in order with the current
WorkflowDefinition.output_structure (§20.19); section IDs are one-based
machine IDs (§20.21); prompt keys are the closed §20.22 set.

ProceedingType.UNKNOWN has no profile and resolves to None — there is no
fallback profile, no triage profile, no Section-74A profile and no
Section-130 profile.

Static data plus one deterministic lookup only: no network, no file
reads, no prompt loading and no engine execution.
"""

from typing import Dict, Optional

from domain.models import (
    DraftSectionSpec,
    ProceedingType,
    WorkflowDraftingProfile,
)

DRAFTING_PROFILE_REGISTRY: Dict[ProceedingType, WorkflowDraftingProfile] = {
    ProceedingType.GST_SEC73_ITC: WorkflowDraftingProfile(
        proceeding_type=ProceedingType.GST_SEC73_ITC,
        sections=(
            DraftSectionSpec(
                section_id="sec73_itc.s1", title="Working paper"
            ),
            DraftSectionSpec(
                section_id="sec73_itc.s2",
                title="ITC reconciliation table",
            ),
            DraftSectionSpec(
                section_id="sec73_itc.s3", title="Reviewable DRC-06 draft"
            ),
        ),
        prompt_key="sec73_itc",
    ),
    ProceedingType.GST_SEC73_GENERAL: WorkflowDraftingProfile(
        proceeding_type=ProceedingType.GST_SEC73_GENERAL,
        sections=(
            DraftSectionSpec(
                section_id="sec73_general.s1", title="Working paper"
            ),
            DraftSectionSpec(
                section_id="sec73_general.s2",
                title="Month-wise GSTR-1 versus GSTR-3B reconciliation",
            ),
            DraftSectionSpec(
                section_id="sec73_general.s3",
                title="Reviewable DRC-06 draft",
            ),
        ),
        prompt_key="sec73_general",
    ),
    ProceedingType.GST_SEC73_RCM: WorkflowDraftingProfile(
        proceeding_type=ProceedingType.GST_SEC73_RCM,
        sections=(
            DraftSectionSpec(
                section_id="sec73_rcm.s1", title="Working paper"
            ),
            DraftSectionSpec(
                section_id="sec73_rcm.s2",
                title="RCM supplier / service-category reconciliation",
            ),
            DraftSectionSpec(
                section_id="sec73_rcm.s3",
                title=(
                    "Reviewable DRC-06 draft with conditional RCM "
                    "submissions"
                ),
            ),
        ),
        prompt_key="sec73_rcm",
    ),
    ProceedingType.GST_SEC74_FRAUD: WorkflowDraftingProfile(
        proceeding_type=ProceedingType.GST_SEC74_FRAUD,
        sections=(
            DraftSectionSpec(
                section_id="sec74_fraud.s1", title="Urgent working paper"
            ),
            DraftSectionSpec(
                section_id="sec74_fraud.s2",
                title="Senior-review / escalation note",
            ),
            DraftSectionSpec(
                section_id="sec74_fraud.s3",
                title="Conditional reviewable DRC-06 draft",
            ),
        ),
        prompt_key="sec74_fraud",
    ),
    ProceedingType.GST_SEC129_ENFORCE: WorkflowDraftingProfile(
        proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
        sections=(
            DraftSectionSpec(
                section_id="sec129.s1",
                title="URGENT enforcement working paper",
            ),
            DraftSectionSpec(
                section_id="sec129.s2",
                title="Enforcement chronology / deadline alert",
            ),
            DraftSectionSpec(
                section_id="sec129.s3",
                title="Penalty computation verification checklist",
            ),
            DraftSectionSpec(
                section_id="sec129.s4",
                title=(
                    "Reviewable response / submission appropriate to the "
                    "actual notice or proceeding"
                ),
            ),
        ),
        prompt_key="sec129",
    ),
}


def get_drafting_profile(
    proceeding_type: ProceedingType,
) -> Optional[WorkflowDraftingProfile]:
    """Return the drafting profile for an approved deep ProceedingType.

    Returns None for ProceedingType.UNKNOWN and any other unsupported
    type: no fallback profile and no triage profile.
    """
    return DRAFTING_PROFILE_REGISTRY.get(proceeding_type)
