"""Purpose: extract style, fit, neck, and department gender tokens."""

from __future__ import annotations

from collections.abc import Mapping

from ..sources import GENDER_MAP, STYLE_DETAIL_KEYS
from ..text import details_map, feature_lines, fold_key, ngrams, tokens
from ..types import SlotRecord
from ._common import dedupe, slot

STYLE_PHRASES = frozenset(
    {
        "crew",
        "v neck",
        "crewneck",
        "slim",
        "regular fit",
        "relaxed",
        "vintage",
        "boho",
        "bohemian",
        "athletic",
        "casual",
        "formal",
        "classic",
        "modern",
        "hoodie",
        "pullover",
        "zip",
        "skinny",
        "straight",
        "bootcut",
        "oversized",
        "cropped",
    }
)
SHORT_FEATURES = 80


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    department = details.get("department")
    if department:
        gender = GENDER_MAP.get(fold_key(department).replace("'", ""))
        if gender:
            rows.append(slot("style", gender, department, "details:department"))
    for key in STYLE_DETAIL_KEYS:
        raw = details.get(key)
        if raw:
            rows.append(slot("style", raw, raw, f"details:{key}"))
    blobs = [str(product.get("title") or "")]
    blobs.extend(line for line in feature_lines(product) if len(line) <= SHORT_FEATURES)
    wanted = {phrase: None for phrase in STYLE_PHRASES}
    for blob in blobs:
        words = tokens(blob)
        for _, _, phrase in ngrams(words, maximum=2):
            if phrase in STYLE_PHRASES:
                wanted[phrase] = phrase
    for phrase, hit in wanted.items():
        if hit:
            rows.append(slot("style", phrase, phrase, "title" if phrase in fold_key(blobs[0]) else "features"))
    return dedupe(rows)
