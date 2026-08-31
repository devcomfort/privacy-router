"""Parser for typed OpenAI Privacy Filter output."""

from __future__ import annotations

from collections.abc import Sequence

from ..parser import (
    DetectorParseError,
    ParsedEntity,
    as_mapping,
    canonical_tag,
    optional_string,
    required_offsets,
    required_string,
    valid_offsets,
)
from ..schemas import Requiredness


class OPFParser:
    """Parse typed OpenAI Privacy Filter output without applying redaction."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse OPF typed spans without applying redaction.

        Args:
            raw: OPF ``RedactionResult``, mapping, or JSON string.
            text: Original input text used to validate span offsets.

        Returns:
            Parsed structural candidates without generated entity IDs.

        Raises:
            DetectorParseError: If typed spans or offsets are invalid.
        """
        payload = as_mapping(raw)
        spans = payload.get("detected_spans")
        if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
            raise DetectorParseError("OPF output detected_spans must be an array")

        parsed: list[ParsedEntity] = []
        for index, item in enumerate(spans):
            data = as_mapping(item)
            label = required_string(data.get("label"), f"OPF span {index} label")
            start, end = required_offsets(data, index)
            if not valid_offsets(text, start, end):
                raise DetectorParseError(f"OPF span {index} has invalid offsets: {(start, end)!r}")
            span = optional_string(data.get("text")) or text[start:end]
            metadata = {key: value for key, value in data.items() if key not in {"label", "start", "end", "text"}}
            parsed.append(
                ParsedEntity(
                    tag=canonical_tag(label, span),
                    kind="structural",
                    native_label=label,
                    span=span,
                    offsets=(start, end),
                    reason=None,
                    confidence=None,
                    detection_method="token_classifier",
                    native_metadata=metadata,
                    is_required=Requiredness(value=None, reason="not assessed"),
                )
            )
        return parsed
