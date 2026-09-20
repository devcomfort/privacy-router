# Cachier — 세션별 탐지 결과 캐시

**상태:** 구현됨. `src/cachier/`가 기준이며, 이전 JSON 해시 유틸리티 초안을 대체한다.

## 역할과 경계

Cachier는 Extractor, Masker와 함께 사용하는 기본 컴포넌트다. 이미 수행한 탐지의 민감성·개별 필수성·전체 마스킹 영향·위치 정보를 재사용한다. 모델 호출, 세션 생성, 원문 보관, 마스킹과 복원은 수행하지 않는다.

- 입력은 Extractor에 전달한 정확한 `str` 또는 `bytes`, 이전 문맥, 해당 추출에 사용한 선택적 `IntentAnnotation`이다. SDK 메시지 객체 변환이나 첨부파일 읽기는 어댑터·호출자 책임이다.
- `ExtractionResult`와 정규화된 `DetectionResult`를 받는다.
- 메모리에 `CachedAssessment`, `DetectionReference`와 해시 기반 키만 보관한다. 원문, 민감 스팬, 의도 내용, 모델 설명, 플레이스홀더 매핑은 저장하지 않는다.
- 원본 세션 데이터와 Masker의 `MaskingContract`는 호출자가 보관한다. 캐시가 진단 결과 전체를 무손실 복원하는 것은 아니다.
- 별도 DB, 디스크 저장, 암호화 저장소, 외부 캐시 서버를 만들지 않는다.

## 캐시 주소

`Cachier.make_key(namespace=..., message=..., history=..., detector_fingerprint=..., intent=...)`로 `CacheKey`를 만든다. `intent`를 생략하면 의도가 없는 추출과만 일치한다.

| 필드 | 의미 |
|---|---|
| `namespace` | 호출자가 명시한 세션·권한 범위. 공백과 누락을 허용하지 않음 |
| `message_hash` | 현재 Extractor 입력의 내용 식별자 |
| `history_hash` | 현재 메시지를 제외한 이전 문맥 전체의 순서·내용 식별자 |
| `detector_fingerprint` | 모델·프롬프트·탐지 규칙을 식별하는 호출자 제공 값. 비어 있으면 거부 |
| `intent_hash` | 원문에 결합된 의도 어노테이션 전체의 지문. 의도 생략은 별도 해시로 구분 |

원문과 문맥의 문자열은 UTF-8로 인코딩한다. 문자열/bytes 타입 표식, 8바이트 길이, 실제 바이트를 순서대로 SHA-256에 공급하므로 문자열과 bytes, 메시지 경계, 문맥 순서가 구분된다. 원문은 JSON 직렬화·역직렬화하거나 정규화하지 않는다. 의도 메타데이터만 키 순서를 고정한 JSON으로 SHA-256을 계산하며, 그 문자열은 저장하지 않는다.

모든 조회는 다섯 필드가 일치해야 한다. 같은 원문이어도 목표·동작·완료 조건·채널·미해결 사항 중 하나가 바뀌면 다른 키다. 패턴 탐지라도 필수성은 문맥 의존적일 수 있으므로 메시지 hash만 같다는 이유로 결과를 재사용하지 않는다. 요약·절삭·compaction으로 문맥이 바뀌면 cache miss가 되며, 의미가 같다고 추정하지 않는다.

## 저장되는 데이터

`CachedAssessment(is_sensitive, references, masking_preserves_task)`를 저장한다. `masking_preserves_task`는 원문 전체의 민감 값을 함께 가려도 작업이 유지되는지에 대한 `True` / `False` / `None`이며, 평가하지 않은 탐지기는 `None`을 유지한다. 근거 문장인 `masking_reason`은 보관하지 않는다. 각 참조에는 아래 필드만 저장한다.

- `value_hash`: 원래 스팬의 UTF-8 SHA-256
- `category`, `start`, `end`, `confidence`
- `confidentiality`: `public` / `private` / `None`
- `necessity`: `required` / `optional` / `None`

`None`은 해당 판단이 미판정이라는 상태이며 세 번째 분류 라벨이 아니다. public 항목도 위치와 판정값을 재사용하지만 보호 대상으로 계산하지 않는다. 두 판단의 이유는 저장하지 않으며, `RouterResult`로 재구성할 때 해당 `reason`은 `None`이다. 브라우저가 같은 입력·의도·판정의 이전 응답 이유를 메모리에서 보여주면 이전 응답이라는 출처를 표시해야 한다.

민감하다는 판단은 있지만 찾은 스팬이 없다는 상태도 보존한다. `ExtractionResult.status`가 `partial`이거나 `DetectionResult.status`가 `failed` 또는 `partial`이면 저장하지 않고 같은 키의 이전 결과도 제거한다. 공개 항목의 원문 검증 실패도 완전한 공개 판정으로 바꾸지 않는다.

반환값은 변경 불가능한 dataclass와 tuple이다. 원래 탐지 결과를 수정해도 캐시가 바뀌지 않는다. 저장 용량은 `max_entries`로 제한하며 기본 256개다. 최근 사용 순서로 유지하고 한도를 넘으면 가장 오래 사용하지 않은 결과를 제거한다. namespace는 인증 기능을 대신하지 않으며, 호출자가 올바른 범위를 제공해야 한다.

