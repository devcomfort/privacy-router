# Product

## Register

product

## Users

Privacy Router serves developers, researchers, reviewers, and operators who need to let AI agents use external language models without silently exposing sensitive prompt content. They work across the API proxy, agent integration, administration, evaluation, and documentation surfaces and need to understand what the system will send, mask, keep local, or reject.

## Product Purpose

Privacy Router is a privacy-first, OpenAI-compatible routing layer. It inspects agent prompts before an external model call, extracts exact sensitive spans with contextual reasoning, makes deterministic query-level policy decisions, masks only validated non-essential spans, and prevents essential or unclassified content from crossing the external trust boundary. Success means safe prompts retain cloud-model utility while every sensitive path has an explicit, testable, fail-closed outcome.

## Brand Personality

Precise, trustworthy, calm. The product explains risk without alarmism, distinguishes observed implementation from target architecture, and prefers verifiable contracts over security theatre.

## Anti-references

- Ambiguous architecture diagrams that present planned components as already implemented.
- Generic SaaS dashboards made from repetitive icon cards and decorative metrics.
- Over-stylized “cybersecurity” visuals, neon gradients, glass effects, and fear-based language.
- Dense research reports that bury decisions, ownership, or completion criteria in uninterrupted prose.
- Interfaces that expose raw sensitive values merely to demonstrate that detection works.

## Design Principles

1. **Make the trust boundary visible.** Every route must state what crosses the external boundary and in what form.
2. **Separate evidence from decisions.** Span-level extraction evidence, query-level policy, routing, and masking contracts remain distinct.
3. **Label reality honestly.** Current, target, blocked, deferred, and completed states are never conflated.
4. **Progressive disclosure over compression.** Lead with the decision and reveal implementation details, affected files, and tests on demand.
5. **Practice the privacy promise.** Public examples and artifacts use placeholders rather than real identifiers or secrets.

## Accessibility & Inclusion

Target WCAG 2.2 AA. All critical states remain distinguishable without color, controls are keyboard-operable, body text maintains at least 4.5:1 contrast, layouts work from narrow mobile screens through desktop review, motion respects reduced-motion preferences, and complete English and Korean content is available without mixing both languages in a single reading mode.
