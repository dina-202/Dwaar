# Phase 3P.8 — Product Rehearsal and Tour Gate

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3P.7 clean-target document key rotation rehearsal

## Goal

Define one final deterministic gate before Dwaar is presented as a coherent product rather than a collection of independently tested subsystems.

The tour gate exercises the real local runtime and persistence/service boundaries in one case.

It deliberately does not call an external LLM.

## Rehearsal case

The deterministic rehearsal uses a synthetic Section 73 ITC mismatch case with:

- DRC-01 demand-adjudication classification;
- verified notice-date provenance;
- FY 2022-23 tax period;
- GSTR-3B claimed ITC;
- GSTR-2B reflected ITC;
- deterministic mismatch arithmetic;
- professional-review-required draft status;
- closed supporting-evidence items.

No real taxpayer/client data is used.

## Product spine exercised

The rehearsal performs, in order:

1. encrypted case intake and notice persistence;
2. immutable encrypted analysis snapshot persistence/load;
3. provenance-bearing GST legal-date resolution;
4. source-verified ITC mismatch research;
5. explicit preservation of unresolved final ITC eligibility;
6. source-grounded supporting-evidence document persistence;
7. human-confirmed, snapshot-bound evidence review;
8. attempted filing of a non-approved draft and deterministic rejection;
9. draft baseline creation;
10. draft review;
11. draft approval;
12. audited case transition into draft-review state;
13. actual filing record with filed-response PDF;
14. filing acknowledgement persistence;
15. unified case timeline projection;
16. live encrypted-storage consistency audit;
17. wrong-key authentication failure;
18. manifest-v2 encrypted backup creation/verification;
19. clean-target runtime recovery;
20. recovered filed-case verification;
21. clean-target document-key rotation from generation A to B;
22. final rotated-runtime storage audit.

## Closed tour-readiness checks

The external report intentionally exposes a smaller stable checklist:

- `encrypted_intake`
- `analysis_snapshot`
- `verified_legal_research`
- `legal_uncertainty_preserved`
- `human_evidence_review`
- `unapproved_filing_blocked`
- `draft_review_approval`
- `filing_acknowledgement`
- `unified_timeline`
- `live_storage`
- `wrong_key_blocked`
- `backup_recovery`
- `key_rotation`

`tour_ready` is true only when every check passes.

## Why the negative gates matter

A tour is not considered ready merely because the happy path succeeds.

The rehearsal explicitly proves:

- Dwaar does not convert verified mismatch law into a fabricated final ITC-eligibility conclusion;
- a working/non-approved draft cannot be recorded as a filing;
- the wrong document key cannot authenticate the live encrypted object set.

These are product behavior, not cosmetic test assertions.

## Operator command

Run:

`python scripts/product_tour_rehearsal.py`

Success:

- exit code `0`;
- one JSON object;
- `tour_ready: true`;
- all closed checks report `pass`.

Failure:

- exit code `1`;
- `tour_ready: false` or sanitized `product_rehearsal_failed`.

The CLI does not expose:

- document keys;
- database/object-store paths;
- case/client identifiers from a deployment;
- underlying exception text.

The runtime is temporary and deleted after the rehearsal.

## External-model regression boundary

The offline tour gate does not call the configured LLM.

Dwaar retains the four existing live notice-regression families:

1. ITC mismatch / Section 73;
2. fraud allegation / Section 74;
3. E-Way Bill enforcement / Section 129;
4. RCM / Section 73.

For deployment/pilot validation with provider credentials configured, run:

`python tests/run_regression.py`

That runner uses the real notice explainer and real sample PDFs and compares structural/status-label coverage against the retained baselines.

Live LLM regression is intentionally not part of normal CI because:

- CI should not require provider secrets;
- CI should not incur external model cost;
- model output is nondeterministic;
- network/provider availability is external to product-code correctness.

## Tour-ready versus pilot-ready

**Tour-ready** means:

- the deterministic product spine composes correctly;
- the professional lifecycle is coherent;
- legal/evidence uncertainty is preserved;
- storage/recovery/rotation safety gates pass;
- the UI and underlying services are covered by the full offline suite.

**Pilot-ready** additionally requires, in the target deployment:

- runtime preflight green;
- operator health green;
- recent verified backup;
- live storage audit green;
- live notice regression green with configured LLM;
- pilot operator/CA credentials and firm access configured.

## Safety invariant

> Dwaar is tour-ready only when the same case can survive the complete professional lifecycle and the critical failure gates without bypassing provenance, review, encryption, or recovery boundaries.
