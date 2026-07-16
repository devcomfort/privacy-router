"""Unit tests for the opt-in placeholder repair subagent."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agents import PlaceholderRepairer, placeholder_repair_enabled


class TestPlaceholderRepairer:
    def test_accepts_only_a_registered_placeholder(self):
        repairer = PlaceholderRepairer(model="openrouter/test", max_attempts=3)

        with patch(
            "agents.router.placeholder_repair.call_llm_structured",
            return_value=SimpleNamespace(placeholder="PHONE#abc12345"),
        ) as call:
            result = repairer.repair_sync(
                observed="PHONE#deadbeef",
                allowed=["PHONE#abc12345"],
                masked_messages=[{"role": "user", "content": "Call PHONE#abc12345"}],
                masked_output="Draft for PHONE#deadbeef",
            )

        assert result == "PHONE#abc12345"
        assert call.call_count == 1
        prompt = str(call.call_args.kwargs["messages"])
        assert "PHONE#abc12345" in prompt
        assert "PHONE#deadbeef" in prompt

    def test_retries_invalid_answer_until_registered_answer(self):
        repairer = PlaceholderRepairer(model="openrouter/test", max_attempts=3)

        with patch(
            "agents.router.placeholder_repair.call_llm_structured",
            side_effect=[
                SimpleNamespace(placeholder="PHONE#not-registered"),
                SimpleNamespace(placeholder="PHONE#abc12345"),
            ],
        ) as call:
            result = repairer.repair_sync(
                observed="PHONE#deadbeef",
                allowed=["PHONE#abc12345"],
                masked_messages=[],
                masked_output="PHONE#deadbeef",
            )

        assert result == "PHONE#abc12345"
        assert call.call_count == 2
        second_prompt = str(call.call_args_list[1].kwargs["messages"])
        assert "not registered" in second_prompt

    def test_returns_none_after_three_failed_attempts(self):
        repairer = PlaceholderRepairer(model="openrouter/test", max_attempts=3)

        with patch(
            "agents.router.placeholder_repair.call_llm_structured",
            return_value=SimpleNamespace(placeholder=None),
        ) as call:
            result = repairer.repair_sync(
                observed="PHONE#deadbeef",
                allowed=["PHONE#abc12345"],
                masked_messages=[],
                masked_output="PHONE#deadbeef",
            )

        assert result is None
        assert call.call_count == 3

    def test_forwards_local_api_base_to_llm(self):
        repairer = PlaceholderRepairer(
            model="openai/local-model",
            api_base="http://127.0.0.1:8001/v1",
        )

        with patch(
            "agents.router.placeholder_repair.call_llm_structured",
            return_value=SimpleNamespace(placeholder="PHONE#abc12345"),
        ) as call:
            result = repairer.repair_sync(
                observed="PHONE#deadbeef",
                allowed=["PHONE#abc12345"],
                masked_messages=[],
                masked_output="PHONE#deadbeef",
            )

        assert result == "PHONE#abc12345"
        assert call.call_args.kwargs["model"] == "openai/local-model"
        assert call.call_args.kwargs["api_base"] == "http://127.0.0.1:8001/v1"


class TestPlaceholderRepairFeatureFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR",
            raising=False,
        )
        assert placeholder_repair_enabled() is False

    def test_accepts_explicit_true_value(self, monkeypatch):
        monkeypatch.setenv(
            "PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR",
            "true",
        )
        assert placeholder_repair_enabled() is True
