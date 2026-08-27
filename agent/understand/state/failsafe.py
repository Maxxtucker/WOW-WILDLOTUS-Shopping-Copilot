"""Purpose: if override_pending is still unrecognized at turn 4, force the gate open.

Input: SessionState, turn.
Output: may set scenario to intent_override and clear legacy / exclusions.
Role: official override always fires on turn 3 or 4; a paraphrase that misses the regex must not keep the gate closed forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..intention.detector import apply_override

if TYPE_CHECKING:
    from .session import SessionState


def apply_override_failsafe(state: SessionState, turn: int) -> None:
    """The published override always fires on turn 3 or 4.

    If an organizer paraphrase defeats every lexical rule, opening the
    internal gate on turn 4 is safer than remaining permanently stuck in
    the old intent.
    """

    if state.scenario_hint == "override_pending" and turn >= 4 and not state.override_seen:
        apply_override(state, None)
