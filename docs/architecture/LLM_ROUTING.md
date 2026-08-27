# LLM ROUTING — Provider / API Key Resilience (Phase 1.6)

**Status:** Implemented 2026-08-27 (Architecture Phase 1.6)
**Companions:** `modules/llm_router.py` (router), `modules/llm_client.py` (Gemini adapter), `tests/test_llm_router.py` (unit tests)

This document describes the provider/key routing layer added to the existing
LLM client. The layer changes **only what happens when a request fails** — the
application's analysis behavior, prompt, model, and output format are
unchanged.

---

## A. Why the router exists

Before Phase 1.6, `modules/llm_client.py` held exactly one hardwired Gemini
API key read once at import. Any quota exhaustion (HTTP 429), rate limit,
provider outage (5xx), or invalid credential surfaced immediately as
`"Error: ..."` — there was no way to use a second authorized key even when one
was available.

The router adds normal provider failover / resilience behavior: a pool of
authorized keys, in-memory state per key, and rotation only for failures that
are about the key or the provider's availability — never for failures that are
about the request itself.

**Policy.** The key pool is only for API keys/accounts the project owner is
authorized to use. The router implements ordinary failover (rate limits,
temporary quota exhaustion, transient service errors, invalid credentials).
It deliberately does **not** circumvent provider-imposed quotas, account
restrictions, or usage limits, and it never cycles keys for permanent
application errors.

## B. Current provider

- **Provider:** Google Gemini
- **Model:** `gemini-3.6-flash` (from `GEMINI_MODEL`, default in
  `modules/llm_client.py`)
- **Prompt:** v3.3 (`prompts/notice_prompt.txt`) — untouched
- **SDK:** `google-genai` 2.19.0 (`from google import genai`)

Only Gemini is implemented. No DeepSeek or other provider exists yet.

## C. Key-slot configuration

Keys come from environment variables only (`.env` via `load_dotenv()`).

| Variable | Meaning |
|---|---|
| `GEMINI_API_KEY` | Legacy single key — still fully supported, slot `gemini_01` |
| `GEMINI_API_KEY_1` … `GEMINI_API_KEY_99` | Numbered key pool — each becomes a slot `gemini_02`, `gemini_03`, … |

Rules (implemented in `discover_slots()`):

- Discovery scans `GEMINI_API_KEY` first, then `GEMINI_API_KEY_1` … `_99` in
  ascending order. There is **no assumed maximum** (scanning is bounded at 99
  only as a sanity limit) and no gap-based stopping — a typo in `_2` does not
  hide `_3`.
- Empty/whitespace values are skipped.
- Duplicate values are collapsed — a numbered variable holding the same value
  as the legacy one is the same account and is not counted twice.
- Slot ids are safe to log: `gemini_01`, `gemini_02`, …
- Adding/removing slots is pure environment configuration — no Python source
  change. Slots are discovered once at import; restart the app after changing
  `.env`.

## D. Error categories

The router's only vocabulary (enum `ErrorCategory` in
`modules/llm_router.py`). The Gemini adapter maps SDK exceptions to these
categories; the router itself knows nothing about the Google SDK.

| Category | Trigger (Gemini) | Meaning |
|---|---|---|
| `quota_rate_limit` | HTTP 429 | Temporary — daily quota exhausted or rate limited |
| `transient_service` | HTTP 5xx, 408 | Provider temporarily unavailable |
| `invalid_auth` | HTTP 401, 403 | Credential rejected — key unusable for this process |
| `invalid_request` | other 4xx (e.g. 400, 404) | Our request is wrong (bad prompt, bad model id) |
| `safety_blocked` | `prompt_feedback.block_reason` set | Content-policy rejection |
| `empty_response` | model returned no text | Nothing useful produced |
| `unknown` | anything uncategorized | Unrecognized failure |

## E. Rotation rules

For one request, the router walks the pool in slot order:

| Category | Action |
|---|---|
| `quota_rate_limit` | Cool the key down (30 s), rotate to the next eligible key |
| `transient_service` | Retry the same key up to 2 more times (1 s apart), then cool it down (10 s) and rotate |
| `invalid_auth` | Disable the key for the current process, rotate immediately |
| `invalid_request` | **NO rotation** — surface the original error |
| `safety_blocked` | **NO rotation** — surface the original error |
| `empty_response` | **NO rotation** (retried once on the same key, pre-existing behavior) |
| `unknown` | **NO rotation** — surface the original error |

When every slot is cooling down or disabled, the router raises
`PoolExhaustedError`: *"Gemini key pool exhausted — all N configured key
slot(s) are cooling down or unusable for this run. Failures: <slot>: <category>,
…"* — a clear, secret-free message. With zero configured keys it reports
*"Gemini API key not configured…"* instead.

Rotation is always bounded: every rotatable failure cools or disables a slot,
so a single request can never spin through the same keys more than once, and
there is no infinite retry loop.

## F. Cooldown behavior

- In-memory only. No persistence, no background scheduler, no quota database,
  no automatic key creation.
- Quota/rate-limit cooldown: **30 s** (`QUOTA_COOLDOWN_SECONDS`).
- Transient-service cooldown: **10 s** (`TRANSIENT_COOLDOWN_SECONDS`).
- Retry bound: **2 retries per key** for transient errors
  (`MAX_TRANSIENT_RETRIES_PER_KEY`), 1 s apart (`TRANSIENT_RETRY_DELAY_SECONDS`).
- A key in cooldown is not touched again until its window passes; expiry is
  checked lazily on the next slot pick. Conservative by design — an exhausted
  key is not hammered.
- All constants live at the top of `modules/llm_router.py` (and are
  constructor-overridable for tests).

Per-slot state (`KeySlot`): provider, slot id, configured flag, available/
cooldown state, `cooldown_until` timestamp, last error category, failure
count, disabled flag. On success the transient failure state of the used slot
resets (failure count 0, error cleared).

## G. Secret-handling rules

- Credential values exist in memory only, inside `KeySlot.api_key`, which is
  `repr=False` — never in reprs or logs.
- Logs carry only safe metadata: `request_id`, `provider`, `model`,
  `key_slot`, `attempt`, `result`. Never the key value, authorization header,
  raw credential, or environment variable value.
- Error messages (including `PoolExhaustedError`) contain slot ids and
  categories only — not the provider's exception message.
- Keys are never written to logs, `PROJECT_MEMORY.md`, metadata files, test
  fixtures, Git, or the UI. Test 12 in `tests/test_llm_router.py` enforces the
  no-leak guarantee.

## H. Future provider extension point

`LLMRouter` is provider-agnostic: it consumes slots + an executor and speaks
only in error categories. Adding a provider later means:

1. a new adapter module (like `llm_client.py` for Gemini) that builds a
   per-key SDK client and maps that SDK's exceptions to `ErrorCategory`;
2. discovering its key pool with `discover_slots(provider=..., slot_prefix=...,
   env_prefix="<PROVIDER>_API_KEY")` — the same numbered-variable convention
   works unchanged.

No router change would be required. (Per the architecture decisions, DeepSeek
remains a future option and is not introduced in this phase.)

## I. What this phase deliberately does NOT implement

- No provider other than Gemini (no DeepSeek adapter yet).
- No persisted state: cooldowns and disabled flags live only for the current
  process and reset on restart.
- No background scheduler, quota database, or automatic key creation.
- No key *pooling* across accounts beyond ordinary failover — quotas are not
  circumvented, and permanent application errors never rotate keys.
- No change to the prompt, model, temperature/settings, output structure,
  Streamlit UI, or `notice_explainer` behavior. The only intended behavioral
  difference: when the current Gemini credential/request fails with an
  eligible transient/quota/authentication condition, the router can use
  another configured authorized key.

---

*End of Phase 1.6 routing documentation.*
