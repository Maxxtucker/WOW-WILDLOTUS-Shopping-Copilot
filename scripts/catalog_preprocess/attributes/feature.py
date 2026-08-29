"""Purpose: extract catalog feature lines and short capability tokens."""

from __future__ import annotations

from collections.abc import Mapping

from ..sources import is_feature_detail_key
from ..text import details_map, feature_lines, fold_key, ngrams, normalize_canonical, tokens
from ..types import SlotRecord
from ._common import dedupe, slot

SKIP_LINES = frozenset(
    {
        "imported",
        "machine wash",
        "hand wash",
        "hand wash only",
        "dry clean",
        "no closure closure",
    }
)
FEATURE_PHRASES = frozenset(
    {
        "hypoallergenic",
        "moisture wicking",
        "moisture-wicking",
        "quick dry",
        "quick drying",
        "waterproof",
        "water resistant",
        "windproof",
        "breathable",
        "rfid",
        "upf",
        "uv protection",
        "insulated",
        "lightweight",
        "seamless",
        "cushioned",
        "anti slip",
        "non slip",
        "touch screen",
        "machine washable",
    }
)
COMPOSITION_HINT = "%"


def _emit(value: str, source: str) -> SlotRecord | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    folded = normalize_canonical(cleaned)
    if not folded:
        return None
    return slot("feature", folded, cleaned, source)


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    for key, raw in details.items():
        if raw and is_feature_detail_key(key):
            rows.append(_emit(raw, f"details:{key}"))
    for line in feature_lines(product):
        folded = fold_key(line)
        if folded in SKIP_LINES or COMPOSITION_HINT in line:
            continue
        rows.append(_emit(line, "features"))
        if len(line) <= 40 and " " not in folded:
            continue
        words = tokens(line)
        for _, _, phrase in ngrams(words, maximum=3):
            key = phrase.replace("-", " ")
            if phrase in FEATURE_PHRASES or key in FEATURE_PHRASES:
                rows.append(slot("feature", key, phrase, "features"))
        if folded.startswith("upf") or " upf " in f" {folded} ":
            rows.append(slot("feature", "upf", line[:80], "features"))
    return dedupe(rows)
