"""Progress bus is a no-op without a listener and emits understand nodes when set."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.decide.ranking import Ranker
from agent.intent_router.router import route_intention
from agent.orchestrator import Agent
from agent.pipeline import TurnPipeline
from agent.progress import emit, progress_listener
from agent.retrieve.candidates.retrieve import retrieve_candidates
from agent.retrieve.catalog.types import SearchHit
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.llm_nlu import OllamaNluClient, set_nlu_client
from agent.understand.observation.rewrite import rewrite_for_nlu
from agent.understand.state import SessionState
from demo.progress_ui import STAGE_ORDER, apply_event, empty_circuit_state, finalize_circuit
from tests.test_understand_router_smoke import build_fixture

BUYING = "I'm looking for women's sandals. A key requirement is: leather."


class ProgressBusTest(unittest.TestCase):
    def test_emit_without_listener_is_noop(self) -> None:
        emit("understand", "casefold", "running")

    def test_rewrite_without_listener_matches_navy_mapping(self) -> None:
        rewritten = rewrite_for_nlu("A navy dress.")
        self.assertIn("blue", rewritten)
        self.assertNotIn("navy", rewritten)

    def test_rewrite_emits_color_map_and_merge(self) -> None:
        events: list[dict] = []
        with progress_listener(events.append):
            rewritten = rewrite_for_nlu("A navy dress.")
        self.assertIn("blue", rewritten)
        nodes = [event["node"] for event in events]
        self.assertIn("casefold", nodes)
        self.assertIn("color_map", nodes)
        self.assertIn("merge_rewrite", nodes)
        merge = next(
            event
            for event in events
            if event["node"] == "merge_rewrite" and event["status"] == "completed"
        )
        self.assertIn("blue", str(merge["detail"]["rewritten"]))

    def test_inspect_emits_attribute_llm(self) -> None:
        configure_understand(MODE_NLU)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        client = OllamaNluClient(host="http://127.0.0.1", model="fake", timeout=1.0)
        events: list[dict] = []
        with (
            patch.object(
                client, "_complete", return_value={"constraints": [], "empty": True}
            ),
            progress_listener(events.append),
        ):
            payload, extract = client.inspect("a navy dress")
        self.assertIsNotNone(payload)
        self.assertIsNotNone(extract)
        nodes = [event["node"] for event in events]
        self.assertIn("color_map", nodes)
        self.assertIn("merge_rewrite", nodes)
        self.assertIn("attribute_llm", nodes)
        self.assertIn("disclosure", nodes)
        self.assertTrue(
            any(
                event["node"] == "attribute_llm" and event["status"] == "completed"
                for event in events
            )
        )

    def test_skip_does_not_overwrite_completed_node(self) -> None:
        state = empty_circuit_state()
        apply_event(
            state,
            {"stage": "understand", "node": "casefold", "status": "completed"},
        )
        apply_event(
            state,
            {"stage": "understand", "node": "casefold", "status": "skipped"},
        )
        self.assertEqual(state["nodes"]["casefold"]["status"], "completed")

    def test_circuit_has_four_stages_only(self) -> None:
        state = empty_circuit_state()
        self.assertEqual(STAGE_ORDER, ("understand", "router", "retrieve", "decide"))
        self.assertEqual(set(state["stages"]), set(STAGE_ORDER))
        self.assertNotIn("ranking", state["stages"])
        self.assertNotIn("reply", state["stages"])
        self.assertNotIn("organize", state["nodes"])
        self.assertNotIn("belief", state["nodes"])
        self.assertNotIn("reply", state["nodes"])
        self.assertIn("probe_before", state["nodes"])
        self.assertIn("hybrid_search", state["nodes"])
        self.assertIn("disclosure", state["nodes"])
        self.assertIn("override_l1", state["nodes"])
        self.assertIn("override_l2", state["nodes"])
        self.assertIn("drop_slots", state["nodes"])
        self.assertIn("build_response", state["nodes"])

    def test_active_graph_follows_stage_events(self) -> None:
        state = empty_circuit_state()
        self.assertEqual(state["activeGraph"], "understand")
        apply_event(
            state,
            {"stage": "understand", "node": "stage", "status": "completed"},
        )
        self.assertEqual(state["activeGraph"], "router")
        apply_event(
            state,
            {"stage": "router", "node": "stage", "status": "completed"},
        )
        self.assertEqual(state["activeGraph"], "retrieve")
        apply_event(
            state,
            {"stage": "retrieve", "node": "normalize", "status": "running"},
        )
        self.assertEqual(state["activeGraph"], "retrieve")
        apply_event(
            state,
            {"stage": "retrieve", "node": "stage", "status": "completed"},
        )
        self.assertEqual(state["activeGraph"], "decide")

    def test_finalize_keeps_view_graph(self) -> None:
        state = empty_circuit_state()
        self.assertEqual(state["viewGraph"], "")
        state["viewGraph"] = "understand"
        finalize_circuit(state, None)
        self.assertEqual(state["activeGraph"], "decide")
        self.assertEqual(state["viewGraph"], "understand")


class ProgressPipelineTest(unittest.TestCase):
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

    def test_run_traced_with_listener_still_returns_reply(self) -> None:
        state = SessionState(session_id="progress", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            response, trace = self.pipeline.run_traced(state, BUYING, 1, 10)
        self.assertIsInstance(response.get("message"), str)
        self.assertEqual(trace.understand["source"], "regex")
        nodes = {event["node"] for event in events}
        stages = {event["stage"] for event in events}
        self.assertIn("turn_delta", nodes)
        self.assertIn("slot_groups", nodes)
        self.assertIn("normalize", nodes)
        self.assertIn("build_response", nodes)
        self.assertNotIn("organize", nodes)
        self.assertNotIn("reply", nodes)
        self.assertNotIn("ranking", stages)
        self.assertNotIn("reply", stages)

    def test_accumulate_skips_override_branch(self) -> None:
        state = SessionState(session_id="acc", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            route_intention(state, self.retriever)
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["replace_delta"], "skipped")
        self.assertEqual(by_node["drop_slots"], "skipped")
        self.assertEqual(by_node["probe_override"], "skipped")
        self.assertEqual(by_node["intention_override"], "skipped")
        self.assertEqual(by_node["probe_before"], "completed")
        self.assertEqual(by_node["apply_delta"], "completed")
        self.assertEqual(by_node["probe_after"], "completed")
        self.assertEqual(by_node["route_llm"], "completed")
        self.assertEqual(by_node["buying"], "completed")
        self.assertEqual(by_node["browsing"], "skipped")
        self.assertEqual(by_node["failsafe"], "completed")

    def test_override_skips_accumulate_branch(self) -> None:
        state = SessionState(session_id="ov", user_profile={})
        events: list[dict] = []
        with (
            patch("agent.intent_router.router.classify_override", return_value=True),
            progress_listener(events.append),
        ):
            route_intention(state, self.retriever)
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["replace_delta"], "completed")
        self.assertEqual(by_node["drop_slots"], "skipped")
        self.assertEqual(by_node["override_l2"], "skipped")
        self.assertEqual(by_node["probe_override"], "completed")
        self.assertEqual(by_node["intention_override"], "completed")
        self.assertEqual(by_node["probe_before"], "skipped")
        self.assertEqual(by_node["apply_delta"], "skipped")
        self.assertEqual(by_node["route_llm"], "skipped")
        self.assertEqual(by_node["buying"], "skipped")
        self.assertEqual(by_node["browsing"], "skipped")
        self.assertEqual(state.intention, "override")

    def test_hybrid_retrieve_skips_exact_branch(self) -> None:
        state = SessionState(session_id="hyb", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            retrieve_candidates(self.retriever, state, None)
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["lexical_in_pool"], "skipped")
        self.assertEqual(by_node["score_exact"], "skipped")
        self.assertEqual(by_node["hybrid_search"], "completed")
        self.assertEqual(by_node["cap_hits"], "completed")

    def test_small_exact_retrieve_completes_hybrid_fill(self) -> None:
        state = SessionState(session_id="ex", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            retrieve_candidates(self.retriever, state, {"B0TESTASIN1"})
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["hybrid_search"], "completed")
        self.assertEqual(by_node["lexical_in_pool"], "completed")
        self.assertEqual(by_node["score_exact"], "completed")
        self.assertEqual(by_node["cap_hits"], "completed")

    def test_exact_retrieve_skips_hybrid_when_floor_met(self) -> None:
        asins = [f"E{index:03d}" for index in range(150)]
        scored = [
            SearchHit(asin, 1.0, 0.0, 1.0, 0.0, 1.0) for asin in asins
        ]
        state = SessionState(session_id="ex150", user_profile={})
        events: list[dict] = []
        with (
            patch.object(self.retriever, "score_candidates", return_value=scored),
            patch.object(self.retriever, "search") as search,
            progress_listener(events.append),
        ):
            hits = retrieve_candidates(self.retriever, state, set(asins))
        search.assert_not_called()
        self.assertEqual(len(hits), 150)
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["hybrid_search"], "skipped")
        self.assertEqual(by_node["lexical_in_pool"], "completed")
        self.assertEqual(by_node["score_exact"], "completed")
        self.assertEqual(by_node["cap_hits"], "completed")

    def test_ranker_skips_unused_belief_path(self) -> None:
        hits = [SearchHit("A", 1.0, 0.0, 1.0, 0.0, 1.0)]
        state = SessionState(session_id="rk", user_profile={})
        ranker = Ranker(self.retriever)
        events: list[dict] = []
        with (
            patch.object(ranker.semantic, "belief", return_value=[("A", 2.0)]),
            progress_listener(events.append),
        ):
            ranked = ranker.apply(hits, state)
        self.assertEqual(ranked[0].parent_asin, "A")
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["qwen_rerank"], "completed")
        self.assertEqual(by_node["belief_hits"], "skipped")
        self.assertEqual(by_node["normalize"], "completed")

    def test_ranker_skips_qwen_when_unavailable(self) -> None:
        hits = [SearchHit("A", 1.0, 0.0, 1.0, 0.0, 1.0)]
        state = SessionState(session_id="rk2", user_profile={})
        ranker = Ranker(self.retriever)
        events: list[dict] = []
        with (
            patch.object(ranker.semantic, "belief", return_value=None),
            progress_listener(events.append),
        ):
            ranker.apply(hits, state)
        by_node = {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped"}
        }
        self.assertEqual(by_node["qwen_rerank"], "skipped")
        self.assertEqual(by_node["belief_hits"], "completed")
        self.assertEqual(by_node["normalize"], "completed")


class AgentRespondTracedTest(unittest.TestCase):
    def test_respond_traced_returns_trace(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog, _slots, retriever = build_fixture(Path(temporary.name))
        self.addCleanup(retriever.close)
        configure_understand(MODE_REGEX)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        with (
            patch("agent.intent_router.router.classify_override", return_value=False),
            patch("agent.intent_router.router.classify_route", return_value="buying"),
        ):
            agent = Agent(catalog, understand_mode=MODE_REGEX)
            self.addCleanup(agent.retriever.close)
            agent.reset("s1", {})
            response, trace = agent.respond_traced("s1", BUYING, 1, 10)
        self.assertIn("message", response)
        self.assertIn("recommendations", response)
        self.assertEqual(trace.understand["source"], "regex")


if __name__ == "__main__":
    unittest.main()
