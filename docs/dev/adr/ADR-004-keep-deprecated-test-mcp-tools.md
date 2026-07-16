# ADR-004: Keep Deprecated `test_mcp_tools.py` Unchanged

## Date

2026-06-16

## Status

Accepted

## Context

The file `server/tests/test_mcp_tools.py` contains tests for older MCP tools such as `classify`, `route`, `generate`, `list_models`, `set_model`, and `list_providers`. The file header explicitly states:

> [DEPRECATED] Tests for old MCP tools (classify, route, generate, etc.). These tools were consolidated into a single `process` tool. See `tests/scenarios/test_mcp_process.py` for the current tests. This file is kept for reference only — it will NOT pass against current code.

The imports at the top of the file reference symbols that no longer exist in `server.mcp.tools` (e.g., `classify`, `route`, `generate`), so the test module cannot even be collected by `pytest` without failing. Refactoring it to use the new `process` tool would duplicate the coverage already provided by `tests/scenarios/test_mcp_process.py`.

## Decision

Keep `server/tests/test_mcp_tools.py` in the repository in its current broken/deprecated state and do not refactor it to pass against the current codebase.

Rationale:

1. **Historical reference**: The file documents the original per-tool API and the test patterns that were used before consolidation. This can help future maintainers understand why the `process` tool was introduced.
2. **Avoid duplicated effort**: The consolidated `process` tool already has dedicated scenario tests; rewriting the old tests would not increase meaningful coverage.
3. **Prioritize feature work**: Engineering time is better spent on the current MCP surface and production features than on resurrecting tests for removed tools.
4. **Explicit deprecation signal**: A failing deprecated test file is an unambiguous signal that the underlying tools are gone, which is preferable to silently deleting the file and losing context.

## Consequences

Positive:

- Preserves a record of the old MCP tool contracts and expected behaviors.
- Avoids redundant test maintenance for functionality that no longer exists.
- Signals clearly to contributors that the tools are deprecated.

Negative:

- Running `pytest server/tests/` without excluding the file will fail collection, which can break CI or local test runs if not configured.
- New contributors may be confused by a checked-in file that is intentionally non-functional.
- Static analysis and coverage tools may flag the file as an issue.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CI failure if the deprecated file is collected by `pytest` | High if not excluded | Medium | Add `server/tests/test_mcp_tools.py` to `pytest.ini`/`pyproject.toml` ignore list, or move it to a non-test directory such as `docs/legacy/`. |
| Maintainer confusion about whether the file should be fixed | Medium | Low | Keep the deprecation header visible; add a link to this ADR in the file docstring. |
| Stale reference becoming misleading as the codebase evolves | Medium | Low | Periodically review deprecated files during release planning; delete the file once the consolidated `process` tool has been stable for several releases. |
| "Broken window" effect encouraging other skipped tests | Low | Medium | Document the policy (reference files are allowed to be broken; active tests are not) and enforce it in code review. |
