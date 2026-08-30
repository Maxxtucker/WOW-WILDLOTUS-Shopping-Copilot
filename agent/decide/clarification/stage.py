"""Purpose: Clarifier stage entry for question choice + dynamic slate planning.

Input: SessionState, RankedCandidate, top_k.
Output: (Plan, slate: list[str]).
Role: pipeline stage 7. The simulator reads ask_attribute, not message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...progress import emit, skip_nodes
from .dynamic_adapter import (
    ATTRIBUTE_COVERAGE,
    PARSER_RELIABILITY,
    CatalogSignatureTransitionModel,
)
from .dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateConfig,
    DynamicSlatePlanner,
    DynamicSlateState,
)
from .planner import ScoreAwarePlanner
from .questions import eligible_questions, recovery_question
from .replies import make_answer_signature
from .slate import apply_sequential_gate
from .types import Plan

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...understand.state.session import SessionState
    from ..ranking.normalize import RankedCandidate


def _question_label(attribute: str | None) -> str:
    return "none" if attribute is None else attribute


def _question_viability(attribute: str | None) -> dict[str, object]:
    if attribute is None:
        return {
            "attribute": "none",
            "coverage": None,
            "parser_reliability": None,
            "useful_probability": None,
            "viable": True,
        }
    coverage = float(ATTRIBUTE_COVERAGE.get(attribute, 0.0))
    reliability = float(PARSER_RELIABILITY.get(attribute, 0.50))
    useful_probability = coverage * reliability
    return {
        "attribute": attribute,
        "coverage": round(coverage, 4),
        "parser_reliability": round(reliability, 4),
        "useful_probability": round(useful_probability, 6),
        "viable": useful_probability >= 0.10,
    }


def _choose_fallback_question(
    dynamic_state: DynamicSlateState,
    dynamic_planner: DynamicSlatePlanner,
    state_asked: list[str],
    eligible_candidates: list[str | None],
) -> str | None:
    """Select the highest-value concrete eligible attribute before turn 10."""

    concrete_candidates = [
        candidate for candidate in eligible_candidates if candidate is not None
    ]
    if not concrete_candidates:
        return None

    best_attr = None
    best_score = -1.0
    best_is_never_asked = False
    never_asked = [
        candidate
        for candidate in concrete_candidates
        if candidate not in state_asked
    ]
    preference = never_asked if never_asked else concrete_candidates

    for attr in preference:
        is_never_asked = attr in never_asked
        attr_best_value = 0.0
        limit = min(10, len(dynamic_state.candidates))
        minimum = (
            0
            if dynamic_planner.config.allow_zero
            else (1 if limit > 0 else 0)
        )
        for slate_size in range(minimum, limit + 1):
            action = DynamicSlateAction(attr, slate_size)
            value = dynamic_planner._action_value(
                dynamic_state,
                action,
                dynamic_planner.config.lookahead_steps,
            )
            attr_best_value = max(attr_best_value, value)
        if (
            best_attr is None
            or attr_best_value > best_score
            or (
                attr_best_value == best_score
                and is_never_asked
                and not best_is_never_asked
            )
        ):
            best_attr = attr
            best_score = attr_best_value
            best_is_never_asked = is_never_asked
    return best_attr


class Clarifier:
    """Stage 7: jointly choose question and ranked-prefix slate size."""

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
                "input": {
                    "turn": state.turn,
                    "ranked_candidates": len(ranked),
                    "disclosed": sorted(state.disclosed)[:12],
                },
                "output": {
                    "ready": True,
                    "no_additional_sentinel": "__no_additional__",
                    "scope": "catalog-predicted replies for candidate × attribute",
                },
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
                "input": {
                    "turn": state.turn,
                    "ranked": len(ranked),
                    "already_asked": list(state.asked),
                    "disclosure_empty": state.disclosure_empty,
                },
                "output": {
                    "questions": [_question_label(item) for item in questions],
                },
            },
        )

        transition_model = CatalogSignatureTransitionModel(
            answer_signature,
            max_candidates=min(80, self.max_planning_candidates),
        )
        emit("decide", "viability_filter", "running")
        dynamic_state = transition_model.root_state(
            turn=state.turn,
            candidates=ranked,
            questions=questions,
            gate_open=state.gate_open,
            scoring_weights=state.scoring_weights,
        )
        emit(
            "decide",
            "viability_filter",
            "completed",
            {
                "input": {
                    "minimum_useful_probability": 0.10,
                    "eligible": [
                        _question_viability(item) for item in questions
                    ],
                },
                "output": {
                    "planner_questions": [
                        _question_label(item) for item in dynamic_state.questions
                    ],
                    "injected_recovery_question": (
                        state.turn < 10
                        and bool(dynamic_state.questions)
                        and all(
                            item not in questions
                            for item in dynamic_state.questions
                            if item is not None
                        )
                    ),
                },
            },
        )

        emit("decide", "planning_head", "running")
        head_mass = sum(
            float(candidate.probability)
            for candidate in dynamic_state.candidates
        )
        emit(
            "decide",
            "planning_head",
            "completed",
            {
                "input": {
                    "ranked_candidates": len(ranked),
                    "max_planning_candidates": min(
                        80, self.max_planning_candidates
                    ),
                    "tail_floor": 0.20,
                },
                "output": {
                    "head_count": len(dynamic_state.candidates),
                    "head_probability_mass": round(head_mass, 6),
                    "tail_probability": round(
                        float(dynamic_state.tail_probability), 6
                    ),
                    "gate_probability": round(
                        float(dynamic_state.gate_probability), 4
                    ),
                },
            },
        )

        dynamic_planner = DynamicSlatePlanner(
            transition_model,
            DynamicSlateConfig(lookahead_steps=2, allow_zero=True),
        )
        allowed_top_k = min(10, max(0, int(top_k)))
        k_max = min(allowed_top_k, len(dynamic_state.candidates))
        final_turn = state.turn == 10
        action_count = (
            1
            if final_turn
            else len(dynamic_state.questions) * (k_max + 1)
        )
        emit("decide", "action_space", "running")
        emit(
            "decide",
            "action_space",
            "completed",
            {
                "input": {
                    "questions": [
                        _question_label(item) for item in dynamic_state.questions
                    ],
                    "top_k": allowed_top_k,
                    "head_count": len(dynamic_state.candidates),
                },
                "output": {
                    "k_range": (
                        [k_max, k_max]
                        if final_turn
                        else [0, k_max]
                    ),
                    "allow_zero": not final_turn,
                    "action_count": action_count,
                    "lookahead_steps": 0 if final_turn else 2,
                    "mode": (
                        "final-turn full slate"
                        if final_turn
                        else "question × slate-size joint search"
                    ),
                },
            },
        )

        emit("decide", "planner", "running")
        raw_plan = dynamic_planner.plan(dynamic_state, allowed_top_k)
        emit(
            "decide",
            "planner",
            "completed",
            {
                "ask_attribute": raw_plan.ask_attribute,
                "reason": raw_plan.reason,
                "input": {
                    "turn": state.turn,
                    "gate_probability": dynamic_state.gate_probability,
                    "head_count": len(dynamic_state.candidates),
                    "tail_probability": dynamic_state.tail_probability,
                    "policy": "dynamic_slate",
                    "lookahead_steps": 2,
                },
                "output": {
                    "ask_attribute": raw_plan.ask_attribute,
                    "reason": raw_plan.reason,
                    "planned": len(raw_plan.recommendations),
                    "recommendations": list(raw_plan.recommendations),
                    "expected_value": round(
                        float(raw_plan.expected_value), 4
                    ),
                },
            },
        )

        emit("decide", "fallback_question", "running")
        plan = raw_plan
        fallback_attr: str | None = None
        fallback_used = False
        if state.turn < 10 and raw_plan.ask_attribute is None:
            fallback_attr = _choose_fallback_question(
                dynamic_state,
                dynamic_planner,
                state.asked,
                questions,
            ) or recovery_question(state)
            plan = Plan(
                raw_plan.recommendations,
                fallback_attr,
                raw_plan.expected_value,
                f"{raw_plan.reason} (fallback: {fallback_attr})",
            )
            fallback_used = True
        emit(
            "decide",
            "fallback_question",
            "completed",
            {
                "input": {
                    "turn": state.turn,
                    "planner_ask_attribute": raw_plan.ask_attribute,
                    "eligible": [_question_label(item) for item in questions],
                },
                "output": {
                    "used": fallback_used,
                    "ask_attribute": plan.ask_attribute,
                    "fallback_attribute": fallback_attr,
                    "slate_unchanged": True,
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
                "output": {
                    "slate": len(slate),
                    "gated": gated,
                    "behavior": (
                        "planned slate changed"
                        if gated
                        else "compatibility gate kept planned slate unchanged"
                    ),
                },
            },
        )
        if gated:
            emit(
                "decide",
                "gate_rank1",
                "completed",
                {
                    "output": {
                        "slate": list(slate)[:5],
                        "count": len(slate),
                    },
                },
            )
            skip_nodes(
                "decide",
                "keep_planned",
                why="sequential gate changed the planned slate",
            )
        else:
            skip_nodes(
                "decide",
                "gate_rank1",
                why="current sequential gate is a no-op",
            )
            emit(
                "decide",
                "keep_planned",
                "completed",
                {
                    "input": {"planned": len(plan.recommendations)},
                    "output": {
                        "slate": list(slate)[:5],
                        "count": len(slate),
                        "unchanged": True,
                    },
                },
            )
        return plan, slate
