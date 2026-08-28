# CA Notice AI — Architecture Specification v1.0

> This document is the contract for all Phase 2+ development.
> Claude Code reads this before writing any Phase 2 code.
> No architectural decision may be reversed without updating this document first.

---

## 1. What This Product Is

**Current promise (MVP):**
> Upload a GST notice PDF → get a structured CA working paper with
> extracted facts, evidence gaps, potential issues, and a reviewable draft reply.

**Out of scope for now (do not build yet):**
- Income Tax notices
- Multi-tenant / multi-CA accounts
- Persistent database (SQLite comes later, Phase 3+)
- Web authentication / login
- DeepSeek as runtime provider (future option, not Phase 2)
- Legal knowledge database (Phase 3+)
- Case management UI (Phase 4+)

---

## 2. The Single Most Important Rule

```
DETERMINISTIC THINGS → PYTHON CODE
LANGUAGE / REASONING → LLM
```

| Task | Who Does It |
|---|---|
| Date arithmetic, deadline calculation | Python only — never LLM |
| Percentage / monetary calculations | Python only |
| Notice form identification (DRC-01, MOV-09) | LLM + Python validation |
| Proceeding type classification | LLM (small focused call) |
| Fact extraction with provenance | LLM → structured objects |
| Evidence gap identification | Workflow config + LLM |
| Generating arguments / draft prose | LLM |
| Validating output before display | Python rules engine |
| Storing facts, provenance, status | Python data structures |
| Case law citations | Never — CA must verify |

---

## 3. Domain Models

All models live in `domain/models.py`.
Pure Python dataclasses and enums. Zero external dependencies. Zero LLM calls.

### 3.1 Enums

```python
from enum import Enum

class ProceedingType(Enum):
    GST_SEC73_GENERAL    = "gst_sec73_general"
    GST_SEC73_ITC        = "gst_sec73_itc"
    GST_SEC73_RCM        = "gst_sec73_rcm"
    GST_SEC74_FRAUD      = "gst_sec74_fraud"
    GST_SEC129_ENFORCE   = "gst_sec129_enforcement"
    UNKNOWN              = "unknown"

class FactStatus(Enum):
    CONFIRMED            = "confirmed"       # Explicitly in notice
    ALLEGED              = "alleged"         # Department's claim only
    UNKNOWN              = "unknown"         # Not in notice, not verified
    REQUIRES_VERIFICATION = "requires_verification"  # CA must check
    INFERRED             = "inferred"        # Calculated/derived

class DraftPermission(Enum):
    YES                  = "yes"             # Can state as fact in draft
    CONDITIONAL          = "conditional"     # Only with [CA TO CONFIRM] wrapper
    NO                   = "no"              # Must not appear in draft

class DeadlineConfidence(Enum):
    CONFIRMED            = "confirmed"       # Service date known
    ESTIMATED            = "estimated"       # Assuming service = notice date
    UNKNOWN              = "unknown"         # Cannot determine

class DeadlineStatus(Enum):
    UPCOMING             = "upcoming"
    CRITICAL             = "critical"        # Within 7 days
    PASSED               = "passed"          # Deadline gone
    UNKNOWN              = "unknown"

class HearingStatus(Enum):
    UPCOMING             = "upcoming"
    TODAY                = "today"
    PASSED               = "passed"
    NOT_SCHEDULED        = "not_scheduled"

class IssueSeverity(Enum):
    CRITICAL             = "critical"        # 100% penalty / fraud / expired
    HIGH                 = "high"            # Large demand / urgent deadline
    MEDIUM               = "medium"          # Standard demand / moderate deadline
    LOW                  = "low"             # Minor / routine

class ValidationStatus(Enum):
    PASS                 = "pass"
    FAIL                 = "fail"
    WARNING              = "warning"
```

### 3.2 Core Data Objects

