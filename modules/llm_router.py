"""Provider/key router for LLM calls (Architecture Phase 1.6).

This module owns exactly one job: deciding which provider key slot serves the
next request, and what happens when a request fails.

It knows nothing about any provider SDK. A provider adapter (Gemini's lives in
modules/llm_client.py) hands the router an executor — a callable that turns
(slot, prompt) into model text, raising ProviderError with a category when it
fails. The router's only vocabulary is the error category:

    QUOTA_RATE_LIMIT  429 — temporary (quota exhausted or rate limited):
                        cool the key down, rotate to the next eligible key.
    TRANSIENT_SERVICE 5xx/408 — provider temporarily unavailable: bounded
                        retries on the same key, then cool + rotate.
    INVALID_AUTH      401/403 — bad credentials: disable the key for this
                        process, rotate immediately.
    INVALID_REQUEST   other 4xx — our request is wrong: DO NOT rotate,
                        surface the error as-is.
    SAFETY_BLOCKED    content-policy rejection: DO NOT rotate, surface it.
    EMPTY_RESPONSE    model returned nothing useful: DO NOT rotate.
    UNKNOWN           unrecognized failure: DO NOT rotate, surface it.

Rotation is always bounded: every rotatable failure either cools a key down
(with a timestamp) or disables it, so a single request can never spin through
the same keys more than once.

State is deliberately in-memory only (no persistence, no background
scheduler, no key creation). Cooldowns are conservative: an exhausted key is
not hammered again within the cooldown window.

Secrets: a KeySlot holds the key value because the provider adapter needs it
to talk to the API, but the value is excluded from repr() and is never logged
or embedded in error messages. Error categories carry the failure category,
not the provider's exception message, into rotation decisions.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("llm_router")

# Conservative in-memory cooldowns and retry bounds, in seconds. Deliberately
# plain constants — this phase does not need a config system.
QUOTA_COOLDOWN_SECONDS = 30
TRANSIENT_COOLDOWN_SECONDS = 10
MAX_TRANSIENT_RETRIES_PER_KEY = 2
TRANSIENT_RETRY_DELAY_SECONDS = 1

# Discovery scans GEMINI_API_KEY_1 .. GEMINI_API_KEY_99. No gap-based
# stopping — a typo in _2 must not silently hide _3 and beyond.
MAX_SLOT_INDEX = 99


class ErrorCategory(str, Enum):
    QUOTA_RATE_LIMIT = "quota_rate_limit"
    TRANSIENT_SERVICE = "transient_service"
    INVALID_AUTH = "invalid_auth"
    INVALID_REQUEST = "invalid_request"
    SAFETY_BLOCKED = "safety_blocked"
    EMPTY_RESPONSE = "empty_response"
    UNKNOWN = "unknown"


# Categories that must never trigger key rotation — the error is the request's
# or the application's fault, not the key's.
NON_ROTATING_CATEGORIES = frozenset(
    {
        ErrorCategory.INVALID_REQUEST,
        ErrorCategory.SAFETY_BLOCKED,
        ErrorCategory.EMPTY_RESPONSE,
        ErrorCategory.UNKNOWN,
    }
)


class ProviderError(Exception):
    """A categorized provider failure. message must never contain a secret."""

    def __init__(self, category: ErrorCategory, message: str):
        super().__init__(message)
        self.category = ErrorCategory(category)
        self.message = message


class PoolExhaustedError(Exception):
    """No eligible key remains: everything is cooling down or disabled."""

    def __init__(self, label: str, env_var_example: str, total_slots: int,
                 failures: list):
        self.label = label
        self.total_slots = total_slots
        self.failures = failures  # list of (slot_id, ErrorCategory) — no messages
        if total_slots == 0:
            super().__init__(
                f"{label} API key not configured. "
                f"Set {env_var_example} and restart the app."
            )
        else:
            detail = "; ".join(
                f"{slot_id} ({category.value})" for slot_id, category in failures
            )
            super().__init__(
                f"{label} key pool exhausted — all {total_slots} configured key "
                f"slot(s) are cooling down or unusable for this run. "
                f"Failures: {detail}. Retry shortly or check the key configuration."
            )


@dataclass
class KeySlot:
    """One configured credential slot inside a provider's key pool.

    provider          e.g. "google"
    slot_id           e.g. "gemini_02" — safe to log
    api_key           the credential value — NEVER logged, never in repr
    configured        True when a usable credential was discovered
    available         False while the slot is in cooldown or disabled
    cooldown_until    time.monotonic() timestamp; 0 means no cooldown
    last_error_category  category of the most recent failure (or None)
    failure_count     failures since the last success on this slot
    disabled          True when INVALID_AUTH made it unusable for this process
    """

    provider: str
    slot_id: str
    api_key: str = field(repr=False)
    configured: bool = True
    available: bool = True
    cooldown_until: float = 0.0
    last_error_category: Optional[str] = None
    failure_count: int = 0
    disabled: bool = False


def discover_slots(provider: str, slot_prefix: str, env_prefix: str,
                   environ: Optional[dict] = None) -> list:
    """Discover configured key slots from environment variables.

    Reads the legacy single-key variable <env_prefix> (e.g. GEMINI_API_KEY)
    plus a numbered pool <env_prefix>_1, <env_prefix>_2, ... in ascending
    order. Empty values are skipped, and duplicate values are collapsed (a
    numbered variable holding the same value as the legacy one is the same
    account and must not be counted twice).

    Args:
        provider: provider identifier stored on each slot (e.g. "google").
        slot_prefix: human-safe slot-id prefix (e.g. "gemini" -> "gemini_01").
        env_prefix: environment variable prefix for the credential pool.
        environ: mapping to read (defaults to os.environ) — tests pass dicts.

    Returns:
        A list of KeySlots in preference order, or [] when nothing is set.
        Slot ids are numbered gemini_01..gemini_99 and never contain the
        variable name's value.
    """
    environ = os.environ if environ is None else environ
    seen_values: set = set()
    slots: list = []

    def add(env_name: str) -> None:
        value = (environ.get(env_name) or "").strip()
        if not value or value in seen_values:
            return
        seen_values.add(value)
        slots.append(
            KeySlot(
                provider=provider,
                slot_id=f"{slot_prefix}_{len(slots) + 1:02d}",
                api_key=value,
            )
        )

    add(env_prefix)  # legacy single-key variable, backward compatible
    for n in range(1, MAX_SLOT_INDEX + 1):
        add(f"{env_prefix}_{n}")
    return slots


Executor = Callable[[KeySlot, str], str]


class LLMRouter:
    """Routes one LLM request across a provider's key pool.

    The executor must raise ProviderError with a category on failure; the
    router never sees provider-specific exceptions. Logging is INFO-level and
    secret-free: provider, model, slot id, attempt number, request id, and
    result category only.
    """

    def __init__(
        self,
        provider: str,
        label: str,
        env_var_example: str,
        model: str,
        slots: list,
        executor: Executor,
        quota_cooldown_seconds: float = QUOTA_COOLDOWN_SECONDS,
        transient_cooldown_seconds: float = TRANSIENT_COOLDOWN_SECONDS,
        max_transient_retries: int = MAX_TRANSIENT_RETRIES_PER_KEY,
        transient_retry_delay: float = TRANSIENT_RETRY_DELAY_SECONDS,
    ):
        self.provider = provider
        self.label = label
        self.env_var_example = env_var_example
        self.model = model
        self.slots = list(slots)
        self.executor = executor
        self.quota_cooldown_seconds = quota_cooldown_seconds
        self.transient_cooldown_seconds = transient_cooldown_seconds
        self.max_transient_retries = max_transient_retries
        self.transient_retry_delay = transient_retry_delay
        self._request_counter = 0
        self._lock = threading.Lock()

    def call(self, prompt: str) -> str:
        """Send prompt through the key pool and return the model text.

        Raises:
            ProviderError: for non-rotating categories (the error is the
                request's or application's fault, not the key's).
            PoolExhaustedError: when no eligible slot remains.
        """
        request_id = self._next_request_id()
        failures: list = []
        attempt = 0
        while True:
            slot = self._next_eligible_slot()
            if slot is None:
                raise PoolExhaustedError(
                    self.label, self.env_var_example, len(self.slots), failures
                )
            attempt += 1
            retries = 0
            while True:
                try:
                    text = self.executor(slot, prompt)
                except ProviderError as exc:
                    self._record_failure(slot, exc.category)
                    logger.info(
                        "llm_request request_id=%s provider=%s model=%s "
                        "key_slot=%s attempt=%s result=failed:%s",
                        request_id, self.provider, self.model, slot.slot_id,
                        attempt, exc.category.value,
                    )
                    if exc.category in NON_ROTATING_CATEGORIES:
                        raise
                    if (
                        exc.category is ErrorCategory.TRANSIENT_SERVICE
                        and retries < self.max_transient_retries
                    ):
                        retries += 1
                        time.sleep(self.transient_retry_delay)
                        continue
                    self._exclude_after_failure(slot, exc.category)
                    failures.append((slot.slot_id, exc.category))
                    break
                else:
                    self._record_success(slot)
                    logger.info(
                        "llm_request request_id=%s provider=%s model=%s "
                        "key_slot=%s attempt=%s result=success",
                        request_id, self.provider, self.model, slot.slot_id, attempt,
                    )
                    return text

    def _next_request_id(self) -> str:
        with self._lock:
            self._request_counter += 1
            return f"req_{self._request_counter:05d}"

    def _next_eligible_slot(self) -> Optional[KeySlot]:
        now = time.monotonic()
        with self._lock:
            for slot in self.slots:
                if slot.disabled:
                    continue
                if not slot.available:
                    if slot.cooldown_until <= now:
                        slot.available = True  # cooldown expired
                    else:
                        continue
                return slot
        return None

    def _record_failure(self, slot: KeySlot, category: ErrorCategory) -> None:
        with self._lock:
            slot.failure_count += 1
            slot.last_error_category = category.value

    def _record_success(self, slot: KeySlot) -> None:
        with self._lock:
            slot.failure_count = 0
            slot.last_error_category = None
            slot.available = True
            slot.cooldown_until = 0.0

    def _exclude_after_failure(self, slot: KeySlot, category: ErrorCategory) -> None:
        now = time.monotonic()
        with self._lock:
            slot.available = False
            if category is ErrorCategory.QUOTA_RATE_LIMIT:
                slot.cooldown_until = now + self.quota_cooldown_seconds
            elif category is ErrorCategory.TRANSIENT_SERVICE:
                slot.cooldown_until = now + self.transient_cooldown_seconds
            elif category is ErrorCategory.INVALID_AUTH:
                slot.disabled = True
