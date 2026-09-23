"""Authoritative workflow validation profiles
(ARCHITECTURE_SPEC_v1_1 §19.16, §19.33–§19.39).

Static deterministic Step-8 mapping contracts: exactly one
WorkflowValidationProfile per deep ProceedingType, carrying the 29 §19.16
requirement mappings and the 24 §19.35–§19.39 special-rule mappings.

Every requirement_text below is the corresponding workflow required_facts
string verbatim, written out independently so later validation can detect
drift between the workflow definitions and these profiles. Special-rule
indices are zero-based indices into the workflow's exact special_rules
list; every index is mapped.

Pure static data plus one deterministic lookup. No validation behavior,
no LLM integration, no network access, no fallback.
"""

from typing import Dict, Optional

from domain.models import (
    ArithmeticCalculationType,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    RequirementKind,
    RequirementStatus,
    ReviewLevel,
    SpecialRuleHandling,
    WorkflowRequirementSpec,
    WorkflowValidationProfile,
)

# --- GST_SEC61_SCRUTINY -----------------------------------------------------

SEC61_SCRUTINY_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC61_SCRUTINY,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec61_scrutiny.r1",
            requirement_text=(
                "Discrepancy / issue stated by the department in "
                "FORM GST ASMT-10"
            ),
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.NONE,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec61_scrutiny.r2",
            requirement_text="FY / tax period under scrutiny",
            kind=RequirementKind.FACT,
            fact_type=FactType.TAX_PERIOD,
            fact_role=FactRole.NONE,
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec61_scrutiny.r3",
            requirement_text=(
                "Response period stated in the notice, where stated"
            ),
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.RESPONSE_PERIOD,
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        1: (SpecialRuleHandling.REVIEW_GATE,),
        2: (
            SpecialRuleHandling.UPSTREAM_INVARIANT,
            SpecialRuleHandling.REVIEW_GATE,
        ),
        3: (SpecialRuleHandling.REVIEW_GATE,),
        4: (SpecialRuleHandling.REVIEW_GATE,),
    },
    review_rules={
        1: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
        4: ReviewLevel.CA_REVIEW,
    },
)

# --- GST_SEC73_ITC (§19.16, §19.35) -----------------------------------------

SEC73_ITC_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC73_ITC,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec73_itc.r1",
            requirement_text="ITC claimed in GSTR-3B (amount)",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.GSTR3B_ITC_CLAIMED_AMOUNT,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_itc.r2",
            requirement_text="ITC reflected in GSTR-2B (amount)",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.GSTR2B_ITC_REFLECTED_AMOUNT,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_itc.r3",
            requirement_text="Difference between GSTR-3B and GSTR-2B (INFERRED)",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.ITC_DIFFERENCE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_itc.r4",
            requirement_text="FY / tax period",
            kind=RequirementKind.FACT,
            fact_type=FactType.TAX_PERIOD,
            fact_role=FactRole.NONE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_itc.r5",
            requirement_text="Interest proposed",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.INTEREST_PROPOSED_AMOUNT,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    review_rules={
        0: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
)

# --- GST_SEC73_GENERAL (§19.16, §19.36) -------------------------------------

SEC73_GENERAL_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC73_GENERAL,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec73_general.r1",
            requirement_text="Tax / liability declared in GSTR-1",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_general.r2",
            requirement_text="Tax / liability discharged in GSTR-3B",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_general.r3",
            requirement_text="Difference between GSTR-1 and GSTR-3B (INFERRED)",
            kind=RequirementKind.DERIVED,
            calculation_type=ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_general.r4",
            requirement_text="FY / tax period",
            kind=RequirementKind.FACT,
            fact_type=FactType.TAX_PERIOD,
            fact_role=FactRole.NONE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_general.r5",
            requirement_text="Interest proposed",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.INTEREST_PROPOSED_AMOUNT,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    review_rules={
        0: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
)

# --- GST_SEC73_RCM (§19.16, §19.37) -----------------------------------------

SEC73_RCM_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC73_RCM,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r1",
            requirement_text="Service / supply category alleged to attract RCM",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.RCM_CATEGORY_ALLEGED,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r2",
            requirement_text="Value of services / supplies alleged to be subject to RCM",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.RCM_VALUE_ALLEGED_AMOUNT,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r3",
            requirement_text="RCM tax alleged as unpaid or short-paid",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.RCM_TAX_ALLEGED_AMOUNT,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r4",
            requirement_text="FY / tax period",
            kind=RequirementKind.FACT,
            fact_type=FactType.TAX_PERIOD,
            fact_role=FactRole.NONE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec73_rcm.r5",
            requirement_text="Interest proposed",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.INTEREST_PROPOSED_AMOUNT,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.FUTURE_LEGAL_RULE, SpecialRuleHandling.REVIEW_GATE),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    review_rules={
        0: ReviewLevel.CA_REVIEW,
        1: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
)

# --- GST_SEC74_FRAUD (§19.16, §19.38) ---------------------------------------

