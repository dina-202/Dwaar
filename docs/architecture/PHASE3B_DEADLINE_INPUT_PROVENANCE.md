# Phase 3B — Deadline Input Provenance Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026  
**Depends on:** Phase 3A.1 page provenance, Phase 3A.2 source trust

## Decision

Dwaar must not infer a universal GST response period from a notice form or from model knowledge.

Official GST rules show that response mechanics differ by proceeding. Examples include:
- CMP-05: show cause within fifteen days of receipt;
- REG-03: reply within seven working days of service;
- ASMT-10: the notice specifies a time not exceeding fifteen days from service;
- RFD-08: reply within fifteen days of receipt;
- DRC-06 is the prescribed representation/reply form for a DRC-01 summary, not itself a universal response-period rule.

Accordingly, this unit only promotes **document-stated** deadline inputs into the deterministic deadline engine.

## New fact roles

Two additive FactRole members are introduced:

- `NOTICE_SERVICE_DATE`
- `RESPONSE_PERIOD`

Both are compatible only with `FactType.DOCUMENT_DETAIL`.

A non-NONE role is valid only when the selected exact `source_text` itself establishes the role.

Examples:

```text
"Notice served on 18-08-2026"
-> NOTICE_SERVICE_DATE

"Furnish reply within 15 days of service"
-> RESPONSE_PERIOD
```

A bare date is not a service date.

A stated calendar due date remains `FactType.STATED_DUE_DATE`; it is not converted into a response period.

## Deterministic input mapping

`_build_deadline_inputs(facts)` returns:

```text
notice_date
service_date
response_period_text
hearing_date_text
```

For every input:
- fact source must be VERIFIED;
- status must be CONFIRMED;
- exactly one eligible fact must exist;
- date parsing is deterministic;
- response-period text is passed verbatim;
- claims are never used as the calculation source.

Ambiguity results in `None`.

## Deadline-engine safety corrections

This unit also closes two pre-existing unsafe fallbacks:

- "working days" / "business days" are not converted to calendar days. They remain UNKNOWN until a verified working-day and holiday-calendar subsystem exists.
- response periods anchored to "receipt" / "received" are treated as service-based. When the service/receipt date is unavailable, Dwaar stays UNKNOWN instead of substituting the notice issue date.

## No statutory fallback in this unit

This patch does not encode:
- 15-day rules;
- 7-working-day rules;
- 30-day rules;
- form-to-deadline lookup;
- holiday/working-day calculations.

Those require a versioned, verified legal-rule subsystem with effective dates and authoritative sources.

## Service-date caution

CGST Act section 169 recognizes multiple modes of service and contains deemed-service mechanics. Therefore Dwaar must not equate notice issue date, portal availability date, email date, postal date, and legal service date unless a verified rule or explicit source supports that mapping.

## Exit criteria

- explicit verified service date reaches Deadline Engine;
- explicit verified response-period source reaches Deadline Engine verbatim;
- ambiguous/missing/unverified inputs remain unknown;
- ALLEGED dates are never calculation anchors;
- existing stated-due-date conflict checking remains separate;
- no hardcoded statutory response period is introduced;
- full regression suite passes.
