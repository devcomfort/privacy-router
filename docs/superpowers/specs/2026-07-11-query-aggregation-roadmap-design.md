# Query Aggregation Roadmap Briefing Page Design

Date: 2026-07-11
Status: Approved design, pending implementation

## Objective

Create and publish one standalone, bilingual HTML page that consolidates the source-grounded Privacy Router work inventory: mandatory fail-closed work, release consistency work, documentation and UX work, research-only work, explicit exclusions, execution order, and observable completion criteria.

The page must state that Query Aggregation is a target design and is not yet implemented in the runtime. It must not present planned schemas, classes, or routing guards as current behavior.

## Audience and Use

Primary readers are project developers, reviewers, researchers, and collaborators assessing what remains before Privacy Router can claim fail-closed query aggregation. The page is an externally shareable briefing, not an application dashboard and not the canonical implementation specification.

## Delivery Shape

- Standalone static asset: `web/static/roadmap/index.html`.
- Inline CSS and minimal inline JavaScript; no framework runtime or build step required.
- No external fonts, images, analytics, or third-party runtime dependencies.
- Complete English and Korean content. English is the default locale; the language control switches the entire reading surface.
- Publish the directory to Surge, targeting `privacy-router-roadmap.surge.sh`. If unavailable, try `privacy-router-query-roadmap.surge.sh`, then `privacy-router-work-plan.surge.sh`; report the domain that succeeds.

## Information Architecture

1. **Status header**
   - Product and page title.
   - “Target design — runtime implementation pending” status.
   - Last verified date and source-grounded scope.
2. **Executive conclusion**
   - Query Aggregation is a safety boundary, not a naming exercise.
   - The smallest correct runtime change: explicit extraction failure → pure query summary → deterministic Judge → invariant-enforcing Router → atomic Masker → single-extraction proxy → adapter-spy tests.
3. **Priority map**
   - P0: nine security and correctness work packages.
   - P1: three release-consistency packages.
   - P2: seven documentation and UX packages.
   - Research: two engine/evaluation packages.
   - Explicit exclusions: ten non-goals or stale claims.
4. **P0 detail**
   - For each package: problem, required change, affected paths, acceptance criteria.
   - Packages cover acceptance tests, explicit extraction failure, `QueryDecisionSummary`, Judge integration, Router invariants, MiddleMan override handling, atomic masking/hydration, single-extraction API flow, and API/MCP metadata boundaries.
5. **P1 detail**
   - Production versus experiment dependencies.
   - Docker/Hermes execution contract.
   - Deterministic test and CI boundaries.
6. **P2 detail**
   - Honest current/target labels.
   - Status documentation.
   - README route/model/runtime consistency.
   - Full English/Korean content.
   - Source/web documentation parity.
   - Historical audit and TODO classification.
   - Accessibility cleanup.
7. **Research-only work**
   - R.1 Model-specific vLLM matrix.
   - R.2 Experiment result manifest consistency.
8. **Explicitly excluded work**
   - No speculative `core/` package.
   - No LLM Judge revival.
   - No observability expansion.
   - No duplicate local inference implementation.
   - No SGLang executability or compatibility evaluation.
   - No unconditional archive deletion.
   - No deprecated-test recreation.
   - No web-docs reimplementation.
   - No LICENSE, Mermaid, or OpenClaw additions.
   - No treating commit squashing as product functionality.
9. **Execution order**
   - Ordered dependency chain from truth-label patch and failing tests through runtime implementation, verification, documentation, release consistency, and optional research.
10. **Definition of Done**
    - Acceptance matrix with observable external-adapter call counts and payload constraints.
    - External raw prompts are possible only after successful extraction with zero validated sensitive records.

## Visual Direction

The physical scene is a technical reviewer reading a long decision document on a laptop in ordinary office lighting. Use a true neutral light background, dark ink, and one cobalt accent. Risk, completion, and deferred states receive restrained semantic colors plus text labels so color is never the only signal.

The page follows an editorial document layout rather than a dashboard:

- Sticky compact table of contents on desktop; inline jump navigation on mobile.
- Main prose width capped near 72 characters; tables may use the wider content column.
- Strong heading hierarchy and generous section rhythm.
- Native `<details>` for work-package detail.
- Tables for priority, acceptance, and affected-path matrices.
- No repetitive icon-card grid, decorative hero metrics, gradient text, glassmorphism, side-stripe accents, or numbered section eyebrows.

