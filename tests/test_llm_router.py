"""Unit tests for modules/llm_router (Architecture Phase 1.6).

Standard library only — no pytest, no new dependencies, and no real Gemini
calls. The "provider" in every test is a fake executor function that
simulates the response/error behaviour described in
docs/architecture/LLM_ROUTING.md.

Every router under test is constructed with explicit slots and executor, so
these tests never read .env or real credentials. All key values used here are
obviously fake strings, and a dedicated test asserts key values never leak
into error messages or reprs.

Usage:
    python tests/test_llm_router.py
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.llm_router import (  # noqa: E402
    ErrorCategory,
    KeySlot,
    LLMRouter,
    PoolExhaustedError,
    ProviderError,
    discover_slots,
)

FAKE_KEY_1 = "fake-key-gemini-slot-1"
FAKE_KEY_2 = "fake-key-gemini-slot-2"


def make_slot(slot_id: str, key: str = FAKE_KEY_1, provider: str = "google") -> KeySlot:
    return KeySlot(provider=provider, slot_id=slot_id, api_key=key)


def make_router(slots, behaviors, **kwargs) -> tuple:
    """Build a router around a fake executor.

    behaviors maps slot_id -> callable() returning the model text; to fail,
    the callable raises ProviderError. Returns (router, call_counts) where
    call_counts counts executor invocations per slot_id.
    """
    call_counts = {slot.slot_id: 0 for slot in slots}

    def executor(slot, prompt):
        call_counts[slot.slot_id] += 1
        return behaviors[slot.slot_id]()

    defaults = dict(transient_retry_delay=0)  # keep the suite fast, no sleeps
    defaults.update(kwargs)
    router = LLMRouter(
        provider="google",
        label="Gemini",
        env_var_example="GEMINI_API_KEY",
        model="gemini-3.6-flash",
        slots=slots,
        executor=executor,
        **defaults,
    )
    return router, call_counts


class RouterBehaviorTests(unittest.TestCase):
    """Required scenarios 1-9 from the Phase 1.6 test plan."""

    def test_01_one_configured_key_success(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        router, calls = make_router([slot1], {"gemini_01": lambda: "analysis text"})
        self.assertEqual(router.call("prompt"), "analysis text")
        self.assertEqual(calls["gemini_01"], 1)
        self.assertEqual(slot1.failure_count, 0)
        self.assertTrue(slot1.available)
        self.assertFalse(slot1.disabled)
        self.assertIsNone(slot1.last_error_category)

    def test_02_quota_error_fails_over_to_next_key(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def quota():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "quota exhausted")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": quota, "gemini_02": lambda: "from key 2"}
        )
        self.assertEqual(router.call("prompt"), "from key 2")
        self.assertEqual(calls["gemini_01"], 1)
        self.assertEqual(calls["gemini_02"], 1)
        self.assertGreater(slot1.cooldown_until, 0)
        self.assertFalse(slot1.available)
        self.assertEqual(slot1.failure_count, 1)
        self.assertEqual(slot1.last_error_category, "quota_rate_limit")
        self.assertFalse(slot1.disabled)  # quota cools down, does not disable
        self.assertEqual(slot2.failure_count, 0)

    def test_03_rate_limit_fails_over_to_next_key(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def rate_limited():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "rate limit hit")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": rate_limited, "gemini_02": lambda: "ok"}
        )
        self.assertEqual(router.call("prompt"), "ok")
        self.assertEqual(slot1.last_error_category, "quota_rate_limit")
        self.assertGreater(slot1.cooldown_until, 0)
        self.assertTrue(slot2.available)

    def test_04_transient_503_bounded_retry_then_failover(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def always_503():
            raise ProviderError(ErrorCategory.TRANSIENT_SERVICE, "503 unavailable")

        # Two keys: 1 initial + 2 retries on slot1, then failover to slot2.
        router, calls = make_router(
            [slot1, slot2],
            {"gemini_01": always_503, "gemini_02": lambda: "recovered"},
            max_transient_retries=2,
        )
        self.assertEqual(router.call("prompt"), "recovered")
        self.assertEqual(calls["gemini_01"], 3)  # bounded: 1 + 2 retries
        self.assertEqual(calls["gemini_02"], 1)
        self.assertGreater(slot1.cooldown_until, 0)

        # One key that never recovers: retries stay bounded, then a clear
        # exhaustion error — never an infinite retry loop.
        lone = make_slot("gemini_01", key=FAKE_KEY_1)
        router2, calls2 = make_router([lone], {"gemini_01": always_503}, max_transient_retries=2)
        with self.assertRaises(PoolExhaustedError) as ctx:
            router2.call("prompt")
        self.assertEqual(calls2["gemini_01"], 3)
        self.assertIn("exhausted", str(ctx.exception))

    def test_05_invalid_key_disabled_next_key_used(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def bad_key():
            raise ProviderError(ErrorCategory.INVALID_AUTH, "401 invalid key")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": bad_key, "gemini_02": lambda: "from key 2"}
        )
        self.assertEqual(router.call("prompt"), "from key 2")
        self.assertTrue(slot1.disabled)  # unusable for the rest of this process
        self.assertEqual(slot1.last_error_category, "invalid_auth")

        # A second request skips the disabled slot entirely.
        self.assertEqual(router.call("prompt"), "from key 2")
        self.assertEqual(calls["gemini_01"], 1)  # never called again
        self.assertEqual(calls["gemini_02"], 2)

    def test_06_invalid_request_does_not_rotate(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def bad_request():
            raise ProviderError(ErrorCategory.INVALID_REQUEST, "400 bad prompt")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": bad_request, "gemini_02": lambda: "never"}
        )
        with self.assertRaises(ProviderError) as ctx:
            router.call("prompt")
        self.assertEqual(ctx.exception.category, ErrorCategory.INVALID_REQUEST)
        self.assertEqual(calls["gemini_02"], 0)  # no rotation
        self.assertTrue(slot1.available)  # no cooldown applied
        self.assertFalse(slot1.disabled)
        self.assertEqual(slot1.cooldown_until, 0)

    def test_07_safety_rejection_does_not_rotate(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def blocked():
            raise ProviderError(ErrorCategory.SAFETY_BLOCKED, "content policy block")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": blocked, "gemini_02": lambda: "never"}
        )
        with self.assertRaises(ProviderError) as ctx:
            router.call("prompt")
        self.assertEqual(ctx.exception.category, ErrorCategory.SAFETY_BLOCKED)
        self.assertIn("content policy block", str(ctx.exception))  # original error surfaced
        self.assertEqual(calls["gemini_02"], 0)  # no rotation
        self.assertTrue(slot1.available)
        self.assertFalse(slot1.disabled)

    def test_08_all_keys_exhausted_clear_failure(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def quota():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "quota exhausted")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": quota, "gemini_02": quota}
        )
        with self.assertRaises(PoolExhaustedError) as ctx:
            router.call("prompt")
        message = str(ctx.exception)
        self.assertIn("exhausted", message)
        self.assertIn("gemini_01", message)
        self.assertIn("gemini_02", message)
        self.assertIn("quota_rate_limit", message)
        self.assertEqual(calls["gemini_01"], 1)
        self.assertEqual(calls["gemini_02"], 1)

    def test_09a_cooldown_prevents_immediately_reusing_exhausted_key(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def quota():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "quota exhausted")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": quota, "gemini_02": quota}
        )
        with self.assertRaises(PoolExhaustedError):
            router.call("prompt")
        self.assertEqual(sum(calls.values()), 2)

        # Immediately after: both keys still cooling down, so the router must
        # not touch the provider at all.
        with self.assertRaises(PoolExhaustedError):
            router.call("prompt")
        self.assertEqual(sum(calls.values()), 2)  # no new executor calls

    def test_09b_cooldown_expiry_re_enables_key_and_success_resets_state(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        behaviors = {"gemini_01": None}
        calls = {"gemini_01": 0}

        def executor(slot, prompt):
            calls[slot.slot_id] += 1
            behavior = behaviors[slot.slot_id]
            return behavior()

        def quota():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "quota exhausted")

        behaviors["gemini_01"] = quota
        router = LLMRouter(
            provider="google",
            label="Gemini",
            env_var_example="GEMINI_API_KEY",
            model="gemini-3.6-flash",
            slots=[slot1],
            executor=executor,
        )
        with self.assertRaises(PoolExhaustedError):
            router.call("prompt")
        self.assertEqual(slot1.failure_count, 1)

        # Simulate the cooldown window passing.
        slot1.cooldown_until = 0.0
        slot1.available = False  # lazy re-enable exercised by the router
        behaviors["gemini_01"] = lambda: "back online"
        self.assertEqual(router.call("prompt"), "back online")
        self.assertTrue(slot1.available)
        self.assertEqual(slot1.failure_count, 0)
        self.assertIsNone(slot1.last_error_category)


class RouterConfigTests(unittest.TestCase):
    """Required scenarios 10-11: configuration and env discovery."""

    def test_10_no_credentials_clear_config_error(self):
        executor_called = []

        def executor(slot, prompt):
            executor_called.append(slot)
            return "never"

        router = LLMRouter(
            provider="google",
            label="Gemini",
            env_var_example="GEMINI_API_KEY",
            model="gemini-3.6-flash",
            slots=[],
            executor=executor,
        )
        with self.assertRaises(PoolExhaustedError) as ctx:
            router.call("prompt")
        message = str(ctx.exception)
        self.assertIn("not configured", message)
        self.assertIn("GEMINI_API_KEY", message)
        self.assertEqual(executor_called, [])  # provider never contacted

        # Discovery with an empty environment yields no slots.
        self.assertEqual(
            discover_slots(provider="google", slot_prefix="gemini", env_prefix="GEMINI_API_KEY", environ={}),
            [],
        )

    def test_11a_legacy_single_key_configuration_still_works(self):
        slots = discover_slots(
            provider="google",
            slot_prefix="gemini",
            env_prefix="GEMINI_API_KEY",
            environ={"GEMINI_API_KEY": "legacy-key-value"},
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].slot_id, "gemini_01")
        self.assertEqual(slots[0].provider, "google")
        self.assertEqual(slots[0].api_key, "legacy-key-value")

        router, calls = make_router(slots, {"gemini_01": lambda: "legacy works"})
        self.assertEqual(router.call("prompt"), "legacy works")
        self.assertEqual(calls["gemini_01"], 1)

    def test_11b_numbered_pool_discovered_in_order_with_dedup(self):
        slots = discover_slots(
            provider="google",
            slot_prefix="gemini",
            env_prefix="GEMINI_API_KEY",
            environ={
                "GEMINI_API_KEY_1": "key-a",
                "GEMINI_API_KEY_2": "key-b",
                "GEMINI_API_KEY_3": "key-c",
            },
        )
        self.assertEqual([s.slot_id for s in slots], ["gemini_01", "gemini_02", "gemini_03"])
        self.assertEqual([s.api_key for s in slots], ["key-a", "key-b", "key-c"])
        self.assertTrue(all(s.provider == "google" for s in slots))

        # Legacy + numbered holding the same value collapse to one slot;
        # empty/whitespace values are skipped.
        slots = discover_slots(
            provider="google",
            slot_prefix="gemini",
            env_prefix="GEMINI_API_KEY",
            environ={
                "GEMINI_API_KEY": "same-key",
                "GEMINI_API_KEY_1": "same-key",  # duplicate account — skipped
                "GEMINI_API_KEY_2": "",  # empty — skipped
                "GEMINI_API_KEY_3": "   ",  # whitespace — skipped
                "GEMINI_API_KEY_4": "other-key",
            },
        )
        self.assertEqual([s.slot_id for s in slots], ["gemini_01", "gemini_02"])
        self.assertEqual([s.api_key for s in slots], ["same-key", "other-key"])


class SecretHygieneTests(unittest.TestCase):
    """Required scenario 12: key values never appear in output."""

    def test_12_key_values_never_leak(self):
        secret = "SEKRIT-3f9a-not-a-real-key"
        slot1 = make_slot("gemini_01", key=secret)
        slot2 = make_slot("gemini_02", key="SEKRIT-8b2c-also-fake")

        def quota():
            raise ProviderError(ErrorCategory.QUOTA_RATE_LIMIT, "quota exhausted")

        router, _ = make_router(
            [slot1, slot2], {"gemini_01": quota, "gemini_02": quota}
        )
        with self.assertRaises(PoolExhaustedError) as ctx:
            router.call("prompt")

        message = str(ctx.exception)
        self.assertNotIn(secret, message)
        self.assertNotIn("SEKRIT-8b2c-also-fake", message)
        # repr must never contain the credential either.
        self.assertNotIn(secret, repr(slot1))
        self.assertNotIn(secret, repr(slot2))


class NoRotationTests(unittest.TestCase):
    """Extra: empty responses must not rotate keys either."""

    def test_empty_response_does_not_rotate(self):
        slot1 = make_slot("gemini_01", key=FAKE_KEY_1)
        slot2 = make_slot("gemini_02", key=FAKE_KEY_2)

        def empty():
            raise ProviderError(ErrorCategory.EMPTY_RESPONSE, "Gemini returned an empty response.")

        router, calls = make_router(
            [slot1, slot2], {"gemini_01": empty, "gemini_02": lambda: "never"}
        )
        with self.assertRaises(ProviderError):
            router.call("prompt")
        self.assertEqual(calls["gemini_02"], 0)  # no rotation
        self.assertTrue(slot1.available)


if __name__ == "__main__":
    unittest.main(verbosity=2)
