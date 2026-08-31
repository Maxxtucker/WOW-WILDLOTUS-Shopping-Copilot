"""Purpose: material slot grounding against the closed material list.

Input: parsed material item, grounded surface, user message.
Output: ConstraintSlot with canonical tuple in MATERIALS, or None.
Role: model picks buckets (cowhide → leather); code only accepts list keys. Several keys are OR.
"""

from __future__ import annotations

from .....domain import MATERIALS
from ..closed import resolve_closed
from ..types import ConstraintSlot, ParsedItem

CLOSED_MATERIAL_SET = frozenset(MATERIALS)


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    del message
    values: list[str] = []
    seen: set[str] = set()
    hints = parsed.canonical_hints
    alts = parsed.alt_surfaces
    if hints:
        for index, hint in enumerate(hints):
            local = alts[index] if index < len(alts) else surface
            key = resolve_closed(local, hint, allowed=CLOSED_MATERIAL_SET)
            if key is not None and key not in seen:
                seen.add(key)
                values.append(key)
    elif alts:
        for local in alts:
            key = resolve_closed(local, None, allowed=CLOSED_MATERIAL_SET)
            if key is not None and key not in seen:
                seen.add(key)
                values.append(key)
    else:
        key = resolve_closed(surface, None, allowed=CLOSED_MATERIAL_SET)
        if key is not None:
            values.append(key)
    if not values:
        return None
    return ConstraintSlot(
        attribute="material",
        surface=surface,
        canonical=tuple(values),
    )
