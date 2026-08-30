"""Purpose: Clarifier stage entry for question choice + slate gating.

Input: SessionState, RankedCandidate, top_k.
Output: (Plan, slate: list[str]).
Role: pipeline stage 7. The simulator reads ask_attribute, not message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...progress import emit, skip_nodes
from .planner import ScoreAwarePlanner
from .questions import eligible_questions
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
        emit("decide", "answer_signature", "running")
        answer_signature = make_answer_signature(self.retriever, state)
        emit(
            "decide",
            "answer_signature",
            "completed",
            {
                "input": {"disclosed": list(state.disclosed)[:8], "turn": state.turn},
                "output": {"ready": True},
            },
        )
        emit("decide", "eligible_questions", "running")
        questions = eligible_questions(
            state,
            ranked,
            answer_signature,
            self.planner.max_planning_candidates,
        )
        emit(
            "decide",
            "eligible_questions",
            "completed",
            {
                "input": {"turn": state.turn, "ranked": len(ranked)},
                "output": {"questions": [item if item is not None else "none" for item in questions]},
            },
        )
        emit("decide", "planner", "running")
        plan = self.planner.plan(
            state,
            ranked,
            min(10, int(top_k)),
            answer_signature,
        )
        emit(
            "decide",
            "planner",
            "completed",
            {
                "ask_attribute": plan.ask_attribute,
                "reason": plan.reason,
                "input": {"top_k": min(10, int(top_k)), "ranked": len(ranked)},
                "output": {
                    "ask_attribute": plan.ask_attribute,
                    "reason": plan.reason,
                    "planned": len(plan.recommendations),
                    "expected_value": round(float(plan.expected_value), 4),
                },
            },
        )
        emit("decide", "sequential_gate", "running")
        slate = apply_sequential_gate(state, plan, ranked)
        gated = list(plan.recommendations) != list(slate)
        emit(
            "decide",
            "sequential_gate",
            "completed",
            {
                "gated": gated,
                "input": {
                    "planned": len(plan.recommendations),
                    "gate_open": state.gate_open,
                    "turn": state.turn,
                    "empty_disclosure_reveal": state.empty_disclosure_reveal,
                },
                "output": {"slate": len(slate), "gated": gated},
            },
        )
        if gated:
            emit(
                "decide",
                "gate_rank1",
                "completed",
                {
                    "output": {"slate": list(slate)[:5], "count": len(slate)},
                },
            )
            skip_nodes(
                "decide",
                "keep_planned",
                why="sequential gate kept rank-1",
            )
        else:
            skip_nodes(
                "decide",
                "gate_rank1",
                why="gate did not truncate the planned slate",
            )
            emit(
                "decide",
                "keep_planned",
                "completed",
                {
                    "output": {
                        "slate": list(slate)[:5],
                        "count": len(slate),
                    },
                },
            )
        return plan, slate
