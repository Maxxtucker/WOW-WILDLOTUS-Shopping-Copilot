"""Understand layer: write this turn's user/simulator text into SessionState.

Input: raw user_message, turn, SessionState written back last turn.
Output: updated SessionState (category, constraints, exclusions, conversion gate).
Role: retrieval and planning read structured fields only and do not parse prose. See README.md.
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
