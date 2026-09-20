"""Inspection views over native SDK objects, with transactional leaf replacement.

The view does not reconstruct the payload. Unknown and opaque data remains in the
original graph. Only paths extracted as editable may be replaced. Shared/cyclic
mutable graphs are reported and refused for editing, not silently flattened.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import BaseModel

from .core import Editor, Patch, Path, Slot, Step
from .semantics import classify


class UnsupportedEdit(ValueError):
    """The spike cannot safely apply the requested native edit."""


def children(value: Any) -> Iterator[tuple[Step, Any]]:
    """Read stored data only, never computed properties or serializer output."""
    if isinstance(value, BaseModel):
        for name, item in vars(value).items():
            yield Step("attr", name), item
        if value.model_extra:
            yield Step("attr", "__pydantic_extra__"), value.model_extra
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) not in (str, int):
                raise UnsupportedEdit("Mapping keys other than str/int require an explicit adapter")
            yield Step("item", key), item
    elif type(value) in (tuple, list):
        for index, item in enumerate(value):
            yield Step("item", index), item


def is_container(value: Any) -> bool:
    return isinstance(value, BaseModel) or type(value) in (dict, list, tuple)


class NativeAdapter:
    def __init__(self, provider: str, editor: Editor) -> None:
        self.provider = provider
        self.editor = editor

    def extract(self, payload: Any) -> tuple[Slot, ...]:
        result: list[Slot] = []
        seen: set[int] = set()
        active: set[int] = set()

        def visit(value: Any, path: Path) -> None:
            category, editable, note = classify(self.provider, payload, path, value)
            if not is_container(value):
                scalar = type(value) in (str, bytes, bool, int, float)
                result.append(
                    Slot(
                        path,
                        category,
                        value,
                        editable and scalar,
                        note or ("opaque" if not scalar and value is not None else ""),
                    )
                )
                return
            if id(value) in active or (type(value) is not tuple and id(value) in seen):
                reason = "cycle" if id(value) in active else "shared_reference"
                result.append(Slot(path, category, value, False, reason))
                return
            # Reusing an immutable tuple does not alias a mutable editing target.
            # Shared mutable descendants are still detected when traversed.
            if type(value) is not tuple:
                seen.add(id(value))
            active.add(id(value))
            try:
                members = list(children(value))
            except UnsupportedEdit as exc:
                result.append(Slot(path, "unknown", value, False, str(exc)))
            else:
                if not members:
                    result.append(Slot(path, category, value, False, "empty_container"))
                for step, item in members:
                    visit(item, (*path, step))
                if isinstance(value, BaseModel) and value.__pydantic_private__:
                    result.append(
                        Slot(
                            (*path, Step("attr", "__pydantic_private__")),
                            "unknown",
                            value.__pydantic_private__,
                            False,
                            "private_state",
                        )
                    )
            active.remove(id(value))

        visit(payload, ())
        return tuple(result)

    def apply(self, payload: Any, patches: list[Patch]) -> Any:
        if not patches:
            return payload
        slots = self.extract(payload)
        if any(slot.note in ("cycle", "shared_reference") for slot in slots):
            raise UnsupportedEdit("Editing shared/cyclic graphs requires an alias-aware policy")
        allowed = {slot.path: slot for slot in slots}
        requested: set[Path] = set()
        changes: list[Patch] = []
        for patch in patches:
            current = allowed.get(patch.slot.path)
            if current is None or not current.editable:
                raise UnsupportedEdit("Path was not extracted as an editable leaf")
            if patch.slot.path in requested:
                raise UnsupportedEdit("Duplicate edit path")
            requested.add(patch.slot.path)
            if type(current.value) is not type(patch.slot.value) or current.value != patch.slot.value:
                raise UnsupportedEdit("Stale extracted value")
            if type(patch.replacement) is not type(current.value):
                raise UnsupportedEdit("Replacement must retain the native leaf type")
            if current.note == "json_text":
                json.loads(patch.replacement)  # Validate only; retain the exact supplied string.
            if patch.replacement != current.value:
                changes.append(patch)
        updated = payload
        for patch in changes:
            updated = self.editor.set(updated, patch.slot.path, patch.replacement)
        return updated


# These narrow intervals are experiment coverage, NOT claims of major-version
# compatibility. Extend only after running this probe at the new endpoints.
ADAPTER_RANGES = {
    "openai": [("==2.54.0", NativeAdapter)],
    "anthropic": [("==1.4.0", NativeAdapter)],
    "litellm": [("==1.99.0", NativeAdapter)],
    "langchain-core": [("==1.6.2", NativeAdapter)],
}


def select_adapter(provider: str, editor: Editor, *, installed_version: str | None = None) -> NativeAdapter:
    actual = Version(installed_version if installed_version is not None else version(provider))
    matches = [factory for interval, factory in ADAPTER_RANGES.get(provider, ()) if actual in SpecifierSet(interval)]
    if len(matches) != 1:
        raise UnsupportedEdit(f"Expected one compatible adapter for {provider} {actual}; found {len(matches)}")
    return matches[0](provider, editor)
