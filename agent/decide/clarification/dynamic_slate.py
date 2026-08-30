"""Finite-horizon dynamic slate sizing for conversational recommendation.

The module is deliberately independent of NLU and retrieval implementations.
An integration supplies counterfactual no-hit/answer branches through the
``DynamicSlateTransitionModel`` protocol.  The planner then searches the
current question and slate size with a two-observation look-ahead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Protocol

from ..ranking.normalize import RankedCandidate
from .types import Plan
from .utility import (
    DEFAULT_RECOMMENDATION_SCORE_WEIGHTS,
    RecommendationScoreWeights,
    hit_utility,
)


@dataclass(frozen=True, slots=True)
class DynamicSlateState:
    """Minimal immutable state consumed by the dynamic slate policy.

    Candidate probabilities are conditional on this state.  Their sum may be
    below one when ``tail_probability`` reserves belief mass for products that
    are outside the planning head.
    """

    turn: int
    candidates: tuple[RankedCandidate, ...]
    questions: tuple[str | None, ...]
    gate_probability: float = 1.0
    tail_probability: float = 0.0
    tail_value: float = 0.0
    cache_key: str = ""
    scoring_weights: RecommendationScoreWeights = DEFAULT_RECOMMENDATION_SCORE_WEIGHTS

    def __post_init__(self) -> None:
        if not 1 <= self.turn <= 10:
            raise ValueError("turn must be between 1 and 10")
        if not isinstance(self.scoring_weights, RecommendationScoreWeights):
            raise TypeError("scoring_weights must be RecommendationScoreWeights")
        if not 0.0 <= self.gate_probability <= 1.0:
            raise ValueError("gate_probability must be between zero and one")
        if not 0.0 <= self.tail_probability <= 1.0:
            raise ValueError("tail_probability must be in [0, 1]")
        if not math.isfinite(self.tail_value) or self.tail_value < 0.0:
            raise ValueError("tail_value must be finite and non-negative")
        mass = self.tail_probability
        for candidate in self.candidates:
            if not math.isfinite(candidate.probability) or candidate.probability < 0.0:
                raise ValueError("candidate probabilities must be finite and non-negative")
            mass += candidate.probability
        if mass > 1.0 + 1e-6:
            raise ValueError("candidate and tail probability mass cannot exceed one")


@dataclass(frozen=True, slots=True)
class DynamicSlateAction:
    """One clarification action: ask an attribute and expose a ranked prefix."""

    ask_attribute: str | None
    slate_size: int


@dataclass(frozen=True, slots=True)
class DynamicSlateBranch:
    """One joint no-hit and answer branch returned by the transition model.

    ``probability`` is the joint branch mass
    ``P(no_hit, answer | state, action)``, not a conditional answer probability.
    ``next_state`` must contain a normalized posterior (plus optional tail mass)
    after miss feedback, answer interpretation, and counterfactual retrieval.
    """

    observation: str
    probability: float
    next_state: DynamicSlateState


class DynamicSlateTransitionModel(Protocol):
    """Adapter implemented by the future response/retrieval integration."""

    def branches(
        self,
        state: DynamicSlateState,
        action: DynamicSlateAction,
    ) -> Sequence[DynamicSlateBranch]:
        """Return no-hit answer branches for ``state`` and ``action``."""


@dataclass(frozen=True, slots=True)
class DynamicSlateConfig:
    """Search depth and action bounds for Dynamic Slating."""

    lookahead_steps: int = 2
    allow_zero: bool = True
    force_full_final_slate: bool = True
    branch_mass_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if self.lookahead_steps < 0:
            raise ValueError("lookahead_steps must be non-negative")
        if self.branch_mass_tolerance < 0.0:
            raise ValueError("branch_mass_tolerance must be non-negative")


class DynamicSlatePlanner:
    """Two-observation expected-TechnicalScore planner over question and k.

    The default depth of two expands answers at turns ``t`` and ``t+1`` and
    uses the best immediate slate at ``t+2`` as its terminal approximation.
    No production pipeline integration is assumed by this module.
    """

    def __init__(
        self,
        transition_model: DynamicSlateTransitionModel,
        config: DynamicSlateConfig | None = None,
    ) -> None:
        self.transition_model = transition_model
        self.config = config or DynamicSlateConfig()

    @staticmethod
    def immediate_value(state: DynamicSlateState, slate_size: int) -> float:
        """Expected current-turn score for the ranked prefix of length ``k``."""

        if slate_size < 0 or slate_size > len(state.candidates):
            raise ValueError("slate_size is outside the candidate range")
        return state.gate_probability * sum(
            candidate.probability
            * hit_utility(state.turn, rank, state.scoring_weights)
            for rank, candidate in enumerate(
                state.candidates[:slate_size], start=1
            )
        )

    def plan(self, state: DynamicSlateState, top_k: int = 10) -> Plan:
        """Return the best current question and ranked prefix."""

        limit = min(10, max(0, int(top_k)), len(state.candidates))
        can_recover_tail = (
            state.turn < 10
            and state.tail_probability > 0.0
            and any(question is not None for question in state.questions)
        )
        if limit == 0 and not can_recover_tail:
            return Plan((), None, 0.0, "dynamic slate: empty planning head")

        if state.turn == 10 and self.config.force_full_final_slate:
            recommendations = tuple(
                candidate.parent_asin for candidate in state.candidates[:limit]
            )
            return Plan(
                recommendations,
                None,
                self.immediate_value(state, limit),
                f"dynamic slate: final-turn full slate, k={limit}",
            )

        actions = self._actions(state, limit)
        scored = [
            (action, self._action_value(state, action, self.config.lookahead_steps))
            for action in actions
        ]
        best_action, best_value = max(scored, key=self._decision_key)

        recommendations = tuple(
            candidate.parent_asin
            for candidate in state.candidates[: best_action.slate_size]
        )
        return Plan(
            recommendations,
            best_action.ask_attribute,
            best_value,
            (
                "dynamic slate: two-observation expected utility, "
                f"k={best_action.slate_size}"
            ),
        )

    def _value(self, state: DynamicSlateState, depth: int) -> float:
        limit = min(10, len(state.candidates))
        if limit == 0:
            return state.tail_value
        if state.turn == 10:
            terminal_k = limit if self.config.force_full_final_slate else self._minimum_k(limit)
            return self.immediate_value(state, terminal_k)
        actions = self._actions(state, limit)
        if depth <= 0:
            return max(self.immediate_value(state, action.slate_size) for action in actions)
        return max(self._action_value(state, action, depth) for action in actions)

    def _action_value(
        self,
        state: DynamicSlateState,
        action: DynamicSlateAction,
        depth: int,
    ) -> float:
        immediate = self.immediate_value(state, action.slate_size)
        if depth <= 0 or state.turn >= 10:
            return immediate

        branches = tuple(self.transition_model.branches(state, action))
        branch_mass = 0.0
        future = 0.0
        for branch in branches:
            probability = float(branch.probability)
            if not math.isfinite(probability) or probability < 0.0:
                raise ValueError("branch probabilities must be finite and non-negative")
            branch_mass += probability
            future += probability * self._value(branch.next_state, depth - 1)

        hit_mass = state.gate_probability * sum(
            candidate.probability
            for candidate in state.candidates[: action.slate_size]
        )
        maximum_branch_mass = max(0.0, 1.0 - hit_mass)
        if branch_mass > maximum_branch_mass + self.config.branch_mass_tolerance:
            raise ValueError(
                "transition branch mass exceeds the probability of continuing"
            )
        return immediate + future

    def _actions(
        self,
        state: DynamicSlateState,
        limit: int,
    ) -> tuple[DynamicSlateAction, ...]:
        questions = state.questions or (None,)
        minimum = self._minimum_k(limit)
        return tuple(
            DynamicSlateAction(question, slate_size)
            for question in questions
            for slate_size in range(minimum, limit + 1)
        )

    def _minimum_k(self, limit: int) -> int:
        if self.config.allow_zero:
            return 0
        return 1 if limit > 0 else 0

    @staticmethod
    def _decision_key(
        row: tuple[DynamicSlateAction, float],
    ) -> tuple[float, bool, int]:
        action, value = row
        # Exact ties prefer an informative question and then a smaller slate.
        return value, action.ask_attribute is not None, -action.slate_size
