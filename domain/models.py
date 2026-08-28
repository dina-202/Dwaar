"""Typed domain models for CA Notice AI (docs/architecture/ARCHITECTURE_SPEC_v1.md §3).

Architecture Phase 2 — Step 1 artifact. Pure data contracts only.

- Standard library only (enum, dataclasses, typing, datetime).
- No business logic, no LLM calls, no Streamlit, no external dependencies.
- Not wired to the running application yet.
- Independently importable: this module imports nothing from the project.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional


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


# --- 3.2 Core Data Objects -------------------------------------------------

@dataclass
class ExtractedFact:
    fact_id: str  # F-001, F-002, ...
    claim: str  # What is being stated
    status: FactStatus
    source_text: Optional[str] = None  # Exact text from notice
    source_page: Optional[int] = None
    allowed_in_draft: DraftPermission = DraftPermission.CONDITIONAL


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
