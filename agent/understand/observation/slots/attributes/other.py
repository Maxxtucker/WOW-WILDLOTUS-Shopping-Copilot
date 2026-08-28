"""Purpose: other slot grounding (fallback attribute).

Input: parsed other item, grounded surface, user message.
Output: ConstraintSlot; canonical is optional and not span-checked.
Role: catch-all when the name is not a more specific attribute.
"""

from __future__ import annotations

from ..types import ParsedItem
from .free import ground_free


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    return ground_free("other", parsed, surface, message)
