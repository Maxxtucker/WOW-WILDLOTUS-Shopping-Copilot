"""Purpose: dispatch a grounded surface to the matching attribute handler.

Input: parsed item whose surface already appears in the user message.
Output: ConstraintSlot from that attribute's module, or None.
Role: the only place that maps attribute name → handler. Category is not a slot.
"""

from __future__ import annotations

from collections.abc import Callable

from ..types import ConstraintSlot, ParsedItem
from . import brand, budget, color, feature, material, other, size, style, use_case

SlotHandler = Callable[[ParsedItem, str, str], ConstraintSlot | None]

HANDLERS: dict[str, SlotHandler] = {
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
    return handler(parsed, surface, message)
