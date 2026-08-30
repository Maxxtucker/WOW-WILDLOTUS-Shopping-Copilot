"""Two-level override: L1 clear-all, L2 drop delta fields, then apply_delta.

Does not call Ollama or read public_set.jsonl.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.intent_router.llm import (
    OverrideDecision,
    categories_distant,
    classify_override,
    should_keep_l1,
)
from agent.intent_router.router import route_intention, strong_override_fallback
from agent.intent_router.writeback import (
    apply_delta,
    apply_override_decision,
    delta_attribute_names,
    delta_has_category,
    drop_typed,
)
from agent.progress import progress_listener
from agent.understand.observation.schema import ObservationExtract
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState

_OVERRIDE = "agent.intent_router.router.classify_override"
_ROUTE = "agent.intent_router.router.classify_route"
_PROBE = "agent.intent_router.router.probe_exact_pool"


def _slot(attribute: str, surface: str, *, hard: bool = True) -> ConstraintSlot:
    return ConstraintSlot(attribute=attribute, surface=surface, is_hard=hard)


def _seeded() -> SessionState:
    state = SessionState("ov-h", {})
    state.category = "sandals"
    state.typed_constraints = [
        _slot("category", "sandals"),
        _slot("color", "pink"),
        _slot("material", "suede"),
    ]
    state.active_constraints = ["pink", "suede"]
    state.excluded_asins = {"OLD"}
    state.shown_asins = {"OLD"}
    state.last_ranked = ["OLD", "NEXT"]
    state.gate_open = False
    return state


class DeltaFieldsTest(unittest.TestCase):
    def test_names_from_slots_category_and_constraints(self) -> None:
        delta = ObservationExtract(
            category="backpack",
            constraints=("leather",),
            slots=(_slot("color", "navy"),),
            source="llm",
        )
        self.assertEqual(
            delta_attribute_names(delta),
            {"category", "color", "material"},
        )
        self.assertTrue(delta_has_category(delta))

    def test_material_only_has_no_category(self) -> None:
        delta = ObservationExtract(
            slots=(_slot("material", "polyester"),),
            source="llm",
        )
        self.assertEqual(delta_attribute_names(delta), {"material"})
        self.assertFalse(delta_has_category(delta))


class CategoryDistanceTest(unittest.TestCase):
    def test_distant_and_close_pairs(self) -> None:
        self.assertTrue(categories_distant("sandals", "backpack"))
        self.assertFalse(categories_distant("sandals", "women sandals"))
        self.assertFalse(categories_distant("running shoes", "formal shoes"))
        self.assertFalse(categories_distant("shoe", "running shoe"))
        self.assertFalse(categories_distant("", "backpack"))
        self.assertFalse(categories_distant("sandals", ""))

    def test_keep_l1_requires_distant_category(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("material", "polyester"),),
            source="llm",
        )
        self.assertFalse(should_keep_l1(state))
        state.turn_delta = ObservationExtract(
            category="backpack",
            slots=(_slot("category", "backpack"),),
            source="llm",
        )
        self.assertTrue(should_keep_l1(state))
        state.turn_delta = ObservationExtract(
            category="women sandals",
            slots=(_slot("category", "women sandals"),),
            source="llm",
        )
        self.assertFalse(should_keep_l1(state))


class HierarchyWritebackTest(unittest.TestCase):
    def test_l1_clears_all_then_apply_delta(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            category="backpack",
            slots=(_slot("category", "backpack"),),
            source="llm",
        )
        apply_override_decision(state, OverrideDecision(1))
        names = {slot.attribute for slot in state.typed_constraints}
        self.assertEqual(names, {"category"})
        self.assertEqual(state.category, "backpack")
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.excluded_asins, set())
        self.assertEqual(state.shown_asins, set())
        self.assertEqual(state.last_ranked, [])

    def test_l2_color_only_keeps_category_and_material(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("color", "navy"),),
            source="llm",
        )
        apply_override_decision(state, OverrideDecision(2))
        by_attr = {
            slot.attribute: slot.surface for slot in state.typed_constraints
        }
        self.assertEqual(by_attr["category"], "sandals")
        self.assertEqual(by_attr["material"], "suede")
        self.assertEqual(by_attr["color"], "navy")
        self.assertNotIn("pink", {slot.surface for slot in state.typed_constraints})
        self.assertTrue(state.gate_open)
        self.assertEqual(state.last_ranked, [])

    def test_l2_category_only_keeps_attributes(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            category="backpack",
            slots=(_slot("category", "backpack"),),
            source="llm",
        )
        apply_override_decision(state, OverrideDecision(2))
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        materials = [
            slot for slot in state.typed_constraints if slot.attribute == "material"
        ]
        cats = [slot for slot in state.typed_constraints if slot.attribute == "category"]
        self.assertEqual(len(colors), 1)
        self.assertEqual(len(materials), 1)
        self.assertEqual(cats[0].surface, "backpack")
        self.assertEqual(state.category, "backpack")

    def test_l2_material_only(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("material", "leather"),),
            source="llm",
        )
        apply_override_decision(state, OverrideDecision(2))
        materials = [
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "material"
        ]
        self.assertEqual(materials, ["leather"])
        self.assertTrue(
            any(slot.attribute == "color" and slot.surface == "pink" for slot in state.typed_constraints)
        )

    def test_level_zero_accumulates_color(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("color", "navy"),),
            source="llm",
        )
        from agent.intent_router.writeback import apply_delta

        apply_delta(state)
        colors = {
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "color"
        }
        self.assertEqual(colors, {"pink", "navy"})
        self.assertFalse(state.gate_open)
        self.assertEqual(state.last_ranked, ["OLD", "NEXT"])


class HierarchyRouterTest(unittest.TestCase):
    def test_strong_start_over_fallback_recovers_missed_router_decision(self) -> None:
        state = _seeded()
        state.latest_message = (
            "Actually, ignore my earlier preference. What I need is water resistant."
        )
        state.current_intent_messages = ["old request", state.latest_message]
        state.turn_delta = ObservationExtract(
            slots=(_slot("feature", "water resistant"),),
            source="llm",
        )
        with (
            patch(_OVERRIDE, return_value=OverrideDecision(0)),
            patch(_PROBE, return_value={"A"}),
        ):
            route_intention(state, MagicMock())

        self.assertTrue(state.override_seen)
        self.assertEqual(state.intention, "override")
        self.assertEqual(state.current_intent_messages, [state.latest_message])
        self.assertEqual(
            [(slot.attribute, slot.surface) for slot in state.typed_constraints],
            [("feature", "water resistant")],
        )

    def test_catalog_copy_words_do_not_trigger_strong_override(self) -> None:
        state = _seeded()
        state.latest_message = (
            "For that, what matters is: use this instead of a clasp; "
            "a keepsake you will never forget."
        )
        self.assertFalse(strong_override_fallback(state))

    def test_l2_decision_skips_replace_and_route(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("color", "navy"),),
            source="llm",
        )
        events: list[dict] = []
        with (
            patch(_OVERRIDE, return_value=OverrideDecision(2)),
            patch(_ROUTE) as route,
            patch(_PROBE, return_value={"A"}) as probe,
            progress_listener(events.append),
        ):
            exact = route_intention(state, MagicMock())
        route.assert_not_called()
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(exact, {"A"})
        self.assertEqual(state.intention, "override")
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["replace_delta"], "skipped")
        self.assertEqual(by_node["drop_slots"], "completed")
        self.assertEqual(by_node["override_l2"], "completed")

    def test_l1_skips_override_l2(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            category="backpack",
            slots=(_slot("category", "backpack"),),
            source="llm",
        )
        events: list[dict] = []
        with (
            patch(_OVERRIDE, return_value=True),
            patch(_ROUTE),
            patch(_PROBE, return_value={"A"}),
            progress_listener(events.append),
        ):
            route_intention(state, MagicMock())
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["override_l2"], "skipped")
        self.assertEqual(by_node["replace_delta"], "completed")
        self.assertEqual(by_node["drop_slots"], "skipped")

    def test_accumulate_skips_drop_slots(self) -> None:
        state = _seeded()
        state.turn_delta = ObservationExtract(
            slots=(_slot("color", "navy"),),
            source="llm",
        )
        events: list[dict] = []
        with (
            patch(_OVERRIDE, return_value=False),
            patch(_ROUTE, return_value="buying"),
            patch(_PROBE, return_value={"A"}),
            progress_listener(events.append),
        ):
            route_intention(state, MagicMock())
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["drop_slots"], "skipped")
        self.assertEqual(by_node["replace_delta"], "skipped")
        self.assertEqual(state.intention, "buying")
        colors = {
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "color"
        }
        self.assertEqual(colors, {"pink", "navy"})


class HierarchyClassifyTest(unittest.TestCase):
    def test_three_illegal_l2_fail_open(self) -> None:
        state = _seeded()
        state.latest_message = "ok"
        client = MagicMock()
        client.complete.side_effect = [
            {"full": False},
            {"constraints": []},
            {"override": True, "extra": 1},
            None,
        ]
        client.last_prompt_tokens = 0
        client.last_completion_tokens = 0
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(0))
        self.assertGreaterEqual(client.complete.call_count, 4)

    def test_no_committed_skips_both_layers(self) -> None:
        state = SessionState("empty", {})
        client = MagicMock()
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            self.assertEqual(classify_override(state), OverrideDecision(0))
        client.complete.assert_not_called()

    def _client(self, *payloads: dict) -> MagicMock:
        client = MagicMock()
        if len(payloads) == 1:
            client.complete.return_value = payloads[0]
        else:
            client.complete.side_effect = list(payloads)
        client.last_prompt_tokens = 0
        client.last_completion_tokens = 0
        return client

    def test_attribute_only_l1_true_demotes_to_l2_replace(self) -> None:
        state = _seeded()
        state.latest_message = (
            "Actually, ignore my earlier preference. What I need is: polyester."
        )
        state.turn_delta = ObservationExtract(
            slots=(_slot("material", "polyester"),),
            source="llm",
        )
        client = self._client({"full": True}, {"override": True})
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(2))
        self.assertEqual(client.complete.call_count, 2)
        apply_override_decision(state, decision)
        by_attr = {
            slot.attribute: slot.surface for slot in state.typed_constraints
        }
        self.assertEqual(by_attr["category"], "sandals")
        self.assertEqual(by_attr["color"], "pink")
        self.assertEqual(by_attr["material"], "polyester")

    def test_attribute_only_l1_true_demotes_to_l2_accumulate_material(self) -> None:
        state = _seeded()
        state.latest_message = (
            "Actually, ignore my earlier preference. What I need is: polyester."
        )
        state.turn_delta = ObservationExtract(
            slots=(_slot("material", "polyester"),),
            source="llm",
        )
        client = self._client({"full": True}, {"override": False})
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(0))
        self.assertEqual(client.complete.call_count, 2)
        apply_delta(state)
        materials = {
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "material"
        }
        self.assertEqual(materials, {"suede", "polyester"})
        self.assertEqual(state.category, "sandals")

    def test_attribute_only_l1_true_demotes_to_accumulate(self) -> None:
        state = _seeded()
        state.latest_message = "Also black and blue."
        state.turn_delta = ObservationExtract(
            slots=(_slot("color", "black"), _slot("color", "blue")),
            source="llm",
        )
        client = self._client({"full": True}, {"override": False})
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(0))
        self.assertEqual(client.complete.call_count, 2)
        apply_delta(state)
        colors = {
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "color"
        }
        self.assertEqual(colors, {"pink", "black", "blue"})
        materials = {
            slot.surface
            for slot in state.typed_constraints
            if slot.attribute == "material"
        }
        self.assertEqual(materials, {"suede"})
        self.assertEqual(state.category, "sandals")

    def test_distant_category_keeps_l1(self) -> None:
        state = _seeded()
        state.latest_message = "Forget sandals. I want a backpack now."
        state.turn_delta = ObservationExtract(
            category="backpack",
            slots=(_slot("category", "backpack"),),
            source="llm",
        )
        client = self._client({"full": True})
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(1))
        client.complete.assert_called_once()

    def test_close_category_demotes_to_l2(self) -> None:
        state = _seeded()
        state.latest_message = "I want women sandals instead."
        state.turn_delta = ObservationExtract(
            category="women sandals",
            slots=(_slot("category", "women sandals"),),
            source="llm",
        )
        client = self._client({"full": True}, {"override": True})
        with patch(
            "agent.intent_router.llm.get_intent_router_client",
            return_value=client,
        ):
            decision = classify_override(state)
        self.assertEqual(decision, OverrideDecision(2))
        self.assertEqual(client.complete.call_count, 2)


class DropTypedTest(unittest.TestCase):
    def test_drop_empty_is_noop(self) -> None:
        state = _seeded()
        drop_typed(state, set())
        self.assertEqual(len(state.typed_constraints), 3)


if __name__ == "__main__":
    unittest.main()
