"""Thin native-library editors for comparison, not a universal copy guarantee.

No serialization or custom reconstruction is used. Library/copy exceptions pass
through unchanged. The driver must check preservation and unchanged-source
invariants: arbitrary object copy hooks, descriptors and SDK setters can violate
those invariants even when a library operation succeeds.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .core import Editor, Path

EDITOR_NAMES = ("glom-copy", "lenses")

SOURCES = {
    "glom-copy": (
        "https://glom.readthedocs.io/en/latest/api.html#glom.T",
        "https://glom.readthedocs.io/en/latest/api.html#glom.Val",
        "https://glom.readthedocs.io/en/latest/mutation.html#glom.Assign",
        "https://docs.python.org/3/library/copy.html",
    ),
    "lenses": (
        "https://python-lenses.readthedocs.io/en/latest/api.html",
        "https://github.com/ingolemo/python-lenses/blob/master/lenses/ui/base.py",
        "https://github.com/ingolemo/python-lenses/blob/master/lenses/hooks/hook_funcs.py",
    ),
}

COPY_POLICY = {
    "glom-copy": (
        "deepcopy(root) for every set, then native glom Assign on that candidate. "
        "Copies unrelated branches and may change opaque-object identity or fail "
        "on file handles; custom deepcopy hooks can defeat isolation. Aliases "
        "within the copy remain aliases, so one mutation can affect another path. "
        "Native Assign cannot replace tuple items or an empty/root path. "
        "Replacement values are literal, not copied or evaluated as glom specs."
    ),
    "lenses": (
        "Native functional set reconstructs changed ancestors through lenses "
        "hooks, normally copy.copy plus setitem/setattr; untouched branches and "
        "replacement values remain shared. This is not a fully detached clone. "
        "Custom copy/setter hooks and SDK metadata need preservation checks. "
        "Tuple item reconstruction uses plain tuple (subclass identity can be "
        "lost); dataclass attribute reconstruction uses dataclasses.replace. "
        "No global hooks are registered or patched."
    ),
}


class GlomCopyEditor:
    name = "glom-copy"

    def __init__(self) -> None:
        import glom

        self._glom = glom

    def _path(self, path: Path) -> Any:
        expression = self._glom.T
        for step in path:
            if step.kind == "item":
                expression = expression[step.key]
            elif isinstance(step.key, str) and step.key.startswith("__"):
                # Documented escape for T's reserved double-underscore names.
                expression = expression.__(step.key[2:])
            else:
                expression = getattr(expression, step.key)
        return expression

    def get(self, root: Any, path: Path) -> Any:
        return self._glom.glom(root, self._path(path))

    def set(self, root: Any, path: Path, value: Any) -> Any:
        assignment = self._glom.Assign(self._path(path), self._glom.Val(value))
        return self._glom.glom(deepcopy(root), assignment)


class LensesEditor:
    name = "lenses"

    def __init__(self) -> None:
        from lenses import lens

        self._lens = lens

    def _path(self, path: Path) -> Any:
        focus = self._lens
        for step in path:
            # Explicit GetAttr avoids collisions with get/set/GetAttr/etc.
            focus = focus.GetItem(step.key) if step.kind == "item" else focus.GetAttr(step.key)
        return focus

    def get(self, root: Any, path: Path) -> Any:
        return self._path(path).get()(root)

    def set(self, root: Any, path: Path, value: Any) -> Any:
        return self._path(path).set(value)(root)


def make_editor(name: str) -> Editor:
    if name == "glom-copy":
        return GlomCopyEditor()
    if name == "lenses":
        return LensesEditor()
    raise ValueError(f"Unknown editor {name!r}; expected one of {EDITOR_NAMES!r}")
