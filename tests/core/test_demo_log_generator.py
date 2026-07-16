"""Regression tests for the demo usage-log generator."""

import importlib.util
import runpy
import sys
import urllib.request
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parents[2] / "scripts" / "generate_demo_logs.py"
_SPEC = importlib.util.spec_from_file_location("generate_demo_logs", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
generate_demo_logs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generate_demo_logs)


def test_generate_log_classifies_each_prompt_once(monkeypatch):
    scenario = {
        "day": 1,
        "title": "Minimal Scenario",
        "description": "Regression fixture",
        "prompts": ["safe prompt", "sensitive prompt"],
    }
    calls: list[str] = []

    def fake_classify(_api_url: str, _api_key: str, text: str) -> dict:
        calls.append(text)
        if text == "sensitive prompt":
            return {
                "is_sensitive": True,
                "records": [{"category": "TEST_SECRET"}],
                "policy_action": "selective_mask",
            }
        return {"is_sensitive": False, "records": [], "policy_action": "allow"}

    monkeypatch.setattr(generate_demo_logs, "classify", fake_classify)

    log, failure_count = generate_demo_logs.generate_log(
        scenario,
        "http://router.example",
        "test-key",
    )
    assert failure_count == 0

    assert calls == scenario["prompts"]
    assert "| 2 | sensitive prompt | True | 1 | selective_mask |" in log


def test_generate_log_marks_failed_classification_in_summary(monkeypatch):
    scenario = {
        "day": 1,
        "title": "Unavailable Router",
        "description": "Regression fixture",
        "prompts": ["unavailable prompt"],
    }

    def failing_classify(_api_url: str, _api_key: str, _text: str) -> dict:
        raise OSError("router unavailable")

    monkeypatch.setattr(generate_demo_logs, "classify", failing_classify)

    log, failure_count = generate_demo_logs.generate_log(
        scenario,
        "http://router.example",
        "test-key",
    )
    assert failure_count == 1

    assert "| 1 | unavailable prompt | error | - | - |" in log


def test_demo_scenarios_do_not_repeat_prompts():
    prompts = [prompt for scenario in generate_demo_logs.SCENARIOS for prompt in scenario["prompts"]]

    assert len(prompts) == len(set(prompts))


def test_generate_log_labels_scripted_classification_run(monkeypatch):
    scenario = {
        "day": 1,
        "title": "Minimal Scenario",
        "description": "Regression fixture",
        "prompts": ["safe prompt"],
    }

    monkeypatch.setattr(
        generate_demo_logs,
        "classify",
        lambda *_args: {"is_sensitive": False, "records": [], "policy_action": "allow"},
    )

    log, failure_count = generate_demo_logs.generate_log(
        scenario,
        "http://router.example",
        "test-key",
    )
    assert failure_count == 0

    assert "# Scripted Demo Classification — Scenario 1: Minimal Scenario" in log
    assert "> **Scripted demo classification run.**" in log
    assert "not runtime telemetry" in log
    assert "real usage" not in log.lower()


def test_script_exits_nonzero_when_any_classification_fails(monkeypatch, tmp_path, capsys):
    def failing_urlopen(*_args, **_kwargs):
        raise OSError("router unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_MODULE_PATH),
            "--api-url",
            "http://router.example",
            "--api-key",
            "test-key",
            "--output",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(_MODULE_PATH), run_name="__main__")

    assert exit_info.value.code == 1
    assert "FAILED" in capsys.readouterr().out
