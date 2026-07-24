# Privacy Router Research Excalidraw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce three readable Excalidraw research maps—research story, system pipeline, and claim–evidence traceability—through the configured Excalidraw MCP.

**Architecture:** Build each board as a deterministic array of Excalidraw drawable elements plus MCP-only `cameraUpdate` elements. Render through MCP `create_view`, save drawable elements inside standard `.excalidraw` document envelopes, export each document through `export_to_excalidraw`, and verify the share URLs in Chromium.

**Tech Stack:** Excalidraw MCP at `https://mcp.excalidraw.com/mcp`, MCP 2025-06-18 Streamable HTTP, Excalidraw JSON, Chromium browser verification.

## Global Constraints

- Use Korean copy with established English terms such as benchmark, leakage, utility, and egress.
- Every board must show `GO_TO_PILOT (8/10) — 논문 결과가 확립된 상태는 아님`.
- Colors: `#a5d8ff` facts/structure, `#d0bfff` methods/system, `#b2f2bb` verified evidence, `#ffd8a8` planned, `#ffc9c9` blockers.
- Body text is at least 16px; headings are at least 20px; panorama text is at least 21px where possible.
- Start every MCP element array with a valid 4:3 `cameraUpdate`; finish with a 1600×1200 overview camera.
- Standard `.excalidraw` files contain drawable elements only; omit MCP pseudo-elements.
- Do not modify `.mcp.json`: the global Excalidraw MCP endpoint is configured and has passed `initialize`, `tools/list`, and `read_me`.
- Do not add unsupported results or claim novelty before G0/G1.
- Do not make intermediate commits; preserve the repository’s squash-first convention.

---

### Task 1: Research Story Board

**Files:**
- Create: `refine-logs/visual/privacy-router-research-story.excalidraw`
- Read: `refine-logs/FINAL_PROPOSAL.md`
- Read: `refine-logs/REVIEW_SUMMARY.md`
- Read: `refine-logs/EXPERIMENT_TRACKER.md`

**Interfaces:**
- Consumes: approved visual design and Excalidraw MCP element format.
- Produces: `storyElements: ExcalidrawElement[]`, a rendered checkpoint, and a standard Excalidraw document.

- [ ] **Step 1: Build the fixed content graph**

Create cards with IDs `story_problem`, `story_gap`, `story_contribution`, `story_reference`, `story_claims`, `story_validation`, `story_venue`, and `story_verdict`. Connect them left-to-right. Add a bottom G0–G6 progress rail and four immediate-action cards: full-text audit, P0/schema freeze, 20–30 scenario pilot, and power/budget analysis.

- [ ] **Step 2: Add explanation and status controls**

Add standalone cards `story_intent`, `story_reading`, `story_legend`, and `story_sources`. Label planned and blocked nodes in text, not only by color. Keep the benchmark contribution visually separate from Privacy Router as a reference implementation.

- [ ] **Step 3: Render through Excalidraw MCP**

Call `tools/call` with `name=create_view` and `arguments.elements=JSON.stringify(storyElementsWithCamera)`. Require `isError !== true` and capture the returned checkpoint ID or app resource.

- [ ] **Step 4: Save and validate the local document**

