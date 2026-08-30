from __future__ import annotations

import math
from threading import RLock
import unittest

from agent import Agent
from agent.decide.clarification.dynamic_adapter import (
    CatalogSignatureTransitionModel,
)
from agent.decide.clarification.dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateBranch,
    DynamicSlateConfig,
    DynamicSlatePlanner,
    DynamicSlateState,
)
from agent.decide.clarification.utility import (
    DEFAULT_SLIDER_POSITION,
    RecommendationScoreWeights,
    hit_utility,
)
from agent.decide.ranking.normalize import normalize_probabilities
from agent.decide.ranking.normalize import RankedCandidate
from agent.understand.state.session import SessionState


class RecommendationScoreWeightsTest(unittest.TestCase):
    def test_slider_endpoints_and_default(self) -> None:
        left = RecommendationScoreWeights.from_slider_position(0)
        default = RecommendationScoreWeights.from_slider_position(
            DEFAULT_SLIDER_POSITION
        )
        right = RecommendationScoreWeights.from_slider_position(100)

        self.assertEqual((left.hitrate_weight, left.mrr_weight), (0.72, 0.08))
        self.assertEqual(
            (default.hitrate_weight, default.mrr_weight),
            (0.50, 0.30),
        )
        self.assertEqual((right.hitrate_weight, right.mrr_weight), (0.08, 0.72))

    def test_recommendation_budget_and_efficiency_are_fixed(self) -> None:
        for position in range(101):
            weights = RecommendationScoreWeights.from_slider_position(position)
            self.assertAlmostEqual(
                weights.hitrate_weight + weights.mrr_weight,
                0.80,
            )
            self.assertEqual(weights.efficiency_weight, 0.20)

    def test_slider_rejects_invalid_positions(self) -> None:
        for position in (None, True, "bad", -0.01, 100.01, math.nan, math.inf):
            with self.subTest(position=position):
                with self.assertRaises(ValueError):
                    RecommendationScoreWeights.from_slider_position(position)

    def test_default_hit_utility_is_unchanged(self) -> None:
        self.assertAlmostEqual(hit_utility(1, 10), 0.73)
        self.assertAlmostEqual(hit_utility(2, 1), 0.98)

    def test_preference_changes_lower_rank_value_concentration(self) -> None:
        more = RecommendationScoreWeights.from_slider_position(0)
        precise = RecommendationScoreWeights.from_slider_position(100)

        self.assertGreater(hit_utility(1, 10, more), hit_utility(1, 10, precise))
        self.assertAlmostEqual(
            hit_utility(1, 1, more),
            hit_utility(1, 1, precise),
        )
        self.assertGreater(
            hit_utility(1, 1, precise) - hit_utility(1, 10, precise),
            hit_utility(1, 1, more) - hit_utility(1, 10, more),
        )


class DynamicPreferencePropagationTest(unittest.TestCase):
    def test_root_answer_and_tail_states_keep_weights(self) -> None:
        weights = RecommendationScoreWeights.from_slider_position(0)
        ranked = normalize_probabilities([("A", 2.0), ("B", 1.0)])
        model = CatalogSignatureTransitionModel(
            lambda asin, _attribute: (asin,),
            max_candidates=2,
        )
        root = model.root_state(
            turn=1,
            candidates=ranked,
            questions=("feature",),
            gate_open=True,
            scoring_weights=weights,
        )

        branches = model.branches(root, DynamicSlateAction("feature", 0))

        self.assertEqual(root.scoring_weights, weights)
        self.assertTrue(branches)
        self.assertTrue(
            all(branch.next_state.scoring_weights == weights for branch in branches)
        )
        self.assertTrue(
            any(
                branch.observation == "__tail_retrieval__"
                for branch in branches
            )
        )

    def test_more_preference_can_choose_a_larger_slate(self) -> None:
        class RecoveryModel:
            def branches(self, state, action):
                remaining = sum(
                    item.probability
                    for item in state.candidates[action.slate_size :]
                )
                if remaining <= 0.0:
                    return ()
                recovered = DynamicSlateState(
                    turn=2,
                    candidates=(RankedCandidate("R", 1.0, 0.80),),
                    questions=(None,),
                    tail_probability=0.20,
                    scoring_weights=state.scoring_weights,
                )
                return (DynamicSlateBranch("recovered", remaining, recovered),)

        planner = DynamicSlatePlanner(
            RecoveryModel(),
            DynamicSlateConfig(lookahead_steps=1, allow_zero=True),
        )

        def plan_at(position):
            state = DynamicSlateState(
                turn=1,
                candidates=(
                    RankedCandidate("A", 1.0, 0.60),
                    RankedCandidate("B", 0.9, 0.40),
                ),
                questions=(None,),
                scoring_weights=RecommendationScoreWeights.from_slider_position(
                    position
                ),
            )
            return planner.plan(state, top_k=2)

        more = plan_at(0)
        precise = plan_at(100)

        self.assertEqual(more.recommendations, ("A", "B"))
        self.assertEqual(precise.recommendations, ("A",))


class _PipelineStub:
    def run_traced(self, state, user_message, turn, top_k):
        return ({"message": user_message}, object())


class AgentPreferenceLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Agent.__new__(Agent)
        self.agent.sessions = {"s": SessionState("s", {})}
        self.agent._lock = RLock()
        self.agent.pipeline = _PipelineStub()

    def test_preference_can_be_set_before_first_respond(self) -> None:
        self.agent.set_recommendation_preference("s", 0)
        state = self.agent.sessions["s"]

        self.assertEqual(state.scoring_weights.hitrate_weight, 0.72)
        self.assertEqual(state.recommendation_preference_position, 0.0)
        self.assertFalse(state.recommendation_preference_locked)

    def test_first_respond_locks_and_late_change_is_rejected(self) -> None:
        self.agent.set_recommendation_preference("s", 100)
        state = self.agent.sessions["s"]
        original = state.scoring_weights

        self.agent.respond("s", "hello", 1, 10)

        self.assertTrue(state.recommendation_preference_locked)
        with self.assertRaises(RuntimeError):
            self.agent.set_recommendation_preference("s", 0)
        self.assertEqual(state.scoring_weights, original)

    def test_invalid_change_does_not_mutate_state(self) -> None:
        state = self.agent.sessions["s"]
        original = state.scoring_weights

        with self.assertRaises(ValueError):
            self.agent.set_recommendation_preference("s", math.nan)

        self.assertEqual(state.scoring_weights, original)
        self.assertFalse(state.recommendation_preference_locked)


if __name__ == "__main__":
    unittest.main()
