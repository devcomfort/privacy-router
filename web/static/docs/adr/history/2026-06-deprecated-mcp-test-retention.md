---
type: historical-note
topic: Retain the deprecated MCP test file as a reference
status: closed
claimed_date: 2026-06-16
recorded: 2026-07-16
date_basis:
  - The earlier record claims 2026-06-16.
  - Git verifies the file lifecycle independently of that claimed date.
evidence:
  - kind: historical
    revision: d3c80c1b
    path: server/tests/test_mcp_tools.py
  - kind: historical
    revision: 94c3f97a
    path: server/tests/test_mcp_tools.py
  - kind: deletion
    revision: ccb32569
    path: server/tests/test_mcp_tools.py
  - kind: historical
    revision: ccb32569
    path: docs/dev/adr/ADR-004-keep-deprecated-test-mcp-tools.md
  - kind: current
    path: tests/scenarios/test_mcp_process.py
  - kind: current
    path: server/tests/test_mcp_lightweight.py
---

# Historical Note: Retain the Deprecated MCP Test File as a Reference

## Why this is not an ADR

The earlier ADR-004 concerned whether an intentionally broken test module should remain in the active test tree as historical reference. That is a repository-maintenance policy, not an architecture boundary or runtime decision. It is preserved here because its rationale and risk analysis explain a real cleanup choice, but it receives no ADR number.

## Context Preserved from the Earlier Record

`server/tests/test_mcp_tools.py` tested older MCP operations such as `classify`, `route`, `generate`, `list_models`, `set_model`, and `list_providers`. Those operations were consolidated into the current MCP workflow. The deprecated test imported symbols that no longer existed, so collecting it under the active suite could fail before any test ran.

The file header stated that it was retained for reference and would not pass against current code. Rewriting it for the consolidated process flow would duplicate coverage in `tests/scenarios/test_mcp_process.py`.

## Earlier Decision

Keep the broken deprecated file unchanged instead of rewriting or deleting it.

The earlier record gave four reasons:

1. **Historical reference:** preserve the old per-tool contracts and test patterns.
2. **Avoid duplicated effort:** current consolidated MCP tests already cover the supported surface.
3. **Prioritize current work:** do not spend engineering time reviving removed APIs.
4. **Explicit deprecation signal:** a visibly broken file makes removal of the old tools unambiguous.

## Consequences Recorded at the Time

### Positive

- Preserved a local record of old MCP contracts and expected behavior.
- Avoided duplicate maintenance for removed functionality.
- Signaled to contributors that the old tools were no longer supported.

### Negative

- `pytest server/tests/` could fail during collection unless the file was excluded.
- New contributors could mistake intentional breakage for an active regression.
- Static analysis and coverage tools could report noise.
- Keeping a broken test in an active test tree normalized an exception to the repository's quality rules.

## Risks Recorded at the Time

| Risk | Likelihood | Impact | Earlier mitigation |
|---|---:|---:|---|
| CI collects the deprecated file and fails | High if not excluded | Medium | Add an ignore rule or move the file outside the test tree. |
| Maintainers cannot tell whether to fix it | Medium | Low | Keep a prominent deprecation header and link the rationale. |
| The reference becomes stale as current MCP behavior evolves | Medium | Low | Review it periodically and delete it after the consolidated tool stabilizes. |
| Broken-window effect encourages more skipped or broken tests | Low | Medium | Restrict exceptions to reference material and enforce active-test health in review. |

## Repository History Correction

Git provides a clearer lifecycle than the claimed 2026-06-16 decision date:

- `d3c80c1b` adds `server/tests/test_mcp_tools.py` on 2026-06-08.
- `94c3f97a` marks it deprecated on 2026-06-09.
- `ccb32569` deletes `server/tests/test_mcp_tools.py` on 2026-07-16 and records the old ADR in the same commit.
- The post-commit tree and current working tree do not contain the deprecated test path.
- Current MCP coverage lives in `tests/scenarios/test_mcp_process.py` and `server/tests/test_mcp_lightweight.py`.

The earlier “keep it broken in the active test tree” policy therefore did not remain the repository's effective state.

## Final Disposition

- Preserve history in Git and this note, not as a non-collectable test module.
- Keep only tests for the supported MCP surface in active test directories.
- Do not attribute this maintenance cleanup to ADR-003; it predates the 2026-07-21–22 architecture hardening package.