SEC74_FRAUD_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC74_FRAUD,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec74_fraud.r1",
            requirement_text="Basis of fraud / wilful-misstatement / suppression allegation",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.FRAUD_BASIS_ALLEGED,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec74_fraud.r2",
            requirement_text="Turnover, tax, refund or ITC amount alleged by the department (ALLEGED unless independently established)",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.DEPARTMENT_ALLEGED_AMOUNT,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec74_fraud.r3",
            requirement_text="FY / tax period",
            kind=RequirementKind.FACT,
            fact_type=FactType.TAX_PERIOD,
            fact_role=FactRole.NONE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec74_fraud.r4",
            requirement_text="Penalty proposed in the notice (ALLEGED)",
            kind=RequirementKind.FACT,
            fact_type=FactType.DEPARTMENT_ALLEGATION,
            fact_role=FactRole.FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT,
            accepted_fact_statuses=(FactStatus.ALLEGED,),
        ),
        WorkflowRequirementSpec(
            requirement_id="sec74_fraud.r5",
            requirement_text="Limitation / extended-period basis invoked in the notice",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.LIMITATION_BASIS,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        1: (SpecialRuleHandling.REVIEW_GATE,),
        2: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
        4: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
    },
    review_rules={
        1: ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        3: ReviewLevel.SENIOR_CA_OR_ADVOCATE,
    },
)

# --- GST_SEC129_ENFORCE (§19.16, §19.39) ------------------------------------

SEC129_VALIDATION_PROFILE = WorkflowValidationProfile(
    proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
    requirement_specs=[
        WorkflowRequirementSpec(
            requirement_id="sec129.r1",
            requirement_text="Goods description",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.GOODS_DESCRIPTION,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r2",
            requirement_text="Vehicle / conveyance number",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.VEHICLE_NUMBER,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r3",
            requirement_text="Detention / seizure date",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.DETENTION_OR_SEIZURE_DATE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r4",
            requirement_text="Section 129 notice date and service date where available",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.SECTION129_NOTICE_OR_SERVICE_DATE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r5",
            requirement_text="Penalty amount proposed in the notice",
            kind=RequirementKind.FACT,
            fact_type=FactType.STATED_AMOUNT,
            fact_role=FactRole.SEC129_PENALTY_PROPOSED_AMOUNT,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r6",
            requirement_text="Value of goods and tax payable on the goods where stated and relevant to penalty computation",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.GOODS_VALUE_OR_TAX_PAYABLE,
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r7",
            requirement_text="Whether the owner of the goods has come forward, where relevant and determinable",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.OWNER_CAME_FORWARD_STATUS,
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r8",
            requirement_text="Explicit hearing / payment / response date stated in the notice or order",
            kind=RequirementKind.FACT,
            fact_type=None,
            fact_role=FactRole.EXPLICIT_PROCEDURAL_DATE,
        ),
        WorkflowRequirementSpec(
            requirement_id="sec129.r9",
            requirement_text="Order date / current enforcement status if an order has already been issued",
            kind=RequirementKind.FACT,
            fact_type=FactType.DOCUMENT_DETAIL,
            fact_role=FactRole.ORDER_DATE_OR_ENFORCEMENT_STATUS,
            absent_on_success=RequirementStatus.REQUIRES_VERIFICATION,
        ),
    ],
    special_rule_handling={
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.REVIEW_GATE,),
        2: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        3: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        4: (SpecialRuleHandling.REVIEW_GATE,),
        5: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        6: (
            SpecialRuleHandling.DETERMINISTIC_CHECK,
            SpecialRuleHandling.REVIEW_GATE,
        ),
    },
    review_rules={
        0: ReviewLevel.CA_REVIEW,
        1: ReviewLevel.CA_REVIEW,
        4: ReviewLevel.CA_REVIEW,
        6: ReviewLevel.URGENT_CA_REVIEW,
    },
)

# --- Deterministic lookup (§19.34) ------------------------------------------

VALIDATION_PROFILE_REGISTRY: Dict[ProceedingType, WorkflowValidationProfile] = {
    ProceedingType.GST_SEC61_SCRUTINY: SEC61_SCRUTINY_VALIDATION_PROFILE,
    ProceedingType.GST_SEC73_ITC: SEC73_ITC_VALIDATION_PROFILE,
    ProceedingType.GST_SEC73_GENERAL: SEC73_GENERAL_VALIDATION_PROFILE,
    ProceedingType.GST_SEC73_RCM: SEC73_RCM_VALIDATION_PROFILE,
    ProceedingType.GST_SEC74_FRAUD: SEC74_FRAUD_VALIDATION_PROFILE,
    ProceedingType.GST_SEC129_ENFORCE: SEC129_VALIDATION_PROFILE,
}


def get_validation_profile(
    proceeding_type: ProceedingType,
) -> Optional[WorkflowValidationProfile]:
    """Return the authoritative profile for a deep proceeding type, or
    None for UNKNOWN / unsupported types (no fallback, no "closest
    workflow").
    """
    return VALIDATION_PROFILE_REGISTRY.get(proceeding_type)
