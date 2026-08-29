"""Tests for the interactive understand NLU console helpers.

Does not start a REPL and does not call Ollama.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.slots_sidecar import SIDECAR_VERSION, catalog_fingerprint
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
_ROUTER_PATCHES: list = []


def setUpModule() -> None:
    patcher = patch.object(nlu_console, "classify_override", return_value=False)
    patcher.start()
    _ROUTER_PATCHES.append(patcher)


def tearDownModule() -> None:
    for patcher in reversed(_ROUTER_PATCHES):
        patcher.stop()
    _ROUTER_PATCHES.clear()


class _FakeNluClient:
    model = "fake"
    host = "http://127.0.0.1"

    def inspect(self, message, *, category, constraints, last_ask):
        payload = {
            "category": "dress",
            "constraints": ["black", "wedding"],
            "empty": False,
        }
        return payload, parse_observation_payload(payload, message)


class ConsoleHelperTest(unittest.TestCase):
    def test_print_json_keeps_short_canonical_on_one_line(self) -> None:
        console = nlu_console.NluConsole(None, out=io.StringIO())
        console.print_json(
            {
                "slots": [
                    {
                        "attribute": "color",
                        "surface": "orpiment or saffron hue",
                        "is_hard": True,
                        "canonical": ["orange"],
                    },
                    {
                        "attribute": "brand",
                        "surface": "Nike or Adidas",
                        "is_hard": True,
                        "canonical": ["Nike", "Adidas"],
                    },
                ]
            }
        )
        text = console.out.getvalue()
        self.assertIn('"canonical": ["orange"]', text)
        self.assertIn('"canonical": ["Nike", "Adidas"]', text)
        self.assertNotIn('"canonical": [\n', text)

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
            payload,
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
        self.assertIsNone(console.state.intention)
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
        self.assertNotIn("active_constraints", snap)
        self.assertNotIn("ranking_constraints", snap)
        self.assertNotIn("legacy_hints", snap)
        self.assertEqual(snap["typed_constraints"][0]["attribute"], "color")
        self.assertEqual(
            snap["model_context"]["locked_constraints"],
            [surface],
        )
        self.assertNotIn("retrieval_pairs", snap)
        self.assertEqual(snap["typed_constraints"][0]["canonical"], ["orange"])
        self.assertEqual(snap["preference_tags"], [])

    def test_seed_commands_fill_model_context(self) -> None:
        console = nlu_console.NluConsole(None, out=io.StringIO())
        console.handle_command("/category running shoes")
        console.handle_command("/constraints leather; under $40")
        console.handle_command("/ask color")
        console.handle_command("/intention buying")
        snap = nlu_console.state_snapshot(console.state)
        self.assertEqual(snap["model_context"]["category"], "running shoes")
        self.assertEqual(
            snap["model_context"]["locked_constraints"],
            ["leather", "under $40"],
        )
        self.assertEqual(snap["model_context"]["last_ask"], "color")
        self.assertEqual(snap["intention"], "buying")


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
        self.assertNotIn("constraints", row)
        self.assertNotIn("override", row)

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
        self.assertEqual(row["slots"][0]["attribute"], "color")
        self.assertEqual(row["slots"][0]["surface"], "orpiment or saffron hue")
        self.assertNotIn("constraints", row)


def _write_sidecar(path: Path, catalog_path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE product_slots (
            parent_asin TEXT NOT NULL,
            attribute TEXT NOT NULL,
            canonical TEXT NOT NULL,
            surface TEXT NOT NULL,
            source TEXT NOT NULL,
            extras_json TEXT,
            PRIMARY KEY (parent_asin, attribute, canonical, surface, source)
        ) WITHOUT ROWID;
        CREATE TABLE product_text (
            parent_asin TEXT NOT NULL,
            field TEXT NOT NULL,
            surface TEXT NOT NULL,
            canonical TEXT NOT NULL,
            PRIMARY KEY (parent_asin, field)
        ) WITHOUT ROWID;
        CREATE TABLE slot_stats (
            attribute TEXT NOT NULL,
            canonical TEXT NOT NULL,
            df INTEGER NOT NULL,
            idf REAL NOT NULL,
            PRIMARY KEY (attribute, canonical)
        ) WITHOUT ROWID;
        """
    )
    connection.executemany("INSERT INTO product_slots VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        (
            ("version", SIDECAR_VERSION),
            ("catalog_fingerprint", catalog_fingerprint(catalog_path)),
        ),
    )
    connection.commit()
    connection.close()


def _shoe(parent_asin: str, title: str) -> dict:
    return {
        "parent_asin": parent_asin,
        "title": title,
        "features": [title],
        "description": [title],
        "price": 49.0,
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
        "details": {},
        "average_rating": 4.0,
        "rating_number": 10,
        "store": "Acme",
    }


class _ScriptedNluClient:
    model = "fake"
    host = "http://127.0.0.1"

    def __init__(self, payloads: list[tuple[dict, str]]) -> None:
        self._payloads = list(payloads)

    def inspect(self, message, *, category, constraints, last_ask):
        del category, constraints, last_ask
        payload, grounding = self._payloads.pop(0)
        return payload, parse_observation_payload(payload, grounding or message)


