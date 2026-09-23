# Phase 3N.7 — Closed Legal Rule Bundles

**Status:** implementation slice  
**Date:** 23 September 2026  
**Depends on:** Phase 3N.6 verified Section 74 scope

## Problem

A legal topic can require more than one authority.

For example, a future ITC eligibility pack may need a statutory provision plus one or more rules or notifications. Treating "one matching rule" as the definition of a resolved legal topic would make Dwaar structurally unable to represent a complete multi-authority research basis.

The opposite shortcut is also unsafe: treating "at least one matching rule" as complete can mark a topic resolved when a required authority is missing.

## Separation of responsibilities

The legal catalog answers:

> Which source-verified rule records are effective for this topic, proceeding and date?

The GST workflow profile answers:

> Which rule keys must be present before this topic is considered complete for this workflow?

These are intentionally separate contracts.

## Closed bundle contract

Each `GstLegalResearchRequirement` now carries:

- legal topic;
- legal applicability date basis;
- ordered `required_rule_keys`.

A topic is resolved only when:

1. its required provenance-bearing date anchor exists;
2. the legal catalog validates;
3. every effective matched rule key is unique;
4. the effective matched key set equals the closed required key set;
5. the resulting matches are returned in workflow-declared bundle order.

An empty required bundle means the topic is deliberately not curated and therefore remains unresolved.

## Existing bundles

The current verified topics are pinned to:

- hearing right → `cgst.s75.4.hearing`;
- demand scope → `cgst.s75.7.demand_scope`;
- Section 74 fraud/suppression period scope → `cgst.s74.fraud_scope`;
- Section 129 timeline → `cgst.s129.3.timeline`;
- Section 129 hearing → `cgst.s129.4.hearing`.

ITC eligibility and RCM applicability retain empty bundles and remain unresolved.

## Fail-closed behavior

A topic remains unresolved when:

- a required rule key is absent;
- the catalog returns an unexpected extra rule key for the topic/date;
- more than one effective rule version appears for the same key;
- the workflow bundle is empty;
- the source catalog is invalid.

Unexpected extra rules deliberately require a workflow-profile update. This prevents catalog growth from silently changing the legal basis that Dwaar treats as complete.

## Why this precedes ITC / RCM expansion

ITC and RCM often depend on interacting statutory provisions, rules and notifications.

Phase 3N.7 makes multi-authority completeness explicit before those packs are added.

The invariant is:

> Dwaar does not call a legal topic complete because it found some law; it calls it complete only when the workflow-declared verified authority bundle is satisfied.
