"""Schemas for the Masker package.

Pydantic models defining the masking/hydration contract. The
:class:`MaskingContract` is the immutable agreement between the
two phases — every placeholder created during masking must be
resolvable during hydration, or the operation fails fast.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, Field


class MaskingContract(BaseModel):
    """Immutable contract linking masking and hydration phases.

    Guarantees that every placeholder created while masking can be
    resolved during hydration. A hydration attempt encountering a
    placeholder NOT present in this contract fails immediately.

    Attributes
    ----------
    placeholder_map : dict
        Mapping of ``[CATEGORY#N]`` placeholders to original values.
    count : int
        Total number of unique placeholders in the contract.

    Examples
    --------
    >>> c = MaskingContract(placeholder_map={"[RRN#1]": "901212-1234567"}, count=1)
    >>> c.validate_response("번호 [RRN#1]입니다.")
    []
    """

    placeholder_map: dict[str, str] = Field(
        default_factory=dict,
        description="Placeholder-to-original-value mapping.",
        examples=[{"[RESIDENT_REGISTRATION_NUMBER#1]": "901212-1234567"}],
    )
    count: int = Field(
        default=0,
        ge=0,
        description="Total number of placeholders created.",
        examples=[3],
    )

    _TOKEN_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"(?P<token>"
        r"\[[A-Za-z][A-Za-z0-9_]{1,63}#[A-Za-z0-9_-]{1,64}\]"
        r"|[A-Za-z][A-Za-z0-9_]{1,63}#[A-Za-z0-9_-]{1,64}"
        r")"
        r"(?![A-Za-z0-9_#-])"
    )

    @property
    def canonical_placeholder_map(self) -> dict[str, str]:
        """Return contract keys in canonical bare ``CATEGORY#suffix`` form."""
        return {placeholder.strip("[]"): original for placeholder, original in self.placeholder_map.items()}

    @property
    def registered_placeholders(self) -> list[str]:
        """Return canonical contract keys in deterministic order."""
        return list(self.canonical_placeholder_map)

    def find_placeholder_tokens(self, text: str) -> list[str]:
        """Find canonical or legacy placeholder-like tokens in ``text``.

        Uppercase categories are treated as placeholder candidates. Mixed-case
        categories are candidates only when they case-fold to a category
        already present in this contract, which avoids interpreting ordinary
        strings such as ``Issue#deadbeef`` as privacy placeholders.
        """
        categories = {key.partition("#")[0].upper() for key in self.canonical_placeholder_map}
        found: list[str] = []
        for match in self._TOKEN_RE.finditer(text):
            token = match.group("token")
            category = token.strip("[]").partition("#")[0]
            if category == category.upper() or category.upper() in categories:
                found.append(token)
        return found

    def validate_response(self, text: str) -> list[str]:
        """Return placeholder-like tokens not registered by this contract."""
        registered = set(self.canonical_placeholder_map)
        return [token for token in self.find_placeholder_tokens(text) if token.strip("[]") not in registered]

    def replace_registered(self, text: str) -> tuple[str, int]:
        """Hydrate exact registered tokens without replacing token prefixes."""
        hydrated = text
        replacements = 0
        items = sorted(
            self.canonical_placeholder_map.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for placeholder, original in items:
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_])"
                rf"(?:\[{re.escape(placeholder)}\]|{re.escape(placeholder)})"
                rf"(?![A-Za-z0-9_#-])"
            )
            hydrated, count = pattern.subn(
                lambda _match, value=original: value,
                hydrated,
            )
            replacements += count
        return hydrated, replacements


class MaskingResult(BaseModel):
    """Result of a masking operation.

    Attributes
    ----------
    masked_text : str
        Text with sensitive spans replaced by placeholders.
    contract : MaskingContract
        Immutable contract for the subsequent hydration phase.

    Examples
    --------
    >>> c = MaskingContract(placeholder_map={"[RRN#1]": "901212-1234567"}, count=1)
    >>> r = MaskingResult(masked_text="주민번호 [RRN#1]", contract=c)
    >>> r.contract.count
    1
    """

    masked_text: str = Field(
        ...,
        description="Text with sensitive spans replaced by placeholders.",
        examples=["주민등록번호 [RESIDENT_REGISTRATION_NUMBER#1] 기재"],
    )
    contract: MaskingContract = Field(
        ...,
        description="The immutable hydration contract.",
        examples=[MaskingContract(placeholder_map={"[RRN#1]": "901212-1234567"}, count=1)],
    )


class HydrationResult(BaseModel):
    """Result of a hydration operation.

    Attributes
    ----------
    hydrated_text : str
        Text with placeholders restored to original values.
    placeholders_restored : int
        How many placeholder replacements were performed.

    Examples
    --------
    >>> r = HydrationResult(hydrated_text="주민번호 901212-1234567", placeholders_restored=1)
    >>> r.placeholders_restored
    1
    """

    hydrated_text: str = Field(
        ...,
        description="Text with all placeholders restored to original values.",
        examples=["주민등록번호 901212-1234567 기재"],
    )
    placeholders_restored: int = Field(
        ...,
        ge=0,
        description="Number of placeholder → original value replacements.",
        examples=[2],
    )
