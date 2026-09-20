# 채팅 메시지 스키마·변환 코드 조사 보고서

**조사 목적:** OpenAI SDK, Anthropic SDK(Claude), LiteLLM, LangChain이 채팅 히스토리를 어떤 자료 구조로 정의하고 JSON으로 내보내거나 다시 읽는지 확인한다.

**조사 기준 버전:** `openai 2.54.0`, `anthropic 1.4.0`, `langchain-core 1.6.2`, 저장소의 `litellm 1.99.0`.
**갱신 기록 (2026-09-08):** `uv` 격리 환경에서 각 라이브러리의 여러 버전, fake HTTP transport, Transformers chat template을 실측해 provider wire JSON과 모델 내부 template을 구분했다.

## 버전과 식별 방식

각 라이브러리의 메시지 타입에는 별도의 `schema_version` 필드가 없습니다. 따라서 캐시 유틸리티에서 라이브러리 버전을 곧바로 메시지 스키마 버전으로 사용하면 안 됩니다.

| 라이브러리 | 조사한 패키지 버전 | 외부 API/내부 식별 방식 | 메시지 스키마 버전 필드 |
|---|---:|---|---|
| OpenAI Python SDK | `2.54.0` | OpenAPI 생성 `TypedDict` union과 Chat Completions endpoint | 없음 |
| Anthropic Python SDK | `1.4.0` | `anthropic-version: 2023-06-01` API header와 generated `TypedDict` | 없음 |
| LiteLLM | `1.99.0` | OpenAI-compatible message dict와 provider별 변환 | 없음 |
| LangChain Core | `1.6.2` | `BaseMessage`의 `type` discriminator와 package serialization | 없음 |

캐시 유틸리티는 다음을 별도로 기록해야 합니다.

| 필드 | 타입 | 역할 | 예시 |
|---|---|---|---|
| `format` | `str` | native 입력 형식 | `"openai-chat"` |
| `adapter_version` | `str` | 우리 adapter가 해석하는 형식 버전 | `"openai-adapter-v1"` |
| `source_library_version` | `str \| None` | 진단·재현용 SDK 버전 | `"openai-2.54.0"` |
| `api_version` | `str \| None` | 공급자 API 버전 | `"anthropic-2023-06-01"` |

`adapter_version`이 hash 검증 기준입니다. SDK patch 버전이 바뀔 때마다 캐시를 무효화할 필요는 없고, 메시지 해석 결과가 바뀌는 adapter 변경 때만 올려야 합니다.

## 1. 핵심 결론

1. 네 생태계 모두 JSON-safe 자료로 바꾸는 방법은 있다.
2. OpenAI와 Anthropic의 **입력 메시지 타입은 주로 `TypedDict`**이므로 런타임에는 일반 Python `dict`다.
3. OpenAI와 Anthropic의 **응답 타입은 Pydantic 모델**이며 `model_dump()`, `model_dump_json()`, `to_dict()`를 제공한다.
4. LiteLLM의 요청은 OpenAI 호환 `dict`이고, 응답 `Message`는 Pydantic 계열 모델이다.
5. LangChain은 `BaseMessage` 객체를 사용하며 `messages_to_dict()`와 `messages_from_dict()`가 공식 왕복 경로다.
6. 어떤 라이브러리도 네 라이브러리의 히스토리를 하나의 공통 객체로 자동 통합하지 않는다.
7. 캐시 유틸리티는 SDK 객체를 직접 섞어 처리하지 말고, 선택된 SDK의 native 형식을 유지한 뒤 JSON-safe 값으로 추출해야 한다.

## 2. OpenAI Python SDK

### 2.1 메시지 union 정의

OpenAI SDK는 `ChatCompletionMessageParam`을 다음 메시지 타입의 union으로 정의한다.

```python
ChatCompletionMessageParam: TypeAlias = Union[
    ChatCompletionDeveloperMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionFunctionMessageParam,
]
```

출처: [`chat_completion_message_param.py`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_message_param.py)
버전별 generated type 표현은 동일하지 않다. 실측한 `openai 1.0.0`의 `ChatCompletionMessageParam`은 union이 아닌 하나의 `TypedDict` class이며 combined fields가 `content`, `function_call`, `name`, `role`이다. `2.54.0`은 위의 six-member union으로 생성된다. 두 버전 모두 단순 `{role, content}` 요청은 dict로 전송되지만, type-level JSON 계약은 바뀐 것이다. 상세 결과는 [`probe_openai_types.py`](../spikes/chat-format-versions/probes/probe_openai_types.py)다.

### 2.2 공통·주요 필드

