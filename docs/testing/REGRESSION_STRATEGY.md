# REGRESSION STRATEGY — CA Notice Explainer

**Status:** Phase 1.5 (2026-08-27) — documents current behavior and the intended direction.
**Companions:** `tests/run_regression.py` (as committed in `19f8d12`), `tests/baselines/`, `tests/expectations/`.

This document records how regression testing works today and how it should evolve. It is a strategy document — no future implementation is described here as already existing.

---

## A. Current regression behavior

`tests/run_regression.py` runs the **unchanged production pipeline** (`modules.notice_explainer.explain_notice`, Gemini + prompt v3.3) over the four fixtures in `data/sample_notices/` (`NOTICE_*.pdf`), saves each fresh output to `tests/outputs/<fixture>.analysis.md`, and reports per notice.

**Comparison type: structural — NOT textual.** The runner performs no exact-text and no normalized-text comparison anywhere (this is stated in its docstring and enforced by design). Specifically, for each notice it checks:

1. The pipeline returned `success=True` — otherwise `EXECUTION_ERROR`.
2. The explanation is non-trivial (≥ 5,000 chars) — a guard against degenerate/truncated outputs.
3. All eight required section-title fragments are present (case-insensitive substring): NOTICE FACTS, ALLEGATIONS, COMPUTATION REVIEW, URGENCY, EVIDENCE GAPS, LEGAL DEFENCES, DRAFT REPLY, CLIENT MESSAGE.
4. If a baseline exists in `tests/baselines/`: the baseline itself must pass the same structural checks, and **every status label present in the baseline must also appear in the fresh output** (coverage direction: baseline → fresh; extra labels in the fresh output are fine).
5. No baseline file → `BASELINE_MISSING`.

Reported statuses: `PASS`, `FAIL`, `BASELINE_MISSING`, `EXECUTION_ERROR`. Exit code 0 unless any notice is `FAIL`/`EXECUTION_ERROR`.

Baseline files (`tests/baselines/<fixture>.baseline.md` + `.metadata.json`) are the frozen outputs of the production pipeline captured at Phase 1/1.5; `tests/outputs/` is git-ignored (regenerated every run, never committed — see `tests/.gitignore`).

## B. Why exact LLM output comparison is insufficient by itself

- **Non-deterministic sampling:** the same prompt and model produce different token sequences on every run, so raw text equality fails on every re-run (permanent false negatives).
- **Substance vs wording:** token-level drift (synonyms, reordered sentences, emoji/formatting, ₹ rendering) changes the text without changing any fact, status label, or legal conclusion. A diff cannot tell "wording changed" from "fact status changed".
- **Provider/model drift:** temperature defaults, model-version updates, or a future provider switch all rewrite prose without any semantic change.
- **One-directional brittleness:** a changed word in the *baseline* invalidates equality even when the fresh output is strictly better.
- Exact comparison therefore belongs in **human review** (side-by-side baseline diffs), not in an automated pass/fail gate.

## C. Proposed future structural/invariant testing approach

- **Typed-model assertions:** once the staged pipeline exists, validate structured output against `modules/domain_models.py` — e.g. every `Fact.status` ∈ `FactStatus`, allegations never stored as CONFIRMED (INVARIANT-001).
- **The eight invariants as machine checks** (ARCHITECTURE_SPEC_V1 §7): inferred figures labelled with basis (002), no service-based deadline without service-date evidence (003), citations verified-or-flagged (004), drafts never use UNKNOWN/NOT_AVAILABLE facts unconditionally (005), correct form/workflow before drafting (006), disputed truth never decided by the model (007), CA review gate (008).
- **Deterministic engines tested without an LLM:** Deadline Engine and arithmetic are pure functions — plain unit tests with known inputs/outputs, runnable offline.
- **Golden structural expectations** (`tests/expectations/`, created Phase 1.5): per-fixture notice-stated facts asserted against *structured extraction* (proceeding family, section, reply form, response period, hearing presence), never against the free-text blob.
- LLM calls stay in the loop only where reasoning is genuinely required; everything checkable by code must be checked by code.

## D. What should remain baseline-text testing

- `tests/baselines/*.baseline.md` remain the **human-review goldens**: a CA (or Dina) can diff a fresh run against the frozen baseline to review prose quality, tone, and unintended prompt drift.
- Before/after prompt changes: baseline diffs are the primary way to review intended vs collateral output changes.
- Baselines are review material, **not** automated pass/fail gates.

## E. What should become structured expectation testing

- `tests/expectations/NOTICE_*.expectations.json` — one file per fixture, containing **only what the notice itself states** (no legal conclusions): proceeding family, section, issue family, reply form, response-period days, service-based-deadline flag, hearing presence, fraud-allegation flag, Section-130-risk mention, RCM markers.
- These files will be consumed by the future phased pipeline (classifier + fact ledger + validator) so that, e.g., NOTICE_3's `reply_form: MOV-09` is asserted against the classified proceeding — the check that enforces INVARIANT-006.
- Values were verified against the extracted notice text on 2026-08-27 before being written.

---

## Development-environment housekeeping note (Phase 1.5, Step 6)

- An older Streamlit process from a previous session still occupies **port 8501** (confirmed still responding on 2026-08-27). The application code is NOT affected.
- **Do not kill unrelated user processes automatically.** The old process was not started by the current agent session and may belong to Dina's own browser/tab.
- Workaround when verifying the app: start new instances on another port — `python -m streamlit run app.py --server.headless true --server.port 8502` (verified working during Phase 1 validation).
- Resolution: Dina should close the old server (or the old tab) when convenient; no code change is involved.