## 사용

```python
from cachier import Cachier
from policy import HeuristicPolicy

cachier = Cachier(max_entries=256)
key = cachier.make_key(
    namespace=session_id,
    message=text,
    history=prior_context,
    detector_fingerprint=detector_fingerprint,
    intent=intent,
)
assessment = cachier.get(key)
if assessment is None:
    extraction = extractor.extract(text, intent=intent)
    cachier.put(key, extraction)
    assessment = cachier.get(key)
    if assessment is None:
        raise RuntimeError("Extraction did not complete")

recommendation = HeuristicPolicy().recommend([assessment])
```

예시의 `text`는 작업에 필요한 이전 대화까지 포함한 정확한 분석 원문이고, `prior_context`는 캐시를 격리하는 이전 문맥이다. `history` 해시가 Extractor의 모델 입력을 대신하지는 않는다. `intent`는 `IntentAnalyzer().annotate(text)` 또는 상위 `Annotator`가 제공한 어노테이션이며, 키와 추출에 **동일한 객체/내용**을 전달해야 한다. 의도 분석까지 생략하려면 호출자가 이전 어노테이션을 보관해 재전달해야 한다. 독립적으로 분석한 문장별 결과만 합쳐 전체 마스킹의 안전성을 추론하지 않는다. 캐시 미적중은 공개 가능의 근거가 아니며 불완전하거나 미판정인 근거의 행동 권고는 `None`이다.

`invalidate(namespace)`는 한 세션의 결과만 제거하고 제거 개수를 반환한다. `clear()`는 이 Cachier 인스턴스의 모든 결과를 제거한다.

Masker에 참조를 다시 사용할 때는 호출자가 보관한 원문에서 `start:end`를 읽고 `value_hash`와 일치하는지 확인한 다음 전달한다. hash는 원문 복원 수단이 아니다. 짧은 이름·전화번호처럼 후보가 적은 값은 hash로도 추측할 수 있으므로 캐시 참조를 외부 에이전트에 보내지 않는다.

`PrivacyRouter`는 이 조회·위치 검증을 수행하며 캐시 적중 시 추출을 건너뛰었다는 상태 이벤트를 전파한다. 실패한 위치 검증은 해당 namespace를 무효화하고 외부 전달을 중단한다. 새 추출은 마스킹·복원 일치까지 성공한 뒤 저장한다. 실행 이벤트와 최종 권장 행동은 캐시 저장 대상이 아니며, 매 실행에서 실제 상태와 현재 Policy로 결정한다.

## 변경 이력

- 2026-09-17: 항목별 기밀 여부와 필요성을 독립적인 이진 라벨 또는 미판정으로 저장한다. public 항목도 보존하되 민감하다고 간주하지 않으며 두 이유는 캐시에 보관하지 않는다.
- 2026-09-17: 개별 필수성과 별도로 전체 공동 마스킹의 작업 유지 여부를 보관한다. 근거 문장은 저장하지 않으며 같은 원문·문맥·의도의 캐시 재사용에도 세 행동 및 진짜 미판정이 유지된다.
- 2026-09-17: `PrivacyRouter`에 캐시 검증·추출 건너뜀 이벤트를 연결했다. Policy 예제를 등급 분류 대신 `recommend()`의 행동 권고로 전환했다.
- 2026-09-17: 의도 어노테이션으로 필수성을 판단하도록 변경하면서 캐시 키에 `intent_hash`를 추가했다. 원문이 같아도 다른 작업의 필수성 결과를 재사용하지 않으며 의도 내용은 저장하지 않는다.
- 2026-09-12: 사용자 결정에 따라 Cachier로 구현. 검토 전 JSON/RFC 8785 초안을 실제 텍스트 입력 기반 캐시와 명시적 세션·규칙 분리로 대체했다. 원문 미저장 원칙은 유지했다.

## Impact Surface

- Code: `src/cachier/`, `src/contracts/annotation.py`, `src/contracts/extraction.py`, `src/agents/extractor/schemas.py`, `src/policy/`, `src/router/`, `demo/server.py`.
- Skills: 변경 없음.
- Docs: 이 문서가 Cachier의 유일한 현행 명세이며 README와 탐지 가이드가 연결된다.
- Decisions: 문맥·의도·규칙이 같은 항목별 기밀 여부·필요성 및 전체 마스킹 판단값만 재사용한다. public 항목은 마스킹 대상이 아니며 기밀 여부 미판정은 보류한다. 이유는 캐시하지 않는다. 세 권장 행동과 원문 보관 경계는 유지한다.
- Archive/versioning: 실행되지 않은 설계 초안은 별도 보존하지 않음. 기존 모델 실험 기록은 변경하지 않음.
- Verification: namespace·모델·문맥·의도 분리, LRU, 실패 결과 무효화, 원문·의도 내용 미저장 및 실제 peer 추론 뒤 동일 의도 재실행 0회 호출을 확인.
- No-update rationale: 서버·인증·외부 저장소와 SDK 어댑터의 운영 통합은 이 컴포넌트의 구현 범위가 아니다.
