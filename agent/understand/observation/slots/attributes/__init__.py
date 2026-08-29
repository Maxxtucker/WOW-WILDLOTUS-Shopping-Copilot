"""Purpose: dispatch a grounded surface to the matching attribute handler.

Input: parsed item whose surface already appears in the user message.
Output: ConstraintSlot from that attribute's module, or None.
Role: the only place that maps attribute name → handler. Category may be a slot.
"""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable

from ..types import ConstraintSlot, ParsedItem
from . import brand, budget, category, color, feature, material, other, size, style, use_case

SlotHandler = Callable[[ParsedItem, str, str], ConstraintSlot | None]

HANDLERS: dict[str, SlotHandler] = {
    "category": category.ground,
    "color": color.ground,
    "material": material.ground,
    "size": size.ground,
    "budget": budget.ground,
    "style": style.ground,
    "brand": brand.ground,
    "feature": feature.ground,
    "use_case": use_case.ground,
    "other": other.ground,
}


def ground_attribute(
    parsed: ParsedItem, surface: str, message: str
) -> ConstraintSlot | None:
    handler = HANDLERS.get(parsed.attribute, other.ground)
    slot = handler(parsed, surface, message)
    if slot is None:
        return None
    if slot.is_hard == parsed.is_hard:
        return slot
    return replace(slot, is_hard=parsed.is_hard)