| 메시지 타입 | 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|---|
| 모든 타입 | `role` | `Literal[...]` | 메시지 종류 | `"user"` |
| user | `content` | `str \| Iterable[ContentPart]` | 사용자 텍스트 또는 이미지·오디오 등 입력 | `"안녕하세요"` |
| user | `name` | `str` | 같은 role의 발화자를 구분하는 선택 필드 | `"홍길동"` |
| assistant | `content` | `str \| Iterable[TextPart \| RefusalPart] \| None` | 모델의 텍스트 출력 | `"처리했습니다"` |
| assistant | `tool_calls` | `Iterable[ToolCall]` | 모델이 호출한 도구 목록 | `[ {"id":"call_1", ...} ]` |
| assistant | `function_call` | `FunctionCall \| None` | 이전 함수 호출 형식. deprecated | `{"name":"lookup", ...}` |
| assistant | `refusal` | `str \| None` | 모델 거부 메시지 | `"요청을 처리할 수 없습니다."` |
| assistant | `audio` | `Audio \| None` | 이전 오디오 응답 정보 | `{"id":"audio_1"}` |
| tool | `content` | `str \| Iterable[TextPart]` | 도구 실행 결과 | `"맑음"` |
| tool | `tool_call_id` | `str` | 결과가 대응하는 도구 호출 ID | `"call_1"` |
| function | `name` | `str` | 이전 함수 이름 | `"lookup"` |
| function | `content` | `str` | 이전 함수 결과 | `"..."` |

대표 구현은 `TypedDict(total=False)`와 `Required[...]` 조합이다.

```python
class ChatCompletionUserMessageParam(TypedDict, total=False):
    content: Required[str | Iterable[ChatCompletionContentPartParam]]
    role: Required[Literal["user"]]
    name: str

class ChatCompletionToolMessageParam(TypedDict, total=False):
    content: Required[str | Iterable[ChatCompletionContentPartTextParam]]
    role: Required[Literal["tool"]]
    tool_call_id: Required[str]
```

출처: [`user message`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_user_message_param.py), [`tool message`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_tool_message_param.py), [`assistant message`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_assistant_message_param.py)

### 2.3 히스토리 입력과 metadata

```python
class CompletionCreateParamsBase(TypedDict, total=False):
    messages: Required[Iterable[ChatCompletionMessageParam]]
    model: Required[str | ChatModel]
    metadata: Metadata | None
    tools: Iterable[ChatCompletionToolUnionParam]
    tool_choice: ChatCompletionToolChoiceOptionParam
```

`metadata`는 일반적으로 **메시지 안의 필드가 아니라 요청 객체의 필드**다. SDK 문서상 최대 16개의 문자열 key-value를 API 객체에 붙이는 용도이며, 메시지별 자유 metadata 계약으로 정의되어 있지는 않다.

`TypedDict`는 런타임 검증 객체가 아니다. 호출자가 임의 key를 넣을 수는 있지만, 해당 key를 OpenAI API가 허용하거나 의미를 보존한다는 보장은 없다.

### 2.4 export와 import

입력 `ChatCompletionMessageParam`은 이미 dict이므로 별도 export 함수가 없다.

응답 모델은 Pydantic 계열의 다음 경로를 사용할 수 있다.

```python
response = client.chat.completions.create(...)
message = response.choices[0].message

payload = message.model_dump(mode="json")
text = message.model_dump_json()
restored = ChatCompletionMessage.model_validate(payload)
```

즉 OpenAI SDK는 **입력 history용 왕복 helper는 제공하지 않고**, 응답 모델의 Pydantic 변환 기능을 제공한다.

## 3. Anthropic Python SDK (Claude)

### 3.1 입력 메시지 정의

```python
class MessageParam(TypedDict, total=False):
    content: Required[
        str | Iterable[
            TextBlockParam
            | ImageBlockParam
            | DocumentBlockParam
            | ThinkingBlockParam
            | ToolUseBlockParam
            | ToolResultBlockParam
            | ContentBlock
        ]
    ]
    role: Required[Literal["user", "assistant", "system"]]
```

출처: [`message_param.py`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message_param.py)

### 3.2 메시지·요청 필드

