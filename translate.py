#!/usr/bin/env python3
"""
Build the bilingual sign-off dataset from the markdown snapshot.

Primary output:
  - signoffs-bilingual.json

Secondary output:
  - signoffs-bilingual-review.md

The script prefers the Anthropic API when ANTHROPIC_API_KEY is available and
falls back to the local `claude` CLI when installed and authenticated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_MD = ROOT / "good-sign-offs-2026-03-19.md"
OUTPUT_JSON = ROOT / "signoffs-bilingual.json"
OUTPUT_JS = ROOT / "signoffs-bilingual.js"
REVIEW_MD = ROOT / "signoffs-bilingual-review.md"
CACHE_JSON = ROOT / ".signoffs-bilingual-cache.json"

CLI_MODEL_DEFAULT = "sonnet"
API_MODEL_DEFAULT = "claude-sonnet-4-20250514"
ANTHROPIC_VERSION = "2023-06-01"


TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "hi": {"type": ["string", "null"]},
                    "translatable": {"type": "boolean"},
                },
                "required": ["id", "hi", "translatable"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You translate English email sign-offs into Hindi adaptations.

Output JSON only through the provided schema/tool.

Rules:
- These are poetic adaptations, not literal translations.
- Keep them short. Prefer one line, a phrase, an image, or a fragment.
- Use everyday Hindi or Hindustani. Urdu-Hindi mix is welcome.
- Aim for warmth, wit, texture, weather, food, memory, travel, family, or sensory detail when appropriate.
- Avoid Sanskritized phrasing unless the original clearly demands it.
- Do not add explanation inside the translation.
- Do not use punctuation other than commas or full stops in the Hindi output.
- Most translations should end with a comma or a full stop.
- If the source is gibberish, an opaque inside joke, only initials, or otherwise not meaningfully translatable, set hi to null and translatable to false.
- If the source is another language and translating it would flatten or distort it, you may also set hi to null and translatable to false.
- Preserve the emotional register. Some entries should remain playful, weird, abrupt, or understated.
- Return one result per input item, preserving ids exactly.
- When translatable is false, hi must be null.
"""


DISALLOWED_PUNCTUATION = set("!?:;()[]{}\"'`~@#$%^&*_+=/\\|<>")


@dataclass(frozen=True)
class HindiOriginal:
    index: int
    hi: str
    en: str


@dataclass(frozen=True)
class EnglishEntry:
    index: int
    en: str
    contributor: str | None
    date: str | None


@dataclass(frozen=True)
class BatchItem:
    id: int
    en: str


