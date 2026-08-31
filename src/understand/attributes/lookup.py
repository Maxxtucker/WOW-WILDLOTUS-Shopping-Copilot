"""Purpose: map predicted-reply surface forms back to atomic constraints (handle semicolons).

Input: predicted value tuples[str, ...]; or SessionState plus a matters payload.
Output: canonical(surface) → atomic-value tuple; None on conflict, then fall back to semicolon split.
Role: catalog features may themselves contain semicolons, so they must not be split blindly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import canonical

if TYPE_CHECKING:
    from ..state.session import SessionState


def build_reply_lookup(
    options: list[tuple[str, ...]],
) -> dict[str, tuple[str, ...] | None]:
    """Store an inverse surface-form map for the pending structured reply.

    ``None`` marks an ambiguous surface that can be produced by two
    different atomic-value segmentations; such a case uses the conservative
    parser fallback instead of silently choosing one candidate's values.
    """

    lookup: dict[str, tuple[str, ...] | None] = {}
    for values in options:
        if not values:
            continue
        key = canonical("; ".join(values))
        previous = lookup.get(key)
        if key in lookup and previous != values:
            lookup[key] = None
        else:
            lookup[key] = values
    return lookup


def resolve_matters_pieces(state: SessionState, payload: str) -> list[str]:
    """Prefer the previous-turn candidate map over splitting on semicolons."""

    predicted = state.reply_value_lookup.get(canonical(payload))
    if predicted is not None:
        return list(predicted)
    return [item.strip() for item in payload.split(";") if item.strip()]
