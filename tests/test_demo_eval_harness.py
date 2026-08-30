"""Demo public_set selection helpers and Scenario Buyer harness."""

from __future__ import annotations

import random
import unittest

from demo.eval_harness import (
    EVALUATORS,
    buyer_llm_status,
    group_metrics,
    parse_buyer_mode,
    parse_llm_mode,
    run_evaluate_with_buyer,
    sample_summaries,
    select_samples,
)
from evaluator.local_evaluator import coarse_category, initial_message, materialize_hidden_fields


def _rows(count: int = 8) -> list[dict]:
    scenarios = ("buying", "browsing", "intent_override", "boundary")
    return [
        {
            "sample_id": f"public_{index:04d}",
            "scenario_type": scenarios[(index - 1) % 4],
            "difficulty_bucket": "easy",
            "category_bucket": "clothing",
            "ground_truth": {"parent_asin": f"X{index}"},
        }
        for index in range(1, count + 1)
    ]


class SelectSamplesTest(unittest.TestCase):
    def test_one_by_sample_id(self) -> None:
        picked = select_samples("one", samples=_rows(), sample_id="public_0003")
        self.assertEqual([row["sample_id"] for row in picked], ["public_0003"])

    def test_one_by_index(self) -> None:
        picked = select_samples("one", samples=_rows(), sample_id="2")
        self.assertEqual(picked[0]["sample_id"], "public_0002")

    def test_range_by_ids(self) -> None:
        picked = select_samples(
            "range",
            samples=_rows(),
            start="public_0002",
            end="public_0004",
        )
        self.assertEqual(
            [row["sample_id"] for row in picked],
            ["public_0002", "public_0003", "public_0004"],
        )

    def test_range_by_line_numbers(self) -> None:
        picked = select_samples("range", samples=_rows(), start=1, end=2)
        self.assertEqual(
            [row["sample_id"] for row in picked],
            ["public_0001", "public_0002"],
        )

    def test_all(self) -> None:
        rows = _rows(5)
        picked = select_samples("all", samples=rows)
        self.assertEqual(len(picked), 5)
        self.assertEqual(picked[0]["sample_id"], "public_0001")

    def test_random_is_reproducible_with_rng(self) -> None:
        rows = _rows(8)
        first = select_samples("random", samples=rows, n=3, rng=random.Random(7))
        second = select_samples("random", samples=rows, n=3, rng=random.Random(7))
        self.assertEqual(
            [row["sample_id"] for row in first],
            [row["sample_id"] for row in second],
        )
        self.assertEqual(len(first), 3)

    def test_random_n_as_string(self) -> None:
        picked = select_samples("random", samples=_rows(6), n="2", rng=random.Random(1))
        self.assertEqual(len(picked), 2)

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_samples("nope", samples=_rows())

    def test_random_too_large_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_samples("random", samples=_rows(3), n=9)

    def test_summaries_omit_ground_truth(self) -> None:
        rows = sample_summaries(_rows(2))
        self.assertEqual(rows[0]["sample_id"], "public_0001")
        self.assertNotIn("ground_truth", rows[0])


class GroupMetricsTest(unittest.TestCase):
    def test_empty_group(self) -> None:
        summary = group_metrics([])
        self.assertEqual(summary["sample_count"], 0)
        self.assertEqual(summary["recommended_technical_score"], 0.0)

    def test_matches_official_weights(self) -> None:
        sessions = [
            {
                "scenario_type": "buying",
                "hit": True,
                "reciprocal_rank": 1.0,
                "first_hit_turn": 1,
            },
            {
                "scenario_type": "browsing",
                "hit": False,
                "reciprocal_rank": 0.0,
                "first_hit_turn": None,
            },
        ]
        summary = group_metrics(sessions)
        self.assertEqual(summary["sample_count"], 2)
        self.assertAlmostEqual(summary["hit_rate_at_10"], 0.5)
        self.assertAlmostEqual(summary["mrr"], 0.5)
        self.assertAlmostEqual(summary["mttc"], 6.0)
        self.assertAlmostEqual(summary["efficiency"], 0.5)
        self.assertAlmostEqual(summary["recommended_technical_score"], 0.5)


class RecordingAgent:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.session_id = session_id

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        self.messages.append(user_message)
        return {
            "message": "ok",
            "ask_attribute": None,
            "recommendations": [{"parent_asin": "A1"}],
        }


class ScenarioBuyerHarnessTest(unittest.TestCase):
    def test_evaluators_include_scenario(self) -> None:
        ids = [item["id"] for item in EVALUATORS]
        self.assertIn("local", ids)
        self.assertIn("scenario", ids)
        scenario = next(item for item in EVALUATORS if item["id"] == "scenario")
        self.assertTrue(scenario["enabled"])
        self.assertEqual(scenario["path"], "evaluator/scenario_evaluator.py")

    def test_parse_buyer_mode_defaults_and_rejects(self) -> None:
        self.assertEqual(parse_buyer_mode(None), 1)
        self.assertEqual(parse_buyer_mode(""), 1)
        self.assertEqual(parse_buyer_mode("3"), 3)
        with self.assertRaises(ValueError):
            parse_buyer_mode(5)

    def test_mode1_first_message_matches_official_template(self) -> None:
        sample = {
            "sample_id": "public_test",
            "scenario_type": "buying",
            "user_profile": {},
            "ground_truth": {"parent_asin": "A1"},
            "intent_card": {
                "hard_constraints": ["leather"],
                "soft_preferences": [],
            },
            "behavior": {},
        }
        products = {"A1": {"title": "Boot", "parent_asin": "A1"}}
        categories = {"A1": ["Men Shoes"]}
        catalog_ids = {"A1"}
        card, behavior = materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        expected = initial_message(
            effective,
            coarse_category(categories["A1"]),
            set(),
        )
        agent = RecordingAgent()
        run_evaluate_with_buyer(
            agent,
            [sample],
            mode=1,
            catalog_ids=catalog_ids,
            categories=categories,
            products=products,
        )
        self.assertEqual(agent.messages[0], expected)
        self.assertEqual(
            expected,
            "I'm looking for Men Shoes. A key requirement is: leather.",
        )
        self.assertEqual(len(agent.messages), 1)

    def test_parse_llm_mode_and_status(self) -> None:
        self.assertEqual(parse_llm_mode("remote"), "remote")
        self.assertEqual(parse_llm_mode("local"), "local")
        self.assertEqual(buyer_llm_status(1, "remote"), "")
        self.assertEqual(buyer_llm_status(2, "local"), "Buyer LLM: local qwen3.5:4b")


if __name__ == "__main__":
    unittest.main()
