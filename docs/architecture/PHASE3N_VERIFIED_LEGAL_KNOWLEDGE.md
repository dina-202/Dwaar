# Phase 3N — Verified GST Legal Knowledge

**Status:** Initial source-verified legal-knowledge layer  
**Date:** 23 September 2026  
**Depends on:** Phase 3M unified case timeline and the Phase 2 provenance-complete drafting boundary

## 1. Purpose

Phase 3N introduces the first legal-authority subsystem that Dwaar may trust as an input.

The purpose is not to make Dwaar an autonomous legal adviser. It is to replace the Phase-2 condition of "no verified legal-rule source exists" with a deterministic, versioned, source-linked catalog that can support professional research and later provenance-complete drafting.

The core rule is:

> Dwaar may verify the source and version of a legal proposition; it must not silently convert that proposition into a final case-specific legal conclusion.

## 2. Trust boundary

The legal-knowledge subsystem distinguishes four separate questions:

1. **Source authenticity** — is the source hosted on an approved official authority domain?
2. **Source verification** — was the proposition curated against that official source and recorded with a verification date?
3. **Temporal applicability** — is the recorded rule version effective for the explicit query date?
4. **Case applicability** — does that rule actually decide the taxpayer's case?

Phase 3N automates 1–3 only.

Question 4 remains a professional/legal reasoning question unless a later deterministic rule engine explicitly models it.

A result therefore means:

> "This source-verified proposition is recorded as effective for the requested date and mapped to this legal-research topic."

It does **not** mean:

> "The taxpayer wins", "the notice is invalid", "the officer lacks jurisdiction", or "this provision conclusively applies to these facts."

## 3. Approved source policy

Initial official hosts are closed to:

- `www.indiacode.nic.in`
- `indiacode.nic.in`
- `cbic-gst.gov.in`
- `www.cbic-gst.gov.in`

All source URLs must use HTTPS.

Search engines, tax blogs, commercial databases, LLM output, social media, summaries and secondary articles may help a human discover material, but they cannot become a `SOURCE_VERIFIED` Dwaar source merely because they are useful.

The initial v1 pack intentionally uses India Code for CGST Act propositions. CBIC sources are allowed by the framework but are added only when the exact notification/rule/circular version is curated.

## 4. Source verification is not legal approval

`SOURCE_VERIFIED` means the recorded proposition was checked against the identified official source/version.

It does not mean:

- a CA or advocate has approved a filing position;
- a provision is constitutionally valid;
- a circular binds a court;
- a judgment remains good law;
- a rule governs every factual variant;
- the source is the only authority on the issue.

Professional review remains required.

## 5. Versioned contracts

Phase 3N uses framework-independent immutable contracts in
`domain/legal_knowledge_models.py`.

### 5.1 LegalAuthorityType

Closed initial values:

- `ACT`
- `RULE`
- `NOTIFICATION`
- `CIRCULAR`
- `ORDER`
- `JUDGMENT`

### 5.2 LegalVerificationStatus

Closed values:

- `SOURCE_VERIFIED`
- `REQUIRES_VERIFICATION`
- `SUPERSEDED`
- `WITHDRAWN`

Only `SOURCE_VERIFIED` source/rule pairs may be returned as trusted matches.

### 5.3 LegalTopic

The first machine topics are deliberately coarse research topics, not legal conclusions:

- `HEARING_RIGHT`
- `DEMAND_SCOPE`
- `SECTION_129_TIMELINE`
- `SECTION_129_HEARING`
- `ITC_ELIGIBILITY`
- `RCM_APPLICABILITY`
- `FRAUD_SUPPRESSION_SCOPE`

The catalog may grow only by an explicit versioned code change.

### 5.4 LegalSourceRef

A source record contains:

- stable `source_id`;
- authority type;
- title;
- issuer;
- official HTTPS URL;
- official domain;
- source version label;
- optional publication date;
- retrieval date;
- verification status.

No source body is trusted merely because a URL exists.

### 5.5 LegalRule

A rule record contains:

- stable `rule_id`;
- stable semantic `rule_key` shared by later versions of the same rule slot;
- source ID;
- provision / locator;
- short source-verified proposition;
- effective-from and optional effective-to dates;
- jurisdiction;
- legal topic;
- applicable Dwaar proceeding types;
- source verification date;
- verification status.

A legal proposition is intentionally concise. Dwaar does not store an entire Act, rulebook or judgment as free prompt material.

## 6. Explicit-date rule

The resolver has no hidden notion of "current law".

Every query supplies an explicit `as_of_date`.

The resolver never calls `date.today()` internally.

This makes historical replay deterministic and prevents an old case snapshot from silently changing because today's date changed.

## 7. Fail-closed catalog validation

Before retrieval, the catalog is validated deterministically.

The catalog is invalid if, among other structural problems:

- source IDs or rule IDs are duplicated;
- a rule references a missing source;
- an official URL is non-HTTPS;
- the URL hostname is outside the closed official-domain allowlist;
- the recorded official domain does not equal the URL hostname;
- an effective-to date precedes effective-from;
- a source-verified rule points to a source that is not source-verified;
- two source-verified versions of the same `rule_key` overlap in time;
- mandatory identifiers, proposition text, provision or proceeding mappings are empty.

