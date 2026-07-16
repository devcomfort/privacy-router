# Query Aggregation Roadmap Briefing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, verify, and publicly deploy a standalone bilingual HTML briefing that accurately consolidates every verified Privacy Router work package and its completion criteria.

**Architecture:** One self-contained `web/static/roadmap/index.html` owns semantic markup, inline CSS, and progressive-enhancement JavaScript. English and Korean are complete sibling articles switched through hash-addressable controls so both languages remain available without JavaScript; Python contract tests verify content counts, structure, privacy, and internal navigation before browser and Surge verification.

**Tech Stack:** HTML5, CSS, vanilla JavaScript, Python 3.13 stdlib, pytest, Chromium, Surge CLI.

## Global Constraints

- Query Aggregation must be labeled as a target design whose runtime implementation is pending.
- Create no frontend build pipeline and add no runtime dependency.
- Use complete English and Korean content; English is the initial locale.
- Use no external fonts, images, analytics, or third-party scripts.
- Public examples use `<personal-id>` and `PERSONAL_IDENTIFIER#7f3a9c2d`, never real identifiers or secrets.
- Target WCAG 2.2 AA, keyboard operation, reduced motion, print support, and 320 px through desktop layouts.
- Preserve the verified counts: 9 P0 packages, 3 P1 packages, 7 P2 packages, 2 research packages, and 10 explicit exclusions.
- Publish `web/static/roadmap/` to the first available domain in this order: `privacy-router-roadmap.surge.sh`, `privacy-router-query-roadmap.surge.sh`, `privacy-router-work-plan.surge.sh`.
- Keep implementation history compact: one meaningful implementation commit after local and public verification; amend it if deployment metadata changes.

## File Structure

- Create `web/static/roadmap/index.html`: complete bilingual briefing, styles, interaction, print rules, and deployment metadata.
- Create `tests/web/test_roadmap_page.py`: deterministic static-page contract and privacy checks.
- Keep `docs/superpowers/specs/2026-07-11-query-aggregation-roadmap-design.md` as the design source and this file as the execution checklist.

---

### Task 1: Static Briefing Contract and Page

**Files:**
- Create: `tests/web/test_roadmap_page.py`
- Create: `web/static/roadmap/index.html`

**Interfaces:**
- Consumes: the approved design at `docs/superpowers/specs/2026-07-11-query-aggregation-roadmap-design.md` and the normative runtime requirements at `docs/dev/query-aggregation-spec.md`.
- Produces: a static directory that can be served or deployed without SvelteKit, plus a test contract reused by Tasks 2 and 3.

- [ ] **Step 1: Write the failing static-page contract**

```python
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).parents[2] / "web/static/roadmap/index.html"


class RoadmapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.anchor_targets: list[str] = []
        self.work_packages: dict[str, int] = {}
        self.external_resources: list[str] = []
        self.languages: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            assert element_id not in self.ids, f"duplicate id: {element_id}"
            self.ids.add(element_id)
        if href := values.get("href"):
            if href.startswith("#"):
                self.anchor_targets.append(href[1:])
        if priority := values.get("data-work-package"):
            self.work_packages[priority] = self.work_packages.get(priority, 0) + 1
        if lang := values.get("lang"):
            self.languages.add(lang)
        if tag in {"script", "img", "source", "iframe"} and values.get("src"):
            self.external_resources.append(values["src"] or "")
        if tag == "link" and values.get("rel") in {"stylesheet", "preload", "modulepreload"}:
            self.external_resources.append(values.get("href") or "")


def parse_page() -> tuple[str, RoadmapParser]:
    source = PAGE.read_text(encoding="utf-8")
    parser = RoadmapParser()
    parser.feed(source)
    return source, parser


def test_roadmap_is_complete_and_bilingual() -> None:
    source, parser = parse_page()
    assert '<html lang="en"' in source
    assert parser.languages >= {"en", "ko"}
    assert "Target design — runtime implementation pending" in source
    assert "목표 설계 — 런타임 구현 대기" in source
    assert parser.work_packages == {"p0": 18, "p1": 6, "p2": 14, "research": 4}
    assert source.count('data-exclusion="true"') == 20


def test_internal_links_have_targets_and_resources_are_local() -> None:
    _, parser = parse_page()
    assert set(parser.anchor_targets) <= parser.ids
    assert parser.external_resources == []


def test_public_copy_contains_no_identifier_or_credential_examples() -> None:
    source, _ = parse_page()
    forbidden = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "api_key": r"\b(?:sk|pr)-[A-Za-z0-9_-]{12,}\b",
        "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "long_personal_number": r"\b\d{6}[- ]?\d{7}\b",
    }
    failures = [name for name, pattern in forbidden.items() if re.search(pattern, source)]
    assert failures == []
    assert "<personal-id>" in source
    assert "PERSONAL_IDENTIFIER#7f3a9c2d" in source
```

