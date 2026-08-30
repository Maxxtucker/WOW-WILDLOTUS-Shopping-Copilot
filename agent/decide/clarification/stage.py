"""Purpose: Clarifier stage entry for question choice + slate gating.

Input: SessionState, RankedCandidate, top_k.
Output: (Plan, slate: list[str]).
Role: pipeline stage 7. The simulator reads ask_attribute, not message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import QUESTION_ATTRIBUTES
from ...progress import emit, skip_nodes
from .dynamic_adapter import CatalogSignatureTransitionModel
from .dynamic_slate import DynamicSlateAction, DynamicSlateConfig, DynamicSlatePlanner, DynamicSlateState
from .planner import ScoreAwarePlanner
from .questions import eligible_questions, recovery_question
from .replies import make_answer_signature
from .slate import apply_sequential_gate
from .types import Plan

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ..ranking.normalize import RankedCandidate
    from ...understand.state.session import SessionState


def _choose_fallback_question(
    dynamic_state: DynamicSlateState,
    dynamic_planner: DynamicSlatePlanner,
    state_asked: list[str],
    eligible_candidates: list[str | None],
) -> str | None:
    """Select highest-value attribute from eligible candidates.
    
    Used when turn < 10 and planner returned None. Ranks eligible concrete attributes
    by two-step expected utility, avoiding attributes already in state.asked.
    Only selects from candidates that passed the eligibility filter.
    
    Returns None only if no concrete candidate is available.
    """
    # Filter to concrete attributes only, preserving order from eligibility filter
    concrete_candidates = [c for c in eligible_candidates if c is not None]
    
    if not concrete_candidates:
        # No concrete candidate available; allow turn < 10 to return None
        # (this is a boundary case where literally no question is eligible)
        return None
    
    # Score each concrete candidate: for each attribute, find its best slate size's expected value
    best_attr = None
    best_score = -1.0
    best_is_never_asked = False
    
    # Partition candidates by ask status
    never_asked = [c for c in concrete_candidates if c not in state_asked]
    repeatable = concrete_candidates
    
    # Prefer never-asked candidates first
    preference = never_asked if never_asked else repeatable
    
    for attr in preference:
        is_never_asked = attr in never_asked
        attr_best_value = 0.0
        
        # Try all feasible slate sizes and pick the best value for this attribute
        limit = min(10, len(dynamic_state.candidates))
        minimum = 0 if dynamic_planner.config.allow_zero else (1 if limit > 0 else 0)
        for slate_size in range(minimum, limit + 1):
            action = DynamicSlateAction(attr, slate_size)
            value = dynamic_planner._action_value(
                dynamic_state, action, dynamic_planner.config.lookahead_steps
            )
            attr_best_value = max(attr_best_value, value)
        
        # Deterministic tie-break: prefer never-asked, then higher score
        if (
            best_attr is None
            or attr_best_value > best_score
            or (attr_best_value == best_score and is_never_asked and not best_is_never_asked)
        ):
            best_attr = attr
            best_score = attr_best_value
            best_is_never_asked = is_never_asked
    
    return best_attr


class Clarifier:
    """Stage 7: joint question selection and slate construction."""

    def __init__(
        self,
        retriever: CatalogRetriever,
        planner: ScoreAwarePlanner | None = None,
    ) -> None:
        self.retriever = retriever
        legacy = planner or ScoreAwarePlanner(max_planning_candidates=500)
        self.max_planning_candidates = legacy.max_planning_candidates

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
            self.max_planning_candidates,
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
        transition_model = CatalogSignatureTransitionModel(
            answer_signature,
            max_candidates=min(80, self.max_planning_candidates),
        )
        dynamic_state = transition_model.root_state(
            turn=state.turn,
            candidates=ranked,
            questions=questions,
            gate_open=state.gate_open,
            scoring_weights=state.scoring_weights,
        )
        dynamic_planner = DynamicSlatePlanner(
            transition_model,
            DynamicSlateConfig(lookahead_steps=2, allow_zero=True),
        )
        plan = dynamic_planner.plan(
            dynamic_state,
            min(10, int(top_k)),
        )
        
        # Before turn 10, if planner returned None, use fallback to select a concrete question
        if state.turn < 10 and plan.ask_attribute is None:
            fallback_attr = _choose_fallback_question(
                dynamic_state, dynamic_planner, state.asked, questions
            ) or recovery_question(state)
            emit(
                "decide",
                "fallback_question",
                "running",
            )
            # Recompute plan with the fallback attribute, keeping the original slate
            plan = Plan(
                plan.recommendations,
                fallback_attr,
                plan.expected_value,  # Use original value; re-score would be expensive
                f"{plan.reason} (fallback: {fallback_attr})",
            )
            emit(
                "decide",
                "fallback_question",
                "completed",
                {
                    "input": {"original_ask_attribute": None},
                    "output": {"ask_attribute": fallback_attr},
                },
            )
        
        emit(
            "decide",
            "planner",
            "completed",
            {
                "ask_attribute": plan.ask_attribute,
                "reason": plan.reason,
                "input": {
                    "top_k": min(10, int(top_k)),
                    "ranked": len(ranked),
                    "policy": "dynamic_slate",
                    "lookahead_steps": 2,
                },
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
