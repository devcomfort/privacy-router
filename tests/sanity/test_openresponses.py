"""Sanity: OpenResponses compliance check.

Runs the OpenResponses compliance test suite against Privacy Router.
Privacy Router implements /v1/chat/completions (OpenAI Chat Completions API),
NOT /responses (OpenAI Responses API), so most compliance tests will fail.
This is informational -- we record which tests pass/fail for future reference.

Requires:
- bun installed (~/.bun/bin/bun)
- OpenResponses repo cloned to /tmp/openresponses
- Running Privacy Router API at localhost:8787
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

OPENRESPONSES_DIR = "/tmp/openresponses"
BUN_BIN = os.path.expanduser("~/.bun/bin/bun")
BASE_URL = os.getenv("PRIVACY_ROUTER_URL", "http://localhost:8787/v1")
API_KEY = os.getenv("PRIVACY_ROUTER_API_KEY", "")

if not os.path.isdir(OPENRESPONSES_DIR):
    pytest.skip(
        "OpenResponses repo not found at /tmp/openresponses",
        allow_module_level=True,
    )
if not os.path.isfile(BUN_BIN):
    pytest.skip("bun not installed", allow_module_level=True)
if not API_KEY:
    pytest.skip("PRIVACY_ROUTER_API_KEY not set", allow_module_level=True)


def _run_compliance(filter_ids: list[str] | None = None) -> dict:
    """Run OpenResponses compliance tests and return parsed JSON."""
    cmd = [
        BUN_BIN,
        "run",
        "bin/compliance-test.ts",
        "--base-url",
        BASE_URL,
        "--api-key",
        API_KEY,
        "--model",
        "openrouter/google/gemma-4-26b-it",
        "--json",
    ]
    if filter_ids:
        cmd.extend(["--filter", ",".join(filter_ids)])

    result = subprocess.run(
        cmd,
        cwd=OPENRESPONSES_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "PATH": f"{os.path.dirname(BUN_BIN)}:{os.environ.get('PATH', '')}",
        },
    )

    output = result.stdout.strip()
    if not output:
        return {"error": "no output", "stderr": result.stderr[:500]}

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {"error": "could not parse JSON", "stdout": output[:500]}


class TestOpenResponsesCompliance:
    """OpenResponses compliance test results (informational)."""

    def test_compliance_suite_runs(self):
        """Verify the compliance suite can execute and return results."""
        results = _run_compliance()
        assert "error" not in results or results.get("summary"), (
            f"Compliance suite failed: {results.get('error', results.get('stderr', 'unknown'))}"
        )

    def test_basic_response(self):
        """basic-response compliance."""
        results = _run_compliance(filter_ids=["basic-response"])
        if "summary" in results:
            s = results["summary"]
            print(f"\n  basic-response: {s.get('passed', 0)} passed, {s.get('failed', 0)} failed")
            assert True
        else:
            pytest.skip(f"Could not run compliance: {results}")

    def test_streaming_response(self):
        """streaming-response compliance."""
        results = _run_compliance(filter_ids=["streaming-response"])
        if "summary" in results:
            s = results["summary"]
            print(f"\n  streaming-response: {s.get('passed', 0)} passed, {s.get('failed', 0)} failed")
            assert True
        else:
            pytest.skip(f"Could not run compliance: {results}")
