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

from typing import Any

from .schemas import HydrationResult, MaskingContract, MaskingResult


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
            f"Hydration failed: {len(unresolved)} unresolvable "
            f"placeholder(s) found: {', '.join(unresolved[:5])}"
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

    def mask(self, text: str, records: list[dict[str, Any]]) -> MaskingResult:
        """Replace sensitive spans with stable placeholders.

        Parameters
        ----------
        text : str
            The original text to mask.
        records : list of dict
            Extraction records. Each must have ``category``, ``span``,
            ``start``, and ``end``.

        Returns
        -------
        MaskingResult
            Masked text and the immutable hydration contract.

        Raises
        ------
        ValueError
            If a record's span cannot be located in *text*.

        Examples
        --------
        >>> masker = Masker()
        >>> result = masker.mask("주민번호 901212-1234567", [{"category": "RRN", "span": "901212-1234567", "start": 5, "end": 19}])
        >>> result.masked_text
        '주민번호 [RRN#1]'
        """
        sorted_records = sorted(
            records,
            key=lambda r: r.get("start", 0),
            reverse=True,
        )

        placeholder_map: dict[str, str] = {}
        counter: dict[str, int] = {}
        masked = text

        for record in sorted_records:
            category = record.get("category", "REDACTED")
            span = record.get("span", "")
            start = record.get("start", 0)
            end = record.get("end", 0)

            if masked[start:end] != span:
                found = masked.find(span)
                if found == -1:
                    raise ValueError(
                        f"Span '{span}' not found in text at "
                        f"expected position [{start}:{end}]"
                    )
                start, end = found, found + len(span)

            counter[category] = counter.get(category, 0) + 1
            placeholder = f"[{category}#{counter[category]}]"
            masked = masked[:start] + placeholder + masked[end:]
            placeholder_map[placeholder] = span

        return MaskingResult(
            masked_text=masked,
            contract=MaskingContract(
                placeholder_map=placeholder_map,
                count=len(placeholder_map),
            ),
        )

    def hydrate(
        self, text: str, contract: MaskingContract
    ) -> HydrationResult:
        """Restore placeholders to their original values.

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
        >>> contract = MaskingContract(placeholder_map={"[RRN#1]": "901212-1234567"}, count=1)
        >>> masker = Masker()
        >>> result = masker.hydrate("번호 [RRN#1]입니다.", contract)
        >>> result.hydrated_text
        '번호 901212-1234567입니다.'
        """
        unresolved = contract.validate_response(text)
        if unresolved:
            raise HydrationError(unresolved)

        hydrated = text
        restored = 0
        for placeholder, original in contract.placeholder_map.items():
            if placeholder in hydrated:
                hydrated = hydrated.replace(placeholder, original)
                restored += 1

        return HydrationResult(
            hydrated_text=hydrated,
            placeholders_restored=restored,
        )
