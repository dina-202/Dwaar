# Phase 3A.2 — OCR Origin and Source-Trust Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026  
**Depends on:** Phase 3A.1 page-aware provenance

## 1. Decision

Dwaar may OCR a page only when that page has no usable embedded PDF text.

Embedded text and OCR text are not equivalent provenance channels. Their legal/factual meaning is independent from extraction reliability, so the model separates:

- `FactStatus`: what kind of assertion the notice contains;
- `SourceTextOrigin`: how the source text entered Dwaar;
- `SourceVerificationStatus`: whether that extraction channel is trusted for filing-grade downstream use.

An OCR-derived departmental allegation therefore remains `ALLEGED`; it is not rewritten to another FactStatus merely because OCR was used. Its source verification is independently `REQUIRES_VERIFICATION`.

## 2. OCR policy

Initial production policy:

1. Preserve non-empty embedded page text exactly.
2. Never OCR over a page that already contains usable embedded text.
3. OCR only blank/scanned pages.
4. Use 300 DPI by default.
5. Default OCR language is English; other Tesseract languages are an explicit deployment/configuration concern.
6. If OCR is required but cannot run, fail with a controlled setup error rather than silently analyze an empty or partial document.
7. OCR text remains page-local and participates in the Phase 3A.1 exact page-substring checks.

This follows PyMuPDF guidance to determine whether OCR is needed before invoking it and to reuse the OCR TextPage for subsequent extraction. Tesseract documentation also notes that recognition quality materially depends on input quality and generally benefits from at least ~300 DPI.

## 3. New source-trust contracts

`SourceTextOrigin`:
- EMBEDDED
- OCR
- MIXED
- UNKNOWN

`SourceVerificationStatus`:
- VERIFIED
- REQUIRES_VERIFICATION

`DocumentPageText`:
- page_number
- text
- origin
- verification
- ocr_language
- ocr_dpi

Legacy `ExtractedFact` construction remains valid. New fields are additive and default to:
- source_origin = EMBEDDED
- source_verification = VERIFIED

## 4. Downstream safety

OCR-derived facts may be shown to the professional user, but until a human-verification workflow exists they must not unlock a specialist draft.

Therefore:

- Validation emits a blocking `fact.source_verification` failure for any unverified source fact.
- Unverified OCR notice dates/hearing details do not feed deterministic deadline inputs.
- Unverified OCR amounts do not feed deterministic arithmetic operands.
- FactStatus remains semantically unchanged.
- No OCR confidence percentage is invented because PyMuPDF's page OCR path does not provide a filing-grade page-level confidence contract suitable for this architecture.

## 5. User experience

When OCR is used, the UI must disclose the physical page numbers that were OCRed and explain that OCR-derived facts require review.

The UI must never label recognized text as equivalent to embedded source text.

## 6. Deferred work

This unit deliberately does not implement:
- human visual verification / promotion of OCR facts;
- deskewing, binarization or image preprocessing;
- language auto-detection;
- table-specific OCR;
- cloud OCR providers;
- OCR confidence scoring;
- image/JPG upload;
- OCR correction persistence.

Those belong after the source-trust boundary is stable.

## 7. Exit criteria

- mixed embedded/scanned PDF ingestion works page-by-page;
- embedded pages are not OCRed;
- scanned pages are OCRed once and retain page number;
- OCR origin and settings are stored;
- OCR failure is controlled;
- OCR facts carry `REQUIRES_VERIFICATION`;
- validation blocks drafting on OCR facts;
- deadline/arithmetic ignore unverified OCR facts;
- legacy embedded-PDF APIs remain intact;
- full regression suite passes.
