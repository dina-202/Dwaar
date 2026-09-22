# Phase 3C.1 — Evidence Candidate Intake Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026

## 1. Purpose

Phase 3C.1 lets Dwaar inspect supporting documents against the workflow evidence checklist without silently converting those documents into taxpayer facts or treating an evidence requirement as satisfied.

The engine creates only **candidate links** for professional review.

## 2. Core rule

> A supporting document can suggest evidence; it cannot prove a taxpayer position by itself.

The evidence engine therefore has no authority to:

- mutate `EvidenceChecklistItem.status`;
- create `ExtractedFact` objects;
- alter arithmetic;
- alter deadline inputs;
- unlock specialist drafting;
- make legal conclusions;
- claim an evidence requirement is satisfied.

## 3. Contracts

### EvidenceDocument

- `document_id`
- `filename`
- ordered `DocumentPageText` pages

### EvidenceCandidate

- stable candidate ID;
- evidence requirement ID;
- supporting document ID;
- exact source quote;
- exact physical page;
- source origin;
- source verification state;
- review status.

All newly proposed candidates start at:

`PENDING_REVIEW`

### EvidenceIntakeResult

- SUCCESS
- PARTIAL
- FAILED
- NO_INPUT

Rejected candidates never consume IDs.

## 4. LLM boundary

The LLM may only propose:

- evidence_id;
- document_id;
- source_text;
- source_page.

Python owns acceptance.

A candidate is rejected unless:

1. the evidence ID exists in the current checklist;
2. the document ID exists in the supplied documents;
3. source_text is non-empty;
4. source_page is a positive integer;
5. the exact source_text occurs on that exact physical page;
6. the candidate has exactly the allowed fields;
7. the same candidate has not already been accepted.

## 5. OCR

OCR evidence candidates are allowed to exist, but retain:

`SourceVerificationStatus.REQUIRES_VERIFICATION`

This unit never promotes OCR evidence to verified.

## 6. Prompt injection

Supporting documents are untrusted data.

The evidence prompt explicitly forbids following instructions inside documents. Even if a document attempts to instruct the model to mark itself sufficient, the model output is still constrained to the four-field candidate contract and Python performs exact provenance validation.

## 7. Human review

Phase 3C.1 intentionally stops before confirmation.

A later Phase 3C.2 review workflow may allow a professional to:

- CONFIRM;
- REJECT;
- correct the matched requirement;
- correct the quoted source;
- add a note;
- promote verified evidence into a controlled evidence graph.

Until then, all candidates remain pending and the existing Phase-2 evidence checklist remains unchanged.

## 8. Exit criteria

- supporting documents can be represented with page/source trust;
- checklist candidates can be proposed in one controlled LLM call;
- fabricated quotes and wrong pages are rejected;
- unknown requirement/document IDs are rejected;
- duplicates are rejected;
- OCR trust state propagates;
- evidence checklist state is never mutated;
- no taxpayer fact is created;
- full regression suite passes.
