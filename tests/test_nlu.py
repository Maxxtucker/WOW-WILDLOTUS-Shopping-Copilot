"""Unit tests for span-grounded NLU, hybrid observe, and intention routing.

Live Ollama is never required. Tests pin understand_mode to regex unless they
patch extract_with_llm. Router classification is mocked in Agent tests; hybrid
observe tests commit turn_delta with apply_delta / replace_with_delta.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.intent_router import apply_delta, replace_with_delta
from agent.retrieve.candidates.routing import (
    BROWSING_LIMIT,
    BUYING_LIMIT,
    routing_for,
)
from agent.decide.clarification import NO_ADDITIONAL, eligible_questions
from agent.domain import classify_constraint
from agent.retrieve.candidates.retrieve import retrieve_candidates
from agent.retrieve.candidates.query import rewrite_query
from agent.retrieve.catalog import CatalogRetriever, SearchHit
from agent.retrieve.from_slots import (
    constraint_pairs,
    required_and_budget,
    slot_search_value,
)
from agent.understand.mode import (
    MODE_NLU,
    MODE_REGEX,
    configure_understand,
    reset_understand_mode,
    resolve_understand_mode,
)
from agent.understand.observation.hybrid import (
    NLU_ATTEMPTS,
    extract_from_regex,
    hybrid_extract,
    regex_is_high_confidence,
)
from agent.understand.observation.llm_nlu import (
    OllamaNluClient,
    _loads_json_object,
    _message_text,
    load_nlu_env,
    nlu_enabled,
)
from agent.understand.observation.schema import (
    ObservationExtract,
    parse_observation_payload,
    span_grounded,
)
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState
from agent.understand.state.failsafe import apply_override_failsafe

_LLM_EXTRACT = "agent.understand.observation.hybrid.extract_with_llm"


def _commit(state: SessionState, *, override: bool = False) -> None:
    if override:
        replace_with_delta(state)
    else:
        apply_delta(state)
    apply_override_failsafe(state, state.turn)


def _shoe_product(parent_asin: str, feature: str, sole: str, rating_number: int) -> dict:
    return {
        "parent_asin": parent_asin,
        "title": f"Example {feature} shoe",
        "features": [feature, "100% Leather", sole],
        "description": ["Comfortable walking shoe"],
        "price": 49.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes"],
        "details": {"Department": "mens"},
        "average_rating": 4.5,
        "rating_number": rating_number,
        "store": "Example",
    }


class SpanGroundingTest(unittest.TestCase):
    def test_accepts_raw_and_canonical_spans(self) -> None:
        message = "Need leather shoes, under $100."
        self.assertTrue(span_grounded("leather", message))
        self.assertTrue(span_grounded("under $100", message))
        self.assertFalse(span_grounded("waterproof", message))

    def test_payload_drops_invented_values(self) -> None:
        extract = parse_observation_payload(
            {
                "category": "running shoes",
                "provisional_hint": None,
                "constraints": ["leather", "breathable mesh"],
                "override": False,
                "override_value": None,
                "track": "buying",
                "empty": False,
            },
            "Need leather running shoes.",
        )
        self.assertEqual(extract.category, "running shoes")
        self.assertEqual(extract.constraints, ("leather",))
        self.assertEqual(extract.track, "buying")
        self.assertEqual(extract.source, "llm")

    def test_payload_without_override_keys_still_parses(self) -> None:
        extract = parse_observation_payload(
            {
                "category": "running shoes",
                "constraints": ["leather"],
                "empty": False,
            },
            "Need leather running shoes.",
        )
        self.assertFalse(extract.override)
        self.assertIsNone(extract.override_value)
        self.assertEqual(extract.constraints, ("leather",))

    def test_inspect_returns_raw_json_and_grounded_extract(self) -> None:
        client = OllamaNluClient()
        payload = {
            "category": "running shoes",
            "provisional_hint": None,
            "constraints": ["leather", "invented mesh"],
            "override": False,
            "override_value": None,
            "track": "buying",
            "empty": False,
        }
        with patch.object(client, "_complete", side_effect=[payload, None]):
            raw, extract = client.inspect("Need leather running shoes.")
        self.assertEqual(raw, payload)
        assert extract is not None
        self.assertEqual(extract.category, "running shoes")
        self.assertEqual(extract.constraints, ("leather",))
        self.assertEqual(extract.repair_rounds, 1)

    def test_empty_flag_writes_nothing(self) -> None:
        extract = parse_observation_payload(
            {"empty": True, "constraints": ["leather"], "track": "buying"},
            "No preference.",
        )
        self.assertTrue(extract.empty)
        self.assertEqual(extract.constraints, ())


class SlotGroundingTest(unittest.TestCase):
    def test_tagged_color_grounds_on_the_right_hand_side(self) -> None:
        extract = parse_observation_payload(
            {
                "category": "running shoes",
                "constraints": ["color=yellow"],
                "override": False,
                "track": "buying",
                "empty": False,
            },
            "I need leather running shoes in yellow.",
        )
        self.assertEqual(extract.constraints, ("yellow",))
        self.assertEqual(extract.slots[0].attribute, "color")
        self.assertEqual(extract.slots[0].canonical, ("yellow",))

    def test_navy_maps_to_blue_but_stores_navy_surface(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "navy",
                        "canonical": "blue",
                    }
                ],
                "track": "buying",
            },
            "A navy dress for the wedding.",
        )
        self.assertEqual(extract.constraints, ("navy",))
        self.assertEqual(extract.slots[0].canonical, ("blue",))
        self.assertEqual(extract.slots[0].surface, "navy")

    def test_navy_without_canonical_is_not_auto_mapped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "color", "surface": "navy"}
                ],
                "track": "buying",
            },
            "A navy dress for the wedding.",
        )
        self.assertTrue(extract.empty)
        self.assertEqual(extract.constraints, ())

    def test_cowhide_without_canonical_is_not_auto_mapped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "material", "surface": "cowhide"}
                ],
                "track": "buying",
            },
            "Need cowhide boots.",
        )
        self.assertTrue(extract.empty)

    def test_grey_spelling_normalizes_to_gray(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "color", "surface": "grey"}
                ],
                "track": "buying",
            },
            "A grey scarf.",
        )
        self.assertEqual(extract.constraints, ("grey",))
        self.assertEqual(extract.slots[0].canonical, ("gray",))

    def test_invented_black_is_dropped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "color", "surface": "black", "canonical": "black"}
                ],
                "track": "buying",
            },
            "A navy dress for the wedding.",
        )
        self.assertTrue(extract.empty)
        self.assertEqual(extract.constraints, ())

    def test_budget_amount_grounds_from_digits(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "budget",
                        "surface": "budget<1000",
                        "amount": 1000,
                        "op": "lte",
                    }
                ],
                "track": "buying",
            },
            "Keep it under 1000 dollars.",
        )
        self.assertEqual(extract.slots[0].attribute, "budget")
        self.assertEqual(extract.slots[0].amount, 1000.0)
        self.assertEqual(extract.slots[0].op, "lte")
        self.assertEqual(extract.constraints, ("1000",))

    def test_object_color_yellow_grounds(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "yellow",
                        "canonical": "yellow",
                    }
                ],
                "track": "buying",
            },
            "better be in yellow and under 1000 dollars",
        )
        self.assertEqual(extract.constraints, ("yellow",))
        self.assertEqual(extract.slots[0].canonical, ("yellow",))

    def test_us_shoe_size_keeps_original_surface(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "US 10",
                        "amount": 10,
                        "op": "eq",
                        "kind": "shoe",
                    }
                ],
                "track": "buying",
            },
            "I wear US 10 running shoes.",
        )
        self.assertEqual(extract.constraints, ("US 10",))
        self.assertEqual(extract.slots[0].attribute, "size")
        self.assertEqual(extract.slots[0].surface, "US 10")
        self.assertIsNone(extract.slots[0].canonical)
        self.assertEqual(extract.slots[0].amount, 10.0)
        self.assertEqual(extract.slots[0].op, "eq")
        self.assertEqual(extract.slots[0].system, "us")
        self.assertEqual(extract.slots[0].kind, "shoe")

    def test_uk_size_sets_uk_system(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "UK 8",
                        "amount": 8,
                        "system": "uk",
                        "kind": "shoe",
                    }
                ],
                "track": "buying",
            },
            "I wear UK 8 boots.",
        )
        self.assertEqual(extract.slots[0].system, "uk")
        self.assertEqual(extract.slots[0].amount, 8.0)
        self.assertEqual(extract.slots[0].kind, "shoe")

    def test_eur_size_normalizes_to_eu(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "EUR 40",
                        "amount": 40,
                        "system": "eur",
                        "kind": "shoe",
                    }
                ],
                "track": "buying",
            },
            "Need EUR 40 sandals.",
        )
        self.assertEqual(extract.slots[0].system, "eu")
        self.assertEqual(extract.slots[0].kind, "shoe")

    def test_digits_only_size_reads_system_from_message(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "10",
                        "amount": 10,
                        "kind": "shoe",
                    }
                ],
                "track": "buying",
            },
            "I wear US 10 running shoes.",
        )
        self.assertEqual(extract.slots[0].surface, "10")
        self.assertEqual(extract.slots[0].system, "us")
        self.assertEqual(extract.slots[0].kind, "shoe")

    def test_system_after_the_number_still_counts(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "10",
                        "amount": 10,
                        "kind": "shoe",
                    }
                ],
                "track": "buying",
            },
            "I wear size 10 US running shoes.",
        )
        self.assertEqual(extract.slots[0].system, "us")
        self.assertEqual(extract.slots[0].kind, "shoe")

    def test_invented_size_system_is_dropped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "10",
                        "amount": 10,
                        "system": "us",
                    }
                ],
                "track": "buying",
            },
            "I wear size 10.",
        )
        self.assertEqual(extract.slots[0].surface, "10")
        self.assertEqual(extract.slots[0].amount, 10.0)
        self.assertIsNone(extract.slots[0].system)
        self.assertIsNone(extract.slots[0].kind)

    def test_ambiguous_us_uk_conversion_leaves_system_empty(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "US 11 / UK 10",
                        "amount": 11,
                    }
                ],
                "track": "buying",
            },
            "Do you have US 11 / UK 10?",
        )
        self.assertEqual(extract.slots[0].surface, "US 11 / UK 10")
        self.assertIsNone(extract.slots[0].system)
        self.assertIsNone(extract.slots[0].kind)

    def test_letter_size_maps_to_apparel_canonical(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [{"attribute": "size", "surface": "XL", "kind": "apparel"}],
                "track": "buying",
            },
            "Need an XL hoodie.",
        )
        self.assertEqual(extract.slots[0].surface, "XL")
        self.assertEqual(extract.slots[0].canonical, ("xl",))
        self.assertEqual(extract.slots[0].kind, "apparel")
        self.assertIsNone(extract.slots[0].amount)
        self.assertIsNone(extract.slots[0].system)

    def test_two_xl_does_not_keep_a_numeric_amount(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "2XL",
                        "kind": "apparel",
                        "canonical": "2xl",
                    }
                ],
                "track": "buying",
            },
            "Need a 2XL hoodie.",
        )
        self.assertEqual(extract.slots[0].canonical, ("xxl",))
        self.assertEqual(extract.slots[0].kind, "apparel")
        self.assertIsNone(extract.slots[0].amount)

    def test_dress_us_size_is_apparel_not_shoe(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "US 4",
                        "amount": 4,
                        "kind": "apparel",
                    }
                ],
                "track": "buying",
            },
            "A US 4 dress for the wedding.",
        )
        self.assertEqual(extract.slots[0].kind, "apparel")
        self.assertEqual(extract.slots[0].system, "us")
        self.assertEqual(extract.slots[0].amount, 4.0)
        self.assertIsNone(extract.slots[0].canonical)

    def test_object_dimensions_use_length_width_unit(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "size", "surface": "3 x 3 inches"}
                ],
                "track": "buying",
            },
            "Need a 3 x 3 inches patch.",
        )
        slot = extract.slots[0]
        self.assertEqual(slot.kind, "dimension")
        self.assertEqual(slot.unit, "in")
        self.assertEqual(slot.length, 3.0)
        self.assertEqual(slot.width, 3.0)
        self.assertIsNone(slot.height)
        self.assertIsNone(slot.system)
        self.assertIsNone(slot.canonical)

    def test_cm_maps_to_mm_and_converts_amount(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "21 cm",
                        "length": 21,
                        "unit": "mm",
                    }
                ],
                "track": "buying",
            },
            "Need a 21 cm bracelet.",
        )
        slot = extract.slots[0]
        self.assertEqual(slot.surface, "21 cm")
        self.assertEqual(slot.kind, "dimension")
        self.assertEqual(slot.unit, "mm")
        self.assertEqual(slot.length, 210.0)
        self.assertEqual(slot.amount, 210.0)

    def test_converted_mm_amount_is_not_span_checked(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "21 cm",
                        "length": 210,
                        "unit": "mm",
                    }
                ],
                "track": "buying",
            },
            "Need a 21 cm bracelet.",
        )
        slot = extract.slots[0]
        self.assertEqual(slot.surface, "21 cm")
        self.assertEqual(slot.unit, "mm")
        self.assertEqual(slot.length, 210.0)

    def test_size_phrase_without_number_still_grounds(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "extra small",
                        "kind": "apparel",
                        "canonical": "xs",
                    }
                ],
                "track": "buying",
            },
            "Do you have this in extra small?",
        )
        self.assertEqual(extract.constraints, ("extra small",))
        self.assertEqual(extract.slots[0].canonical, ("xs",))
        self.assertEqual(extract.slots[0].kind, "apparel")

    def test_extra_small_without_canonical_is_not_auto_mapped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "size", "surface": "extra small", "kind": "apparel"}
                ],
                "track": "buying",
            },
            "Do you have this in extra small?",
        )
        self.assertEqual(extract.slots[0].surface, "extra small")
        self.assertEqual(extract.slots[0].kind, "apparel")
        self.assertIsNone(extract.slots[0].canonical)

    def test_kind_is_not_inferred_from_product_words(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [{"attribute": "size", "surface": "US 10", "amount": 10}],
                "track": "buying",
            },
            "I wear US 10 running shoes.",
        )
        self.assertEqual(extract.slots[0].system, "us")
        self.assertIsNone(extract.slots[0].kind)

    def test_model_kind_alias_shoes_folds_to_shoe(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "size",
                        "surface": "US 10",
                        "amount": 10,
                        "kind": "shoes",
                    }
                ],
                "track": "buying",
            },
            "I wear US 10 running shoes.",
        )
        self.assertEqual(extract.slots[0].kind, "shoe")


class RepairLoopTest(unittest.TestCase):
    def test_repair_merges_grounded_retry(self) -> None:
        client = OllamaNluClient()
        first = {
            "category": "dress",
            "constraints": [
                {"attribute": "color", "surface": "black", "canonical": "black"}
            ],
            "override": False,
            "track": "buying",
            "empty": False,
        }
        repair = {
            "constraints": [
                {"attribute": "color", "surface": "yellow", "canonical": "yellow"}
            ]
        }
        message = "I want a yellow dress."
        with patch.object(client, "_complete", side_effect=[first, repair]) as mocked:
            raw, extract = client.inspect(message)
        self.assertEqual(mocked.call_count, 2)
        assert extract is not None
        self.assertEqual(extract.constraints, ("yellow",))
        self.assertEqual(extract.repair_rounds, 1)
        assert raw is not None
        self.assertEqual(raw["category"], "dress")

    def test_three_failed_repairs_drop_ungrounded_slot(self) -> None:
        client = OllamaNluClient()
        bad = {
            "constraints": [
                {"attribute": "color", "surface": "black", "canonical": "black"}
            ],
            "track": "buying",
        }
        message = "I want a yellow dress."
        with patch.object(client, "_complete", side_effect=[bad, bad, bad, bad]) as mocked:
            _raw, extract = client.inspect(message)
        self.assertEqual(mocked.call_count, 4)
        assert extract is not None
        self.assertTrue(extract.empty)
        self.assertEqual(extract.repair_rounds, 3)


class OllamaParseTest(unittest.TestCase):
    def test_loads_json_object_strips_think_tags(self) -> None:
        raw = '<think>planning</think>{"category": "shoes", "empty": false}'
        self.assertEqual(
            _loads_json_object(raw),
            {"category": "shoes", "empty": False},
        )

    def test_message_text_falls_back_to_thinking_field(self) -> None:
        envelope = {
            "message": {
                "content": "",
                "thinking": '{"category": "dress"}',
            }
        }
        self.assertEqual(_message_text(envelope), '{"category": "dress"}')


class HybridObserveTest(unittest.TestCase):
    def setUp(self) -> None:
        configure_understand(MODE_REGEX)

    def tearDown(self) -> None:
        configure_understand(MODE_REGEX)

    def test_regex_mode_disables_nlu(self) -> None:
        configure_understand(MODE_REGEX)
        self.assertFalse(nlu_enabled())

    def test_nlu_flag_false_resolves_to_regex(self) -> None:
        reset_understand_mode()
        with patch.dict(
            os.environ,
            {"AGENT_NLU_ENABLED": "0", "AGENT_UNDERSTAND_MODE": ""},
        ):
            self.assertEqual(resolve_understand_mode(None), MODE_REGEX)

    def test_load_nlu_env_file_does_not_run_on_import(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".env", delete=False
        )
        handle.write("AGENT_NLU_ENABLED=1\nAGENT_NLU_MODEL=probe-model\n")
        handle.close()
        path = Path(handle.name)
        try:
            reset_understand_mode()
            with patch.dict(
                os.environ,
                {"AGENT_NLU_ENABLED": "0", "AGENT_NLU_MODEL": "", "AGENT_UNDERSTAND_MODE": ""},
            ):
                self.assertEqual(resolve_understand_mode(None), MODE_REGEX)
                loaded = load_nlu_env(path, overwrite=True)
                self.assertEqual(loaded["AGENT_NLU_ENABLED"], "1")
                self.assertEqual(loaded["AGENT_NLU_MODEL"], "probe-model")
                self.assertEqual(resolve_understand_mode(None), MODE_NLU)
        finally:
            path.unlink(missing_ok=True)

    def test_key_requirement_regex_when_nlu_off(self) -> None:
        message = "I'm looking for Men Shoes. A key requirement is: leather."
        self.assertTrue(regex_is_high_confidence(message))
        with patch(_LLM_EXTRACT) as mocked:
            state = SessionState("s", {})
            state.begin_turn(message, 1)
            mocked.assert_not_called()
        _commit(state)
        self.assertEqual(state.category, "Men Shoes")
        self.assertIn("leather", state.active_constraints)
        self.assertIsNone(state.intention)

    def test_regex_new_need_is_constraint_not_override_flag(self) -> None:
        message = "Actually, ignore my earlier preference. What I need is: leather."
        state = SessionState("s", {})
        extract = extract_from_regex(state, message)
        self.assertFalse(extract.override)
        self.assertIsNone(extract.override_value)
        self.assertIn("leather", extract.constraints)
        self.assertTrue(
            any(slot.surface == "leather" and slot.is_hard for slot in extract.slots)
        )

    def test_nlu_runs_on_protocol_phrasing(self) -> None:
        message = "I'm looking for Men Shoes. A key requirement is: leather."

        def fake(_state: SessionState, _message: str) -> ObservationExtract:
            return ObservationExtract(
                category="running shoes",
                constraints=("mesh",),
                source="llm",
            )

        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=fake):
            state = SessionState("s", {})
            state.begin_turn(message, 1)
        _commit(state)
        self.assertEqual(state.category, "running shoes")
        self.assertEqual(state.active_constraints, ["mesh"])

    def test_exploring_writes_category_without_constraints(self) -> None:
        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes, but I'm still exploring.", 1)
        _commit(state)
        self.assertEqual(state.category, "Men Shoes")
        self.assertEqual(state.active_constraints, [])
        self.assertIsNone(state.intention)

    def test_llm_slots_are_stored_on_session(self) -> None:
        def fake(_state: SessionState, _message: str) -> ObservationExtract:
            slot = ConstraintSlot(
                attribute="color",
                surface="navy",
                canonical="blue",
            )
            return ObservationExtract(
                category="dress",
                constraints=("navy",),
                slots=(slot,),
                track="buying",
                source="llm",
            )

        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=fake):
            state = SessionState("s", {})
            state.begin_turn("A navy dress please.", 1)
        _commit(state)
        self.assertEqual(state.active_constraints, ["navy"])
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        self.assertEqual(len(colors), 1)
        self.assertEqual(colors[0].canonical, ("blue",))

    def test_mocked_llm_writes_constraints(self) -> None:
        def fake(_state: SessionState, message: str) -> ObservationExtract:
            return ObservationExtract(
                category="running shoes",
                constraints=("leather",),
                track="buying",
                source="llm",
            )

        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=fake):
            state = SessionState("s", {})
            state.begin_turn("Need leather running shoes I can train in.", 1)
        _commit(state)
        self.assertEqual(state.category, "running shoes")
        self.assertEqual(state.active_constraints, ["leather"])
        self.assertIsNone(state.intention)

    def test_mocked_empty_extract_writes_nothing(self) -> None:
        def fake(_state: SessionState, _message: str) -> ObservationExtract:
            return ObservationExtract(empty=True, source="llm")

        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=fake):
            state = SessionState("s", {})
            state.category = "Men Shoes"
            state.begin_turn("No preference, use your judgment.", 1)
        _commit(state)
        self.assertEqual(state.active_constraints, [])
        self.assertEqual(state.category, "Men Shoes")

    def test_regex_mode_does_not_call_llm(self) -> None:
        with patch(_LLM_EXTRACT) as mocked:
            state = SessionState("s", {})
            extract = hybrid_extract(state, "Need something I can run in.")
            mocked.assert_not_called()
        self.assertEqual(extract.source, "regex")

    def test_three_failed_nlu_attempts_fall_back_to_regex(self) -> None:
        configure_understand(MODE_NLU)
        message = "I'm looking for Men Shoes. A key requirement is: leather."
        with patch(_LLM_EXTRACT, return_value=None) as mocked:
            state = SessionState("s", {})
            extract = hybrid_extract(state, message)
        self.assertEqual(mocked.call_count, NLU_ATTEMPTS)
        self.assertEqual(extract.source, "regex")
        self.assertEqual(extract.category, "Men Shoes")
        self.assertIn("leather", extract.constraints)

    def test_agent_nlu_mode_starts_runtime(self) -> None:
        from agent import Agent

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog_path = Path(temporary.name) / "catalog.jsonl"
        catalog_path.write_text(
            json.dumps(_shoe_product("A", "leather", "Leather sole", 10)) + "\n",
            encoding="utf-8",
        )
        with patch("agent.orchestrator.ensure_llm_runtime") as ensured:
            with patch("agent.orchestrator.warmup_nlu"):
                with patch("agent.orchestrator.load_nlu_env"):
                    agent = Agent(catalog_path, understand_mode="nlu")
        ensured.assert_called_once()
        self.assertEqual(agent.understand_mode, MODE_NLU)

    def test_agent_regex_mode_skips_runtime(self) -> None:
        from agent import Agent

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog_path = Path(temporary.name) / "catalog.jsonl"
        catalog_path.write_text(
            json.dumps(_shoe_product("A", "leather", "Leather sole", 10)) + "\n",
            encoding="utf-8",
        )
        with patch("agent.orchestrator.ensure_llm_runtime") as ensured:
            Agent(catalog_path, understand_mode="regex")
        ensured.assert_not_called()

    def test_llm_override_opens_gate_with_constraints(self) -> None:
        def fake(_state: SessionState, _message: str) -> ObservationExtract:
            return ObservationExtract(
                constraints=("waterproof",),
                source="llm",
            )

        state = SessionState("s", {})
        state.begin_turn("I'm looking for Men Shoes. Prefer an old style.", 1)
        _commit(state)
        self.assertFalse(state.gate_open)
        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=fake):
            state.begin_turn("Waterproof instead of that earlier look.", 2)
        _commit(state, override=True)
        self.assertTrue(state.gate_open)
        self.assertTrue(state.override_seen)
        self.assertIn("waterproof", state.active_constraints)
        self.assertEqual(state.legacy_hints, [])
        self.assertEqual(state.intention, None)


class IntentionRoutingTest(unittest.TestCase):
    def test_buying_is_exact_first_with_tight_cap(self) -> None:
        buying = routing_for("buying")
        self.assertTrue(buying.exact_first)
        self.assertEqual(buying.limit, BUYING_LIMIT)
        self.assertGreater(buying.weights.required, buying.weights.lexical)

    def test_browsing_is_exact_first_with_wide_cap(self) -> None:
        buying = routing_for("buying")
        browsing = routing_for("browsing")
        self.assertTrue(browsing.exact_first)
        self.assertEqual(browsing.limit, BROWSING_LIMIT)
        self.assertGreater(browsing.weights.lexical, buying.weights.lexical)
        self.assertGreater(browsing.weights.missing_required, buying.weights.missing_required)

    def test_retrieve_scores_passed_exact_without_catalog_search(self) -> None:
        hit = SearchHit("A", 1.0, 0.0, 1.0, 0.0, 1.0)
        state = SessionState("s", {})
        state.intention = "browsing"
        retriever = MagicMock()
        retriever.score_candidates.return_value = [hit]
        hits = retrieve_candidates(retriever, state, {"A", "B"})
        retriever.search.assert_not_called()
        retriever.score_candidates.assert_called_once()
        self.assertEqual([item.parent_asin for item in hits], ["A"])

    def test_retrieve_empty_exact_does_not_bm25(self) -> None:
        state = SessionState("s", {})
        state.intention = "buying"
        retriever = MagicMock()
        retriever.score_candidates.return_value = []
        hits = retrieve_candidates(retriever, state, set())
        retriever.search.assert_not_called()
        retriever.score_candidates.assert_called_once()
        self.assertEqual(hits, [])

    def test_override_matches_buying_weights(self) -> None:
        buying = routing_for("buying")
        override = routing_for("override")
        self.assertTrue(override.exact_first)
        self.assertEqual(override.limit, buying.limit)
        self.assertEqual(override.weights, buying.weights)

    def test_unset_intention_keeps_historical_exact_first_cap(self) -> None:
        default = routing_for(None)
        self.assertTrue(default.exact_first)
        self.assertEqual(default.limit, 500)

    def test_retrieve_respects_intention_caps(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog_path = Path(temporary.name) / "catalog.jsonl"
        rows = [
            _shoe_product("A", "leather", "Leather sole", 100),
            _shoe_product("B", "leather", "Rubber sole", 20),
            _shoe_product("C", "cotton", "Synthetic sole", 5),
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        with CatalogRetriever(catalog_path) as retriever:
            buying_state = SessionState("buy", {})
            buying_state.category = "Men Shoes"
            buying_state.active_constraints = ["leather"]
            buying_state.intention = "buying"
            buying_hits = retrieve_candidates(retriever, buying_state)
            self.assertLessEqual(len(buying_hits), BUYING_LIMIT)
            self.assertTrue(buying_hits)

            browsing_state = SessionState("browse", {})
            browsing_state.category = "Men Shoes"
            browsing_state.intention = "browsing"
            browsing_hits = retrieve_candidates(retriever, browsing_state)
            self.assertLessEqual(len(browsing_hits), BROWSING_LIMIT)
            self.assertTrue(browsing_hits)


class TypedRetrievalTest(unittest.TestCase):
    def test_color_paraphrase_retrieves_as_canonical_not_feature(self) -> None:
        surface = "orpiment or saffron hue"
        slot = ConstraintSlot(
            attribute="color",
            surface=surface,
            canonical="orange",
        )
        self.assertEqual(classify_constraint(surface), "feature")
        self.assertEqual(slot_search_value(slot), "orange")

        state = SessionState("s", {})
        state.active_constraints = [surface]
        state.typed_constraints = [slot]
        self.assertEqual(constraint_pairs(state), (("color", "orange"),))
        self.assertFalse(hasattr(state, "retrieval_pairs"))

        required, budget = required_and_budget(state)
        self.assertEqual(required, (("color", ("orange",)),))
        self.assertIsNone(budget)

        query, _tags = rewrite_query(state)
        self.assertIn("orange", query)
        self.assertNotIn("feature", query)

    def test_uk_shoe_size_keeps_system_and_amount(self) -> None:
        slot = ConstraintSlot(
            attribute="size",
            surface="UK size 8.5",
            amount=8.5,
            system="uk",
            kind="shoe",
        )
        self.assertEqual(slot_search_value(slot), "UK 8.5")
        state = SessionState("s", {})
        state.typed_constraints = [slot]
        self.assertEqual(constraint_pairs(state), (("size", "UK 8.5"),))

    def test_budget_slot_becomes_interval_not_required_string(self) -> None:
        slot = ConstraintSlot(
            attribute="budget",
            surface="$1,000",
            amount=1000,
            op="lte",
        )
        state = SessionState("s", {})
        state.typed_constraints = [slot]
        required, budget = required_and_budget(state)
        self.assertEqual(required, ())
        self.assertEqual(budget, (None, 1000.0))

    def test_string_constraints_still_used_without_slots(self) -> None:
        state = SessionState("s", {})
        state.active_constraints = ["leather"]
        self.assertEqual(constraint_pairs(state), (("material", "leather"),))

    def test_typed_color_ranks_orange_product_above_unrelated_feature(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog_path = Path(temporary.name) / "catalog.jsonl"
        rows = [
            {
                "parent_asin": "ORANGE",
                "title": "Orange evening dress",
                "features": ["orange fabric"],
                "description": ["A bright orange party dress"],
                "price": 80.0,
                "categories": ["Clothing, Shoes & Jewelry", "Women", "Dresses"],
                "details": {"Color": "Orange"},
                "average_rating": 4.5,
                "rating_number": 10,
                "store": "Example",
            },
            _shoe_product("LEATHER", "leather", "Leather sole", 100),
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        state = SessionState("s", {})
        state.category = "Dresses"
        state.intention = "buying"
        state.latest_message = "Something in an orpiment or saffron hue"
        state.active_constraints = ["orpiment or saffron hue"]
        state.typed_constraints = [
            ConstraintSlot(
                attribute="color",
                surface="orpiment or saffron hue",
                canonical="orange",
            )
        ]
        with CatalogRetriever(catalog_path) as retriever:
            hits = retrieve_candidates(retriever, state)
        self.assertTrue(hits)
        self.assertEqual(hits[0].parent_asin, "ORANGE")

    def test_known_slot_attribute_is_not_asked_again(self) -> None:
        state = SessionState("s", {})
        state.turn = 1
        state.typed_constraints = [
            ConstraintSlot(attribute="color", surface="navy", canonical="blue")
        ]
        candidates = [
            type("Hit", (), {"parent_asin": "A"})(),
            type("Hit", (), {"parent_asin": "B"})(),
        ]

        def answer(parent_asin: str, attribute: str) -> tuple[str, ...]:
            if attribute == "color":
                return ("red",) if parent_asin == "A" else ("blue",)
            if attribute == "size":
                return ("m",) if parent_asin == "A" else ("l",)
            return NO_ADDITIONAL

        questions = eligible_questions(state, candidates, answer, 10)
        self.assertNotIn("color", questions)
        self.assertIn("size", questions)

    def test_or_colors_rank_orange_without_requiring_all_three(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        catalog_path = Path(temporary.name) / "catalog.jsonl"
        rows = [
            {
                "parent_asin": "ORANGE",
                "title": "Orange evening dress",
                "features": ["orange fabric"],
                "description": ["A bright orange party dress"],
                "price": 80.0,
                "categories": ["Clothing, Shoes & Jewelry", "Women", "Dresses"],
                "details": {"Color": "Orange"},
                "average_rating": 4.5,
                "rating_number": 10,
                "store": "Example",
            },
            _shoe_product("LEATHER", "leather", "Leather sole", 100),
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        state = SessionState("s", {})
        state.category = "Dresses"
        state.intention = "buying"
        state.latest_message = "blue, or orange or pink"
        state.typed_constraints = [
            ConstraintSlot(
                attribute="color",
                surface="blue, or orange or pink",
                canonical=("blue", "orange", "pink"),
            )
        ]
        query, _tags = rewrite_query(state)
        self.assertIn("blue", query)
        self.assertIn("orange", query)
        self.assertIn("pink", query)
        required, _budget = required_and_budget(state)
        self.assertEqual(required, (("color", ("blue", "orange", "pink")),))
        with CatalogRetriever(catalog_path) as retriever:
            hits = retrieve_candidates(retriever, state)
        self.assertTrue(hits)
        self.assertEqual(hits[0].parent_asin, "ORANGE")


class SlotOrListTest(unittest.TestCase):
    def tearDown(self) -> None:
        configure_understand(MODE_REGEX)

    def test_canonical_list_is_or_of_closed_colors(self) -> None:
        message = "I want blue, or orange or pink shoes."
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "blue, or orange or pink",
                        "canonical": ["blue", "orange", "pink"],
                    }
                ],
                "track": "buying",
            },
            message,
        )
        self.assertEqual(len(extract.slots), 3)
        self.assertEqual(
            {slot.canonical for slot in extract.slots},
            {("blue",), ("orange",), ("pink",)},
        )
        self.assertTrue(all(slot.is_hard for slot in extract.slots))

    def test_omitted_is_hard_defaults_true(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "color", "surface": "navy", "canonical": "blue"}
                ]
            },
            "A navy dress for the wedding.",
        )
        self.assertEqual(len(extract.slots), 1)
        self.assertTrue(extract.slots[0].is_hard)

    def test_is_hard_false_is_kept(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "navy",
                        "canonical": "blue",
                        "is_hard": False,
                    }
                ]
            },
            "I might like a navy dress.",
        )
        self.assertEqual(len(extract.slots), 1)
        self.assertFalse(extract.slots[0].is_hard)

    def test_category_list_keeps_hard_and_soft_rows(self) -> None:
        extract = parse_observation_payload(
            {
                "category": [
                    {"surface": "Men Shoes", "is_hard": True},
                    {"surface": "sneakers", "is_hard": False},
                ],
                "constraints": [],
            },
            "I need Men Shoes but sneakers would be nice.",
        )
        categories = [slot for slot in extract.slots if slot.attribute == "category"]
        self.assertEqual(extract.category, "Men Shoes")
        self.assertEqual(
            {(slot.surface, slot.is_hard) for slot in categories},
            {("Men Shoes", True), ("sneakers", False)},
        )

    def test_three_color_objects_stay_separate_rows(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {"attribute": "color", "surface": "blue", "canonical": "blue"},
                    {"attribute": "color", "surface": "orange", "canonical": "orange"},
                    {"attribute": "color", "surface": "pink", "canonical": "pink"},
                ],
                "track": "buying",
            },
            "I want blue, or orange or pink shoes.",
        )
        self.assertEqual(len(extract.slots), 3)
        self.assertEqual(
            {slot.canonical for slot in extract.slots},
            {("blue",), ("orange",), ("pink",)},
        )

    def test_surfaces_list_without_single_surface(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surfaces": ["blue", "orange", "pink"],
                        "canonical": ["blue", "orange", "pink"],
                    }
                ],
                "track": "buying",
            },
            "I want blue, or orange or pink shoes.",
        )
        self.assertEqual(
            {slot.canonical for slot in extract.slots},
            {("blue",), ("orange",), ("pink",)},
        )

    def test_invalid_canonical_in_list_is_dropped(self) -> None:
        extract = parse_observation_payload(
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "blue or chartreuse",
                        "canonical": ["blue", "chartreuse"],
                    }
                ],
                "track": "buying",
            },
            "blue or chartreuse is fine",
        )
        self.assertEqual(extract.slots[0].canonical, ("blue",))

    def test_second_turn_extends_color_list(self) -> None:
        def first(_state: SessionState, _message: str) -> ObservationExtract:
            return ObservationExtract(
                constraints=("blue",),
                slots=(
                    ConstraintSlot(
                        attribute="color", surface="blue", canonical=("blue",)
                    ),
                ),
                track="buying",
                source="llm",
            )

        def second(_state: SessionState, _message: str) -> ObservationExtract:
            return ObservationExtract(
                constraints=("orange",),
                slots=(
                    ConstraintSlot(
                        attribute="color", surface="orange", canonical=("orange",)
                    ),
                ),
                track="buying",
                source="llm",
            )

        configure_understand(MODE_NLU)
        with patch(_LLM_EXTRACT, side_effect=[first(None, ""), second(None, "")]):
            state = SessionState("s", {})
            state.begin_turn("Something blue.", 1)
            _commit(state)
            self.assertEqual(state.typed_constraints[0].canonical, ("blue",))
            state.begin_turn("Orange is also fine.", 2)
        _commit(state)
        colors = [slot for slot in state.typed_constraints if slot.attribute == "color"]
        self.assertEqual(len(colors), 2)
        self.assertEqual(
            {slot.canonical for slot in colors},
            {("blue",), ("orange",)},
        )


if __name__ == "__main__":
    unittest.main()
