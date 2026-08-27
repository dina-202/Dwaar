# PROJECT MEMORY — CA Notice Explainer Tool
> Auto-updated by the agent after every prompt. Do not edit manually.

**Last Updated :** 2026-08-27
**By            :** Claude Code
**Prompt Count  :** 21

---

## CURRENT STATE
```
Phase       : ARCHITECTURE PHASE 1 COMPLETE — additive only, app behaviour unchanged
Git         : repo initialized by Dina; baseline commit 4f09e38 "baseline: working
              CA notice explainer before architecture migration". HEAD = 4f09e38.
              Working tree clean for all tracked files; untracked new files only:
              modules/domain_models.py, tests/.
Working     : (1) NOTICE_4 runtime baseline captured — tests/baselines/
              NOTICE_4_RCM_Sec73_DRC01.baseline.md (19,159-char Gemini output,
              2,665 raw chars, gemini-3.6-flash, prompt v3.3) + .metadata.json.
              (2) modules/domain_models.py — typed dataclasses/enums for Case,
              Proceeding, Document, Fact, Evidence, Issue, Deadline, Workflow,
              LegalReference, Draft, ValidationResult; FactStatus enum exactly
              CONFIRMED/ALLEGED_BY_DEPARTMENT/NOT_AVAILABLE/REQUIRES_VERIFICATION/
              INFERRED; stdlib only; NOT wired into the app; independently
              importable. (3) tests/run_regression.py — stdlib-only runner over
              the four NOTICE_*.pdf fixtures; saves runs to tests/outputs/;
              compares vs tests/baselines/; statuses PASS/FAIL/BASELINE_MISSING/
              EXECUTION_ERROR. First run: NOTICE_4 PASS (baseline compared),
              NOTICE_1–3 BASELINE_MISSING (expected), 0 FAIL/EXECUTION_ERROR.
              Streamlit verified to start (my instance came up on 8502 — port
              8501 is held by an older server; old server should be stopped
              eventually).
Broken      : Nothing
Next Task   : (Dina) review Phase 1; nothing further without instruction. Phase 2
              per plan: Deadline Engine + Fact/Evidence store + draft consumes
              structured facts. NOTICE_1–3 baselines still missing — capture them
              (promote tests/outputs/ runs to baselines) when instructed.
```

---