```python
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import date, datetime

@dataclass
class ExtractedFact:
    fact_id: str                            # F-001, F-002, ...
    claim: str                              # What is being stated
    status: FactStatus
    source_text: Optional[str] = None      # Exact text from notice
    source_page: Optional[int] = None
    allowed_in_draft: DraftPermission = DraftPermission.CONDITIONAL

@dataclass
class DeadlineResult:
    notice_date: Optional[date]
    service_date: Optional[date]            # None if not in notice
    response_period_days: Optional[int]
    response_deadline: Optional[date]       # None if service date unknown
    deadline_confidence: DeadlineConfidence
    deadline_status: DeadlineStatus
    days_remaining: Optional[int]           # None if deadline unknown
    hearing_date: Optional[date]
    hearing_status: HearingStatus
    portal_verification_required: bool
    notes: List[str] = field(default_factory=list)

@dataclass
class EvidenceGap:
    item: str                               # What is needed
    why_it_matters: str                     # Why the CA needs it
    status: str = "REQUIRES VERIFICATION"

@dataclass
class PotentialDefence:
    name: str
    legal_basis: str                        # Section / rule
    argument: str
    facts_required: List[str]
    evidence_required: List[str]
    strength: str                           # "Cannot assess yet" / Strong / Moderate / Weak
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
    """
    The full structured output of one notice analysis.
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
```

---

## 4. Component Architecture

### 4.1 Proceeding Classifier (`domain/proceeding_classifier.py`)

**Input:** Raw notice text (string)
**Output:** `ProceedingType` enum value
**LLM call:** Yes — one small, focused call only
**Purpose:** Identify WHAT TYPE of notice this is before any analysis begins

Rules:
- Must return one of the defined `ProceedingType` values
- If uncertain → return `UNKNOWN`
- Classification drives workflow selection — everything downstream depends on it
- Never skip classification and go straight to analysis

### 4.2 Deadline Engine (`domain/deadline_engine.py`)

**Input:** notice_date, service_date (optional), response_period_text, hearing_date_text, today
**Output:** `DeadlineResult` dataclass
**LLM call:** NEVER — pure Python only
**Purpose:** All date arithmetic, deadline status, days remaining

Rules:
- If service_date is None → deadline confidence = ESTIMATED, note it clearly
- If response_period text says "from date of service" and service date unavailable:
  → response_deadline = None, confidence = UNKNOWN
- days_remaining = None if deadline unknown
- Portal verification required = True whenever deadline has passed or is unknown

### 4.3 Fact Engine (`domain/fact_engine.py`)

**Input:** Raw notice text, proceeding type
**Output:** `List[ExtractedFact]`
**LLM call:** Yes — focused fact extraction call
**Purpose:** Extract every material fact, label each with status and source

Rules:
- Every amount in the notice → CONFIRMED + source_text
- Every allegation → ALLEGED
- Any taxpayer fact not stated in notice → UNKNOWN
- allowed_in_draft = YES only for CONFIRMED facts
- allowed_in_draft = CONDITIONAL for ALLEGED (must use [CA TO CONFIRM] wrapper)
- allowed_in_draft = NO for UNKNOWN

### 4.4 Workflow Engine (`domain/workflow_engine.py`)

**Input:** `ProceedingType`
**Output:** `WorkflowDefinition` (required facts list, evidence gaps, issue types, output structure)
**LLM call:** Never
**Purpose:** Load the correct workflow definition for the classified proceeding

### 4.5 Reasoning Engine (`modules/llm_client.py` — existing)

**Input:** Structured prompt built from facts + workflow + proceeding type
**Output:** Text sections (summary, required action, defences, draft, client message)
**LLM call:** Yes — this is the main analysis call
**Purpose:** Language reasoning, draft generation, argument articulation
**Constraint:** Only receives CONFIRMED and ALLEGED facts — never UNKNOWN as if confirmed

### 4.6 Validation Engine (`domain/validation_engine.py`)

**Input:** `NoticeAnalysis` object
**Output:** `ValidationResult`
**LLM call:** Never — pure Python rules
**Purpose:** Check output quality before display

