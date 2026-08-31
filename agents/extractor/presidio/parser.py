from __future__ import annotations

from collections.abc import Sequence

from ..parser import (
    DetectorParseError,
    ParsedEntity,
    canonical_tag,
    confidence,
    explanation,
    field,
    mapping,
    presidio_method,
    required_offsets,
    required_string,
    valid_offsets,
)
from ..schemas import Requiredness


class PresidioParser:
    """Parse Presidio ``RecognizerResult`` objects or equivalent dictionaries."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise DetectorParseError("Presidio output must be a result array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(raw):
            entity_type = required_string(field(item, "entity_type"), f"Presidio result {index} entity_type")
            start, end = required_offsets(item, index)
            if not valid_offsets(text, start, end):
                raise DetectorParseError(f"Presidio result {index} has invalid offsets: {(start, end)!r}")
            metadata = mapping(field(item, "recognition_metadata"))
            parsed.append(
                ParsedEntity(
                    tag=canonical_tag(entity_type, text[start:end]),
                    kind="structural",
                    native_label=entity_type,
                    span=text[start:end],
                    offsets=(start, end),
                    reason=explanation(field(item, "analysis_explanation")),
                    confidence=confidence(field(item, "score")),
                    detection_method=presidio_method(metadata),
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed
