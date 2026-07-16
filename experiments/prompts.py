"""Prompt variant definitions for Privacy Router experiments.

Each variant combines one or more prompting techniques:
- zeroshot: No examples, direct instruction only
- fewshot: Labeled examples (3 or 8)
- cot: Chain-of-Thought (step-by-step reasoning)
- role: Role-based safety prompt (DLP guardrail persona)
- evidence: Context-grounded CoT (quote evidence before classifying)
- multistep: Multi-step pipeline (detect → classify → judge)
- conservative: Conservative bias (when uncertain, flag as sensitive)
- selfcheck: Self-check / self-critique before final output

Naming convention: techniques joined with '+', e.g. 'fewshot+cot+role'
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompt_variants"
PROMPTS_DIR.mkdir(exist_ok=True)


# ── Technique fragments ──────────────────────────────────────────────────────

ROLE_PREAMBLE = """You are a Data Loss Prevention (DLP) guardrail for an enterprise LLM assistant.
Your primary objective is to prevent leakage of regulated data or business secrets.
You must be conservative: when uncertain, err on the side of flagging content as sensitive.
"""

FEWSHOT_3 = """
## Examples

### Example 1
Input: "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "PII 포함"},
  "records": [
    {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "confidence": 0.98, "reasoning": "주민등록번호 패턴", "is_essential": false},
    {"category": "EMAIL_ADDRESS", "span": "이메일", "confidence": 0.90, "reasoning": "이메일 언급", "is_essential": false}
  ]
}
```

### Example 2
Input: "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "미공개 연구 아이디어"},
  "records": [
    {"category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "Attention 대체 아이디어", "confidence": 0.92, "reasoning": "미공개 연구 개념", "is_essential": true}
  ]
}
```

### Example 3
Input: "오늘 서울 날씨는 맑고 기온은 25도입니다."
Output:
```json
{
  "sensitivity": {"is_sensitive": false, "rationale": "민감 정보 없음"},
  "records": []
}
```
"""

FEWSHOT_8 = (
    FEWSHOT_3
    + """
### Example 4
Input: "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "미공개 사업 결정"},
  "records": [
    {"category": "FABRICATION_PROCESS_DECISION", "span": "TSMC 3nm 공정", "confidence": 0.94, "reasoning": "미공개 제조 결정", "is_essential": false}
  ]
}
```

### Example 5
Input: "내 주민등록번호가 뭐야?"
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "PII 직접 질의"},
  "records": [
    {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "주민등록번호", "confidence": 0.95, "reasoning": "PII 직접 언급", "is_essential": true}
  ]
}
```

### Example 6
Input: "연락처: hong@example.com, 010-1234-5678. 안내 메일을 작성해줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "PII 포함"},
  "records": [
    {"category": "EMAIL_ADDRESS", "span": "hong@example.com", "confidence": 0.98, "reasoning": "이메일 주소", "is_essential": false},
    {"category": "MOBILE_PHONE_NUMBER", "span": "010-1234-5678", "confidence": 0.98, "reasoning": "전화번호 패턴", "is_essential": false}
  ]
}
```

### Example 7
Input: "https://internal.company.com/project-x 에서 실적 데이터를 확인해줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": true, "rationale": "내부 URL"},
  "records": [
    {"category": "INTERNAL_SYSTEM_URL", "span": "https://internal.company.com/project-x", "confidence": 0.95, "reasoning": "내부 시스템 URL", "is_essential": true}
  ]
}
```

### Example 8
Input: "Python에서 리스트를 정렬하는 방법을 알려줘."
Output:
```json
{
  "sensitivity": {"is_sensitive": false, "rationale": "일반 지식"},
  "records": []
}
```
"""
)

COT_INSTRUCTION = """
## Step-by-Step Reasoning

Before outputting JSON, think through these steps:

Step 1: Read the entire input text carefully.

Step 2: For each sentence, ask yourself:
  - Does this contain personal identifiers (name, phone, email, ID number)?
  - Does this contain unpublished research, business secrets, or internal decisions?
  - Does this contain credentials, internal URLs, or sensitive URLs?

Step 3: For each identified sensitive span, determine:
  - What category does it belong to?
  - What is the exact minimal span?
  - Why is it sensitive?
  - If masked, would the user's question lose its meaning? (is_essential)