class ConsoleRetrieveHandoffTest(unittest.TestCase):
    """Tiny catalog + sidecar. Mock override/route LLMs. Real probe and retrieve."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        catalog_path = root / "catalog.jsonl"
        products = [
            _shoe("BLUE_SHOE", "Blue leather sandals"),
            _shoe("PINK_SHOE", "Pink leather sandals"),
            {
                "parent_asin": "BOOK",
                "title": "Blue cookbook",
                "features": ["recipes"],
                "description": ["A cookbook"],
                "price": 12.0,
                "categories": ["Books"],
                "details": {},
                "average_rating": 4.0,
                "rating_number": 5,
                "store": "Penguin",
            },
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in products),
            encoding="utf-8",
        )
        slots_path = root / "product_slots.sqlite3"
        rows = [
            ("BLUE_SHOE", "color", "blue", "blue", "title", None),
            ("BLUE_SHOE", "material", "leather", "leather", "title", None),
            ("PINK_SHOE", "color", "pink", "pink", "title", None),
            ("PINK_SHOE", "material", "leather", "leather", "title", None),
            ("BOOK", "color", "blue", "blue", "title", None),
            ("BOOK", "category", "book", "Books", "categories", None),
        ]
        for asin in ("BLUE_SHOE", "PINK_SHOE"):
            for tag in ("clothing shoe jewelry", "woman", "shoe"):
                rows.append((asin, "category", tag, tag, "categories:tree", None))
        _write_sidecar(slots_path, catalog_path, rows)
        self.retriever = CatalogRetriever(catalog_path, slots_path=slots_path)
        self.addCleanup(self.retriever.close)
        self.assertTrue(self.retriever._slots_attached)

    def test_accumulate_prints_pool_and_retrieve_top(self) -> None:
        payload = {
            "category": [
                {
                    "surface": "sandals",
                    "canonical": ["shoe"],
                    "is_hard": True,
                }
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
        client = _ScriptedNluClient([(payload, "I want blue sandals.")])
        out = io.StringIO()
        console = nlu_console.NluConsole(client, out=out, retriever=self.retriever)
        console.apply_mode = "nlu"
        console.mode = "nlu"
        with patch("agent.intent_router.router.classify_override", return_value=False):
            with patch(
                "agent.intent_router.router.classify_route", return_value="buying"
            ) as route:
                console.run_turn("I want blue sandals.")
                route.assert_called_once()
        self.assertEqual(console.state.intention, "buying")
        self.assertFalse(console.last_router["override"])
        self.assertEqual(console.last_router["route_llm"], "buying")
        self.assertEqual(console.last_router["pool_after"], 1)
        self.assertEqual(console.last_router["exact"], 1)
        self.assertEqual(console.last_exact, {"BLUE_SHOE"})
        self.assertTrue(console.last_retrieve["scored_exact"])
        top_asins = {row["parent_asin"] for row in console.last_retrieve["top"]}
        self.assertTrue(top_asins <= {"BLUE_SHOE"})
        self.assertNotIn("BOOK", top_asins)
        text = out.getvalue()
        self.assertIn('"pool_after": 1', text)
        self.assertIn('"intention": "buying"', text)

    def test_override_skips_route_llm_and_still_retrieves(self) -> None:
        first = {
            "category": [
                {
                    "surface": "sandals",
                    "canonical": ["shoe"],
                    "is_hard": True,
                }
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
        second = {
            "category": [
                {
                    "surface": "sandals",
                    "canonical": ["shoe"],
                    "is_hard": True,
                }
            ],
            "constraints": [
                {
                    "attribute": "material",
                    "surface": "leather",
                    "canonical": ["leather"],
                    "is_hard": True,
                }
            ],
            "empty": False,
        }
        client = _ScriptedNluClient(
            [
                (first, "I want blue sandals."),
                (second, "Ignore my earlier preference. I want leather sandals instead."),
            ]
        )
        console = nlu_console.NluConsole(
            client, out=io.StringIO(), retriever=self.retriever
        )
        console.apply_mode = "nlu"
        console.mode = "nlu"
        with patch("agent.intent_router.router.classify_override", return_value=False):
            with patch(
                "agent.intent_router.router.classify_route", return_value="buying"
            ):
                console.run_turn("I want blue sandals.")
        self.assertEqual(console.last_exact, {"BLUE_SHOE"})
        with patch("agent.intent_router.router.classify_override", return_value=True):
            with patch("agent.intent_router.router.classify_route") as route:
                console.run_turn(
                    "Ignore my earlier preference. I want leather sandals instead."
                )
                route.assert_not_called()
        self.assertEqual(console.state.intention, "override")
        self.assertTrue(console.last_router["override"])
        self.assertEqual(console.last_router["route_llm"], "skipped")
        self.assertIsNone(console.last_router["pool_before"])
        self.assertEqual(console.last_exact, {"BLUE_SHOE", "PINK_SHOE"})
        self.assertFalse(
            any(slot.attribute == "color" for slot in console.state.typed_constraints)
        )
        top_asins = {row["parent_asin"] for row in console.last_retrieve["top"]}
        self.assertEqual(top_asins, {"BLUE_SHOE", "PINK_SHOE"})
        self.assertTrue(console.last_retrieve["scored_exact"])
        console.handle_command("/pool")
        self.assertIn("BLUE_SHOE", console.out.getvalue())


if __name__ == "__main__":
    unittest.main()
