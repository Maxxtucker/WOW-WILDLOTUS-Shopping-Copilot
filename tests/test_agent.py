from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Agent
from agent.decide.clarification import (
    NO_ADDITIONAL,
    ScoreAwarePlanner,
    apply_sequential_gate,
    hit_utility,
)
from agent.decide.clarification.types import Plan
from agent.decide.ranking import normalize_probabilities
from agent.domain import card_constraints, coarse_category, intent_card
from agent.retrieve.catalog import (
    CatalogRetriever,
    _coerce_constraints,
    build_response_signature,
)
from agent.intent_router import apply_delta, replace_with_delta
from agent.understand.mode import MODE_REGEX, configure_understand, reset_understand_mode
from agent.understand.state import SessionState
from agent.understand.state.failsafe import apply_override_failsafe
from evaluator.local_evaluator import (
    catalog_index,
    evaluate,
    intent_card as official_intent_card,
)


_ROUTER_PATCHES: list = []


def _fake_classify_override(state: SessionState) -> bool:
    text = (state.latest_message or "").casefold()
    return "ignore my earlier preference" in text or (
        "changed my mind" in text and "disregard" in text
    )


def _fake_classify_route(
    state: SessionState,
    *,
    pool_before: int | None = None,
    pool_after: int | None = None,
    ratio: float | None = None,
) -> str:
    if state.active_constraints or state.typed_constraints:
        return "buying"
    return "browsing"


def setUpModule() -> None:
    configure_understand(MODE_REGEX)
    for target, kwargs in (
        (
            "agent.intent_router.router.classify_override",
            {"side_effect": _fake_classify_override},
        ),
        (
            "agent.intent_router.router.classify_route",
            {"side_effect": _fake_classify_route},
        ),
    ):
        patcher = patch(target, **kwargs)
        patcher.start()
        _ROUTER_PATCHES.append(patcher)


def tearDownModule() -> None:
    for patcher in reversed(_ROUTER_PATCHES):
        patcher.stop()
    _ROUTER_PATCHES.clear()
    reset_understand_mode()


def _commit(state: SessionState, *, override: bool | None = None) -> None:
    if override is None:
        override = _fake_classify_override(state)
    if override:
        replace_with_delta(state)
    else:
        apply_delta(state)
    apply_override_failsafe(state, state.turn)


def product(
    parent_asin: str,
    *,
    feature: str,
    sole: str,
    rating_number: int,
) -> dict:
    return {
        "parent_asin": parent_asin,
        "title": f"Example {feature} shoe",
        "features": [feature, "100% Leather", sole],
        "description": ["Comfortable walking shoe"],
        "price": 49.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes"],
        "details": {"Department": "mens"},
        "average_rating": 4.5,
        "rating_number": rating_number,
        "store": "Example",
    }


class StateTest(unittest.TestCase):
    def test_buying_initial_state_and_open_gate_miss(self) -> None:
        state = SessionState("s", {})
        state.begin_turn(
            "I'm looking for Men Shoes. A key requirement is: leather.", 1
        )
        _commit(state)
        self.assertEqual(state.category, "Men Shoes")
        self.assertTrue(state.gate_open)
        self.assertIn("leather", state.active_constraints)
        state.record_action(["A"], "other")
        state.begin_turn("For that, what matters is: Rubber sole.", 2)
        _commit(state)
        self.assertIn("A", state.excluded_asins)
        self.assertIn("Rubber sole", state.active_constraints)

    def test_closed_override_gate_does_not_turn_slate_into_negative_feedback(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        _commit(state)
        self.assertFalse(state.gate_open)
        state.record_action(["A"], "other")
        state.begin_turn("For that, what matters is: leather; Rubber sole.", 2)
        _commit(state)
        self.assertNotIn("A", state.excluded_asins)
        state.record_action(["A"], "other")
        state.begin_turn(
            "Actually, ignore my earlier preference. What I need is: leather.", 3
        )
        _commit(state)
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.intent_version, 1)
        self.assertEqual(state.legacy_hints, [])

    def test_empty_replies_do_not_write_constraints(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes, but I'm still exploring.", 1)
        _commit(state)
        self.assertEqual(state.category, "Men Shoes")
        self.assertEqual(state.active_constraints, [])
        state.record_action(["A"], "other")
        state.begin_turn(
            "I don't have a preference for other; please use your judgment.", 2
        )
        _commit(state)
        self.assertEqual(state.active_constraints, [])
        state.record_action(["B"], "other")
        state.begin_turn("I don't have an additional preference for other.", 3)
        _commit(state)
        self.assertEqual(state.active_constraints, [])

    def test_candidate_reply_map_preserves_semicolon_inside_atomic_value(self) -> None:
        state = SessionState("s", {})
        state.turn = 2
        state.set_reply_options(
            [("Water resistant; suitable for winter", "Rubber sole")]
        )
        state.observe(
            "For that, what matters is: Water resistant; suitable for winter; "
            "Rubber sole."
        )
        _commit(state)
        self.assertEqual(
            state.active_constraints,
            ["Water resistant; suitable for winter", "Rubber sole"],
        )

    def test_structured_constraint_words_do_not_trigger_override(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes, but I'm still exploring.", 1)
        _commit(state)
        state.record_action(["A"], "other")
        state.begin_turn(
            "For that, what matters is: Use this instead of a belt; "
            "a reminder not to forget hydration.",
            2,
        )
        _commit(state)
        self.assertFalse(state.override_seen)
        self.assertEqual(state.intent_version, 0)
        self.assertIn("A", state.excluded_asins)
        self.assertEqual(
            state.active_constraints,
            ["Use this instead of a belt", "a reminder not to forget hydration"],
        )

    def test_paraphrased_override_opens_gate_and_clears_legacy_hint(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        _commit(state)
        self.assertFalse(state.gate_open)
        state.begin_turn(
            "I've changed my mind; disregard the earlier preference. "
            "Instead, I need waterproof leather.",
            3,
        )
        _commit(state)
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.legacy_hints, [])
        self.assertIn("waterproof leather", " ".join(state.active_constraints).casefold())

    def test_pending_override_has_turn_four_fail_safe(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        _commit(state)
        state.begin_turn("Completely different requirements now.", 4)
        _commit(state)
        self.assertTrue(state.gate_open)
        self.assertFalse(state.override_seen)
        self.assertNotEqual(state.intention, "override")

    def test_preference_tags_snapshot_from_profile(self) -> None:
        state = SessionState(
            "s",
            {
                "purchase_frequency": "3-4 prior purchases",
                "average_prior_rating": 5.0,
                "rating_style": "usually positive",
                "preference_tags": ["fit", "comfort", "durability"],
                "summary": "Prior purchases emphasize fit, comfort, durability.",
            },
        )
        self.assertEqual(state.preference_tags, ("fit", "comfort", "durability"))
        self.assertEqual(SessionState("s", {}).preference_tags, ())
        self.assertEqual(SessionState("s", {"summary": "x"}).preference_tags, ())
        self.assertEqual(
            SessionState("s", {"preference_tags": []}).preference_tags, ()
        )
        self.assertEqual(
            SessionState(
                "s", {"preference_tags": ["  Fit ", "comfort", "fit", "", 1]}
            ).preference_tags,
            ("Fit", "comfort"),
        )

    def test_preference_tags_survive_observe_and_override(self) -> None:
        state = SessionState("s", {"preference_tags": ["fit", "comfort"]})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        _commit(state)
        state.begin_turn(
            "Actually, ignore my earlier preference. What I need is: leather.", 3
        )
        _commit(state)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.preference_tags, ("fit", "comfort"))
        self.assertNotIn("fit", state.active_constraints)
        self.assertEqual(state.ranking_constraints, ("leather",))


class PlannerTest(unittest.TestCase):
    def test_reward_exposes_low_rank_early_hit_tradeoff(self) -> None:
        self.assertAlmostEqual(hit_utility(1, 10), 0.73)
        self.assertAlmostEqual(hit_utility(2, 1), 0.98)
        self.assertGreater(hit_utility(2, 1), hit_utility(1, 10))

    def test_informative_answer_avoids_full_early_slate(self) -> None:
        state = SessionState("s", {})
        state.turn = 1
        ranked = normalize_probabilities([(f"P{i}", 1.0) for i in range(10)])

        def answer(parent_asin: str, attribute: str) -> tuple[str, ...]:
            return (parent_asin,) if attribute == "other" else NO_ADDITIONAL

        plan = ScoreAwarePlanner().plan(state, ranked, 10, answer)
        self.assertEqual(plan.ask_attribute, "other")
        self.assertLess(len(plan.recommendations), 10)

    def test_turn_ten_is_full_slate_with_no_question(self) -> None:
        state = SessionState("s", {})
        state.turn = 10
        ranked = normalize_probabilities([(f"P{i}", 10 - i) for i in range(12)])
        plan = ScoreAwarePlanner().plan(
            state, ranked, 10, lambda _asin, _attr: NO_ADDITIONAL
        )
        self.assertEqual(len(plan.recommendations), 10)
        self.assertIsNone(plan.ask_attribute)

    def test_empty_disclosure_is_full_slate_with_no_question(self) -> None:
        state = SessionState("s", {})
        state.turn = 2
        state.disclosure_empty = True
        ranked = normalize_probabilities([(f"P{i}", 12 - i) for i in range(12)])
        plan = ScoreAwarePlanner().plan(
            state, ranked, 10, lambda _asin, _attr: ("split",)
        )
        self.assertEqual(len(plan.recommendations), 10)
        self.assertEqual(list(plan.recommendations), [f"P{i}" for i in range(10)])
        self.assertIsNone(plan.ask_attribute)
        self.assertEqual(plan.reason, "empty disclosure")

    def test_sequential_gate_keeps_full_slate_on_empty_disclosure(self) -> None:
        state = SessionState("s", {})
        state.turn = 2
        state.gate_open = True
        state.disclosure_empty = True
        ranked = normalize_probabilities([(f"P{i}", 10 - i) for i in range(10)])
        plan = Plan(tuple(item.parent_asin for item in ranked), "color", 1.0, "joint")
        slate = apply_sequential_gate(state, plan, ranked)
        self.assertEqual(slate, [item.parent_asin for item in ranked])


class RetrievalAndAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temporary.name) / "catalog.jsonl"
        self.rows = [
            product("A", feature="leather", sole="Leather sole", rating_number=100),
            product("B", feature="leather", sole="Rubber sole", rating_number=20),
            product("C", feature="cotton", sole="Synthetic sole", rating_number=5),
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_response_signature_matches_official_generator(self) -> None:
        for row in self.rows:
            signature = build_response_signature(row)
            official = official_intent_card(row)
            self.assertEqual(signature.target_category, official["target_category"])
            self.assertEqual(
                list(signature.hard_constraints), official["hard_constraints"]
            )
            self.assertEqual(
                list(signature.soft_preferences), official["soft_preferences"]
            )

    def test_response_only_lookup_preserves_full_constraint(self) -> None:
        with CatalogRetriever(self.catalog_path) as retriever:
            matches = set(
                retriever.signature_candidates(
                    "material", "Leather sole", response_only=True
                )
            )
            self.assertEqual(matches, {"A"})

    def test_two_constraint_tuple_is_not_misread_as_attribute_pair(self) -> None:
        parsed = _coerce_constraints(("leather", "Rubber sole"))
        self.assertEqual(
            parsed,
            (("material", "leather"), ("feature", "Rubber sole")),
        )

    def test_agent_contract_and_session_isolation(self) -> None:
        agent = Agent(self.catalog_path, understand_mode="regex")
        agent.reset("one", {"preference_tags": []})
        agent.reset("two", {"preference_tags": []})
        category = coarse_category(self.rows[0]["categories"])
        first = card_constraints(intent_card(self.rows[0]))[0]
        response = agent.respond(
            "one",
            f"I'm looking for {category}. A key requirement is: {first}.",
            1,
            10,
        )
        self.assertIsInstance(response["message"], str)
        self.assertIn(response["ask_attribute"], {"other", "feature", "material"})
        self.assertLessEqual(len(response["recommendations"]), 10)
        self.assertEqual(response["usage"], {"prompt_tokens": 0, "completion_tokens": 0})
        self.assertEqual(agent.sessions["two"].turn, 0)

    def test_large_indistinguishable_pool_keeps_enough_slate_coverage(self) -> None:
        rows = [
            product(
                f"P{index:02d}",
                feature="leather",
                sole="Rubber sole",
                rating_number=30 - index,
            )
            for index in range(30)
        ]
        catalog = Path(self.temporary.name) / "collision-catalog.jsonl"
        catalog.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        catalog_ids, categories, products = catalog_index(catalog)
        samples = [
            {
                "sample_id": "collision",
                "scenario_type": "browsing",
                "user_profile": {"preference_tags": []},
                "ground_truth": {"parent_asin": "P29"},
            }
        ]
        with patch.dict(os.environ, {"AGENT_INDEX_PATH": ":memory:"}):
            result = evaluate(
                Agent(catalog, understand_mode="regex"),
                samples,
                catalog_ids,
                categories,
                products,
            )
        self.assertEqual(result["hit_rate_at_10"], 1.0)


if __name__ == "__main__":
    unittest.main()
