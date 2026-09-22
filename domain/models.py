"""Typed domain models for CA Notice AI (docs/architecture/ARCHITECTURE_SPEC_v1.md §3).

Architecture Phase 2 — Step 1 artifact. Pure data contracts only.

- Standard library only (enum, dataclasses, typing, datetime).
- No business logic, no LLM calls, no Streamlit, no external dependencies.
- Not wired to the running application yet.
- Independently importable: this module imports nothing from the project.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union


# --- 3.1 Enums ------------------------------------------------------------

class ProceedingType(Enum):
    GST_SEC73_GENERAL = "gst_sec73_general"
    GST_SEC73_ITC = "gst_sec73_itc"
    GST_SEC73_RCM = "gst_sec73_rcm"
    GST_SEC74_FRAUD = "gst_sec74_fraud"
    GST_SEC129_ENFORCE = "gst_sec129_enforcement"
    UNKNOWN = "unknown"


class FactStatus(Enum):
    CONFIRMED = "confirmed"  # Explicitly in notice
    ALLEGED = "alleged"  # Department's claim only
    UNKNOWN = "unknown"  # Not in notice, not verified
    REQUIRES_VERIFICATION = "requires_verification"  # CA must check
    INFERRED = "inferred"  # Calculated/derived


class DraftPermission(Enum):
    YES = "yes"  # Can state as fact in draft
    CONDITIONAL = "conditional"  # Only with [CA TO CONFIRM] wrapper
    NO = "no"  # Must not appear in draft


class DeadlineConfidence(Enum):
    CONFIRMED = "confirmed"  # Service date known
    ESTIMATED = "estimated"  # Assuming service = notice date
    UNKNOWN = "unknown"  # Cannot determine


class DeadlineStatus(Enum):
    UPCOMING = "upcoming"
    CRITICAL = "critical"  # Within 7 days
    PASSED = "passed"  # Deadline gone
    UNKNOWN = "unknown"


class HearingStatus(Enum):
    UPCOMING = "upcoming"
    TODAY = "today"
    PASSED = "passed"
    NOT_SCHEDULED = "not_scheduled"


class IssueSeverity(Enum):
    CRITICAL = "critical"  # 100% penalty / fraud / expired
    HIGH = "high"  # Large demand / urgent deadline
    MEDIUM = "medium"  # Standard demand / moderate deadline
    LOW = "low"  # Minor / routine


class ValidationStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


# --- Phase 2 Step 2.5 enums (ARCHITECTURE_SPEC_v1_1 §5, §6) -----------------
# Additive taxonomy/classification contracts. Existing Step 1 enums above are
# unchanged. Values follow the repo convention: lowercase member names.

class NoticeFamily(Enum):
    """GST notice family (ARCHITECTURE_SPEC_v1_1 §5.1)."""

    RETURN_COMPLIANCE = "return_compliance"
    REGISTRATION = "registration"
    COMPOSITION = "composition"
    GST_PRACTITIONER = "gst_practitioner"
    REFUND = "refund"
    ASSESSMENT_SCRUTINY = "assessment_scrutiny"
    AUDIT = "audit"
    DEMAND_ADJUDICATION = "demand_adjudication"
    ENFORCEMENT = "enforcement"
    REVISION = "revision"
    UNKNOWN = "unknown"


class NoticeForm(Enum):
    """Recognized Taxonomy v1 notice forms (ARCHITECTURE_SPEC_v1_1 §5.2).

    Section 130 is intentionally NOT a member (§3.9): it is captured later
    as a cited section with provenance, never as a fabricated form id.
    """

    GSTR_3A = "gstr_3a"
    CMP_05 = "cmp_05"
    REG_03 = "reg_03"
    REG_17 = "reg_17"
    REG_23 = "reg_23"
    PCT_03 = "pct_03"
    RFD_08 = "rfd_08"
    ASMT_02 = "asmt_02"
    ASMT_10 = "asmt_10"
    ASMT_14 = "asmt_14"
    ADT_01 = "adt_01"
    RVN_01 = "rvn_01"
    DRC_01A = "drc_01a"
    DRC_01 = "drc_01"
    DRC_01B = "drc_01b"
    DRC_01C = "drc_01c"
    MOV_SERIES = "mov_series"
    UNKNOWN = "unknown"


class SupportLevel(Enum):
    """Workflow support level (ARCHITECTURE_SPEC_v1_1 §5.3).

    Assigned by Python taxonomy validation, never by the LLM alone.
    """

    DEEP_WORKFLOW = "deep_workflow"
    TRIAGE_ONLY = "triage_only"
    UNKNOWN = "unknown"


class ClassificationConfidence(Enum):
    """Qualitative classification confidence (ARCHITECTURE_SPEC_v1_1 §5.5).

    Categorical only — numeric/percentage confidence is NOT used.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class CommunicationIdentifierStatus(Enum):
    """Observed RFN/DIN presence only (ARCHITECTURE_SPEC_v1_1 §6.2).

    Portal verification is a separate boolean/result, never a member here.
    """

    RFN_PRESENT = "rfn_present"
    DIN_PRESENT = "din_present"
    BOTH_PRESENT = "both_present"
    NEITHER_FOUND = "neither_found"
    UNKNOWN = "unknown"


