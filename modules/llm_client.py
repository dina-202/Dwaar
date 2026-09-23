"""Gemini client. This module has exactly one job: talk to Gemini.

It loads API keys from .env, configures the SDK lazily per key slot, and
exposes two functions — one to build a prompt from the template file, one to
send it to the model and get the text back.

Since Phase 1.6 the call path routes through modules/llm_router: a pool of
authorized Gemini keys (GEMINI_API_KEY, plus optionally GEMINI_API_KEY_1,
GEMINI_API_KEY_2, ...) is discovered at import time, and on quota/rate-limit,
transient-service, or invalid-credential failures the router cools down or
disables the failing slot and retries with the next eligible one. The legacy
single-key setup (GEMINI_API_KEY only) behaves exactly as before.

This module remains the only place that knows the Google SDK — it translates
SDK exceptions into router error categories. The router itself is
provider-agnostic, which is the seam a future provider adapter plugs into.
"""

import os
import time
from pathlib import Path

from google import genai
from dotenv import load_dotenv

from modules.llm_router import (
    ErrorCategory,
    LLMRouter,
    PoolExhaustedError,
    ProviderError,
    discover_slots,
)

# Configure once at module level. Must run load_dotenv() BEFORE os.getenv()
# or the key comes back None.
load_dotenv()
_model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# The prompt template lives outside the code so Dina can edit it without
# touching Python. Resolve it relative to this file, not the CWD.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "notice_prompt.txt"

# One SDK client per key slot, created lazily on first use. genai.Client only
# stores configuration; the HTTP call happens per request.
_clients: dict = {}


def _client_for(slot) -> "genai.Client":
    client = _clients.get(slot.slot_id)
    if client is None:
        client = genai.Client(api_key=slot.api_key)
        _clients[slot.slot_id] = client
    return client


def _category_for_status(code: int) -> ErrorCategory:
    """Map an HTTP status code from the Google SDK to a router category."""
    if code == 429:
        return ErrorCategory.QUOTA_RATE_LIMIT
    if code in (401, 403):
        return ErrorCategory.INVALID_AUTH
    if code == 408:
        return ErrorCategory.TRANSIENT_SERVICE
    if 500 <= code <= 599:
        return ErrorCategory.TRANSIENT_SERVICE
    return ErrorCategory.INVALID_REQUEST  # any other 4xx: our request is wrong


def _generate_with_key(slot, prompt: str) -> str:
    """One attempt at a Gemini call on one key slot.

    Returns the model text, or raises ProviderError with a category the
    router understands. Keeps the pre-router retry behaviour: an empty
    response is retried once after 2 seconds. An explicit content-policy
    block (prompt_feedback.block_reason) is surfaced immediately — the router
    must not rotate keys for a safety rejection.
    """

    def one_try() -> str:
        response = _client_for(slot).models.generate_content(
            model=_model_name,
            contents=prompt,
        )
        block_reason = getattr(
            getattr(response, "prompt_feedback", None), "block_reason", None
        )
        if block_reason:
            raise ProviderError(
                ErrorCategory.SAFETY_BLOCKED,
                "Gemini blocked the response (content safety policy).",
            )
        return response.text or ""

    for attempt in range(2):
        try:
            text = one_try()
        except ProviderError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            category = (
                _category_for_status(code)
                if isinstance(code, int)
                else ErrorCategory.UNKNOWN
            )
            raise ProviderError(category, str(exc)) from exc
        if text.strip():
            return text
        if attempt == 0:
            time.sleep(2)
    raise ProviderError(ErrorCategory.EMPTY_RESPONSE, "Gemini returned an empty response.")


# The key pool is discovered from the environment at import time, exactly like
# the old single key was. Slots are read once; adding or removing
# GEMINI_API_KEY_N variables takes effect on the next app restart.
_router = LLMRouter(
    provider="google",
    label="Gemini",
    env_var_example=(
        "GEMINI_API_KEY (and optionally GEMINI_API_KEY_1, GEMINI_API_KEY_2, ...)"
    ),
    model=_model_name,
    slots=discover_slots(
        provider="google",
        slot_prefix="gemini",
        env_prefix="GEMINI_API_KEY",
    ),
    executor=_generate_with_key,
)


def llm_runtime_configuration_ready() -> bool:
    """Return whether the current analysis-model runtime is configured.

    This is intentionally configuration-only: it does not call the provider,
    consume quota, expose key counts, or validate network/provider health.
    The router already owns credential discovery, so readiness reuses that
    boundary instead of reading secret values elsewhere.
    """
    return bool(_router.slots) and bool(
        isinstance(_model_name, str) and _model_name.strip()
    )


def build_notice_prompt(notice_text: str, today: str) -> str:
    """
    Load the notice prompt template and inject the notice text into it.

    Args:
        notice_text: The extracted text of the notice, as returned by
            modules.pdf_reader.extract_text().
        today: Human-readable today's date string (e.g. "26-August-2026"),
            injected into the {today} placeholder in the template.

    Returns:
        The full prompt ready to send to Gemini. On failure (missing or
        unreadable template file) it returns a clean error string instead of
        raising, so the caller can show it directly in the UI.
    """
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return f"Could not load prompt template ({_PROMPT_PATH.name}): {e}"
    return template.replace("{notice_text}", notice_text).replace("{today}", today)


def call_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini and return the model's text response.

    The request is routed through the key pool (modules.llm_router): on
    quota/rate-limit, transient-service, or invalid-credential failures the
    router fails over to the next eligible configured key. The caller never
    sees an exception: any error is returned as a clean string prefixed with
    "Error". Errors that are the request's fault (invalid request, safety
    block, empty response) are surfaced unchanged without rotating keys.

    Args:
        prompt: The full prompt string, as built by build_notice_prompt().

    Returns:
        The model's text response, or an error string starting with "Error".
    """
    try:
        return _router.call(prompt)
    except ProviderError as exc:
        return f"Error: {exc.message}"
    except PoolExhaustedError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: {exc}"
