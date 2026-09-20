"""Parser for Presidio Analyzer recognizer results."""

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
from ..schemas import ConfidentialityJudgment, NecessityJudgment


class PresidioParser:
    """Parse Presidio ``RecognizerResult`` objects or equivalent dictionaries."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse Presidio recognizer results into normalized candidates.

        Args:
            raw: Presidio ``RecognizerResult`` sequence.
            text: Original input text used to recover exact spans.

        Returns:
            Parsed structural candidates without generated entity IDs.

        Raises:
            DetectorParseError: If a result lacks valid fields or offsets.
        """
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
                    confidentiality=ConfidentialityJudgment(
                        value="private",
                        reason=explanation(field(item, "analysis_explanation"))
                        or f"Presidio identified this span as {entity_type}.",
                    ),
                    confidence=confidence(field(item, "score")),
                    detection_method=presidio_method(metadata),
                    native_metadata=metadata,
                    necessity=NecessityJudgment(
                        value=None, reason="Presidio detects PII but does not assess task necessity."
                    ),
                )
            )
        return parsed