class AuthorityDetailsStatus(Enum):
    """Authority-details extraction completeness (ARCHITECTURE_SPEC_v1_1 §6.3).

    Extraction completeness only — legal competence/jurisdiction
    conclusions are deliberately not encoded here.
    """

    PRESENT = "present"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ArithmeticStatus(Enum):
    """Deterministic arithmetic check outcome (ARCHITECTURE_SPEC_v1_1 §6.7).

    Added in Step 2.5; the ArithmeticResult contract belongs to Step 7.
    """

    PASS = "pass"
    MISMATCH = "mismatch"
    INSUFFICIENT_DATA = "insufficient_data"


# --- Phase 2 Step 6.1 enum (ARCHITECTURE_SPEC_v1_1 §17.1) -------------------

class FactType(Enum):
    """Machine-readable fact category for structured fact extraction.

    Identifies WHAT KIND of information was extracted from a notice. It does
    NOT decide whether the underlying legal proposition is true (§17.1).
    """

    NOTICE_REFERENCE = "notice_reference"
    NOTICE_DATE = "notice_date"
    TAXPAYER_NAME = "taxpayer_name"
    GSTIN = "gstin"

    AUTHORITY_NAME = "authority_name"
    AUTHORITY_DESIGNATION = "authority_designation"
    AUTHORITY_OFFICE = "authority_office"
    JURISDICTION_TEXT = "jurisdiction_text"

    RFN = "rfn"
    DIN = "din"

    STATUTORY_SECTION = "statutory_section"
    STATUTORY_RULE = "statutory_rule"
    STATUTORY_NOTIFICATION = "statutory_notification"

    TAX_PERIOD = "tax_period"

    STATED_DUE_DATE = "stated_due_date"
    HEARING_DETAILS = "hearing_details"

    STATED_AMOUNT = "stated_amount"

    DEPARTMENT_ALLEGATION = "department_allegation"

    REQUESTED_DOCUMENT = "requested_document"
    REFERENCED_ANNEXURE = "referenced_annexure"

    # §19.1: additive member authorized by Phase 2 Step 8A (Step 6.4).
    DOCUMENT_DETAIL = "document_detail"

    OTHER_NOTICE_FACT = "other_notice_fact"


# --- Phase 2 Step 6.4 enum (ARCHITECTURE_SPEC_v1_1 §19.2) -------------------

