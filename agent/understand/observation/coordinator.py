"""Purpose: apply category, constraints, then override in a fixed order every turn.

Input: SessionState, this turn's message.
Output: SessionState updated in place.
Role: catalog copy may contain instead/forget; locked constraints are applied before override.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import add_constraint
from ..intention.detector import apply_override
from .classify import (
    CategoryHit,
    colon_fallback,
    extract_category,
    extract_constraints,
    parse_override,
)

if TYPE_CHECKING:
    from ..state.session import SessionState


class ObservationCoordinator:
    """Compose extractors without changing parse order."""

    def apply(self, state: SessionState, message: str) -> SessionState:
        observe(state, message)
        return state


def observe(state: SessionState, message: str) -> None:
    value = message.strip()
    constraints = extract_constraints(state, value)
    category_hit = extract_category(value)

    if constraints:
        for piece in constraints:
            add_constraint(state, piece)
        state.informative_replies += 1
        state.last_reply_informative = True
        if category_hit is not None:
            state.category = category_hit.category
        return

    if category_hit is not None:
        _apply_category(state, category_hit)

    override = parse_override(value, gate_closed=not state.gate_open)
    if override is not None:
        apply_override(state, override.new_value)
        return

    pieces = colon_fallback(state, value)
    if pieces:
        for piece in pieces:
            add_constraint(state, piece)
        state.informative_replies += 1
        state.last_reply_informative = True


def _apply_category(state: SessionState, hit: CategoryHit) -> None:
    state.category = hit.category
    if not hit.provisional_hint:
        return
    state.gate_open = False
    if hit.provisional_hint not in state.legacy_hints:
        state.legacy_hints.append(hit.provisional_hint)