- [ ] **Step 2: Run the focused contract and observe the expected failure**

Run:

```bash
python -m pytest tests/web/test_roadmap_page.py -q
```

Expected: failure because `web/static/roadmap/index.html` does not exist.

- [ ] **Step 3: Create the self-contained semantic page**

Use this head, locale shell, and section-ID contract. The work-package copy that follows supplies every `<details>` body; no empty section or scaffold comment may remain in the written file.

```html
<!doctype html>
<html lang="en" data-current-locale="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Source-grounded Privacy Router query aggregation implementation roadmap.">
  <link rel="canonical" href="https://privacy-router-roadmap.surge.sh/">
  <meta property="og:url" content="https://privacy-router-roadmap.surge.sh/">
  <title>Privacy Router — Query Aggregation Roadmap</title>
</head>
<body>
  <span id="en" class="locale-target" aria-hidden="true"></span>
  <span id="ko" class="locale-target" aria-hidden="true"></span>
  <header class="utility-bar" aria-label="Page controls">
    <a href="#en" lang="en">English</a>
    <a href="#ko" lang="ko">한국어</a>
    <button id="expand-all" type="button" aria-expanded="false">Expand all</button>
  </header>
  <article class="briefing briefing-en" lang="en" aria-labelledby="title-en">
    <section id="status-en"><h1 id="title-en">Query Aggregation Roadmap</h1></section>
    <nav aria-label="English roadmap sections">
      <a href="#priorities-en">Priority map</a>
      <a href="#p0-en">P0 — Security and correctness</a>
      <a href="#p1-en">P1 — Release consistency</a>
      <a href="#p2-en">P2 — Documentation and UX</a>
      <a href="#research-en">Research only</a>
      <a href="#excluded-en">Explicit exclusions</a>
      <a href="#sequence-en">Execution order</a>
      <a href="#done-en">Definition of Done</a>
      <a href="#sources-en">Sources</a>
    </nav>
  </article>
  <article class="briefing briefing-ko" lang="ko" aria-labelledby="title-ko">
    <section id="status-ko"><h1 id="title-ko">Query Aggregation 작업 지도</h1></section>
    <nav aria-label="한국어 작업 지도 섹션">
      <a href="#priorities-ko">우선순위 지도</a>
      <a href="#p0-ko">P0 — 보안·정확성</a>
      <a href="#p1-ko">P1 — 릴리스 정합성</a>
      <a href="#p2-ko">P2 — 문서·UX</a>
      <a href="#research-ko">연구 전용</a>
      <a href="#excluded-ko">명시적 제외</a>
      <a href="#sequence-ko">실행 순서</a>
      <a href="#done-ko">완료 기준</a>
      <a href="#sources-ko">근거 문서</a>
    </nav>
  </article>
</body>
</html>
```

