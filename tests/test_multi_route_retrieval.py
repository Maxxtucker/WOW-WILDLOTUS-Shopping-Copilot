from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agent.retrieve.candidates.multi_route import fuse_routes
from agent.retrieve.candidates.retrieve import retrieve_candidates
from agent.retrieve.catalog.types import SearchHit
from agent.decide.ranking.belief import belief_from_hits
from agent.understand.state import SessionState


def hit(parent_asin: str, score: float = 1.0) -> SearchHit:
    return SearchHit(parent_asin, score, score, 0.0, 0.0, 0.0)


class MultiRouteFusionTest(unittest.TestCase):
    def test_fused_scores_do_not_become_an_almost_uniform_belief(self) -> None:
        hits = [
            SearchHit(
                f"P{index}",
                0.040 - index * 0.003,
                0.0,
                0.0,
                0.0,
                1.0,
                reasons=("route:strict+raw",),
            )
            for index in range(10)
        ]

        weights = belief_from_hits(hits)

        self.assertGreater(weights[0][1], weights[-1][1] * 20)

    def test_candidate_supported_by_two_safety_routes_moves_ahead(self) -> None:
        strict = [hit(f"S{index:03d}") for index in range(30)]
        relaxed = [hit("TARGET")]
        raw = [hit("TARGET")]

        fused = fuse_routes(
            (("strict", 1.4, strict), ("relaxed", 0.9, relaxed), ("raw", 1.1, raw)),
            limit=50,
        )

        self.assertEqual(fused[0].parent_asin, "TARGET")
        self.assertIn("route:relaxed+raw", fused[0].reasons)

    def test_live_raw_text_adds_relaxed_and_independent_routes(self) -> None:
        strict_asins = {f"S{index:03d}" for index in range(150)}
        strict_hits = [hit(asin, 2.0) for asin in sorted(strict_asins)]
        retriever = MagicMock()
        retriever.lexical_scores.return_value = {}
        retriever.score_candidates.return_value = strict_hits
        retriever.search.side_effect = [[hit("TARGET")], [hit("TARGET")]]
        state = SessionState("multi", {})
        state.intention = "buying"
        state.current_intent_messages = ["warm leather winter boots"]

        hits = retrieve_candidates(retriever, state, strict_asins)

        self.assertEqual(retriever.search.call_count, 2)
        self.assertEqual(hits[0].parent_asin, "TARGET")
        self.assertIn("route:relaxed+raw", hits[0].reasons)

    def test_early_safety_routes_do_not_treat_slate_as_certain_miss(self) -> None:
        strict_asins = {f"S{index:03d}" for index in range(150)}
        retriever = MagicMock()
        retriever.lexical_scores.return_value = {}
        retriever.score_candidates.return_value = [
            hit(asin, 2.0) for asin in sorted(strict_asins)
        ]
        retriever.search.side_effect = [[hit("TARGET")], [hit("TARGET")]]
        state = SessionState("latent-gate", {})
        state.turn = 3
        state.intention = "buying"
        state.current_intent_messages = ["actually I need a water resistant watch"]
        state.excluded_asins = {"TARGET"}

        hits = retrieve_candidates(retriever, state, strict_asins)

        self.assertEqual(hits[0].parent_asin, "TARGET")
        for call in retriever.search.call_args_list:
            self.assertEqual(tuple(call.kwargs["exclude_asins"]), ())


if __name__ == "__main__":
    unittest.main()
