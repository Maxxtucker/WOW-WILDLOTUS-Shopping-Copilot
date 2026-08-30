"""Demo shelf padding must not re-run retrieve."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.understand.state import SessionState
from demo.hydrate import expand_recommendations_for_ui, hydrate_many


class ExpandRecommendationsTest(unittest.TestCase):
    def test_uses_official_order_and_marks_every_card_on_slate(self) -> None:
        state = SessionState("hy", {})
        state.last_ranked = ["A", "B", "C", "D"]
        rows = expand_recommendations_for_ui(
            MagicMock(),
            state,
            [{"parent_asin": "C"}, {"parent_asin": "B"}],
            limit=3,
        )
        self.assertEqual(
            [row["parent_asin"] for row in rows],
            ["C", "B"],
        )
        self.assertTrue(all(row["on_slate"] for row in rows))

    def test_falls_back_to_official_when_last_ranked_empty(self) -> None:
        state = SessionState("hy", {})
        state.last_ranked = []
        rows = expand_recommendations_for_ui(
            MagicMock(),
            state,
            [{"parent_asin": "X"}, {"parent_asin": "Y"}],
            limit=10,
        )
        self.assertEqual([row["parent_asin"] for row in rows], ["X", "Y"])
        self.assertTrue(all(row["on_slate"] for row in rows))

    def test_does_not_call_retrieve_candidates(self) -> None:
        state = SessionState("hy", {})
        state.last_ranked = ["ONLY"]
        with patch(
            "agent.retrieve.candidates.retrieve.retrieve_candidates"
        ) as retrieve:
            rows = expand_recommendations_for_ui(
                MagicMock(),
                state,
                [{"parent_asin": "ONLY"}],
                limit=10,
            )
        retrieve.assert_not_called()
        self.assertEqual([row["parent_asin"] for row in rows], ["ONLY"])
        self.assertTrue(rows[0]["on_slate"])

    def test_hydrate_copies_on_slate(self) -> None:
        retriever = MagicMock()
        retriever.get_product.return_value = {"title": "Boot"}
        cards = hydrate_many(
            retriever,
            [{"parent_asin": "A", "on_slate": True}, {"parent_asin": "B"}],
            limit=10,
        )
        self.assertTrue(cards[0]["on_slate"])
        self.assertFalse(cards[1]["on_slate"])


if __name__ == "__main__":
    unittest.main()
