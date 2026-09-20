"""Parser for the LiteLLM extractor's structured response."""

from __future__ import annotations

from collections.abc import Sequence

from ..parser import (
    DetectorParseError,
    ParsedEntity,
    as_mapping,
    canonical_tag,
    confidence,
    confidentiality_judgment,
    mapping,
    necessity_judgment,
    normalize_kind,
    offsets,
    optional_string,
    required_string,
)


class LLMParser:
    """Parse structured output produced by the LiteLLM-backed extractor."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse one LLM response into backend-neutral candidates.

        Args:
            raw: Structured LLM payload or Pydantic model.
            text: Original input text used for offset context.

        Returns:
            Parsed candidates without generated entity IDs.

        Raises:
            DetectorParseError: If the payload shape is invalid.
        """
        payload = as_mapping(raw)
        records = payload.get("records", payload.get("entities"))
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise DetectorParseError("LLM output records must be an array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(records):
            data = as_mapping(item)
            tag = required_string(data.get("tag") or data.get("category"), f"LLM record {index} tag")
            span = required_string(data.get("span"), f"LLM record {index} span")
            parsed.append(
                ParsedEntity(
                    tag=canonical_tag(tag, span),
                    kind=normalize_kind(data.get("kind"), default="contextual"),
                    native_label=optional_string(data.get("native_label")) or tag,
                    span=span,
                    offsets=offsets(data, index),
                    confidentiality=confidentiality_judgment(data.get("confidentiality")),
                    confidence=confidence(data.get("confidence")),
                    detection_method="llm",
                    native_metadata=mapping(data.get("native_metadata")),
                    necessity=necessity_judgment(data.get("necessity")),
                )
            )
        return parsed
