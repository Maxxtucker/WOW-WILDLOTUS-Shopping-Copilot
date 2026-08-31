"""Purpose: SlotRecord constructor shared by attribute extractors."""

from __future__ import annotations

from typing import Any

from ..text import normalize_canonical
from ..types import SlotRecord


def slot(
    attribute: str,
    canonical: str,
    surface: str,
    source: str,
    extras: dict[str, Any] | None = None,
    *,
    fold: bool = True,
) -> SlotRecord | None:
    folded = (
        normalize_canonical(canonical) if fold else str(canonical or "").strip()
    )
    cleaned_surface = str(surface or "").strip()
    if not folded or not cleaned_surface:
        return None
    return SlotRecord(
        attribute=attribute,
        canonical=folded,
        surface=cleaned_surface,
        source=source,
        extras=extras or None,
    )


def dedupe(rows: list[SlotRecord | None]) -> list[SlotRecord]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[SlotRecord] = []
    for row in rows:
        if row is None:
            continue
        key = (row.attribute, row.canonical, row.surface, row.source)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
