"""Independent native-state observer; never feeds reconstructed data to editors."""

from __future__ import annotations

import struct
from typing import Any

from pydantic import BaseModel

from .core import Path, Step, path_label


def scalar_record(value: Any) -> tuple[Any, ...]:
    if type(value) is float:
        return (type(value), struct.pack("!d", value))
    if type(value) in (str, bytes, int, bool, type(None)):
        return (type(value), value)
    return (type(value), "opaque_identity", id(value))


def capture(root: Any) -> dict[Path, tuple[Any, ...]]:
    """Observe types, key order, presence, references and private state directly."""
    result: dict[Path, tuple[Any, ...]] = {}
    seen: dict[int, Path] = {}

    def walk(value: Any, path: Path) -> None:
        is_model = isinstance(value, BaseModel)
        if is_model or type(value) in (dict, list):
            if id(value) in seen:
                result[path] = (type(value), "reference", seen[id(value)])
                return
            seen[id(value)] = path
        if is_model:
            result[path] = (
                type(value),
                "model",
                tuple(vars(value)),
                frozenset(value.model_fields_set),
                tuple(type(value).model_fields),
            )
            for key, item in vars(value).items():
                walk(item, (*path, Step("attr", key)))
            # Unlike extraction, observation covers empty/None metadata too.
            walk(value.__pydantic_extra__, (*path, Step("attr", "__pydantic_extra__")))
            walk(value.__pydantic_private__, (*path, Step("attr", "__pydantic_private__")))
        elif type(value) is dict:
            result[path] = (type(value), "mapping", tuple((type(key), key) for key in value))
            for key, item in value.items():
                walk(item, (*path, Step("item", key)))
        elif type(value) in (tuple, list):
            result[path] = (type(value), "sequence", len(value))
            for index, item in enumerate(value):
                walk(item, (*path, Step("item", index)))
        else:
            result[path] = scalar_record(value)

    walk(root, ())
    return result


def expected_changes(before: dict, edits: dict[Path, Any]) -> dict:
    expected = before.copy()
    for path, replacement in edits.items():
        expected[path] = scalar_record(replacement)
        for index, step in enumerate(path):
            parent = path[:index]
            record = expected.get(parent)
            if record and len(record) == 5 and record[1] == "model" and step.kind == "attr" and step.key in record[4]:
                expected[parent] = (*record[:3], record[3] | {step.key}, record[4])
    return expected


def different_paths(expected: dict, actual: dict) -> list[str]:
    missing = object()
    return sorted(
        path_label(path)
        for path in expected.keys() | actual.keys()
        if expected.get(path, missing) != actual.get(path, missing)
    )
