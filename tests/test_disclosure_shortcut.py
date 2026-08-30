"""Empty-disclosure shortcut: page leftover ranks without router or retrieve.

Does not call Ollama or read public_set.jsonl.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.pipeline import TurnPipeline, next_ranked_page, pages_empty_disclosure
from agent.progress import progress_listener
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.coordinator import observe
from agent.understand.observation.disclosure import (
    apply_disclosure,
    parse_disclosure_empty,
)
from agent.understand.observation.llm_nlu import OllamaNluClient, set_nlu_client
from agent.understand.observation.schema import ObservationExtract
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState
from tests.test_understand_router_smoke import build_fixture

RANKED = [f"A{index:02d}" for index in range(20)]


class ParseDisclosureTest(unittest.TestCase):
    def test_legal_bool_only(self) -> None:
        self.assertTrue(parse_disclosure_empty({"empty": True}))
        self.assertFalse(parse_disclosure_empty({"empty": False}))
        self.assertTrue(parse_disclosure_empty({"empty": "true"}))
        self.assertIsNone(parse_disclosure_empty({"empty": True, "constraints": []}))
        self.assertIsNone(parse_disclosure_empty({"constraints": []}))
        self.assertIsNone(parse_disclosure_empty(None))


class ApplyDisclosureTest(unittest.TestCase):
    def test_legal_empty_voids_extract(self) -> None:
        extract = ObservationExtract(
            category="dress",
            empty=False,
            source="llm",
            slots=(ConstraintSlot(attribute="category", surface="dress"),),
        )
        out = apply_disclosure(
            extract, "ok sure", complete=lambda *_a, **_k: {"empty": True}
        )
        self.assertTrue(out.empty)
        self.assertTrue(out.disclosure_empty)
        self.assertIsNone(out.category)

    def test_three_illegal_fail_open(self) -> None:
        extract = ObservationExtract(category="dress", empty=False, source="llm")
        calls = {"n": 0}

        def complete(*_a, **_k):
            calls["n"] += 1
            return {"constraints": [], "empty": True}

        out = apply_disclosure(extract, "a navy dress", complete=complete)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(out.category, "dress")
        self.assertIs(out.disclosure_empty, False)


class DisclosureObserveTest(unittest.TestCase):
    def test_legal_empty_sets_turn_delta_none(self) -> None:
        configure_understand(MODE_NLU)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        client = OllamaNluClient()
        events: list[dict] = []

        def complete(_user, *, system=None, **_kwargs):
            text = system or ""
            if text.startswith("You judge whether this shopper utterance discloses"):
                return {"empty": True}
            return {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "blue",
                        "canonical": ["blue"],
                    }
                ],
                "empty": False,
            }

        state = SessionState("disc-obs", {})
        with (
            patch.object(client, "_category_picks", return_value=()),
            patch.object(client, "_complete", side_effect=complete),
            patch(
                "agent.understand.observation.llm_nlu.get_nlu_client",
                return_value=client,
            ),
            progress_listener(events.append),
        ):
            observe(state, "I want blue running shoes.")
        self.assertIsNone(state.turn_delta)
        self.assertIs(state.disclosure_empty, True)
        self.assertTrue(
            any(
                event["node"] == "disclosure"
                and event["status"] == "completed"
                and event.get("detail", {}).get("empty") is True
                for event in events
            )
        )


class DisclosureShortcutPipelineTest(unittest.TestCase):
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

    def _seeded(self) -> SessionState:
        state = SessionState("disc-pipe", {})
        state.last_ranked = list(RANKED)
        state.shown_asins = {RANKED[0]}
        state.excluded_asins = {RANKED[0]}
        return state

    def _empty_extract(self, *_args, **_kwargs) -> ObservationExtract:
        return ObservationExtract(empty=True, source="llm", disclosure_empty=True)

    def test_specific_no_preference_returns_to_dynamic_planner(self) -> None:
        state = self._seeded()
        state.last_ask = "color"
        state.disclosure_empty = True
        state.turn_delta = None

        # last_ask does not block paging shortcut; it only prevents re-asking
        # the same attribute. When turn_delta=None, no new evidence exists,
        # so paging from last_ranked is correct. Clarifier will avoid "color"
        # because last_ask prevents it.
        self.assertTrue(pages_empty_disclosure(state))

    def test_empty_pages_ranks_2_to_11(self) -> None:
        state = self._seeded()
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                self._empty_extract,
            ),
            patch.object(self.pipeline.intent_router, "apply") as router,
            patch.object(self.pipeline.organizer, "apply") as organizer,
        ):
            response, trace = self.pipeline.run_traced(state, "ok sure", 2, 10)
        router.assert_not_called()
        organizer.assert_not_called()
        recs = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(recs, RANKED[1:11])
        self.assertEqual(len(recs), 10)
        self.assertEqual(response["ask_attribute"], "other")
        self.assertEqual(trace.decide["reason"], "empty disclosure")
        self.assertEqual(trace.decide["slate"], RANKED[1:11])
        self.assertEqual(state.last_ranked, RANKED)

    def test_short_leftover_still_shortcuts(self) -> None:
        state = SessionState("disc-short", {})
        state.last_ranked = [f"A{index:02d}" for index in range(9)]
        self.assertEqual(len(next_ranked_page(state)), 9)
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                self._empty_extract,
            ),
            patch.object(self.pipeline.intent_router, "apply") as router,
            patch.object(self.pipeline.organizer, "apply") as organizer,
        ):
            response, trace = self.pipeline.run_traced(state, "ok", 2, 10)
        router.assert_not_called()
        organizer.assert_not_called()
        recs = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(recs, state.last_ranked)
        self.assertEqual(trace.decide["reason"], "empty disclosure")

    def test_second_empty_still_shortcuts(self) -> None:
        state = self._seeded()
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                self._empty_extract,
            ),
            patch.object(self.pipeline.intent_router, "apply") as router,
            patch.object(self.pipeline.organizer, "apply") as organizer,
        ):
            first, _trace = self.pipeline.run_traced(state, "ok", 2, 10)
            self.assertEqual(
                [item["parent_asin"] for item in first["recommendations"]],
                RANKED[1:11],
            )
            second, trace = self.pipeline.run_traced(state, "sure", 3, 10)
        router.assert_not_called()
        organizer.assert_not_called()
        self.assertEqual(
            [item["parent_asin"] for item in second["recommendations"]],
            RANKED[11:20],
        )
        self.assertEqual(trace.decide["reason"], "empty disclosure")

    def test_disclosed_calls_router(self) -> None:
        state = self._seeded()

        def disclosed(*_args, **_kwargs) -> ObservationExtract:
            return ObservationExtract(
                category="sandals",
                empty=False,
                source="llm",
                disclosure_empty=False,
                slots=(
                    ConstraintSlot(
                        attribute="category",
                        surface="sandals",
                        is_hard=True,
                    ),
                ),
            )

        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                disclosed,
            ),
            patch.object(
                self.pipeline.intent_router, "apply", return_value=None
            ) as router,
            patch.object(self.pipeline.organizer, "apply", return_value=[]),
        ):
            self.pipeline.run_traced(state, "navy sandals", 2, 10)
        router.assert_called()

    def test_three_illegal_does_not_shortcut(self) -> None:
        state = self._seeded()

        def fail_open(*_args, **_kwargs) -> ObservationExtract:
            return ObservationExtract(
                empty=True, source="llm", disclosure_empty=False
            )

        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                fail_open,
            ),
            patch.object(
                self.pipeline.intent_router, "apply", return_value=None
            ) as router,
            patch.object(self.pipeline.organizer, "apply", return_value=[]),
        ):
            self.pipeline.run_traced(state, "ok", 2, 10)
        router.assert_called()

    def test_all_shown_last_ranked_does_not_shortcut(self) -> None:
        state = SessionState("disc-shown", {})
        state.last_ranked = ["ONLY"]
        state.shown_asins = {"ONLY"}
        state.excluded_asins = {"ONLY"}
        self.assertEqual(next_ranked_page(state), [])
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                self._empty_extract,
            ),
            patch.object(
                self.pipeline.intent_router, "apply", return_value=None
            ) as router,
            patch.object(self.pipeline.organizer, "apply", return_value=[]),
        ):
            self.pipeline.run_traced(state, "ok", 2, 10)
        router.assert_called()

    def test_no_last_ranked_does_not_shortcut(self) -> None:
        state = SessionState("disc-first", {})
        self.assertEqual(next_ranked_page(state), [])
        with (
            patch(
                "agent.understand.observation.coordinator.hybrid_extract",
                self._empty_extract,
            ),
            patch.object(
                self.pipeline.intent_router, "apply", return_value=None
            ) as router,
            patch.object(self.pipeline.organizer, "apply", return_value=[]),
        ):
            self.pipeline.run_traced(state, "ok", 1, 10)
        router.assert_called()


if __name__ == "__main__":
    unittest.main()
