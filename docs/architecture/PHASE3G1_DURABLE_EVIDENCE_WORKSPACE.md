# Phase 3G.1 — Durable Supporting Evidence Workspace

**Status:** Pilot supporting-evidence persistence  
**Date:** 22 September 2026  
**Depends on:** Phase 3F saved cases and analysis snapshots

## 1. Purpose

Phase 3G.1 turns supporting evidence from temporary Streamlit uploads into durable encrypted case documents.

For a saved case, a professional can now:

1. attach supporting PDF evidence;
2. retain those files across sessions/restarts;
3. list persisted evidence metadata;
4. rerun evidence-to-checklist candidate matching from the persisted files.

Human Confirm/Reject decisions remain session-only in this phase.

## 2. Durable document type

Supporting evidence is stored as:

`CaseDocumentKind.SUPPORTING_EVIDENCE`

using the existing authorized document persistence path.

That means each file receives:

- opaque document ID;
- SHA-256 metadata;
- encrypted AES-GCM object storage;
- DOCUMENT_ADDED audit event;
- authenticated actor attribution.

Plain document bytes are not stored in SQLite.

## 3. One-file persistence semantics

`add_supporting_evidence_pdf()` persists exactly one PDF per call.

This is deliberate.

The service does not claim atomic multi-file batch semantics across several encrypted objects.

The UI may iterate over selected files and report individual successes/failures.

## 4. Authorization

Attaching evidence requires:

`DOCUMENT_ADD`

through the existing AuthorizedCaseService.

Reading/decrypting persisted evidence requires:

`DOCUMENT_READ`

Evidence candidate matching additionally requires:

`EVIDENCE_REVIEW`

through `AuthorizedEvidenceWorkspaceService`.

UI visibility does not replace backend authorization.

## 5. Stable evidence document identity

The old temporary workspace generated session IDs such as:

`D-001`

Phase 3G.1 candidate matching uses the actual persisted case document ID instead.

Example:

`DOC-<opaque id>`

This matters because later durable evidence review records need a stable document reference that survives reloads and restarts.

## 6. Load and integrity path

Persisted evidence is loaded through AuthorizedCaseService.

That path verifies:

- firm/case access;
- document identity;
- encrypted-object availability;
- plaintext byte size against metadata;
- SHA-256 against metadata.

The PDF is then parsed page-by-page using the existing PDF/OCR ingestion boundary.

If document metadata changes between list and read, evidence loading fails closed.

## 7. Evidence matching

`analyze_persisted_evidence()`:

1. lists only SUPPORTING_EVIDENCE documents for the case;
2. decrypts and integrity-checks them;
3. creates EvidenceDocument objects using persisted document IDs;
4. calls the existing source-grounded evidence candidate engine.

The candidate engine still:

- cannot satisfy an evidence requirement automatically;
- cannot create taxpayer facts;
- must quote exact source text from a physical page;
- preserves OCR/source-verification status;
- returns pending-review candidates only.

## 8. Saved-case UI

The saved-case workspace now includes:

**Persisted supporting evidence**

It shows existing attachment metadata.

Users with DOCUMENT_ADD may select one or more PDFs and click:

**Attach selected evidence**

Each selected file is persisted independently.

After any successful/attempted attachment operation, temporary candidate/review session state is cleared so stale matches cannot silently survive a changed evidence set.

## 9. Explicit matching

Users with EVIDENCE_REVIEW may click:

**Analyze attached evidence**

Dwaar then reruns candidate matching against the currently persisted evidence set.

The result remains advisory.

No candidate changes:

- EvidenceChecklistItem.status;
- taxpayer facts;
- draft eligibility;
- validation state.

## 10. Review state remains temporary

Confirm/Reject buttons still create the existing in-memory EvidenceReviewRecord objects only.

The UI explicitly labels these as session review records.

This is intentional because an `evidence_id` belongs to a particular analysis/checklist contract.

Persisting a review without binding it to an analysis snapshot could make an old decision appear valid against a future changed checklist.

## 11. Phase 3G.2 dependency

Durable review persistence must bind each decision to at least:

- case ID;
- analysis snapshot ID;
- evidence requirement ID;
- persisted supporting document ID;
- source page;
- source quote hash / protected source payload;
- decision;
- reviewer identity;
- review timestamp.

The exact storage design belongs to Phase 3G.2.

## 12. Unsaved notice behavior

The new durable workspace is used only for saved cases.

Unsaved/new notice analysis may still use the temporary supporting-evidence workspace because no durable case/document identity exists yet.

This prevents accidental creation of orphan evidence objects before a case is explicitly saved.

## 13. Failure disclosure

UI failures are generic.

Internal details such as:

- object-store paths;
- encryption failures;
- parser internals;
- provider errors;
- database internals

are not rendered to the professional.

## 14. Exit criteria

- saved-case evidence PDFs persist as encrypted SUPPORTING_EVIDENCE;
- attachment uses authenticated DOCUMENT_ADD boundary;
- persisted evidence lists after reload;
- candidate engine uses persisted document IDs;
- DOCUMENT_READ protects evidence loading;
- EVIDENCE_REVIEW protects matching;
- source grounding/OCR verification rules remain unchanged;
- stale session matches clear when evidence changes;
- Confirm/Reject remains explicitly non-durable;
- full regression suite passes.
