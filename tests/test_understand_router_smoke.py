"""End-to-end smoke: observe NLU → turn_delta → intention router → sidecar probe.

Offline tests script Ollama HTTP. Live Ollama is opt-in via AGENT_SMOKE_LIVE=1.
Does not read public_set.jsonl. Shopper sentences only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from agent.intent_router.llm import OVERRIDE_SYSTEM, ROUTE_SYSTEM
from agent.intent_router.probe import probe_exact_pool
from agent.intent_router.router import route_intention
from agent.retrieve.candidates.retrieve import CandidateOrganizer
from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.slots_sidecar import SIDECAR_VERSION, catalog_fingerprint
from agent.retrieve.from_slots import exact_pool_groups
from agent.understand.mode import (
    MODE_NLU,
    MODE_REGEX,
    configure_understand,
    reset_understand_mode,
)
from agent.understand.observation.llm_nlu import (
    _ATTRIBUTE_SYSTEM_PROMPT,
    _CATEGORY_LAYER_PROMPT,
    _COLOR_WORD_PROMPT,
    load_nlu_env,
    nlu_host,
)
from agent.understand.observation.rewrite import rewrite_for_nlu
from agent.understand.state import SessionState

BLUE_SHOE = "BLUE_SHOE"
PINK_SHOE = "PINK_SHOE"
BOOK = "BOOK"
SHOE_TAGS = ("clothing shoe jewelry", "woman", "shoe")
TURN1 = "I'm looking for women's sandals."
TURN2 = "Those sandals in navy, please."
TURN3 = "Ignore my earlier preference. I want leather sandals instead."
_ALLOWED_ID_RE = re.compile(r"^- (\S+)\s+[—–-]\s+")
_LIVE_TRUE = frozenset({"1", "true", "yes", "on"})


def _live_flag() -> bool:
    return os.environ.get("AGENT_SMOKE_LIVE", "").strip().lower() in _LIVE_TRUE


def _reset_llm_clients() -> None:
    import agent.intent_router.llm as router_llm
    import agent.understand.observation.llm_nlu as nlu_mod

    nlu_mod._client = None
    router_llm._client = None


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


def _product(
    parent_asin: str,
    title: str,
    categories: list[str],
    *,
    store: str = "Acme",
) -> dict:
    return {
        "parent_asin": parent_asin,
        "title": title,
        "features": [title],
        "description": [title],
        "price": 49.0,
        "categories": categories,
        "details": {},
        "average_rating": 4.0,
        "rating_number": 10,
        "store": store,
    }


def build_fixture(root: Path) -> tuple[Path, Path, CatalogRetriever]:
    catalog_path = root / "catalog.jsonl"
    products = [
        _product(
            BLUE_SHOE,
            "Blue leather sandals",
            ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
        ),
        _product(
            PINK_SHOE,
            "Pink leather sandals",
            ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
        ),
        _product(BOOK, "Blue cookbook", ["Books"], store="Penguin"),
    ]
    catalog_path.write_text(
        "".join(json.dumps(row) + "\n" for row in products),
        encoding="utf-8",
    )
    slots_path = root / "product_slots.sqlite3"
    rows: list[tuple] = []
    for asin, color in ((BLUE_SHOE, "blue"), (PINK_SHOE, "pink")):
        rows.append((asin, "color", color, color, "title", None))
        rows.append((asin, "material", "leather", "leather", "title", None))
        for tag in SHOE_TAGS:
            rows.append((asin, "category", tag, tag, "categories:tree", None))
    rows.append((BOOK, "color", "blue", "blue", "title", None))
    rows.append((BOOK, "category", "book", "Books", "categories", None))
    _write_sidecar(slots_path, catalog_path, rows)
    retriever = CatalogRetriever(catalog_path, slots_path=slots_path)
    return catalog_path, slots_path, retriever


def _category_canonicals(slots) -> set[str]:
    tags: set[str] = set()
    for slot in slots:
        if slot.attribute == "category" and slot.canonical:
            tags.update(slot.canonical)
    return tags


def _allowed_ids(user: str) -> list[str]:
    found = [match.group(1) for match in _ALLOWED_ID_RE.finditer(user)]
    if found:
        return found
    ids: list[str] = []
    for line in user.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        rest = stripped[2:]
        for sep in (" — ", " – ", " - "):
            if sep in rest:
                ids.append(rest.split(sep, 1)[0].strip())
                break
        else:
            token = rest.split(None, 1)[0].strip()
            if token:
                ids.append(token)
    return ids


def _category_reply(user: str) -> dict:
    allowed = set(_allowed_ids(user))
    for candidate in ("Clothing_Shoes_and_Jewelry", "women", "shoes"):
        if candidate in allowed:
            return {"ids": [candidate], "stop": False}
    return {"ids": [], "stop": True}


def _attribute_reply(user: str) -> dict:
    text = user.casefold()
    if "leather" in text:
        return {
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
    if "blue" in text or "navy" in text:
        return {
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
    return {"constraints": [], "empty": False}


def _override_reply(user: str) -> dict:
    return {"override": "ignore my earlier preference" in user.casefold()}


def _route_reply(user: str) -> dict:
    match = re.search(r"Candidate pool after this turn's delta: (\S+)", user)
    after = match.group(1) if match else "null"
    if after == "1":
        return {"intention": "buying"}
    return {"intention": "browsing"}


def _alias_keep_reply(user: str) -> dict:
    keep: list[str] = []
    for line in user.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or "→" not in stripped:
            continue
        phrase = stripped[2:].split("→", 1)[0].strip()
        if phrase:
            keep.append(phrase)
    return {"keep": keep}


def _kind(system: str, user: str) -> str:
    if system.startswith("You check color alias pairs"):
        return "alias_color"
    if system.startswith("You check material alias pairs"):
        return "alias_material"
    if system.startswith("You assign this shopping message"):
        return "category"
    if system.startswith("You extract this turn's shopping attributes"):
        if user.startswith("The previous JSON failed span checks"):
            return "repair"
        return "attribute"
    if system.startswith("You decide whether this customer message replaces"):
        return "override"
    if system.startswith("You choose buying vs browsing"):
        return "route"
    return "unknown"


@dataclass
class ChatCall:
    kind: str
    system: str
    user: str
    reply: dict


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        envelope = {
            "message": {"content": json.dumps(payload)},
            "prompt_eval_count": 11,
            "eval_count": 7,
        }
        self._raw = json.dumps(envelope).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class OfflineUnderstandRouterSmokeTest(unittest.TestCase):
    """Scripted HTTP. Always runs. Tiny catalog + sidecar, no live Ollama."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        _catalog, _slots, self.retriever = build_fixture(Path(self.temporary.name))
        self.addCleanup(self.retriever.close)
        self.assertTrue(self.retriever._slots_attached)
        self.calls: list[ChatCall] = []
        self._urlopen = patch("urllib.request.urlopen", side_effect=self._fake_urlopen)
        self._urlopen.start()
        self.addCleanup(self._urlopen.stop)
        configure_understand(MODE_NLU)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        _reset_llm_clients()
        self.addCleanup(_reset_llm_clients)

    def _fake_urlopen(self, request: Request, timeout: float | None = None):
        del timeout
        raw = request.data
        if callable(raw):
            raw = raw()
        body = json.loads(bytes(raw).decode("utf-8"))
        messages = body["messages"]
        system = str(messages[0]["content"])
        user = str(messages[1]["content"])
        kind = _kind(system, user)
        if kind == "alias_color":
            reply = _alias_keep_reply(user)
        elif kind == "alias_material":
            reply = _alias_keep_reply(user)
        elif kind == "category":
            reply = _category_reply(user)
        elif kind == "attribute":
            reply = _attribute_reply(user)
        elif kind == "repair":
            reply = {"constraints": [], "empty": False}
        elif kind == "override":
            reply = _override_reply(user)
        elif kind == "route":
            reply = _route_reply(user)
        else:
            raise AssertionError(f"unexpected LLM system prompt: {system[:80]!r}")
        self.calls.append(ChatCall(kind, system, user, reply))
        return _FakeHttpResponse(reply)

    def _kinds(self) -> list[str]:
        return [call.kind for call in self.calls]

    def test_observe_does_not_commit_before_router(self) -> None:
        self.assertIn("blue", rewrite_for_nlu(TURN2))
        self.assertNotIn("navy", rewrite_for_nlu(TURN2))

        state = SessionState("smoke", {})
        state.begin_turn(TURN1, 1)

        delta = state.turn_delta
        self.assertIsNotNone(delta)
        assert delta is not None
        self.assertEqual(delta.source, "llm")
        self.assertFalse(delta.empty)
        self.assertFalse(delta.override)
        self.assertIsNone(delta.track)
        tags = _category_canonicals(delta.slots)
        self.assertIn("woman", tags)
        self.assertTrue(tags & {"shoe", "sandal"})
        self.assertEqual(state.typed_constraints, [])
        self.assertIsNone(state.intention)
        self.assertIsNone(state.category)
        self.assertEqual(
            self._kinds(),
            ["category", "category", "category", "attribute"],
            msg=[(call.kind, call.user[:160]) for call in self.calls],
        )
        self.assertEqual(self.calls[0].system, _CATEGORY_LAYER_PROMPT)
        self.assertEqual(self.calls[3].system, _ATTRIBUTE_SYSTEM_PROMPT)
        self.assertEqual(set(self.calls[3].reply), {"constraints", "empty"})
        self.assertNotIn("override", self.calls[3].reply)
        self.assertNotIn("track", self.calls[3].reply)

    def test_accumulate_browsing_then_buying_then_override(self) -> None:
        state = SessionState("smoke", {})
        organizer = CandidateOrganizer(self.retriever)

        state.begin_turn(TURN1, 1)
        nlu_calls = list(self.calls)
        with patch(
            "agent.intent_router.router.probe_exact_pool",
            wraps=probe_exact_pool,
        ) as probe:
            with patch.object(self.retriever, "search") as search:
                exact = route_intention(state, self.retriever)
                hits = organizer.apply(state, exact)
        search.assert_not_called()
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(exact, {BLUE_SHOE, PINK_SHOE})
        self.assertEqual(state.intention, "browsing")
        self.assertIsNone(state.candidate_count_before_delta)
        self.assertEqual(state.candidate_count, 2)
        self.assertEqual({hit.parent_asin for hit in hits}, {BLUE_SHOE, PINK_SHOE})
        session_tags = _category_canonicals(state.typed_constraints)
        self.assertIn("shoe", session_tags)
        self.assertIn("woman", session_tags)
        groups = dict(exact_pool_groups(state))
        self.assertIn("category", groups)
        route_calls = [call for call in self.calls[len(nlu_calls) :] if call.kind == "route"]
        self.assertEqual(len(route_calls), 1)
        self.assertIn("Candidate pool before this turn's delta: null", route_calls[0].user)
        self.assertIn("Candidate pool after this turn's delta: 2", route_calls[0].user)
        self.assertIn("Ratio after/before: null", route_calls[0].user)
        self.assertGreater(state.router_prompt_tokens, 0)
        self.assertTrue(self.calls[len(nlu_calls)].system.startswith(OVERRIDE_SYSTEM[:40]))
        self.assertTrue(route_calls[0].system.startswith(ROUTE_SYSTEM[:40]))

        self.calls.clear()
        state.begin_turn(TURN2, 2)
        self.assertEqual(
            self._kinds(),
            ["alias_color", "category", "category", "attribute"],
        )
        self.assertEqual(self.calls[0].system, _COLOR_WORD_PROMPT)
        self.assertIsNotNone(state.turn_delta)
        assert state.turn_delta is not None
        colors_in_delta = [
            slot for slot in state.turn_delta.slots if slot.attribute == "color"
        ]
        self.assertEqual(len(colors_in_delta), 1)
        self.assertEqual(colors_in_delta[0].canonical, ("blue",))
        self.assertTrue(colors_in_delta[0].is_hard)
        prior_colors = [
            slot for slot in state.typed_constraints if slot.attribute == "color"
        ]
        self.assertEqual(prior_colors, [])
        with patch.object(self.retriever, "search") as search:
            exact = route_intention(state, self.retriever)
            hits = organizer.apply(state, exact)
        search.assert_not_called()
        self.assertEqual(exact, {BLUE_SHOE})
        self.assertEqual(state.intention, "buying")
        self.assertEqual(state.candidate_count_before_delta, 2)
        self.assertEqual(state.candidate_count, 1)
        self.assertEqual([hit.parent_asin for hit in hits], [BLUE_SHOE])
        self.assertIn("shoe", _category_canonicals(state.typed_constraints))
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        self.assertEqual(len(colors), 1)
        self.assertEqual(colors[0].canonical, ("blue",))
        route_calls = [call for call in self.calls if call.kind == "route"]
        self.assertEqual(len(route_calls), 1)
        self.assertIn("Candidate pool before this turn's delta: 2", route_calls[0].user)
        self.assertIn("Candidate pool after this turn's delta: 1", route_calls[0].user)
        self.assertIn("Ratio after/before: 0.5", route_calls[0].user)

        self.calls.clear()
        state.begin_turn(TURN3, 3)
        with patch(
            "agent.intent_router.router.probe_exact_pool",
            wraps=probe_exact_pool,
        ) as probe:
            with patch.object(self.retriever, "search") as search:
                exact = route_intention(state, self.retriever)
                hits = organizer.apply(state, exact)
        search.assert_not_called()
        self.assertEqual(probe.call_count, 1)
        self.assertNotIn("route", self._kinds())
        self.assertEqual(self._kinds().count("override"), 1)
        self.assertEqual(state.intention, "override")
        self.assertTrue(state.gate_open)
        self.assertIsNone(state.candidate_count_before_delta)
        self.assertEqual(exact, {BLUE_SHOE, PINK_SHOE})
        self.assertEqual({hit.parent_asin for hit in hits}, {BLUE_SHOE, PINK_SHOE})
        self.assertFalse(
            any(slot.attribute == "color" for slot in state.typed_constraints)
        )
        materials = [
            slot for slot in state.typed_constraints if slot.attribute == "material"
        ]
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0].canonical, ("leather",))

    def test_regex_mode_does_not_call_nlu_http(self) -> None:
        configure_understand(MODE_REGEX)
        _reset_llm_clients()
        state = SessionState("regex-smoke", {})
        state.begin_turn(TURN1, 1)
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(state.turn_delta)
        assert state.turn_delta is not None
        self.assertEqual(state.turn_delta.source, "regex")