Step 4: Compile your findings into the JSON output.
"""

EVIDENCE_INSTRUCTION = """
## Evidence-Grounded Detection

For each sensitive span you detect, you MUST:
1. Quote the exact text span from the input
2. Explain why that specific text is sensitive
3. Do NOT infer sensitivity from context alone — the evidence must be in the text

Format your reasoning as: "The text '[quoted span]' is sensitive because [reason]."
"""

MULTISTEP_INSTRUCTION = """
## Multi-Step Detection Pipeline

### Step 1: Morphological Scan
First, scan for pattern-based sensitive information:
- Korean RRN: 6digits-7digits (e.g., 901212-1234567)
- Phone: 01X-XXXX-XXXX
- Email: user@domain
- URL: https://internal.* or https://*.local
- API keys: sk-*, key-*, token-*

### Step 2: Contextual Analysis
Then, analyze for meaning-based sensitivity:
- Unpublished research: "새로운", "구상 중", "접근하려", "아직 제출하지 않은"
- Business secrets: "채택", "결정", "전략", "예산", "내부"
- Credentials: passwords, API keys, tokens

### Step 3: Integration
Combine both scans. A span is sensitive if EITHER scan flags it.
"""

CONSERVATIVE_INSTRUCTION = """
## Conservative Detection Rule

**When in doubt, flag it as sensitive.**

It is better to over-detect (false positive) than to miss sensitive information (false negative).

Specifically:
- If a research idea MIGHT be unpublished, flag it
- If a number MIGHT be a budget, flag it
- If a name MIGHT be identifying, flag it
- Only skip if the information is CLEARLY public knowledge (weather, programming syntax, general advice)
"""

SELFCHECK_INSTRUCTION = """
## Self-Check Before Outputting

Before writing your final JSON, verify:

1. **Did I check every sentence?** Re-read the input. Any sensitive spans I missed?
2. **Did I separate morphological patterns?** (phone, email, RRN) from contextual meaning? (research, business)
3. **Is my is_essential judgment correct?**
   - Masking preserves meaning → is_essential: false
   - Masking destroys meaning → is_essential: true
   - Explicit confidentiality markers → ALWAYS is_essential: true
4. **Are my spans minimal?** No particles, no adverbs, no verb derivations included.
"""


# ── Base detection rules ─────────────────────────────────────────────────────

DETECTION_RULES = """
## Detection Rules

### Morphological Patterns (always flag)
- Korean RRN (주민등록번호): 6digits-7digits or the word "주민등록번호"
- Phone number: 01X-XXXX-XXXX or the word "전화번호"
- Email: user@domain format or the word "이메일"
- Internal URL: https://internal.*, https://*.local
- Credentials: passwords, API keys (sk-*, key-*)

### Contextual Sensitivity (flag when meaning suggests)
- Unpublished research: "새로운 아이디어", "구상 중", "접근하려", "아직 제출하지 않은"
- Business secrets: "채택 결정", "전략", "예산", "내부적으로"
- Severity order: methodology (HOW) > concept (WHAT) > status

### Masking Test (for is_essential)
- "이 span을 [MASKED]로 치환하면 원래 질의 의미가 유지되는가?"
- YES, meaning preserved → is_essential: false
- NO, meaning lost → is_essential: true
- Explicit markers ("비밀로 해줘", "공개하지 마") → ALWAYS is_essential: true
"""

OUTPUT_FORMAT = """
## Output Format

```json
{
  "sensitivity": {
    "is_sensitive": true,
    "rationale": "한 문장 설명"
  },
  "records": [
    {
      "category": "SCREAMING_SNAKE_CASE",
      "span": "최소 텍스트 단위",
      "confidence": 0.95,
      "reasoning": "왜 민감한지 한 줄",
      "is_essential": false
    }
  ]
}
```

