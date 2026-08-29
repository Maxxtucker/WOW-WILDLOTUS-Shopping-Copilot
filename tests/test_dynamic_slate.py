from __future__ import annotations

import unittest

from agent.decide.clarification.dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateBranch,
    DynamicSlateConfig,
    DynamicSlatePlanner,
    DynamicSlateState,
)
from agent.decide.ranking.normalize import RankedCandidate


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


if __name__ == "__main__":
    unittest.main()