@unittest.skipUnless(
    _live_flag(),
    "set AGENT_SMOKE_LIVE=1 to hit local Ollama",
)
class LiveUnderstandRouterSmokeTest(unittest.TestCase):
    """Real Ollama. Fails when the flag is set but GET /api/tags does not succeed."""

    @classmethod
    def setUpClass(cls) -> None:
        load_nlu_env()
        from agent.understand.observation.runtime import ollama_reachable

        if not ollama_reachable():
            raise AssertionError(
                "AGENT_SMOKE_LIVE=1 but Ollama GET /api/tags failed at "
                f"{nlu_host()}"
            )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        _catalog, _slots, self.retriever = build_fixture(Path(self.temporary.name))
        self.addCleanup(self.retriever.close)
        configure_understand(MODE_NLU)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        _reset_llm_clients()
        self.addCleanup(_reset_llm_clients)

    def test_live_observe_routes_and_probes(self) -> None:
        state = SessionState("live-smoke", {})
        organizer = CandidateOrganizer(self.retriever)
        state.begin_turn("I'm looking for women's sandals.", 1)
        delta = state.turn_delta
        self.assertIsNotNone(delta)
        assert delta is not None
        self.assertEqual(delta.source, "llm")
        self.assertEqual(state.typed_constraints, [])
        self.assertIsNone(state.intention)
        exact = route_intention(state, self.retriever)
        self.assertIn(state.intention, {"buying", "browsing", "override"})
        hits = organizer.apply(state, exact)
        if exact is not None:
            self.assertTrue({hit.parent_asin for hit in hits} <= exact)
        state.begin_turn(
            "Ignore my earlier preference. I want leather sandals instead.",
            2,
        )
        self.assertIsNotNone(state.turn_delta)
        assert state.turn_delta is not None
        self.assertEqual(state.turn_delta.source, "llm")
        exact = route_intention(state, self.retriever)
        self.assertIn(state.intention, {"buying", "browsing", "override"})
        organizer.apply(state, exact)


if __name__ == "__main__":
    unittest.main()
