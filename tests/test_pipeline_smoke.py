"""Offline smoke: one TurnPipeline turn from understand through the official reply.

Does not read public_set.jsonl. Router LLMs are patched. Understand is regex
unless a test injects a scripted NLU client.
"""

from __future__ import annotations

import io
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.domain import ALLOWED_ATTRIBUTES
from agent.pipeline import TurnPipeline
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.llm_nlu import set_nlu_client
from agent.understand.observation.schema import parse_observation_payload
from agent.understand.state import SessionState

from tests.test_understand_router_smoke import (
    BLUE_SHOE,
    BOOK,
    PINK_SHOE,
    TURN3,
    build_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
BUYING = "I'm looking for women's sandals. A key requirement is: leather."
BROWSING = "I'm looking for women's sandals, but I'm still exploring."


def _load_console():
    spec = importlib.util.spec_from_file_location(
        "nlu_console",
        ROOT / "scripts" / "nlu_console.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_official_response(payload: dict) -> None:
    unittest.TestCase().assertIsInstance(payload.get("message"), str)
    ask = payload.get("ask_attribute")
    unittest.TestCase().assertTrue(ask is None or ask in ALLOWED_ATTRIBUTES)
    recs = payload.get("recommendations")
    unittest.TestCase().assertIsInstance(recs, list)
    for item in recs:
        unittest.TestCase().assertIsInstance(item, dict)
        unittest.TestCase().assertIn("parent_asin", item)
    usage = payload.get("usage")
    unittest.TestCase().assertIsInstance(usage, dict)


class _ScriptedExtractClient:
    model = "fake"
    host = "http://127.0.0.1"

    def __init__(self, payloads: list[tuple[dict, str]]) -> None:
        self._payloads = list(payloads)

    def inspect(self, message, *, category, constraints, last_ask):
        del category, constraints, last_ask
        payload, grounding = self._payloads.pop(0)
        return payload, parse_observation_payload(payload, grounding or message)

    def extract(self, message, *, category, constraints, last_ask):
        _payload, parsed = self.inspect(
            message, category=category, constraints=constraints, last_ask=last_ask
        )
        return parsed


class PipelineSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        _catalog, _slots, self.retriever = build_fixture(Path(self.temporary.name))
        self.addCleanup(self.retriever.close)
        configure_understand(MODE_REGEX)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        self.addCleanup(lambda: set_nlu_client(None))
        self.pipeline = TurnPipeline(self.retriever)
        self.override_patch = patch(
            "agent.intent_router.router.classify_override", return_value=False
        )
        self.route_patch = patch(
            "agent.intent_router.router.classify_route", return_value="buying"
        )
        self.override_patch.start()
        self.route_patch.start()
        self.addCleanup(self.override_patch.stop)
        self.addCleanup(self.route_patch.stop)

    def test_buying_first_turn_returns_message_and_recs(self) -> None:
        state = SessionState("smoke-buy", {})
        response, trace = self.pipeline.run_traced(state, BUYING, 1, 10)
        _assert_official_response(response)
        self.assertTrue(response["recommendations"])
        self.assertEqual(state.turn, 1)
        self.assertIn(state.intention, {"buying", "browsing", "override"})
        self.assertGreater(trace.retrieve["hit_count"], 0)
        rec_ids = {item["parent_asin"] for item in response["recommendations"]}
        self.assertTrue(rec_ids <= {BLUE_SHOE, PINK_SHOE, BOOK})

    def test_browsing_first_turn_still_responds(self) -> None:
        self.route_patch.stop()
        self.route_patch = patch(
            "agent.intent_router.router.classify_route", return_value="browsing"
        )
        self.route_patch.start()
        self.addCleanup(self.route_patch.stop)
        state = SessionState("smoke-browse", {})
        response, _trace = self.pipeline.run_traced(state, BROWSING, 1, 10)
        _assert_official_response(response)
        self.assertEqual(state.intention, "browsing")
        self.assertIsInstance(response["message"], str)

    def test_second_turn_excludes_previous_scored_slate(self) -> None:
        state = SessionState("smoke-miss", {})
        first, _trace = self.pipeline.run_traced(state, BUYING, 1, 10)
        shown = [item["parent_asin"] for item in first["recommendations"]]
        self.assertTrue(shown)
        self.assertTrue(state.last_gate_open)
        second, _trace = self.pipeline.run_traced(
            state, "Those sandals in navy, please.", 2, 10
        )
        _assert_official_response(second)
        self.assertTrue(set(shown) <= state.excluded_asins)

    def test_override_turn_still_recommends(self) -> None:
        state = SessionState("smoke-override", {})
        self.pipeline.run_traced(state, BUYING, 1, 10)
        self.override_patch.stop()
        self.override_patch = patch(
            "agent.intent_router.router.classify_override", return_value=True
        )
        self.override_patch.start()
        self.addCleanup(self.override_patch.stop)
        response, _trace = self.pipeline.run_traced(state, TURN3, 2, 10)
        _assert_official_response(response)
        self.assertEqual(state.intention, "override")
        self.assertTrue(response["recommendations"])

    def test_empty_utterance_does_not_raise(self) -> None:
        state = SessionState("smoke-empty", {})
        response, _trace = self.pipeline.run_traced(state, "hello there", 1, 10)
        _assert_official_response(response)
        self.assertIsInstance(response["message"], str)

    def test_turn_ten_is_full_slate_without_question(self) -> None:
        state = SessionState("smoke-final", {})
        state.turn = 9
        response, trace = self.pipeline.run_traced(state, BUYING, 10, 10)
        _assert_official_response(response)
        self.assertIsNone(response["ask_attribute"])
        self.assertGreaterEqual(len(response["recommendations"]), 1)
        self.assertLessEqual(len(response["recommendations"]), 10)
        self.assertIsNone(trace.decide["ask_attribute"])

    def test_none_exact_pool_falls_back_to_search(self) -> None:
        state = SessionState("smoke-hybrid", {})
        with patch(
            "agent.intent_router.router.probe_exact_pool", return_value=None
        ):
            response, trace = self.pipeline.run_traced(state, BUYING, 1, 10)
        _assert_official_response(response)
        self.assertIsNone(trace.exact)
        self.assertFalse(trace.retrieve["scored_exact"])
        self.assertGreater(trace.retrieve["hit_count"], 0)

    def test_scripted_nlu_first_turn(self) -> None:
        configure_understand(MODE_NLU)
        payload = {
            "category": [
                {"surface": "sandals", "canonical": ["shoe"], "is_hard": True}
            ],
            "constraints": [
                {
                    "attribute": "color",
                    "surface": "blue",
                    "canonical": ["blue"],
                    "is_hard": True,
                }
            ],
            "empty": False,
        }
        set_nlu_client(_ScriptedExtractClient([(payload, "I want blue sandals.")]))
        state = SessionState("smoke-nlu", {})
        response, trace = self.pipeline.run_traced(
            state, "I want blue sandals.", 1, 10
        )
        _assert_official_response(response)
        self.assertEqual(trace.understand["source"], "llm")
        rec_ids = {item["parent_asin"] for item in response["recommendations"]}
        self.assertTrue(rec_ids <= {BLUE_SHOE})


class ConsoleChatbotSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        _catalog, _slots, self.retriever = build_fixture(Path(self.temporary.name))
        self.addCleanup(self.retriever.close)
        configure_understand(MODE_REGEX)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        self.nlu_console = _load_console()

    def test_console_prints_stages_and_titled_recommendation(self) -> None:
        out = io.StringIO()
        console = self.nlu_console.NluConsole(
            None, out=out, retriever=self.retriever
        )
        with patch("agent.intent_router.router.classify_override", return_value=False):
            with patch(
                "agent.intent_router.router.classify_route", return_value="buying"
            ):
                console.run_turn(BUYING)
        text = out.getvalue()
        self.assertIn("--- understand ---", text)
        self.assertIn("--- router ---", text)
        self.assertIn("--- retrieve ---", text)
        self.assertIn("--- ranking ---", text)
        self.assertIn("--- decide ---", text)
        self.assertIn("--- agent ---", text)
        self.assertTrue("BLUE_SHOE" in text or "PINK_SHOE" in text)
        self.assertIn("leather sandals", text)
        self.assertTrue(console.last_trace.response["recommendations"])
        self.assertLessEqual(console.state.turn, 10)


if __name__ == "__main__":
    unittest.main()
