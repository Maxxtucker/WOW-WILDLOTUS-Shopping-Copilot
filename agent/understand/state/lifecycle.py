"""Purpose: understand entry for one turn (clock + miss + observe).

Input: SessionState, user_message, turn.
Output: the same SessionState object, updated in place with turn_delta.
Role: pipeline stage 1. The intention router commits constraints and fail-safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..observation.coordinator import observe
from .miss_feedback import apply_miss_feedback

if TYPE_CHECKING:
    from .session import SessionState


class StateDetector:
    """Stage 1: session clock, miss exclusions, then delta observation."""

    def apply(self, state: SessionState, message: str, turn: int) -> SessionState:
        begin_turn(state, message, turn)
        return state


def begin_turn(state: SessionState, message: str, turn: int) -> None:
    apply_miss_feedback(state, turn)
    state.turn = turn
    state.latest_message = str(message)
    state.message_history.append(state.latest_message)
    state.current_intent_messages.append(state.latest_message)
    state.last_reply_informative = False
    state.turn_delta = None
    state.disclosure_empty = None
    state.candidate_count_before_delta = None
    state.router_prompt_tokens = 0
    state.router_completion_tokens = 0
    observe(state, message)
