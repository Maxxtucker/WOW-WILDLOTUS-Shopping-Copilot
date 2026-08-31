"""Progress bus is a no-op without a listener and emits understand nodes when set."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.decide.clarification.stage import Clarifier
from agent.decide.ranking import Ranker
from agent.decide.ranking.normalize import RankedCandidate
from agent.intent_router.llm import OverrideDecision
from agent.intent_router.router import route_intention
from agent.orchestrator import Agent
from agent.pipeline import TurnPipeline
from agent.progress import STAGE_NODES, emit, progress_listener
from agent.retrieve.candidates.retrieve import retrieve_candidates
from agent.retrieve.catalog.types import SearchHit
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.coordinator import observe
from agent.understand.observation.hybrid import hybrid_extract
from agent.understand.observation.llm_nlu import OllamaNluClient, set_nlu_client
from agent.understand.observation.rewrite import rewrite_for_nlu
from agent.understand.observation.schema import ObservationExtract
from agent.understand.observation.slots.types import ConstraintSlot
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
        self.assertIn("prior_miss", nodes)
        self.assertIn("turn_reset", nodes)
        self.assertIn("understand_mode", nodes)
        self.assertIn("regex_extract", nodes)
        self.assertIn("active_intent_evidence", nodes)
        self.assertIn("empty_disclosure_gate", nodes)
        self.assertIn("slot_groups", nodes)
        self.assertIn("weighted_score", nodes)
        self.assertIn("normalize", nodes)
        self.assertIn("hit_component", nodes)
        self.assertIn("epsilon_roll", nodes)
        self.assertIn("selected_attribute", nodes)
        self.assertIn("build_response", nodes)
        self.assertNotIn("organize", nodes)
        self.assertNotIn("reply", nodes)
        self.assertNotIn("ranking", stages)
        self.assertNotIn("reply", stages)
        terminal_nodes = {
            event["node"]
            for event in events
            if event["status"] in {"completed", "skipped", "error"}
        }
        expected_nodes = {
            node
            for stage_nodes in STAGE_NODES.values()
            for node in stage_nodes
        }
        self.assertEqual(expected_nodes - terminal_nodes, set())

    def test_progress_listener_does_not_change_response(self) -> None:
        without_listener = SessionState(session_id="same", user_profile={})
        with_listener = SessionState(session_id="same", user_profile={})
        events: list[dict] = []
        with patch.object(
            self.pipeline.ranker.semantic, "belief", return_value=None
        ):
            expected, _ = self.pipeline.run_traced(
                without_listener, BUYING, 1, 10
            )
            with progress_listener(events.append):
                actual, _ = self.pipeline.run_traced(
                    with_listener, BUYING, 1, 10
                )
        self.assertEqual(actual, expected)
        self.assertTrue(events)

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
        self.assertEqual(by_node["override_l1"], "skipped")
        self.assertEqual(by_node["override_l2"], "skipped")
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

    def test_strong_override_fallback_is_an_explicit_l2_node(self) -> None:
        state = SessionState(session_id="fallback", user_profile={})
        state.turn = 2
        state.category = "shoes"
        state.latest_message = (
            "Ignore my earlier preference; I need polyester instead."
        )
        state.turn_delta = ObservationExtract(
            constraints=("polyester",),
            slots=(
                ConstraintSlot(
                    attribute="material",
                    surface="polyester",
                    canonical=("polyester",),
                    is_hard=True,
                ),
            ),
            source="regex",
        )
        events: list[dict] = []
        with progress_listener(events.append):
            route_intention(state, self.retriever)
        completed = {
            event["node"]: event
            for event in events
            if event["status"] == "completed"
        }
        self.assertTrue(
            completed["strong_override_fallback"]["detail"]["output"]["matched"]
        )
        self.assertEqual(
            completed["override_l2"]["detail"]["output"]["source"],
            "strong explicit fallback",
        )
        self.assertIn("drop_slots", completed)
        self.assertIn("override_gate_cleanup", completed)
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

    def test_retrieve_publishes_full_score_fanout(self) -> None:
        state = SessionState(session_id="score-trace", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            retrieve_candidates(self.retriever, state, None)
        completed = {
            event["node"]: event
            for event in events
            if event["status"] == "completed"
        }
        expected = {
            "bm25_score",
            "required_score",
            "preferred_score",
            "category_score",
            "budget_score",
            "dimension_score",
            "exclusion_score",
            "structured_subtotal",
            "rating_prior",
            "popularity_prior",
            "catalog_prior",
            "title_text_fit",
            "details_text_fit",
            "description_text_fit",
            "soft_text_fit",
            "profile_diagnostic",
            "weighted_score",
        }
        self.assertTrue(expected.issubset(completed))
        formula = completed["weighted_score"]["detail"]["input"]["formula"]
        self.assertIn("1.15*w_lex*lexical", formula)
        self.assertEqual(
            completed["profile_diagnostic"]["detail"]["input"][
                "final_score_weight"
            ],
            0.0,
        )

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
        hits = [
            SearchHit(
                "A",
                1.0,
                0.0,
                1.0,
                0.0,
                1.0,
                reasons=("route:strict+raw",),
            ),
            SearchHit(
                "B",
                0.98,
                0.0,
                1.0,
                0.0,
                1.0,
                reasons=("route:relaxed",),
            ),
        ]
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
        self.assertEqual(by_node["belief_temperature"], "completed")
        self.assertEqual(by_node["belief_hits"], "completed")
        self.assertEqual(by_node["normalize"], "completed")
        temperature_event = next(
            event
            for event in events
            if event["node"] == "belief_temperature"
            and event["status"] == "completed"
        )
        output = temperature_event["detail"]["output"]
        self.assertEqual(output["mode"], "adaptive RRF scale")
        self.assertAlmostEqual(output["temperature"], 0.005)


class ProgressBranchTest(unittest.TestCase):
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

    def _statuses(self, events: list[dict]) -> dict[str, str]:
        return {
            event["node"]: event["status"]
            for event in events
            if event["status"] in {"completed", "skipped", "error"}
        }

    def test_nlu_failure_falls_back_to_regex_nodes(self) -> None:
        configure_understand(MODE_NLU)
        state = SessionState(session_id="nlu-fallback", user_profile={})
        events: list[dict] = []
        with (
            patch(
                "agent.understand.observation.hybrid.extract_with_llm",
                return_value=None,
            ),
            progress_listener(events.append),
        ):
            extract = hybrid_extract(state, BUYING)
        statuses = self._statuses(events)
        self.assertEqual(extract.source, "regex")
        self.assertEqual(statuses["nlu_attempt"], "completed")
        self.assertEqual(statuses["regex_extract"], "completed")
        fallback = next(
            event
            for event in events
            if event["node"] == "nlu_attempt" and event["status"] == "completed"
        )
        self.assertEqual(fallback["detail"]["output"]["fallback"], "regex")
        self.assertEqual(fallback["detail"]["output"]["attempts_used"], 3)

    def test_colon_restore_runs_for_regex_without_constraints(self) -> None:
        state = SessionState(session_id="colon", user_profile={})
        state.last_ask = "material"
        events: list[dict] = []
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                return_value=ObservationExtract(
                    category="sandals",
                    source="regex",
                    empty=False,
                    slots=(
                        ConstraintSlot(
                            attribute="category",
                            surface="sandals",
                            is_hard=True,
                        ),
                    ),
                ),
            ),
            progress_listener(events.append),
        ):
            observe(state, "My answer: leather")
        completed = {
            event["node"]: event
            for event in events
            if event["status"] == "completed"
        }
        self.assertTrue(completed["colon_restore"]["detail"]["output"]["applied"])
        self.assertIn("leather", completed["colon_restore"]["detail"]["output"]["restored_constraints"])

    def test_l2_override_skips_full_replace_and_accumulate(self) -> None:
        state = SessionState(session_id="l2", user_profile={})
        state.category = "sandals"
        state.turn_delta = ObservationExtract(
            constraints=("leather",),
            slots=(
                ConstraintSlot(
                    attribute="material",
                    surface="leather",
                    canonical=("leather",),
                    is_hard=True,
                ),
            ),
            source="regex",
        )
        events: list[dict] = []
        with (
            patch(
                "agent.intent_router.router.classify_override",
                return_value=OverrideDecision(2),
            ),
            progress_listener(events.append),
        ):
            route_intention(state, self.retriever)
        statuses = self._statuses(events)
        self.assertEqual(statuses["drop_slots"], "completed")
        self.assertEqual(statuses["replace_delta"], "skipped")
        self.assertEqual(statuses["probe_override"], "completed")
        self.assertEqual(statuses["apply_delta"], "skipped")
        self.assertEqual(state.intention, "override")

    def test_empty_disclosure_skips_router_retrieve_and_planning(self) -> None:
        state = SessionState(session_id="page", user_profile={})
        state.last_ranked = ["B0TESTASIN1", "B0TESTASIN2"]
        events: list[dict] = []
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                return_value=ObservationExtract(
                    empty=True,
                    source="llm",
                    disclosure_empty=True,
                ),
            ),
            progress_listener(events.append),
        ):
            self.pipeline.run_traced(state, "ok sure", 2, 10)
        statuses = self._statuses(events)
        self.assertEqual(statuses["empty_disclosure_gate"], "completed")
        self.assertEqual(statuses["override_l1"], "skipped")
        self.assertEqual(statuses["hybrid_search"], "skipped")
        self.assertEqual(statuses["planner"], "skipped")
        self.assertEqual(statuses["persist_turn"], "completed")
        self.assertEqual(statuses["build_response"], "completed")

    def test_raw_evidence_completes_rrf_and_skips_base_only(self) -> None:
        state = SessionState(session_id="rrf", user_profile={})
        state.current_intent_messages = ["leather sandals"]
        events: list[dict] = []
        with progress_listener(events.append):
            retrieve_candidates(self.retriever, state, None)
        statuses = self._statuses(events)
        self.assertEqual(statuses["raw_evidence"], "completed")
        self.assertEqual(statuses["base_only"], "skipped")
        self.assertEqual(statuses["relaxed_route"], "completed")
        self.assertEqual(statuses["raw_text_route"], "completed")
        self.assertEqual(statuses["weighted_rrf"], "completed")

    def test_base_only_skips_rrf_without_raw_evidence(self) -> None:
        state = SessionState(session_id="base-only", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            retrieve_candidates(self.retriever, state, None)
        statuses = self._statuses(events)
        self.assertEqual(statuses["base_only"], "completed")
        self.assertEqual(statuses["weighted_rrf"], "skipped")
        self.assertEqual(statuses["relaxed_route"], "skipped")

    def test_pool_probe_publishes_or_and_unknown_numeric_contract(self) -> None:
        state = SessionState(session_id="pool-trace", user_profile={})
        events: list[dict] = []
        with progress_listener(events.append):
            route_intention(state, self.retriever)
        probe = next(
            event
            for event in events
            if event["node"] == "probe_after" and event["status"] == "completed"
        )
        payload = probe["detail"]["input"]
        self.assertEqual(payload["within_attribute"], "OR")
        self.assertEqual(payload["across_attributes"], "AND")
        self.assertIn("catalog-unknown", payload["lenient_unknown"])
        self.assertFalse(payload["numeric"]["strict_allow_missing"])
        self.assertTrue(payload["numeric"]["lenient_allow_missing"])

    def _plan_events(self, *, turn: int, roll: float | None) -> dict[str, dict]:
        state = SessionState(session_id="decide-trace", user_profile={})
        state.turn = turn
        ranked = [RankedCandidate("B0TESTASIN1", 1.0, 1.0)]
        clarifier = Clarifier(self.retriever)
        events: list[dict] = []
        with progress_listener(events.append):
            if roll is None:
                clarifier.apply(state, ranked, 10)
            else:
                with (
                    patch(
                        "agent.decide.clarification.stage.eligible_questions",
                        return_value=["color", "material"],
                    ),
                    patch(
                        "agent.decide.clarification.stage.random.Random"
                    ) as mocked,
                ):
                    mocked.return_value.random.return_value = roll
                    mocked.return_value.choice.side_effect = lambda pool: pool[0]
                    clarifier.apply(state, ranked, 10)
        return {
            event["node"]: event
            for event in events
            if event["status"] in {"completed", "skipped"}
        }

    def test_decide_exploit_skips_uniform_explore(self) -> None:
        by_node = self._plan_events(turn=1, roll=0.50)
        self.assertEqual(by_node["epsilon_roll"]["status"], "completed")
        self.assertEqual(by_node["technical_exploit"]["status"], "completed")
        self.assertEqual(by_node["uniform_explore"]["status"], "skipped")
        self.assertEqual(by_node["gate_rank1"]["status"], "skipped")
        self.assertEqual(by_node["keep_planned"]["status"], "completed")

    def test_decide_explore_skips_technical_exploit(self) -> None:
        by_node = self._plan_events(turn=1, roll=0.05)
        self.assertEqual(by_node["uniform_explore"]["status"], "completed")
        self.assertEqual(by_node["technical_exploit"]["status"], "skipped")

    def test_decide_final_turn_disables_exploration(self) -> None:
        by_node = self._plan_events(turn=10, roll=None)
        self.assertEqual(
            by_node["epsilon_roll"]["detail"]["output"]["selection_mode"],
            "disabled",
        )
        self.assertEqual(by_node["technical_exploit"]["status"], "skipped")
        self.assertEqual(by_node["uniform_explore"]["status"], "skipped")


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
