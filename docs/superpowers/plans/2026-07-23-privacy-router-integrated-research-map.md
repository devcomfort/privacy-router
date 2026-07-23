# Privacy Router Complete Research Map Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the integrated Excalidraw board so every text item from the three source boards appears, every technical term is explained in plain Korean, and every card uses grammatical complete sentences.

**Architecture:** Treat the three source boards as immutable inputs and build a 106-item coverage map from their text element IDs. Reconstruct the integrated board as six vertical chapters instead of scaling and copying the old cards: overview, research story, system pipeline, claims and evidence, research gates, and glossary/sources. Validate source-to-target coverage, wording, geometry, MCP rendering, and browser readability before replacing the share URL.

**Tech Stack:** Excalidraw JSON v2, Python JSON transformation in the execution kernel, official Excalidraw MCP `create_view` and `export_to_excalidraw`, Firefox WebDriver fallback on ARM64.

## Global Constraints

- Modify only `refine-logs/visual/privacy-router-integrated-research-map.excalidraw`; preserve all three source boards byte-for-byte.
- The source coverage denominator is exactly 106 text elements: research story 28, system pipeline 23, claim–evidence 55.
- Include source titles, subtitles, status notices, body cards, reading instructions, legends, and source references; do not filter repeated metadata.
- Use plain Korean first. Show a standard English term in parentheses only at its first occurrence.
- Every main card follows `무엇인가 → 왜 필요한가 → 어떻게 확인하는가`; pipeline cards use `입력 → 처리 → 출력 → 실패 시 동작`.
- Preserve every experiment ID, gate ID, threshold, venue, evidence state, and failure fallback exactly.
- Keep `GO_TO_PILOT (8/10) — 논문 결과가 확립된 상태는 아님` and `NO PAPER EVIDENCE` as explicit status labels.
- Body copy is at least 18px, secondary explanations at least 16px, chapter headings 26–30px, and the document title at least 34px.
- Use blue for facts/structure, purple for methods/system, orange for plans/pass rules, green for implementation evidence/fallback/actions, and red for blockers/trust boundaries/no paper evidence.
- Standard `.excalidraw` files contain drawable elements only; `cameraUpdate` remains MCP-only.
- Preserve the squash-first convention; create no intermediate implementation commits.

---

### Task 1: Build the Complete Source-Coverage and Wording Catalog

**Files:**
- Read: `refine-logs/visual/privacy-router-research-story.excalidraw`
- Read: `refine-logs/visual/privacy-router-system-pipeline.excalidraw`
- Read: `refine-logs/visual/privacy-router-claim-evidence.excalidraw`
- Read: `docs/superpowers/specs/2026-07-23-privacy-router-integrated-research-map-design.md`
- Modify later: `refine-logs/visual/privacy-router-integrated-research-map.excalidraw`

**Interfaces:**
- Consumes: three immutable Excalidraw v2 documents.
- Produces: `source_texts: dict[str, list[tuple[str, str]]]`, `plain_copy: dict[str, str]`, and `coverage_map: dict[str, list[str]]` in the execution kernel.

- [ ] **Step 1: Parse and fingerprint all source boards**

Load the three documents, reject pseudo-elements or duplicate IDs, and save each file's SHA-256 before rewriting the target.

```python
source_paths = [
    Path("refine-logs/visual/privacy-router-research-story.excalidraw"),
    Path("refine-logs/visual/privacy-router-system-pipeline.excalidraw"),
    Path("refine-logs/visual/privacy-router-claim-evidence.excalidraw"),
]
source_docs = {path.name: json.loads(path.read_text()) for path in source_paths}
source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
for name, doc in source_docs.items():
    ids = [element["id"] for element in doc["elements"]]
    assert doc["type"] == "excalidraw" and doc["version"] == 2
    assert len(ids) == len(set(ids))
    assert not any(element["type"] in {"cameraUpdate", "delete", "restoreCheckpoint"} for element in doc["elements"])
```

- [ ] **Step 2: Create the 106-item text inventory**

Prefix source IDs with the board name so repeated IDs cannot collide. Assert the required per-board and total counts before composing any target element.

```python
source_texts = {
    name: [(element["id"], element.get("text", "").strip())
           for element in doc["elements"]
           if element.get("type") == "text" and element.get("text", "").strip()]
    for name, doc in source_docs.items()
}
assert {name: len(items) for name, items in source_texts.items()} == {
    "privacy-router-research-story.excalidraw": 28,
    "privacy-router-system-pipeline.excalidraw": 23,
    "privacy-router-claim-evidence.excalidraw": 55,
}
assert sum(map(len, source_texts.values())) == 106
```

- [ ] **Step 3: Rewrite each source item as plain, complete Korean**

Create one `plain_copy` entry for every prefixed source ID. Preserve identifiers and numbers but replace mixed fragments using this fixed vocabulary:

| Source wording | Board wording |
|---|---|
| candidate egress | 외부로 보내기 직전의 내용(외부 전송 후보) |
| egress decision / action | 외부 전송 여부와 처리 방식 |
| exact span | 원문에서 민감 정보가 차지하는 정확한 문자 범위 |
| raw value | 가리지 않은 원문 값 |
| lifecycle | 정보의 공개·승인·만료 상태 변화 |
| recipient / purpose | 수신자 / 사용 목적 |
| controlled intervention | 한 번에 한 조건만 바꾸는 통제 실험 |
| paired benchmark | 같은 상황을 조건별로 짝지은 비교 데이터셋 |
| policy compliance | 사전에 정한 정책을 올바르게 따른 비율 |
| serialized egress bytes | 네트워크 요청으로 변환되어 실제로 외부에 전달되는 내용 |
| trust boundary | 이 선을 넘으면 외부 시스템의 통제 아래 놓이는 경계 |
| fail-closed | 규칙 위반이나 불확실성이 있으면 전송하지 않고 실행을 중단하는 방식 |
| gold labels | 평가에만 쓰는 정답 표시 |
| oracle diagnostics | 한 단계를 완벽한 정답으로 바꾸어 오류가 생긴 위치를 찾는 진단 |
| utility | 보호 처리 뒤에도 사용자의 작업을 성공적으로 마칠 수 있는 정도 |
| safe-FPR | 안전한 내용을 민감하다고 잘못 판단한 비율 |
| confidence interval | 반복 표본에서 실제 효과가 있을 범위를 추정한 구간 |
| non-inferiority | 기준보다 정해진 허용치 이상 나빠지지 않았다는 조건 |
| failure fallback | 기준을 못 맞췄을 때 논문 주장을 줄이는 방법 |

For each card, replace noun-only lines with complete sentences. For example, replace `G0 BLOCKED / Novelty audit / 동등 artifact 없음` with `G0은 현재 막혀 있습니다. 관련 논문과 공개 산출물을 전문까지 조사하여 같은 데이터셋이나 평가 체계가 없음을 확인해야 통과합니다.`

- [ ] **Step 4: Build a strict source-to-target coverage map**

Each source text ID must map to at least one new target text ID. One target may explain more than one source item, but the source title, status, reading order, legend, and sources each keep a distinct target.

```python
coverage_map = {}
def cover(board_name: str, source_id: str, *target_ids: str) -> None:
    key = f"{board_name}:{source_id}"
    if not target_ids:
        raise ValueError(f"No target for {key}")
    coverage_map[key] = list(target_ids)
```

- [ ] **Step 5: Verify the catalog before layout work**

Assert that all 106 source keys exist in both `plain_copy` and `coverage_map`. Scan rewritten copy for unexplained mixed fragments and sentence-ending omissions.

```python
source_keys = {
    f"{board}:{element_id}"
    for board, items in source_texts.items()
    for element_id, _ in items
}
assert source_keys == set(plain_copy)
assert source_keys == set(coverage_map)
assert all(text.rstrip().endswith((".", "?", ")", "]", "함", "아님", "BLOCKED", "EVIDENCE"))
           for text in plain_copy.values())
```

Expected: `106/106 covered, 0 missing` plus the three unchanged source hashes.

---

### Task 2: Reconstruct the Six-Chapter Excalidraw Board

**Files:**
- Modify: `refine-logs/visual/privacy-router-integrated-research-map.excalidraw`

**Interfaces:**
- Consumes: `plain_copy`, `coverage_map`, source experiment/gate IDs, and approved design rules.
- Produces: `integrated_document: dict` with sections `integrated_overview`, `integrated_story`, `integrated_pipeline`, `integrated_claims`, `integrated_gates`, and `integrated_glossary`.

- [ ] **Step 1: Define deterministic element helpers**

Use rectangles, text, and arrows with stable IDs. Compute text height from explicit line count; never shrink copy to fit.

```python
def text_height(text: str, font_size: int, line_height: float = 1.25) -> int:
    return math.ceil(len(text.splitlines()) * font_size * line_height)

def card(card_id: str, x: int, y: int, width: int, text: str,
         fill: str, stroke: str, font_size: int = 18) -> list[dict]:
    padding = 18
    height = max(90, text_height(text, font_size) + padding * 2)
    return [
        make_rectangle(card_id, x, y, width, height, fill, stroke),
        make_text(f"{card_id}_text", x + padding, y + padding, text, font_size, width - padding * 2),
    ]
```

- [ ] **Step 2: Build the overview and five chapter-navigation cards**

The overview states the research question, candidate contribution, current evidence limit, and reading order in full sentences. Add navigation cards for research story, system pipeline, claims/evidence, research gates, and glossary/sources.

- [ ] **Step 3: Build Chapter 1 — Research Story**