class FactRole(Enum):
    """Closed semantic role vocabulary (ARCHITECTURE_SPEC_v1_1 §19.2).

    Exactly 22 members. A role describes the machine-readable semantic use
    of a fact; it does NOT determine legal liability and it does NOT
    choose FactStatus (§19.6). Values follow the repo convention:
    lowercase member names. NONE is the default for facts whose role is
    not workflow-relevant.
    """

    NONE = "none"

    GSTR3B_ITC_CLAIMED_AMOUNT = "gstr3b_itc_claimed_amount"
    GSTR2B_ITC_REFLECTED_AMOUNT = "gstr2b_itc_reflected_amount"
    INTEREST_PROPOSED_AMOUNT = "interest_proposed_amount"

    GSTR1_LIABILITY_DECLARED_AMOUNT = "gstr1_liability_declared_amount"
    GSTR3B_LIABILITY_DISCHARGED_AMOUNT = "gstr3b_liability_discharged_amount"

    RCM_CATEGORY_ALLEGED = "rcm_category_alleged"
    RCM_VALUE_ALLEGED_AMOUNT = "rcm_value_alleged_amount"
    RCM_TAX_ALLEGED_AMOUNT = "rcm_tax_alleged_amount"

    FRAUD_BASIS_ALLEGED = "fraud_basis_alleged"
    DEPARTMENT_ALLEGED_AMOUNT = "department_alleged_amount"
    FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT = "fraud_penalty_proposed_alleged_amount"
    LIMITATION_BASIS = "limitation_basis"

    GOODS_DESCRIPTION = "goods_description"
    VEHICLE_NUMBER = "vehicle_number"
    DETENTION_OR_SEIZURE_DATE = "detention_or_seizure_date"
    SECTION129_NOTICE_OR_SERVICE_DATE = "section129_notice_or_service_date"
    SEC129_PENALTY_PROPOSED_AMOUNT = "sec129_penalty_proposed_amount"
    GOODS_VALUE_OR_TAX_PAYABLE = "goods_value_or_tax_payable"
    OWNER_CAME_FORWARD_STATUS = "owner_came_forward_status"
    EXPLICIT_PROCEDURAL_DATE = "explicit_procedural_date"
    ORDER_DATE_OR_ENFORCEMENT_STATUS = "order_date_or_enforcement_status"


# --- Phase 2 Step 6.3 enum (ARCHITECTURE_SPEC_v1_1 §18.1) -------------------

class SourceTextOrigin(Enum):
    """How source text entered Dwaar; independent from legal/fact status."""

    EMBEDDED = "embedded"
    OCR = "ocr"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class SourceVerificationStatus(Enum):
    """Whether the extraction channel is filing-grade verified."""

    VERIFIED = "verified"
    REQUIRES_VERIFICATION = "requires_verification"


