# Query Aggregation Before/After Diagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bilingual, abstract Before/After diagram that makes the current implicit query decision and the target explicit `QueryDecisionSummary` boundary immediately comparable.

**Architecture:** The existing standalone roadmap remains one dependency-free HTML file. Each locale-specific Executive conclusion receives a semantic `<figure>` before the seven-step change chain; shared CSS renders the two lanes side by side on desktop and stacked below 42rem. Static contract tests protect bilingual parity, structural labels, semantic hooks, and the no-Mermaid/no-canvas constraint.

**Tech Stack:** HTML5, CSS custom properties and grid, Python 3.13 stdlib `html.parser`, pytest, Chromium browser verification.

## Global Constraints

- Keep `web/static/roadmap/index.html` as the only runtime asset; add no package, font, image, script, CDN, Mermaid, SVG, or canvas dependency.
- Preserve English as the default locale and retain the existing hash-addressable English/Korean sibling articles.
- The leading line must describe a missing explicit contract, not claim that the current runtime is already leaking raw prompts.
- English leading line: “Problem — span evidence exists, but the query-level decision is implicit inside Judge, so the fail-closed invariant is hard to verify at each boundary.”
- Korean leading line: “문제 — span 증거는 있지만 query-level 결정이 Judge 내부에 암묵적으로 섞여 있어, fail-closed invariant를 각 경계에서 검증하기 어렵습니다.”
- Amber must mean ambiguity and cobalt must identify `QueryDecisionSummary`; every color meaning also requires visible text.
- Desktop uses equal side-by-side lanes; widths below 42rem stack Before above After in semantic reading order.
- The page must have no horizontal overflow at 320px, preserve a readable print view, and expose headings and ordered steps to assistive technology.
- Preserve the verified work-package contract: P0 9, P1 3, P2 7, research 2, explicit exclusions 10.
- Keep implementation history compact by amending the existing roadmap commit instead of creating a trivial follow-up commit.

---

## File Structure

- Modify: `tests/web/test_roadmap_page.py` — adds a static bilingual and semantic contract for the comparison figures.
- Modify: `web/static/roadmap/index.html` — adds shared comparison styles and one locale-specific figure per Executive conclusion.
- Include in final amended commit: `docs/superpowers/specs/2026-07-11-query-aggregation-roadmap-design.md` and this plan.

---

### Task 1: Bilingual Before/After Comparison Figure

**Files:**
- Modify: `tests/web/test_roadmap_page.py`
- Modify: `web/static/roadmap/index.html`
- Test: `tests/web/test_roadmap_page.py`

**Interfaces:**
- Consumes: the existing `.content-section`, `.section-intro`, `.change-chain`, locale article, print, and `@media (max-width: 42rem)` contracts.
- Produces: two `.architecture-compare` figures, four `data-flow` lanes, eighteen `data-step` query-path nodes, two `data-evidence-branch` elements, and visible bilingual problem statements.

- [x] **Step 1: Write the failing static contract test**

Insert this test before the existing locale-state tests in `tests/web/test_roadmap_page.py`:

```python
def test_before_after_diagram_is_bilingual_semantic_and_dependency_free() -> None:
    source, _ = parse_page()

    assert source.count('class="architecture-compare"') == 2
    assert source.count('<section class="flow-lane" data-flow="before"') == 2
    assert source.count('<section class="flow-lane" data-flow="after"') == 2
    assert source.count('data-evidence-branch') == 2

    for step in (
        "raw-prompt",
        "extraction-records",
        "judge-combined",
        "router",
        "extraction-result",
        "query-decision-summary",
        "judge-policy",
        "router-gate",
    ):
        assert f'data-step="{step}"' in source

    assert (
        "Problem — span evidence exists, but the query-level decision is implicit inside Judge, "
        "so the fail-closed invariant is hard to verify at each boundary."
    ) in source
    assert (
        "문제 — span 증거는 있지만 query-level 결정이 Judge 내부에 암묵적으로 섞여 있어, "
        "fail-closed invariant를 각 경계에서 검증하기 어렵습니다."
    ) in source

    assert "Before · implicit decision" in source
    assert "After · explicit contract" in source
    assert "이전 · 암묵적 결정" in source
    assert "이후 · 명시적 계약" in source
    assert "ExtractionRecord[] → Masker" in source
    assert "ExtractionRecord[] → 마스킹" in source

    lowered = source.lower()
    assert "<mermaid" not in lowered
    assert "<canvas" not in lowered
    assert "<svg" not in lowered
```

- [x] **Step 2: Run the focused test and observe the intended failure**

Run:

```bash
python -m pytest tests/web/test_roadmap_page.py::test_before_after_diagram_is_bilingual_semantic_and_dependency_free -q
```

Expected: `FAIL` at `source.count('class="architecture-compare"') == 2` because no comparison figure exists yet.

- [x] **Step 3: Add the shared semantic diagram CSS**

Add these rules after the existing `.change-chain` block in `web/static/roadmap/index.html`:

