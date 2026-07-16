"""
CourtListener Legal Opinion Puller — async parallel extraction of contextually
sensitive legal text for Privacy Router benchmark augmentation.

Pulls court opinions with sensitive content (divorce, criminal, trade secrets,
corporate litigation) via the CourtListener REST API v4.

Requirements:
    - Free account at https://www.courtlistener.com/register/
    - API token from https://www.courtlistener.com/profile/api-token/
    - Set COURTLISTENER_API_TOKEN env var

Rate limits (free tier): 5 req/min, 50 req/hr, 125 req/day

Usage:
    export COURTLISTENER_API_TOKEN=your_token_here
    python experiments/courtlistener_pull.py --query "trade secrets"
    python experiments/courtlistener_pull.py --query "divorce AND custody" --max 50
    python experiments/courtlistener_pull.py --docket-id 12345  # fetch specific case
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# ── Configuration ──────────────────────────────────────────────
API_BASE = "https://www.courtlistener.com/api/rest/v4"
API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN", "")
OUTPUT_DIR = Path(__file__).resolve().parent / "datasets" / "courtlistener"
MAX_CONCURRENT = 3  # free tier: 5 req/min — be conservative


# ── Data Structures ────────────────────────────────────────────
@dataclass
class OpinionChunk:
    """Extracted text chunk from a court opinion, ready for labeling."""

    opinion_id: int
    case_name: str
    court: str
    date_filed: str
    citation: str
    snippet: str  # ~1500 char chunk from opinion text

    def to_label_dict(self) -> dict[str, Any]:
        return {
            "source": "courtlistener",
            "opinion_id": self.opinion_id,
            "case_name": self.case_name,
            "court": self.court,
            "date_filed": self.date_filed,
            "citation": self.citation,
            "text": self.snippet,
        }


# ── API Client ─────────────────────────────────────────────────
class CourtListenerClient:
    """Async httpx client for CourtListener REST API v4."""

    def __init__(self) -> None:
        if not API_TOKEN:
            raise RuntimeError(
                "COURTLISTENER_API_TOKEN not set. Get one at https://www.courtlistener.com/profile/api-token/"
            )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> CourtListenerClient:
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Token {API_TOKEN}"},
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=MAX_CONCURRENT),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def search_opinions(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Full-text search for opinions matching query."""
        assert self._client
        url = "/search/"
        params: dict[str, Any] = {
            "q": query,
            "type": "o",  # opinions only
            "page_size": min(max_results, 50),
        }
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])[:max_results]

    async def get_opinion_text(self, opinion_id: int) -> str:
        """Fetch full opinion text by cluster ID."""
        assert self._client
        # Try clusters endpoint for opinion text
        resp = await self._client.get(f"/clusters/{opinion_id}/")
        resp.raise_for_status()
        data = resp.json()

        # Get the opinion text — may be in plain_text or html_with_citations
        text = ""
        sub_opinions = data.get("sub_opinions", [])
        if sub_opinions:
            # Fetch first opinion's text
            op_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else ""
            if op_url:
                op_resp = await self._client.get(op_url.replace(API_BASE, ""))
                op_resp.raise_for_status()
                op_data = op_resp.json()
                text = op_data.get("plain_text", "") or op_data.get("html_with_citations", "")

        if not text:
            text = data.get("plain_text", "") or data.get("html_with_citations", "")

        return text


# ── Text Processing ────────────────────────────────────────────
HTML_TAG_RE = re.compile(r"<[^>]+>")
ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
PAGE_NUM_RE = re.compile(r"\n\s*\d+\s*\n")  # page numbers in legal text


def clean_opinion_text(text: str) -> str:
    """Clean legal opinion text: strip HTML, page numbers, normalize whitespace."""
    text = HTML_TAG_RE.sub(" ", text)
    text = ENTITY_RE.sub(" ", text)
    text = PAGE_NUM_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 1500) -> list[str]:
    """Split text into ~chunk_size character chunks at sentence boundaries."""
    sentences = SENTENCE_SPLIT_RE.split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 20:  # skip very short fragments
            continue
        current.append(s)
        current_len += len(s)
        if current_len >= chunk_size:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


# ── Sensitive Content Queries ──────────────────────────────────
SENSITIVE_QUERIES = [
    # Divorce & family law (high personal sensitivity)
    'divorce AND custody AND ("best interest" OR visitation)',
    '"marital property" AND (dissolution OR equitable distribution)',
    # Criminal law (identity/liberty sensitivity)
    '"criminal defendant" AND (sentencing OR "motion to suppress")',
    '"ineffective assistance of counsel" AND conviction',
    # Trade secrets & corporate (business sensitivity)
    '"trade secrets" AND (misappropriation OR "inevitable disclosure")',
    '"non-compete" AND ("legitimate business interest" OR enforceable)',
    # Medical/healthcare privacy
    '"HIPAA" AND (violation OR "protected health information")',
    '"medical malpractice" AND (negligence OR "standard of care")',
    # Financial fraud
    '"securities fraud" AND ("material misrepresentation" OR scienter)',
    '"insider trading" AND ("non-public information" OR tipper)',
]


# ── Entry Point ────────────────────────────────────────────────
async def pull_opinions(
    queries: list[str] | None = None,
    max_per_query: int = 10,
) -> list[dict[str, Any]]:
    """
    Search CourtListener for sensitive legal opinions, extract text chunks.

    Args:
        queries: List of search queries. Defaults to SENSITIVE_QUERIES.
        max_per_query: Max results to fetch per query.
    """
    if queries is None:
        queries = SENSITIVE_QUERIES

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with CourtListenerClient() as client:
        all_chunks: list[OpinionChunk] = []
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        for query in queries:
            print(f"\nSearching: {query[:80]}...")
            try:
                results = await client.search_opinions(query, max_per_query)
            except httpx.HTTPStatusError as e:
                print(f"  [WARN] HTTP {e.response.status_code} — rate limited? Skipping.")
                continue

            print(f"  Found {len(results)} opinions")
            if not results:
                continue

            async def fetch_one(result: dict) -> OpinionChunk | None:
                async with sem:
                    try:
                        opinion_id = result.get("id", 0)
                        case_name = result.get("caseName", "Unknown")
                        court = result.get("court", "Unknown")
                        date_filed = result.get("dateFiled", "")
                        citation = result.get("citation", "")

                        # Try to get the snippet from search result first
                        text = result.get("snippet", "") or result.get("text", "")
                        if len(text) < 200:
                            # Fetch full text
                            text = await client.get_opinion_text(opinion_id)

                        if not text or len(text) < 200:
                            return None

                        cleaned = clean_opinion_text(text)
                        paragraphs = chunk_text(cleaned)

                        # Return first substantial chunk
                        for p in paragraphs:
                            if len(p) > 200:
                                return OpinionChunk(
                                    opinion_id=opinion_id,
                                    case_name=case_name,
                                    court=court,
                                    date_filed=date_filed,
                                    citation=citation,
                                    snippet=p,
                                )

                        # Fallback: use first 1500 chars of full text
                        return OpinionChunk(
                            opinion_id=opinion_id,
                            case_name=case_name,
                            court=court,
                            date_filed=date_filed,
                            citation=citation,
                            snippet=cleaned[:1500],
                        )
                    except Exception as e:
                        print(f"    [WARN] {e}")
                        return None

            chunks = await asyncio.gather(*[fetch_one(r) for r in results])
            valid = [c for c in chunks if c is not None]
            all_chunks.extend(valid)
            print(f"    Extracted {len(valid)} chunks")

            # Rate limiting: wait between queries
            await asyncio.sleep(1.5)

    # Export
    output = [c.to_label_dict() for c in all_chunks]
    out_path = OUTPUT_DIR / "courtlistener_chunks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nTotal: {len(output)} chunks from {len(queries)} queries")
    print(f"Saved to {out_path}")
    return output


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Pull CourtListener legal opinions")
    parser.add_argument(
        "--query", type=str, default=None, help="Single search query (uses preset sensitive queries if omitted)"
    )
    parser.add_argument("--max", type=int, default=10, help="Max results per query (default: 10)")
    parser.add_argument("--docket-id", type=int, default=None, help="Fetch a specific docket by ID")
    args = parser.parse_args()

    if args.docket_id:
        async with CourtListenerClient() as client:
            text = await client.get_opinion_text(args.docket_id)
            cleaned = clean_opinion_text(text)
            chunks = chunk_text(cleaned)
            for i, c in enumerate(chunks[:5]):
                print(f"--- Chunk {i + 1} ({len(c)} chars) ---")
                print(c[:300])
                print()
    elif args.query:
        await pull_opinions(queries=[args.query], max_per_query=args.max)
    else:
        await pull_opinions(max_per_query=args.max)


if __name__ == "__main__":
    asyncio.run(main())
