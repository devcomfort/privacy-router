"""
EDGAR 10-K Puller — async parallel extraction of contextually sensitive sections.

Pulls 10-K filings from SEC EDGAR, extracts Item 1A (Risk Factors) and
Item 3 (Legal Proceedings), chunks into paragraphs, and exports for labeling.

Usage:
    python experiments/edgar_pull.py --tickers AAPL,MSFT,GOOGL --years 2023,2024
    python experiments/edgar_pull.py --ciks 320193,789019 --years 2024

SEC Requirements:
    - User-Agent header with company name + email (10 req/s limit)
    - No API key needed for public data APIs
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# ── Configuration ──────────────────────────────────────────────
SEC_USER_AGENT = "PrivacyRouter/1.0 (dearkimdh02@gmail.com)"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}.txt"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
OUTPUT_DIR = Path(__file__).resolve().parent / "datasets" / "edgar"
MAX_CONCURRENT = 8


# ── Data Structures ────────────────────────────────────────────
@dataclass
class FilingMeta:
    """Metadata for a single 10-K filing."""

    cik: str
    ticker: str
    company_name: str
    fiscal_year: int
    accession_number: str
    filing_date: str
    primary_document: str

    @property
    def acc_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def cik_stripped(self) -> str:
        return self.cik.lstrip("0")

    @property
    def cik_padded(self) -> str:
        return self.cik.zfill(10)

    @property
    def txt_url(self) -> str:
        return SEC_ARCHIVE_URL.format(self.cik_stripped, self.acc_no_dashes, self.accession_number)


@dataclass
class FilingChunk:
    """Extracted text chunk from a filing, ready for labeling."""

    filing: FilingMeta
    section: str
    text: str

    def to_label_dict(self) -> dict[str, Any]:
        return {
            "source": "edgar",
            "cik": self.filing.cik,
            "ticker": self.filing.ticker,
            "company": self.filing.company_name,
            "fiscal_year": self.filing.fiscal_year,
            "filing_date": self.filing.filing_date,
            "section": self.section,
            "text": self.text,
        }


# ── SEC API Client ─────────────────────────────────────────────
class SECClient:
    """Async httpx client with SEC-compliant User-Agent."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SECClient:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=MAX_CONCURRENT),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def get_json(self, url: str) -> dict[str, Any]:
        assert self._client
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def get_text(self, url: str) -> str:
        assert self._client
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.text


# ── Resolution ─────────────────────────────────────────────────
async def resolve_cik_map(client: SECClient) -> dict[str, dict[str, str]]:
    """Fetch company_tickers.json → {ticker: {cik_str, title}}."""
    data = await client.get_json(SEC_COMPANY_TICKERS_URL)
    return {v["ticker"]: v for v in data.values()}


async def get_10k_filings(
    client: SECClient,
    cik: str,
    ticker: str,
    years: list[int],
) -> list[FilingMeta]:
    """Fetch filing history, filter to 10-K for requested years."""
    padded = cik.zfill(10)
    url = SEC_SUBMISSIONS_URL.format(padded)
    data = await client.get_json(url)

    filings: list[FilingMeta] = []
    forms = data.get("filings", {}).get("recent", {})
    if not forms:
        return filings

    n = len(forms["accessionNumber"])
    for i in range(n):
        form_type = forms["form"][i]
        if form_type not in ("10-K", "10-K/A"):
            continue

        fy_match = re.search(r"20(\d{2})", forms.get("reportDate", [""] * n)[i])
        if not fy_match:
            fy_match = re.search(r"20(\d{2})", forms["filingDate"][i])
        if not fy_match:
            continue
        fiscal_year = 2000 + int(fy_match.group(1))
        if years and fiscal_year not in years:
            continue

        filings.append(
            FilingMeta(
                cik=cik,
                ticker=ticker,
                company_name=data.get("name", ticker),
                fiscal_year=fiscal_year,
                accession_number=forms["accessionNumber"][i],
                filing_date=forms["filingDate"][i],
                primary_document=forms["primaryDocument"][i],
            )
        )

    return filings


