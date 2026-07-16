#!/usr/bin/env python3
"""Test a specific prompt variant against the local model."""

import json
import sys
from pathlib import Path

import litellm

PROMPTS_DIR = Path(__file__).parent / "prompt_variants"

TEST_CASES = [
    {"name": "일반날씨", "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.", "expected": "allow"},
    {
        "name": "PII 포함",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "expected": "selective_mask",
    },
]


def test_prompt(prompt_name: str, temperature: float = 0.7, top_p: float = 1.0, max_tokens: int = 2048):
    prompt_path = PROMPTS_DIR / f"extract.{prompt_name}.prompt"
    if not prompt_path.exists():
        print(f"Prompt not found: {prompt_path}")
        return

    prompt_template = prompt_path.read_text(encoding="utf-8")

    for case in TEST_CASES:
        rendered = prompt_template.replace("{{text}}", case["text"])

        print(f"\n{'=' * 60}")
        print(f"Prompt: {prompt_name} | Case: {case['name']}")
        print(f"{'=' * 60}")

        try:
            response = litellm.completion(
                model="openai/google/gemma-4-E4B-it",
                messages=[{"role": "user", "content": rendered}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                api_base="http://localhost:8000/v1",
                timeout=60,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()

            # Try to parse JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            is_sensitive = data.get("sensitivity", {}).get("is_sensitive", False)
            records = data.get("records", [])

            print(f"  is_sensitive: {is_sensitive}")
            print(f"  records: {len(records)}")
            print("  OK: parsed successfully")

        except json.JSONDecodeError as e:
            print(f"  JSON ERROR: {e}")
            print(f"  Raw response: {content[:200]}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    prompt_name = sys.argv[1] if len(sys.argv) > 1 else "role"
    test_prompt(prompt_name)
