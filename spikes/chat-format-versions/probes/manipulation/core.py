"""Native-object extraction and replacement contract for the manipulation spike.

No payload export/import or provider conversion. Paths are explicit attribute/item
operations, never executable expressions supplied by callers. Extraction exposes
original leaves, including unsupported opaque values, instead of dropping them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Step:
    kind: Literal["item", "attr"]
    key: str | int


Path = tuple[Step, ...]


@dataclass(frozen=True)
class Slot:
    path: Path
    category: str
    value: Any
    editable: bool = True
    note: str = ""


@dataclass(frozen=True)
class Patch:
    slot: Slot
    replacement: Any


class Editor(Protocol):
    """Library-specific native path operations; set returns the new root."""

    name: str

    def get(self, root: Any, path: Path) -> Any: ...

    def set(self, root: Any, path: Path, value: Any) -> Any: ...


class DataAdapter(Protocol):
    """Identical caller API for SDK-native requests, responses and tool data."""

    def extract(self, payload: Any) -> tuple[Slot, ...]: ...

    def apply(self, payload: Any, patches: list[Patch]) -> Any: ...


def path_label(path: Path) -> str:
    return "$" + "".join(f".{step.key}" if step.kind == "attr" else f"[{step.key!r}]" for step in path)