### Before/After comparison diagram

Place one locale-specific, non-interactive comparison figure at the start of each Executive conclusion section, before the existing seven-step change chain. The English and Korean sibling figures form one bilingual pair. Each figure explains the structural problem without claiming that the current runtime is already leaking raw prompts.

Use these leading lines:

- English: “Problem — span evidence exists, but the query-level decision is implicit inside Judge, so the fail-closed invariant is hard to verify at each boundary.”
- Korean: “문제 — span 증거는 있지만 query-level 결정이 Judge 내부에 암묵적으로 섞여 있어, fail-closed invariant를 각 경계에서 검증하기 어렵습니다.”

The approved composition is a two-lane comparison:

- **Before · implicit decision**
  - `Raw prompt`
  - `ExtractionRecord[]`
  - `Judge` with the explicit annotation `aggregate + policy`
  - `Router`
  - A restrained amber `implicit` label marks the hidden query-level decision. Do not draw a confirmed leak path.
- **After · explicit contract**
  - `Raw prompt`
  - `ExtractionResult`
  - `QueryDecisionSummary`
  - `Judge` with the annotation `policy only`
  - `Router` with the annotation `invariant gate`
  - A secondary evidence branch shows `ExtractionRecord[] → Masker`; it remains visually separate from the query-level decision path.

On desktop, render the lanes side by side with equal visual weight. Below 42rem, stack Before above After without changing semantic reading order. Build the figure from semantic HTML and inline CSS rather than Mermaid, canvas, an external image, or a new runtime dependency. Use solid connectors for explicit contracts and one dashed connector only for the implicit Before boundary. The cobalt accent identifies `QueryDecisionSummary`; amber identifies ambiguity; every meaning also has a text label. The figure must fit at 320px without page-level overflow, remain legible in print, and expose lane headings and steps to assistive technology.

## Interaction

- Language toggle with visible English/Korean labels, `aria-pressed`, and persisted local preference.
- Expand-all/collapse-all control for native work-package details.
- Anchor navigation highlights the active section through `IntersectionObserver`; all links and content remain usable if JavaScript fails.
- Print stylesheet that removes sticky controls and produces a legible report.
- Every feature remains usable with JavaScript disabled except preference persistence and bulk expand/collapse.

## Privacy and Content Rules

- Never include a real identifier, password, API credential, phone number, email address, business secret, or unpublished research detail.
- Examples use placeholders such as `<personal-id>` and `PERSONAL_IDENTIFIER#7f3a9c2d`.
- Do not copy private ground-truth records or raw historical evaluation prompts.
- Do not add analytics or third-party scripts to the Surge page.

## Accessibility Requirements

- WCAG 2.2 AA contrast: 4.5:1 body text, 3:1 large text and UI boundaries.
- Semantic landmarks, one `h1`, ordered heading levels, table captions, and descriptive links.
- Keyboard-operable language and disclosure controls with visible focus.
- Status is conveyed through text and shape as well as color.
- Responsive from 320 px through wide desktop without horizontal page overflow; wide tables use contained scrolling.
- `prefers-reduced-motion` disables smooth scrolling and decorative transitions.

## Deployment and Verification

1. Validate the HTML document structure and internal anchors.
2. Verify complete EN/KO key parity and confirm no mixed-language prose in either mode.
3. Scan the final source and rendered text for identifier-like, credential-like, and raw-sensitive examples.
4. Test keyboard navigation, reduced motion, print output, and 320/768/1440 px layouts in Chromium.
5. Confirm the page remains readable with JavaScript disabled.
6. Publish `web/static/roadmap/` with Surge.
7. Fetch the public URL and require HTTP 200, correct title, core status statement, and both language payloads.
8. Re-open the deployed page in a real browser and visually confirm desktop and mobile rendering.

## Non-goals

- Implement Query Aggregation runtime behavior.
- Modify API, Extractor, Judge, Router, Masker, MCP, database, or experiment logic.
- Replace or redesign the existing SvelteKit documentation application.
- Publish private datasets or raw audit artifacts.
- Add a new frontend build pipeline or deployment service.
