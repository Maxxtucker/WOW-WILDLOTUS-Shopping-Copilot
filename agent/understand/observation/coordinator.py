"""Purpose: extract this turn into turn_delta only. Does not commit SessionState.

Input: SessionState, this turn's message.
Output: state.turn_delta set from hybrid_extract (plus regex colon fallback).
Role: the intention router commits constraints after it classifies override.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ...domain import classify_constraint
from ...progress import emit
from .classify import colon_fallback
from .hybrid import hybrid_extract
from .slots.types import ConstraintSlot

if TYPE_CHECKING:
    from ..state.session import SessionState


class ObservationCoordinator:
    """Extract this turn without committing constraints."""

    def apply(self, state: SessionState, message: str) -> SessionState:
        observe(state, message)
        return state


def observe(state: SessionState, message: str) -> None:
    value = message.strip()
    extract = hybrid_extract(state, value)
    if (
        not extract.empty
        and extract.source != "llm"
        and not extract.constraints
    ):
        pieces = colon_fallback(state, value)
        if pieces:
            extra = tuple(
                ConstraintSlot(
                    attribute=classify_constraint(piece),
                    surface=piece,
                    is_hard=True,
                )
                for piece in pieces
            )
            extract = replace(
                extract,
                constraints=tuple(pieces),
                slots=extract.slots + extra,
            )
    state.disclosure_empty = extract.disclosure_empty
    state.turn_delta = None if extract.empty else extract
    slots = []
    if not extract.empty:
        slots = [
            slot.as_dict() if hasattr(slot, "as_dict") else dict(slot)
            for slot in extract.slots
        ]
    staged = {
        "source": None if extract.empty else extract.source,
        "category": None if extract.empty else extract.category,
        "slots": slots,
        "empty": extract.empty,
        "repair_rounds": extract.repair_rounds,
        "disclosure_empty": extract.disclosure_empty,
    }
    emit(
        "understand",
        "turn_delta",
        "completed",
        {
            "input": {
                "message": value,
                "committed_category_before_router": state.category,
                "committed_constraints_before_router": list(
                    state.locked_constraint_strings()
                ),
            },
            "output": {
                "turn_delta": None if extract.empty else staged,
                "will_router_commit": not extract.empty,
            },
            **staged,
            "gate_open": state.gate_open,
            "session_category": state.category,
        },
    )
