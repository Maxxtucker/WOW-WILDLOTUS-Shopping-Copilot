"""Demo stage-reveal terminal dump. No Ollama and no public_set labels."""

from __future__ import annotations

import io
import unittest

from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState
from demo.turn_monitor import log_stage_reveal, maybe_log_progress_event, session_snapshot


def _state() -> SessionState:
    state = SessionState("monitor", {})
    state.category = "sandals"
    state.intention = None
    state.gate_open = True
    state.last_ask = None
    state.asked = []
    state.candidate_count = None
    state.last_slate = []
    state.typed_constraints = [
        ConstraintSlot(
            attribute="category",
            surface="sandals",
            canonical=("sandal",),
            is_hard=True,
        )
    ]
    return state


class SessionSnapshotTest(unittest.TestCase):
    def test_omits_profile_and_keeps_slots(self) -> None:
        snap = session_snapshot(_state())
        self.assertEqual(snap["category"], "sandals")
        self.assertEqual(snap["typed_constraints"][0]["canonical"], ["sandal"])
        self.assertNotIn("user_profile", snap)
        self.assertNotIn("message_history", snap)


class StageRevealTest(unittest.TestCase):
    def test_understand_prints_delta_and_session(self) -> None:
        buf = io.StringIO()
        log_stage_reveal(
            turn=1,
            stage="understand",
            detail={
                "source": "llm",
                "category": "sandals",
                "empty": False,
                "slots": [
                    {
                        "attribute": "category",
                        "surface": "sandals",
                        "canonical": ["sandal"],
                        "is_hard": True,
                    }
                ],
            },
            state=_state(),
            stream=buf,
        )
        text = buf.getvalue()
        self.assertIn("turn 1 / understand", text)
        self.assertIn("turn_delta", text)
        self.assertIn("sandal", text)
        self.assertIn("--- session ---", text)
        self.assertIn('"category": "sandals"', text)

    def test_router_prints_intention_and_hard_groups(self) -> None:
        buf = io.StringIO()
        state = _state()
        state.intention = "browsing"
        log_stage_reveal(
            turn=1,
            stage="router",
            detail={
                "intention": "browsing",
                "override": False,
                "exact": 2,
                "hard_groups": [{"attribute": "category", "values": ["sandal"]}],
                "exact_sample": ["A", "B"],
            },
            state=state,
            stream=buf,
        )
        text = buf.getvalue()
        self.assertIn("turn 1 / router", text)
        self.assertIn("browsing", text)
        self.assertIn("hard_groups", text)
        self.assertIn("sandal", text)

    def test_retrieve_prints_ranked_top(self) -> None:
        buf = io.StringIO()
        ranked = [
            {"parent_asin": f"B{index:02d}", "probability": 1.0 - index / 20}
            for index in range(1, 11)
        ]
        log_stage_reveal(
            turn=2,
            stage="retrieve",
            detail={
                "hit_count": 40,
                "scored_exact": True,
                "top": [
                    {
                        "parent_asin": "B01",
                        "score": 3.2,
                        "matched_constraints": ["category"],
                    }
                ],
                "ranked_top": ranked,
            },
            stream=buf,
        )
        text = buf.getvalue()
        self.assertIn("turn 2 / retrieve", text)
        self.assertIn("ranked top 10", text)
        self.assertIn("B01", text)
        self.assertIn("B10", text)
        self.assertIn("probability=", text)

    def test_decide_prints_recommendations_and_message(self) -> None:
        buf = io.StringIO()
        log_stage_reveal(
            turn=2,
            stage="decide",
            detail={
                "ask_attribute": "color",
                "reason": "split the pool",
                "gated": False,
                "planned_slate": ["B01"],
                "slate": ["B01"],
                "response": {
                    "message": "Here is a sandal. What color?",
                    "ask_attribute": "color",
                    "recommendations": ["B01"],
                },
            },
            stream=buf,
        )
        text = buf.getvalue()
        self.assertIn("turn 2 / decide", text)
        self.assertIn("Here is a sandal. What color?", text)
        self.assertIn("B01", text)
        self.assertIn("--- respond ---", text)

    def test_non_stage_event_is_silent(self) -> None:
        buf = io.StringIO()
        maybe_log_progress_event(
            {"stage": "understand", "node": "casefold", "status": "completed"},
            turn=1,
            stream=buf,
        )
        self.assertEqual(buf.getvalue(), "")

    def test_stage_completed_event_prints(self) -> None:
        buf = io.StringIO()
        maybe_log_progress_event(
            {
                "stage": "router",
                "node": "stage",
                "status": "completed",
                "detail": {"intention": "buying", "hard_groups": []},
            },
            turn=4,
            stream=buf,
        )
        self.assertIn("turn 4 / router", buf.getvalue())
        self.assertIn("buying", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