| 위치 | 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|---|
| message | `role` | `Literal["user", "assistant"]` | 대화 발화자 | `"user"` |
| message | `content` | `str \| Iterable[ContentBlock]` | 텍스트 또는 block 배열 | `"안녕하세요"` |
| content block | `type` | `Literal[...]` | text, image, tool_use, tool_result 등 | `"text"` |
| tool_use block | `id` | `str` | 도구 호출 ID | `"toolu_1"` |
| tool_use block | `name` | `str` | 도구 이름 | `"lookup"` |
| tool_use block | `input` | `object` | 도구 입력 JSON | `{"city":"서울"}` |
| tool_result block | `tool_use_id` | `str` | 대응하는 도구 호출 ID | `"toolu_1"` |
| 요청 | `messages` | `Iterable[MessageParam]` | 순서가 있는 대화 메시지 | `[...]` |
| 요청 | `system` | `str \| Iterable[TextBlockParam]` | system prompt. 메시지 배열 밖 | `"도우미 역할"` |
| 요청 | `metadata` | `MetadataParam` | 요청에 붙이는 metadata | `{"user_id":"..."}` |
| 요청 | `tools` | `Iterable[ToolUnionParam]` | 도구 정의 목록 | `[ {...} ]` |
| 요청 | `tool_choice` | `ToolChoiceParam` | 도구 선택 정책 | `{"type":"auto"}` |

Anthropic의 요청 문서는 system prompt에 대해 **Messages API 입력 배열에는 system role을 사용하지 않고 top-level `system`을 사용한다**고 설명한다. 현재 생성된 `MessageParam` 타입 alias에 `system` role이 나타나는 것과 문서 설명 사이에 차이가 있으므로, 실제 요청 adapter는 endpoint 문서를 우선해야 한다.

출처: [`message_create_params.py`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message_create_params.py)

### 3.3 응답 모델

```python
class Message(BaseModel):
    id: str
    content: list[ContentBlock]
    model: Model
    role: Literal["assistant"]
    stop_reason: StopReason | None
    stop_sequence: str | None
    type: Literal["message"]
    usage: Usage
```

출처: [`message.py`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message.py)

### 3.4 export와 import

Anthropic SDK의 응답 `Message`는 OpenAI SDK와 비슷한 Pydantic 변환 기능을 가진다.

```python
response = client.messages.create(...)

payload = response.model_dump(mode="json")
text = response.model_dump_json()
restored = Message.model_validate(payload)

# API 이름과 None 포함 여부를 직접 통제할 수 있는 export
payload = response.to_dict(
    mode="json",
    use_api_names=True,
    exclude_unset=True,
    exclude_none=False,
)
```

입력 `MessageParam`에는 별도의 history export/import helper가 없다. 애플리케이션은 JSON dict 배열을 직접 보관한다.

## 4. LiteLLM

### 4.1 `Message` 응답 모델

현재 LiteLLM의 `litellm.types.utils.Message`는 다음과 같이 정의된다.

```python
class Message(SafeAttributeModel, OpenAIObject):
    content: str | None
    role: Literal["assistant", "user", "system", "tool", "function"]
    tool_calls: list[ChatCompletionMessageToolCall | ChatCompletionMessageCustomToolCall] | None
    function_call: FunctionCall | None
    audio: ChatCompletionAudioResponse | None = None
    images: list[ImageURLListItem] | None = None
    reasoning_content: str | None = None
    thinking_blocks: list[...] | None = None
    reasoning_items: list[...] | None = None
    provider_specific_fields: dict[str, Any] | None = None
    annotations: list[ChatCompletionAnnotation] | None = None
```

현재 모델 설정은 `extra="allow"`이며, provider-specific field나 추가 key를 보관할 수 있다.

