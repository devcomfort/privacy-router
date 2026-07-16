"""
Convert AI Hub 판결서 익명처리 (Judgment Anonymization) data to Label Studio import format.

The AI Hub dataset contains Korean court opinions with PII-labeled name sections.
We reconstruct the full opinion text, chunk it, and classify as selective_mask
(names are PII but the opinion-reading task survives masking).

Usage:
    python experiments/aihub_convert.py
    python experiments/aihub_convert.py --merge  # merge with existing EDGAR chunks
"""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

# ── Configuration ──────────────────────────────────────────────
DATASET_DIR = Path(__file__).resolve().parent / "datasets" / "aihub"
LABEL_DIR = DATASET_DIR / "3.개방데이터" / "2.데이터(NIA)" / "Training" / "02.라벨링데이터"
OUTPUT_FILE = Path(__file__).resolve().parent / "datasets" / "aihub_chunks.json"
EDGAR_FILE = Path(__file__).resolve().parent / "datasets" / "edgar" / "edgar_chunks.json"
LS_IMPORT = Path(__file__).resolve().parent / "datasets" / "labelstudio_import.json"

CHUNK_SIZE = 1500
MAX_CASES_PER_CATEGORY = 50
MIN_CHUNK_LENGTH = 200

# PII section titles to exclude (these are label references, not case text)
PII_SECTION_RE = re.compile(r"#.*?#")

# Section titles that are real case content (not metadata)
CONTENT_TITLES = {
    "판시사항",
    "판결요지",
    "이유",
    "이    유",
    "주문",
    "청구취지",
    "청구취지 및 항소취지",
    "항소취지",
    "상고이유",
    "상고이유서",
    "제1심판결",
    "원심판결",
    "참조조문",
    "참조판례",
    "변론종결",
    "재판부",
    "변 호 인",
}


# ── Core Logic ─────────────────────────────────────────────────
def extract_case_text(data: dict[str, Any]) -> str | None:
    """Reconstruct full case text from sections, excluding PII labels."""
    parts: list[str] = []
    for sec in data.get("sections", []):
        title = sec.get("title", "")
        text = sec.get("text", "").strip()
        if not text:
            continue
        # Skip PII-labeled sections (these reference entities, not case content)
        if PII_SECTION_RE.search(title) and len(text) < 100:
            continue
        # Skip very short metadata
        if len(text) < 15 and title not in CONTENT_TITLES:
            continue
        parts.append(text)

    full_text = "\n\n".join(parts)
    if len(full_text) < MIN_CHUNK_LENGTH:
        return None
    return full_text


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks at natural boundaries (period, newline)."""
    # Split on Korean/English sentence endings
    sentences = re.split(r"(?<=[.!?。])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        current.append(s)
        current_len += len(s)
        if current_len >= size:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def read_zip_jsons(zip_path: Path, max_files: int = 0) -> list[dict[str, Any]]:
    """Read all JSON files from a zip archive."""
    results: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json")]
        if max_files:
            names = names[:max_files]
        for name in names:
            with zf.open(name) as f:
                try:
                    data = json.load(f)
                    results.append(data)
                except json.JSONDecodeError:
                    continue
    return results


# ── Entry Point ────────────────────────────────────────────────
def convert_all(merge: bool = False) -> list[dict[str, Any]]:
    """
    Read AI Hub labeled data, extract text chunks, export for Label Studio.

    Args:
        merge: If True, merge with existing EDGAR chunks into labelstudio_import.json.
    """
    all_chunks: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()

    for zip_name in ["TL_01.일반판결.zip", "TL_02.1-2-최종심.zip"]:
        zip_path = LABEL_DIR / zip_name
        if not zip_path.exists():
            print(f"[SKIP] {zip_path} not found")
            continue

        print(f"Reading {zip_name}...")
        cases = read_zip_jsons(zip_path)
        print(f"  {len(cases)} cases loaded")

        for case in cases:
            info = case.get("info", {})
            case_class = info.get("caseClass", "기타")
            if category_counts[case_class] >= MAX_CASES_PER_CATEGORY:
                continue

            text = extract_case_text(case)
            if not text:
                continue

            chunks = chunk_text(text)
            for ch in chunks:
                if len(ch) < MIN_CHUNK_LENGTH:
                    continue
                all_chunks.append(
                    {
                        "source": "aihub",
                        "case_class": case_class,
                        "case_name": info.get("caseNm", ""),
                        "case_no": info.get("caseNo", ""),
                        "court": info.get("courtNm", ""),
                        "court_type": info.get("courtType", ""),
                        "date": info.get("judmnAdjuDe", ""),
                        "text": ch,
                    }
                )
                category_counts[case_class] += 1

    print(f"\nExported {len(all_chunks)} chunks by category:")
    for cat, n in category_counts.most_common():
        print(f"  {cat}: {n}")

    # Save standalone
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Saved {OUTPUT_FILE}")

    # Convert to Label Studio format
    ls_tasks = []
    for i, ch in enumerate(all_chunks):
        ls_tasks.append(
            {
                "id": 10000 + i,  # high IDs to not collide with EDGAR
                "data": {"text": ch["text"]},
                "meta": {
                    "source": "aihub",
                    "case_class": ch["case_class"],
                    "case_name": ch["case_name"],
                    "court": ch["court"],
                    "date": ch["date"],
                },
            }
        )

    # Merge with EDGAR if requested
    if merge and EDGAR_FILE.exists():
        with open(EDGAR_FILE) as f:
            edgar = json.load(f)
        for i, ch in enumerate(edgar):
            ls_tasks.append(
                {
                    "id": i + 1,
                    "data": {"text": ch["text"]},
                    "meta": {
                        "source": "edgar",
                        "ticker": ch.get("ticker", ""),
                        "company": ch.get("company", ""),
                        "fiscal_year": ch.get("fiscal_year", ""),
                        "section": ch.get("section", ""),
                    },
                }
            )
        print(f"Merged {len(edgar)} EDGAR chunks → {len(ls_tasks)} total tasks")

    with open(LS_IMPORT, "w", encoding="utf-8") as f:
        json.dump(ls_tasks, f, ensure_ascii=False, indent=2)
    print(f"Label Studio import: {LS_IMPORT} ({len(ls_tasks)} tasks)")

    return all_chunks


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert AI Hub data to Label Studio format")
    parser.add_argument(
        "--merge", action="store_true", help="Merge with EDGAR chunks into unified labelstudio_import.json"
    )
    args = parser.parse_args()
    convert_all(merge=args.merge)
