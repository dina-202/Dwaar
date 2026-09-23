# Phase 3N.12 — Verified Historical ITC Mismatch Regimes

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.11 full-period legal applicability safety

## Goal

Add the first source-verified ITC research capability without turning a return mismatch into a conclusion that ITC is eligible or ineligible.

The new capability answers a narrower question:

> Which source-verified mismatch-verification regime governs the source tax period?

It does not answer:

> Is the taxpayer's ITC legally eligible?

## New legal topic

`ITC_MISMATCH_VERIFICATION` is separate from `ITC_ELIGIBILITY`.

This separation is deliberate.

A verified mismatch circular can tell a CA how the department's 3B-versus-supplier-statement discrepancy should be verified for a historical period. It cannot by itself establish all factual and statutory conditions for ITC entitlement.

`ITC_ELIGIBILITY` therefore remains uncurated and unresolved.

## Trusted source policy

The approved primary-government domain allowlist now includes the official GST Council website:

- `gstcouncil.gov.in`
- `www.gstcouncil.gov.in`

alongside India Code and CBIC.

GST Council is used only for official Government of India material. Secondary tax sites remain ineligible for `SOURCE_VERIFIED` status.

## Verified source versions

### Circular No. 183/15/2022-GST

Primary source:

- CBIC official PDF;
- issued 27 December 2022.

The circular addresses differences between ITC availed in FORM GSTR-3B and ITC appearing in FORM GSTR-2A for FY 2017-18 and 2018-19.

The Dwaar proposition records only that the circular provides a case-specific verification procedure, including verification of relevant Section 16 conditions and prescribed supplier tax-payment evidence, subject to the circular's own limitations.

Catalog applicability interval:

- 1 April 2017 through 31 March 2019.

This interval models the financial-year scope identified by the circular. It is a research applicability interval, not a claim that GST existed before 1 July 2017.

### Circular No. 193/05/2023-GST

Primary source:

- official GST Council circular page/file;
- issued 17 July 2023.

The circular addresses mismatch verification for 1 April 2019 through 31 December 2021.

It expressly describes sub-period treatment, including Rule 36(4) limits for the periods beginning 9 October 2019, 1 January 2020 and 1 January 2021, and notes the change from 1 January 2022.

The Dwaar proposition therefore describes it as **period-specific verification guidance** rather than flattening those sub-periods into one percentage rule.

Catalog applicability interval:

- 1 April 2019 through 31 December 2021.

## One semantic rule key, versioned sources

Both circular records use:

`cbic.itc_mismatch_verification`

as the semantic rule key.

They are non-overlapping versions of the same research slot:

- v1 → Circular 183 scope;
- v2 → Circular 193 scope.

The closed GST ITC workflow bundle requires that one semantic key.

This lets the interval resolver select the correct source version without requiring both circulars simultaneously.

## Full-period safety

Phase 3N.11 applies.

Examples:

- FY 2018-19 is fully covered by the Circular 183 scope;
- FY 2019-20 is fully covered by the Circular 193 scope;
- FY 2020-21 is fully covered by Circular 193;
- FY 2021-22 is **not** fully covered because Circular 193's scope ends on 31 December 2021;
- a source period explicitly stated as 1 April 2021 through 31 December 2021 can resolve Circular 193.

Dwaar does not use the 31 March 2022 end date to project post-1-January-2022 law backward, and it does not split FY 2021-22 into invented sub-periods.

## Question-plan behavior

The ITC workflow now has two separate research questions:

1. historical mismatch-verification regime;
2. final ITC eligibility.

The mismatch-regime question requires a source-verified tax period.

It intentionally does not require the existing `GSTR2B_ITC_REFLECTED_AMOUNT` role, because Circulars 183 and 193 concern GSTR-2A historical discrepancies. Reusing a 2B-specific semantic role for 2A would corrupt fact provenance.

Final ITC eligibility continues to require the existing ITC factual inputs and remains unresolved pending a broader verified authority model.

## Safety invariants

> A GSTR-3B / GSTR-2A or GSTR-2B mismatch is not, by itself, proof that ITC is legally ineligible.

> A verified historical mismatch procedure is not a verified case-specific entitlement conclusion.

> Dwaar must not relabel GSTR-2A evidence as GSTR-2B merely to satisfy a machine role.

## Sources verified during this phase

- Circular No. 183/15/2022-GST, CBIC, dated 27 December 2022.
- Circular No. 193/05/2023-GST, CBIC/GST Council, dated 17 July 2023.

The runtime remains offline. These official materials are curated into versioned application data; production analysis does not fetch the web.
