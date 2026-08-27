"""Purpose: session-state package. Holds SessionState and turn lifecycle.

Input: session_id, user_profile; later stages mutate SessionState in place.
Output: updated SessionState (constraints, exclusions, conversion gate).
Role: memory hub of understand. See README.md.
"""

from .lifecycle import StateDetector, begin_turn
from .session import SessionState

__all__ = ["SessionState", "StateDetector", "begin_turn"]
