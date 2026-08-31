from __future__ import annotations

from collections.abc import Sequence

from ..parser import (
    DetectorParseError,
    ParsedEntity,
    as_mapping,
    canonical_tag,
    confidence,
    optional_string,
    required_offsets,
    required_string,
    valid_offsets,
)
from ..schemas import Requiredness


class LFMParser:
    """Parse decoded LFM2.5 PII spans."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise DetectorParseError("LFM output must be a decoded span array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(raw):
            data = as_mapping(item)
            label = required_string(
                data.get("label") or data.get("entity_type") or data.get("category") or data.get("type"),
                f"LFM span {index} label",
            )
            start, end = required_offsets(data, index)
            if not valid_offsets(text, start, end):
                raise DetectorParseError(f"LFM span {index} has invalid offsets: {(start, end)!r}")
            span = optional_string(data.get("text") or data.get("span")) or text[start:end]
            metadata = {
                key: value
                for key, value in data.items()
                if key not in {"label", "entity_type", "category", "type", "start", "end", "text", "span", "score", "confidence"}
            }
            parsed.append(
                ParsedEntity(
                    tag=canonical_tag(label, span),
                    kind="structural",
                    native_label=label,
                    span=span,
                    offsets=(start, end),
                    reason=None,
                    confidence=confidence(data.get("confidence", data.get("score"))),
                    detection_method="token_classifier",
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed
