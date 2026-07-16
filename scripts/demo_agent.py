#!/usr/bin/env python3
"""Privacy Router Demo Agent — Simulates agent behavior with Privacy Router integration.

This script demonstrates how Hermes Agent interacts with Privacy Router to
protect sensitive information while generating responses.

Usage:
    python scripts/demo_agent.py [--api-key pr-...] [--model privacy-router]
"""

import argparse
import json
import urllib.request
from datetime import datetime
from pathlib import Path


def classify(api_url: str, api_key: str, text: str) -> dict:
    """Call Privacy Router classify endpoint."""
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(f"{api_url}/api/v1/classify", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def generate(api_url: str, api_key: str, text: str) -> dict:
    """Call Privacy Router generate endpoint (classify + mask + LLM)."""
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(f"{api_url}/api/v1/generate", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def chat(api_url: str, api_key: str, text: str, model: str) -> dict:
    """Call Privacy Router chat completions endpoint."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request(f"{api_url}/v1/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def process_with_privacy(api_url: str, api_key: str, text: str, model: str) -> dict:
    """Simulate agent behavior with Privacy Router integration.

    This demonstrates the flow:
    1. Agent receives user input
    2. Agent calls Privacy Router classify to check for sensitive data
    3. Based on classification, agent either:
       a. Sends directly to LLM (non-sensitive)
       b. Masks and sends to LLM (sensitive, maskable)
       c. Routes to local LLM (sensitive, essential)
    4. Agent logs all decisions for audit trail
    """
    log_entry = {"timestamp": datetime.now().isoformat(), "input": text, "steps": []}

    # Step 1: Classify
    print(f"\n{'=' * 60}")
    print(f"Input: {text[:60]}...")
    print(f"{'=' * 60}")

    print("\n[Step 1] Classifying with Privacy Router...")
    classify_result = classify(api_url, api_key, text)
    is_sensitive = classify_result.get("is_sensitive", False)
    records = classify_result.get("records", [])
    policy = classify_result.get("policy_action", "unknown")

    log_entry["steps"].append(
        {"step": "classify", "is_sensitive": is_sensitive, "records": len(records), "policy_action": policy}
    )

    print(f"  is_sensitive: {is_sensitive}")
    print(f"  records: {len(records)}")
    for r in records:
        print(f'    - {r.get("category")}: "{r.get("span")}" ({r.get("confidence", 0):.0%})')
    print(f"  policy_action: {policy}")

    # Step 2: Route based on policy
    if policy == "blocked":
        print("\n[Step 2] 🚫 Request blocked — extreme sensitivity")
        log_entry["steps"].append({"step": "blocked", "reason": "extreme sensitivity"})
        return log_entry

    if policy == "block":
        print("\n[Step 2] 🏠 Routing to local LLM (sensitive data is essential)")
        print("  → Data stays on-device, no external API call")
        log_entry["steps"].append({"step": "block", "reason": "sensitive data essential"})
        # In real implementation, this would call a local LLM
        print("  → [Simulated] Local LLM response generated")
        return log_entry

    if policy == "selective_mask":
        print("\n[Step 2] 🔒 Masking sensitive data and sending to external LLM")
        chat_result = chat(api_url, api_key, text, model)
        chat_result.get("privacy_router", {})
        response = chat_result.get("choices", [{}])[0].get("message", {}).get("content", "")

        log_entry["steps"].append(
            {
                "step": "selective_mask",
                "records_masked": len(records),
                "model_used": model,
                "response_length": len(response),
            }
        )

        print(f"  → Masked {len(records)} record(s)")
        print(f"  → Model: {model}")
        print(f"  → Response: {response[:100]}...")
        return log_entry

    # Non-sensitive: send directly
    print("\n[Step 2] ✅ No sensitive data — sending directly to LLM")
    chat_result = chat(api_url, api_key, text, model)
    response = chat_result.get("choices", [{}])[0].get("message", {}).get("content", "")

    log_entry["steps"].append({"step": "direct", "model_used": model, "response_length": len(response)})

    print(f"  → Model: {model}")
    print(f"  → Response: {response[:100]}...")
    return log_entry


def main():
    parser = argparse.ArgumentParser(description="Privacy Router Demo Agent")
    parser.add_argument("--api-url", default="http://localhost:8787", help="Privacy Router API URL")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument("--model", default="privacy-router", help="Privacy Router model alias")
    parser.add_argument("--output", default="usage-log/demo-agent-log.json", help="Output log file")
    args = parser.parse_args()

    # Demo scenarios
    scenarios = [
        "오늘 날씨가 좋습니다",
        "파이썬에서 리스트 컴프리헨션 사용법을 알려주세요",
        "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘",
        "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다",
        "새로운 Attention 대체 아이디어를 구상 중이다",
        "이메일을 작성해주세요",
        "내 주민등록번호가 뭐야?",
        "새로운 강화학습 알고리즘을 설계해주세요",
    ]

    print("=" * 60)
    print("Privacy Router Demo Agent")
    print(f"API: {args.api_url}")
    print(f"Model: {args.model}")
    print("=" * 60)

    all_logs = []
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n\n{'#' * 60}")
        print(f"Scenario {i}/{len(scenarios)}")
        print(f"{'#' * 60}")
        log = process_with_privacy(args.api_url, args.api_key, scenario, args.model)
        all_logs.append(log)

    # Save logs
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_logs, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'=' * 60}")
    print(f"Logs saved to {output_path}")
    print(f"Total scenarios: {len(all_logs)}")

    # Summary
    sensitive_count = sum(1 for log_entry in all_logs if log_entry.get("steps", [{}])[0].get("is_sensitive"))
    print(f"Sensitive: {sensitive_count}/{len(all_logs)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
