"""Purpose: if the conversion gate is still closed at turn 4, force it open.

Input: SessionState, turn.
Output: may set gate_open True. Does not label intention=override.
Role: a missed override paraphrase must not keep conversion disabled forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SessionState


def apply_override_failsafe(state: SessionState, turn: int) -> None:
    """Open the conversion gate if it is still closed at turn 4.

    Does not set override_seen, does not bump intent_version, and does not
    write intention=override. The intention router already classified this turn.
    """

    if not state.gate_open and turn >= 4:
        state.gate_open = True