## FILE STATUS
| File | Status |
|---|---|
| app.py | ✅ created — Streamlit UI, zero logic |
| modules/pdf_reader.py | ✅ created + TESTED on 2 real PDFs |
| modules/llm_client.py | ✅ created + TESTED — model fallback now gemini-3.6-flash |
| modules/notice_explainer.py | ✅ created — explain_notice(pdf_bytes) -> dict |
| prompts/notice_prompt.txt | ✅ rewritten — 6-section GST template + {today} + {notice_text} |
| requirements.txt | ✅ created — 4 libs; google-generativeai → google-genai (migrated) |
| .env | ✅ created — real key + GEMINI_MODEL=gemini-3.6-flash (key value never logged) |
| .gitignore | ✅ created — .env is ignored |
| modules/__init__.py | ✅ created — empty |
| modules/domain_models.py | ✅ created (Phase 1) — typed dataclasses/enums, stdlib only, NOT wired to app |
| tests/run_regression.py | ✅ created (Phase 1) — stdlib-only runner, runs existing pipeline on 4 fixtures |
| tests/baselines/NOTICE_4_RCM_Sec73_DRC01.baseline.md | ✅ created (Phase 1) — runtime baseline, 19,159 chars |
| tests/baselines/NOTICE_4_RCM_Sec73_DRC01.metadata.json | ✅ created (Phase 1) — baseline metadata |
| tests/outputs/*.analysis.md | ✅ generated (Phase 1) — regression runs for NOTICE_1–4, regenerated each run |
| docs/architecture/CURRENT_ARCHITECTURE_AUDIT.md | ✅ created — read-only audit, sections A–L, no code changed |

**Folders:** modules/ ✅ · prompts/ ✅ · data/sample_notices/ ✅

**Test PDFs in data/sample_notices/:**
| File | Source | Pages | Chars extracted |
|---|---|---|---|
| test_sample.pdf | W3C dummy.pdf | 1 | 15 |
| test_sample_multipage.pdf | IRS Publication 1 | 2 | 11,562 |

> NOTE: Four real GST notices are now present in data/sample_notices/:
> NOTICE_1 (S.73 ITC/GSTR-2B mismatch), NOTICE_2 (S.74 fraud/suppression),
> NOTICE_3 (S.129 e-way bill), NOTICE_4 (S.73 RCM). Verified end-to-end on all four.
> NOTICE_4 runtime baseline captured in tests/baselines/ (Phase 1, 2026-08-27);
> NOTICE_1–3 still have no baselines (runner reports BASELINE_MISSING).

---

## SESSION LOG
> Most recent prompt at the TOP

[PROMPT #13 — ARCHITECTURE PHASE 1 — 19:05]
Task     : Architecture Phase 1 — controlled migration. Verify git baseline 4f09e38;
           capture NOTICE_4 runtime baseline; create typed domain models
           (modules/domain_models.py) and a stdlib-only regression runner
           (tests/run_regression.py); validate; update memory. NO changes to
           app.py, modules/*.py (existing), prompts, PDFs, .env; no new deps;
           no Gemini→DeepSeek switch.
Did      : Architecture Phase 1 — Git baseline already established as 4f09e38;
           NOTICE_4 runtime baseline captured; typed domain models and initial
           standard-library regression runner introduced without changing
           existing application behavior.
           (1) Confirmed HEAD = 4f09e38 "baseline: working CA notice explainer
           before architecture migration", working tree clean before work.
           (2) Ran NOTICE_4_RCM_Sec73_DRC01.pdf through the EXISTING pipeline
           (Gemini gemini-3.6-flash, prompt v3.3): SUCCESS, 2,665 raw chars,
           19,159-char analysis, all 8 sections, status labels verified.
           Saved verbatim to tests/baselines/NOTICE_4_RCM_Sec73_DRC01.baseline.md
           + .metadata.json (source filename, extraction/output char counts,
           provider, model, prompt version, timestamp). Not edited.
           (3) Created modules/domain_models.py — dataclasses/enums only, stdlib
           only, independently importable, no business logic/LLM/Streamlit, NOT
           wired into the app. 11 concepts (Case, Proceeding, Document, Fact,
           Evidence, Issue, Deadline, Workflow, LegalReference, Draft,
           ValidationResult) + FactStatus enum (exactly the five spec statuses)
           + EvidenceStatus enum. Import + construction test passed.
           (4) Created tests/run_regression.py — stdlib only; discovers the four
           NOTICE_*.pdf fixtures, runs the existing explain_notice pipeline,
           saves outputs to tests/outputs/, compares vs tests/baselines/ via
           structural checks (8 section titles, ≥5000 chars, baseline status-label
           coverage — never raw text equality). First run: NOTICE_4 PASS,
           NOTICE_1–3 BASELINE_MISSING, 0 FAIL/EXECUTION_ERROR, exit 0.
           (5) Streamlit verified: my instance started on port 8502 (health ok;
           port 8501 is held by an older server from a previous session — old
           server should be stopped eventually). Instance stopped after check.
           (6) git status: only untracked new files = modules/domain_models.py
           and tests/; git diff on all tracked files EMPTY (app.py, existing
           modules, prompt, PDFs all byte-identical to baseline). .env NOT
           tracked and correctly gitignored; secret scan of tracked text files
           found no key-like strings. docs/architecture/CURRENT_ARCHITECTURE_AUDIT.md
           is already inside the baseline commit.
Files    : NEW modules/domain_models.py, tests/run_regression.py,
           tests/baselines/NOTICE_4_RCM_Sec73_DRC01.baseline.md,
           tests/baselines/NOTICE_4_RCM_Sec73_DRC01.metadata.json,
           tests/outputs/NOTICE_1–4 *.analysis.md (generated). PROJECT_MEMORY.md
           (this update). NO existing file modified, nothing committed.
Errors   : none. (Known harmless NOTE-003 SDK advisory re: automatic function
           calling printed during Gemini calls — ignore.)
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #12 — ARCHITECTURE AUDIT (READ-ONLY) — 18:20]
Task     : Read ARCHITECTURE_SPEC_V1.md, IMPLEMENTATION_PLAN, AGENTS.md, PROJECT_MEMORY;
           audit the current codebase (12 areas) WITHOUT modifying any source code,
           prompts, or adding features. Create docs/architecture/CURRENT_ARCHITECTURE_AUDIT.md
           with sections A–J; assess domain-concept equivalence; compare against the four
           fixtures; give recommended first step + files touched + files untouched + rollback.
Did      : Re-verified all 4 code files, requirements.txt, .env keys, prompt structure.
           Key findings: (1) NO git repo — rollback today is manual backups only; (2) NO
           tests exist; (3) no persistence/data models anywhere; (4) NOTICE_4 has never
           been run through the pipeline (baseline missing); (5) runtime LLM is Google
           Gemini (gemini-3.6-flash) — there is NO DeepSeek invocation in app code;
           "DeepSeek V4 Pro" in the spec = the Claude Code build loop (this session), so
           spec Layer J wording vs runtime is an open question to settle with Dina;
           (6) prompt rules are the only enforcement of all 8 invariants (no code-level
           validation); (7) mega-prompt OUTPUT QUALITY RULES are numbered 1–7, 11, 12, 8,
           9, 10 (non-sequential by design). Wrote the full audit to
           docs/architecture/CURRENT_ARCHITECTURE_AUDIT.md: A current system, B target,
           C gap analysis, D reusable components, E prompt→code extraction targets,
           F risks R1–R9, G migration order (Step 0 preconditions → Steps 1–10),
           H file-by-file plan, I what stays unchanged, J what must not be done yet,
           K fixture break-point analysis (NOTICE_3 MOV-09 form-selection = highest risk;
           NOTICE_1 ITC-vs-general classification; NOTICE_2 S.74 demotion + validator
           calibration; NOTICE_4 unknown baseline + notice-cited notification vs verified
           authority). Recommended first step: ADDITIVE ONLY — modules/domain_models.py
           (typed dataclasses/enums mirroring spec §3 incl. the five Fact statuses) +
           tests/run_regression.py (stdlib-only, no new pip deps per AGENTS.md); no
           existing file modified; rollback = delete both new files. Later phases need
           backups/git init before touching existing files.
Files    : docs/architecture/CURRENT_ARCHITECTURE_AUDIT.md (new). PROJECT_MEMORY.md
           (this update). NO code, prompt, fixture, .env, or requirements change.
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #11 — REWRITE PROMPT v3.3 — 17:41]
Task     : Modify prompts/notice_prompt.txt only — add three rules to SECTION 7 after
           the unsupported-factual-premise rules: strict source discipline for draft
           factual assertions, no advocacy-driven fact creation, source-confirmed
           terminology. Run on NOTICE_3, inspect draft reply, verify, update memory.
Did      : Added the three rules verbatim to SECTION 7 (strict source discipline —
           facts must be notice-confirmed / source-confirmed / [CA TO CONFIRM], never
           auto-upgraded to "valid"/"genuine"/"bona fide"; no advocacy-driven fact
           creation — WRONG/RIGHT e-way-bill example; source-confirmed terminology —
           preserve notice wording). No other rules changed, no other file touched.
           Re-ran pipeline on NOTICE_3_EWayBill_Sec129_DRC01.pdf: SUCCESS True, 2,511
           raw chars, 14,648-char explanation, all 8 sections present. Verified draft
           reply: uses "The notice refers to Tax Invoice No. RJT/2026-27/0891 dated
           19-08-2026…" (no "valid"/"genuine" upgrade); E-Way Bill non-generation
           reason is [CA TO CONFIRM] (not assumed); invoice-accompanied-goods is
           [CA TO CONFIRM]; no "no intent to evade" / "tax liability fully recorded"
           as established fact. All v3.2 protections intact (submission framing, status
           labels, service-date discipline — correctly shows the notice's own "on or
           before 27-08-2026" as [ALLEGED BY DEPARTMENT] + [CANNOT BE CONFIRMED
           WITHOUT SERVICE DATE], evidence gaps, [CA LEGAL RESEARCH REQUIRED]).
           RESIDUAL (minor, not fixed): §B.6 still concludes "the transaction
           represents a bona fide commercial transaction" — it IS hedged ("Subject to
           verification of these records… it is submitted that…") but names the term;
           §6/§3 also introduce statutory detail not in the notice (Section 126,
           "2021 amendments to Section 129 effective 01-01-2022", §73 penalty
           mechanics) — pre-existing pattern, out of scope for this run.
Files    : prompts/notice_prompt.txt (SECTION 7 — three rules added). No other file changed.
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #10 — REWRITE PROMPT v3.2 — 17:16]
Task     : Modify prompts/notice_prompt.txt only — in SECTION 7 add two rules after
           "Address every material section/rule cited in the notice.": legal
           conclusions framed as submissions; unsupported factual premises conditional
           or [CA TO CONFIRM]. Run on NOTICE_2, verify, update memory.
Did      : Added the two rules verbatim to SECTION 7 (legal-conclusion framing with
           "It is submitted that…"/"Without prejudice…" examples + WRONG/RIGHT pairs;
           conditional-factual-premise rule). No other rules changed, no other file
           touched. Re-ran the pipeline on NOTICE_2_Fraud_Sec74_DRC01.pdf: SUCCESS
           True, 3,007 raw chars, 18,528-char explanation, all 8 sections present.
           Verified: §C.2 no longer says "Section 74 is inapplicable" (now "the
           extended period… may not be invocable" / "penalty… is unsustainable" under
           an "It is respectfully submitted that" wrapper); §C.3 no longer asserts
           "there is no underlying tax evasion" (replaced by conditional "interest is
           consequential to a sustainable principal demand" + submission); §C.10 uses
           the exact prompt template "Without prejudice, and subject to verification
           of the underlying records, [CA TO CONFIRM…] it is submitted that the
           ingredients alleged under Section 74 are not established."; unsupported
           premises conditional/[CA TO CONFIRM]. All v3.1 protections intact
           (status labels, service-date discipline, evidence gaps, [CA LEGAL RESEARCH
           REQUIRED], no fabricated citations). RESIDUAL (minor, not fixed): §C.2 uses
           "is unsustainable" rather than the prompt's softer "may not be sustainable";
           §3 Penalty still introduces Section 73 penalty mechanics (10%/₹10,000) not
           in the notice (pre-existing, out of scope for this run).
Files    : prompts/notice_prompt.txt (SECTION 7 — two rules added). No other file changed.
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #9 — REWRITE PROMPT v3.1 — 17:08]
Task     : Modify prompts/notice_prompt.txt only — add Output Quality Rule 11 (label
           derived/calculated figures) and Rule 12 (ban unverified legal citations).
           Run pipeline on NOTICE_2_Fraud_Sec74_DRC01.pdf, verify A-G, update memory.
Did      : Added Rule 11 and Rule 12 immediately after Rule 7 in the OUTPUT QUALITY
           RULES section, exactly per spec. Rule 11: any computed/derived figure must
           be labelled [INFERRED — calculated from notice figures: X − Y = Z];
           [ALLEGED BY DEPARTMENT] only for figures the department actually states.
           Rule 12: never invent unverified circulars / notifications / GST Council
           decisions / CBIC instructions / case citations; unverified authority ->
           [CA LEGAL RESEARCH REQUIRED...]. All other v3 rules left unchanged. No
           other source file touched.
           Ran the full pipeline on NOTICE_2_Fraud_Sec74_DRC01.pdf (S.74(1) fraud/
           suppression): SUCCESS True, 3,007 raw chars, 17,149-char explanation, all 8
           sections present. Verified: (A) all fraud/suppression allegations carry
           [ALLEGED BY DEPARTMENT]; (D) derived 18% tax rate correctly labelled
           [INFERRED — calculated from notice figures: (7,56,000/42,00,000)×100=18%];
           (E) zero fabricated circular/notification/case citations. RESIDUAL OVERREACH
           (flagged, NOT fixed — task said do not rewrite v3): Draft Reply §C.2
           concludes "Section 74 is inapplicable... penalty cannot be legally
           sustained" and §C.3 asserts "there is no underlying tax evasion" as though
           established, instead of a conditional/[CA TO CONFIRM] submission. Minor:
           §3 Penalty introduces Section 73 penalty mechanics (10%/₹10,000) not in the
           notice; "Explanation 2 to Section 74" vs notice's "Explanation to Section 74".
Files    : prompts/notice_prompt.txt (added Rules 11 & 12 only). No other file changed.
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #8 — REWRITE PROMPT v3 — 16:52]
Task     : Rewrite prompts/notice_prompt.txt only, with the source-grounded fact-
           discipline template (allegation-vs-fact, service-date handling, evidence
           gaps, legal uncertainty, no fabricated case law, CA verification). Then run
           the pipeline on NOTICE_1_ITC_Mismatch_DRC01.pdf, compare, update memory.
Did      : Replaced the entire notice_prompt.txt with the 8-section evidence-disciplined
           template (Notice Facts / Department's Allegations / Issue & Computation
           Review / Urgency-Procedural Risk / Evidence Gaps / Legal Defences / Draft
           Reply / Client Message) + {today} + {notice_text}. Status labels
           [CONFIRMED]/[ALLEGED BY DEPARTMENT]/[NOT AVAILABLE]/[REQUIRES
           VERIFICATION]/[INFERRED]; "Financial Year / Tax Period" (not Assessment
           Year); service-date discipline (no deadline computed without service date);
           [CA TO CONFIRM] placeholders; no case law / no "penalty is nil" /
           no "taxpayer is entitled to" guarantees. No other source file touched.
           Ran the full pipeline on the REAL notice NOTICE_1_ITC_Mismatch_DRC01.pdf
           (now present in data/sample_notices/): SUCCESS True, 2,771 raw chars,
           19,875-char Gemini explanation, all 8 sections present. Verified the four
           objectives hold: (1) excess ITC kept as
           [ALLEGED BY DEPARTMENT] not fact; (2) no invented taxpayer facts (all
           [CA TO CONFIRM]); (3) defences marked "Cannot assess yet" / [CA LEGAL
           RESEARCH REQUIRED]; (4) service-based 21-day deadline correctly NOT computed
           (service date absent → [CANNOT BE CONFIRMED WITHOUT SERVICE DATE]).
Files    : prompts/notice_prompt.txt (full rewrite). run_output.txt (new, temp).
           No other files changed.
Errors   : none. (One pre-existing SDK advisory line re: automatic function calling —
           harmless, already known as NOTE-003.)
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #7 — REWRITE PROMPT — 11:12]
Task     : Rewrite prompts/notice_prompt.txt only, with a 6-section GST advocate
           template; then run the pipeline on NOTICE_1_ITC_Mismatch_DRC01.pdf.
Did      : Replaced the entire notice_prompt.txt with the new 6-section template
           (Notice Summary / Key Details / Required Action / Urgency / Draft Reply
           Letter / Client Communication), {today} deadline-passed rule, and detailed
           GST legal-submission instructions (S.16(2)(aa), R.36(4), S.50 interest,
           S.73/74 penalty, ITC reconciliation table, CA-ACTION-REQUIRED note).
           No other source file touched. Ran the full pipeline: SUCCESS True, 11,562
           raw chars, all 6 sections present in the Gemini response.
           NOTE: data/sample_notices/NOTICE_1_ITC_Mismatch_DRC01.pdf does NOT exist
           (glob + grep confirm zero matches — only test_sample.pdf and
           test_sample_multipage.pdf are present). Ran on test_sample_multipage.pdf
           (IRS Publication 1) as a substitute; model correctly flagged it as a US
           IRS doc, not a GST notice, while still producing the full 6-section
           GST-style reply.
Files    : prompts/notice_prompt.txt (full rewrite). No other files changed.
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #6 — RUN THE APP — 09:58]
Task     : Find and run the Streamlit app correctly; report the exact working command.
Did      : `where python` -> C:\Users\dines\AppData\Local\Programs\Python\Python312\
           python.exe (Python 3.12). `where py` -> NOT found (py launcher not
           installed). `where streamlit` -> Scripts\streamlit.exe exists, but the
           bare `streamlit run app.py` fails (Scripts folder not reliably on PATH).
           Confirmed `python -m streamlit --version` -> 1.62.0. Started
           `python -m streamlit run app.py --server.headless true` in background:
           Uvicorn up on :::8501, Local URL http://localhost:8501. Polled: root=200,
           /_stcore/health=200 ("ok"). No startup traceback (the lone
           ConnectionResetError WinError 10054 is my polling socket closing — benign).
Files    : No source files changed. PROJECT_MEMORY.md updated (new KNOWN GOTCHAS).
Errors   : none.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #5 — DATE + SINGLE-SCENARIO — 09:44]
Task     : Two changes only: (1) stamp today's date into the notice prompt; (2)
           replace the multi-scenario block with a single-scenario rule + add a
           deadline-passed line at the top of the template.
Did      : FIX 1 — added `from datetime import date` to notice_explainer.py; inside
           explain_notice() added `today = date.today().strftime("%d-%B-%Y")` before
           build_notice_prompt() and called build_notice_prompt(text, today). In
           llm_client.py changed the signature to build_notice_prompt(notice_text,
           today) and the return to .replace("{notice_text}", ...).replace("{today}",
           today), plus docstring. FIX 2 — in prompts/notice_prompt.txt added the
           "Today's date is {today}… ⚠️ DEADLINE PASSED…" instruction before section 1,
           and added the single-scenario instruction. NOTE: the "Scenario A/B/C"
           block the task referenced did NOT exist in the template (grep found zero
           matches), so the single-scenario rule was ADDED, not a replace.
           Tested: deterministic build_notice_prompt test — {today} -> 26-August-2026,
           no literal {today} left, both instructions present. Full pipeline on
           test_sample_multipage.pdf: success True, 11,562 raw chars, 3,515-char
           Gemini explanation, no error.
Files    : modules/notice_explainer.py, modules/llm_client.py,
           prompts/notice_prompt.txt. No other files touched.
Errors   : none in code. One console UnicodeEncodeError (cp1252) printing the prompt
           with the ⚠️ emoji — that is ERR-001, harmless; reran with
           PYTHONIOENCODING=utf-8.
Attempts : 1
Fix      : n/a (UnicodeEncodeError avoided via PYTHONIOENCODING=utf-8, not a code fix)
Status   : DONE

[PROMPT #4 — RESUME — 17:38]
Task     : Resume — verify files, fix API failure, run the app
Did      : Checked all source files (app.py, pdf_reader.py, llm_client.py,
           notice_explainer.py) — all present and complete from last session,
           nothing missing. Ran the IRS test: call_gemini() returned
           "Error: 404 ... gemini-2.5-flash is no longer available to new users".
           Key authenticated fine (402 was gone) — the MODEL NAME was the blocker.
           Listed models via client.models.list(), tested candidates, and the
           error's suggested gemini-3.6-flash (+ 3.7-flash) both returned "OK".
           Changed GEMINI_MODEL to gemini-3.6-flash in .env and updated the
           fallback default in llm_client.py. Re-ran IRS test: 3,904-char clean
           response, no error prefix.
           Started `streamlit run app.py`: server up on localhost:8501, HTTP 200,
           /_stcore/health -> "ok", no startup traceback.
Files    : .env (GEMINI_MODEL changed), modules/llm_client.py (default model
           string changed). No other source files touched.
Errors   : gemini-2.5-flash returns HTTP 404 for this free-tier key (model
           discontinued for new users) — NOT the 402 balance issue.
Attempts : 2 model tests (one timed out on a hung call, killed it and reran
           individually with flush).
Fix      : Use gemini-3.6-flash (the model the 404 error itself recommended).
Status   : DONE

[PROMPT #3 — TASK 2 — 15:57]
Task     : Create app.py (Streamlit UI, zero logic)
Did      : Wrote app.py exactly per spec. All logic delegated to modules — app.py
           only calls explain_notice() and renders the dict. Success path: success
           banner + st.markdown(explanation) + expander with raw_text[:2000] in
           st.text(). Failure path: st.error(result["error"]). Footer caption
           "Powered by Gemini AI".
Files    : app.py (new)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #3 — TASK 1 — 15:57]
Task     : Create modules/notice_explainer.py — glue between pdf_reader and llm_client
Did      : Wrote explain_notice(pdf_bytes) -> dict with exactly one public function.
           Calls extract_text() (catches RuntimeError), returns the scanned-PDF
           dict when text is empty/whitespace, else build_notice_prompt() +
           call_gemini(). call_gemini already returns "Error: ..." strings, so
           a Gemini failure is detected and mapped to success False with raw_text
           preserved (so the UI could later offer a fallback). Full docstring
           covers args, returns, and every key.
Files    : modules/notice_explainer.py (new)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #3 — TASK 0 — 15:56]
Task     : Migrate google-generativeai -> google-genai (deprecated -> supported SDK)
Did      : Step 1 — pip install google-genai -> 2.19.0 installed.
           Step 2 — requirements.txt: replaced google-generativeai with google-genai.
           Step 3 — Rewrote modules/llm_client.py to the new SDK: from google import
           genai, genai.Client(api_key=...), client.models.generate_content(
           model=..., contents=...). Verified the live signature via inspect before
           writing. All docstrings, retry logic, error handling, and template loading
           kept identical. Only the SDK call lines changed.
           Step 4 — Re-ran IRS PDF test: 5,425-char clean response, starts with
           "Here's an analysis...", no Error prefix, no deprecation warning.
           Step 5 — pip uninstall google-generativeai -y -> 0.8.6 removed.
Files    : modules/llm_client.py (rewritten), requirements.txt (1 line changed)
Errors   : none. One harmless SDK advisory printed on the new SDK ("direct AFC in
           Models.generate_content not recommended") — irrelevant, we don't use
           function calling; plain text prompt, call succeeds.
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #2 — TASK 4 — 14:47]
Task     : Test llm_client.py end-to-end using the IRS Publication 1 text
Did      : Ran the full pipeline: extract_text(IRS PDF) -> build_notice_prompt()
           -> call_gemini(). Prompt built 12,900 chars (placeholder replaced).
           Live Gemini call returned 4,507 chars — all 5 sections present plus a
           formal draft reply with the exact [PLACEHOLDERS]. Model correctly
           identified the doc as a U.S. IRS publication, NOT an Indian notice,
           and said so plainly — proves the template steers it well.
Files    : No source files changed. llm_client.py worked first try, unmodified.
Errors   : none (one FutureWarning from google.generativeai — deprecation notice,
           non-fatal, see NOTE-001 below)
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #2 — TASK 3 — 14:46]
Task     : Create modules/llm_client.py following the Gemini pattern in AGENTS.md
Did      : Wrote the module. load_dotenv() + genai.configure() run once at module
           level before building the model. Public API: call_gemini(prompt)->str
           and build_notice_prompt(notice_text)->str. Template path resolved from
           __file__ (not CWD) so imports work from anywhere. API call is wrapped
           in try/except returning "Error: ..." strings; empty response.text
           retries once after 2 seconds. Both functions have docstrings.
Files    : modules/llm_client.py (new)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #2 — TASK 2 — 14:45]
Task     : Create prompts/notice_prompt.txt with the exact analysis template
Did      : Wrote the template verbatim as specified — system role, 5 numbered
           sections (Notice Summary, Key Details, Required Action, Urgency,
           Draft Reply Letter), and a single {notice_text} placeholder between
           the NOTICE TEXT marker lines.
Files    : prompts/notice_prompt.txt (new)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #2 — TASK 1 — 14:45]
Task     : Install dependencies (pip install -r requirements.txt), report fresh vs
           already-present
Did      : Ran python -m pip install -r requirements.txt. Fresh installs: streamlit
           1.62.0, google-generativeai 0.8.6 (+ transitive deps). Already present:
           pymupdf 1.28.0, python-dotenv 1.2.2. Two downloads hit read timeouts and
           pip resumed/retried them automatically — install completed clean.
Files    : No source files touched. Environment changed (site-packages).
Errors   : none (two transient download ReadTimeoutError warnings, pip self-healed)
Attempts : 1 (pip's own retry handled the timeouts)
Fix      : n/a
Status   : DONE

[PROMPT #1 — TASK 4 — 14:13]
Task     : Download a small PDF from the internet and prove extract_text() works
Did      : Downloaded via urllib, saved into data/sample_notices/, ran extract_text()
           on the raw bytes (same path Streamlit will use), printed first 500 chars.
           Test 1 — W3C dummy.pdf: returned str, 15 chars ("Dummy PDF file").
           Too short to actually prove anything, so ran a second, harder test.
           Test 2 — IRS Publication 1 (324 KB, 2 pages): returned str, 11,562 chars,
           both pages joined in order, first 500 chars clean and readable.
           Error path — passed b"this is definitely not a pdf": raised RuntimeError
           "Could not read this PDF: Failed to open stream" as designed.
Files    : data/sample_notices/test_sample.pdf (new)
           data/sample_notices/test_sample_multipage.pdf (new)
           No source files changed — pdf_reader.py worked first try, unmodified.
Errors   : 1. First download URL (africau.edu/images/default/sample.pdf) returned
           HTTP 404 — that widely-quoted test URL is dead.
           2. Console printed "America?s" instead of "America's", which looked like
           a text-extraction bug.
Attempts : Download: 2 URLs tried, 2nd worked. Apostrophe: 1 check to diagnose.
Fix      : 1. Kept a fallback list of URLs and used the W3C/IRS ones instead.
           2. NOT a bug. Dumped the codepoints: the extracted char is U+2019, the
           correct curly apostrophe. Windows console stdout is cp1252 and cannot
           display it, so it prints "?". The string in memory is correct and
           Streamlit will render it fine. Do not "fix" this.
Status   : DONE

[PROMPT #1 — TASK 3 — 14:09]
Task     : Build modules/pdf_reader.py following the PyMuPDF pattern in AGENTS.md
Did      : Wrote extract_text(pdf_bytes: bytes) -> str exactly on the AGENTS.md
           pattern (fitz.open with stream=, join page.get_text(), close). Added
           try/except that re-raises as RuntimeError with a user-safe message, and
           a finally block so the doc is closed even when extraction fails.
           Full docstring covers Args / Returns / Raises.
           Also verified the local toolchain: Python 3.12.9, PyMuPDF 1.28.0 already
           installed — no pip install needed for testing.
Files    : modules/pdf_reader.py (new)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #1 — TASK 2 — 14:06]
Task     : Create requirements.txt, .gitignore, .env, modules/__init__.py
Did      : Wrote all four files with the exact contents Dina specified. .env holds
           placeholder values only — no real API key was written.
Files    : requirements.txt (streamlit, pymupdf, google-generativeai, python-dotenv)
           .gitignore (.env, __pycache__/, *.pyc, .streamlit/secrets.toml)
           .env (GEMINI_API_KEY=paste_your_key_here, GEMINI_MODEL=gemini-2.5-flash)
           modules/__init__.py (empty, makes modules/ a package)
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

[PROMPT #1 — TASK 1 — 14:05]
Task     : Create folder structure — modules/, prompts/, data/sample_notices/
Did      : Created all three folders inside the project root via New-Item -Force
Files    : No files touched. Folders created: modules/, prompts/, data/sample_notices/
Errors   : none
Attempts : 1
Fix      : n/a
Status   : DONE

---

## ERROR REGISTRY
> Errors that were hit and solved — so no agent repeats them

**ERR-003 — RESOLVED 2026-08-25 — DeepSeek API balance depleted (not a Gemini or code issue)**
Symptom : The earlier run surfaced a HTTP 402 payment-required error. Per Dina this
          was the DeepSeek API balance being depleted, not a Gemini or code problem.
          Balance was topped up.
Note    : On resuming, the Gemini key authenticated fine — the 402 did not recur.
          A DIFFERENT blocker surfaced instead: the model ID gemini-2.5-flash now
          returns HTTP 404 "no longer available to new users". That is NOTE-004,
          not this error.

**NOTE-004 — gemini-2.5-flash discontinued for new keys; switched to gemini-3.6-flash**
Symptom : generate_content(model="gemini-2.5-flash") -> 404 "This model
          models/gemini-2.5-flash is no longer available to new users."
Cause   : Google has cut new/free-tier access to gemini-2.5-flash.
Fix     : GEMINI_MODEL set to gemini-3.6-flash (the ID the 404 suggested).
          gemini-3.7-flash also works. AGENTS.md's pinned "gemini-2.5-flash" is
          now STALE — Dina owns AGENTS.md, so it was not edited; flag for her.

**ERR-001 — "America?s" in extracted text is NOT an extraction bug**
Symptom : Printing extracted text in a Windows terminal shows `?` where curly
          quotes, en-dashes, ₹ etc. should be.
Cause   : Windows console stdout encoding is cp1252, which cannot represent those
          characters. PyMuPDF returned the correct U+2019 — verified by codepoint.
Fix     : Nothing to fix in pdf_reader.py. If a future agent needs clean console
          output for debugging, set PYTHONIOENCODING=utf-8 for that run only.
          Never add encode/decode calls to pdf_reader.py to chase this.

**NOTE-001 — RESOLVED on 2026-08-23 — migrated to google-genai 2.19.0**
google-generativeai was deprecated/EOL. Dina authorized the migration. The old
package is uninstalled, llm_client.py now uses `from google import genai` +
`genai.Client(api_key=...)`, and the pipeline re-tested clean (5,425 chars).
AGENTS.md's "QUICK REFERENCE — Gemini" code block is now STALE (still shows the
old `google.generativeai` pattern). It was not edited — Dina owns AGENTS.md.
New correct pattern is captured in modules/llm_client.py and NOTE-003.

**NOTE-003 — New Google GenAI SDK pattern (as of google-genai 2.19.0)**
```python
from google import genai
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    contents=prompt,
)
result = response.text
```
One quirk: the SDK prints an advisory about "automatic function calling" when
using Models.generate_content directly. Harmless for us (plain text, no tools) —
do not chase it.

**ERR-002 — https://www.africau.edu/images/default/sample.pdf is dead (HTTP 404)**
Cause   : Commonly quoted "test PDF" URL, no longer hosted.
Fix     : Use https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf
          (tiny) or https://www.irs.gov/pub/irs-pdf/p1.pdf (2 pages, text-heavy).
          Both confirmed live on 2026-08-23.

---

## KNOWN GOTCHAS
> Hard-won environment quirks — never forget these

**Run the app:** `python -m streamlit run app.py`
- NOT `streamlit run app.py` — the Python `Scripts` folder is not reliably on PATH,
  so the bare `streamlit` command can fail to launch.
- NOT `py -m streamlit run app.py` — the `py` launcher is NOT installed on this
  machine (`where py` -> "Could not find files").
- `python` IS on PATH (C:\Users\dines\AppData\Local\Programs\Python\Python312\
  python.exe), so `python -m streamlit run app.py` is the reliable command.
- Verified 2026-08-26: server up on localhost:8501, HTTP 200, /_stcore/health -> "ok".

---

## DECISIONS MADE
| Decision | Reason |
|---|---|
| Streamlit not FastAPI | Fastest UI, free hosting, no HTML needed |
| Gemini not DeepSeek | Free tier, data on Google servers, Indian language support |
| PyMuPDF not pdfplumber | Faster, handles more PDF types |
| Windows native not WSL | No Linux-specific deps needed for this stack |
| Text extraction not Vision | 95% of CA notices are digital PDFs with text layer |
| data/sample_notices/ added | Holds test PDFs so extraction can be verified without real client notices |
| gemini-2.5-flash → gemini-3.6-flash | Old model ID 404s for new free-tier keys; API error recommended 3.6-flash |
| Prompt v3 — source-grounded fact discipline, allegation-vs-fact separation, service-date handling, evidence gaps, legal uncertainty, no fabricated case law, CA verification required | Eliminates hallucinated taxpayer facts, wrongly computed service-based deadlines, "Assessment Year" misuse, and overstated legal conclusions in AI-generated notices |
| Prompt v3.1 — derived-figure labelling and verified-legal-citation discipline added; unverified circulars, notifications, CBIC instructions, GST Council decisions and case citations prohibited | Stops the model presenting arithmetic-derived figures as department-stated, and invented/unverified circulars, notifications, and case law as authority |
| Prompt v3.2 — draft reply legal conclusions must be framed as submissions/conditional positions; unsupported factual premises must be conditional or marked [CA TO CONFIRM] | Stops the draft reply asserting "Section 74 is inapplicable" / "there is no underlying tax evasion" as established facts instead of as submissions or conditional/[CA TO CONFIRM] positions |
| Prompt v3.3 — strict source discipline inside draft replies; invoice references cannot be upgraded to valid/genuine facts; advocacy cannot create factual premises; unsupported taxpayer facts must remain [CA TO CONFIRM] or conditional | Stops the draft reply auto-upgrading "Tax Invoice No. X" to "valid/genuine tax invoice", inventing a reason for a missing E-Way Bill, or asserting "bona fide sale / no intent to evade / tax fully recorded" without a source |
| Architecture decision — current application continues using Gemini as runtime baseline. DeepSeek remains a future provider option and will not be introduced during Phase 1. | Freezes the runtime provider during the migration so any output change is attributable to architecture steps, not a provider switch; DeepSeek stays a Phase 2+ option |

---

## FEATURES DONE
- [x] Folder structure
- [x] PDF text extraction
- [x] Gemini API call
- [x] Notice explanation in UI
- [x] Draft reply generation
- [ ] Streamlit Cloud deploy