An invalid catalog yields no trusted matches.

There is no partial salvage of an invalid catalog.

## 8. Deterministic retrieval

A query contains:

- explicit `as_of_date`;
- one `ProceedingType`;
- one or more `LegalTopic` values.

A rule matches only when all are true:

1. catalog validation passes;
2. rule verification status is `SOURCE_VERIFIED`;
3. source verification status is `SOURCE_VERIFIED`;
4. requested proceeding type is explicitly mapped to the rule;
5. requested topic equals the rule topic;
6. `effective_from <= as_of_date`;
7. `effective_to` is absent or `as_of_date <= effective_to`.

No free-text semantic search, embedding similarity or LLM ranking is part of this trust path.

## 9. Unresolved legal research remains visible

A requested topic with no trusted date-applicable match is returned as unresolved.

Dwaar must not fill that gap from model memory.

Examples in the initial pack:

- the general RCM-applicability topic remains unresolved until the relevant current notification/rule material is curated;
- ITC eligibility remains unresolved until its versioned statutory/rule material is curated;
- older pre-2022 Section 129 timeline rules remain unresolved until historical versions are added.

This is intentional safety behavior, not a product failure.

## 10. Initial GST v1 legal pack

The first pack is deliberately small and high-confidence.

Source:

- The Central Goods and Services Tax Act, 2017 — India Code consolidated source accessed 23 September 2026.

Initial propositions:

1. CGST Act section 75(4): hearing opportunity where requested in writing or where an adverse decision is contemplated.
2. CGST Act section 75(7): adjudicated demand cannot exceed the notice amount and cannot be confirmed on grounds outside the notice.
3. CGST Act section 129(3), post-1 January 2022 version: notice/order timing following detention or seizure.
4. CGST Act section 129(4), post-1 January 2022 version: opportunity of hearing before penalty determination under section 129(3).

The Section 129 records intentionally begin on 1 January 2022. Phase 3N does not pretend the same text/version applies to an earlier event.

## 11. Drafting boundary

Phase 3N does **not** remove the existing Phase-2 external-citation barrier from specialist drafting.

The initial legal-knowledge layer is a trusted research input, not permission for the LLM to emit arbitrary citations.

A later 3N integration step may add a closed `LEGAL_RULE` provenance block rendered only by Python from a resolved `rule_id`.

Until that renderer exists:

- LLM-created legal citations remain prohibited;
- arbitrary URLs remain prohibited;
- case-law citations remain prohibited unless separately source-verified and supported by a closed renderer;
- `CA LEGAL RESEARCH REQUIRED` remains appropriate for unresolved topics.

## 12. No runtime network dependency

The trusted catalog is committed, versioned application data.

Trusted retrieval performs no network request.

Refreshing or expanding the catalog is a curation/development operation that must verify the official source before committing a new version.

This keeps production analysis deterministic and prevents an unavailable or changed website from silently changing legal output.

## 13. Security and privacy

The legal catalog contains public authority metadata and propositions only.

It contains no:

- client data;
- GSTINs;
- case facts;
- uploaded notice text;
- tokens;
- credentials;
- private object keys.

No tenant-specific persistence migration is required for the initial catalog/resolver.

## 14. Initial code boundary

Phase 3N initial implementation adds:

- `domain/legal_knowledge_models.py` — immutable contracts;
- `domain/legal_knowledge.py` — fail-closed catalog validator and resolver;
- `workflows/gst/legal_knowledge.py` — versioned GST source/rule pack;
- `workflows/gst/legal_research.py` — closed per-workflow research-topic plans;
- `app.py` — read-only verified-legal-source panel using the notice date as the explicit version-selection date;
- `tests/test_legal_knowledge.py` and `tests/test_gst_legal_research.py` — offline deterministic tests.

The legal panel's notice-date basis is displayed explicitly. It is a research view, not a claim that the notice date is the correct substantive-law date for every issue. Tax-period-dependent topics remain unresolved until a later contract supplies the correct legal applicability date.

No dependency change is required.

## 15. Exit criteria

The initial 3N layer is complete when:

- source/rule contracts are immutable and framework-independent;
- trusted sources are restricted to the closed official-domain allowlist;
- retrieval requires an explicit date;
- no network or LLM call occurs in trusted retrieval;
- duplicate/invalid/overlapping source-verified versions fail closed;
- only source-verified source/rule pairs may match;
- proceeding/topic/date matching is deterministic;
- unresolved topics are explicit;
- the initial India Code CGST propositions are represented with effective dates;
- pre-2022 Section 129 queries do not receive the post-2022 rule version;
- the full offline regression suite remains green;
- existing drafting citation prohibitions remain intact.

## 16. Next 3N increments

After this foundation is green:

1. expand curated notification/rule/circular packs for RCM, ITC and reply-form questions;
2. add explicit legal-applicability date inputs for tax-period-dependent rules instead of reusing the notice date;
3. introduce a closed Python-rendered legal-rule draft block;
4. bind saved legal briefs to analysis snapshots so historical cases retain the exact catalog version used;
5. add professional source-refresh/re-verification workflow and expiry warnings.

No step may bypass source verification in order to make the UI look more complete.
