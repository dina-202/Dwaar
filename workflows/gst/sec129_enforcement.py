"""GST_SEC129_ENFORCE deep workflow definition
(ARCHITECTURE_SPEC_v1_1 §10.3 Contract 5).

Static deterministic case-handling configuration for the Section 129
detention / movement-of-goods enforcement workflow: required facts,
evidence requirements, issue types, output structure and safety rules —
verbatim from the authoritative spec.

Current-law safety invariants encoded here: no hardcoded 100% penalty
assumption (the proposed penalty is extracted as a fact and statutory
computation is deferred to the deterministic arithmetic/legal-rule layer);
no universal 7-day taxpayer reply deadline; MOV-09 is a departmental order
and is never a taxpayer reply form; Section-130-only proceedings do not use
this workflow; deadline status comes from the deterministic deadline engine
and explicit procedural dates.

No classification, no LLM calls, no deadline or arithmetic logic.
"""

from domain.models import IssueSeverity, ProceedingType

from .base import WorkflowDefinition

SEC129_ENFORCEMENT_WORKFLOW = WorkflowDefinition(
    proceeding_type=ProceedingType.GST_SEC129_ENFORCE,
    required_facts=[
        "Goods description",
        "Vehicle / conveyance number",
        "Detention / seizure date",
        "Section 129 notice date and service date where available",
        "Penalty amount proposed in the notice",
        "Value of goods and tax payable on the goods where stated and relevant to penalty computation",
        "Whether the owner of the goods has come forward, where relevant and determinable",
        "Explicit hearing / payment / response date stated in the notice or order",
        "Order date / current enforcement status if an order has already been issued",
    ],
    evidence_requirements=[
        "Tax invoice for the goods",
        "E-Way Bill, or evidence explaining its absence where available",
        "Detention / seizure order, including MOV-06 where issued",
        "Section 129 notice and any subsequent order / MOV documents actually issued",
        "GR / LR / GRN / delivery or transport documents relevant to movement of goods",
    ],
    issue_types=[
        "EWAY_BILL",
        "DETENTION",
        "PENALTY_COMPUTATION",
        "PROCEDURAL_TIMELINE",
        "SECTION_130_RISK",
    ],
    default_severity=IssueSeverity.HIGH,
    output_structure=[
        "URGENT enforcement working paper",
        "Enforcement chronology / deadline alert",
        "Penalty computation verification checklist",
        "Reviewable response / submission appropriate to the actual notice or proceeding",
    ],
    special_rules=[
        "Never assume the tax invoice is valid; invoice validity remains REQUIRES_VERIFICATION until supported by evidence.",
        "Never invent a reason for a missing or defective E-Way Bill.",
        "Do not hardcode a 100% penalty assumption; extract the proposed penalty and defer statutory computation to the deterministic arithmetic/legal-rule layer.",
        "Do not treat the Section 129 seven-day statutory notice/order timeline as a universal taxpayer reply deadline.",
        "MOV-09 is a departmental order and must never be described as the taxpayer's reply form.",
        "A Section-130-only proceeding does not use this deep workflow and remains TRIAGE_ONLY until a separate workflow exists.",
        "Active detention/seizure requires urgent CA escalation, but deadline status must come from the deterministic Deadline Engine and explicit procedural dates.",
    ],
)
