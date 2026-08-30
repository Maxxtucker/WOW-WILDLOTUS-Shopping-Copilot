"""Purpose: extract textile and leather materials onto the evaluator 9-material list."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..eval_maps import SPECIFIC_MATERIALS
from ..sources import MATERIAL_DETAIL_KEYS
from ..text import (
    composition_parts,
    details_map,
    feature_lines,
    flatten_text,
    fold_key,
    ngrams,
    tokens,
)
from ..types import SlotRecord
from ._common import dedupe, slot

SHORT_LINE = 48


def _eval_material(phrase: str, aliases: Mapping[str, dict[str, Any]]) -> str | None:
    key = fold_key(phrase)
    if not key:
        return None
    entry = aliases.get(key)
    if not entry:
        compact = key.replace("-", " ")
        entry = aliases.get(compact)
    if not entry:
        return None
    value = str(entry.get("eval") or "").strip()
    return value or None


def _from_compositions(
    text: str,
    source: str,
    aliases: Mapping[str, dict[str, Any]],
) -> list[SlotRecord | None]:
    rows: list[SlotRecord | None] = []
    for pct, name in composition_parts(text):
        mapped = _eval_material(name, aliases)
        if mapped is None:
            mapped = _eval_material(name.split()[0], aliases) if name.split() else None
        if mapped is None:
            continue
        extras = {"pct": pct}
        rows.append(slot("material", mapped, name, source, extras))
    return rows


def _from_blob(
    blob: str,
    source: str,
    aliases: Mapping[str, dict[str, Any]],
    *,
    allow_fabric: bool,
) -> list[SlotRecord | None]:
    rows: list[SlotRecord | None] = []
    words = tokens(blob)
    used: set[int] = set()
    for start, end, phrase in ngrams(words, maximum=3):
        if any(index in used for index in range(start, end)):
            continue
        mapped = _eval_material(phrase, aliases)
        if mapped is None:
            continue
        if mapped == "fabric" and not allow_fabric:
            continue
        used.update(range(start, end))
        rows.append(slot("material", mapped, phrase, source))
    return rows


def extract(
    product: Mapping[str, object],
    *,
    aliases: Mapping[str, dict[str, Any]],
) -> list[SlotRecord]:
    rows: list[SlotRecord | None] = []
    details = details_map(product)
    features = feature_lines(product)
    feature_blob = " ".join(features)
    rows.extend(_from_compositions(feature_blob, "features:composition", aliases))
    for key in MATERIAL_DETAIL_KEYS:
        raw = details.get(key)
        if not raw:
            continue
        rows.extend(_from_compositions(raw, f"details:{key}", aliases))
        mapped = _eval_material(raw, aliases)
        if mapped is not None:
            rows.append(slot("material", mapped, raw, f"details:{key}"))
        else:
            rows.extend(_from_blob(raw, f"details:{key}", aliases, allow_fabric=True))

    specific = {
        row.canonical
        for row in rows
        if row is not None and row.canonical in SPECIFIC_MATERIALS
    }
    allow_fabric = not specific
    title = str(product.get("title") or "")
    for line in features:
        if len(line) <= SHORT_LINE:
            rows.extend(_from_blob(line, "features", aliases, allow_fabric=allow_fabric))
    rows.extend(_from_blob(title, "title", aliases, allow_fabric=allow_fabric))
    if allow_fabric and "fabric" in fold_key(flatten_text(features) + " " + title):
        has_fabric = any(
            row is not None and row.canonical == "fabric" for row in rows
        )
        if not has_fabric and not specific:
            rows.append(slot("material", "fabric", "fabric", "features"))
    return dedupe(rows)