class FactExtractionStatus(Enum):
    """Additive fact-extraction outcome channel (ARCHITECTURE_SPEC_v1_1 §18.1).

    Distinguishes successful extraction (including a genuinely empty facts
    list) from partial or failed extraction, so downstream preflight never
    draws absence-based conclusions from a non-successful extraction
    (§18.3). Values follow the repo convention: lowercase member names.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_INPUT = "no_input"


# --- 3.2 Core Data Objects -------------------------------------------------

@dataclass
class ExtractedFact:
    fact_id: str  # F-001, F-002, ...
    claim: str  # What is being stated
    status: FactStatus
    source_text: Optional[str] = None  # Exact text from notice
    source_page: Optional[int] = None
    allowed_in_draft: DraftPermission = DraftPermission.CONDITIONAL
    # §17.2: additive Step 6.1 field, placed after the original six fields
    # with a default so all pre-Step-6.1 construction forms remain
    # backward compatible.
    fact_type: FactType = FactType.OTHER_NOTICE_FACT
    # §19.3: additive Step 6.4 field, placed last with a default so all
    # prior construction forms remain backward compatible.
    fact_role: FactRole = FactRole.NONE
    # Phase 3A.2: extraction-channel trust is independent from FactStatus.
    source_origin: SourceTextOrigin = SourceTextOrigin.EMBEDDED
    source_verification: SourceVerificationStatus = (
        SourceVerificationStatus.VERIFIED
    )


@dataclass
class DocumentPageText:
    """One physical PDF page after embedded-text/OCR ingestion."""

    page_number: int
    text: str
    origin: SourceTextOrigin
    verification: SourceVerificationStatus
    ocr_language: Optional[str] = None
    ocr_dpi: Optional[int] = None


@dataclass
class DeadlineResult:
    notice_date: Optional[date]
    service_date: Optional[date]  # None if not in notice
    response_period_days: Optional[int]
    response_deadline: Optional[date]  # None if service date unknown
    deadline_confidence: DeadlineConfidence
    deadline_status: DeadlineStatus
    days_remaining: Optional[int]  # None if deadline unknown
    hearing_date: Optional[date]
    hearing_status: HearingStatus
    portal_verification_required: bool
    notes: List[str] = field(default_factory=list)


@dataclass
class EvidenceGap:
    item: str  # What is needed
    why_it_matters: str  # Why the CA needs it
    status: str = "REQUIRES VERIFICATION"


@dataclass
class PotentialDefence:
    name: str
    legal_basis: str  # Section / rule
    argument: str
    facts_required: List[str]
    evidence_required: List[str]
    strength: str  # "Cannot assess yet" / Strong / Moderate / Weak
    limitations: str
    case_law_note: str = "[CA LEGAL RESEARCH REQUIRED]"


@dataclass
class ValidationCheck:
    rule_id: str
    description: str
    passed: bool
    message: str


@dataclass
class ValidationResult:
    overall_passed: bool
    checks: List[ValidationCheck]
    warnings: List[str]


@dataclass
class NoticeAnalysis:
    """The full structured output of one notice analysis.
    This is what gets rendered by app.py.
    """

    # Identification
    proceeding_type: ProceedingType
    notice_date: Optional[date]
    notice_reference: Optional[str]
    issuing_authority: Optional[str]
    taxpayer_name: Optional[str]
    gstin: Optional[str]
    tax_period: Optional[str]
    sections_cited: List[str]
    reply_form: Optional[str]

    # Core outputs
    facts: List[ExtractedFact]
    deadlines: DeadlineResult
    allegations: List[str]
    evidence_gaps: List[EvidenceGap]
    potential_defences: List[PotentialDefence]

    # Generated text
    notice_summary: str
    required_action: str
    draft_reply: str
    client_whatsapp: str

    # Meta
    validation: ValidationResult
    raw_text_chars: int
    today: date
    analysis_timestamp: datetime


# --- Phase 2 Step 2.5 dataclasses (ARCHITECTURE_SPEC_v1_1 §5.4) -------------

@dataclass
class NoticeClassification:
    """Final notice classification output (ARCHITECTURE_SPEC_v1_1 §5.4).

    Pure data contract — no classifier logic, no registry, no LLM here.
    classification_reasons holds concise, marker-based audit/debug reasons.
    """

    notice_family: NoticeFamily
    notice_form: NoticeForm
    proceeding_type: ProceedingType
    support_level: SupportLevel
    confidence: ClassificationConfidence
    classification_reasons: List[str]


# --- Phase 2 Step 6.3 dataclass (ARCHITECTURE_SPEC_v1_1 §18.2) ---------------

@dataclass
class FactExtractionResult:
    """Additive extraction outcome wrapper (ARCHITECTURE_SPEC_v1_1 §18.2).

    The backward-compatible `extract_facts` returns exactly this object's
    `facts`. The status channel exists so downstream preflight can
    distinguish successful from partial/failed extraction (§18.3). Pure
    data contract only — no provider exception strings, no API internals,
    no raw error objects.
    """

    facts: List[ExtractedFact]
    status: FactExtractionStatus
    rejected_item_count: int = 0


# --- Phase 2 Step 7.1 enums (ARCHITECTURE_SPEC_v1_1 §18.9, §18.17) ----------

class DeadlineConflictStatus(Enum):
    """Comparison between a stated due date and the calculated deadline
    (ARCHITECTURE_SPEC_v1_1 §18.9).

    Date comparison only — there is deliberately no VALID / INVALID member:
    this enum never decides legal validity or correctness.
    """

    MATCH = "match"
    CONFLICT = "conflict"
    CANNOT_COMPARE = "cannot_compare"


class ArithmeticCalculationType(Enum):
    """Approved deterministic arithmetic calculations (ARCHITECTURE_SPEC_v1_1
    §18.17 / §18.23).

    The Phase 2 whitelist is exactly these two reconciliation differences.
    Statutory penalty, RCM and interest calculations are deliberately
    absent until a future verified legal-rule subsystem.
    """

    ITC_DIFFERENCE = "itc_difference"
    OUTPUT_TAX_DIFFERENCE = "output_tax_difference"


# --- Phase 2 Step 7.1 dataclasses (ARCHITECTURE_SPEC_v1_1 §18.13, §18.18–18.21)

@dataclass
class PreflightResult:
    """Deterministic preflight output (ARCHITECTURE_SPEC_v1_1 §18.13).

    Exactly twelve fields. Deliberately NO legal-validity fields: this
    dataclass never contains notice_valid, notice_invalid,
    jurisdiction_valid or officer_competent.
    """

    fact_extraction_status: FactExtractionStatus

    communication_identifier_status: CommunicationIdentifierStatus
    portal_verification_required: bool

    authority_details_status: AuthorityDetailsStatus
    authority_verification_required: bool

    stated_due_date_fact_ids: List[str]
    parsed_stated_due_dates: List[date]
    unparsed_stated_due_date_fact_ids: List[str]

    deadline_conflict_status: DeadlineConflictStatus

    hearing_fact_ids: List[str]
    requested_document_fact_ids: List[str]
    referenced_annexure_fact_ids: List[str]


@dataclass
class ArithmeticOperand:
    """One side of an arithmetic request (ARCHITECTURE_SPEC_v1_1 §18.18).

    `value_text` must be an exact substring of the referenced fact's
    source_text — the arithmetic layer validates that provenance, it does
    not guess which token to use. No parsed Decimal, no semantic role, no
    currency field here.
    """

    source_fact_id: str
    value_text: str


@dataclass
class ArithmeticRequest:
    """Explicit arithmetic request (ARCHITECTURE_SPEC_v1_1 §18.19).

    Operand ordering is authoritative: ITC_DIFFERENCE is GSTR-3B (left) −
    GSTR-2B (right); OUTPUT_TAX_DIFFERENCE is GSTR-1 (left) − GSTR-3B
    (right). The engine computes left − right; it never infers roles.
    """

    calculation_type: ArithmeticCalculationType
    left_operand: ArithmeticOperand
    right_operand: ArithmeticOperand


@dataclass
class ArithmeticResult:
    """Deterministic arithmetic output (ARCHITECTURE_SPEC_v1_1 §18.21).

    Semantically inferred/derived, but NOT an ExtractedFact: no fact_id,
    no FactStatus, no source_text/source_page. Draft use is CONDITIONAL by
    default; the later Validation Engine controls its drafting use.
    """

    calculation_type: ArithmeticCalculationType
    status: ArithmeticStatus

    source_fact_ids: List[str]
    operand_values: List[Decimal]

    result: Optional[Decimal]
    formula: str

    currency: str = "INR"

    allowed_in_draft: DraftPermission = DraftPermission.CONDITIONAL


# --- Phase 2 Step 8.1 enums (ARCHITECTURE_SPEC_v1_1 §19.9, §19.10, §19.17,
#     §19.20, §19.22, §19.33) ------------------------------------------------

class RequirementStatus(Enum):
    """Workflow-requirement resolution state (ARCHITECTURE_SPEC_v1_1 §19.9).

    Exactly the five §19.9 members. No NOT_APPLICABLE in Phase 2.
    """

    SATISFIED = "satisfied"
    DERIVED = "derived"
    REQUIRES_VERIFICATION = "requires_verification"
    UNKNOWN = "unknown"
    MISSING = "missing"


class RequirementKind(Enum):
    """Workflow-requirement kind (ARCHITECTURE_SPEC_v1_1 §19.10)."""

    FACT = "fact"
    DERIVED = "derived"


class EvidenceStatus(Enum):
    """Evidence-checklist item state (ARCHITECTURE_SPEC_v1_1 §19.17).

    The current Step-8 "emit UNKNOWN only" behavior is deliberately NOT
    encoded here — it belongs to Step 8.4.
    """

    UNKNOWN = "unknown"
    PRESENT = "present"
    MISSING = "missing"
    REQUIRES_VERIFICATION = "requires_verification"


class ReviewLevel(Enum):
    """Mandatory human review level (ARCHITECTURE_SPEC_v1_1 §19.20)."""

    CA_REVIEW = "ca_review"
    SENIOR_CA_OR_ADVOCATE = "senior_ca_or_advocate"
    URGENT_CA_REVIEW = "urgent_ca_review"


class DraftEligibility(Enum):
    """Specialist-drafting gate (ARCHITECTURE_SPEC_v1_1 §19.22).

    A drafting gate only — none of these members means filing approved,
    legally valid, or CA review unnecessary. Interpretation (aggregation)
    belongs to later steps.
    """

    ALLOWED = "allowed"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class SpecialRuleHandling(Enum):
    """How a workflow special rule is handled (ARCHITECTURE_SPEC_v1_1 §19.33).

    A special rule may map to one or more handling types; every
    safety-critical special rule has at least one mapping.
    """

    DETERMINISTIC_CHECK = "deterministic_check"
    REVIEW_GATE = "review_gate"
    UPSTREAM_INVARIANT = "upstream_invariant"
    FUTURE_LEGAL_RULE = "future_legal_rule"


# --- Phase 2 Step 8.1 dataclasses (ARCHITECTURE_SPEC_v1_1 §19.11, §19.12,
#     §19.18, §19.21, §19.23, §19.24, §19.34) --------------------------------

@dataclass
class WorkflowRequirementSpec:
    """One workflow completeness requirement (ARCHITECTURE_SPEC_v1_1 §19.11).

    A FACT requirement selects facts by `fact_type` and/or `fact_role`; a
    DERIVED requirement selects arithmetic by `calculation_type`. No
    claim-text matching. `requirement_text` MUST equal the corresponding
    workflow `required_facts` string verbatim.
    """

    requirement_id: str
    requirement_text: str
    kind: RequirementKind

    fact_type: Optional[FactType] = None
    fact_role: Optional[FactRole] = None
    calculation_type: Optional[ArithmeticCalculationType] = None

    accepted_fact_statuses: Tuple[FactStatus, ...] = (FactStatus.CONFIRMED,)
    absent_on_success: RequirementStatus = RequirementStatus.MISSING


@dataclass
class RequirementResult:
    """Result of resolving one requirement (ARCHITECTURE_SPEC_v1_1 §19.12).

    No free-form LLM explanation field.
    """

    requirement_id: str
    requirement_text: str
    status: RequirementStatus
    related_fact_ids: List[str]
    calculation_type: Optional[ArithmeticCalculationType] = None


@dataclass
class EvidenceChecklistItem:
    """One workflow evidence checklist entry (ARCHITECTURE_SPEC_v1_1 §19.18).

    `requirement_text` must equal the workflow `evidence_requirements`
    string verbatim. During current Phase 2 Step 8: status = UNKNOWN for
    all.
    """

    evidence_id: str
    requirement_text: str
    status: EvidenceStatus


@dataclass
class ReviewRequirement:
    """One mandatory human review requirement (ARCHITECTURE_SPEC_v1_1 §19.21).

    No filing decision field.
    """

    review_id: str
    level: ReviewLevel
    reason: str
    mandatory: bool = True


@dataclass
class ValidationItem:
    """One deterministic Step-8 validation check (ARCHITECTURE_SPEC_v1_1
    §19.23).

    Status is ValidationStatus (PASS / WARNING / FAIL) — product/workflow
    safety state, never a legal conclusion. Messages are deterministic
    static templates; no LLM text generation.
    """

    check_id: str
    status: ValidationStatus
    message: str
    related_fact_ids: List[str]
    related_calculation_types: List[ArithmeticCalculationType]


@dataclass
class ValidationEngineResult:
    """Aggregated Step-8 validation output (ARCHITECTURE_SPEC_v1_1 §19.24).

    Exactly seven fields. Deliberately NO PotentialDefence and NO
    legal-validity fields.
    """

    overall_status: ValidationStatus
    draft_eligibility: DraftEligibility
    case_severity: Optional[IssueSeverity]

    checks: List[ValidationItem]
    requirements: List[RequirementResult]
    evidence_checklist: List[EvidenceChecklistItem]
    review_requirements: List[ReviewRequirement]


@dataclass
class WorkflowValidationProfile:
    """Static per-workflow validation mapping (ARCHITECTURE_SPEC_v1_1 §19.34).

    `special_rule_handling` / `review_rules` indices are zero-based indices
    into the workflow's exact `special_rules` list. Every special-rule
    index must be mapped. Pure data contract — no execution logic.
    """

    proceeding_type: ProceedingType
    requirement_specs: List[WorkflowRequirementSpec]
    special_rule_handling: Dict[int, Tuple[SpecialRuleHandling, ...]]
    review_rules: Dict[int, ReviewLevel]


# --- Phase 2 Step 9.1 enums (ARCHITECTURE_SPEC_v1_1 §20.20) -------------------

class DraftGenerationStatus(Enum):
    """Specialist drafting generation outcome (ARCHITECTURE_SPEC_v1_1 §20.20).

    Exactly the three §20.20 members. Stable machine-contract values: no
    aliases and no generic UNKNOWN member.
    """

    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"


class DraftFailureCode(Enum):
    """Specialist drafting failure channel (ARCHITECTURE_SPEC_v1_1 §20.20).

    Exactly the six §20.20 members. Stable machine-contract values: no
    aliases, no generic UNKNOWN and no RETRY_EXHAUSTED.
    """

    VALIDATION_REQUIRED = "validation_required"
    DRAFT_BLOCKED = "draft_blocked"
    WORKFLOW_UNAVAILABLE = "workflow_unavailable"
    LLM_ERROR = "llm_error"
    MALFORMED_RESPONSE = "malformed_response"
    POST_VALIDATION_FAILED = "post_validation_failed"


class DraftBlockKind(Enum):
    """Closed provenance-complete draft block kinds (§25.3)."""

    STATIC = "static"
    FACT = "fact"
    ARITHMETIC = "arithmetic"
    DEADLINE = "deadline"
    HEARING = "hearing"
    REQUIREMENT = "requirement"
    EVIDENCE = "evidence"
    REVIEW = "review"


# --- Phase 2 Step 9.1 dataclasses (ARCHITECTURE_SPEC_v1_1 §20.20) -------------

@dataclass
class DraftSectionSpec:
    """One architecture-owned drafting section identity (§20.20).

    Stable one-based machine ID plus the exact workflow output_structure
    title. Pure data contract — no template or prompt content.
    """

    section_id: str
    title: str


@dataclass
class WorkflowDraftingProfile:
    """Static per-workflow drafting mapping (ARCHITECTURE_SPEC_v1_1 §20.19,
    §20.21, §20.22).

    Maps one deep proceeding type to ordered drafting section specs and a
    closed prompt key. Pure data contract — no prompt text, no filenames,
    no LLM access.
    """

    proceeding_type: ProceedingType
    sections: Tuple[DraftSectionSpec, ...]
    prompt_key: str


# --- Phase 2 Step 9E.1 candidate contracts (ARCHITECTURE_SPEC_v1_1 §25) -------

@dataclass
class StaticDraftBlock:
    template_id: str


@dataclass
class FactDraftBlock:
    fact_id: str


@dataclass
class ArithmeticDraftBlock:
    arithmetic_index: int


@dataclass
class DeadlineDraftBlock:
    pass


@dataclass
class HearingDraftBlock:
    pass


@dataclass
class RequirementDraftBlock:
    requirement_id: str


@dataclass
class EvidenceDraftBlock:
    evidence_id: str


@dataclass
class ReviewDraftBlock:
    review_id: str


DraftCandidateBlock = Union[
    StaticDraftBlock,
    FactDraftBlock,
    ArithmeticDraftBlock,
    DeadlineDraftBlock,
    HearingDraftBlock,
    RequirementDraftBlock,
    EvidenceDraftBlock,
    ReviewDraftBlock,
]


@dataclass
class DraftCandidateSection:
    section_id: str
    blocks: Tuple[DraftCandidateBlock, ...]


@dataclass
class DraftSection:
    """One provenance-complete rendered draft section (§25.5)."""

    section_id: str
    title: str
    rendered_text: str


@dataclass
class DraftPostValidationResult:
    """Deterministic post-draft validation output (ARCHITECTURE_SPEC_v1_1
    §20.20, §20.30).

    Structural / reference / lexical safety validation only — never general
    semantic legal-prose understanding (§20.27).
    """

    overall_status: ValidationStatus
    checks: List[ValidationItem]


@dataclass
class SpecialistDraftResult:
    """Closed specialist drafting result (ARCHITECTURE_SPEC_v1_1 §20.20).

    Exactly nine fields, every field caller-supplied: no implicit defaults
    and no default_factory. Optional fields must be explicitly passed as
    None when absent. All metadata surfaces are Python-owned (§20.38);
    deliberately no filing_approved / legally_valid / liability_confirmed
    fields.
    """

    status: DraftGenerationStatus
    draft_eligibility: DraftEligibility
    sections: List[DraftSection]
    unresolved_requirements: List[RequirementResult]
    evidence_checklist: List[EvidenceChecklistItem]
    review_requirements: List[ReviewRequirement]
    post_validation: Optional[DraftPostValidationResult]
    failure_code: Optional[DraftFailureCode]
    error_message: Optional[str]


# --- Phase 2 Step 10.1 dataclasses (ARCHITECTURE_SPEC_v1_1 §24.5–§24.6) ----

@dataclass
class TriageSummary:
    proceeding_type: ProceedingType
    notice_form: NoticeForm
    support_level: SupportLevel
    classification_confidence: ClassificationConfidence
    extraction_status: FactExtractionStatus
    portal_verification_required: bool
    authority_verification_required: bool
    communication_identifier_status: CommunicationIdentifierStatus
    authority_details_status: AuthorityDetailsStatus
    deadline_status: DeadlineStatus
    hearing_status: HearingStatus
    requested_document_fact_ids: List[str]
    referenced_annexure_fact_ids: List[str]
    message: str


@dataclass
class Phase2AnalysisResult:
    classification: NoticeClassification
    extraction_result: FactExtractionResult
    deadline_result: DeadlineResult
    preflight_result: PreflightResult
    arithmetic_results: List[ArithmeticResult]
    validation_result: ValidationEngineResult
    draft_result: SpecialistDraftResult
    triage_summary: Optional[TriageSummary]
