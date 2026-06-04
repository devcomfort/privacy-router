"""Streaming hydration — resolve placeholders in token streams.

When the backend LLM streams masked text back, placeholders like
``[STUDENT_AFFILIATION#1]`` may be split across chunk boundaries.
This module buffers chunks and hydrates only complete placeholders,
forwarding the rest as-is.

Examples
--------
>>> from agents.masker import Masker, MaskingContract
>>> c = MaskingContract(placeholder_map={'[NAME#1]': '김동현'}, count=1)
>>> h = StreamingHydrator(c)
>>> list(h.feed('안녕하세요 [NAM'))
[]
>>> list(h.feed('E#1]님!'))
['안녕하세요 ', '김동현', '님!']
>>> list(h.flush())
[]
"""

from __future__ import annotations

import re

from agents.masker.schemas import MaskingContract

# Placeholders look like [CATEGORY#N] where category is SCREAMING_SNAKE_CASE
_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*#\d+\]")
_MAX_PLACEHOLDER_LEN = 64  # conservative upper bound for any placeholder


class StreamingHydrator:
    """Buffers token chunks and hydrates complete placeholders.

    Parameters
    ----------
    contract : MaskingContract or None
        The hydration contract from the Masker.  If ``None``, chunks
        are forwarded unchanged (no-op hydrator).

    Examples
    --------
    >>> c = MaskingContract(placeholder_map={'[NAME#1]': '김동현'}, count=1)
    >>> h = StreamingHydrator(c)
    >>> list(h.feed('안녕 [NAM'))
    ['안녕 ']
    >>> list(h.feed('E#1]님'))
    ['김동현', '님']
    """

    def __init__(self, contract: MaskingContract | None) -> None:
        self._contract = contract
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        """Feed a new chunk and return hydrated pieces as they become ready.

        Parameters
        ----------
        chunk : str
            A fragment of text from the LLM stream.

        Yields
        ------
        str
            Hydrated text pieces.  May be empty if nothing is ready.
        """
        if self._contract is None:
            return [chunk]

        self._buffer += chunk

        # Find the last potential placeholder start '[' that could be
        # the beginning of a multi-chunk placeholder
        last_open = self._buffer.rfind("[")
        if last_open == -1 or len(self._buffer) - last_open > _MAX_PLACEHOLDER_LEN:
            # No partial placeholder — hydrate everything and flush
            result = self._hydrate_all(self._buffer)
            self._buffer = ""
            return [result]

        # Split: everything before the last '[' is safe to hydrate and emit
        safe = self._buffer[:last_open]
        self._buffer = self._buffer[last_open:]

        if safe:
            return [self._hydrate_all(safe)]
        return []

    def flush(self) -> list[str]:
        """Hydrate and return any remaining buffered text.

        Yields
        ------
        str
            Final hydrated text (may be empty).
        """
        if self._contract is None:
            return []
        if self._buffer:
            result = self._hydrate_all(self._buffer)
            self._buffer = ""
            return [result]
        return []

    # ── Internal ─────────────────────────────────────────────────────────────

    def _hydrate_all(self, text: str) -> str:
        """Replace all placeholders in *text* with original values."""
        if self._contract is None:
            return text
        result = text
        for placeholder, original in self._contract.placeholder_map.items():
            result = result.replace(placeholder, original)
        return result
