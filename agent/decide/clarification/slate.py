"""Purpose: sequential slate risk gate after planning.

Input: SessionState, Plan, ranked list.
Output: parent_asin list, possibly truncated to rank-1.
Role: when the gate is open, it is not turn 10, and an informative question remains (or remaining candidates can still be probed one per turn), expose only 1. Empty disclosure skips this cut and keeps the planned Top-K.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ranking.normalize import RankedCandidate
    from ...understand.state.session import SessionState
    from .types import Plan


def apply_sequential_gate(
    state: SessionState,
    plan: Plan,
    ranked: list[RankedCandidate],
) -> list[str]:
    """Expose only rank-1 while an informative answer is still pending.

    Rank one can only benefit from converting now; lower-ranked items are
    usually worth deferring because the answer and the free no-hit feedback
    can promote them on the next turn. With no useful question, singleton
    probing is used only when all remaining candidates still fit into the
    remaining one-at-a-time turns plus the final Top-10; otherwise the
    planner's wider slate is preserved. Turn 10 is always full Top-K.
    """

    slate = list(plan.recommendations)
    if state.empty_disclosure_reveal:
        return slate
    sequential_capacity = 10 + (10 - state.turn)
    if (
        state.gate_open
        and state.turn < 10
        and len(slate) > 1
        and (
            plan.ask_attribute is not None
            or len(ranked) <= sequential_capacity
        )
    ):
        return slate[:1]
    return slate
