"""Purpose: mark the previous slate as a miss because the evaluator called respond again.

Input: SessionState, current turn.
Output: if turn>1 and last_gate_open, merge last_slate into excluded_asins.
Role: the evaluator has no negative click; displays while the gate was closed (before Override) must not count as misses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SessionState


def apply_miss_feedback(state: SessionState, turn: int) -> None:
    """If the evaluator called us again, the previous scored slate missed."""

    if turn > 1 and state.last_gate_open:
        state.excluded_asins.update(state.last_slate)
