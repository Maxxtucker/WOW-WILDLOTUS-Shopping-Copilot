"""Purpose: color slot grounding against the closed color list.

Input: parsed color item, grounded surface, user message.
Output: ConstraintSlot with canonical tuple in CLOSED_COLORS, or None.
Role: model picks buckets (navy → blue); code only accepts list keys. Several keys are OR.
"""

from __future__ import annotations

from ..closed import resolve_closed
from ..types import ConstraintSlot, ParsedItem

CLOSED_COLORS = (
    "black",
    "white",
    "blue",
    "red",
    "pink",
    "green",
    "brown",
    "gray",
    "purple",
    "yellow",
    "orange",
)
CLOSED_COLOR_SET = frozenset(CLOSED_COLORS)


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    del message
    values: list[str] = []
    seen: set[str] = set()
    hints = parsed.canonical_hints
    alts = parsed.alt_surfaces
    if hints:
        for index, hint in enumerate(hints):
            local = alts[index] if index < len(alts) else surface
            key = resolve_closed(local, hint, allowed=CLOSED_COLOR_SET)
            if key is not None and key not in seen:
                seen.add(key)
                values.append(key)
    elif alts:
        for local in alts:
            key = resolve_closed(local, None, allowed=CLOSED_COLOR_SET)
            if key is not None and key not in seen:
                seen.add(key)
                values.append(key)
    else:
        key = resolve_closed(surface, None, allowed=CLOSED_COLOR_SET)
        if key is not None:
            values.append(key)
    if not values:
        return None
    return ConstraintSlot(
        attribute="color",
        surface=surface,
        canonical=tuple(values),
    )
