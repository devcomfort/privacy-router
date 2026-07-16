"""
Export EDGAR chunks to Label Studio import format with optional pre-annotations.

Usage:
    python experiments/labelstudio_export.py
    python experiments/labelstudio_export.py --pre-label  # run E4B pre-labeling first
"""

from __future__ import annotations

import json
from pathlib import Path

EDGAR_CHUNKS = Path(__file__).resolve().parent / "datasets" / "edgar" / "edgar_chunks.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "datasets" / "labelstudio_import.json"


def export_for_labelstudio(chunks: list[dict], pre_label: bool = False) -> list[dict]:
    """
    Convert EDGAR chunks to Label Studio task format.

    Label Studio expects:
    [
      {
        "data": {"text": "..."},
        "predictions": [{
          "model_version": "privacy-router-v1",
          "result": [{
            "from_name": "sensitivity",
            "to_name": "text",
            "type": "choices",
            "value": {"choices": ["block"]}
          }]
        }]
      },
      ...
    ]
    """
    tasks = []
    for i, chunk in enumerate(chunks):
        task: dict = {
            "id": i + 1,
            "data": {
                "text": chunk["text"],
            },
            "meta": {
                "source": "edgar",
                "ticker": chunk["ticker"],
                "company": chunk["company"],
                "fiscal_year": chunk["fiscal_year"],
                "filing_date": chunk["filing_date"],
                "section": chunk["section"],
            },
        }
        if pre_label:
            # Add placeholder pre-annotation (model to fill in later)
            task["predictions"] = [
                {
                    "model_version": "pending",
                    "result": [
                        {
                            "from_name": "sensitivity",
                            "to_name": "text",
                            "type": "choices",
                            "value": {"choices": ["selective_mask"]},
                        }
                    ],
                }
            ]
        tasks.append(task)
    return tasks


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Export EDGAR chunks to Label Studio format")
    parser.add_argument("--pre-label", action="store_true", help="Add placeholder pre-annotations")
    args = parser.parse_args()

    with open(EDGAR_CHUNKS) as f:
        chunks = json.load(f)

    tasks = export_for_labelstudio(chunks, pre_label=args.pre_label)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(tasks)} tasks to {OUTPUT_FILE}")
    print("\nLabel Studio setup:")
    print(
        "  1. docker run -it -p 8080:8080 -v $(pwd)/labelstudio-data:/label-studio/data heartexlabs/label-studio:latest"
    )
    print(f"  2. Create project → Import → Upload {OUTPUT_FILE}")
    print("  3. Labeling config XML: see experiments/labelstudio_config.xml")


if __name__ == "__main__":
    main()