출처: 설치된 `litellm/types/utils.py`의 `Message` 정의 및 [LiteLLM 입력 문서](https://docs.litellm.ai/docs/completion/input)

### 4.2 필드 의미

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `content` | `str \| None` | 메시지 텍스트 | `"안녕하세요"` |
| `role` | `Literal[...]` | OpenAI-compatible role | `"assistant"` |
| `tool_calls` | `list[...] \| None` | 도구 호출 목록 | `[ {...} ]` |
| `function_call` | `FunctionCall \| None` | legacy 함수 호출 | `{"name":"lookup"}` |
| `reasoning_content` | `str \| None` | provider가 제공한 추론 내용 | `"..."` |
| `provider_specific_fields` | `dict[str, Any] \| None` | 프로바이더별 추가 정보 | `{"trace_id":"..."}` |
| `annotations` | `list[...] \| None` | 응답 annotation | `[ {...} ]` |
| 추가 key | `Any` | 모델 설정상 보존 가능 | `{"metadata": {...}}` |

LiteLLM의 요청 history는 `completion(messages=[...])`에 넘기는 OpenAI-compatible dict 배열이다. LiteLLM은 이 배열을 여러 provider 입력으로 변환하지만, 모든 provider에서 임의의 추가 field가 동일하게 보존된다고 보장하지 않는다.

### 4.3 export와 import

응답 `Message`는 다음 방법으로 JSON-safe 값을 얻을 수 있다.

```python
message.model_dump(mode="json")
message.to_dict()
message.json()  # 현재 버전에서는 dict를 반환하는 호환 메서드
```

다시 모델 객체가 필요하면 Pydantic validation을 사용할 수 있다.

```python
restored = Message.model_validate(payload)
```

그러나 LiteLLM은 `history_to_json()`이나 `json_to_history()` 같은 범용 대화 히스토리 왕복 API를 제공하지 않는다. 요청 history는 애플리케이션이 dict 배열로 관리해야 한다.

## 5. LangChain Core

### 5.1 `BaseMessage` 스키마

```python
class BaseMessage(Serializable):
    content: str | list[str | dict[Any, Any]]
    additional_kwargs: dict[Any, Any] = Field(default_factory=dict)
    response_metadata: dict[Any, Any] = Field(default_factory=dict)
    type: str
    name: str | None = None
    id: str | None = None

    model_config = ConfigDict(extra="allow")
```

출처: [`base.py`](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/base.py)

### 5.2 주요 메시지 타입

| 타입 | 주요 용도 | 추가 정보 예시 |
|---|---|---|
| `SystemMessage` | 시스템 지침 | `content` |
| `HumanMessage` | 사용자 입력 | `content`, `name`, `id` |
| `AIMessage` | 모델 응답 | `tool_calls`, `invalid_tool_calls`, `usage_metadata` |
| `ToolMessage` | 도구 실행 결과 | `tool_call_id`, `artifact`, `status` |
| `FunctionMessage` | legacy 함수 결과 | `name` |
| `ChatMessage` | 사용자 지정 role | `role` |
| `*MessageChunk` | streaming 조각 | 부분 content, 부분 tool call |

`content`는 문자열뿐 아니라 content block 목록도 될 수 있다. `additional_kwargs`는 provider가 전달한 추가 payload, `response_metadata`는 header·logprob·token count·model name 등 응답 정보를 보관하는 영역이다.

### 5.3 export 코드

현재 LangChain Core의 구현은 다음과 같다.

```python
def message_to_dict(message: BaseMessage) -> dict[str, Any]:
    return {"type": message.type, "data": message.model_dump()}


def messages_to_dict(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    return [message_to_dict(m) for m in messages]
```

결과 예시:

```json
{
  "type": "human",
  "data": {
    "content": "안녕하세요",
    "additional_kwargs": {"tag": "important"},
    "response_metadata": {},
    "type": "human",
    "name": null,
    "id": null
  }
}
```

### 5.4 import 코드

```python
def messages_from_dict(messages: Sequence[dict[str, Any]]) -> list[BaseMessage]:
    return [_message_from_dict(m) for m in messages]
```

내부 import는 `type` 값에 따라 구체 클래스를 선택한다.

```python
if type_ == "human":
    return HumanMessage(**message["data"])
if type_ == "ai":
    return AIMessage(**message["data"])
if type_ == "system":
    return SystemMessage(**message["data"])
if type_ == "tool":
    return ToolMessage(**message["data"])
raise ValueError(f"Got unexpected message type: {type_}")
```

LangChain은 네 라이브러리 중 유일하게 **메시지 객체 배열을 위한 명시적 export/import helper**를 제공한다. 하지만 결과는 OpenAI `{"role": ..., "content": ...}`가 아니라 LangChain 전용 `{"type": ..., "data": ...}` envelope다.

### 5.5 텍스트 변환의 한계

LangChain의 `get_buffer_string()` 같은 함수는 메시지를 사람이 읽는 문자열로 합칠 수 있지만, role·tool call·metadata를 완전하게 복원하기 위한 직렬화가 아니다. 캐시 기준 자료로 사용하면 구조가 손실된다.

## 6. metadata와 tag 비교

| 라이브러리 | metadata 위치 | 확장 필드 보존 | 주의점 |
|---|---|---|---|
| OpenAI | 주로 요청 top-level `metadata`; 메시지에는 `name`, tool 관련 필드 | TypedDict 표준 밖 임의 field는 보장되지 않음 | provider 전송 가능 여부 확인 필요 |
| Anthropic | 요청 top-level `metadata`, `system`, `tools`; content block 내부에도 provider 구조 존재 | `MessageParam`의 정해진 block union 중심 | system은 메시지 배열 밖에서 처리 |
| LiteLLM | 요청 kwargs와 provider-specific message field | `Message`는 `extra="allow"` | provider별 전달·응답 보존이 다를 수 있음 |
| LangChain | `additional_kwargs`, `response_metadata`, 모델 extra field | `extra="allow"` | export 결과가 LangChain 전용 envelope |

캐시 hash에는 임의 field를 조용히 제거하면 안 된다. 다만 모든 metadata가 Detector 판단에 영향을 주는 것은 아니므로 다음 범위를 별도로 정의해야 한다.

- Detector 입력에 실제 전달되는 field
- 요청 실행 옵션에만 해당하는 field
- 응답 관찰용 field
- 캐시 namespace로 분리해야 하는 field

## 7. Compaction과 히스토리 항목

현재 조사한 compaction 방식은 하나로 통일되어 있지 않다.

| 시스템 | 표현 | export/import 시 주의점 |
|---|---|---|
| Anthropic | assistant content 안의 `compaction` block | 반환된 전체 content block을 다음 history에 그대로 추가 |
| OpenAI Responses | `type="compaction"` opaque item | 내부 내용을 해석·수정하지 않고 그대로 보관 |
| LangChain | summary middleware가 기존 메시지를 summary로 교체 | checkpointer 상태가 새 메시지 배열로 바뀜 |
| LiteLLM | 공통 compaction item 없음 | 호출자가 명시한 구조만 보관 |

따라서 low-level history item에는 다음 구분을 둘 수 있다.

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `kind` | `Literal["message", "compaction"]` | 일반 메시지인지 compaction인지 | `"compaction"` |
| `source` | `str` | 원본 라이브러리와 필드 위치 | `"anthropic.content_block"` |
| `payload` | `JsonObject` | 원본 JSON 전체 | `{ "type": "compaction", ... }` |
| `message_hash` | `str` | 항목 하나의 hash | `"item-hash-21"` |
| `history_hash` | `str` | 이 항목까지의 누적 hash | `"history-hash-21"` |
| `covered_history_hash` | `str \| None` | compaction이 대체한 이전 범위 | `"history-hash-20"` |

표식이 없는 summary 문장을 보고 임의로 compaction으로 판정하면 안 된다.

## 8. 캐시 유틸리티에 대한 결론

1. 입력은 선택한 SDK의 native history를 받는다.
2. OpenAI·Anthropic·LiteLLM dict는 JSON-safe 여부만 검증한다.
3. LangChain은 `messages_to_dict()`를 통해 LangChain envelope를 보존한다.
4. 응답 모델은 각 라이브러리의 `model_dump()` 또는 `to_dict()`를 사용한다.
5. 모든 JSON 필드를 보존하고 객체 key만 RFC 8785로 정규화한다.
6. 배열 순서, content block 순서, tool call 순서는 유지한다.
7. 중복 key·바이너리·비JSON 타입은 파싱 단계에서 거부한다.
8. hash는 메시지 하나와 누적 히스토리 prefix 각각에 대해 계산한다.
9. Detector 결과는 메시지 hash와 history hash를 통해 연결하되, 문맥 의존 결과는 history hash 없이 재사용하지 않는다.
10. 복원에 필요한 원문 값은 이 유틸리티에 저장하지 않고, 상위 key-value 시스템이 별도로 관리한다.

## 9. 참고 소스

- [OpenAI `ChatCompletionMessageParam`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_message_param.py)
- [OpenAI `ChatCompletionAssistantMessageParam`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_assistant_message_param.py)
- [OpenAI `CompletionCreateParamsBase`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/completion_create_params.py)
- [Anthropic `MessageParam`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message_param.py)
- [Anthropic `MessageCreateParamsBase`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message_create_params.py)
- [Anthropic `Message`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message.py)
- [LangChain `BaseMessage`](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/base.py)
- [LiteLLM Input Params](https://docs.litellm.ai/docs/completion/input)
- [Anthropic Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [LangChain Short-term Memory](https://docs.langchain.com/oss/python/langchain/short-term-memory)
- [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages)
- [Hugging Face Transformers Chat Templates](https://huggingface.co/docs/transformers/main/en/chat_templating)


## 10. 여러 버전 설치 스파이크

### 10.1 버전 식별 가능 여부

런타임 패키지 버전은 `importlib.metadata.version(package_name)`으로 확인할 수 있다. 조사한 SDK 메시지 타입에는 공통 `schema_version` 필드가 없었다. 따라서 다음 세 값을 분리해야 한다.

| 값 | 의미 | 캐시 hash 기준 |
|---|---|---|
| `source_library_version` | 설치된 SDK의 재현·진단 정보 | 직접 사용하지 않음 |
| `api_version` | 공급자 API 계약 버전 | provider adapter 입력 |
| `adapter_version` | 우리 코드가 해석한 native 형식 버전 | 사용함 |

### 10.2 버전별 결과

| 라이브러리 | 설치해 본 버전 | JSON·객체 형식 차이 | 실측 결론 |
|---|---|---|---|
| OpenAI Python SDK | `1.0.0`, `1.54.0`, `2.54.0` | API type은 1.0.0에서 combined `TypedDict`(`content`, `function_call`, `name`, `role`), 2.54.0에서 six-member role-specific union. 단순 fixture를 dict-shaped wire 입력으로 수락 | 단순 `{role, content}` wire shape는 세 버전에서 동일하지만 generated type 계약은 변경됨 |
| Anthropic Python SDK | `0.25.0`, `0.49.0`, `1.4.0` | `MessageParam`은 세 버전 모두 `content`·`role` `TypedDict`. 요청 필드는 `thinking`, `tools`, `tool_choice`, 이후 `cache_control`, `container`, `output_config` 등으로 증가 | 기존 history shape는 유지되지만 요청 계약은 확장됨 |
| LangChain Core | `0.2.0`, `0.3.0`, `1.6.2` | `type/data` envelope는 유지. `0.x` serialized data에는 `example`이 있었고, `1.6.2`에서는 없어졌으며 `AIMessage`에 `usage_metadata`가 추가됨 | 같은 대화라도 LangChain 버전에 따라 export JSON이 달라질 수 있음 |
| LiteLLM | `1.54.0`, `1.60.0`, `1.85.0`, `1.99.0` | OpenAI-compatible 요청 dict는 유지. `Message` 응답 모델은 1.54.0의 기본 필드에서 1.60.0의 provider-specific 필드, 이후 reasoning·annotation·image 필드로 확장됨 | 요청 경계는 안정적이지만 응답 모델과 provider 변환은 변할 수 있음 |

프로브의 `fixture_shape`·`input_shape`는 공통 fixture로부터 프로브가 locally 만든 dict의 형태이며 SDK가 객체를 생성했다는 뜻이 아니다. `TypedDict` 여부와 필드는 imported class의 type marker·annotation을 별도로 조사했다.

`litellm 1.40.0`과 `1.50.0`은 PyPI에 해당 안정 릴리스가 없었다. `1.60.0`은 Python 3.13에서 `cgi` 제거로 import가 실패했지만 Python 3.12에서는 설치·import·schema probe가 성공했다. 이는 JSON schema 차이와 별개의 런타임 호환성 문제다.

**결론:** 라이브러리 버전에 따라 JSON-safe 표현은 실제로 바뀔 수 있다. Detector cache의 `(namespace, history_hash_n)`은 캐시 주소다. 실제 상위 계층의 재사용 검증은 기존 명세의 `format`, `schema_version`, `detector_fingerprint`, `masker_fingerprint`까지 포함해야 한다. `adapter_version`, `api_version`, provider/model profile은 `history_hash` chain에 섞지 않고 별도 compatibility/profile key로 관리한다.

실행 가능한 스파이크 자산은 [`spikes/chat-format-versions/`](../spikes/chat-format-versions/)에 있다. 공통 입력은 [`three-turn.json`](../spikes/chat-format-versions/fixtures/three-turn.json), 버전 probe는 [`probe_versions.py`](../spikes/chat-format-versions/probes/probe_versions.py), 결과 요약은 [`results.json`](../spikes/chat-format-versions/results.json)이다.

## 11. 실제 provider 전송 형식

### 11.1 공통 정정

OpenAI SDK, Anthropic SDK, LiteLLM을 통한 원격 호출에서 애플리케이션이 provider에 보내는 것은 **HTTP JSON 요청**이다. SDK가 history를 하나의 자유형 텍스트 prompt로 먼저 만들어 전송하는 공통 규칙은 확인되지 않았다.

그 다음 provider 서버가 내부적으로 메시지 구조를 모델 입력 token sequence로 바꿀 수 있지만, OpenAI·Anthropic 원격 API는 그 최종 prompt text 또는 chat template을 공개 입력 계약으로 제공하지 않는다. 따라서 세 경계를 구분해야 한다.

1. **Detector history hash:** native history JSON의 메시지 내용·순서만 누적하는 기존 `history_hash`
2. **wire/profile hash:** provider request JSON의 `wire_payload_hash`와 provider/model/API/template 설정의 `provider_profile_hash`
3. **provider 내부 경계:** 모델별 chat template과 tokenizer를 거친 token sequence

### 11.2 provider별 HTTP JSON

| 호출 경로 | 실제 body 핵심 | role·content 규칙 | metadata·제어 정보 |
|---|---|---|---|
| OpenAI Chat Completions | `{"model": "...", "messages": [...]}` | `system`, `developer`, `user`, `assistant`, `tool`, legacy `function`; `content`는 문자열 또는 content-part 배열 | tool call과 `tool_call_id`, request top-level `metadata`, model별 prompt cache breakpoint 등 |
| Anthropic Messages | `{"model": "...", "max_tokens": ..., "system": ..., "messages": [...]}` | `messages`에는 API 문서상 `user`·`assistant`; `content`는 문자열 또는 typed block 배열. system은 top-level | `anthropic-version: 2023-06-01`; tool use/result와 block별 `cache_control` |
| LiteLLM → OpenAI target | OpenAI-compatible `POST /chat/completions` JSON | 입력 `messages`를 거의 그대로 전달 | target provider가 이해하지 못하는 임의 field의 보존은 보장하지 않음 |
| LiteLLM → Anthropic target | Anthropic `POST /v1/messages` JSON으로 변환 | 문자열 content를 `{"type":"text","text":"..."}` block으로 만들고 system도 text block 배열로 변환 | `max_tokens` 기본값 등 target-specific 필드가 추가될 수 있음 |
현재 LiteLLM `1.99.0`을 fake localhost server에 연결한 결과, OpenAI target은 `/chat/completions`에 전체 fixture `messages` 배열을 보냈고, Anthropic target은 root `api_base`에서 `/v1/messages`로 다음과 같이 변환했다.

```json
{
  "max_tokens": 4096,
  "system": [{"type": "text", "text": "You are a concise assistant."}],
  "messages": [
    {
      "role": "user",
      "content": [{"type": "text", "text": "Summarize the weather report."}]
    },
    {
      "role": "assistant",
      "content": [{"type": "text", "text": "I need the report first."}]
    }
  ]
}
```

이는 모든 LiteLLM 버전·모델의 고정 규칙이 아니라 `1.99.0`과 해당 target을 대상으로 한 실측이다. probe는 [`probe_litellm_targets.py`](../spikes/chat-format-versions/probes/probe_litellm_targets.py)다.

### 11.3 LangChain 변환

LangChain Core `1.6.2`의 동일한 메시지 배열은 저장 시 다음 envelope를 유지한다.

```json
{"type": "human", "data": {"content": "...", "additional_kwargs": {}, "response_metadata": {}, "type": "human"}}
```

OpenAI 변환 helper를 적용하면 `{"role": "user", "content": "..."}`가 되고, tool call은 OpenAI의 `tool_calls` 구조로 변환된다. 이는 최종 provider wire payload가 아니라 LangChain integration이 사용할 중간 변환 결과다. 실측 probe는 [`probe_langchain_conversion.py`](../spikes/chat-format-versions/probes/probe_langchain_conversion.py)다.

## 12. 모델 내부의 텍스트 chat template

로컬 causal language model은 role·content dict를 그대로 이해하는 것이 아니라 token sequence를 계속 생성한다. Hugging Face Transformers의 `tokenizer.apply_chat_template()`은 모델 tokenizer에 저장된 Jinja template으로 이 구조를 텍스트/control token으로 렌더링한다.

같은 fixture를 모델별로 렌더링한 결과:

```text
SmolLM2 / Qwen:
<|im_start|>system
You are a concise assistant.<|im_end|>
<|im_start|>user
Summarize the weather report.<|im_end|>
<|im_start|>assistant
I need the report first.<|im_end|>
<|im_start|>assistant

Mistral-7B-Instruct:
<s> [INST] You are a concise assistant.

Summarize the weather report. [/INST] I need the report first.</s>
```

따라서 텍스트 형식은 **라이브러리별 고정 형식이 아니라 주로 모델·tokenizer별 형식**이다. 문법의 핵심은 template마다 다르며, role marker, begin/end token, 줄바꿈, tool block, assistant generation prompt가 모두 의미를 가질 수 있다. `add_generation_prompt=True` 같은 옵션도 최종 token sequence를 바꾼다.

이번 실측은 `transformers 5.17.0`에서 다음 Hugging Face commit revision을 고정해 수행했다.

| 모델 | 고정 revision |
|---|---|
| `HuggingFaceTB/SmolLM2-135M-Instruct` | `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| `Qwen/Qwen2.5-0.5B-Instruct` | `7ae557604adf67be50417f59c2c2f167def9a775` |
| `mistralai/Mistral-7B-Instruct-v0.2` | `63a8b081895390a26e140280378bc85ec8bce07a` |

원격 provider의 최종 텍스트는 provider 서버 내부 template이므로 이 저장소에서 재현 가능한 공통 문자열로 간주하면 안 된다. 로컬 모델까지 지원할 때만 `model_id`, revision, tokenizer chat template, template 옵션을 함께 기록해야 한다. Transformers 실측 probe는 [`probe_chat_templates.py`](../spikes/chat-format-versions/probes/probe_chat_templates.py)다.

## 13. hash 유틸리티에 미치는 영향

1. **hash 경계 분리:** `history_hash`는 native history JSON과 메시지 순서만으로 계산한다. provider request 전체는 별도 `wire_payload_hash`, provider/model/API/template 설정은 별도 `provider_profile_hash`로 계산하며 어느 것도 history chain에 섞지 않는다.
2. **형식 분리:** OpenAI dict, Anthropic top-level `system` 구조, LiteLLM target payload, LangChain `type/data` envelope를 하나의 공통 메시지 배열로 자동 합치지 않는다.
3. **버전 분리:** SDK patch 버전이 아니라 `adapter_version`을 provider profile의 호환성 기준으로 사용한다. field 추가·기본값·변환 규칙이 cache 의미를 바꿀 때만 adapter를 올린다.
4. **provider/model 분리:** 같은 `messages`라도 target provider, endpoint, model, API version, chat-template 옵션이 다르면 모델 입력 의미가 달라질 수 있다. 이 값은 `provider_profile_hash` 또는 별도 cache key segment로 관리한다.
5. **metadata 분류:** `role`, content block, tool call처럼 모델 입력에 영향을 주는 필드는 hash에 포함한다. tracing·응답 관찰용 metadata는 별도 namespace로 분리할 수 있지만 조용히 삭제하면 안 된다.
6. **unknown field 보존:** provider-specific field를 버리면 같은 SDK object가 다른 payload로 재구성될 수 있으므로 adapter가 인식하지 못한 JSON field는 보존하거나 명시적으로 거부한다.
7. **golden wire test:** 각 adapter는 실제 네트워크 없이 fake transport로 request body를 고정 검증한다. SDK 업그레이드 시 schema probe와 golden payload를 함께 재실행한다.

이번 스파이크는 hash 구현을 변경하지 않았다. 현재 [`docs/cache-hash-utility.md`](cache-hash-utility.md)의 `(namespace, history_hash_n)` Detector 계약은 유지하고, provider request cache가 필요할 때만 `wire_payload_hash`·`provider_profile_hash`를 별도 계층으로 추가한다.

## 14. 다음 설계안

- 기본 저장 단위는 선택한 native history와 그에 대한 `history_hash`이다.
- provider request cache를 추가할 경우 native history cache와 분리된 `wire_payload_hash`·`provider_profile_hash`를 사용한다.
- adapter는 `to_json_safe()`와 `to_provider_payload()`를 분리한다. 전자는 저장·hash용, 후자는 실제 전송용이다.
- 원격 provider 최종 prompt text를 저장·재생성하려고 하지 않는다.
- 로컬 모델 adapter만 tokenizer template과 rendering 옵션을 명시적으로 포함한다.
- SDK 버전 감지는 런타임 진단 필드와 lockfile로 수행하고, schema 호환성은 adapter contract와 golden wire fixture로 판정한다.
- Anthropic의 top-level `system`, LiteLLM의 target별 block 변환, LangChain의 `type/data` envelope를 각각 독립적인 호환성 사례로 취급한다.

## Impact Surface

- Code: `spikes/chat-format-versions/`에 버전·wire·LangChain·chat-template probe와 공통 fixture를 추가했다. 운영 코어는 변경하지 않았다.
- Skills: 변경 없음.
- Docs: 버전별 JSON 차이, provider HTTP JSON, 모델별 chat template, hash 경계를 이 보고서에 추가했고, 본문과 `cache-hash-utility.md`를 합친 인쇄용 Word 파생본 `message-format-report.docx`를 생성했다.
- Decisions: SDK 버전과 `adapter_version`을 분리하고, 원격 provider payload와 모델 내부 token template을 별도 경계로 취급한다.
- Archive/versioning: 최신 조사 보고서이며 이전 문서와 경쟁하지 않는다.
- Verification: OpenAI `1.0.0/1.54.0/2.54.0`, Anthropic `0.25.0/0.49.0/1.4.0`, LangChain Core `0.2.0/0.3.0/1.6.2`, LiteLLM `1.54.0/1.85.0/1.99.0`을 격리 설치해 probe했다. fake HTTP와 local tokenizer rendering 결과를 확인했다.
- No-update rationale: cache/hash utility 구현과 static demo는 별도 설계 승인 후 진행한다.
