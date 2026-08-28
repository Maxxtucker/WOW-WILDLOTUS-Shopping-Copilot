"""Purpose: category may be a top-level extract field or a typed slot.

Input: raw category value plus the user message, or a parsed item.
Output: a copied span, or a ConstraintSlot.
Role: category grounding; hardness is user language, not a catalog fingerprint.
"""

from __future__ import annotations

from ...schema import ground_span
from ..types import ConstraintSlot, ParsedItem


def ground_category(value: object, message: str) -> str | None:
    return ground_span(value, message)


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    del message
    if not surface.strip():
        return None
    return ConstraintSlot(
        attribute="category",
        surface=surface,
        is_hard=parsed.is_hard,
    )
