"""Purpose: style slot grounding.

Input: parsed style item, grounded surface, user message.
Output: ConstraintSlot; canonical is optional and not span-checked.
Role: free string. Copy the shopper span.
"""

from __future__ import annotations

from ..types import ParsedItem
from .free import ground_free


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    return ground_free("style", parsed, surface, message)
