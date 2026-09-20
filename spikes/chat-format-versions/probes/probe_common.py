from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "three-turn.json"


def load_messages() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text())
