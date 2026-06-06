"""Shared LLM calling interface using litellm + instructor.

Model candidates:
  Edge (<8B):
    ibm-granite/granite-4.1-8b          ($0.05)  한국어
    mistralai/ministral-3b-2512        ($0.10)  현행
  Performant:
    qwen/qwen3.6-35b-a3b               ($0.14)  MoE, 한국어
    qwen/qwen3.5-9b                     ($0.04)  9B
    deepseek/deepseek-v4-flash          ($0.10)  아시아언어
    google/gemma-4-26b-a4b-it           ($0.06)  무료티어
  Frontier (Native JSON):
    anthropic/claude-haiku-latest        ($1.00)  Structured output
    google/gemini-3.1-flash-lite        ($0.25)  Judge 추천
    google/gemini-3.5-flash             ($1.50)  최신
"""

from __future__ import annotations

import json
import os
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

    is_gemini = "gemini" in model.lower()

    if is_gemini:
        return _call_raw_json(messages, response_model, model, max_tokens, api_key)

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


    client = instructor.from_litellm(litellm.completion)

    return client.chat.completions.create(
        model=model,
        response_model=response_model,
        messages=messages,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
    )


def _call_raw_json(
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str,
    max_tokens: int,
    api_key: str,
) -> T:
    """Call LLM and manually parse JSON response into Pydantic model."""
    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
    )
    content = response.choices[0].message.content.strip()

    # Extract JSON from markdown blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    data = json.loads(content)

    # Handle array response: wrap in dict if model expects a wrapper
    if isinstance(data, list):
        # Try to find a list-typed field in the model
        for field_name, field_info in response_model.model_fields.items():
            if str(field_info.annotation).startswith("list"):
                data = {field_name: data}
                break

    return response_model.model_validate(data)
