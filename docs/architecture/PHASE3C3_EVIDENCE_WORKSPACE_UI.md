# Phase 3C.3 — Temporary Evidence Workspace UI Contract

**Status:** Architecture amendment  
**Date:** 22 September 2026  
**Depends on:** Phase 3C.1 candidate intake, Phase 3C.2 human review

## 1. Purpose

Expose supporting-document evidence intake and human review in the current Streamlit application without pretending that Streamlit session state is durable case storage.

## 2. Notice-analysis cache

Streamlit reruns the script on widget interaction. Re-running the LLM-backed notice analysis on every evidence review click is wasteful and can introduce inconsistent repeated model calls.

The app therefore caches the Phase-2 result in `st.session_state` using a SHA-256 key bound to the exact notice PDF bytes.

When notice bytes change:

- notice analysis is recomputed;
- cached document pages/raw text are replaced;
- all temporary evidence workspace state is cleared.

## 3. Evidence-workspace cache

The evidence workspace key is bound to:

- exact notice PDF bytes;
- ordered evidence checklist IDs;
- ordered supporting filenames;
- SHA-256 digest of each supporting file payload.

Any change invalidates:

- evidence intake result;
- evidence review records.

This prevents review decisions from leaking across different document sets.

## 4. User flow

1. Upload notice PDF.
2. Dwaar runs or reuses content-bound notice analysis.
3. Existing Phase-2 output remains visible.
4. Upload one or more supporting PDFs.
5. Dwaar builds provenance-aware EvidenceDocument objects.
6. Candidate matching runs once for that exact workspace key.
7. Candidate links are shown with exact quote/page/source trust.
8. Professional may Confirm or Reject each candidate with an optional note.
9. Review records are displayed separately.

## 5. Safety boundaries

The UI must not:

- mutate Phase-2 ExtractedFact objects;
- mutate EvidenceChecklistItem.status;
- alter arithmetic/deadline results;
- regenerate or unlock drafting based on review records;
- claim session state is persistent;
- hide OCR source-verification status.

## 6. Session-state limitation

Streamlit Session State is tied to the current browser/WebSocket session and resets when that session is lost or reloaded.

Therefore the UI labels this as a **temporary session workspace**.

Durable Client/Case/Document/Evidence/Review storage belongs to Phase 3D.

## 7. Exit criteria

- notice analysis is reused on evidence-only reruns;
- evidence matching is reused for unchanged supporting files;
- supporting-file change invalidates evidence matching but not notice analysis;
- notice change invalidates both notice/evidence cache;
- Confirm/Reject creates review records;
- Phase-2 evidence checklist remains unchanged;
- full regression suite passes.
