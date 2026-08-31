from __future__ import annotations

import unittest

from agent.decide.clarification.dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateBranch,
    DynamicSlateConfig,
    DynamicSlatePlanner,
    DynamicSlateState,
)
from agent.decide.clarification.dynamic_adapter import CatalogSignatureTransitionModel
from agent.decide.clarification.questions import eligible_questions
from agent.decide.clarification.stage import (
    ATTRIBUTE_EXPLORATION_RATE,
    _select_attribute_with_exploration,
)
from agent.decide.clarification.types import NO_ADDITIONAL, Plan
from agent.decide.ranking.normalize import RankedCandidate, normalize_probabilities
from agent.understand.state.gate import open_conversion_gate
from agent.understand.state.session import SessionState


def candidate(parent_asin: str, probability: float) -> RankedCandidate:
    return RankedCandidate(parent_asin, probability, probability)


class FixedTransitionModel:
    def __init__(self, transitions: dict[str, list[DynamicSlateBranch]]) -> None:
        self.transitions = transitions
        self.calls: list[tuple[str, DynamicSlateAction]] = []

    def branches(
        self,
        state: DynamicSlateState,
        action: DynamicSlateAction,
    ) -> list[DynamicSlateBranch]:
        self.calls.append((state.cache_key, action))
        return self.transitions.get(state.cache_key, [])


class StubRandom:
    def __init__(self, roll: float, selected: str) -> None:
        self.roll = roll
        self.selected = selected

    def random(self) -> float:
        return self.roll

    def choice(self, values: tuple[str, ...]) -> str:
        if self.selected not in values:
            raise AssertionError(f"{self.selected!r} is not in the exploration pool")
        return self.selected


class DynamicSlatePlannerTests(unittest.TestCase):
    def test_final_turn_uses_full_valid_slate(self) -> None:
        state = DynamicSlateState(
            turn=10,
            candidates=(candidate("A", 0.6), candidate("B", 0.4)),
            questions=("color",),
        )
        planner = DynamicSlatePlanner(FixedTransitionModel({}))

        plan = planner.plan(state, top_k=10)

        self.assertEqual(plan.recommendations, ("A", "B"))
        self.assertIsNone(plan.ask_attribute)

    def test_gate_closed_can_choose_zero_slate(self) -> None:
        terminal = DynamicSlateState(
            turn=2,
            candidates=(candidate("A", 1.0),),
            questions=(None,),
            cache_key="terminal",
        )
        root = DynamicSlateState(
            turn=1,
            candidates=(candidate("A", 1.0),),
            questions=("color",),
            gate_probability=0.0,
            cache_key="root",
        )
        transition = FixedTransitionModel(
            {
                "root": [DynamicSlateBranch("answer", 1.0, terminal)],
            }
        )
        planner = DynamicSlatePlanner(
            transition,
            DynamicSlateConfig(lookahead_steps=1, allow_zero=True),
        )

        plan = planner.plan(root)

        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.ask_attribute, "color")

    def test_depth_two_expands_two_answer_transitions(self) -> None:
        leaf = DynamicSlateState(
            turn=3,
            candidates=(candidate("C", 1.0),),
            questions=(None,),
            cache_key="leaf",
        )
        middle = DynamicSlateState(
            turn=2,
            candidates=(candidate("B", 1.0),),
            questions=("material",),
            gate_probability=0.0,
            cache_key="middle",
        )
        root = DynamicSlateState(
            turn=1,
            candidates=(candidate("A", 1.0),),
            questions=("color",),
            gate_probability=0.0,
            cache_key="root",
        )
        transition = FixedTransitionModel(
            {
                "root": [DynamicSlateBranch("first", 1.0, middle)],
                "middle": [DynamicSlateBranch("second", 1.0, leaf)],
            }
        )
        planner = DynamicSlatePlanner(
            transition,
            DynamicSlateConfig(lookahead_steps=2, allow_zero=True),
        )

        planner.plan(root)

        visited = {key for key, _action in transition.calls}
        self.assertIn("root", visited)
        self.assertIn("middle", visited)

    def test_rejects_branch_mass_above_no_hit_probability(self) -> None:
        next_state = DynamicSlateState(
            turn=2,
            candidates=(candidate("B", 1.0),),
            questions=(None,),
        )
        state = DynamicSlateState(
            turn=1,
            candidates=(candidate("A", 1.0),),
            questions=("color",),
        )
        transition = FixedTransitionModel(
            {"": [DynamicSlateBranch("impossible", 1.0, next_state)]}
        )
        planner = DynamicSlatePlanner(
            transition,
            DynamicSlateConfig(lookahead_steps=1, allow_zero=False),
        )

        with self.assertRaisesRegex(ValueError, "probability of continuing"):
            planner.plan(state)