Inline CSS must implement the approved neutral-light tokens, 72-character prose measure, desktop sticky navigation, mobile inline navigation, focus-visible states, contained table overflow, print selection, and reduced-motion override. Inline JavaScript must persist the hash-selected locale, update the document language, toggle every `<details>` in the active article, and highlight the active table-of-contents link with `IntersectionObserver`. The initial HTML remains readable and navigable if either enhancement fails.

Use these exact work-package titles and preserve their order in both locales:

```text
P0
1. Lock the external-transmission invariant in tests / 외부 전송 invariant를 테스트로 고정
2. Distinguish extraction success from failure / Extraction 성공과 실패를 구분
3. Add QueryDecisionSummary and pure aggregation / QueryDecisionSummary와 순수 집계 구현
4. Make Judge consume the summary / Judge가 summary만 사용
5. Enforce final Router invariants / Router 최종 invariant 적용
6. Close MiddleMan and forced-override bypasses / MiddleMan·forced override 우회 차단
7. Make masking atomic and hydration fail-fast / Masking atomic·Hydration fail-fast
8. Apply single-extraction in the API proxy / API proxy single-extraction 적용
9. Constrain API and MCP metadata / API·MCP metadata 경계 정리

P1
1. Split production and experiment dependencies / 제품·실험 dependency 분리
2. Reconcile Docker and Hermes execution contracts / Docker·Hermes 실행 계약 정리
3. Separate deterministic tests, integration tests, and real-LLM eval / 테스트·평가 경계 분리

P2
1. Label current and target architecture honestly / 현재·목표 설계 구분
2. Add a current status page / 현재 상태 페이지 추가
3. Reconcile README routes, models, and commands / README 정합성 수정
4. Provide complete English and Korean content / 완전한 영문·한국어 제공
5. Enforce source and web documentation parity / source·web 문서 parity 보장
6. Classify audit and TODO history / audit·TODO 역사 분류
7. Clear accessibility warnings / 접근성 경고 제거

Research
R.1 Build a model-specific vLLM matrix / 모델별 vLLM 매트릭스 작성
R.2 Reconcile the experiment-result manifest / 실험 결과 manifest 정합화
```

Render every P0 package as `<details data-work-package="p0">` with four labeled blocks: problem, required change, affected paths, and acceptance criteria. Render P1, P2, and research packages with purpose and observable completion criteria. Render each explicit exclusion as an `<li data-exclusion="true">`. Use unique `-en` and `-ko` suffixes for all section IDs.

The Definition of Done table must include successful-safe, maskable, essential, mixed, extractor exception, structured parse failure, invalid offset, invalid mask index, local failure, and hydration failure rows. Each row must state the canonical action, external raw call count, and payload requirement.

- [ ] **Step 4: Run the static contract and make it pass**

Run:

```bash
python -m pytest tests/web/test_roadmap_page.py -q
```

Expected: `3 passed`.

---

### Task 2: Browser, Accessibility, and Responsive Verification

**Files:**
- Modify only when verification finds a defect: `web/static/roadmap/index.html`
- Test: `tests/web/test_roadmap_page.py`

**Interfaces:**
- Consumes: the passing static asset and contract from Task 1.
- Produces: a browser-verified static page ready for public deployment.

- [ ] **Step 1: Serve the page locally**

Run from the repository root:

```bash
python -m http.server 4173 --directory web/static/roadmap
```

Expected: `http://127.0.0.1:4173/` returns the roadmap page.

- [ ] **Step 2: Verify the English desktop state at 1440 × 1000**

Check in Chromium:

```text
- English is initially visible and Korean content is hidden.
- The status explicitly says runtime implementation is pending.
- The sticky table of contents does not overlap headings.
- Every P0/P1/P2/research count matches 9/3/7/2.
- Tables scroll inside their container rather than overflowing the page.
- No external network request is made after the document request.
```

- [ ] **Step 3: Verify Korean and keyboard interaction**

