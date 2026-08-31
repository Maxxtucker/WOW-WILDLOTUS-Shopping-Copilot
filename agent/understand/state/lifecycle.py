"""Purpose: understand entry for one turn (clock + miss + observe).

Input: SessionState, user_message, turn.
Output: the same SessionState object, updated in place with turn_delta.
Role: pipeline stage 1. The intention router commits constraints and fail-safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...progress import emit
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
    prior_excluded = set(state.excluded_asins)
    emit(
        "understand",
        "prior_miss",
        "running",
        {
            "input": {
                "turn": turn,
                "last_gate_open": state.last_gate_open,
                "last_slate": list(state.last_slate),
            }
        },
    )
    apply_miss_feedback(state, turn)
    newly_excluded = sorted(set(state.excluded_asins) - prior_excluded)
    emit(
        "understand",
        "prior_miss",
        "completed",
        {
            "input": {
                "turn": turn,
                "last_gate_open": state.last_gate_open,
                "last_slate": list(state.last_slate),
            },
            "output": {
                "applied": bool(newly_excluded),
                "newly_excluded": newly_excluded,
                "excluded_total": len(state.excluded_asins),
            },
        },
    )
    emit("understand", "turn_reset", "running")
    state.turn = turn
    state.latest_message = str(message)
    state.message_history.append(state.latest_message)
    state.last_reply_informative = False
    state.turn_delta = None
    state.disclosure_empty = None
    state.candidate_count_before_delta = None
    state.router_prompt_tokens = 0
    state.router_completion_tokens = 0
    emit(
        "understand",
        "turn_reset",
        "completed",
        {
            "input": {"turn": turn, "message": state.latest_message},
            "output": {
                "history_length": len(state.message_history),
                "turn_delta": None,
                "disclosure_empty": None,
                "candidate_count_before_delta": None,
                "router_prompt_tokens": 0,
                "router_completion_tokens": 0,
            },
        },
    )
    observe(state, message)
    emit("understand", "active_intent_evidence", "running")
    appended = state.disclosure_empty is False
    if state.disclosure_empty is False:
        state.current_intent_messages.append(state.latest_message)
    emit(
        "understand",
        "active_intent_evidence",
        "completed",
        {
            "input": {
                "disclosure_empty": state.disclosure_empty,
                "message": state.latest_message,
            },
            "output": {
                "appended": appended,
                "message_count": len(state.current_intent_messages),
            },
            "why": (
                None
                if appended
                else "Only non-empty disclosures feed active-intent raw recall"
            ),
        },
    )