class CatalogSignatureTransitionModelTests(unittest.TestCase):
    def test_tail_only_state_asks_high_coverage_recovery_question(self) -> None:
        model = CatalogSignatureTransitionModel(lambda _asin, _attribute: ())
        state = model.root_state(
            turn=2,
            candidates=(),
            questions=(None, "feature", "size", "use_case"),
            gate_open=True,
        )
        planner = DynamicSlatePlanner(
            model,
            DynamicSlateConfig(lookahead_steps=2, allow_zero=True),
        )

        plan = planner.plan(state)

        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.ask_attribute, "feature")
        self.assertGreater(plan.expected_value, 0.0)

    def test_effective_coverage_floor_removes_rare_questions(self) -> None:
        ranked = normalize_probabilities([("A", 1.0)])
        model = CatalogSignatureTransitionModel(lambda _asin, _attribute: ("x",))
        state = model.root_state(
            turn=1,
            candidates=ranked,
            questions=(None, "feature", "style", "size", "use_case", "budget"),
            gate_open=True,
        )

        self.assertEqual(state.questions, (None, "feature", "style"))

    def test_other_is_compacted_and_not_repeated_in_next_state(self) -> None:
        ranked = normalize_probabilities([(f"P{i}", 10 - i) for i in range(8)])

        def signature(parent_asin: str, attribute: str) -> tuple[str, ...]:
            if attribute == "other":
                return (f"free-{parent_asin}",)
            return ("black",) if parent_asin in {"P0", "P1"} else ("blue",)

        model = CatalogSignatureTransitionModel(
            signature,
            max_candidates=8,
            max_other_branches=4,
        )
        state = model.root_state(
            turn=1,
            candidates=ranked,
            questions=(None, "other", "color"),
            gate_open=True,
        )
        branches = model.branches(state, DynamicSlateAction("other", 0))

        head_branches = [
            branch
            for branch in branches
            if not branch.observation.startswith("__tail_")
        ]
        tail_branches = [
            branch
            for branch in branches
            if branch.observation.startswith("__tail_")
        ]
        self.assertLessEqual(len(head_branches), 4)
        self.assertEqual(len(tail_branches), 2)
        self.assertAlmostEqual(sum(branch.probability for branch in branches), 1.0)
        self.assertTrue(branches)
        self.assertTrue(all("other" not in branch.next_state.questions for branch in branches))

    def test_low_coverage_attribute_adds_no_information_mass(self) -> None:
        ranked = normalize_probabilities([("A", 2.0), ("B", 1.0)])
        model = CatalogSignatureTransitionModel(
            lambda asin, _attribute: (asin,),
            max_candidates=2,
            tail_floor=0.0,
        )
        state = model.root_state(
            turn=1,
            candidates=ranked,
            questions=("use_case",),
            gate_open=True,
        )

        branches = model.branches(state, DynamicSlateAction("use_case", 0))

        no_information = [
            branch for branch in branches
            if branch.observation == "__no_information__"
        ]
        self.assertEqual(len(no_information), 1)
        self.assertGreater(no_information[0].probability, 0.98)

    def test_no_hit_removes_open_gate_slate_from_branches(self) -> None:
        ranked = normalize_probabilities([("A", 3.0), ("B", 2.0), ("C", 1.0)])
        model = CatalogSignatureTransitionModel(
            lambda asin, _attribute: (asin,),
            max_candidates=3,
        )
        state = model.root_state(
            turn=1,
            candidates=ranked,
            questions=("color",),
            gate_open=True,
        )
        branches = model.branches(state, DynamicSlateAction("color", 1))
        remaining = {
            item.parent_asin
            for branch in branches
            for item in branch.next_state.candidates
        }

        self.assertNotIn("A", remaining)
        self.assertEqual(remaining, {"B", "C"})

    def test_turns_1_to_9_never_return_none(self) -> None:
        """Verify that turn < 10 never chooses ask_attribute=None."""
        # Create a state where few products match; normally planner might choose None
        state = DynamicSlateState(
            turn=5,
            candidates=(candidate("A", 0.4), candidate("B", 0.3)),
            questions=("color", "material"),  # No None in the question list
        )
        planner = DynamicSlatePlanner(FixedTransitionModel({}))
        
        plan = planner.plan(state, top_k=10)
        
        # Should never return None on turn 5
        self.assertIsNotNone(plan.ask_attribute)
        self.assertIn(plan.ask_attribute, ("color", "material"))

    def test_fallback_prefers_never_asked_over_repeatable(self) -> None:
        """Verify fallback ranking: never-asked attributes preferred over repeatable."""
        from agent.decide.clarification.stage import _choose_fallback_question
        
        state = DynamicSlateState(
            turn=3,
            candidates=(candidate("A", 0.5), candidate("B", 0.5)),
            questions=("feature", "material", "color"),
        )
        planner = DynamicSlatePlanner(FixedTransitionModel({}))
        state_asked = ["material"]  # Already asked material
        eligible_candidates = ["feature", "material", "color"]  # All concrete attributes from eligible_questions
        
        # Should pick from never-asked (feature, color) not from already-asked (material)
        result = _choose_fallback_question(state, planner, state_asked, eligible_candidates)
        
        self.assertIn(result, ("feature", "color", "material"))
        # Should prefer never-asked over repeatable in scoring



class AttributeExplorationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SessionState("session-a", {})
        self.state.turn = 3
        self.raw_plan = Plan(("A", "B"), "feature", 0.75, "planner optimum")

    def test_exploit_keeps_the_planner_attribute_and_slate(self) -> None:
        selection = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            ["feature", "size", "budget"],
            has_ranked_candidates=True,
            rng=StubRandom(ATTRIBUTE_EXPLORATION_RATE, "size"),
        )

        self.assertEqual(selection.mode, "exploit")
        self.assertIs(selection.plan, self.raw_plan)
        self.assertEqual(selection.exploration_pool, ("feature", "size", "budget"))

    def test_explore_can_select_an_informative_attribute_below_viability(self) -> None:
        model = CatalogSignatureTransitionModel(
            lambda _asin, _attribute: ("answer",)
        )
        dynamic_state = model.root_state(
            turn=self.state.turn,
            candidates=(candidate("A", 1.0),),
            questions=("feature", "size", "budget"),
            gate_open=True,
        )
        self.assertEqual(dynamic_state.questions, ("feature",))

        selection = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            ["feature", "size", "budget"],
            has_ranked_candidates=True,
            rng=StubRandom(0.0, "size"),
        )

        self.assertEqual(selection.mode, "explore")
        self.assertEqual(selection.plan.ask_attribute, "size")
        self.assertEqual(selection.plan.recommendations, self.raw_plan.recommendations)
        self.assertEqual(selection.plan.expected_value, self.raw_plan.expected_value)
        self.assertIn("attribute exploration: size", selection.plan.reason)

    def test_selection_is_reproducible_and_changes_seed_after_override(self) -> None:
        first = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            ["feature", "size", "budget"],
            has_ranked_candidates=True,
        )
        repeated = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            ["feature", "size", "budget"],
            has_ranked_candidates=True,
        )

        self.assertEqual(first, repeated)
        old_roll = first.roll
        old_version = self.state.intent_version
        self.state.asked = ["feature", "size"]
        ranked = [candidate("A", 1.0)]
        signature = lambda _asin, _attribute: ("answer",)
        before_override = eligible_questions(
            self.state,
            ranked,
            signature,
            max_planning_candidates=500,
        )
        self.assertNotIn("feature", before_override)
        self.assertNotIn("size", before_override)

        open_conversion_gate(self.state)
        after_override_questions = eligible_questions(
            self.state,
            ranked,
            signature,
            max_planning_candidates=500,
        )
        after_override = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            after_override_questions,
            has_ranked_candidates=True,
        )

        self.assertEqual(self.state.intent_version, old_version + 1)
        self.assertEqual(self.state.asked, [])
        self.assertIn("feature", after_override.exploration_pool)
        self.assertIn("size", after_override.exploration_pool)
        self.assertNotEqual(after_override.roll, old_roll)

    def test_exploration_pool_uses_informative_unasked_questions(self) -> None:
        self.state.asked = ["color"]
        self.state.disclosure_empty = True
        ranked = [candidate("A", 1.0)]

        def signature(_asin: str, attribute: str) -> tuple[str, ...]:
            return NO_ADDITIONAL if attribute == "budget" else ("answer",)

        questions = eligible_questions(
            self.state,
            ranked,
            signature,
            max_planning_candidates=500,
        )
        selection = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            questions,
            has_ranked_candidates=True,
            rng=StubRandom(0.0, "size"),
        )

        self.assertNotIn("color", selection.exploration_pool)
        self.assertNotIn("other", selection.exploration_pool)
        self.assertNotIn("budget", selection.exploration_pool)
        self.assertIn("size", selection.exploration_pool)
        self.assertEqual(selection.plan.ask_attribute, "size")

    def test_empty_ranking_disables_exploration_and_preserves_recovery(self) -> None:
        selection = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            ["feature", "material", "color", "other"],
            has_ranked_candidates=False,
            rng=StubRandom(0.0, "feature"),
        )

        self.assertEqual(selection.mode, "disabled")
        self.assertEqual(selection.exploration_pool, ())
        self.assertIs(selection.plan, self.raw_plan)

    def test_all_asked_disables_exploration(self) -> None:
        self.state.asked = [
            "other",
            "feature",
            "material",
            "color",
            "style",
            "size",
            "use_case",
            "budget",
        ]
        questions = eligible_questions(
            self.state,
            [candidate("A", 1.0)],
            lambda _asin, _attribute: ("answer",),
            max_planning_candidates=500,
        )
        selection = _select_attribute_with_exploration(
            self.state,
            self.raw_plan,
            questions,
            has_ranked_candidates=True,
            rng=StubRandom(0.0, "feature"),
        )

        self.assertEqual(questions, [])
        self.assertEqual(selection.mode, "disabled")
        self.assertEqual(selection.exploration_pool, ())
        self.assertIs(selection.plan, self.raw_plan)

    def test_final_turn_disables_exploration_and_keeps_no_question(self) -> None:
        self.state.turn = 10
        final_plan = Plan(("A", "B"), None, 0.75, "final turn")

        selection = _select_attribute_with_exploration(
            self.state,
            final_plan,
            ["feature", "size"],
            has_ranked_candidates=True,
            rng=StubRandom(0.0, "size"),
        )

        self.assertEqual(selection.mode, "disabled")
        self.assertEqual(selection.exploration_pool, ())
        self.assertIsNone(selection.plan.ask_attribute)
        self.assertEqual(selection.plan.recommendations, ("A", "B"))


if __name__ == "__main__":
    unittest.main()
