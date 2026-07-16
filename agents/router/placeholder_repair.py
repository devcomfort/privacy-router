"""Opt-in subagent for repairing malformed masked placeholders."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from agents.llm import call_llm_structured, load_prompt, render_prompt

from .schemas import PlaceholderRepairDecision

_FEATURE_FLAG = "PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_PROMPT_PATH = Path(__file__).with_name("placeholder_repair.prompt")


def placeholder_repair_enabled() -> bool:
    """Return whether the beta placeholder repair path is explicitly enabled."""
    return os.getenv(_FEATURE_FLAG, "").strip().lower() in _TRUE_VALUES


class PlaceholderRepairer:
    """Map one malformed token to an existing masking-contract key.

    The repairer receives masked context only. Its response is accepted only
    when it exactly equals one of the contract's registered placeholders.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._model = model
        self._api_base = api_base
        self._max_attempts = max_attempts
        self._prompt = load_prompt(str(_PROMPT_PATH))

    async def repair(
        self,
        *,
        observed: str,
        allowed: list[str],
        masked_messages: list[dict[str, object]],
        masked_output: str,
    ) -> str | None:
        """Asynchronously repair one token without blocking the event loop."""
        return await asyncio.to_thread(
            self.repair_sync,
            observed=observed,
            allowed=allowed,
            masked_messages=masked_messages,
            masked_output=masked_output,
        )

    def repair_sync(
        self,
        *,
        observed: str,
        allowed: list[str],
        masked_messages: list[dict[str, object]],
        masked_output: str,
    ) -> str | None:
        """Try up to ``max_attempts`` and accept only a registered key."""
        registered = list(dict.fromkeys(allowed))
        if not registered:
            return None

        allowed_set = set(registered)
        feedback = "No previous attempt."
        for _ in range(self._max_attempts):
            prompt = render_prompt(
                self._prompt["template"],
                allowed_placeholders_json=json.dumps(registered, ensure_ascii=False),
                masked_messages_json=json.dumps(masked_messages, ensure_ascii=False),
                masked_output_json=json.dumps(masked_output, ensure_ascii=False),
                observed_json=json.dumps(observed, ensure_ascii=False),
                feedback=feedback,
            )
            try:
                decision = call_llm_structured(
                    messages=[{"role": "user", "content": prompt}],
                    response_model=PlaceholderRepairDecision,
                    model=self._model,
                    api_base=self._api_base,
                    max_tokens=int(self._prompt["config"].get("max_tokens", 256)),
                )
            except Exception:
                feedback = (
                    "The previous attempt failed to produce valid structured "
                    "output. Return one registered placeholder or null."
                )
                continue

            candidate: Any = decision.placeholder
            if candidate in allowed_set:
                return str(candidate)
            if candidate is None:
                feedback = (
                    "The previous answer was null. Re-check the complete masked "
                    "context; return null again only if the mapping is ambiguous."
                )
            else:
                feedback = f"{candidate!r} is not registered. Return an exact item from the registered list or null."

        return None
