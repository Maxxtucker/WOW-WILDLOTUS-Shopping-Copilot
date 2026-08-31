"""Purpose: leftover short details values that are not another attribute."""

from __future__ import annotations

from collections.abc import Mapping

from ..sources import (
    COLOR_DETAIL_KEYS,
    MATERIAL_DETAIL_KEYS,
    SIZE_DETAIL_KEYS,
    SKIP_OTHER_KEYS,
    STYLE_DETAIL_KEYS,
    USE_CASE_DETAIL_KEYS,
    is_brand_detail_key,
    is_dimension_detail_key,
    is_feature_detail_key,
    is_style_detail_key,
    is_weight_detail_key,
)
from ..text import categories_list, details_map, fold_key
from ..types import SlotRecord
from ._common import dedupe, slot

MAX_OTHER = 4
MAX_SURFACE = 80
ROUTED_KEYS = (
    COLOR_DETAIL_KEYS
    | MATERIAL_DETAIL_KEYS
    | SIZE_DETAIL_KEYS
    | STYLE_DETAIL_KEYS
    | USE_CASE_DETAIL_KEYS
    | SKIP_OTHER_KEYS
)
JEWELRY_MARKERS = ("jewelry", "watches", "earrings", "necklaces", "bracelets", "rings")
METAL_PHRASES = (
    "gold",
    "silver",
    "platinum",
    "rose gold",
    "white gold",
    "sterling silver",
)


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    for key, value in details.items():
        if (
            key in ROUTED_KEYS
            or is_dimension_detail_key(key)
            or is_brand_detail_key(key)
            or is_style_detail_key(key)
            or is_feature_detail_key(key)
            or is_weight_detail_key(key)
        ):
            continue
        if len(value) > MAX_SURFACE or value.lower().startswith("http"):
            continue
        rows.append(slot("other", value, value, f"details:{key}"))
        if len([row for row in rows if row is not None]) >= MAX_OTHER:
            break
    blob = " ".join(fold_key(item) for item in categories_list(product))
    jewelry = any(marker in blob for marker in JEWELRY_MARKERS)
    if jewelry:
        title = fold_key(product.get("title"))
        for phrase in METAL_PHRASES:
            if phrase in title or phrase in fold_key(" ".join(details.values())):
                rows.append(slot("other", phrase, phrase, "title:metal"))
                break
    return dedupe(rows)[:MAX_OTHER]
