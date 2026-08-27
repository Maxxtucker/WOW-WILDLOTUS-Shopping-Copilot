"""Understand layer: write this turn's user/simulator text into SessionState.

Input: raw user_message, turn, SessionState written back last turn.
Output: updated SessionState (scenario, constraints, exclusions, conversion gate).
Role: retrieval and planning read structured fields only and do not parse prose. See README.md.
"""

from .state import SessionState, StateDetector, begin_turn

__all__ = ["SessionState", "StateDetector", "begin_turn"]