Validation rules (minimum):
- [ ] Every amount has a source fact
- [ ] No UNKNOWN fact appears as confirmed in draft
- [ ] Deadline result has confidence label
- [ ] If deadline passed → CRITICAL warning present
- [ ] If fraud/Section 74 → severity = CRITICAL
- [ ] Draft contains CA ACTION REQUIRED footer
- [ ] No detected citation patterns (r"\d+/\d+/20\d\d") unless in quotes from notice

---

## 5. GST Workflow Taxonomy — Phase 2 Scope

Five workflows. Implement in this order.

### 5.1 GST-73-ITC — ITC Mismatch (Priority 1)
```
Trigger:       DRC-01 + Section 73 + Section 16(2)(aa) / Rule 36(4)
Form:          DRC-01 → Reply in DRC-06
Required facts:
  - ITC claimed in GSTR-3B (amount)
  - ITC in GSTR-2B (amount)
  - Difference (INFERRED: 3B minus 2B)
  - FY / tax period
  - Interest proposed
Required evidence:
  - GSTR-2B for all months in period
  - GSTR-3B ITC tables
  - Invoice-level reconciliation
  - Supplier GSTR-1 filing status
  - Bank payment proof to suppliers
Key issues:    ITC_MISMATCH, SUPPLIER_DEFAULT, INTEREST_COMPUTATION
Output:        Working paper + ITC reconciliation table template + DRC-06 draft
```

### 5.2 GST-73-GENERAL — General Tax Short-Payment (Priority 1)
```
Trigger:       DRC-01 + Section 73 (output tax mismatch, GSTR-1 vs 3B)
Form:          DRC-01 → Reply in DRC-06
Required facts:
  - Tax declared in GSTR-1
  - Tax paid in GSTR-3B
  - Difference (INFERRED)
  - Interest proposed
Required evidence:
  - Monthly GSTR-1 and GSTR-3B
  - GSTR-9 annual return
  - Credit notes / amendments
Key issues:    SHORT_PAYMENT, GSTR_MISMATCH, INTEREST_COMPUTATION
Output:        Working paper + month-wise reconciliation table + DRC-06 draft
```

### 5.3 GST-73-RCM — Reverse Charge Non-Compliance (Priority 1)
```
Trigger:       DRC-01 + Section 73 + Section 9(3) / RCM / Notification 13/2017
Form:          DRC-01 → Reply in DRC-06
Required facts:
  - Service type (advocate / GTA / import)
  - Value of services received
  - RCM tax not paid
  - Interest proposed
Required evidence:
  - Invoices from unregistered / RCM-covered suppliers
  - Form 26AS (TDS data) if advocates
  - GSTR-3B table 3.1(d) for period
Key issues:    RCM_LIABILITY, ITC_REVERSAL, INTEREST_COMPUTATION
Output:        Working paper + DRC-06 draft with RCM submissions
```

### 5.4 GST-74-FRAUD — Fraud / Suppression (Priority 1)
```
Trigger:       DRC-01 + Section 74 (any mention of fraud / suppression / wilful misstatement)
Form:          DRC-01 → Reply in DRC-06
Severity:      CRITICAL always — 100% penalty exposure
Required facts:
  - Basis of fraud allegation (bank data / RERA / third-party)
  - Undisclosed turnover alleged (ALLEGED only)
  - Extended limitation period invoked (5 years)
  - 100% penalty proposed (ALLEGED)
Required evidence:
  - Books of accounts
  - Bank statements
  - All filed returns for period
  - Any correspondence with department
  - If RERA — project documents, completion certificates
Key issues:    FRAUD_ALLEGATION, SUPPRESSION, PENALTY_100PCT, LIMITATION_5YR
Special rules:
  - NEVER soften fraud allegation in analysis
  - NEVER state fraud is absent without source
  - Escalate to senior CA / advocate immediately
Output:        Urgent working paper + escalation note + conditional DRC-06 draft
```

