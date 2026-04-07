#!/usr/bin/env python3
"""
Filter out review-listed sign-offs from the shipped dataset and assemble a
Netlify-ready static folder.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
HTML_SOURCE = ROOT / "sign-offs.html"
REVIEW_SOURCE = ROOT / "signoffs-bilingual-review.md"
DATA_JSON = ROOT / "signoffs-bilingual.json"
DATA_JS = ROOT / "signoffs-bilingual.js"

FULL_JSON_BACKUP = ROOT / ".signoffs-bilingual-full.json"
FULL_JS_BACKUP = ROOT / ".signoffs-bilingual-full.js"

NETLIFY_DIR = ROOT / "netlify"
NETLIFY_HTML = NETLIFY_DIR / "index.html"
NETLIFY_JSON = NETLIFY_DIR / "signoffs-bilingual.json"
NETLIFY_JS = NETLIFY_DIR / "signoffs-bilingual.js"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_js_dataset(path: Path, payload: list[dict[str, Any]]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        "// Generated for runtime use. Safe to load from file:// or HTTP.\n"
        f"window.SIGNOFFS_DATA = {serialized};\n",
        encoding="utf-8",
    )


def ensure_backups() -> None:
    if not FULL_JSON_BACKUP.exists():
        shutil.copy2(DATA_JSON, FULL_JSON_BACKUP)
    if not FULL_JS_BACKUP.exists():
        shutil.copy2(DATA_JS, FULL_JS_BACKUP)


def parse_excluded_indices(review_path: Path) -> set[int]:
    excluded: set[int] = set()
    for line in review_path.read_text(encoding="utf-8").splitlines():
        duplicate_match = re.match(r"^\s*-\s+#(\d+):", line)
        if duplicate_match:
            excluded.add(int(duplicate_match.group(1)))
            continue
        entry_match = re.match(r"^(\d+)\.\s+Issues:", line)
        if entry_match:
            excluded.add(int(entry_match.group(1)))
    return excluded


def filter_dataset(records: list[dict[str, Any]], excluded_indices: set[int]) -> list[dict[str, Any]]:
    filtered = [
        record
        for index, record in enumerate(records, start=1)
        if index not in excluded_indices
    ]
    return filtered


def build_netlify_folder(filtered_records: list[dict[str, Any]]) -> None:
    NETLIFY_DIR.mkdir(exist_ok=True)
    shutil.copy2(HTML_SOURCE, NETLIFY_HTML)
    write_json(NETLIFY_JSON, filtered_records)
    write_js_dataset(NETLIFY_JS, filtered_records)


def main() -> int:
    ensure_backups()

    full_records = json.loads(FULL_JSON_BACKUP.read_text(encoding="utf-8"))
    if not isinstance(full_records, list):
        raise ValueError("Full dataset backup must be a JSON array")

    excluded_indices = parse_excluded_indices(REVIEW_SOURCE)
    filtered_records = filter_dataset(full_records, excluded_indices)

    write_json(DATA_JSON, filtered_records)
    write_js_dataset(DATA_JS, filtered_records)
    build_netlify_folder(filtered_records)

    print(
        f"Excluded {len(excluded_indices)} review-listed entries. "
        f"Published dataset now has {len(filtered_records)} entries. "
        f"Netlify folder created at {NETLIFY_DIR}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
