"""Purpose: free-string constraint grounding (surface copy, optional canonical list).

Input: attribute name plus a parsed item whose surface already grounded.
Output: ConstraintSlot with no closed-list check. Canonical members are OR.
Role: brand, style, feature, use_case, and other share this path.
"""

from __future__ import annotations

from ..text import fold_key
from ..types import ConstraintSlot, ParsedItem


def ground_free(
    attribute: str,
    parsed: ParsedItem,
    surface: str,
    message: str,
) -> ConstraintSlot:
    del message
    values: list[str] = []
    seen: set[str] = set()
    if parsed.canonical_hints:
        for hint in parsed.canonical_hints:
            key = fold_key(hint)
            if not key or key in seen:
                continue
            seen.add(key)
            values.append(hint)
    elif parsed.alt_surfaces:
        for alt in parsed.alt_surfaces:
            key = fold_key(alt)
            if not key or key in seen:
                continue
            seen.add(key)
            values.append(alt)
    canonical = tuple(values) if values else None
    return ConstraintSlot(
        attribute=attribute,
        surface=surface,
        canonical=canonical,
    )