### 5.5 GST-129-ENFORCEMENT — Detention / E-Way Bill (Priority 1)
```
Trigger:       MOV-09 or Section 129 or Section 130 or E-Way Bill detention
Form:          MOV-09 → Reply in MOV-09 / DRC-06
Deadline:      7 days (URGENT — always CRITICAL if approaching / passed)
Required facts:
  - Goods description
  - Vehicle number
  - Detention date
  - Tax amount (CONFIRMED from notice)
  - Penalty amount (CONFIRMED — 100% of tax for Section 129)
Required evidence:
  - Tax invoice for goods
  - E-Way Bill (or reason it was absent)
  - Inspection / detention order (MOV-06)
  - GRN / delivery documents
Key issues:    EWAY_BILL_ABSENT, DETENTION, URGENT_DEADLINE, PENALTY_100PCT
Special rules:
  - Deadline is 7 days from service — always flag CRITICAL if within 7 days
  - Never assume invoice was "valid" — mark as REQUIRES_VERIFICATION
  - Never invent reason for missing e-way bill
Output:        URGENT working paper + 7-day deadline alert + MOV-09 reply draft
```

---

## 6. Target Folder Structure (End of Phase 2)

```
ca-ai-tool/
├── app.py                          # Streamlit UI — thin wrapper only
├── AGENTS.md
├── PROJECT_MEMORY.md
├── requirements.txt
├── .env
├── .gitignore
│
├── domain/                         # NEW Phase 2 — pure Python, no LLM
│   ├── __init__.py
│   ├── models.py                   # All dataclasses and enums
│   ├── proceeding_classifier.py    # LLM call — classify notice type
│   ├── deadline_engine.py          # Pure Python — all date arithmetic
│   ├── fact_engine.py              # LLM call — extract + label facts
│   └── validation_engine.py       # Pure Python — output quality rules
│
├── workflows/                      # NEW Phase 2 — workflow definitions
│   ├── __init__.py
│   └── gst/
│       ├── __init__.py
│       ├── base.py                 # WorkflowDefinition base class
│       ├── sec73_itc.py            # ITC mismatch workflow
│       ├── sec73_general.py        # General short-payment workflow
│       ├── sec73_rcm.py            # RCM workflow
│       ├── sec74_fraud.py          # Fraud/suppression workflow
│       └── sec129_enforcement.py  # Detention/e-way bill workflow
│
├── modules/                        # EXISTING — keep, modify minimally
│   ├── __init__.py
│   ├── pdf_reader.py               # Unchanged
│   ├── llm_client.py               # Keep public API — wire to domain
│   ├── llm_router.py               # Unchanged
│   └── notice_explainer.py        # Refactor — orchestrate domain layer
│
├── prompts/                        # Refactor — one prompt per workflow
│   ├── base_rules.txt              # Shared evidence discipline rules
│   └── gst/
│       ├── sec73_itc.txt
│       ├── sec73_general.txt
│       ├── sec73_rcm.txt
│       ├── sec74_fraud.txt
│       └── sec129_enforcement.txt
│
├── tests/
│   ├── run_regression.py           # Existing
│   ├── test_llm_router.py          # Existing
│   ├── test_deadline_engine.py     # NEW Phase 2
│   ├── test_classifier.py          # NEW Phase 2
│   ├── test_validation_engine.py   # NEW Phase 2
│   ├── baselines/
│   ├── expectations/
│   └── outputs/
│
├── data/
│   └── sample_notices/
│
└── docs/
    ├── architecture/
    │   ├── ARCHITECTURE_SPEC_v1.md  # This document
    │   ├── CURRENT_ARCHITECTURE_AUDIT.md
    │   └── LLM_ROUTING.md
    └── testing/
        └── REGRESSION_STRATEGY.md
```

---

## 7. Implementation Sequence — Phase 2

**Do not skip steps. Do not combine steps. Each step must pass before the next begins.**

