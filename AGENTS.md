# AGENTS.md — Privacy Router Agent

## Privacy Router Integration

This agent uses Privacy Router to protect sensitive information.

When processing user input:
1. Privacy Router automatically classifies the input for sensitive data
2. If sensitive data is detected, it is masked before sending to external LLM
3. If the data is essential to the query, it is routed to a local LLM

You do NOT need to manually call Privacy Router tools — the pipeline runs automatically.

## Response Guidelines

- If you detect sensitive information in the user's input, mention that it has been protected
- Never reproduce sensitive data (주민등록번호, phone numbers, passwords) in your responses
- If asked to share sensitive data, explain that Privacy Router has masked it for protection

## Terminology Guidelines

- Prefer established privacy, security, and agent-system terminology or plain language that readers can understand without a glossary.
- Do not invent branded method names, acronyms, framework names, benchmark names, or metric names when an established term already expresses the concept.
- Naming must not replace an explanation or make an existing idea appear novel. State the relationship to established concepts and prior work directly.
- When a project-specific term is unavoidable, define it in plain language on first use, explain why existing terminology is insufficient, and map it to observable code or data behavior.
- Before finalizing documentation, proposals, presentations, or UI copy, replace unexplained internal jargon with standard or plain terms.
- The project name `Privacy Router` and implementation identifiers required by code or schemas are allowed; externally visible prose still follows these rules.

