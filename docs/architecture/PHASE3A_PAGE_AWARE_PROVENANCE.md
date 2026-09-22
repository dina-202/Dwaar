# Phase 3A — Page-Aware Document Provenance Contract

**Status:** Additive architecture amendment  
**Date:** 22 September 2026  
**Applies to:** Phase-2 ingestion and Fact Engine provenance  
**Does not replace:** `docs/architecture/ARCHITECTURE_SPEC_v1_1.md`

## 1. Problem

The current PDF reader flattens every PDF page into one string:

```python
"".join(page.get_text() for page in doc)
```

The Fact Engine then verifies that an LLM-provided `source_text` is an exact substring of that flattened text. This grounds the quote to the document, but it cannot independently prove that the LLM-provided `source_page` is correct.

That creates an avoidable trust gap: a quote can be real while its displayed page number is wrong.

## 2. Decision

Introduce an additive page-aware ingestion path while preserving every existing public Phase-2 API.

The old APIs remain available and behavior-compatible:

- `modules.pdf_reader.extract_text(pdf_bytes) -> str`
- `domain.fact_engine.extract_facts(raw_text, classification)`
- `domain.fact_engine.extract_facts_with_status(raw_text, classification)`
- `domain.phase2_orchestrator.run_phase2_analysis(raw_text, today)`

New page-aware APIs are additive:

- `modules.pdf_reader.extract_page_texts(pdf_bytes) -> List[str]`
- `domain.fact_engine.extract_facts_with_page_provenance(raw_text, classification, page_texts)`
- `domain.phase2_orchestrator.run_phase2_analysis_from_pages(page_texts, today)`

The Streamlit app should move to the page-aware path after the contract and tests are in place.

## 3. Page numbering

`extract_page_texts` returns text in physical PDF page order.

List index is zero-based in Python, but **document page numbers are one-based**:

```text
page_texts[0] -> source_page 1
page_texts[1] -> source_page 2
...
```

No LLM is allowed to create or renumber pages.

## 4. Raw-text compatibility

For a digital PDF:

```python
raw_text == "".join(page_texts)
```

This exactly preserves the previous flattening behavior for classification and all downstream components that still consume raw text.

The page-aware path is therefore additive provenance, not a classification-input rewrite.

## 5. Fact source-page rules

When page-aware provenance is supplied, Python owns page validation.

For every candidate fact:

1. `source_text` must still be a non-empty exact substring of `raw_text`.
2. Python finds every page whose extracted text contains that exact `source_text`.
3. If no page contains it, the candidate is rejected.
4. If the LLM supplies `source_page=N`, the candidate is accepted only if page N exists **and** contains the exact `source_text`.
5. If the LLM supplies `source_page=null` and exactly one page contains the quote, Python assigns that page number.
6. If the LLM supplies `source_page=null` and multiple pages contain the quote, `source_page` remains null. Python must not guess which occurrence the model intended.
7. A quote spanning a page boundary is rejected by the page-aware path because no single page can substantiate the page citation.
8. Wrong-page claims are never silently repaired to a different LLM-claimed page. The only automatic assignment allowed is null -> unique deterministic page.

This is intentionally fail-closed.

## 6. Prompt representation

When page-aware extraction is active, the extraction prompt presents each page inside machine-owned page markers so the LLM can propose a page number.

The markers are metadata, not notice text.

Candidate `source_text` must still be copied from the underlying page content. Since Python validates against the unmarked raw text and exact page text, prompt markup can never become accepted provenance.

## 7. Scanned pages and OCR

This step does **not** implement OCR.

Reason: OCR is materially slower and changes the provenance source from embedded PDF text to recognized text. PyMuPDF's documented OCR path uses Tesseract-backed `Page.get_textpage_ocr()`, and the result should be reused for subsequent extraction/search on that page.

OCR will be Phase 3A.2 and must plug into the same ordered page-text contract rather than create a parallel pipeline.

Phase 3A.2 must add explicit page text-origin metadata (embedded/OCR) before OCR-derived text is treated as filing-grade provenance.

## 8. Reading order

This step preserves the existing `Page.get_text()` behavior.

PyMuPDF documents that plain-text extraction follows the order encoded by the PDF creator and may not match natural visual reading order. A future layout-aware extraction change must therefore be tested independently and must not be mixed into this provenance patch.

## 9. Security and trust invariants

This amendment adds the following invariants:

- A displayed non-null `source_page` from the page-aware path is deterministically substantiated by exact text on that page.
- Invalid page numbers are rejected.
- Wrong-page model output is rejected.
- Page metadata never weakens the existing exact-substring provenance requirement.
- The LLM does not control page numbering.
- Page-aware extraction still makes exactly one Fact Engine LLM call.
- Legacy raw-text APIs do not silently change behavior.

## 10. Exit criteria

Phase 3A.1 is complete when tests demonstrate:

- PDF page order is preserved;
- legacy `extract_text` output equals joined page text;
- unique page can be assigned by Python when the model returns null;
- correct claimed page is accepted;
- wrong claimed page is rejected;
- out-of-range/invalid page is rejected;
- duplicate quote on multiple pages with null page stays null;
- page markers appear in the page-aware extraction prompt but cannot satisfy provenance;
- old public API signatures and tests remain intact;
- the Streamlit runtime uses the page-aware path.
