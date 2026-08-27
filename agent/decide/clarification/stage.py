"""Purpose: Clarifier stage entry for question choice + slate gating.

Input: SessionState, RankedCandidate, top_k.
Output: (Plan, slate: list[str]).
Role: pipeline stage 7. The simulator reads ask_attribute, not message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .planner import ScoreAwarePlanner
from .replies import make_answer_signature
from .slate import apply_sequential_gate
from .types import Plan

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ..ranking.normalize import RankedCandidate
    from ...understand.state.session import SessionState


class Clarifier:
    """Stage 7: joint question selection and slate construction."""

    def __init__(
        self,
        retriever: CatalogRetriever,
        planner: ScoreAwarePlanner | None = None,
    ) -> None:
        self.retriever = retriever
        self.planner = planner or ScoreAwarePlanner(max_planning_candidates=500)

    def apply(
        self,
        state: SessionState,
        ranked: list[RankedCandidate],
        top_k: int,
    ) -> tuple[Plan, list[str]]:
        plan = self.planner.plan(
            state,
            ranked,
            min(10, int(top_k)),
            make_answer_signature(self.retriever, state),
        )
        slate = apply_sequential_gate(state, plan, ranked)
        return plan, slate
