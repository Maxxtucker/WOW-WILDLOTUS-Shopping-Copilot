"""Purpose: execute the slate selected by the joint planner.

Input: SessionState, Plan, ranked list.
Output: parent_asin list selected by the planner.
Role: keep planning and execution consistent; slate-size risk belongs in the joint objective.
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
    """Return the planned slate without a contradictory post-plan override."""

    del state, ranked
    return list(plan.recommendations)