Retain all 28 source items. Present the eight original stages in reading order. Under each stage, add three labeled sentences: `핵심 내용`, `왜 필요한가`, and `어떻게 확인하는가`. Keep the original status, gate strip, four immediate actions, reading order, color legend, and source list in this chapter rather than moving or deleting them.

- [ ] **Step 4: Build Chapter 2 — System Pipeline**

Retain all 23 source items. Keep separate lanes titled `모델이 실제로 보는 영역(MODEL-VISIBLE)` and `평가에만 쓰는 영역(EVALUATOR-ONLY)`. For each of the seven model-visible stages show `입력`, `처리`, `출력`, and `실패 시 동작`. Explain the red trust boundary and fail-closed rule with complete sentences. Connect only the actual transmitted content to the scorer; never draw gold data flowing into the model request.

- [ ] **Step 5: Build Chapter 3 — Claims and Evidence**

Retain all 55 source items. Replace the compressed wide matrix with seven stacked C1–C7 panels. Each panel contains five blocks:

1. `이 주장이 묻는 것`
2. `필요한 실험`
3. `통과 기준과 그 뜻`
4. `현재 근거 상태`
5. `기준을 못 맞췄을 때 줄일 주장`

Keep E0-P, E0-F, E1, G0, G1, G3, and G4 above the panels as shared prerequisites. Preserve every numerical threshold and `NO PAPER EVIDENCE` label.

- [ ] **Step 6: Build Chapter 4 — Research Gates and Immediate Actions**

Create G0–G6 as seven full cards. Every card states `목적`, `통과 조건`, `필요한 산출물`, and `지금 할 일`. Show all gates as `BLOCKED`. Reproduce the four source actions: full-text audit, P0/schema freeze, validity pilot, and power/budget analysis, with Korean explanations and the gate each action can open.

- [ ] **Step 7: Build Chapter 5 — Glossary and Sources**

Include all terms from Task 1 Step 3 plus the meanings of E0-P, E0-F, E1, C1–C7, and G0–G6. Add the three source-board names and five evidence documents. State that the glossary explains existing terms and does not introduce a new method, metric, or result.

- [ ] **Step 8: Save the standard Excalidraw document**

Use one standard document envelope with overview-first app state:

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://mcp.excalidraw.com",
  "elements": [],
  "appState": {
    "viewBackgroundColor": "#ffffff",
    "gridSize": null,
    "zoom": {"value": 0.72},
    "scrollX": 60,
    "scrollY": 100
  },
  "files": {}
}
```

- [ ] **Step 9: Run structural and content validation**

Parse the saved target and assert unique IDs, no pseudo-elements, all six section IDs, minimum fonts, all C1–C7/E0-P/E0-F/E1/G0–G6 labels, every numerical threshold, and 106/106 coverage. Recalculate the source hashes and require exact equality with Task 1.

Expected output includes target element/text counts, minimum font, canvas bounds, `coverage=106/106`, `missing=0`, and `sources_unchanged=true`.

---

### Task 3: Render, Export, and Visually Verify the Complete Board

**Files:**
- Verify: `refine-logs/visual/privacy-router-integrated-research-map.excalidraw`
- Preserve: the three source `.excalidraw` files

**Interfaces:**
- Consumes: validated `integrated_document`.
- Produces: one MCP checkpoint ID, one `https://excalidraw.com/#json=...` share URL, and browser-observed acceptance evidence.

- [ ] **Step 1: Render through the official Excalidraw MCP**

Call `mcp__excalidraw_read_me` only if it has not already been called in the execution session. Pass drawable elements to `create_view` and require a checkpoint ID. Use MCP-only 1600×1200 camera positions for the overview and each chapter.

- [ ] **Step 2: Export one replacement share URL**

Call `export_to_excalidraw` with the full standard document JSON. Require a non-empty URL beginning with `https://excalidraw.com/#json=`. If export fails, retry the MCP session once while preserving the local file.

- [ ] **Step 3: Open the URL in a real 1600×1200 browser**

Use the Chromium device when available; otherwise use Firefox WebDriver. Verify the overview loads without a replacement dialog and shows the title, research question, `GO_TO_PILOT`, evidence warning, and five chapter links.

- [ ] **Step 4: Inspect every chapter at a readable zoom**

Scroll to all five chapters and verify: no clipped text, no overlapping cards, no arrows crossing text, body copy readable at 18px, secondary copy readable at 16px, and red status labels repeated in words. Capture temporary screenshots for each chapter and delete them after inspection.

- [ ] **Step 5: Correct only observed visual defects**

Increase card height, line breaks, gaps, or chapter height when copy is clipped. Do not lower font sizes. Rebuild, re-render, and re-export if any document element changes.

- [ ] **Step 6: Repeat final checks and report**

Repeat Task 2 Step 9 against the final file, remove temporary screenshots, and close the temporary browser session. Report the local path, new share URL, MCP render result, browser result, structural counts, minimum font, and `106/106` coverage. Do not repeat the full board copy in chat.
