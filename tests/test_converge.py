from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from converge.agent import Agent
from converge.domain import card_constraints, coarse_category, intent_card
from converge.planner import (
    NO_ADDITIONAL,
    ScoreAwarePlanner,
    hit_utility,
    normalize_probabilities,
)
from converge.retrieval import (
    CatalogRetriever,
    _coerce_constraints,
    build_response_signature,
)
from converge.state import SessionState
from evaluator.local_evaluator import (
    catalog_index,
    evaluate,
    intent_card as official_intent_card,
)


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
        self.assertEqual(state.scenario_hint, "buying")
        self.assertTrue(state.gate_open)
        self.assertIn("leather", state.active_constraints)
        state.record_action(["A"], "other")
        state.begin_turn("For that, what matters is: Rubber sole.", 2)
        self.assertIn("A", state.excluded_asins)
        self.assertIn("Rubber sole", state.active_constraints)

    def test_closed_override_gate_does_not_turn_slate_into_negative_feedback(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        self.assertFalse(state.gate_open)
        state.record_action(["A"], "other")
        state.begin_turn("For that, what matters is: leather; Rubber sole.", 2)
        self.assertNotIn("A", state.excluded_asins)
        state.record_action(["A"], "other")
        state.begin_turn(
            "Actually, ignore my earlier preference. What I need is: leather.", 3
        )
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.intent_version, 1)
        self.assertEqual(state.legacy_hints, [])

    def test_boundary_and_no_additional_are_not_constraints(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes, but I'm still exploring.", 1)
        state.record_action(["A"], "other")
        state.begin_turn(
            "I don't have a preference for other; please use your judgment.", 2
        )
        self.assertTrue(state.boundary_seen)
        self.assertEqual(state.active_constraints, [])
        self.assertNotIn("other", state.no_preference)
        state.record_action(["B"], "other")
        state.begin_turn("I don't have an additional preference for other.", 3)
        self.assertIn("other", state.no_preference)
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
        self.assertEqual(
            state.active_constraints,
            ["Water resistant; suitable for winter", "Rubber sole"],
        )

    def test_structured_constraint_words_do_not_trigger_override(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes, but I'm still exploring.", 1)
        state.record_action(["A"], "other")
        state.begin_turn(
            "For that, what matters is: Use this instead of a belt; "
            "a reminder not to forget hydration.",
            2,
        )
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
        self.assertFalse(state.gate_open)
        state.begin_turn(
            "I've changed my mind; disregard the earlier preference. "
            "Instead, I need waterproof leather.",
            3,
        )
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertEqual(state.legacy_hints, [])
        self.assertIn("waterproof leather", " ".join(state.active_constraints).casefold())

    def test_pending_override_has_turn_four_fail_safe(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        state.begin_turn("Completely different requirements now.", 4)
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)


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

    def test_static_question_policy_respects_configured_priority(self) -> None:
        state = SessionState("s", {})
        state.turn = 1
        ranked = normalize_probabilities([(f"P{i}", 1.0) for i in range(3)])

        def answer(parent_asin: str, attribute: str) -> tuple[str, ...]:
            if attribute == "color":
                return ("blue",) if parent_asin != "P2" else ("red",)
            if attribute == "feature":
                return (parent_asin,)
            return NO_ADDITIONAL

        planner = ScoreAwarePlanner(
            question_policy="static",
            question_priority=(
                "color",
                "feature",
                "material",
                "style",
                "size",
                "use_case",
                "budget",
                "other",
            ),
        )
        plan = planner.plan(state, ranked, 10, answer)
        self.assertEqual(plan.ask_attribute, "color")

    def test_question_priority_must_contain_all_supported_attributes(self) -> None:
        with self.assertRaises(ValueError):
            ScoreAwarePlanner(question_priority=("other", "feature"))


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
        agent = Agent(self.catalog_path)
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
        with patch.dict(os.environ, {"CONVERGE_INDEX_PATH": ":memory:"}):
            result = evaluate(
                Agent(catalog),
                samples,
                catalog_ids,
                categories,
                products,
            )
        self.assertEqual(result["hit_rate_at_10"], 1.0)


if __name__ == "__main__":
    unittest.main()