def normalize_line(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_multiline_text(text: str) -> str:
    lines = [normalize_line(line) for line in text.splitlines()]
    return "\n".join(lines).strip()


def iso_utc_from_snapshot(text: str | None) -> str | None:
    if not text:
        return None
    return f"{text.replace(' ', 'T')}:00Z"


def parse_snapshot(path: Path) -> tuple[list[HindiOriginal], list[EnglishEntry]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    section: str | None = None
    current: dict[str, Any] | None = None
    entries: list[dict[str, Any]] = []

    for line_no, line in enumerate(raw_lines, start=1):
        if line.startswith("## Hindi"):
            section = "hi"
            continue
        if line.startswith("## English"):
            section = "en"
            continue
        if line.strip() == "---":
            if current:
                entries.append(current)
                current = None
            continue
        match = re.match(r"^(\d+)\.\s+(.*)$", line)
        if match:
            if current:
                entries.append(current)
            current = {
                "section": section,
                "index": int(match.group(1)),
                "parts": [match.group(2)],
                "line_no": line_no,
            }
            continue
        if current and line.strip() and not line.startswith("Source:"):
            current["parts"].append(line)

    if current:
        entries.append(current)

    hindi_originals: list[HindiOriginal] = []
    english_entries: list[EnglishEntry] = []

    for entry in entries:
        body = "\n".join(entry["parts"])
        if entry["section"] == "hi":
            match = re.match(r"^\*\*(.*)\*\*\s+—\s+_(.*)_$", body, re.S)
            if not match:
                raise ValueError(
                    f"Could not parse Hindi original #{entry['index']} from line {entry['line_no']}"
                )
            hindi_originals.append(
                HindiOriginal(
                    index=entry["index"],
                    hi=normalize_multiline_text(match.group(1)),
                    en=normalize_multiline_text(match.group(2)),
                )
            )
            continue

        if entry["section"] == "en":
            match = re.match(
                r"^(.*)\s+—\s+_(.*)_\s+\((\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\)$",
                body,
                re.S,
            )
            if not match:
                raise ValueError(
                    f"Could not parse English entry #{entry['index']} from line {entry['line_no']}"
                )
            english_entries.append(
                EnglishEntry(
                    index=entry["index"],
                    en=normalize_multiline_text(match.group(1)),
                    contributor=normalize_multiline_text(match.group(2)),
                    date=iso_utc_from_snapshot(match.group(3)),
                )
            )

    if len(hindi_originals) != 40 or len(english_entries) != 2123:
        raise ValueError(
            f"Unexpected snapshot counts: {len(hindi_originals)} Hindi originals, {len(english_entries)} English entries"
        )

    return hindi_originals, english_entries


def pick_examples(originals: list[HindiOriginal], count: int = 14) -> list[HindiOriginal]:
    return originals[:count]


def build_prompt(batch: list[BatchItem], examples: list[HindiOriginal]) -> str:
    examples_block = "\n".join(
        f'- EN: "{example.en}"\n  HI: "{example.hi}"' for example in examples
    )
    batch_payload = json.dumps(
        [{"id": item.id, "en": item.en} for item in batch],
        ensure_ascii=False,
        indent=2,
    )
    return f"""Translate these email sign-offs into Hindi.

Style examples:
{examples_block}

Return one JSON result per item. Use `null` for hi when something should be skipped.

Items:
{batch_payload}
"""


def resolve_api_model(model: str) -> str:
    alias_map = {
        "sonnet": API_MODEL_DEFAULT,
        "opus": "claude-opus-4-1",
    }
    return alias_map.get(model, model)


def run_claude_cli(prompt: str, *, model: str, effort: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cmd = [
        "claude",
        "--print",
        "--model",
        model,
        "--effort",
        effort,
        "--tools",
        "",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(TRANSLATION_SCHEMA, ensure_ascii=False),
        "--system-prompt",
        SYSTEM_PROMPT,
        prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "claude CLI failed")
    payload = json.loads(proc.stdout)
    structured = payload.get("structured_output") or {}
    translations = structured.get("translations")
    if not isinstance(translations, list):
        raise ValueError("claude CLI response did not include structured_output.translations")
    return translations, payload


def run_anthropic_api(prompt: str, *, model: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    body = {
        "model": resolve_api_model(model),
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {
                "name": "submit_translations",
                "description": "Return the Hindi translations for the provided sign-offs.",
                "input_schema": TRANSLATION_SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": "submit_translations"},
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Anthropic API request failed: HTTP {exc.code} {detail}") from exc

    translations: list[dict[str, Any]] | None = None
    for block in payload.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "submit_translations":
            input_payload = block.get("input") or {}
            translations = input_payload.get("translations")
            break
    if not isinstance(translations, list):
        raise ValueError("Anthropic API response did not include tool translations")
    return translations, payload


def choose_backend(requested: str) -> str:
    if requested in {"anthropic", "claude"}:
        return requested
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude"
    raise RuntimeError("No translation backend available. Set ANTHROPIC_API_KEY or install/authenticate the `claude` CLI.")


def load_existing_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Cache file must be a JSON object: {path}")
    cache: dict[str, dict[str, Any]] = {}
    for en, item in data.items():
        if not isinstance(en, str) or not isinstance(item, dict):
            continue
        cache[en] = {
            "hi": item.get("hi"),
            "translatable": bool(item.get("translatable")),
        }
    return cache


def normalize_hi_text(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = normalize_multiline_text(text)
    normalized = normalized.strip("“”\"'")
    normalized = re.sub(r"\s+,", ",", normalized)
    normalized = re.sub(r"\s+\.", ".", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized or None


def validate_batch_results(
    batch: list[BatchItem], translations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    expected_ids = {item.id for item in batch}
    actual_ids = [item.get("id") for item in translations]
    if len(translations) != len(batch) or set(actual_ids) != expected_ids:
        raise ValueError(
            f"Batch id mismatch. Expected {sorted(expected_ids)}, got {sorted(set(actual_ids))}"
        )

    normalized_by_id: dict[int, dict[str, Any]] = {}
    for item in translations:
        translation_id = item.get("id")
        translatable = bool(item.get("translatable"))
        hi = normalize_hi_text(item.get("hi"))
        if translatable and not hi:
            raise ValueError(f"Batch item {translation_id} is translatable but hi is missing")
        if not translatable:
            hi = None
        normalized_by_id[int(translation_id)] = {
            "id": int(translation_id),
            "hi": hi,
            "translatable": translatable,
        }
    return [normalized_by_id[item.id] for item in batch]


def translate_batch(
    batch: list[BatchItem],
    *,
    backend: str,
    model: str,
    effort: str,
    examples: list[HindiOriginal],
    retries: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prompt = build_prompt(batch, examples)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if backend == "anthropic":
                raw_translations, payload = run_anthropic_api(prompt, model=model)
            else:
                raw_translations, payload = run_claude_cli(prompt, model=model, effort=effort)
            return validate_batch_results(batch, raw_translations), payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(5 * attempt, 15))
    raise RuntimeError(f"Failed to translate batch after {retries} attempts: {last_error}") from last_error


def build_unique_batches(
    english_entries: list[EnglishEntry],
    existing: dict[str, dict[str, Any]],
    *,
    batch_size: int,
    limit: int | None,
    force: bool,
) -> list[list[BatchItem]]:
    unique_order: list[str] = []
    seen: set[str] = set()
    for entry in english_entries:
        if entry.en not in seen:
            unique_order.append(entry.en)
            seen.add(entry.en)

    items: list[BatchItem] = []
    next_id = 1
    for en in unique_order:
        if not force and en in existing and ("translatable" in existing[en]):
            continue
        items.append(BatchItem(id=next_id, en=en))
        next_id += 1

    if limit is not None:
        items = items[:limit]

    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def build_output_entries(
    english_entries: list[EnglishEntry], translation_cache: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entry in english_entries:
        translated = translation_cache.get(entry.en, {})
        output.append(
            {
                "en": entry.en,
                "hi": translated.get("hi"),
                "contributor": entry.contributor,
                "date": entry.date,
                "translatable": translated.get("translatable", False),
            }
        )
    return output


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_js_dataset(path: Path, payload: list[dict[str, Any]]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        "// Generated by translate.py. Safe to load from file:// or HTTP.\n"
        f"window.SIGNOFFS_DATA = {body};\n",
        encoding="utf-8",
    )


def write_cache(path: Path, payload: dict[str, dict[str, Any]]) -> None:
    serialized = {
        en: {
            "hi": item.get("hi"),
            "translatable": bool(item.get("translatable")),
        }
        for en, item in sorted(payload.items(), key=lambda pair: pair[0])
    }
    write_json(path, serialized)


def find_review_flags(
    english_entries: list[EnglishEntry],
    output_entries: list[dict[str, Any]],
    translation_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hi_counts = Counter(
        entry["hi"]
        for entry in output_entries
        if entry.get("translatable") and isinstance(entry.get("hi"), str) and entry.get("hi")
    )
    flags: list[dict[str, Any]] = []

    for source, translated in zip(english_entries, output_entries, strict=True):
        issues: list[str] = []
        hi = translated.get("hi")
        translatable = bool(translated.get("translatable"))

        if not translatable:
            issues.append("untranslatable")
        if translatable and not hi:
            issues.append("missing_hi")
        if isinstance(hi, str) and hi:
            if "\n" in hi:
                issues.append("multiline_hi")
            if hi[-1] not in {",", ".", "।"}:
                issues.append("missing_terminal_punctuation")
            if any(char in DISALLOWED_PUNCTUATION for char in hi):
                issues.append("disallowed_punctuation")
            if re.search(r"[A-Za-z]{2,}", hi):
                issues.append("latin_characters")
            if hi_counts[hi] > 2:
                issues.append("duplicate_hi")
        if issues:
            flags.append(
                {
                    "index": source.index,
                    "en": source.en,
                    "hi": hi,
                    "issues": sorted(set(issues)),
                    "translatable": translatable,
                }
            )
    return flags


def build_duplicate_hi_groups(
    english_entries: list[EnglishEntry], output_entries: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, translated in zip(english_entries, output_entries, strict=True):
        hi = translated.get("hi")
        if translated.get("translatable") and isinstance(hi, str) and hi:
            grouped[hi].append({"index": source.index, "en": source.en})
    return {
        hi: entries
        for hi, entries in grouped.items()
        if len(entries) > 2
    }


def count_review_items(
    flags: list[dict[str, Any]], duplicate_groups: dict[str, list[dict[str, Any]]]
) -> int:
    count = len(duplicate_groups)
    for flag in flags:
        issues = [issue for issue in flag["issues"] if issue != "duplicate_hi"]
        if issues:
            count += 1
    return count


def write_review_report(
    path: Path,
    english_entries: list[EnglishEntry],
    output_entries: list[dict[str, Any]],
    flags: list[dict[str, Any]],
) -> None:
    duplicate_groups = build_duplicate_hi_groups(english_entries, output_entries)
    issue_counts = Counter(issue for flag in flags for issue in flag["issues"] if issue != "duplicate_hi")
    if duplicate_groups:
        issue_counts["duplicate_hi_groups"] = len(duplicate_groups)
    translatable_count = sum(1 for item in output_entries if item.get("translatable"))
    review_item_count = count_review_items(flags, duplicate_groups)
    lines = [
        "# Sign-Off Translation Review",
        "",
        f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        f"- English entries: {len(english_entries)}",
        f"- Marked translatable: {translatable_count}",
        f"- Marked untranslatable: {len(english_entries) - translatable_count}",
        f"- Review items: {review_item_count}",
        "",
        "## Issue Counts",
        "",
    ]
    for issue, count in sorted(issue_counts.items()):
        lines.append(f"- `{issue}`: {count}")
    if not issue_counts:
        lines.append("- None")
    lines.extend(["", "## Duplicate Hindi Groups", ""])
    if not duplicate_groups:
        lines.append("No repeated Hindi outputs above the review threshold.")
    else:
        for hi, entries in sorted(
            duplicate_groups.items(),
            key=lambda item: (-len(item[1]), item[0]),
        ):
            lines.append(f"- `{hi}` appears {len(entries)} times:")
            for entry in entries:
                lines.append(f"  - #{entry['index']}: {entry['en']}")
    lines.extend(["", "## Entry Flags", ""])
    entry_flags = []
    for flag in flags:
        issues = [issue for issue in flag["issues"] if issue != "duplicate_hi"]
        if issues:
            entry_flags.append({**flag, "issues": issues})
    if not entry_flags:
        lines.append("No entry-specific flags.")
    else:
        for flag in entry_flags:
            lines.append(f"{flag['index']}. Issues: {', '.join(flag['issues'])}")
            lines.append(f"   EN: {flag['en']}")
            lines.append(f"   HI: {flag['hi'] if flag['hi'] is not None else 'null'}")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def print_summary(
    english_entries: list[EnglishEntry], output_entries: list[dict[str, Any]], flags: list[dict[str, Any]]
) -> None:
    translated = sum(1 for item in output_entries if item.get("translatable"))
    duplicate_groups = build_duplicate_hi_groups(english_entries, output_entries)
    review_item_count = count_review_items(flags, duplicate_groups)
    print(
        f"Wrote {len(output_entries)} bilingual entries. {translated} translatable, "
        f"{len(output_entries) - translated} untranslatable, {review_item_count} review items.",
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_MD, help="Markdown snapshot to parse")
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON, help="Path for the bilingual JSON output")
    parser.add_argument("--js-output", type=Path, default=OUTPUT_JS, help="Path for the JS dataset sidecar")
    parser.add_argument("--review-output", type=Path, default=REVIEW_MD, help="Path for the review report")
    parser.add_argument("--cache-output", type=Path, default=CACHE_JSON, help="Path for resumable translation cache")
    parser.add_argument(
        "--backend",
        choices=["auto", "anthropic", "claude"],
        default="auto",
        help="Translation backend. Defaults to Anthropic API when ANTHROPIC_API_KEY is set, otherwise `claude` CLI.",
    )
    parser.add_argument("--model", default=CLI_MODEL_DEFAULT, help="Model alias or name for the chosen backend")
    parser.add_argument("--batch-size", type=int, default=50, help="Items per translation batch")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high"],
        default="low",
        help="Reasoning effort for the local `claude` CLI backend",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only translate this many unique English sign-offs")
    parser.add_argument("--retries", type=int, default=3, help="Retries per batch")
    parser.add_argument("--force", action="store_true", help="Retranslate even if output JSON already contains entries")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Parse the markdown snapshot and write outputs without calling a translation backend",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    originals, english_entries = parse_snapshot(args.source)

    if args.parse_only:
        empty_cache = load_existing_cache(args.cache_output)
        output_entries = build_output_entries(english_entries, empty_cache)
        write_json(args.output, output_entries)
        write_js_dataset(args.js_output, output_entries)
        write_cache(args.cache_output, empty_cache)
        flags = find_review_flags(english_entries, output_entries, empty_cache)
        write_review_report(args.review_output, english_entries, output_entries, flags)
        print_summary(english_entries, output_entries, flags)
        return 0

    backend = choose_backend(args.backend)
    examples = pick_examples(originals)
    translation_cache = load_existing_cache(args.cache_output)
    batches = build_unique_batches(
        english_entries,
        translation_cache,
        batch_size=args.batch_size,
        limit=args.limit,
        force=args.force,
    )

    total_batches = len(batches)
    total_cost = 0.0
    for batch_index, batch in enumerate(batches, start=1):
        batch_start = time.time()
        translations, payload = translate_batch(
            batch,
            backend=backend,
            model=args.model,
            effort=args.effort,
            examples=examples,
            retries=args.retries,
        )
        for item in translations:
            source_text = next(batch_item.en for batch_item in batch if batch_item.id == item["id"])
            translation_cache[source_text] = {
                "hi": item["hi"],
                "translatable": item["translatable"],
            }

        output_entries = build_output_entries(english_entries, translation_cache)
        write_json(args.output, output_entries)
        write_js_dataset(args.js_output, output_entries)
        write_cache(args.cache_output, translation_cache)

        total_cost += float(payload.get("total_cost_usd") or 0.0)
        duration = time.time() - batch_start
        print(
            f"[{batch_index}/{total_batches}] translated {len(batch)} unique sign-offs "
            f"in {duration:.1f}s via {backend}; cumulative cost ${total_cost:.4f}"
        , flush=True)

    output_entries = build_output_entries(english_entries, translation_cache)
    write_cache(args.cache_output, translation_cache)
    flags = find_review_flags(english_entries, output_entries, translation_cache)
    write_json(args.output, output_entries)
    write_js_dataset(args.js_output, output_entries)
    write_review_report(args.review_output, english_entries, output_entries, flags)
    print_summary(english_entries, output_entries, flags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