```css
.problem-line {
  margin: 1.35rem 0 0;
  padding: 0.9rem 1rem;
  border: 1px solid color-mix(in oklab, var(--planned), white 60%);
  border-radius: var(--radius-sm);
  background: color-mix(in oklab, var(--planned), white 91%);
  color: var(--ink);
  font-size: 0.92rem;
  line-height: 1.55;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.architecture-compare { margin: 1rem 0 1.6rem; }
.compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.flow-lane {
  min-width: 0;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.flow-lane[data-flow="after"] {
  border-color: color-mix(in oklab, var(--accent), white 50%);
  background: color-mix(in oklab, var(--accent), white 97%);
}
.flow-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.flow-heading h3 { margin: 0; font-size: 1rem; }
.flow-state {
  flex: 0 0 auto;
  color: var(--ink-soft);
  font: 700 0.68rem/1 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.flow-state.implicit { color: oklch(0.40 0.11 76); }
.flow-steps {
  display: grid;
  gap: 0.65rem;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: flow-step;
}
.flow-step {
  position: relative;
  min-width: 0;
  padding: 0.72rem 0.8rem 0.72rem 2.55rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: white;
  overflow-wrap: anywhere;
}
.flow-step::before {
  counter-increment: flow-step;
  content: counter(flow-step);
  position: absolute;
  left: 0.75rem;
  top: 0.78rem;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 50%;
  background: var(--ink);
  color: white;
  font: 700 0.65rem/1.15rem ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  text-align: center;
}
.flow-step + .flow-step::after {
  content: "";
  position: absolute;
  left: 1.3rem;
  bottom: calc(100% + 1px);
  height: 0.65rem;
  border-left: 2px solid var(--line-strong);
}
.flow-lane[data-flow="before"] .flow-step[data-step="judge-combined"] {
  border-color: var(--planned);
}
.flow-lane[data-flow="before"] .flow-step[data-step="judge-combined"]::after {
  border-left-style: dashed;
  border-left-color: var(--planned);
}
.flow-lane[data-flow="after"] .flow-step[data-step="query-decision-summary"] {
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}
.flow-step strong { display: block; margin-bottom: 0.2rem; font-size: 0.9rem; }
.flow-step span { display: block; color: var(--ink-soft); font-size: 0.78rem; line-height: 1.4; }
.evidence-branch {
  margin: 0.75rem 0 0 2.55rem;
  padding: 0.68rem 0.75rem;
  border-left: 2px solid var(--accent);
  background: color-mix(in oklab, var(--accent), white 94%);
  color: var(--ink-soft);
  font: 650 0.75rem/1.45 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  overflow-wrap: anywhere;
}
.evidence-branch strong { color: var(--accent-ink); }
```

Add these declarations inside the existing `@media (max-width: 42rem)` block:

```css
.compare-grid { grid-template-columns: 1fr; }
.flow-lane { padding: 0.85rem; }
.evidence-branch { margin-left: 2.2rem; }
```

Add this rule inside the existing `@media print` block:

```css
.page-grid { display: block; }
.problem-line,
.flow-lane,
.flow-step,
.evidence-branch {
  background: white !important;
  color: black !important;
  box-shadow: none !important;
  break-inside: avoid;
}
```


- [x] **Step 4: Add the English comparison figure**

Insert this block after the English `.section-intro` and before `<ol class="change-chain">`:

```html
<p class="problem-line">Problem — span evidence exists, but the query-level decision is implicit inside Judge, so the fail-closed invariant is hard to verify at each boundary.</p>
<figure class="architecture-compare" aria-labelledby="compare-en-title">
  <figcaption id="compare-en-title" class="sr-only">Current and target Query Aggregation structures</figcaption>
  <div class="compare-grid">
    <section class="flow-lane" data-flow="before" aria-labelledby="before-en-title">
      <div class="flow-heading"><h3 id="before-en-title">Before · implicit decision</h3><span class="flow-state implicit">implicit</span></div>
      <ol class="flow-steps">
        <li class="flow-step" data-step="raw-prompt"><strong>Raw prompt</strong><span>One query enters the privacy boundary.</span></li>
        <li class="flow-step" data-step="extraction-records"><strong>ExtractionRecord[]</strong><span>Span evidence exists without a query-level outcome.</span></li>
        <li class="flow-step" data-step="judge-combined"><strong>Judge</strong><span>Aggregation + policy share one implicit boundary.</span></li>
        <li class="flow-step" data-step="router"><strong>Router</strong><span>Routing consumes the combined judgment.</span></li>
      </ol>
    </section>
    <section class="flow-lane" data-flow="after" aria-labelledby="after-en-title">
      <div class="flow-heading"><h3 id="after-en-title">After · explicit contract</h3><span class="flow-state">explicit</span></div>
      <ol class="flow-steps">
        <li class="flow-step" data-step="raw-prompt"><strong>Raw prompt</strong><span>One query enters the privacy boundary.</span></li>
        <li class="flow-step" data-step="extraction-result"><strong>ExtractionResult</strong><span>Success or failure is explicit.</span></li>
        <li class="flow-step" data-step="query-decision-summary"><strong>QueryDecisionSummary</strong><span>One pure artifact carries the query-level decision.</span></li>
        <li class="flow-step" data-step="judge-policy"><strong>Judge</strong><span>Policy only · canonical action.</span></li>
        <li class="flow-step" data-step="router-gate"><strong>Router</strong><span>Invariant gate · allowed endpoint.</span></li>
      </ol>
      <div class="evidence-branch" data-evidence-branch><strong>Evidence branch</strong><br>ExtractionRecord[] → Masker</div>
    </section>
  </div>
</figure>
```

