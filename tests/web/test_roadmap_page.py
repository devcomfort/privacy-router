"""Contract tests for the public Query Aggregation roadmap page."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).parents[2] / "web/static/roadmap/index.html"


class RoadmapParser(HTMLParser):
    """Collect the structural contract without adding HTML parser dependencies."""

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
        if (href := values.get("href")) and href.startswith("#"):
            self.anchor_targets.append(href[1:])
        if priority := values.get("data-work-package"):
            self.work_packages[priority] = self.work_packages.get(priority, 0) + 1
        if lang := values.get("lang"):
            self.languages.add(lang)
        if tag in {"script", "img", "source", "iframe"} and values.get("src"):
            self.external_resources.append(values["src"] or "")
        if tag == "link" and values.get("rel") in {
            "stylesheet",
            "preload",
            "modulepreload",
        }:
            self.external_resources.append(values.get("href") or "")


def parse_page() -> tuple[str, RoadmapParser]:
    """Return the source and its structural index."""
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
    assert parser.work_packages == {
        "p0": 18,
        "p1": 6,
        "p2": 14,
        "research": 4,
    }
    assert source.count('data-exclusion="true"') == 20


def test_sglang_evaluation_is_explicitly_out_of_scope() -> None:
    """SGLang may appear only as a non-goal, never as research work."""
    source, _ = parse_page()

    for locale in ("en", "ko"):
        research_start = source.index(f'id="research-{locale}"')
        excluded_start = source.index(f'id="excluded-{locale}"')
        assert "SGLang" not in source[research_start:excluded_start]


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
    assert "&lt;personal-id&gt;" in source
    assert "PERSONAL_IDENTIFIER#7f3a9c2d" in source


def test_before_after_diagram_is_bilingual_semantic_and_dependency_free() -> None:
    source, _ = parse_page()

    assert source.count('class="architecture-compare"') == 2
    assert source.count('<section class="flow-lane" data-flow="before"') == 2
    assert source.count('<section class="flow-lane" data-flow="after"') == 2
    assert source.count("data-evidence-branch") == 2

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
        "Problem — span evidence exists, but the query-level decision is implicit "
        "inside Judge, so the fail-closed invariant is hard to verify at each "
        "boundary."
    ) in source
    assert (
        "문제 — span 증거는 있지만 query-level 결정이 Judge 내부에 암묵적으로 "
        "섞여 있어, fail-closed invariant를 각 경계에서 검증하기 어렵습니다."
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


def test_deep_link_locale_state_controls_briefing_visibility() -> None:
    """A work-package anchor must render the matching language briefing."""
    source, _ = parse_page()

    assert "hash.endsWith('-ko')" in source
    assert 'html[data-current-locale="ko"] .briefing-en { display: none; }' in source
    assert 'html[data-current-locale="ko"] .briefing-ko { display: block; }' in source


def test_deep_link_locale_state_controls_language_controls() -> None:
    """A Korean work-package link must select Korean controls and labels."""
    source, _ = parse_page()

    assert (
        'html[data-current-locale="ko"] .lang-link[href="#en"] { background: transparent; color: color-mix(in oklab, white 76%, transparent); }'
        in source
    )
    assert 'html[data-current-locale="ko"] .lang-link[href="#ko"] { background: white; color: var(--ink); }' in source
    assert 'html[data-current-locale="ko"] .button-en { display: none; }' in source
    assert 'html[data-current-locale="ko"] .button-ko { display: inline; }' in source
