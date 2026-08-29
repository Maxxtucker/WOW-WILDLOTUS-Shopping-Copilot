"""Intention router: mock the independent LLM. No regex routing assertions."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.intent_router.router import route_intention
from agent.understand.observation.schema import ObservationExtract
from agent.understand.state import SessionState

_OVERRIDE = "agent.intent_router.router.classify_override"
_ROUTE = "agent.intent_router.router.classify_route"
_PROBE = "agent.intent_router.router.probe_exact_pool"


class IntentRouterTest(unittest.TestCase):
    def test_override_replaces_constraints_and_skips_route_llm(self) -> None:
        state = SessionState("s", {})
        state.category = "Men Shoes"
        state.active_constraints = ["old style"]
        state.legacy_hints = ["Prefer an old style."]
        state.typed_constraints = [object()]
        state.latest_message = "Ignore my earlier preference. Leather instead."
        state.turn_delta = ObservationExtract(
            category="Men Shoes",
            constraints=("leather",),
            source="regex",
        )
        retriever = MagicMock()
        with patch(_OVERRIDE, return_value=True) as override:
            with patch(_ROUTE) as route:
                with patch(_PROBE, return_value={"A", "B"}) as probe:
                    exact = route_intention(state, retriever)
        override.assert_called_once()
        route.assert_not_called()
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(exact, {"A", "B"})
        self.assertEqual(state.intention, "override")
        self.assertEqual(state.active_constraints, ["leather"])
        self.assertEqual(state.legacy_hints, [])
        self.assertEqual(
            [(slot.attribute, slot.surface, slot.is_hard) for slot in state.typed_constraints],
            [("category", "Men Shoes", True)],
        )
        self.assertTrue(state.gate_open)
        self.assertEqual(state.candidate_count, 2)
        self.assertIsNone(state.candidate_count_before_delta)

    def test_non_override_probes_twice_then_labels_buying(self) -> None:
        state = SessionState("s", {})
        state.category = "Men Shoes"
        state.latest_message = "A key requirement is: leather."
        state.turn_delta = ObservationExtract(
            category="Men Shoes",
            constraints=("leather",),
            source="regex",
        )
        pools = [{"A", "B", "C"}, {"A"}]

        def fake_probe(_retriever, _state):
            return pools.pop(0)

        with patch(_OVERRIDE, return_value=False):
            with patch(_ROUTE, return_value="buying") as route:
                with patch(_PROBE, side_effect=fake_probe):
                    exact = route_intention(state, MagicMock())
        self.assertEqual(exact, {"A"})
        self.assertEqual(state.intention, "buying")
        self.assertEqual(state.active_constraints, ["leather"])
        self.assertEqual(state.candidate_count_before_delta, 3)
        self.assertEqual(state.candidate_count, 1)
        route.assert_called_once()
        kwargs = route.call_args.kwargs
        self.assertEqual(kwargs["pool_before"], 3)
        self.assertEqual(kwargs["pool_after"], 1)
        self.assertAlmostEqual(kwargs["ratio"], 1 / 3)

    def test_none_pool_is_not_count_zero(self) -> None:
        state = SessionState("s", {})
        state.latest_message = "Just looking around."
        state.turn_delta = ObservationExtract(category="sandals", source="regex")
        with patch(_OVERRIDE, return_value=False):
            with patch(_ROUTE, return_value="browsing") as route:
                with patch(_PROBE, return_value=None):
                    exact = route_intention(state, MagicMock())
        self.assertIsNone(exact)
        self.assertIsNone(state.candidate_count)
        self.assertIsNone(state.candidate_count_before_delta)
        self.assertEqual(state.intention, "browsing")
        kwargs = route.call_args.kwargs
        self.assertIsNone(kwargs["pool_before"])
        self.assertIsNone(kwargs["pool_after"])
        self.assertIsNone(kwargs["ratio"])

    def test_disclosure_with_instead_accumulates_when_override_is_false(self) -> None:
        state = SessionState("s", {})
        state.category = "Men Shoes"
        state.active_constraints = ["leather"]
        state.latest_message = (
            "For that, what matters is: Use this instead of a belt."
        )
        state.turn_delta = ObservationExtract(
            constraints=("Use this instead of a belt",),
            source="regex",
        )
        with patch(_OVERRIDE, return_value=False):
            with patch(_ROUTE, return_value="buying") as route:
                with patch(_PROBE, return_value={"A"}):
                    exact = route_intention(state, MagicMock())
        route.assert_called_once()
        self.assertEqual(exact, {"A"})
        self.assertFalse(state.override_seen)
        self.assertEqual(state.intention, "buying")
        self.assertEqual(
            state.active_constraints,
            ["leather", "Use this instead of a belt"],
        )

    def test_failsafe_opens_gate_without_override_label(self) -> None:
        state = SessionState("s", {})
        state.turn = 4
        state.gate_open = False
        state.legacy_hints = ["Prefer an old style."]
        state.latest_message = "Completely different requirements now."
        with patch(_OVERRIDE, return_value=False):
            with patch(_ROUTE, return_value="browsing"):
                with patch(_PROBE, return_value=None):
                    route_intention(state, MagicMock())
        self.assertTrue(state.gate_open)
        self.assertFalse(state.override_seen)
        self.assertEqual(state.intention, "browsing")


class HardSoftConstraintTest(unittest.TestCase):
    def tearDown(self) -> None:
        from agent.understand.mode import MODE_REGEX, configure_understand

        configure_understand(MODE_REGEX)

    def test_hard_and_soft_color_coexist(self) -> None:
        from agent.intent_router.writeback import apply_delta
        from agent.retrieve.from_slots import exact_pool_groups, preferred_pairs
        from agent.understand.observation.slots import ConstraintSlot

        state = SessionState("s", {})
        state.turn_delta = ObservationExtract(
            category="Men Shoes",
            slots=(
                ConstraintSlot(
                    attribute="color",
                    surface="pink",
                    canonical="pink",
                    is_hard=True,
                ),
                ConstraintSlot(
                    attribute="color",
                    surface="navy",
                    canonical="blue",
                    is_hard=False,
                ),
            ),
            source="llm",
        )
        apply_delta(state)
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        self.assertEqual(len(colors), 2)
        groups = dict(exact_pool_groups(state))
        self.assertEqual(groups["color"], ("pink",))
        self.assertEqual(preferred_pairs(state), (("color", "blue"),))

    def test_same_value_later_hard_overwrites_soft(self) -> None:
        from agent.intent_router.writeback import apply_delta
        from agent.retrieve.from_slots import exact_pool_groups, preferred_pairs
        from agent.understand.observation.slots import ConstraintSlot

        state = SessionState("s", {})
        state.turn_delta = ObservationExtract(
            slots=(
                ConstraintSlot(
                    attribute="color",
                    surface="black",
                    canonical="black",
                    is_hard=False,
                ),
            ),
            source="llm",
        )
        apply_delta(state)
        state.turn_delta = ObservationExtract(
            slots=(
                ConstraintSlot(
                    attribute="color",
                    surface="black",
                    canonical="black",
                    is_hard=True,
                ),
            ),
            source="llm",
        )
        apply_delta(state)
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        self.assertEqual(len(colors), 1)
        self.assertTrue(colors[0].is_hard)
        self.assertEqual(dict(exact_pool_groups(state))["color"], ("black",))
        self.assertEqual(preferred_pairs(state), ())

    def test_soft_category_does_not_join_hard_category_group(self) -> None:
        from agent.intent_router.writeback import apply_delta
        from agent.retrieve.from_slots import exact_pool_groups
        from agent.understand.observation.slots import ConstraintSlot

        state = SessionState("s", {})
        state.turn_delta = ObservationExtract(
            slots=(
                ConstraintSlot(
                    attribute="category", surface="Men Shoes", is_hard=True
                ),
                ConstraintSlot(
                    attribute="category", surface="sneakers", is_hard=False
                ),
            ),
            source="llm",
        )
        apply_delta(state)
        self.assertEqual(state.category, "Men Shoes")
        self.assertEqual(dict(exact_pool_groups(state))["category"], ("Men Shoes",))

    def test_leftover_regex_is_soft_and_omitted_from_exact_groups(self) -> None:
        from agent.intent_router.writeback import apply_delta
        from agent.retrieve.from_slots import exact_pool_groups
        from agent.understand.mode import MODE_REGEX, configure_understand

        configure_understand(MODE_REGEX)
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        apply_delta(state)
        self.assertFalse(state.gate_open)
        self.assertTrue(
            any(not slot.is_hard for slot in state.typed_constraints)
        )
        self.assertEqual(
            dict(exact_pool_groups(state)).get("category"),
            ("Men Shoes",),
        )
        self.assertEqual(
            [attribute for attribute, _values in exact_pool_groups(state)],
            ["category"],
        )

    def test_summary_category_does_not_upgrade_existing_soft_row(self) -> None:
        from agent.intent_router.writeback import apply_delta
        from agent.retrieve.from_slots import exact_pool_groups
        from agent.understand.observation.slots import ConstraintSlot

        state = SessionState("s", {})
        state.turn_delta = ObservationExtract(
            category="sneakers",
            slots=(
                ConstraintSlot(
                    attribute="category", surface="sneakers", is_hard=False
                ),
            ),
            source="llm",
        )
        apply_delta(state)
        rows = [slot for slot in state.typed_constraints if slot.attribute == "category"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].is_hard)
        self.assertEqual(state.category, "sneakers")
        self.assertNotIn("category", dict(exact_pool_groups(state)))


if __name__ == "__main__":
    unittest.main()