- [x] **Step 5: Add the Korean comparison figure**

Insert this block after the Korean `.section-intro` and before `<ol class="change-chain">`:

```html
<p class="problem-line">문제 — span 증거는 있지만 query-level 결정이 Judge 내부에 암묵적으로 섞여 있어, fail-closed invariant를 각 경계에서 검증하기 어렵습니다.</p>
<figure class="architecture-compare" aria-labelledby="compare-ko-title">
  <figcaption id="compare-ko-title" class="sr-only">현재와 목표 Query Aggregation 구조</figcaption>
  <div class="compare-grid">
    <section class="flow-lane" data-flow="before" aria-labelledby="before-ko-title">
      <div class="flow-heading"><h3 id="before-ko-title">이전 · 암묵적 결정</h3><span class="flow-state implicit">암묵적</span></div>
      <ol class="flow-steps">
        <li class="flow-step" data-step="raw-prompt"><strong>Raw prompt</strong><span>하나의 query가 privacy boundary로 들어옵니다.</span></li>
        <li class="flow-step" data-step="extraction-records"><strong>ExtractionRecord[]</strong><span>span 증거는 있지만 query-level 결과는 없습니다.</span></li>
        <li class="flow-step" data-step="judge-combined"><strong>Judge</strong><span>집계 + 정책이 하나의 암묵적 경계를 공유합니다.</span></li>
        <li class="flow-step" data-step="router"><strong>Router</strong><span>결합된 판단을 받아 routing합니다.</span></li>
      </ol>
    </section>
    <section class="flow-lane" data-flow="after" aria-labelledby="after-ko-title">
      <div class="flow-heading"><h3 id="after-ko-title">이후 · 명시적 계약</h3><span class="flow-state">명시적</span></div>
      <ol class="flow-steps">
        <li class="flow-step" data-step="raw-prompt"><strong>Raw prompt</strong><span>하나의 query가 privacy boundary로 들어옵니다.</span></li>
        <li class="flow-step" data-step="extraction-result"><strong>ExtractionResult</strong><span>성공 또는 실패가 명시됩니다.</span></li>
        <li class="flow-step" data-step="query-decision-summary"><strong>QueryDecisionSummary</strong><span>하나의 순수 artifact가 query-level 결정을 전달합니다.</span></li>
        <li class="flow-step" data-step="judge-policy"><strong>Judge</strong><span>정책만 수행 · canonical action.</span></li>
        <li class="flow-step" data-step="router-gate"><strong>Router</strong><span>invariant gate · 허용된 endpoint.</span></li>
      </ol>
      <div class="evidence-branch" data-evidence-branch><strong>증거 분기</strong><br>ExtractionRecord[] → 마스킹</div>
    </section>
  </div>
</figure>
```

- [x] **Step 6: Run the focused and full roadmap contracts**

Run:

```bash
python -m pytest tests/web/test_roadmap_page.py::test_before_after_diagram_is_bilingual_semantic_and_dependency_free -q
python -m pytest tests/web/test_roadmap_page.py -q
```

Expected: the focused test passes; the full file passes with seven total tests and the existing package counts remain unchanged.

- [x] **Step 7: Verify the rendered diagram locally**

Serve the page in the existing tmux-backed static server or run:

```bash
python -m http.server 4173 --directory web/static/roadmap
```

Verify in Chromium at 1440×1000 and 320×800:

```text
- English and Korean each show exactly one problem line and one comparison figure.
- At 1440px, Before and After have equal-width side-by-side lanes.
- At 320px, Before stacks above After and document scrollWidth equals clientWidth.
- QueryDecisionSummary is the only cobalt-emphasized query-path node.
- The Before Judge boundary is amber, dashed, and visibly labeled implicit/암묵적.
- The evidence branch is visually separate from the numbered query-decision path.
- Both figure captions and lane headings are exposed in the accessibility tree.
- Print mode removes backgrounds and preserves borders, text, and lane order.
```

- [x] **Step 8: Amend the compact roadmap commit**

Run:

```bash
git add \
  web/static/roadmap/index.html \
  tests/web/test_roadmap_page.py \
  docs/superpowers/specs/2026-07-11-query-aggregation-roadmap-design.md \
  docs/superpowers/plans/2026-07-12-query-aggregation-comparison-diagram.md
git commit --amend --no-edit
```

Expected: one amended `feat: publish query aggregation roadmap` commit containing the approved design, implementation plan, static contract, and rendered figure.