Write this envelope with drawable elements only:

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://mcp.excalidraw.com",
  "elements": [],
  "appState": {"viewBackgroundColor": "#ffffff", "gridSize": null},
  "files": {}
}
```

Parse the file and assert that all 8 main card IDs, `story_intent`, the status sentence, and G0–G6 occur exactly once.

---

### Task 2: System Pipeline Board

**Files:**
- Create: `refine-logs/visual/privacy-router-system-pipeline.excalidraw`
- Read: `refine-logs/FINAL_PROPOSAL.md`
- Read: `refine-logs/EXPERIMENT_PLAN.md`

**Interfaces:**
- Consumes: policy ontology, model-input separation rule, and leakage metrics from the approved research artifacts.
- Produces: `pipelineElements: ExcalidrawElement[]`, a rendered checkpoint, and a standard Excalidraw document.

- [ ] **Step 1: Draw the two-lane data flow**

Use a top `MODEL-VISIBLE` lane and a bottom `EVALUATOR-ONLY` lane. In the top lane draw candidate egress → Extractor → factual factors → frozen P0 → transformation → route → serialized egress. In the lower lane draw gold spans/atoms → acceptable actions → leakage/utility scorer.

- [ ] **Step 2: Draw trust and decision boundaries**

Add a red dashed trust boundary before external model/tool transmission. Show transformation actions `allow` and `mask/rewrite`; show route actions `approved external`, `local`, `ask`, and `deny`. Add a red rule card: `model_input 외 gold field 포함 시 실행 거부`.

- [ ] **Step 3: Add outcomes and diagnostics**

Add literal/atom/derived leakage, recipient-specific exposure, task success, and latency/cost. Add an oracle strip: span oracle, factor oracle, policy oracle, route-matched, oracle-route. Include design intent, reading order, legend, and source cards.

- [ ] **Step 4: Render and validate**

Render with MCP `create_view`, save drawable elements to the local envelope, parse the file, and assert that both lanes, the trust boundary, all six action labels, all leakage levels, and the status sentence are present.

---

### Task 3: Claim–Evidence Board

**Files:**
- Create: `refine-logs/visual/privacy-router-claim-evidence.excalidraw`
- Read: `refine-logs/EXPERIMENT_PLAN.md`
- Read: `refine-logs/EXPERIMENT_TRACKER.md`
- Read: `refine-logs/PIPELINE_SUMMARY.md`

**Interfaces:**
- Consumes: C1–C7 claim matrix, E0-P/E0-F/E1/E2–E7 experiments, and G0–G6 gates.
- Produces: `claimElements: ExcalidrawElement[]`, a rendered checkpoint, and a standard Excalidraw document.

- [ ] **Step 1: Draw the foundation rail**

Place E0-P pilot validity, E0-F full-dataset validation, and E1 known-answer sanity on the left. Connect them as prerequisites rather than paper evidence.

- [ ] **Step 2: Draw seven compact claim lanes**

Each C1–C7 lane must show `Claim → Experiment → Metric/pass rule → Current status/fallback`. Use the exact rules from the spec: matched safe-FPR and cluster CI for C1; conditional diagnostics without causal attribution for C2; intersection–union for C3; shared-threshold gap for C4; AURC/eventual completion for C5; reliability plus upper failure bound for C6; decomposed efficiency for C7.

- [ ] **Step 3: Add blockers and evidence disclaimer**

Add G0, G1, G3, and G4 as common blockers. Mark every C1–C7 lane `NO PAPER EVIDENCE`; mark C6 unit tests only as `implementation property`. Include design intent, reading order, legend, and sources.

- [ ] **Step 4: Render and validate**

Render with MCP `create_view`, save the standard local document, parse it, and assert unique presence of C1–C7, E0-P/E0-F/E1/E2-D/E2-T/E3/E4/E5/E6/E7, G0/G1/G3/G4, and the evidence disclaimer.

---

### Task 4: Export and Visual Acceptance

**Files:**
- Verify: `refine-logs/visual/privacy-router-research-story.excalidraw`
- Verify: `refine-logs/visual/privacy-router-system-pipeline.excalidraw`
- Verify: `refine-logs/visual/privacy-router-claim-evidence.excalidraw`

**Interfaces:**
- Consumes: three validated Excalidraw documents.
- Produces: three share URLs and browser-observed acceptance evidence.

- [ ] **Step 1: Export each document through MCP**

Call `tools/call` with `name=export_to_excalidraw` and `arguments.json=JSON.stringify(document)`. Require three non-empty `https://` URLs. If an export fails, retain the local file and report that URL independently as failed.

- [ ] **Step 2: Open each share URL in Chromium**

Use a 1440×900 viewport. For each board, verify the title, status warning, main flow, explanation card, reading order, and legend. Use screenshots only to inspect appearance; do not add them as repository artifacts.

- [ ] **Step 3: Correct only observed layout defects**

If text is clipped or cards overlap, increase the affected card’s width/height or line spacing and rerun `create_view` and export for that board. Do not redesign unaffected boards.

- [ ] **Step 4: Run final structural checks**

Parse all three files; verify unique element IDs, no `cameraUpdate` in local files, no font below 14px, all labels use the approved palette, and every expected title/status phrase exists. Report local paths, share URLs, and observed browser results.
