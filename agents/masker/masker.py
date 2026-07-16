"""Masker — Masking and hydration with fail-fast contracts.

The Masker handles both phases of the sensitive data lifecycle:
- **mask**: replace sensitive spans with placeholders, producing a
  :class:`MaskingContract`
- **hydrate**: resolve placeholders back to original values using
  the contract, raising :class:`HydrationError` if any placeholder
  is unresolvable.

Examples
--------
>>> masker = Masker()
>>> result = masker.mask(
...     text="주민번호 901212-1234567 전화 010-9876-5432",
...     records=[
...         {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
...         {"category": "MOBILE_PHONE_NUMBER", "span": "010-9876-5432", "start": 23, "end": 36},
...     ],
... )
>>> result.masked_text
'주민번호 [RESIDENT_REGISTRATION_NUMBER#1] 전화 [MOBILE_PHONE_NUMBER#1]'
>>> llm_response = f"처리 완료: {result.masked_text}"
>>> hydrated = masker.hydrate(llm_response, result.contract)
>>> "901212-1234567" in hydrated.hydrated_text
True
"""

from __future__ import annotations

import secrets
from typing import Any

from .schemas import HydrationResult, MaskingContract, MaskingResult

_PLACEHOLDER_LABEL = "SENSITIVE_DATA"


class HydrationError(Exception):
    """Raised when hydration fails due to unresolvable placeholders.

    Parameters
    ----------
    unresolved : list of str
        The placeholders that could not be resolved.
    """

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = unresolved
        super().__init__(
            f"Hydration failed: {len(unresolved)} unresolvable placeholder(s) found: {', '.join(unresolved[:5])}"
        )


class Masker:
    """Handles masking and hydration with fail-fast semantics.

    The masking/hydration pipeline is a two-phase contract:

    1. ``mask(text, records)`` → masked text + ``MaskingContract``
    2. Send masked text to LLM, receive response
    3. ``hydrate(response, contract)`` → restored text

    If step 3 encounters any placeholder not in the contract,
    :class:`HydrationError` is raised immediately.

    Examples
    --------
    Refer to the :ref:`module-level example <masker-example>`.
    """

    def mask(
        self,
        text: str,
        records: list[dict[str, Any]],
        *,
        placeholder_registry: dict[str, str] | None = None,
    ) -> MaskingResult:
        """Replace sensitive spans with request-scoped opaque placeholders.

        Placeholders use ``SENSITIVE_DATA#random8``. A caller that masks
        multiple fields from one request can share ``placeholder_registry`` so
        repeated values use one token. A new registry per request prevents
        cross-request linkage, and prompt-derived categories never cross the
        trust boundary.
        """
        if len(records) <= 1:
            sorted_records = records
        else:
            sorted_records = sorted(
                records,
                key=lambda record: record.get("start", 0),
                reverse=True,
            )

        placeholder_map: dict[str, str] = {}
        placeholders_by_span = placeholder_registry if placeholder_registry is not None else {}
        reserved_placeholders = set(placeholders_by_span.values())
        if len(reserved_placeholders) != len(placeholders_by_span):
            raise ValueError("Placeholder registry contains duplicate tokens.")
        masked = text

        for record in sorted_records:
            span = record.get("span", "")
            start = record.get("start", 0)
            end = record.get("end", 0)

            if masked[start:end] != span:
                found = masked.find(span)
                if found == -1:
                    continue
                start, end = found, found + len(span)

            placeholder = placeholders_by_span.get(span)
            if placeholder is None:
                while True:
                    candidate = f"{_PLACEHOLDER_LABEL}#{secrets.token_hex(4)}"
                    if candidate not in reserved_placeholders:
                        placeholder = candidate
                        break
                placeholders_by_span[span] = placeholder
                reserved_placeholders.add(placeholder)
            placeholder_map[placeholder] = span
            masked = masked[:start] + placeholder + masked[end:]

        return MaskingResult(
            masked_text=masked,
            contract=MaskingContract(
                placeholder_map=placeholder_map,
                count=len(placeholder_map),
            ),
        )

    def selective_mask(
        self,
        text: str,
        records: list[dict[str, Any]],
        mask_indices: list[int],
    ) -> MaskingResult:
        """Mask only the records at the given indices.

        Used when the PerRecordEvaluator determines some records are
        non-essential and can be safely masked while others must
        remain visible for the query to be meaningful.

        Parameters
        ----------
        text : str
            Original text.
        records : list of dict
            All extracted records. Each must have ``category``, ``span``,
            ``start``, and ``end``.
        mask_indices : list of int
            0-based indices into ``records`` indicating which to mask.

        Returns
        -------
        MaskingResult
            Partially masked text and contract.
        """
        to_mask = [records[i] for i in mask_indices if 0 <= i < len(records)]
        return self.mask(text, to_mask)

    def hydrate(self, text: str, contract: MaskingContract) -> HydrationResult:
        """Restore placeholders to their original values.

        Matches both bracketed ``[CATEGORY#hash]`` and bare
        ``CATEGORY#hash`` placeholders for robust hydration.

        Parameters
        ----------
        text : str
            LLM response text containing placeholders.
        contract : MaskingContract
            The contract produced by :meth:`mask`.

        Returns
        -------
        HydrationResult
            Hydrated text with original values restored.

        Raises
        ------
        HydrationError
            If *text* contains placeholders not present in the contract.

        Examples
        --------
        >>> contract = MaskingContract(placeholder_map={"RRN#1": "901212-1234567"}, count=1)
        >>> masker = Masker()
        >>> result = masker.hydrate("번호 RRN#1입니다.", contract)
        >>> result.hydrated_text
        '번호 901212-1234567입니다.'
        """
        unresolved = contract.validate_response(text)
        if unresolved:
            raise HydrationError(unresolved)

        hydrated, restored = contract.replace_registered(text)

        return HydrationResult(
            hydrated_text=hydrated,
            placeholders_restored=restored,
        )
