from __future__ import annotations

import json
import re
from pathlib import Path

PROMPT_PATH = Path(__file__).parents[1] / "extract.fixed.prompt"


def test_fixed_prompt_fenced_json_examples_are_parseable() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", prompt, flags=re.DOTALL)

    assert len(blocks) == 2
    for block in blocks:
        json.loads(block)