```text
- Activate 한국어 using only Tab and Enter.
- All headings, descriptions, table labels, controls, and completion criteria switch to Korean.
- Focus remains visible.
- Expand all opens every details element in the active locale; Collapse all closes them.
- Reload preserves the locale preference when JavaScript is enabled.
- With JavaScript disabled, #en and #ko links still switch complete articles.
```

- [ ] **Step 4: Verify 320 × 800 and 768 × 1024 layouts**

```text
- No page-level horizontal overflow.
- The utility bar wraps without covering content.
- Navigation becomes inline rather than sticky.
- Heading copy remains inside the viewport.
- Code and table overflow is contained.
- Tap targets are at least 44 × 44 CSS pixels.
```

- [ ] **Step 5: Verify reduced motion and print output**

```text
- prefers-reduced-motion removes smooth scrolling and nonessential transitions.
- Print preview removes utility controls and sticky positioning.
- Both language articles do not print simultaneously; the selected article prints.
- Text remains dark on white and tables preserve borders.
```

- [ ] **Step 6: Re-run the focused contract after browser fixes**

Run:

```bash
python -m pytest tests/web/test_roadmap_page.py -q
```

Expected: `3 passed`.

---

### Task 3: Surge Deployment and Public Verification

**Files:**
- Modify: `web/static/roadmap/index.html` only if the successful domain differs from the preferred canonical URL.
- Include in the final implementation commit: `tests/web/test_roadmap_page.py`, `web/static/roadmap/index.html`, and this plan.

**Interfaces:**
- Consumes: browser-verified files from Task 2 and an authenticated Surge CLI environment.
- Produces: a stable public HTTPS URL with verified content and one compact implementation commit.

- [ ] **Step 1: Confirm the Surge CLI is available**

Run:

```bash
npx --yes surge --version
```

Expected: a version string and exit code 0.

- [ ] **Step 2: Publish to the preferred domain**

Run:

```bash
npx --yes surge web/static/roadmap privacy-router-roadmap.surge.sh
```

Expected: `Success! - Published to privacy-router-roadmap.surge.sh`.

If Surge reports that the domain is unavailable, retry in exact order:

```bash
npx --yes surge web/static/roadmap privacy-router-query-roadmap.surge.sh
npx --yes surge web/static/roadmap privacy-router-work-plan.surge.sh
```

Do not create an unrelated random domain. If all three are unavailable, stop with the three concrete Surge errors and request a domain choice.

- [ ] **Step 3: Set and redeploy the canonical URL**

The file initially contains the preferred canonical URL. If `privacy-router-query-roadmap.surge.sh` succeeds instead, replace both occurrences of:

```text
https://privacy-router-roadmap.surge.sh/
```

with:

```text
https://privacy-router-query-roadmap.surge.sh/
```

If `privacy-router-work-plan.surge.sh` succeeds, replace both preferred-domain occurrences with:

```text
https://privacy-router-work-plan.surge.sh/
```

Rerun the three static tests, then publish the same directory to the successful domain once more.

- [ ] **Step 4: Verify the public response and rendered page**

Require:

```text
- HTTPS response status is 200.
- Content-Type contains text/html.
- Title is “Privacy Router — Query Aggregation Roadmap”.
- English source contains “Target design — runtime implementation pending”.
- Korean source contains “목표 설계 — 런타임 구현 대기”.
- A real Chromium tab renders the same desktop and mobile layout verified locally.
- Language switching and details controls work on the deployed origin.
```

- [ ] **Step 5: Create one meaningful implementation commit**

```bash
git add web/static/roadmap/index.html tests/web/test_roadmap_page.py docs/superpowers/plans/2026-07-11-query-aggregation-roadmap.md
git commit -m "feat: publish query aggregation roadmap"
```

Expected: one commit containing the page, its contract tests, the final deployment URL, and this execution plan. Do not stage unrelated working-tree files.
