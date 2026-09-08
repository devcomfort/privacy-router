# 채팅 메시지 스키마·변환 코드 조사 보고서

**조사 목적:** OpenAI SDK, Anthropic SDK(Claude), LiteLLM, LangChain이 채팅 히스토리를 어떤 자료 구조로 정의하고 JSON으로 내보내거나 다시 읽는지 확인한다.

**조사 기준 버전:** `openai 2.54.0`, `anthropic 1.4.0`, `langchain-core 1.6.2`, 저장소의 `litellm 1.99.0`.

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

## Impact Surface

- Code: 변경 없음. 외부 SDK 스키마와 export/import 동작만 조사했다.
- Skills: 변경 없음.
- Docs: OpenAI·Anthropic·LiteLLM·LangChain 메시지 스키마와 변환 경로를 하나의 보고서로 정리했다.
- Decisions: native format을 유지하고 JSON-safe 형태로만 추출하며, compaction은 명시된 provider 표식으로만 구분한다.
- Archive/versioning: 최신 조사 보고서이며 이전 문서와 경쟁하지 않는다.
- Verification: OpenAI·Anthropic·LangChain은 현재 SDK에서 코드를 확인했고, LiteLLM은 설치된 `Message` 모델과 메서드를 확인했다.
- No-update rationale: 캐시 유틸리티 구현과 static demo는 별도 설계 승인 후 진행한다.