# ── Text Extraction ────────────────────────────────────────────
# Section header patterns: "Item 1A. Risk Factors" / "Item 3. Legal Proceedings"
SECTION_START_RE = re.compile(
    r"""ITEM\s+1A[.]\s+R\s*I\s*S\s*K\s+F\s*A\s*C\s*T\s*O\s*R\s*S"""
    r"""|ITEM\s+3[.]\s+LEGAL\s+PROCEEDINGS""",
    re.IGNORECASE,
)
# Stop at exhibits/signatures or next unrelated ITEM
END_OF_BODY_RE = re.compile(
    r"ITEM\s+1[56][.]|SIGNATURES|EXHIBIT\s+INDEX|PART\s+IV",
    re.IGNORECASE,
)
NEXT_ANY_ITEM_RE = re.compile(r"ITEM\s+\d+[A-Z]?[.]", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
HTML_TAG_RE = re.compile(r"<[^>]+>")
TABLE_RE = re.compile(r"<TABLE[^>]*>.*?</TABLE>", re.DOTALL | re.IGNORECASE)
ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def clean_html(text: str) -> str:
    """Strip HTML tags, entities, normalize whitespace."""
    text = TABLE_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = ENTITY_RE.sub(" ", text)
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
        if not s:
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


def extract_sections(text: str) -> list[tuple[str, str]]:
    """Extract Item 1A + Item 3 sections from 10-K body text."""
    # Truncate at end of body (before exhibits/signatures)
    body_end = END_OF_BODY_RE.search(text)
    body = text[: body_end.start()] if body_end else text

    results: list[tuple[str, str]] = []
    matches = list(SECTION_START_RE.finditer(body))
    for i, m in enumerate(matches):
        matched = m.group().upper()
        if "1A" in matched and ("RISK" in matched or "RIS" in matched):
            section_name = "risk_factors"
        elif "3" in matched and "LEGAL" in matched:
            section_name = "legal_proceedings"
        else:
            continue

        # End = next section match (for all but last), or next ITEM after 200+ chars
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            # For last match, find next ITEM header (skip inline refs by requiring 200+ char gap)
            after_start = body[m.start() + 100 :]
            next_item = NEXT_ANY_ITEM_RE.search(after_start)
            end_pos = m.start() + 100 + next_item.start() if next_item else len(body)

        section_text = body[m.start() : end_pos].strip()
        if len(section_text) > 100:
            results.append((section_name, section_text))

    return results


async def pull_10k_text(client: SECClient, filing: FilingMeta) -> list[FilingChunk]:
    """Download 10-K full text and extract sections."""
    try:
        raw = await client.get_text(filing.txt_url)
    except httpx.HTTPStatusError as e:
        print(f"  [WARN] HTTP {e.response.status_code} for {filing.ticker}")
        return []
    except Exception as e:
        print(f"  [WARN] {e} for {filing.ticker}")
        return []

    cleaned = clean_html(raw)
    result: list[FilingChunk] = []
    for section_name, section_text in extract_sections(cleaned):
        for chunk_text_blob in chunk_text(section_text):
            result.append(
                FilingChunk(
                    filing=filing,
                    section=section_name,
                    text=chunk_text_blob,
                )
            )
    return result


# ── Entry Point ────────────────────────────────────────────────
async def pull_all(
    tickers: list[str],
    ciks: list[str] | None = None,
    years: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Pull 10-K filings for given tickers/CIKs and fiscal years.

    Args:
        tickers: Stock tickers (e.g. ["AAPL", "MSFT"]).
        ciks: Optional CIK numbers as strings (e.g. ["320193"]).
        years: Optional fiscal years (e.g. [2023, 2024]). None = all.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_years = years or []

    async with SECClient() as client:
        ticker_map = await resolve_cik_map(client)

        all_filings: list[FilingMeta] = []
        tasks = []

        for ticker in tickers:
            info = ticker_map.get(ticker.upper())
            if not info:
                print(f"[SKIP] Ticker '{ticker}' not found in SEC ticker map")
                continue
            cik = str(info["cik_str"])
            tasks.append(get_10k_filings(client, cik, ticker, target_years))

        if ciks:
            for cik in ciks:
                tasks.append(get_10k_filings(client, cik, cik, target_years))

        results = await asyncio.gather(*tasks)
        for r in results:
            all_filings.extend(r)

        print(f"Found {len(all_filings)} 10-K filings across {len(tickers)} tickers")

        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def pull_one(filing: FilingMeta) -> list[FilingChunk]:
            async with sem:
                print(f"  Pulling {filing.ticker} FY{filing.fiscal_year} ({filing.filing_date})...")
                file_chunks = await pull_10k_text(client, filing)
                print(f"    -> {len(file_chunks)} chunks")
                return file_chunks

        chunk_lists = await asyncio.gather(*[pull_one(f) for f in all_filings])

    all_chunks: list[dict[str, Any]] = []
    for cl in chunk_lists:
        all_chunks.extend(c.to_label_dict() for c in cl)

    print(f"\nExtracted {len(all_chunks)} text chunks total")

    out_path = OUTPUT_DIR / "edgar_chunks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Saved to {out_path}")
    return all_chunks


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Pull EDGAR 10-K filings")
    parser.add_argument(
        "--tickers", type=str, default="AAPL,MSFT,GOOGL", help="Comma-separated tickers (default: AAPL,MSFT,GOOGL)"
    )
    parser.add_argument("--ciks", type=str, default=None, help="Comma-separated CIK numbers")
    parser.add_argument("--years", type=str, default=None, help="Comma-separated fiscal years (default: all)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    ciks = [c.strip() for c in args.ciks.split(",") if c.strip()] if args.ciks else None
    years = [int(y.strip()) for y in args.years.split(",") if y.strip()] if args.years else None

    await pull_all(tickers=tickers, ciks=ciks, years=years)


if __name__ == "__main__":
    asyncio.run(main())