```
STEP 1 — domain/models.py
  Create all enums and dataclasses.
  Zero external deps. Confirm: python -c "from domain.models import *; print('OK')"
  No wiring to app. No LLM.

STEP 2 — domain/deadline_engine.py
  Pure Python. No LLM. No external deps.
  Input: notice_date, service_date, response_period_text, hearing_date_text, today
  Output: DeadlineResult
  Unit tests: test_deadline_engine.py — minimum 8 cases:
    (1) service date known, deadline future
    (2) service date known, deadline passed
    (3) service date unknown, "from date of service"
    (4) service date unknown, "from date of issue"
    (5) hearing date upcoming
    (6) hearing date passed
    (7) deadline within 7 days → CRITICAL
    (8) no date information at all
  All 8 tests must pass before Step 3.

STEP 3 — workflows/gst/ definitions
  Create base.py WorkflowDefinition dataclass.
  Create all 5 workflow files as Python objects (not YAML).
  Each workflow object contains: required_facts list, evidence_gaps list,
  issue_types list, severity, output_structure.
  No LLM. No wiring to app yet.

STEP 4 — domain/proceeding_classifier.py
  One focused LLM call. Classify notice → ProceedingType.
  Test on all 4 sample notices:
    NOTICE_1 → GST_SEC73_ITC
    NOTICE_2 → GST_SEC74_FRAUD
    NOTICE_3 → GST_SEC129_ENFORCE
    NOTICE_4 → GST_SEC73_RCM
  All 4 must classify correctly before Step 5.

STEP 5 — domain/fact_engine.py
  LLM call: extract facts from notice text → List[ExtractedFact]
  Each fact has: claim, status, source_text, allowed_in_draft
  Test on NOTICE_1: all monetary amounts must be CONFIRMED with source_text
  No UNKNOWN fact may have allowed_in_draft = YES

STEP 6 — domain/validation_engine.py
  Pure Python. Implement all validation rules from Section 4.6 above.
  test_validation_engine.py: test each rule passes and fails correctly.

STEP 7 — Refactor modules/notice_explainer.py
  Wire domain layer: pdf_reader → classifier → deadline_engine →
  workflow_engine → fact_engine → llm_client (reasoning) → validation_engine
  Return NoticeAnalysis object instead of raw dict.
  Run all 4 notices. All must succeed.

STEP 8 — Update app.py
  Display NoticeAnalysis sections from structured object.
  NOTICE_3 must show CRITICAL urgency and 7-day deadline automatically.
  NOTICE_2 must show CRITICAL severity for Section 74.

STEP 9 — Split prompts/notice_prompt.txt into workflow-specific prompts
  Do NOT delete notice_prompt.txt until all 5 workflow prompts are tested.
  Each workflow prompt is smaller and focused — no giant 8-section generic prompt.

STEP 10 — Run full regression on all 4 notices
  All must pass. Update baselines if output improved.
  Commit Phase 2.
```

---

## 8. What AGENTS.md Must Add (Dina Updates)

Add these to AGENTS.md KNOWN GOTCHAS after Phase 2 begins:

```
DOMAIN LAYER RULES:
- domain/ modules are pure Python — never import LLM packages there
- deadline_engine.py must NEVER call any LLM — dates are code's job
- validation_engine.py must NEVER call any LLM
- fact_engine.py returns ExtractedFact objects — never raw strings
- All LLM calls go through modules/llm_client.py only
- WorkflowDefinition objects are loaded from workflows/gst/ — never hardcoded in notice_explainer.py
```

---

## 9. The Prompt Architecture Rule

**After Phase 2, the prompt for each workflow call will be small.**

It receives:
- Proceeding type (known)
- Extracted facts (with status labels)
- Evidence gaps (from workflow definition)
- Deadline result (calculated by code)
- Today's date

It generates:
- Narrative summary
- Required action steps
- Potential defence arguments (conditional)
- Draft reply prose (using only permitted facts)
- Client WhatsApp message

It does NOT:
- Calculate dates
- Classify the proceeding
- Decide what evidence is needed
- Validate its own output

The LLM writes. Everything else is code.

---

*Document version: 1.0 — Created before Phase 2 coding begins*
*Update this document when any architectural decision changes*
*This document takes precedence over any conflicting instruction in a prompt*
