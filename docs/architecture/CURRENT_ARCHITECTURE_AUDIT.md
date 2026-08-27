# CURRENT ARCHITECTURE AUDIT — CA Notice Explainer → CA Notice AI

**Audit date:** 27-August-2026
**Auditor:** Claude Code (DeepSeek V4 Pro session)
**Scope:** Read-only audit. No source code, prompt, or behaviour changes were made.
**Documents compared against:** `ARCHITECTURE_SPEC_V1.md` (v1.0, dated 27-August-2026) and `IMPLEMENTATION_PLAN (1).md`.

---

## 0. VERIFIED CODEBASE INVENTORY (as found)

| Path | Size | Lines | Role |
|---|---|---|---|
| `app.py` | 937 B | 35 | Streamlit UI entrypoint, zero logic |
| `modules/__init__.py` | 0 B | 0 | Empty package marker |
| `modules/pdf_reader.py` | 1,275 B | 40 | PyMuPDF text extraction |
| `modules/llm_client.py` | 2,927 B | 83 | Google Gemini client + prompt templating |
| `modules/notice_explainer.py` | 2,619 B | 69 | Pipeline orchestrator |
| `prompts/notice_prompt.txt` | 18,148 B | 632 | Single universal prompt (v3.3) |
| `requirements.txt` | 45 B | 4 | streamlit, pymupdf, google-genai, python-dotenv |
| `data/sample_notices/` | — | — | 4 fixture notices + 2 generic test PDFs |
| `AGENTS.md` / `PROJECT_MEMORY.md` | — | — | Agent rulebook / auto-memory (Dina-owned / agent-maintained) |
| `ARCHITECTURE_SPEC_V1.md` / `IMPLEMENTATION_PLAN (1).md` | — | — | Target architecture + migration plan (Dina's docs) |

**Hard facts that constrain everything below:**

1. **This is NOT a git repository** (there is a `.gitignore` but no `.git`). Rollback today = manual file backup; there is no version history.
2. **There are no tests anywhere** (no `tests/`, no pytest, no test runner; `find -iname "*test*"` matches only the fixture PDF names).
3. **There is no `docs/` folder** prior to this audit document.
4. **3 of 4 regression fixtures have ever been run through the pipeline.** NOTICE_1, NOTICE_2, NOTICE_3 were each run end-to-end (PROJECT_MEMORY prompts #8, #9, #11). **NOTICE_4_RCM_Sec73_DRC01.pdf has never been exercised.**
5. **No database, no persistence, no files written at runtime.** The only output is an ephemeral in-memory dict handed to Streamlit.
6. **`.env` contains** `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.6-flash`, plus `NVIDIA_API_KEY` and `OPENAI_API_KEY` that no application code references.

---

## A. CURRENT SYSTEM

### A.1 Application entrypoint

- `app.py` is the sole entrypoint. Run command (per PROJECT_MEMORY KNOWN GOTCHAS): `python -m streamlit run app.py` (NOT bare `streamlit`, NOT `py -m`).
- Flow: `st.file_uploader("Upload Notice PDF", type="pdf")` → `uploaded.read()` → `explain_notice(pdf_bytes)` under a spinner → if `result["success"]`: `st.success` + `st.markdown(result["explanation"])` + an expander showing `result["raw_text"][:2000]`; else `st.error(result["error"])`.
- Footer caption: "Powered by Gemini AI".
- **No `st.session_state` usage anywhere**, despite AGENTS.md explicitly mandating it for anything that must survive Streamlit reruns. This works today only because the whole analysis is one synchronous call with no state to carry.

### A.2 Streamlit/UI structure

Single page, centered layout, zero logic. The UI has exactly two states: "no file uploaded" and "result of one analysis". There is no case list, no proceeding list, no evidence/documents panel, no deadline dashboard, no feedback capture, no review/approve control. Every structured requirement the spec places on Layer A ("show deadlines", "collect CA feedback") is currently absent from the UI.

### A.3 PDF/document extraction pipeline

`modules/pdf_reader.py` — one public function:

- `extract_text(pdf_bytes: bytes) -> str` opens the PDF from an in-memory stream via PyMuPDF (`fitz`), joins `page.get_text()` per page in order, closes the doc in `finally`.
- Corrupt/not-a-PDF → `RuntimeError("Could not read this PDF: ...")`.
- Empty text is returned as `""` — the caller interprets it as a scanned-PDF condition.

**What exists:** raw text only. **What does not exist:** table extraction, metadata (filename, page count, hash), page/source mapping of extracted spans, document classification, per-document records. There is no `Document` concept at all — the extracted string is anonymous.

### A.4 LLM/provider integration

`modules/llm_client.py`:

- Uses the **Google GenAI SDK** (`from google import genai`, package `google-genai` 2.19.0), configured once at module level: `genai.Client(api_key=os.getenv("GEMINI_API_KEY"))`, model from `os.getenv("GEMINI_MODEL", "gemini-3.6-flash")`.
- `_generate_once(prompt) -> str`: `client.models.generate_content(model=..., contents=prompt)` → `response.text or ""`.
- `call_gemini(prompt) -> str`: try/except returning `"Error: ..."` strings; one retry after 2s on empty text.
- No temperature/token controls, no structured output mode, no function calling, no streaming.

**Provider coupling:** `call_gemini` is hardwired to Google's SDK. There is no provider abstraction layer.

### A.5 DeepSeek V4 Pro invocation path

**There is no DeepSeek invocation path in the application code.** The runtime app calls only Google Gemini (`gemini-3.6-flash`).

The spec's "DeepSeek V4 Pro via Claude Code integration" (ARCHITECTURE_SPEC_V1.md §1) refers to the **agentic build loop**, not the runtime: the Claude Code sessions that develop this project are powered by DeepSeek V4 Pro (this session included; AGENTS.md's Agent Roster also lists DeepSeek V4 as the second-opinion agent in Antigravity). In other words:

| Path | Model | Where |
|---|---|---|
| Runtime analysis of uploaded notices | Gemini 3.6 Flash | `modules/llm_client.py` → Google API |
| Prompt authoring, verification runs, build loop | DeepSeek V4 Pro | Claude Code session (this environment) |

**Discrepancy to resolve:** ARCHITECTURE_SPEC_V1.md §4 Layer J states "DeepSeek V4 Pro is the reasoning/drafting worker" — but the only reasoning/drafting worker wired into the running product is Gemini. The UI caption ("Powered by Gemini AI") matches the code, not the spec. This must be settled explicitly before Phase 2+; a provider switch touches `modules/llm_client.py` and `.env` conventions and would require a DeepSeek API key + OpenAI-compatible SDK path (or a decision that "DeepSeek V4 Pro" in the spec means the build loop only).

### A.6 Prompt loading and templating

- `build_notice_prompt(notice_text, today)` in `llm_client.py` loads `prompts/notice_prompt.txt` (UTF-8, path resolved from `__file__`, not CWD) and does exactly two replacements: `.replace("{notice_text}", notice_text)` and `.replace("{today}", today)`.
- `today` is produced in `notice_explainer.py`: `date.today().strftime("%d-%B-%Y")` (e.g. "27-August-2026").
- The template is a **single universal mega-prompt, 632 lines**, containing in one file: role framing, evidence status vocabulary, source discipline, never-invent list, date/procedural discipline, eight output sections (Notice Facts / Allegations / Computation Review / Urgency / Evidence Gaps / Defences / Draft Reply / Client Message), Output Quality Rules, CA-action checklist, and the notice-text slot.
- Quirk: the OUTPUT QUALITY RULES block is numbered **1–7, 11, 12, 8, 9, 10** (rules 11 and 12 were inserted after rule 7 by task instruction and kept their labels; the file numbering is therefore non-sequential).

### A.7 Data flow: PDF → analysis → rendered output

```
PDF bytes
  └─ explain_notice(pdf_bytes)                    [modules/notice_explainer.py]
       ├─ extract_text(pdf_bytes)                 [modules/pdf_reader.py]
       │     ├─ RuntimeError → {success:False, error, raw_text:"", explanation:""}
       │     └─ "" → {success:False, error:"Scanned PDF detected…"}
       ├─ today = date.today().strftime("%d-%B-%Y")
       ├─ prompt = build_notice_prompt(text, today)  [modules/llm_client.py]
       ├─ explanation = call_gemini(prompt)          [modules/llm_client.py → Google Gemini]
       │     └─ starts with "Error" → {success:False, error, raw_text:text, explanation:""}
       └─ {success:True, explanation, raw_text, error:""}
              └─ app.py: st.markdown(explanation) + st.expander(raw_text[:2000])
```

**Critical property:** the LLM output is one free-form markdown blob. There is **no structured intermediate representation** between raw text and rendered output. Facts, allegations, deadlines, evidence gaps, defences, the draft reply and the client message are all produced in a single LLM pass as one string. The only "structuring" is the result dict's four keys.

### A.8 Persistent state / data models

**None.** No database, no JSON files, no dataclasses/Pydantic models, no session persistence. Every run is stateless and independent. No Case, Proceeding, Document, Fact, Evidence, Issue, Deadline, Workflow, LegalReference, Draft, or Validation types exist anywhere in code.

### A.9 Validation logic

**None in code.** The only code-level guards are: corrupt-PDF `RuntimeError`, scanned-PDF empty-text check, `"Error"` prefix check on the Gemini reply, one empty-response retry. All substantive validation (status labels, source discipline, service-date discipline, citation discipline, CA-verification checklist) is **prompt text only** — the LLM is asked to self-discipline, and nothing in code verifies the output. There is no Output Validator equivalent.

### A.10 Tests / regression mechanisms

**None.** No test files, no test framework, no CI. The de-facto regression practice so far is ad-hoc manual runs of `explain_notice()` via `python -c` against the fixture PDFs, with outcomes recorded narratively in PROJECT_MEMORY.md (prompts #8, #9, #11). There are no golden/expected outputs.

### A.11 PROJECT_MEMORY conventions

`PROJECT_MEMORY.md` is the project's only cross-session memory. Conventions (enforced by AGENTS.md AUTO-MEMORY RULE):
- Header block (`Last Updated`, `By`, `Prompt Count` — currently 19).
- `CURRENT STATE` block (Phase / Working / Broken / Next Task).
- `FILE STATUS` table + Test-PDF inventory.
- `SESSION LOG` — newest first, fixed format (`[PROMPT #N — TASK — HH:MM]` with Task/Did/Files/Errors/Attempts/Fix/Status).
- `ERROR REGISTRY` (numbered ERR-/NOTE- entries with symptoms and fixes).
- `KNOWN GOTCHAS` (environment quirks, e.g. exact run command, cp1252 console encoding).
- `DECISIONS MADE` table (includes Prompt v3 → v3.3 decisions).
- `FEATURES DONE` checklist.

This file is the closest thing the project has to a change log and design-decision log and must be preserved as the audit trail through the migration.

### A.12 Current architecture reusable as-is (summary)

See section D for detail. In one line: extraction + single-shot LLM reasoning + result-dict contract, all cleanly separated into three single-purpose modules — a sound skeleton into which the spec's layers can be inserted.

---

## B. TARGET ARCHITECTURE (from ARCHITECTURE_SPEC_V1.md, condensed)

Layers A–K: UI (retain Streamlit) → Case Manager → Document Intelligence → Proceeding Classifier → Deterministic Engines (arithmetic/dates/deadlines/status/validation — **code, not LLM**) → Fact/Evidence Engine (only structured facts reach drafting) → Issue Engine (reusable issue modules) → Workflow Engine → Legal Knowledge (versioned, verified) → LLM Reasoning (DeepSeek V4 Pro per spec; structured inputs, replaceable) → Output Validator (pre-delivery checks).

Domain model: Client → Case → TaxRegistration → Proceeding → Documents/Facts/Evidence/Issues/Deadlines/WorkflowRuns/LegalReferences/Tasks/Drafts/Reviews, each with minimum field sets and enumerations (Fact statuses are exactly the five labels the current prompt already uses).

Prompt architecture after migration: **8 small prompt contracts** (extraction, classification, issue identification, legal explanation, working paper, draft reply, client message, validation) — explicitly "do not maintain one universal mega-prompt". Workflow-specific instructions live in workflow definitions (P0: S.73 general, S.74, RCM, ITC mismatch, S.129/MOV).

Eight critical invariants (INVARIANT-001…008) that must hold at all times.

MVP acceptance is gated on: correct classification, correct form selection, no unconditional unsupported facts, explicit deadline uncertainty without service date, deterministic/validated arithmetic, verified-or-flagged citations, actionable evidence gaps, workflow-differentiated steps, automated regression, traceable CA feedback.

---

## C. GAP ANALYSIS (current prototype vs spec)

| Spec element | Current state | Gap |
|---|---|---|
| Layer A — UI | `app.py` upload+render only | No deadlines view, no evidence-gaps view, no draft view as separate artifact, no CA feedback capture |
| Layer B — Case Manager | Absent | No case lifecycle, no client/case linkage, no persistence |
| Layer C — Document Intelligence | Only `extract_text` (raw text) | No tables, metadata, page/source mapping, document classification, Document records, hashing |
| Layer D — Proceeding Classifier | Absent as code | Classification happens implicitly inside the single LLM call; no explicit unknown/ambiguous state; no confidence |
| Layer E — Deterministic Engines | Absent | All arithmetic, date math, day counts and deadline logic are done by the LLM (directly contrary to spec: "must be code-driven") |
| Layer F — Fact/Evidence Engine | Absent | Draft generation consumes the raw prompt/LLM blob; no Fact/Evidence store; no provenance fields |
| Layer G — Issue Engine | Absent | Issue vocabulary exists only inside prompt Section 6; no reusable issue modules |
| Layer H — Workflow Engine | Absent | One universal prompt for all proceeding types; no workflow registry/taxonomy in code |
| Layer I — Legal Knowledge | Absent (spec defers it) | No gap *yet*; Rule 12's `[CA LEGAL RESEARCH REQUIRED]` marker is the conceptual seed |
| Layer J — LLM Reasoning | Gemini one-shot, mega-prompt | Provider mismatch vs spec (Gemini vs DeepSeek V4 Pro); no structured input contract; not "replaceable" (hardwired SDK call) |
| Layer K — Output Validator | Absent in code | Prompt-only self-policing; nothing checks the output before it reaches the CA |
| §3 domain model | Absent entirely | No typed models of any kind (see A.8) |
| §8 prompt architecture | One 632-line mega-prompt | Direct violation of the spec's "no universal mega-prompt" directive |
| §9 migration phases | Phase 1 not started | — |
| Invariants 001–008 | Present **as prompt rules only** (v3, v3.1, v3.2, v3.3 additions) | Zero code enforcement; honoured only if the LLM complies run-by-run |
| Regression testing | Manual, ad-hoc | No automation; NOTICE_4 never exercised; no golden outputs |

**Domain-concept equivalence table (spec §3 vs current prototype):**

| Spec concept | Present in prototype? | Where |
|---|---|---|
| Case | ❌ No equivalent | — |
| Proceeding | ◐ Partial, unstructured | Prompt Section 1 "NOTICE FACTS" field list (taxpayer, GSTIN, form, authority, ref no, notice date, FY/tax period, sections cited, amounts, reply form, response period, service date, deadline, hearing, status) — free text in the LLM blob |
| Document | ◐ Implicit only | `result["raw_text"]` string; no id/filename/hash/page count/extraction status |
| Fact | ◐ Partial | The prompt's five status labels `[CONFIRMED] / [ALLEGED BY DEPARTMENT] / [NOT AVAILABLE] / [REQUIRES VERIFICATION] / [INFERRED]` are **exactly** the spec's Fact statuses — but emitted as prose, with no fact records, no source_document_id/page/excerpt, no confidence, no draft_permission |
| Evidence | ◐ Partial | Prompt Section 5 "EVIDENCE GAPS" (ITEM / WHY IT MATTERS / STATUS) ≈ spec Evidence fields (requested_reason, status); free text only |
| Issue | ◐ Partial | Prompt Section 6 with sub-fields (LEGAL BASIS, WHY IT MAY BE RELEVANT, FACTS REQUIRED, EVIDENCE REQUIRED, LIMITATIONS/RISKS, INITIAL ASSESSMENT) ≈ spec Issue fields; no issue_id/severity/legal_basis_refs |
| Deadline | ◐ Partial | Prompt DATE AND PROCEDURAL DISCIPLINE + Section 1 date fields; **computed by the LLM**, not by code; no Deadline records |
| Workflow | ❌ No equivalent | Universal prompt; no registry, no triggers/required_facts/validation_rules |
| LegalReference | ◐ Emerging | Prompt Rule 12 + `[CA LEGAL RESEARCH REQUIRED: …]` marker distinguishes verified vs unverified authority; no legal_ref records |
| Draft | ◐ Partial | Prompt Section 7 produces the draft inside the same output blob; no separate Draft object/versioning |
| Validation | ❌ No code equivalent | OUTPUT QUALITY RULES 1–12 + "═══ CA ACTION REQUIRED BEFORE FILING ═══" exist only as prompt text |

---

## D. REUSABLE COMPONENTS (current assets that survive migration unchanged or nearly unchanged)

| Component | Reuse | Notes |
|---|---|---|
| `modules/pdf_reader.py` | ✅ As-is | Spec Phase 1 says "preserve current document extraction". Becomes the first stage of Document Intelligence. Do not modify. |
| `modules/llm_client.py::build_notice_prompt` | ✅ As-is | Template-from-`prompts/` loader (UTF-8, path from `__file__`) generalises directly to the spec's 8 prompt contracts — same mechanism, more files. |
| `modules/notice_explainer.py` orchestration + result-dict contract | ◐ As seam | The `{success, explanation, raw_text, error}` dict is the stable UI contract. New layers should be inserted *inside* `explain_notice`, keeping the dict shape so `app.py` never changes. `today` stamping is the seed of the Deadline Engine's `today` input. |
| `prompts/notice_prompt.txt` rule inventory | ◐ As specification source | The 632-line prompt is a de-facto requirements document: the status vocabulary (→ Fact.status enum), the never-invent list (→ validator checks + Fact provenance rules), the date/procedural discipline (→ Deadline Engine behaviour spec), Rule 11 (→ deterministic arithmetic + inferred-figure labelling), Rule 12 (→ LegalReference verification rules), Section 7 rules v3.2/v3.3 (→ draft-prompt contract + INVARIANT-005 checks), Output Quality Rules (→ Output Validator check list). **Extract the rules from the prompt; do not lose them.** |
| Prompt Section 6 sub-field format | ◐ Template | Its structured key list is a ready-made field layout for the Issue model. |
| `data/sample_notices/` fixtures | ✅ As-is | The four NOTICE_*.pdf are the regression corpus named by the spec (§6) — spec fixtures 001–004 map 1:1. |
| Result-dict error conventions (`"Error: "` prefix, RuntimeError mapping) | ✅ As-is | Already a serviceable failure contract; keep. |
| PROJECT_MEMORY.md conventions | ✅ As-is | Audit trail, error registry, decisions log — the migration's change history until git exists. |

---

## E. COMPONENTS THAT MUST BE EXTRACTED (from prompt text → code/models)

Each line names the prompt artifact, the target code home, and the invariant it will enforce.

| Prompt artifact (current location in `prompts/notice_prompt.txt`) | Must become | Enforces |
|---|---|---|
| Status labels block (§CORE EVIDENCE DISCIPLINE, ~lines 12–28) | `Fact.status` enum: CONFIRMED / ALLEGED_BY_DEPARTMENT / NOT_AVAILABLE / REQUIRES_VERIFICATION / INFERRED (typed model) | INVARIANT-001, spec §3.4 |
| DATE AND PROCEDURAL DISCIPLINE block (~lines 62–105) | Deterministic Deadline Engine (inputs: notice_date, service_date, response_period, hearing_date, today; outputs: deadline + explicit uncertainty states) | INVARIANT-003 |
| Rule 11 (~lines 557–575) | Deterministic arithmetic helpers + inferred-figure labelling in the Fact model | INVARIANT-002 |
| Rule 12 (~lines 576–606) | LegalReference model with verification_status; notice-cited vs independently-verified distinction | INVARIANT-004 |
| Section 7 factual rules (v3.2 ~lines 382–401; v3.3 ~lines 403–523) | Draft-prompt contract + validator checks (no unconditional UNKNOWN/NOT_AVAILABLE facts in drafts) | INVARIANT-005, INVARIANT-007 |
| OUTPUT QUALITY RULES 1–12 (~lines 547–615) | Output Validator check list (Layer K) | All invariants |
| "═══ CA ACTION REQUIRED BEFORE FILING ═══" (~lines 618–624) | Task/Review model seed + UI review gate | INVARIANT-008 |
| Section 1 NOTICE FACTS fields (~lines 108–143) | Proceeding model fields + Proceeding Classifier inputs | INVARIANT-006, spec §3.2 |
| Section 5 EVIDENCE GAPS (~lines 244–274) | Evidence model records (PRESENT/MISSING/REQUESTED/VERIFIED/REJECTED) | MVP "evidence gaps are actionable" |

---

## F. RISKS

**R1 — Prompt regression on split (highest probability).** The 632-line mega-prompt works today across three fixtures. Its sections are cross-dependent (Section 7 draft rules lean on Section 2's allegation labels; Rule 11 feeds Section 1/2/3 figures). Splitting into 8 contracts without a shared vocabulary header will regress output on all four fixtures simultaneously. Mitigation: keep a shared "evidence vocabulary + invariants" preamble in every contract; run all four fixtures before/after each split.

**R2 — Deterministic engines will change visible output.** Once code computes deadlines/arithmetic, Section 1/3/4 output differs from today's LLM-authored wording (e.g., "Illustrative estimate assuming service occurred on 22-08-2026"). Any automated comparison must compare *facts and statuses*, not text.

**R3 — Provider ambiguity (Gemini vs DeepSeek).** Spec Layer J names DeepSeek V4 Pro; runtime is Gemini. If the intent is to migrate the runtime to DeepSeek, `modules/llm_client.py` needs a provider-neutral interface, a new API key, and model-selection conventions; all four fixtures must be re-verified under the new provider (output tone/length will shift). If the intent is build-loop-only, the spec wording should be corrected. **Decide before Phase 2.**

**R4 — Persistence conflicts with AGENTS.md.** AGENTS.md NEVER-rules forbid adding databases/auth without asking Dina. A Fact ledger and Case manager need storage (SQLite/JSON). This is an explicit approval gate, not a silent implementation.

**R5 — No git, no tests, no golden outputs.** Any regression suite is built from zero, and rollback relies on file backups until `git init` happens (needs Dina's go-ahead — outside agent authority). The current "expected output" knowledge lives only in PROJECT_MEMORY narrative entries.

**R6 — Validator calibration.** A naive Output Validator will flag phrasing the current prompt deliberately permits (e.g., §C.2 "is unsustainable" under a submission wrapper, §B.6's hedged "bona fide commercial transaction", §3's S.73 penalty mechanics). Validator must check *labelling and framing*, not reject every assertive word, or it will reject working drafts.

**R7 — Form-selection fragility.** The DRC-06-vs-MOV-09 distinction (INVARIANT-006) is currently prompt luck — verified only because the v3.3 run on NOTICE_3 happened to render "MOV-09/DRC-01". A workflow engine that picks the wrong form turns a correct draft into a wrong one.

**R8 — Environment fragility.** Known quirks (Windows cp1252 console, model ID discontinuations like gemini-2.5-flash → 404, non-sequential rule numbering in the prompt) will confuse future agents mid-migration; they are documented only in PROJECT_MEMORY.

**R9 — NOTICE_4 is untested.** The RCM fixture has never been run; its notification-citation (Notification No. 13/2017-CT (Rate)) is the first fixture where Rule 12's "explicitly contained in the source material" carve-out is exercised. Its behaviour is unknown until run.

---

## G. MIGRATION ORDER (recommended, aligned with spec §9 + IMPLEMENTATION_PLAN steps)

| Step | Work | Files affected (exact) | Behaviour change? |
|---|---|---|---|
| 0 | **Preconditions:** run NOTICE_4 through the current pipeline to establish the baseline; ask Dina about `git init` (R5) and storage (R4); settle Gemini-vs-DeepSeek intent (R3) | none (run only) | No |
| 1 | **Domain contracts:** typed dataclasses for Case, Proceeding, Document, Fact (+status enum), Evidence, Issue, Deadline, Workflow, LegalReference, Draft, ValidationResult, mirroring spec §3 field lists | NEW `modules/domain_models.py` | No |
| 2 | **Regression scaffold:** stdlib-only runner executing `explain_notice()` on all four fixtures; asserts result-dict contract + presence of the five status labels + absence of bare "valid/g genuine invoice" strings in the draft section of output | NEW `tests/run_regression.py` | No |
| 3 | **Baseline snapshot:** record current prompt hash + outputs of all four fixtures (golden-ish baselines, text-normalized) | NEW `tests/baselines/` | No |
| 4 | **Deadline Engine** (deterministic; returns explicit uncertainty without service date) wired beside — not instead of — the LLM; Section 1/4 facts sourced from the engine | NEW `modules/deadline_engine.py`; MODIFY `modules/notice_explainer.py` | Yes (dates become code-computed) |
| 5 | **Fact/Evidence store + extraction stage:** split the current single call into (a) extraction/classification call feeding Fact/Evidence records, (b) working-paper call consuming those records; keep the final merged markdown for the UI | NEW `modules/fact_ledger.py`, `modules/evidence_store.py`; MODIFY `modules/notice_explainer.py`; MODIFY/Split `prompts/notice_prompt.txt` (extraction + working-paper contracts; original preserved as legacy) | Yes (staged calls) |
| 6 | **Proceeding Classifier + Workflow Registry** with the five P0 families; workflow definitions in config, not prompts | NEW `modules/classifier.py`, `modules/workflows/` (+registry) | Yes |
| 7 | **Draft sourcing rule:** draft generator consumes only Fact/Evidence records (spec Layer F gate) | MODIFY draft prompt contract | Yes |
| 8 | **Output Validator:** checks from the prompt's Rules 1–12 as code checks; flag/reject before render | NEW `modules/output_validator.py`; MODIFY `modules/notice_explainer.py` | Yes (UI gains warnings) |
| 9 | **Legal Knowledge seed:** LegalReference records + verification_status; notice-cited vs verified distinction | NEW `modules/legal_references.py` | Yes |
| 10 | **CA pilot** | — | — |

Per the non-goals: no complete rewrite, no Income Tax, no autonomous filing, no case-law automation without verified sources, no universal mega-prompt.

---

## H. FILE-BY-FILE IMPLEMENTATION PLAN

For every file, current role → planned change → exact current file(s) affected.

| # | Current file (exact) | Current role | Planned change | New/modified |
|---|---|---|---|---|
| 1 | — | — | `modules/domain_models.py` — dataclasses + enums per spec §3 (Proceeding, Document, Fact, Evidence, Issue, Deadline, Workflow, LegalReference, Draft, Case, ValidationResult) | NEW |
| 2 | — | — | `tests/run_regression.py` — stdlib-only runner over the four fixtures | NEW |
| 3 | — | — | `tests/baselines/` — normalized baseline outputs | NEW |
| 4 | `modules/notice_explainer.py:57` (`today = date.today()…`) | stamps `{today}` | Deadline Engine input (`today`) moves to engine call; orchestrator passes notice fields in | MODIFIED |
| 5 | `modules/notice_explainer.py:41-69` (single `extract → prompt → call_gemini` chain) | orchestration | Staged pipeline: extraction → classifier → fact/evidence → deadline → drafting → validation, re-assembling the same `{success, explanation, raw_text, error}` dict | MODIFIED |
| 6 | `modules/llm_client.py:27-46` (`build_notice_prompt`) | single-template loader | Generalize to a template-by-name loader (`build_prompt(contract_name, **kwargs)`); keep old signature as a thin wrapper during transition | MODIFIED |
| 7 | `modules/llm_client.py:49-82` (`call_gemini`/`_generate_once`) | hardwired Google SDK | Introduce a provider-neutral `call_llm()`; keep `call_gemini` delegating to it; add DeepSeek adapter only if R3 resolves to runtime migration | MODIFIED |
| 8 | `prompts/notice_prompt.txt` (632 lines) | universal mega-prompt | Split into contract files under `prompts/` (extraction, classification, issues, legal-explanation, working-paper, draft-reply, client-message, validation) each carrying the shared vocabulary preamble; **original file preserved unchanged as `prompts/notice_prompt.legacy.txt` for rollback** | SPLIT (new files) / original preserved |
| 9 | `app.py` | render single blob | Unchanged through all phases except (later, optional) adding validator warnings / deadline and evidence-gap panels. Spec says preserve the UI initially | UNTOUCHED until pilot feedback |
| 10 | `modules/pdf_reader.py` | text extraction | Unchanged (spec: preserve document extraction) | UNTOUCHED |
| 11 | `requirements.txt` | 4 deps | Unchanged unless Dina approves a storage or testing dependency | UNTOUCHED (approval gate) |
| 12 | `.env` | Gemini key/model | Unchanged unless R3 resolves to runtime DeepSeek (add `DEEPSEEK_API_KEY`, model vars) | UNTOUCHED (approval gate) |
| 13 | `data/sample_notices/*.pdf` | fixtures | Used as regression corpus; never modified | UNTOUCHED |

---

## I. WHAT SHOULD REMAIN UNCHANGED

1. **`modules/pdf_reader.py`** — extraction is correct, tested, and the spec says preserve it.
2. **The result-dict contract** (`success/explanation/raw_text/error`) — the stable boundary the UI depends on; new layers adapt to it, not the reverse.
3. **`app.py`'s render behaviour** during Phases 1–4 — the UI must keep rendering the working paper unchanged while the internals change.
4. **The five status labels and their meanings** — they are the domain vocabulary; every prompt contract and model enum must use exactly these.
5. **The eight invariants** — any refactor is a regression if one stops holding.
6. **The never-invent list and Rules 11/12, v3.2/v3.3 draft rules** — they must be carried into code/contracts verbatim in substance (they are the accumulated hard-won discipline of prompts v3 → v3.3).
7. **The four fixture PDFs** — unmodified regression corpus.
8. **PROJECT_MEMORY.md conventions** — kept current after every step (AGENTS.md rule), including this audit.
9. **AGENTS.md, ARCHITECTURE_SPEC_V1.md, IMPLEMENTATION_PLAN (1).md** — Dina-owned documents; agents do not edit them without direction.
10. **The original mega-prompt** — preserved as a legacy fallback file when split (never deleted).

---

## J. WHAT MUST NOT BE DONE YET

1. **No prompt split** until Step 0 baseline (including a NOTICE_4 run) exists — splitting first would leave no baseline to detect regression (R1).
2. **No provider switch** until R3 is decided; do not add a DeepSeek SDK or key to the runtime speculatively.
3. **No storage/database/persistence** until Dina approves (AGENTS.md NEVER-rule; R4).
4. **No Income Tax domain**, no autonomous filing, no portal actions (spec out-of-scope).
5. **No "verified case-law" automation** without the Legal Knowledge subsystem; keep `[CA LEGAL RESEARCH REQUIRED]` until then.
6. **No UI redesign** (case lists, dashboards) before the data layers exist — UI against models, not against strings.
7. **No validator enforcement in the UI** (hard rejections) until calibration against all four fixtures is done (R6).
8. **No deletion of the current prompt, modules, or fixtures** at any point in this migration.
9. **No golden-output thresholds** that compare raw text equality — LLM output is non-deterministic; assert on facts/statuses/labels (R2).

---

## K. REGRESSION-FIXTURE BREAK-POINT ANALYSIS

Where the current implementation is most likely to break when the workflow architecture is introduced — fixture by fixture.

### Fixture 001 — NOTICE_1_ITC_Mismatch_DRC01 (S.73, ITC/GSTR-2B)

- **Classification ambiguity:** cites both S.73(1) *and* S.16(2)(aa)/R.36(4). A naive classifier may tag it generic `GST_SEC_73_GENERAL` instead of `GST_SEC_73_ITC` — which drives entirely different evidence items (GSTR-2B/2A reconciliation vs generic demand). INVARIANT-006 risk.
- **Known incident to guard:** the LLM once inserted the *derived* GSTR-2B figure ₹4,72,500 (= 7,84,500 − 3,12,000) into an `[ALLEGED BY DEPARTMENT]` item. A deterministic arithmetic + validator pairing (Rule 11) is the fix; the fixture is the regression test for it.
- **Deadline/status:** hearing 04-08-2026 passed; service date absent. A deterministic engine must output "hearing passed → order status unknown → verify portal", and the validator must reject any "no order has been passed" phrasing (Rule 9).
- **Likely first break point:** the staged extraction→drafting split — the draft section's ITC reconciliation table template currently derives from raw prompt context; once the draft consumes only structured Facts, the table must come from Evidence records (GSTR-2B/3B) that don't exist yet.

### Fixture 002 — NOTICE_2_Fraud_Sec74_DRC01 (S.74 fraud/suppression)

- **Proceeding-family risk:** S.74 vs S.73 demotion. The prompt's own discipline (allegations stay allegations) is exactly what a hard Fact ledger must encode — if the extraction stage stores "fraud" as a CONFIRMED fact, every downstream stage breaks INVARIANT-001.
- **Draft temptation:** the v3.2 rules exist precisely because the model asserted "no underlying tax evasion"/"Section 74 inapplicable". The draft contract + validator must keep enforcing submission-framing (INVARIANT-005/007); this fixture is the regression test.
- **Issue-module fit:** TURNOVER_RECONCILIATION (bank credits vs 26AS vs RERA) and FRAUD_SUPPRESSION modules both apply; a workflow that runs only one will miss the other.
- **Likely first break point:** Output Validator — today's output still contains §C.2 "is unsustainable" phrasing (recorded residual). A strict validator flags it; calibration must accept submission-wrapped conclusions (R6).

### Fixture 003 — NOTICE_3_EWayBill_Sec129_DRC01 (S.129, MOV-09)

- **Form-selection risk (highest of all fixtures):** the proceeding is DRC-01 *and* MOV-09, reply in **MOV-09** — every other fixture replies in DRC-06. A workflow engine that defaults to DRC-06 produces a wrong-form draft. INVARIANT-006 is directly at stake, and the spec's MVP gate ("correct form selected") exists largely because of this fixture.
- **Deadline stress:** 7-day period AND a stated date ("on or before 27-08-2026") AND service-date basis. The Deadline Engine must handle the explicit-stated-date vs service-period tension without collapsing one into the other.
- **Prompt coverage gap:** there are no e-way-bill/detention-specific rules in the current prompt (EWAY_BILL and DETENTION issue modules have no prompt counterpart yet); v3.3's strict source discipline (invoice terminology, no assumed E-Way Bill reason) is the only protection. The workflow layer must *add* rules here, not just reorganize.
- **Likely first break point:** workflow selection + draft form header. The MOV-09 workflow needs its own draft contract (release-of-goods prayer, 7-day urgency) that does not exist in the current universal prompt.

### Fixture 004 — NOTICE_4_RCM_Sec73_DRC01 (S.73, RCM — **never run to date**)

- **Unknown baseline:** no current output exists, so no regression comparison is possible until Step 0 runs it. Any architecture change before that run leaves this fixture with no before/after.
- **Notification citation:** the notice itself cites "Notification No. 13/2017-CT (Rate) dated 28-06-2017". Rule 12 permits citations "explicitly contained in the source material" — so the model may state it. The LegalReference model must distinguish **notice-cited** authority from **independently verified** authority, or the validator will either wrongly flag it or wrongly let it pass.
- **RCM specifics:** S.9(3) liability, GSTR-3B Table 3.1(d), 26AS/S.194J TDS evidence, "To be det." penalty, future deadline (17-09-2026) with future hearing (22-09-2026). The RCM workflow must pull in evidence items the generic S.73 workflow never asks for.
- **Likely first break point:** classification — RCM is a *type* of S.73 proceeding, so the classifier must key on S.9(3)/RCM/notification signals, not on S.73 alone; misclassification silently merges RCM into the generic S.73 workflow.

**Cross-fixture break points (ranked):**

1. `explain_notice()` return contract vs staged pipeline (all four fixtures) — the UI consumes one markdown blob; stages must re-assemble it (A.7/H.5).
2. Prompt split without shared vocabulary (all four) — R1.
3. Form/workflow selection (003 worst, then 001's ITC-vs-general ambiguity, 004's RCM-vs-general) — INVARIANT-006.
4. Deterministic dates/arithmetic replacing LLM math (001, 003, 004) — R2.
5. Draft sourcing gate (001's ITC table, 002's fraud drafting) — INVARIANT-005.
6. Validator calibration against currently-tolerated phrasing (002) — R6.
7. LegalReference verification for notice-cited vs verified citations (004) — INVARIANT-004.

---

## L. RECOMMENDATIONS

### 1. Recommended first implementation step

**Step 0 (preconditions), then Step 1+2 combined as the first code step:**

- **Step 0a:** Run NOTICE_4_RCM_Sec73_DRC01.pdf through the *current unchanged* pipeline and record the full output — establishes the missing baseline for the only untested fixture. (Execution-only; no file changes.)
- **Step 0b:** Ask Dina: (i) `git init` before any migration (rollback safety — currently no version control), (ii) storage approval for Phase 2+ (AGENTS.md gate), (iii) Gemini-vs-DeepSeek runtime intent (spec wording).
- **Step 1+2 (first code change):** Create `modules/domain_models.py` (typed dataclasses/enums mirroring spec §3, including the five Fact statuses) and `tests/run_regression.py` (stdlib-only runner executing `explain_notice()` against all four fixtures and asserting the result-dict contract + status-label presence). **Strictly additive — zero behaviour change.**

Rationale: contracts first (per IMPLEMENTATION_PLAN Step 2: "Do not change UI behavior yet"), regression scaffolding second, so every later phase has an automated before/after.

### 2. Files that step would touch

- **NEW:** `modules/domain_models.py`
- **NEW:** `tests/run_regression.py` (stdlib-only; no new pip dependencies — AGENTS.md requires asking before adding libraries)
- **No existing file modified.**

### 3. Files that must remain untouched

- `app.py`
- `modules/pdf_reader.py`
- `modules/llm_client.py`
- `modules/notice_explainer.py`
- `prompts/notice_prompt.txt`
- `data/sample_notices/` (all PDFs)
- `.env`
- `requirements.txt`
- `AGENTS.md`, `ARCHITECTURE_SPEC_V1.md`, `IMPLEMENTATION_PLAN (1).md` (Dina-owned)
- `PROJECT_MEMORY.md` (except its mandated log update)

### 4. Rollback strategy

- **Step 1+2 are additive-only:** rollback = delete `modules/domain_models.py` and `tests/run_regression.py`. Nothing else can regress.
- **Before any later phase that modifies existing files** (`notice_explainer.py`, `llm_client.py`, prompt split): take a dated backup snapshot (e.g. `backups/2026-08-27/` with copies of all touched files + the full prompt) or — preferred, pending Dina's approval — `git init` + baseline commit. There is currently **no git history to roll back to**, so a snapshot is mandatory before Phase 4+ (see G step 4).
- **Prompt split:** preserve `prompts/notice_prompt.txt` verbatim as `prompts/notice_prompt.legacy.txt`; any contract-split regression is then reversible by repointing the loader to the legacy file (one-line change in `llm_client.py`).
- **Pipeline surgery:** keep the old single-shot path as a fallback branch inside `notice_explainer.py` (e.g., `USE_STAGED_PIPELINE` flag defaulting to the legacy path) until all four fixtures pass under the staged path — flip the default only after regression passes.

---

*End of audit. No code, prompt, or behaviour was changed during this audit; the only new artifact is this document.*
