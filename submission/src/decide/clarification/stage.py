"""Purpose: Clarifier stage entry for question choice + dynamic slate planning.

Input: SessionState, RankedCandidate, top_k.
Output: (Plan, slate: list[str]).
Role: pipeline stage 7. The simulator reads ask_attribute, not message.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...progress import emit, progress_enabled, skip_nodes
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

ATTRIBUTE_EXPLORATION_RATE = 0.20

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...understand.state.session import SessionState
    from ..ranking.normalize import RankedCandidate


@dataclass(frozen=True)
class AttributeSelection:
    plan: Plan
    mode: str
    roll: float | None
    exploration_pool: tuple[str, ...]


def _question_label(attribute: str | None) -> str:
    return "none" if attribute is None else attribute


def _select_attribute_with_exploration(
    state: SessionState,
    raw_plan: Plan,
    eligible_candidates: Sequence[str | None],
    *,
    has_ranked_candidates: bool,
    rng: random.Random | None = None,
) -> AttributeSelection:
    """Use deterministic epsilon-greedy selection over informative questions."""

    exploration_pool = (
        tuple(
            attribute
            for attribute in eligible_candidates
            if attribute is not None
        )
        if state.turn < 10 and has_ranked_candidates
        else ()
    )
    if not exploration_pool:
        return AttributeSelection(raw_plan, "disabled", None, exploration_pool)

    source = rng or random.Random(
        f"{state.session_id}\0{state.intent_version}\0{state.turn}"
    )
    roll = source.random()
    if roll >= ATTRIBUTE_EXPLORATION_RATE:
        return AttributeSelection(raw_plan, "exploit", roll, exploration_pool)

    selected = source.choice(exploration_pool)
    plan = Plan(
        raw_plan.recommendations,
        selected,
        raw_plan.expected_value,
        f"{raw_plan.reason} (attribute exploration: {selected})",
    )
    return AttributeSelection(plan, "explore", roll, exploration_pool)


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
        selected_k = len(raw_plan.recommendations)
        selected_candidates = dynamic_state.candidates[:selected_k]
        scoring = dynamic_state.scoring_weights
        gate_probability = float(dynamic_state.gate_probability)
        hit_value = gate_probability * sum(
            float(candidate.probability) * float(scoring.hitrate_weight)
            for candidate in selected_candidates
        )
        mrr_value = gate_probability * sum(
            float(candidate.probability)
            * float(scoring.mrr_weight)
            / rank
            for rank, candidate in enumerate(selected_candidates, start=1)
        )
        efficiency_factor = max(0.0, (11 - dynamic_state.turn) / 10.0)
        efficiency_value = gate_probability * sum(
            float(candidate.probability)
            * float(scoring.efficiency_weight)
            * efficiency_factor
            for candidate in selected_candidates
        )
        immediate_value = hit_value + mrr_value + efficiency_value
        selected_action = DynamicSlateAction(raw_plan.ask_attribute, selected_k)
        selected_branches = (
            ()
            if dynamic_state.turn >= 10 or not progress_enabled()
            else transition_model.branches(dynamic_state, selected_action)
        )
        answer_rows = [
            {
                "observation": branch.observation,
                "probability": round(float(branch.probability), 6),
            }
            for branch in selected_branches
            if not branch.observation.startswith("__tail_")
        ]
        tail_rows = [
            {
                "observation": branch.observation,
                "probability": round(float(branch.probability), 6),
                "terminal_value": round(
                    float(branch.next_state.tail_value), 6
                ),
            }
            for branch in selected_branches
            if branch.observation.startswith("__tail_")
        ]
        component_common = {
            "turn": dynamic_state.turn,
            "slate_size": selected_k,
            "gate_probability": gate_probability,
            "selected_probability_mass": round(
                sum(
                    float(candidate.probability)
                    for candidate in selected_candidates
                ),
                6,
            ),
        }
        for node, weight, value, formula in (
            (
                "hit_component",
                scoring.hitrate_weight,
                hit_value,
                "gate × candidate probability × hit weight",
            ),
            (
                "mrr_component",
                scoring.mrr_weight,
                mrr_value,
                "gate × candidate probability × MRR weight / rank",
            ),
            (
                "efficiency_component",
                scoring.efficiency_weight,
                efficiency_value,
                "gate × candidate probability × efficiency weight × (11-turn)/10",
            ),
        ):
            emit(
                "decide",
                node,
                "completed",
                {
                    "input": {
                        **component_common,
                        "weight": round(float(weight), 6),
                        "formula": formula,
                    },
                    "output": {"expected_contribution": round(value, 6)},
                },
            )
        emit(
            "decide",
            "immediate_value",
            "completed",
            {
                "input": {
                    "hit": round(hit_value, 6),
                    "mrr": round(mrr_value, 6),
                    "efficiency": round(efficiency_value, 6),
                },
                "output": {"immediate_value": round(immediate_value, 6)},
            },
        )
        emit(
            "decide",
            "answer_branches",
            "completed",
            {
                "input": {
                    "ask_attribute": raw_plan.ask_attribute,
                    "slate_size": selected_k,
                    "max_typed_branches": transition_model.max_typed_branches,
                    "max_other_branches": transition_model.max_other_branches,
                },
                "output": {
                    "branch_count": len(answer_rows),
                    "branch_mass": round(
                        sum(row["probability"] for row in answer_rows), 6
                    ),
                    "branches": answer_rows[:12],
                },
            },
        )
        emit(
            "decide",
            "tail_branches",
            "completed",
            {
                "input": {
                    "tail_probability": round(
                        float(dynamic_state.tail_probability), 6
                    ),
                    "tail_retrieval_success": (
                        transition_model.tail_retrieval_success
                    ),
                },
                "output": {
                    "branch_count": len(tail_rows),
                    "branches": tail_rows,
                },
            },
        )
        future_value = float(raw_plan.expected_value) - immediate_value
        emit(
            "decide",
            "future_value",
            "completed",
            {
                "input": {
                    "lookahead_steps": 0 if final_turn else 2,
                    "answer_branch_count": len(answer_rows),
                    "tail_branch_count": len(tail_rows),
                },
                "output": {
                    "expected_future_value": round(future_value, 6),
                },
            },
        )
        emit(
            "decide",
            "planner",
            "completed",
            {
                "input": {
                    "action_count": action_count,
                    "immediate_value": round(immediate_value, 6),
                    "future_value": round(future_value, 6),
                    "tie_break": "informative question, then smaller slate",
                },
                "output": {
                    "ask_attribute": raw_plan.ask_attribute,
                    "planned": selected_k,
                    "recommendations": list(raw_plan.recommendations),
                    "expected_value": round(
                        float(raw_plan.expected_value), 6
                    ),
                    "reason": raw_plan.reason,
                },
            },
        )
        selection = _select_attribute_with_exploration(
            state,
            raw_plan,
            questions,
            has_ranked_candidates=bool(ranked),
        )
        plan = selection.plan
        emit(
            "decide",
            "epsilon_roll",
            "completed",
            {
                "input": {
                    "seed_parts": {
                        "session_id": state.session_id,
                        "intent_version": state.intent_version,
                        "turn": state.turn,
                    },
                    "epsilon": ATTRIBUTE_EXPLORATION_RATE,
                    "exploration_pool": list(selection.exploration_pool),
                },
                "output": {
                    "roll": (
                        None
                        if selection.roll is None
                        else round(selection.roll, 6)
                    ),
                    "selection_mode": selection.mode,
                    "branch": (
                        "technical exploit"
                        if selection.mode == "exploit"
                        else "uniform eligible exploration"
                        if selection.mode == "explore"
                        else "disabled"
                    ),
                },
            },
        )
        if selection.mode == "exploit":
            emit(
                "decide",
                "technical_exploit",
                "completed",
                {
                    "input": {
                        "planner_attribute": raw_plan.ask_attribute,
                        "roll": round(float(selection.roll), 6),
                        "threshold": ATTRIBUTE_EXPLORATION_RATE,
                    },
                    "output": {
                        "ask_attribute": plan.ask_attribute,
                        "slate_unchanged": True,
                    },
                },
            )
            skip_nodes(
                "decide",
                "uniform_explore",
                why="epsilon roll selected the technical-score plan",
            )
        elif selection.mode == "explore":
            skip_nodes(
                "decide",
                "technical_exploit",
                why="epsilon roll selected uniform attribute exploration",
            )
            emit(
                "decide",
                "uniform_explore",
                "completed",
                {
                    "input": {
                        "pool": list(selection.exploration_pool),
                        "roll": round(float(selection.roll), 6),
                        "threshold": ATTRIBUTE_EXPLORATION_RATE,
                    },
                    "output": {
                        "selected": plan.ask_attribute,
                        "selection": "uniform seeded choice",
                        "slate_unchanged": True,
                    },
                },
            )
        else:
            skip_nodes(
                "decide",
                "technical_exploit",
                "uniform_explore",
                why="epsilon-greedy is disabled on the final turn or without an exploration pool",
            )
        emit(
            "decide",
            "selected_attribute",
            "completed",
            {
                "input": {
                    "planner_ask_attribute": raw_plan.ask_attribute,
                    "selection_mode": selection.mode,
                    "exploration_pool": list(selection.exploration_pool),
                },
                "output": {
                    "ask_attribute": plan.ask_attribute,
                    "planned": len(plan.recommendations),
                    "recommendations": list(plan.recommendations),
                    "expected_value": round(float(plan.expected_value), 6),
                    "slate_unchanged": True,
                },
                "runtime": {
                    "turn": state.turn,
                    "gate_probability": dynamic_state.gate_probability,
                    "head_count": len(dynamic_state.candidates),
                    "tail_probability": dynamic_state.tail_probability,
                    "policy": "dynamic_slate",
                    "lookahead_steps": 2,
                    "attribute_exploration_rate": ATTRIBUTE_EXPLORATION_RATE,
                },
            },
        )

        emit("decide", "fallback_question", "running")
        fallback_attr: str | None = None
        fallback_used = False
        if state.turn < 10 and plan.ask_attribute is None:
            fallback_attr = _choose_fallback_question(
                dynamic_state,
                dynamic_planner,
                state.asked,
                questions,
            ) or recovery_question(state)
            plan = Plan(
                plan.recommendations,
                fallback_attr,
                plan.expected_value,
                f"{plan.reason} (fallback: {fallback_attr})",
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
                    "selection_mode": selection.mode,
                    "selected_ask_attribute": selection.plan.ask_attribute,
                    "exploration_pool": list(selection.exploration_pool),
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
