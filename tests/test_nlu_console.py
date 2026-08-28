"""Tests for the interactive understand NLU console helpers.

Does not start a REPL and does not call Ollama.
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path

from agent.understand.observation.schema import ObservationExtract, parse_observation_payload

ROOT = Path(__file__).resolve().parents[1]


def _load_console():
    spec = importlib.util.spec_from_file_location(
        "nlu_console",
        ROOT / "scripts" / "nlu_console.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nlu_console = _load_console()


class _FakeNluClient:
    model = "fake"
    host = "http://127.0.0.1"

    def inspect(self, message, *, category, constraints, last_ask):
        payload = {
            "category": "dress",
            "provisional_hint": None,
            "constraints": ["black", "wedding"],
            "override": False,
            "override_value": None,
            "track": "buying",
            "empty": False,
        }
        return payload, parse_observation_payload(payload, message)


class ConsoleHelperTest(unittest.TestCase):
    def test_split_constraints_keeps_commas_inside_a_span(self) -> None:
        self.assertEqual(
            nlu_console.split_constraints("leather; under $40"),
            ["leather", "under $40"],
        )
        self.assertEqual(nlu_console.split_constraints("  "), [])

    def test_labeled_constraints_use_keyword_attributes(self) -> None:
        labeled = nlu_console.labeled_constraints(["black", "leather", "under $40"])
        self.assertEqual(labeled[0]["attribute"], "color")
        self.assertEqual(labeled[1]["attribute"], "material")
        self.assertEqual(labeled[2]["attribute"], "budget")

    def test_grounding_drops_invented_spans(self) -> None:
        payload = {
            "category": "running shoes",
            "constraints": ["leather", "breathable mesh"],
        }
        extract = parse_observation_payload(
            {**payload, "override": False, "track": "buying", "empty": False},
            "Need leather running shoes.",
        )
        dropped = nlu_console.grounding_drops(
            payload, extract, "Need leather running shoes."
        )
        self.assertEqual(dropped["constraints"], ["breathable mesh"])

    def test_apply_none_leaves_session_untouched(self) -> None:
        console = nlu_console.NluConsole(_FakeNluClient(), out=io.StringIO())
        console.apply_mode = "none"
        console.state.category = "sandals"
        console.run_turn("I want a black dress for a wedding.")
        self.assertEqual(console.state.category, "sandals")
        self.assertEqual(console.state.active_constraints, [])
        self.assertEqual(console.state.turn, 0)

    def test_apply_nlu_writes_category_and_constraints(self) -> None:
        console = nlu_console.NluConsole(_FakeNluClient(), out=io.StringIO())
        console.apply_mode = "nlu"
        console.mode = "nlu"
        console.run_turn("I want a black dress for a wedding.")
        self.assertEqual(console.state.category, "dress")
        self.assertEqual(console.state.active_constraints, ["black", "wedding"])
        self.assertEqual(console.state.track, "buying")
        self.assertEqual(console.state.turn, 1)
        self.assertTrue(console.state.typed_constraints)

    def test_apply_nlu_does_not_write_regex_when_model_fails(self) -> None:
        class _FailingClient:
            model = "fake"
            host = "http://127.0.0.1"
            last_error = "content was not a JSON object (done_reason='length')"

            def inspect(self, message, *, category, constraints, last_ask):
                return None, None

        console = nlu_console.NluConsole(_FailingClient(), out=io.StringIO())
        console.apply_mode = "nlu"
        console.mode = "nlu"
        console.state.category = "running shoes"
        console.run_turn(
            "actually, blue and pink also ok for me. brand wise i want it to be Nike"
        )
        self.assertEqual(console.state.turn, 0)
        self.assertEqual(console.state.category, "running shoes")
        self.assertEqual(console.state.active_constraints, [])
        self.assertIn("not a JSON object", console.out.getvalue())
        self.assertNotIn("applied nlu", console.out.getvalue())

    def test_state_snapshot_uses_slot_attribute_not_keyword_guess(self) -> None:
        from agent.understand.observation.slots import ConstraintSlot

        console = nlu_console.NluConsole(None, out=io.StringIO())
        surface = "orpiment or saffron hue"
        console.state.active_constraints = [surface]
        console.state.typed_constraints = [
            ConstraintSlot(attribute="color", surface=surface, canonical="orange")
        ]
        snap = nlu_console.state_snapshot(console.state)
        self.assertEqual(snap["active_constraints"][0]["attribute"], "color")
        self.assertNotIn("retrieval_pairs", snap)
        self.assertEqual(snap["typed_constraints"][0]["canonical"], ["orange"])

    def test_seed_commands_fill_model_context(self) -> None:
        console = nlu_console.NluConsole(None, out=io.StringIO())
        console.handle_command("/category running shoes")
        console.handle_command("/constraints leather; under $40")
        console.handle_command("/ask color")
        console.handle_command("/track buying")
        snap = nlu_console.state_snapshot(console.state)
        self.assertEqual(snap["model_context"]["category"], "running shoes")
        self.assertEqual(
            snap["model_context"]["locked_constraints"],
            ["leather", "under $40"],
        )
        self.assertEqual(snap["model_context"]["last_ask"], "color")


class ExtractDictTest(unittest.TestCase):
    def test_failed_extract_is_not_ok(self) -> None:
        row = nlu_console.extract_as_dict(None, elapsed_ms=12.3)
        self.assertFalse(row["ok"])
        self.assertEqual(row["elapsed_ms"], 12.3)

    def test_empty_extract_keeps_source(self) -> None:
        row = nlu_console.extract_as_dict(ObservationExtract(empty=True, source="llm"))
        self.assertTrue(row["empty"])
        self.assertEqual(row["source"], "llm")
        self.assertEqual(row["slots"], [])
        self.assertEqual(row["repair_rounds"], 0)

    def test_extract_dict_labels_slots_not_keyword_guess(self) -> None:
        from agent.understand.observation.slots import ConstraintSlot

        extract = ObservationExtract(
            constraints=("orpiment or saffron hue",),
            slots=(
                ConstraintSlot(
                    attribute="color",
                    surface="orpiment or saffron hue",
                    canonical="orange",
                ),
            ),
            source="llm",
        )
        row = nlu_console.extract_as_dict(extract)
        self.assertEqual(row["constraints"][0]["attribute"], "color")
        self.assertEqual(row["constraints"][0]["span"], "orpiment or saffron hue")


if __name__ == "__main__":
    unittest.main()
