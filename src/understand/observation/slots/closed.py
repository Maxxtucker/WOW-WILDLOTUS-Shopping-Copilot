"""Purpose: closed-list canonical check shared by color and material.

Input: shopper surface, optional model canonical, and the allowed labels.
Output: an official list member, or None.
Role: the model picks the bucket; this only accepts a list key (plus grey/gray).
"""

from __future__ import annotations

from .text import fold_key


def fold_closed_key(value: str) -> str:
    """Casefold and collapse grey/gray spelling. No semantic color/material aliases."""

    key = fold_key(value)
    if key == "grey":
        return "gray"
    return key


def resolve_closed(
    surface: str,
    canonical_hint: str | None,
    *,
    allowed: frozenset[str],
) -> str | None:
    """Accept a closed-list label from the model, or the surface if it already is one."""

    hint = fold_closed_key(canonical_hint or "")
    if hint in allowed:
        return hint
    surf = fold_closed_key(surface or "")
    if surf in allowed:
        return surf
    return None
