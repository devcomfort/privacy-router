"""Parser for decoded LiquidAI LFM2.5 detector spans."""

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
from ..schemas import ConfidentialityJudgment, NecessityJudgment


class LFMParser:
    """Parse decoded LFM2.5 PII spans."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse decoded LFM2.5 spans into structural candidates.

        Args:
            raw: LFM decoder span sequence.
            text: Original input text used to recover missing span text.

        Returns:
            Parsed structural candidates without generated entity IDs.

        Raises:
            DetectorParseError: If a decoded span is malformed.
        """
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
                if key
                not in {
                    "label",
                    "entity_type",
                    "category",
                    "type",
                    "start",
                    "end",
                    "text",
                    "span",
                    "score",
                    "confidence",
                }
            }
            parsed.append(
                ParsedEntity(
                    tag=canonical_tag(label, span),
                    kind="structural",
                    native_label=label,
                    span=span,
                    offsets=(start, end),
                    confidentiality=ConfidentialityJudgment(
                        value="private", reason=f"LFM PII detector identified this span as {label}."
                    ),
                    confidence=confidence(data.get("confidence", data.get("score"))),
                    detection_method="token_classifier",
                    native_metadata=metadata,
                    necessity=NecessityJudgment(
                        value=None, reason="LFM detects PII but does not assess task necessity."
                    ),
                )
            )
        return parsed
