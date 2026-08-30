"""Demo shelf padding must not re-run retrieve."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.understand.state import SessionState
from demo.hydrate import expand_recommendations_for_ui


class ExpandRecommendationsTest(unittest.TestCase):
    def test_pads_from_last_ranked_only(self) -> None:
        state = SessionState("hy", {})
        state.last_ranked = ["A", "B", "C", "D"]
        rows = expand_recommendations_for_ui(
            MagicMock(),
            state,
            [{"parent_asin": "A"}],
            limit=3,
        )
        self.assertEqual(
            [row["parent_asin"] for row in rows],
            ["A", "B", "C"],
        )

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
                limit=8,
            )
        retrieve.assert_not_called()
        self.assertEqual([row["parent_asin"] for row in rows], ["ONLY"])


if __name__ == "__main__":
    unittest.main()
