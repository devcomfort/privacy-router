"""LiteLLM과 instructor-py를 연결하는 공용 LLM 호출 클라이언트.

Extractor와 Critic은 이 모듈을 통해 모델을 호출합니다. LiteLLM이
프로바이더 전송을 담당하고, instructor-py가 구조화된 Pydantic 응답을
검증합니다. 일부 모델의 호환성 문제를 위한 JSON 폴백도 이 경계 안에서
처리합니다.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any

import instructor  # noqa: E402  -- must follow warnings / env setup
import litellm
from dotenv import load_dotenv
from dotpromptz import Dotprompt
from pydantic import BaseModel

from config import is_trusted_local_api_base, resolve_model_api_key

# Suppress noisy warnings before they happen
warnings.filterwarnings("ignore", message="Field name.*shadows an attribute")
os.environ["LITELLM_LOG"] = "ERROR"
litellm.suppress_debug_info = True

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_EXTERNAL_MODEL = "openrouter/google/gemma-4-26b-it"

def _build_metadata(component: str | None) -> dict[str, str] | None:
    """호출 컴포넌트 이름을 LiteLLM 메타데이터로 변환합니다."""
    return {"component": component} if component else None


def load_prompt(prompt_path: str) -> dict[str, Any]:
    """`.prompt` 파일을 읽어 모델, 호출 설정, 템플릿으로 분해합니다."""
    d = Dotprompt()
    with open(prompt_path) as f:
        content = f.read()
    parsed = d.parse(content)

    return {
        "model": parsed.raw.get("model", DEFAULT_EXTERNAL_MODEL),
        "config": parsed.raw.get("config", {}),
        "template": parsed.template,
    }


def render_prompt(template: str, **kwargs: Any) -> str:
    """템플릿의 `{{변수명}}` 자리를 전달받은 값으로 치환합니다."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def _resolve_api_key(model: str) -> str | None:
    """모델 식별자에 맞는 공급자 API 키를 환경 설정에서 조회합니다."""
    return resolve_model_api_key(model)


def _resolve_call_api_key(
    model: str,
    api_key: str | None,
    api_base: str | None,
) -> str | None:
    """단일 호출에 사용할 API 키를 결정합니다.

    명시적으로 전달된 키를 가장 먼저 사용합니다. 신뢰된 로컬 엔드포인트는
    외부 자격 증명을 필요로 하지 않으므로 호환성용 더미 키를 사용합니다.
    그 외의 경우 모델 공급자와 환경변수에서 키를 조회하며, 키를 찾지
    못하면 외부 호출을 시작하지 않고 ``ValueError``를 발생시킵니다.
    """
    if api_key:
        return api_key
    if is_trusted_local_api_base(api_base):
        return "dummy"
    resolved = _resolve_api_key(model) or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or None
    if not resolved:
        raise ValueError(
            f"API key is required for model '{model}'. "
            "Please pass 'api_key' explicitly or set the provider environment variable (e.g., OPENROUTER_API_KEY)."
        )
    return resolved

def call_llm(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    api_key: str | None = None,
    api_base: str | None = None,
    component: str = "generator",
) -> str:
    """LiteLLM을 통해 일반 텍스트 응답을 생성합니다.

    ``model``을 생략하면 ``LLM_MODEL`` 환경변수와 기본 외부 모델을
    사용합니다. ``api_base``가 있으면 해당 OpenAI 호환 엔드포인트로
    요청을 보냅니다.
    """
    model = model or os.getenv("LLM_MODEL", DEFAULT_EXTERNAL_MODEL)
    api_key = _resolve_call_api_key(model, api_key, api_base)

    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
        metadata=_build_metadata(component),
    )
    if api_base:
        kwargs["api_base"] = api_base

    response = litellm.completion(**kwargs)

    return response.choices[0].message.content.strip()


def call_llm_structured[T: BaseModel](
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str | None = None,
    max_tokens: int = 4096,
    api_key: str | None = None,
    api_base: str | None = None,
    component: str = "generator",
) -> T:
    """instructor-py를 통해 Pydantic 구조화 응답을 생성합니다.

    일반적인 모델은 ``instructor.from_litellm``이 응답을 검증합니다.
    Gemini와 EXAONE은 현재 엔드포인트 호환성 때문에 raw JSON을 받은 뒤
    동일한 Pydantic 모델로 직접 검증합니다.

    예시:

    ```python
    class Answer(BaseModel):
        result: str

    response = call_llm_structured(
        [{"role": "user", "content": "Say hello"}],
        Answer,
    )
    ```
    """
    model = model or os.getenv("LLM_MODEL", DEFAULT_EXTERNAL_MODEL)
    api_key = _resolve_call_api_key(model, api_key, api_base)

    is_gemini = "gemini" in model.lower()
    is_exaone = "exaone" in model.lower()

    # Gemini and EXAONE use raw JSON parsing (no instructor/JSON mode)
    if is_gemini or is_exaone:
        return _call_raw_json(
            messages,
            response_model,
            model,
            max_tokens,
            api_key,
            api_base,
            component,
        )
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
        metadata=_build_metadata(component),
    )
    if api_base:
        kwargs["api_base"] = api_base

    return client.chat.completions.create(**kwargs)


def _call_raw_json[T: BaseModel](
    messages: list[dict[str, str]],
    response_model: type[T],
    model: str,
    max_tokens: int,
    api_key: str,
    api_base: str | None = None,
    component: str = "generator",
) -> T:
    """모델 응답에서 JSON을 추출하고 Pydantic 모델로 검증합니다.

    마크다운 코드 펜스와 추론 태그를 제거하고, 응답이 목록이면
    대상 모델의 목록 필드로 감싼 뒤 검증합니다.
    """
    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=max_tokens,
        api_key=api_key if api_key else None,
        metadata=_build_metadata(component),
    )
    if api_base:
        kwargs["api_base"] = api_base

    # Force JSON output for all models
    kwargs["response_format"] = {"type": "json_object"}

    response = litellm.completion(**kwargs, timeout=60)
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
        json_matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL))
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
