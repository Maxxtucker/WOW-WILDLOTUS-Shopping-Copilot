"""Understand layer: stage one natural-language turn as an observation delta.

Input: raw user_message, turn, SessionState written back last turn.
Output: updated turn clock, miss memory, and non-committed SessionState.turn_delta.
Role: Intent Router decides how the delta changes committed constraints. See README.md.
"""

from .mode import (
    MODE_NLU,
    MODE_REGEX,
    configure_understand,
    current_understand_mode,
    reset_understand_mode,
    resolve_understand_mode,
)
from .state import SessionState, StateDetector, begin_turn

__all__ = [
    "MODE_NLU",
    "MODE_REGEX",
    "SessionState",
    "StateDetector",
    "begin_turn",
    "configure_understand",
    "current_understand_mode",
    "reset_understand_mode",
    "resolve_understand_mode",
]
