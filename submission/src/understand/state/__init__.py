"""Purpose: session-state package. Holds SessionState and turn lifecycle.

Input: session_id, user_profile; later stages mutate SessionState in place.
Output: updated SessionState (constraints, exclusions, conversion gate).
Role: memory hub of understand. See README.md.
"""

from .gate import apply_override, open_conversion_gate
from .lifecycle import StateDetector, begin_turn
from .session import SessionState, preference_tags_from_profile

__all__ = [
    "SessionState",
    "StateDetector",
    "apply_override",
    "begin_turn",
    "open_conversion_gate",
    "preference_tags_from_profile",
]
