"""Shared LLM calling interface using litellm + instructor.

Model candidates:
  Small (<8B):
    ibm-granite/granite-4.1-8b          ($0.05)  한국어
    mistralai/ministral-3b-2512        ($0.10)  현행
  Middle (8-30B):
    qwen/qwen3.6-35b-a3b               ($0.14)  MoE, 한국어
    qwen/qwen3.5-9b                     ($0.04)  9B
    deepseek/deepseek-v4-flash          ($0.10)  아시아언어
    google/gemma-4-26b-a4b-it           ($0.06)  무료티어
  Large (>30B, Native JSON):
    anthropic/claude-haiku-latest        ($1.00)  Structured output
    google/gemini-3.1-flash-lite        ($0.25)  Judge 추천
    google/gemini-3.5-flash             ($1.50)  최신
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any, TypeVar

import instructor  # noqa: E402  -- must follow warnings / env setup
import litellm
from dotenv import load_dotenv
from dotpromptz import Dotprompt
from pydantic import BaseModel

# Suppress noisy warnings before they happen
warnings.filterwarnings("ignore", message="Field name.*shadows an attribute")
os.environ["LITELLM_LOG"] = "ERROR"
litellm.suppress_debug_info = True

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

T = TypeVar("T", bound=BaseModel)


def load_prompt(prompt_path: str) -> dict[str, Any]:
    """Load and parse a .prompt file using dotpromptz."""
    d = Dotprompt()
    with open(prompt_path, "r") as f:
        content = f.read()
    parsed = d.parse(content)

    return {
        "model": parsed.raw.get("model", "openrouter/mistralai/ministral-3b-2512"),
        "config": parsed.raw.get("config", {}),
        "template": parsed.template,
    }


def render_prompt(template: str, **kwargs: Any) -> str:
    """Render a prompt template with variables."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def call_llm(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    api_key: str | None = None,
    api_base: str | None = None,
) -> str:
    """Call LLM via litellm (unstructured text output)."""
    model = model or os.getenv("LLM_MODEL", "openrouter/mistralai/ministral-3b-2512")
    api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
    )
    if api_base:
        kwargs["api_base"] = api_base

    response = litellm.completion(**kwargs)

    return response.choices[0].message.content.strip()


def call_llm_structured(
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str | None = None,
    max_tokens: int = 4096,
    api_key: str | None = None,
    api_base: str | None = None,
) -> T:
    """Call LLM via litellm + instructor (structured Pydantic output).

    For Gemini models, falls back to raw text + parsing if structured mode fails.

    Examples
    --------
    >>> from pydantic import BaseModel
    >>> class Answer(BaseModel):
    ...     result: str
    >>> response = call_llm_structured([{"role": "user", "content": "Say hello"}], Answer)
    >>> isinstance(response, Answer)
    True
    """
    model = model or os.getenv("LLM_MODEL", "openrouter/mistralai/ministral-3b-2512")
    api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    # For local/openai-compatible endpoints, use a dummy key if none provided
    if not api_key and api_base:
        api_key = "dummy"

    is_gemini = "gemini" in model.lower()
    is_exaone = "exaone" in model.lower()

    # Gemini and EXAONE use raw JSON parsing (no instructor/JSON mode)
    if is_gemini or is_exaone:
        return _call_raw_json(messages, response_model, model, max_tokens, api_key, api_base)
    # Local models (vLLM, Ollama) need JSON mode — they don't support tool_choice
    if api_base:
        client = instructor.from_litellm(litellm.completion, mode=instructor.Mode.JSON)
    else:
        client = instructor.from_litellm(litellm.completion)

    kwargs: dict = dict(
        model=model,
        response_model=response_model,
        messages=messages,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
    )
    if api_base:
        kwargs["api_base"] = api_base

    return client.chat.completions.create(**kwargs)


def _call_raw_json(
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str,
    max_tokens: int,
    api_key: str,
    api_base: str | None = None,
) -> T:
    """Call LLM and manually parse JSON response into Pydantic model."""
    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
    )
    if api_base:
        kwargs["api_base"] = api_base

    # EXAONE needs response_format to produce JSON
    if "exaone" in model.lower():
        kwargs["response_format"] = {"type": "json_object"}

    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content.strip()

    # Extract JSON from markdown blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    # Strip Qwen3 thinking tags if present
    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()

    # If content doesn't start with {, try to extract JSON from reasoning text
    if not content.lstrip().startswith("{"):
        # Find the last JSON object in the text
        json_matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL))
        if json_matches:
            content = json_matches[-1].group(0)

    data = json.loads(content)

    # Handle array response: wrap in dict if model expects a wrapper
    if isinstance(data, list):
        # Try to find a list-typed field in the model
        for field_name, field_info in response_model.model_fields.items():
            if str(field_info.annotation).startswith("list"):
                data = {field_name: data}
                break

    return response_model.model_validate(data)
