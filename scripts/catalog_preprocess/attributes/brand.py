"""Purpose: extract store and details brand names."""

from __future__ import annotations

from collections.abc import Mapping

from ..sources import BRAND_DETAIL_KEYS
from ..text import details_map
from ..types import SlotRecord
from ._common import dedupe, slot

SKIP_BRANDS = frozenset({"imported", "unknown", "n/a", "na", "none", "generic"})


def _emit(value: str, source: str) -> SlotRecord | None:
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in SKIP_BRANDS:
        return None
    return slot("brand", cleaned, cleaned, source)


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    store = str(product.get("store") or "").strip()
    if store:
        rows.append(_emit(store, "store"))
    details = details_map(product)
    for key in BRAND_DETAIL_KEYS:
        raw = details.get(key)
        if raw:
            rows.append(_emit(raw, f"details:{key}"))
    manufacturer = details.get("manufacturer")
    if manufacturer and manufacturer.casefold() != store.casefold():
        rows.append(_emit(manufacturer, "details:manufacturer"))
    return dedupe(rows)
