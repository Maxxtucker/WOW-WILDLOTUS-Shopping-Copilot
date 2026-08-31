"""Purpose: map catalog color names onto the evaluator 11-color list."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..sources import COLOR_DETAIL_KEYS
from ..text import (
    categories_list,
    details_map,
    feature_lines,
    fold_key,
    ngrams,
    split_alternatives,
    tokens,
)
from ..types import SlotRecord
from ._common import dedupe, slot

JEWELRY_MARKERS = (
    "jewelry",
    "watches",
    "earrings",
    "necklaces",
    "bracelets",
    "rings",
    "pendant",
)
METAL_COLORS = frozenset(
    {
        "gold",
        "silver",
        "platinum",
        "rose gold",
        "white gold",
        "yellow gold",
        "sterling silver",
    }
)
SHORT_FEATURES = 80


def _is_jewelry(product: Mapping[str, object]) -> bool:
    blob = " ".join(fold_key(item) for item in categories_list(product))
    return any(marker in blob for marker in JEWELRY_MARKERS)


def _eval_color(phrase: str, aliases: Mapping[str, dict[str, Any]]) -> str | None:
    key = fold_key(phrase)
    if not key:
        return None
    entry = aliases.get(key)
    if not entry:
        return None
    value = str(entry.get("eval") or "").strip()
    return value or None


def _skip_jewelry_metal(phrase: str, *, jewelry: bool) -> bool:
    if not jewelry:
        return False
    return fold_key(phrase) in METAL_COLORS


def _from_blob(
    blob: str,
    source: str,
    aliases: Mapping[str, dict[str, Any]],
    *,
    jewelry: bool,
) -> list[SlotRecord | None]:
    words = tokens(blob)
    if not words:
        return []
    used: set[int] = set()
    rows: list[SlotRecord | None] = []
    for start, end, phrase in ngrams(words, maximum=4):
        if any(index in used for index in range(start, end)):
            continue
        if _skip_jewelry_metal(phrase, jewelry=jewelry):
            continue
        mapped = _eval_color(phrase, aliases)
        if mapped is None:
            continue
        used.update(range(start, end))
        rows.append(slot("color", mapped, phrase, source))
    return rows


def extract(
    product: Mapping[str, object],
    *,
    aliases: Mapping[str, dict[str, Any]],
) -> list[SlotRecord]:
    jewelry = _is_jewelry(product)
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    for key in COLOR_DETAIL_KEYS:
        raw = details.get(key)
        if not raw:
            continue
        for piece in split_alternatives(raw) or [raw]:
            if _skip_jewelry_metal(piece, jewelry=jewelry):
                continue
            mapped = _eval_color(piece, aliases)
            if mapped is not None:
                rows.append(slot("color", mapped, piece, f"details:{key}"))
            else:
                rows.extend(_from_blob(piece, f"details:{key}", aliases, jewelry=jewelry))
    title = str(product.get("title") or "")
    rows.extend(_from_blob(title, "title", aliases, jewelry=jewelry))
    for line in feature_lines(product):
        if len(line) > SHORT_FEATURES:
            continue
        rows.extend(_from_blob(line, "features", aliases, jewelry=jewelry))
    return dedupe(rows)