No sensitive information: `{"sensitivity": {"is_sensitive": false, "rationale": "민감 정보 없음"}, "records": []}`
"""


# ── Variant builder ──────────────────────────────────────────────────────────


def build_prompt(techniques: list[str]) -> str:
    """Build a prompt from a list of technique names."""
    parts = []

    # Role preamble
    if "role" in techniques:
        parts.append(ROLE_PREAMBLE.strip())

    # Main instruction
    parts.append("Output ONLY a single JSON object. No markdown, no text outside the JSON.\n")
    parts.append("You detect sensitive information in text. Follow the rules below exactly.\n")

    # Conservative bias
    if "conservative" in techniques:
        parts.append(CONSERVATIVE_INSTRUCTION.strip())

    # Detection rules (always included)
    parts.append(DETECTION_RULES.strip())

    # Multi-step pipeline
    if "multistep" in techniques:
        parts.append(MULTISTEP_INSTRUCTION.strip())

    # Evidence grounding
    if "evidence" in techniques:
        parts.append(EVIDENCE_INSTRUCTION.strip())

    # Chain-of-Thought
    if "cot" in techniques:
        parts.append(COT_INSTRUCTION.strip())

    # Few-shot examples
    if "fewshot8" in techniques:
        parts.append(FEWSHOT_8.strip())
    elif "fewshot" in techniques:
        parts.append(FEWSHOT_3.strip())

    # Self-check
    if "selfcheck" in techniques:
        parts.append(SELFCHECK_INSTRUCTION.strip())

    # Output format
    parts.append(OUTPUT_FORMAT.strip())

    # Input placeholder
    parts.append("분석할 텍스트:\n{{text}}")

    return "\n\n---\n\n".join(parts)


# ── Variant definitions ──────────────────────────────────────────────────────

VARIANTS: dict[str, list[str]] = {
    # Single techniques
    "zeroshot": [],
    "fewshot": ["fewshot"],
    "fewshot8": ["fewshot8"],
    "cot": ["cot"],
    "role": ["role"],
    "evidence": ["evidence"],
    "multistep": ["multistep"],
    "conservative": ["conservative"],
    "selfcheck": ["selfcheck"],
    # Two-way combinations
    "fewshot+cot": ["fewshot", "cot"],
    "fewshot+role": ["fewshot", "role"],
    "fewshot+evidence": ["fewshot", "evidence"],
    "cot+role": ["cot", "role"],
    "cot+conservative": ["cot", "conservative"],
    "cot+selfcheck": ["cot", "selfcheck"],
    "role+conservative": ["role", "conservative"],
    "multistep+cot": ["multistep", "cot"],
    "evidence+selfcheck": ["evidence", "selfcheck"],
    # Three-way combinations
    "fewshot+cot+role": ["fewshot", "cot", "role"],
    "fewshot+cot+conservative": ["fewshot", "cot", "conservative"],
    "fewshot+cot+selfcheck": ["fewshot", "cot", "selfcheck"],
    "fewshot+role+conservative": ["fewshot", "role", "conservative"],
    "cot+role+conservative": ["cot", "role", "conservative"],
    "multistep+cot+selfcheck": ["multistep", "cot", "selfcheck"],
    "evidence+cot+selfcheck": ["evidence", "cot", "selfcheck"],
    # Four-way combinations
    "fewshot+cot+role+conservative": ["fewshot", "cot", "role", "conservative"],
    "fewshot+cot+role+selfcheck": ["fewshot", "cot", "role", "selfcheck"],
    "fewshot+cot+conservative+selfcheck": ["fewshot", "cot", "conservative", "selfcheck"],
    "fewshot+role+conservative+selfcheck": ["fewshot", "role", "conservative", "selfcheck"],
    # Full combination
    "fewshot+cot+role+conservative+selfcheck": ["fewshot", "cot", "role", "conservative", "selfcheck"],
    "fewshot8+cot+role+conservative+selfcheck": ["fewshot8", "cot", "role", "conservative", "selfcheck"],
}


def generate_all_variants() -> dict[str, str]:
    """Generate all prompt variants and save to files. Returns {name: path}."""
    result = {}
    for name, techniques in VARIANTS.items():
        prompt_text = build_prompt(techniques)
        path = PROMPTS_DIR / f"extract.{name}.prompt"
        path.write_text(prompt_text, encoding="utf-8")
        result[name] = str(path)
    return result


def get_variant_names() -> list[str]:
    """Return all variant names."""
    return list(VARIANTS.keys())


def get_variant_techniques(name: str) -> list[str]:
    """Return techniques used in a variant."""
    return VARIANTS.get(name, [])


if __name__ == "__main__":
    paths = generate_all_variants()
    print(f"Generated {len(paths)} prompt variants in {PROMPTS_DIR}")
    for name, _path in sorted(paths.items()):
        techniques = "+".join(VARIANTS[name]) if VARIANTS[name] else "zeroshot"
        print(f"  {name:<50} <- [{techniques}]")
