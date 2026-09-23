"""Tests for the secret-free analysis-model configuration readiness seam."""

import unittest
from unittest.mock import patch

import modules.llm_client as llm_client


class LlmRuntimeConfigurationTests(unittest.TestCase):
    def test_ready_requires_at_least_one_configured_router_slot(self):
        with (
            patch.object(llm_client._router, "slots", [object()]),
            patch.object(llm_client, "_model_name", "gemini-test-model"),
        ):
            self.assertTrue(llm_client.llm_runtime_configuration_ready())

    def test_no_configured_slot_is_not_ready(self):
        with (
            patch.object(llm_client._router, "slots", []),
            patch.object(llm_client, "_model_name", "gemini-test-model"),
        ):
            self.assertFalse(llm_client.llm_runtime_configuration_ready())

    def test_blank_model_name_is_not_ready(self):
        with (
            patch.object(llm_client._router, "slots", [object()]),
            patch.object(llm_client, "_model_name", "   "),
        ):
            self.assertFalse(llm_client.llm_runtime_configuration_ready())

    def test_readiness_check_does_not_call_provider_executor(self):
        executor = llm_client._router.executor
        with (
            patch.object(llm_client._router, "slots", [object()]),
            patch.object(llm_client, "_model_name", "gemini-test-model"),
            patch.object(llm_client._router, "executor") as executor_mock,
        ):
            self.assertTrue(llm_client.llm_runtime_configuration_ready())
            executor_mock.assert_not_called()
        self.assertIs(llm_client._router.executor, executor)


if __name__ == "__main__":
    unittest.main()
