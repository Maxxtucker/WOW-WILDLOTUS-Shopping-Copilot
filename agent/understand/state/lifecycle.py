"""Purpose: understand entry for one turn (clock + miss + observe + fail-safe).

Input: SessionState, user_message, turn.
Output: the same SessionState object, updated in place.
Role: pipeline stage 1; observation.classify runs inside observe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..observation.coordinator import observe
from .failsafe import apply_override_failsafe
from .miss_feedback import apply_miss_feedback

if TYPE_CHECKING:
    from .session import SessionState


class StateDetector:
    """Stage 1: session clock, miss exclusions, then observation."""

    def apply(self, state: SessionState, message: str, turn: int) -> SessionState:
        begin_turn(state, message, turn)
        return state


def begin_turn(state: SessionState, message: str, turn: int) -> None:
    apply_miss_feedback(state, turn)
    state.turn = turn
    state.latest_message = str(message)
    state.message_history.append(state.latest_message)
    state.last_reply_informative = False
    observe(state, message)
    apply_override_failsafe(state, turn)
