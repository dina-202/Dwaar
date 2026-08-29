"""Generic deterministic Step-8.2 Validation Engine
(docs/architecture/ARCHITECTURE_SPEC_v1_1 §19, §19.56–§19.87).

Staged Step-8.2 implementation (§19.73): this module implements the
support gate, extraction health, fact safety invariants, preflight
checks, deadline/hearing checks, arithmetic structural/outcome checks,
workflow special-rule handling, ReviewRequirement generation/dedup,
overall status aggregation, case severity and interim
DraftEligibility.

`requirements` and `evidence_checklist` are ALWAYS empty during Step
8.2 — Step 8.3 owns requirement resolution and Step 8.4 owns evidence
checklist generation (§19.73). The empty lists are a staged
implementation state, never proof of completeness.

Pure deterministic Python (§19.8): no LLM calls, no network access, no
deadline/arithmetic recomputation, no runtime source-file reading and
no semantic interpretation of workflow strings. Workflow and profile
lookup are deterministic registry reads driven only by
`classification.proceeding_type` (§19.7).

ValidationStatus semantics (§19.23): FAIL/WARNING/PASS are
product/workflow safety states, never legal conclusions.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from domain.models import (
    ArithmeticCalculationType,
    ArithmeticResult,
    ArithmeticStatus,
    AuthorityDetailsStatus,
    CommunicationIdentifierStatus,
    DeadlineConflictStatus,
    DeadlineResult,
    DeadlineStatus,
    DraftEligibility,
    DraftPermission,
    FactExtractionResult,
    FactExtractionStatus,
    FactRole,
    FactStatus,
    FactType,
    HearingStatus,
    IssueSeverity,
    NoticeClassification,
    PreflightResult,
    ProceedingType,
    ReviewLevel,
    ReviewRequirement,
    SpecialRuleHandling,
    SupportLevel,
    ValidationEngineResult,
    ValidationItem,
    ValidationStatus,
    WorkflowValidationProfile,
)
from workflows.gst import get_workflow
from workflows.gst.base import WorkflowDefinition
from workflows.gst.validation_profiles import get_validation_profile


# --- Architecture-owned constants ------------------------------------------

# §19.60: fixed fact-invariant check IDs with their exact invariant
# descriptions, in fixed emission order. One ValidationItem per invariant.
_FACT_INVARIANTS: Tuple[Tuple[str, str], ...] = (
    ("fact.department_allegation_status", "Department-allegation status invariant"),
    ("fact.department_allegation_draft_permission", "Department-allegation draft-permission invariant"),
    ("fact.other_notice_fact_status", "Other-notice-fact status invariant"),
    ("fact.requires_verification_draft_permission", "Requires-verification draft-permission invariant"),
    ("fact.confirmed_draft_permission", "Confirmed-fact draft-permission invariant"),
    ("fact.alleged_draft_permission", "Alleged-fact draft-permission invariant"),
    ("fact.fact_id_present", "Fact-ID presence invariant"),
    ("fact.source_text_present", "Fact source-text presence invariant"),
    ("fact.fact_id_unique", "Fact-ID uniqueness invariant"),
    ("fact.role_compatibility", "FactRole compatibility invariant"),
)

# §19.58: the six structural support checks (emitted for DEEP_WORKFLOW).
_SUPPORT_STRUCTURAL_IDS: Tuple[str, ...] = (
    "support.workflow_registered",
    "support.profile_registered",
    "support.workflow_alignment",
    "support.profile_alignment",
    "support.requirement_alignment",
    "support.special_rule_coverage",
)

# §19.66: stable workflow check-ID prefixes per ProceedingType.
_PREFIX_BY_PROCEEDING: Dict[ProceedingType, str] = {
    ProceedingType.GST_SEC73_ITC: "sec73_itc",
    ProceedingType.GST_SEC73_GENERAL: "sec73_general",
    ProceedingType.GST_SEC73_RCM: "sec73_rcm",
    ProceedingType.GST_SEC74_FRAUD: "sec74_fraud",
    ProceedingType.GST_SEC129_ENFORCE: "sec129",
}

# §19.64: arithmetic check-ID suffixes. The first five are structural
# (§19.29): a FAIL among them blocks drafting. `outcome` is not structural.
_ARITHMETIC_SUFFIXES: Tuple[str, ...] = (
    "calculation_type",
    "draft_permission",
    "source_resolution",
    "role_provenance",
    "result_status_consistency",
    "outcome",
)
_ARITHMETIC_STRUCTURAL_SUFFIXES: Tuple[str, ...] = _ARITHMETIC_SUFFIXES[:-1]

# §19.5: closed FactRole → FactType compatibility table.
_STATED_AMOUNT_ROLES = frozenset({
    FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
    FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
    FactRole.INTEREST_PROPOSED_AMOUNT,
    FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT,
    FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT,
    FactRole.SEC129_PENALTY_PROPOSED_AMOUNT,
})
_DEPARTMENT_ALLEGATION_ROLES = frozenset({
    FactRole.RCM_CATEGORY_ALLEGED,
    FactRole.RCM_VALUE_ALLEGED_AMOUNT,
    FactRole.RCM_TAX_ALLEGED_AMOUNT,
    FactRole.FRAUD_BASIS_ALLEGED,
    FactRole.DEPARTMENT_ALLEGED_AMOUNT,
    FactRole.FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT,
})
_DOCUMENT_DETAIL_ROLES = frozenset({
    FactRole.LIMITATION_BASIS,
    FactRole.GOODS_DESCRIPTION,
    FactRole.VEHICLE_NUMBER,
    FactRole.DETENTION_OR_SEIZURE_DATE,
    FactRole.SECTION129_NOTICE_OR_SERVICE_DATE,
    FactRole.GOODS_VALUE_OR_TAX_PAYABLE,
    FactRole.OWNER_CAME_FORWARD_STATUS,
    FactRole.ORDER_DATE_OR_ENFORCEMENT_STATUS,
})
_PROCEDURAL_DATE_TYPES = frozenset({
    FactType.STATED_DUE_DATE,
    FactType.HEARING_DETAILS,
    FactType.DOCUMENT_DETAIL,
})

# §19.15: approved operand-role order per calculation type.
_OPERAND_ROLES: Dict[ArithmeticCalculationType, Tuple[FactRole, FactRole]] = {
    ArithmeticCalculationType.ITC_DIFFERENCE: (
        FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
    ),
    ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE: (
        FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT,
        FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT,
    ),
}


# --- Helpers ----------------------------------------------------------------

def _item(
    check_id: str,
    status: ValidationStatus,
    message: str,
    fact_ids: Optional[List[str]] = None,
    calculation_types: Optional[List[ArithmeticCalculationType]] = None,
) -> ValidationItem:
    """Build one ValidationItem with defensive list copies so callers can
    never share mutable state with the engine output."""
    return ValidationItem(
        check_id=check_id,
        status=status,
        message=message,
        related_fact_ids=[] if fact_ids is None else list(fact_ids),
        related_calculation_types=(
            [] if calculation_types is None else list(calculation_types)
        ),
    )


def _usable_fact_id(fact) -> bool:
    """A usable fact ID is a non-empty, non-blank string (§19.60)."""
    return bool(isinstance(fact.fact_id, str) and fact.fact_id.strip())


def _offender_ids(facts) -> List[str]:
    """Non-empty fact IDs of the given offending facts, in input order."""
    return [fact.fact_id for fact in facts if _usable_fact_id(fact)]


def _find_item(checks: List[ValidationItem], check_id: str) -> Optional[ValidationItem]:
    for item in checks:
        if item.check_id == check_id:
            return item
    return None


def _dedup_reviews(reviews: List[ReviewRequirement]) -> List[ReviewRequirement]:
    """§19.42/§19.72: deduplicate by (level, reason), preserving first
    occurrence and, when duplicates collapse, the first review_id. Never
    merge different review levels."""
    deduped: List[ReviewRequirement] = []
    seen = set()
    for review in reviews:
        key = (review.level, review.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(review)
    return deduped


# --- 1. Support gate (§19.58, §19.45, §19.46) -------------------------------

def _support_gate(
    checks: List[ValidationItem],
    classification: NoticeClassification,
    workflow: Optional[WorkflowDefinition],
    profile: Optional[WorkflowValidationProfile],
) -> None:
    if classification.support_level == SupportLevel.TRIAGE_ONLY:
        checks.append(_item(
            "support.level",
            ValidationStatus.FAIL,
            "Specialist deep-workflow drafting is unavailable for this recognized notice.",
        ))
        return
    if (
        classification.support_level == SupportLevel.UNKNOWN
        or classification.proceeding_type == ProceedingType.UNKNOWN
    ):
        checks.append(_item(
            "support.level",
            ValidationStatus.FAIL,
            "Specialist deep-workflow drafting is unavailable because the notice classification is unsupported or unknown.",
        ))
        return

    checks.append(_item(
        "support.level",
        ValidationStatus.PASS,
        "Deep workflow support is available for the classified proceeding.",
    ))

    workflow_ok = isinstance(workflow, WorkflowDefinition)
    checks.append(_item(
        "support.workflow_registered",
        ValidationStatus.PASS if workflow_ok else ValidationStatus.FAIL,
        "A deep WorkflowDefinition is registered for the classified proceeding."
        if workflow_ok
        else "No deep WorkflowDefinition is registered for the classified proceeding.",
    ))

    profile_ok = isinstance(profile, WorkflowValidationProfile)
    checks.append(_item(
        "support.profile_registered",
        ValidationStatus.PASS if profile_ok else ValidationStatus.FAIL,
        "A WorkflowValidationProfile is registered for the classified proceeding."
        if profile_ok
        else "No WorkflowValidationProfile is registered for the classified proceeding.",
    ))

    workflow_aligned = (
        workflow_ok and workflow.proceeding_type == classification.proceeding_type
    )
    checks.append(_item(
        "support.workflow_alignment",
        ValidationStatus.PASS if workflow_aligned else ValidationStatus.FAIL,
        "WorkflowDefinition proceeding type matches the classification."
        if workflow_aligned
        else "WorkflowDefinition proceeding type does not match the classification.",
    ))

    profile_aligned = (
        profile_ok and profile.proceeding_type == classification.proceeding_type
    )
    checks.append(_item(
        "support.profile_alignment",
        ValidationStatus.PASS if profile_aligned else ValidationStatus.FAIL,
        "WorkflowValidationProfile proceeding type matches the classification."
        if profile_aligned
        else "WorkflowValidationProfile proceeding type does not match the classification.",
    ))

    requirement_aligned = (
        workflow_ok
        and profile_ok
        and len(profile.requirement_specs) == len(workflow.required_facts)
        and all(
            spec.requirement_text == workflow.required_facts[index]
            for index, spec in enumerate(profile.requirement_specs)
        )
    )
    checks.append(_item(
        "support.requirement_alignment",
        ValidationStatus.PASS if requirement_aligned else ValidationStatus.FAIL,
        "Workflow requirement profile matches the workflow required-facts contract."
        if requirement_aligned
        else "Workflow requirement profile does not match the workflow required-facts contract.",
    ))

    coverage_ok = (
        workflow_ok
        and profile_ok
        and all(
            index in profile.special_rule_handling
            and bool(profile.special_rule_handling[index])
            for index in range(len(workflow.special_rules))
        )
    )
    checks.append(_item(
        "support.special_rule_coverage",
        ValidationStatus.PASS if coverage_ok else ValidationStatus.FAIL,
        "Every workflow special rule has an authoritative validation/review handling mapping."
        if coverage_ok
        else "One or more workflow special rules lack an authoritative handling mapping.",
    ))


# --- 2. Extraction health (§19.59, §19.27) -----------------------------------

def _extraction_health(
    checks: List[ValidationItem],
    extraction_result: FactExtractionResult,
) -> None:
    status = extraction_result.status
    if status == FactExtractionStatus.SUCCESS:
        checks.append(_item(
            "extraction.status",
            ValidationStatus.PASS,
            "Fact extraction completed successfully.",
        ))
    elif status == FactExtractionStatus.PARTIAL:
        checks.append(_item(
            "extraction.status",
            ValidationStatus.WARNING,
            "Fact extraction was partial; validated positive facts remain usable but absence-based conclusions are not reliable.",
        ))
    elif status == FactExtractionStatus.FAILED:
        checks.append(_item(
            "extraction.status",
            ValidationStatus.FAIL,
            "Fact extraction failed; specialist drafting is blocked.",
        ))
    elif status == FactExtractionStatus.NO_INPUT:
        checks.append(_item(
            "extraction.status",
            ValidationStatus.FAIL,
            "No usable notice text was available for fact extraction; specialist drafting is blocked.",
        ))
    else:
        checks.append(_item(
            "extraction.status",
            ValidationStatus.FAIL,
            "Fact extraction status is unsupported.",
        ))


# --- 3. Fact safety invariants (§19.60, §19.28, §19.5) -----------------------

def _role_compatible(fact) -> bool:
    """§19.5 deterministic role → FactType compatibility. FactRole.NONE is
    compatible with every FactType. No silent role/type rewriting."""
    role = fact.fact_role
    if role == FactRole.NONE:
        return True
    if role in _STATED_AMOUNT_ROLES:
        return fact.fact_type == FactType.STATED_AMOUNT
    if role in _DEPARTMENT_ALLEGATION_ROLES:
        return fact.fact_type == FactType.DEPARTMENT_ALLEGATION
    if role in _DOCUMENT_DETAIL_ROLES:
        return fact.fact_type == FactType.DOCUMENT_DETAIL
    if role == FactRole.EXPLICIT_PROCEDURAL_DATE:
        return fact.fact_type in _PROCEDURAL_DATE_TYPES
    return False


def _fact_invariants(
    checks: List[ValidationItem],
    facts,
) -> None:
    """Emit exactly the ten §19.60 invariant items. Read-only: facts are
    never mutated."""
    offenders_by_check: Dict[str, list] = {}

    offenders_by_check["fact.department_allegation_status"] = [
        f for f in facts
        if f.fact_type == FactType.DEPARTMENT_ALLEGATION
        and f.status != FactStatus.ALLEGED
    ]
    offenders_by_check["fact.department_allegation_draft_permission"] = [
        f for f in facts
        if f.fact_type == FactType.DEPARTMENT_ALLEGATION
        and f.allowed_in_draft == DraftPermission.YES
    ]
    offenders_by_check["fact.other_notice_fact_status"] = [
        f for f in facts
        if f.fact_type == FactType.OTHER_NOTICE_FACT
        and f.status != FactStatus.REQUIRES_VERIFICATION
    ]
    offenders_by_check["fact.requires_verification_draft_permission"] = [
        f for f in facts
        if f.status == FactStatus.REQUIRES_VERIFICATION
        and f.allowed_in_draft != DraftPermission.NO
    ]
    offenders_by_check["fact.confirmed_draft_permission"] = [
        f for f in facts
        if f.status == FactStatus.CONFIRMED
        and f.allowed_in_draft != DraftPermission.YES
    ]
    offenders_by_check["fact.alleged_draft_permission"] = [
        f for f in facts
        if f.status == FactStatus.ALLEGED
        and f.allowed_in_draft != DraftPermission.CONDITIONAL
    ]
    offenders_by_check["fact.fact_id_present"] = [
        f for f in facts if not _usable_fact_id(f)
    ]
    offenders_by_check["fact.source_text_present"] = [
        f for f in facts
        if not (isinstance(f.source_text, str) and f.source_text.strip())
    ]

    # fact.fact_id_unique: duplicated non-empty IDs, each ID once, in first
    # duplicate-detection order. Empty IDs are owned by the presence check.
    seen_ids = set()
    duplicated_ids: List[str] = []
    duplicate_facts = []
    for fact in facts:
        fact_id = fact.fact_id
        if not _usable_fact_id(fact):
            continue
        if fact_id in seen_ids:
            if fact_id not in duplicated_ids:
                duplicated_ids.append(fact_id)
                duplicate_facts.append(fact)
        else:
            seen_ids.add(fact_id)
    offenders_by_check["fact.fact_id_unique"] = duplicate_facts

    offenders_by_check["fact.role_compatibility"] = [
        f for f in facts if not _role_compatible(f)
    ]

    for check_id, description in _FACT_INVARIANTS:
        offenders = offenders_by_check[check_id]
        if offenders:
            # §19.60: FAIL → IDs of all offending facts in extraction
            # order. fact_id_present may legitimately FAIL with an empty
            # related list when offenders have no usable ID.
            checks.append(_item(
                check_id,
                ValidationStatus.FAIL,
                f"{description} failed.",
                fact_ids=_offender_ids(offenders),
            ))
        else:
            checks.append(_item(
                check_id,
                ValidationStatus.PASS,
                f"{description} is satisfied.",
            ))


# --- 4. Preflight checks (§19.61, §19.30) ------------------------------------

def _preflight_checks(
    checks: List[ValidationItem],
    preflight: PreflightResult,
    deadline_result: Optional[DeadlineResult],
) -> None:
    if preflight.portal_verification_required:
        checks.append(_item(
            "preflight.portal_verification",
            ValidationStatus.WARNING,
            "GST portal identifier/authenticity verification is required.",
        ))
    else:
        checks.append(_item(
            "preflight.portal_verification",
            ValidationStatus.PASS,
            "GST portal identifier/authenticity verification is not currently flagged by preflight.",
        ))

    if preflight.authority_verification_required:
        checks.append(_item(
            "preflight.authority_verification",
            ValidationStatus.WARNING,
            "Issuing-authority competence/jurisdiction requires CA/legal verification.",
        ))
    else:
        checks.append(_item(
            "preflight.authority_verification",
            ValidationStatus.PASS,
            "Issuing-authority verification is not currently flagged by preflight.",
        ))

    comm_status = preflight.communication_identifier_status
    if comm_status == CommunicationIdentifierStatus.UNKNOWN:
        checks.append(_item(
            "preflight.communication_identifier",
            ValidationStatus.WARNING,
            "Communication identifier status is UNKNOWN.",
        ))
    elif isinstance(comm_status, CommunicationIdentifierStatus):
        checks.append(_item(
            "preflight.communication_identifier",
            ValidationStatus.PASS,
            "Communication identifier status is available.",
        ))
    else:
        checks.append(_item(
            "preflight.communication_identifier",
            ValidationStatus.FAIL,
            "Communication identifier status is unsupported.",
        ))

    authority_status = preflight.authority_details_status
    if authority_status == AuthorityDetailsStatus.UNKNOWN:
        checks.append(_item(
            "preflight.authority_details",
            ValidationStatus.WARNING,
            "Authority details status is UNKNOWN.",
        ))
    elif isinstance(authority_status, AuthorityDetailsStatus):
        checks.append(_item(
            "preflight.authority_details",
            ValidationStatus.PASS,
            "Authority details status is available.",
        ))
    else:
        checks.append(_item(
            "preflight.authority_details",
            ValidationStatus.FAIL,
            "Authority details status is unsupported.",
        ))

    conflict_status = preflight.deadline_conflict_status
    if conflict_status == DeadlineConflictStatus.CONFLICT:
        checks.append(_item(
            "preflight.deadline_conflict",
            ValidationStatus.WARNING,
            "The notice-stated due date conflicts with the calculated response deadline.",
        ))
    elif conflict_status == DeadlineConflictStatus.CANNOT_COMPARE:
        if preflight.stated_due_date_fact_ids or deadline_result is not None:
            checks.append(_item(
                "preflight.deadline_conflict",
                ValidationStatus.WARNING,
                "The notice-stated due date and calculated response deadline cannot be reliably compared.",
            ))
        else:
            checks.append(_item(
                "preflight.deadline_conflict",
                ValidationStatus.PASS,
                "No deadline comparison is currently available or required.",
            ))
    elif conflict_status == DeadlineConflictStatus.MATCH:
        checks.append(_item(
            "preflight.deadline_conflict",
            ValidationStatus.PASS,
            "The notice-stated due date matches the calculated response deadline.",
        ))
    else:
        checks.append(_item(
            "preflight.deadline_conflict",
            ValidationStatus.FAIL,
            "Preflight deadline-conflict status is unsupported.",
        ))


# --- 5. Deadline / hearing checks (§19.62, §19.63, §19.31) --------------------

def _deadline_hearing_checks(
    checks: List[ValidationItem],
    deadline_result: DeadlineResult,
) -> None:
    deadline_status = deadline_result.deadline_status
    if deadline_status == DeadlineStatus.UPCOMING:
        checks.append(_item(
            "deadline.status",
            ValidationStatus.PASS,
            "The calculated response deadline is upcoming.",
        ))
    elif deadline_status == DeadlineStatus.CRITICAL:
        checks.append(_item(
            "deadline.status",
            ValidationStatus.WARNING,
            "The calculated response deadline is critical.",
        ))
    elif deadline_status == DeadlineStatus.PASSED:
        checks.append(_item(
            "deadline.status",
            ValidationStatus.WARNING,
            "The calculated response deadline has passed.",
        ))
    elif deadline_status == DeadlineStatus.UNKNOWN:
        checks.append(_item(
            "deadline.status",
            ValidationStatus.WARNING,
            "The calculated response deadline is unknown.",
        ))
    else:
        checks.append(_item(
            "deadline.status",
            ValidationStatus.FAIL,
            "Deadline status is unsupported.",
        ))

    hearing_status = deadline_result.hearing_status
    if hearing_status == HearingStatus.UPCOMING:
        checks.append(_item(
            "hearing.status",
            ValidationStatus.PASS,
            "The scheduled hearing is upcoming.",
        ))
    elif hearing_status == HearingStatus.TODAY:
        checks.append(_item(
            "hearing.status",
            ValidationStatus.WARNING,
            "The scheduled hearing is today.",
        ))
    elif hearing_status == HearingStatus.PASSED:
        checks.append(_item(
            "hearing.status",
            ValidationStatus.WARNING,
            "The scheduled hearing has passed.",
        ))
    elif hearing_status == HearingStatus.NOT_SCHEDULED:
        checks.append(_item(
            "hearing.status",
            ValidationStatus.PASS,
            "No hearing is currently scheduled in the DeadlineResult.",
        ))
    else:
        checks.append(_item(
            "hearing.status",
            ValidationStatus.FAIL,
            "Hearing status is unsupported.",
        ))


def _deadline_urgent_review(
    reviews: List[ReviewRequirement],
    deadline_result: DeadlineResult,
) -> None:
    """§19.63: urgent review only for CRITICAL / PASSED deadlines."""
    deadline_status = deadline_result.deadline_status
    if deadline_status == DeadlineStatus.CRITICAL:
        reviews.append(ReviewRequirement(
            review_id="deadline.urgent_review",
            level=ReviewLevel.URGENT_CA_REVIEW,
            reason="Deadline status is CRITICAL; urgent CA review is required.",
            mandatory=True,
        ))
    elif deadline_status == DeadlineStatus.PASSED:
        reviews.append(ReviewRequirement(
            review_id="deadline.urgent_review",
            level=ReviewLevel.URGENT_CA_REVIEW,
            reason="Deadline status is PASSED; urgent CA review is required.",
            mandatory=True,
        ))


# --- 6. Arithmetic checks (§19.64, §19.65, §19.29, §19.15) --------------------

def _resolve_fact(facts, fact_id: str):
    """Exact case-sensitive fact_id equality; a source ID resolves only
    when it matches exactly ONE fact."""
    matches = [fact for fact in facts if fact.fact_id == fact_id]
    if len(matches) == 1:
        return matches[0]
    return None


def _source_id_strings(source_fact_ids) -> List[str]:
    """§19.64: source IDs restricted to valid non-empty strings, stored
    order preserved."""
    return [
        fact_id for fact_id in source_fact_ids
        if isinstance(fact_id, str) and fact_id.strip()
    ]


def _arithmetic_checks(
    checks: List[ValidationItem],
    n: int,
    result: ArithmeticResult,
    facts,
) -> None:
    """Six §19.64 checks per ArithmeticResult. No recomputation."""
    calculation_type = result.calculation_type

    if isinstance(calculation_type, ArithmeticCalculationType):
        checks.append(_item(
            f"arithmetic.{n}.calculation_type",
            ValidationStatus.PASS,
            "Arithmetic calculation type is approved.",
            calculation_types=[calculation_type],
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.calculation_type",
            ValidationStatus.FAIL,
            "Arithmetic calculation type is unsupported.",
        ))

    if result.allowed_in_draft == DraftPermission.CONDITIONAL:
        checks.append(_item(
            f"arithmetic.{n}.draft_permission",
            ValidationStatus.PASS,
            "Arithmetic draft permission is CONDITIONAL.",
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.draft_permission",
            ValidationStatus.FAIL,
            "Arithmetic draft permission must be CONDITIONAL.",
        ))

    resolved = [
        _resolve_fact(facts, fact_id)
        for fact_id in result.source_fact_ids
    ]
    sources_resolve = all(fact is not None for fact in resolved)
    if sources_resolve:
        checks.append(_item(
            f"arithmetic.{n}.source_resolution",
            ValidationStatus.PASS,
            "Arithmetic source facts resolve uniquely.",
            fact_ids=_source_id_strings(result.source_fact_ids),
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.source_resolution",
            ValidationStatus.FAIL,
            "Arithmetic source facts do not resolve uniquely.",
            fact_ids=_source_id_strings(result.source_fact_ids),
        ))

    expected_roles = _OPERAND_ROLES.get(calculation_type)
    roles_match = (
        expected_roles is not None
        and len(result.source_fact_ids) == 2
        and sources_resolve
        and resolved[0].fact_role == expected_roles[0]
        and resolved[1].fact_role == expected_roles[1]
    )
    if roles_match:
        checks.append(_item(
            f"arithmetic.{n}.role_provenance",
            ValidationStatus.PASS,
            "Arithmetic operand FactRoles match the approved calculation contract.",
            fact_ids=_source_id_strings(result.source_fact_ids),
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.role_provenance",
            ValidationStatus.FAIL,
            "Arithmetic operand FactRoles do not match the approved calculation contract.",
            fact_ids=_source_id_strings(result.source_fact_ids),
        ))

    status = result.status
    result_value = result.result
    consistent = (
        (status == ArithmeticStatus.PASS and result_value == Decimal("0"))
        or (
            status == ArithmeticStatus.MISMATCH
            and result_value is not None
            and result_value != Decimal("0")
        )
        or (
            status == ArithmeticStatus.INSUFFICIENT_DATA
            and result_value is None
        )
    )
    if consistent:
        checks.append(_item(
            f"arithmetic.{n}.result_status_consistency",
            ValidationStatus.PASS,
            "Arithmetic status and result are internally consistent.",
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.result_status_consistency",
            ValidationStatus.FAIL,
            "Arithmetic status and result are internally inconsistent.",
        ))

    if status == ArithmeticStatus.PASS:
        checks.append(_item(
            f"arithmetic.{n}.outcome",
            ValidationStatus.PASS,
            "Arithmetic result matches.",
        ))
    elif status == ArithmeticStatus.MISMATCH:
        checks.append(_item(
            f"arithmetic.{n}.outcome",
            ValidationStatus.WARNING,
            "Arithmetic result is a mismatch.",
        ))
    elif status == ArithmeticStatus.INSUFFICIENT_DATA:
        checks.append(_item(
            f"arithmetic.{n}.outcome",
            ValidationStatus.WARNING,
            "Arithmetic result has insufficient data.",
        ))
    else:
        checks.append(_item(
            f"arithmetic.{n}.outcome",
            ValidationStatus.FAIL,
            "Arithmetic outcome status is unsupported.",
        ))


# --- 7. Workflow special-rule handling (§19.40, §19.66–§19.71, §19.81–§19.85)

def _deterministic_check(
    checks: List[ValidationItem],
    proceeding_type: ProceedingType,
    index: int,
    prefix: str,
) -> None:
    """Step-8.2 execution semantics for the five current
    DETERMINISTIC_CHECK mappings (§19.81–§19.85)."""
    check_id = f"workflow.{prefix}.special_rule.{index}.deterministic_check"

    if (proceeding_type, index) == (ProceedingType.GST_SEC73_ITC, 1):
        # §19.81: deferred until Step 8.3 requirement resolution.
        checks.append(_item(
            check_id,
            ValidationStatus.WARNING,
            "Derived workflow validation is deferred until Step 8.3 requirement resolution.",
            calculation_types=[ArithmeticCalculationType.ITC_DIFFERENCE],
        ))
        return
    if (proceeding_type, index) == (ProceedingType.GST_SEC73_GENERAL, 1):
        # §19.81: deferred until Step 8.3 requirement resolution.
        checks.append(_item(
            check_id,
            ValidationStatus.WARNING,
            "Derived workflow validation is deferred until Step 8.3 requirement resolution.",
            calculation_types=[ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE],
        ))
        return
    if (proceeding_type, index) == (ProceedingType.GST_SEC74_FRAUD, 0):
        # §19.83: mirror the already-emitted generic invariant; no re-run.
        generic = _find_item(checks, "fact.department_allegation_status")
        if generic is not None and generic.status == ValidationStatus.PASS:
            checks.append(_item(
                check_id,
                ValidationStatus.PASS,
                "Fraud/suppression allegations remain departmental allegations.",
            ))
        else:
            checks.append(_item(
                check_id,
                ValidationStatus.FAIL,
                "Fraud/suppression allegation status safety failed.",
                fact_ids=(
                    list(generic.related_fact_ids)
                    if generic is not None and generic.status == ValidationStatus.FAIL
                    else []
                ),
            ))
        return
    if (proceeding_type, index) == (ProceedingType.GST_SEC74_FRAUD, 2):
        # §19.84: mirror fact.source_text_present; no re-run.
        generic = _find_item(checks, "fact.source_text_present")
        if generic is not None and generic.status == ValidationStatus.PASS:
            checks.append(_item(
                check_id,
                ValidationStatus.PASS,
                "Fraud-workflow fact provenance is present.",
            ))
        else:
            checks.append(_item(
                check_id,
                ValidationStatus.FAIL,
                "Fraud-workflow fact provenance safety failed.",
                fact_ids=(
                    list(generic.related_fact_ids)
                    if generic is not None and generic.status == ValidationStatus.FAIL
                    else []
                ),
            ))
        return
    if (proceeding_type, index) == (ProceedingType.GST_SEC129_ENFORCE, 6):
        # §19.85: architectural-boundary PASS; no statutory deadline
        # calculation is authorized here.
        checks.append(_item(
            check_id,
            ValidationStatus.PASS,
            "Section-129 deadline handling uses only supplied preflight/deadline results; validation adds no statutory deadline calculation.",
        ))
        return

    # Out-of-contract (prefix, index) pairing: never silently pass an
    # undefined deterministic check.
    checks.append(_item(
        check_id,
        ValidationStatus.FAIL,
        "Deterministic special check is not defined for this workflow rule.",
    ))


def _special_rules(
    checks: List[ValidationItem],
    reviews: List[ReviewRequirement],
    workflow: WorkflowDefinition,
    profile: WorkflowValidationProfile,
) -> None:
    """§19.40/§19.66–§19.71: deterministic special-rule processing driven
    only by the authoritative profile mappings. Workflow text is used
    verbatim (message/reason), never semantically interpreted."""
    prefix = _PREFIX_BY_PROCEEDING.get(
        workflow.proceeding_type, workflow.proceeding_type.value
    )

    for index in sorted(profile.special_rule_handling):
        if not 0 <= index < len(workflow.special_rules):
            # Out-of-range profile key (contract violation, flagged by
            # profile tests): skip rather than crash.
            continue
        rule_text = workflow.special_rules[index]
        for handling in profile.special_rule_handling[index]:
            if handling == SpecialRuleHandling.REVIEW_GATE:
                checks.append(_item(
                    f"workflow.{prefix}.special_rule.{index}.review_gate",
                    ValidationStatus.WARNING,
                    f"Mandatory review gate applies: {rule_text}",
                ))
                level = profile.review_rules.get(index)
                if isinstance(level, ReviewLevel):
                    reviews.append(ReviewRequirement(
                        review_id=(
                            f"workflow.{prefix}.special_rule.{index}.review"
                        ),
                        level=level,
                        reason=rule_text,
                        mandatory=True,
                    ))
            elif handling == SpecialRuleHandling.FUTURE_LEGAL_RULE:
                checks.append(_item(
                    f"workflow.{prefix}.special_rule.{index}.future_legal_rule",
                    ValidationStatus.WARNING,
                    "This workflow rule requires future verified legal-rule support and CA review.",
                ))
            elif handling == SpecialRuleHandling.UPSTREAM_INVARIANT:
                checks.append(_item(
                    f"workflow.{prefix}.special_rule.{index}.upstream_invariant",
                    ValidationStatus.PASS,
                    "This safety boundary is enforced by an authoritative upstream component and is not re-run by validation.",
                ))
            elif handling == SpecialRuleHandling.DETERMINISTIC_CHECK:
                _deterministic_check(checks, workflow.proceeding_type, index, prefix)
            else:
                # Unknown handling member: never silently skip.
                checks.append(_item(
                    f"workflow.{prefix}.special_rule.{index}.unknown_handling",
                    ValidationStatus.FAIL,
                    "Special-rule handling type is unsupported.",
                ))


# --- 8–11. Aggregation, severity, eligibility --------------------------------

def _aggregate_status(checks: List[ValidationItem]) -> ValidationStatus:
    """§19.25/§19.76: deterministic dominance over emitted items only."""
    if any(item.status == ValidationStatus.FAIL for item in checks):
        return ValidationStatus.FAIL
    if any(item.status == ValidationStatus.WARNING for item in checks):
        return ValidationStatus.WARNING
    return ValidationStatus.PASS


def _case_severity(
    classification: NoticeClassification,
    workflow: Optional[WorkflowDefinition],
    deadline_result: Optional[DeadlineResult],
) -> Optional[IssueSeverity]:
    """§19.32: workflow default severity for valid deep workflows;
    CRITICAL when the supplied deadline is CRITICAL/PASSED; None for
    triage/unknown without an urgent supplied deadline."""
    deadline_status = (
        deadline_result.deadline_status if deadline_result is not None else None
    )
    urgent = deadline_status in (DeadlineStatus.CRITICAL, DeadlineStatus.PASSED)

    if (
        workflow is not None
        and classification.support_level == SupportLevel.DEEP_WORKFLOW
    ):
        if urgent:
            return IssueSeverity.CRITICAL
        return workflow.default_severity

    if urgent:
        return IssueSeverity.CRITICAL
    return None


def _draft_eligibility(
    checks: List[ValidationItem],
    reviews: List[ReviewRequirement],
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    workflow: Optional[WorkflowDefinition],
    profile: Optional[WorkflowValidationProfile],
) -> DraftEligibility:
    """§19.75: interim Step-8.2 BLOCKED conditions only. Warnings and
    review requirements resolve to REVIEW_REQUIRED; nothing else can
    reach ALLOWED without a fully clean synthetic configuration."""
    if classification.support_level != SupportLevel.DEEP_WORKFLOW:
        return DraftEligibility.BLOCKED
    if classification.proceeding_type == ProceedingType.UNKNOWN:
        return DraftEligibility.BLOCKED
    if workflow is None:
        return DraftEligibility.BLOCKED
    if profile is None:
        return DraftEligibility.BLOCKED

    if any(
        item.check_id in _SUPPORT_STRUCTURAL_IDS
        and item.status == ValidationStatus.FAIL
        for item in checks
    ):
        return DraftEligibility.BLOCKED

    if extraction_result.status in (
        FactExtractionStatus.FAILED,
        FactExtractionStatus.NO_INPUT,
    ):
        return DraftEligibility.BLOCKED

    fact_invariant_ids = {check_id for check_id, _ in _FACT_INVARIANTS}
    if any(
        item.check_id in fact_invariant_ids
        and item.status == ValidationStatus.FAIL
        for item in checks
    ):
        return DraftEligibility.BLOCKED

    if any(
        item.check_id.startswith("arithmetic.")
        and item.check_id.rsplit(".", 1)[-1] in _ARITHMETIC_STRUCTURAL_SUFFIXES
        and item.status == ValidationStatus.FAIL
        for item in checks
    ):
        return DraftEligibility.BLOCKED

    if any(item.status == ValidationStatus.WARNING for item in checks):
        return DraftEligibility.REVIEW_REQUIRED
    if reviews:
        return DraftEligibility.REVIEW_REQUIRED
    return DraftEligibility.ALLOWED


# --- Public API --------------------------------------------------------------

def run_validation(
    classification: NoticeClassification,
    extraction_result: FactExtractionResult,
    preflight_result: PreflightResult,
    arithmetic_results: List[ArithmeticResult],
    deadline_result: Optional[DeadlineResult] = None,
) -> ValidationEngineResult:
    """§19.7/§19.73: generic deterministic Step-8.2 validation.

    Facts are accessed only through `extraction_result.facts`; the
    workflow and validation profile are obtained deterministically from
    `classification.proceeding_type`. During Step 8.2 the result always
    carries `requirements == []` and `evidence_checklist == []`
    (§19.73): empty lists are a staged state, never completeness proof.
    """
    checks: List[ValidationItem] = []
    reviews: List[ReviewRequirement] = []

    workflow = get_workflow(classification.proceeding_type)
    profile = get_validation_profile(classification.proceeding_type)

    facts = extraction_result.facts

    # 1. Support gate.
    _support_gate(checks, classification, workflow, profile)

    # 2. Extraction health.
    _extraction_health(checks, extraction_result)

    # 3. Fact safety invariants.
    _fact_invariants(checks, facts)

    # 4. Preflight checks.
    _preflight_checks(checks, preflight_result, deadline_result)

    # 5. Deadline / hearing checks + urgent review.
    if deadline_result is not None:
        _deadline_hearing_checks(checks, deadline_result)
        _deadline_urgent_review(reviews, deadline_result)

    # 6. Arithmetic structural / outcome checks.
    for n, arithmetic_result in enumerate(arithmetic_results, start=1):
        _arithmetic_checks(checks, n, arithmetic_result, facts)

    # 7. Workflow special-rule handling (valid deep workflow only).
    if (
        classification.support_level == SupportLevel.DEEP_WORKFLOW
        and workflow is not None
        and profile is not None
        and workflow.proceeding_type == classification.proceeding_type
        and profile.proceeding_type == classification.proceeding_type
    ):
        _special_rules(checks, reviews, workflow, profile)

    reviews = _dedup_reviews(reviews)

    return ValidationEngineResult(
        overall_status=_aggregate_status(checks),
        draft_eligibility=_draft_eligibility(
            checks,
            reviews,
            classification,
            extraction_result,
            workflow,
            profile,
        ),
        case_severity=_case_severity(classification, workflow, deadline_result),
        checks=checks,
        requirements=[],
        evidence_checklist=[],
        review_requirements=reviews,
    )
