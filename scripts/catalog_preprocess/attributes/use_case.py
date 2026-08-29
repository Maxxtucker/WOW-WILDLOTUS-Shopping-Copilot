"""Purpose: extract occasion / activity tokens onto use_case."""

from __future__ import annotations

from collections.abc import Mapping

from ..sources import USE_CASE_DETAIL_KEYS
from ..text import categories_list, details_map, feature_lines, fold_key, ngrams, tokens
from ..types import SlotRecord
from ._common import dedupe, slot

USE_CASES = {
    "hiking": "hiking",
    "running": "running",
    "run": "running",
    "gym": "gym",
    "workout": "gym",
    "training": "gym",
    "winter": "winter",
    "outdoor": "outdoor",
    "outdoors": "outdoor",
    "work": "work",
    "workwear": "work",
    "travel": "travel",
    "wedding": "wedding",
    "swim": "swim",
    "swimming": "swim",
    "halloween": "halloween",
    "costume": "halloween",
    "athletic": "gym",
    "casual": "casual",
    "office": "work",
}


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    for key in USE_CASE_DETAIL_KEYS:
        raw = details.get(key)
        if not raw:
            continue
        mapped = USE_CASES.get(fold_key(raw))
        rows.append(slot("use_case", mapped or raw, raw, f"details:{key}"))
    blobs = [
        str(product.get("title") or ""),
        " ".join(categories_list(product)),
        *[line for line in feature_lines(product) if len(line) <= 120],
    ]
    seen: set[str] = set()
    for blob in blobs:
        for _, _, phrase in ngrams(tokens(blob), maximum=2):
            mapped = USE_CASES.get(phrase)
            if mapped and mapped not in seen:
                seen.add(mapped)
                rows.append(slot("use_case", mapped, phrase, "text"))
    return dedupe(rows)
