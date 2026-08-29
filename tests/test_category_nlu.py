"""Category tree, alias rewrite, and split category/attribute NLU.

Live Ollama is never required. Layered classify tests mock HTTP JSON.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.intent_router.writeback import apply_delta
from agent.retrieve.from_slots import uses_search_aliases
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.category_merch import is_merchandising_label
from agent.understand.observation.category_scope import (
    filter_layer_decision,
    node_adds_unstated_audience,
)
from agent.understand.observation.category_tree import (
    CategoryLayerDecision,
    CategoryNode,
    load_category_tree,
    tree_depth,
    walk_category_tree,
)
from agent.understand.observation.coordinator import observe
from agent.understand.observation.llm_nlu import OllamaNluClient, _CATEGORY_LAYER_PROMPT
from agent.understand.observation.rewrite import AliasHit, merge_alias_hits, rewrite_for_nlu
from agent.understand.observation.schema import parse_observation_payload
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TREE_PATH = ROOT / "scripts" / "catalog_preprocess" / "aliases" / "category_tree.json"
PARENTS_PATH = ROOT / "scripts" / "catalog_preprocess" / "aliases" / "category_parents.json"


def _all_tree_tags(nodes: tuple[CategoryNode, ...]) -> set[str]:
    tags: set[str] = set()
    for node in nodes:
        tags.update(node.catalog_tags)
        tags.update(_all_tree_tags(node.children))
    return tags


def _classify_running_shoes(
    message: str,
    parent: CategoryNode | None,
    children: tuple[CategoryNode, ...],
) -> CategoryLayerDecision:
    del message, parent
    ids = {node.id for node in children}
    if "Clothing_Shoes_and_Jewelry" in ids:
        return CategoryLayerDecision(("Clothing_Shoes_and_Jewelry",), False)
    if "women" in ids:
        return CategoryLayerDecision(("women",), False)
    if "shoes" in ids:
        return CategoryLayerDecision(("shoes",), False)
    return CategoryLayerDecision((), True)


class MerchLabelTest(unittest.TestCase):
    def test_promo_shelves_are_merch(self) -> None:
        for label in (
            "20% Off Prime Members Exclusive | Men",
            "Amazon Fashion Sales & Deals",
            "$50 and Under Backpacks",
            "4+ Stars: Clothes, Shoes and Jewelry",
            "Amazon Fashion 3",
        ):
            self.assertTrue(is_merchandising_label(label), label)

    def test_product_types_are_not_merch(self) -> None:
        for label in ("Women", "Shoes", "Running", "Team sports"):
            self.assertFalse(is_merchandising_label(label), label)


class CategoryScopeTest(unittest.TestCase):
    def test_prompt_allows_empty_and_forbids_narrower_children(self) -> None:
        self.assertIn("Empty ids is allowed", _CATEGORY_LAYER_PROMPT)
        self.assertIn("broader than or equal", _CATEGORY_LAYER_PROMPT)
        self.assertIn("Kids Shoes", _CATEGORY_LAYER_PROMPT)

    def test_kids_shoes_is_narrower_than_running_shoes(self) -> None:
        kids = CategoryNode("kids_shoes", "Kids Shoes", ("kids shoe",))
        shoes = CategoryNode("shoes", "Shoes", ("shoe",))
        self.assertTrue(
            node_adds_unstated_audience("I want running shoes.", kids)
        )
        self.assertFalse(
            node_adds_unstated_audience("I want running shoes.", shoes)
        )
        filtered = filter_layer_decision(
            "I want running shoes.",
            (kids, shoes),
            CategoryLayerDecision(("kids_shoes", "shoes"), False),
        )
        self.assertEqual(filtered.ids, ("shoes",))
        self.assertFalse(filtered.stop)

    def test_women_is_kept_when_the_message_names_women(self) -> None:
        women = CategoryNode("women", "Women", ("woman",))
        self.assertFalse(
            node_adds_unstated_audience("I'm looking for women's sandals.", women)
        )
        filtered = filter_layer_decision(
            "I'm looking for women's sandals.",
            (women,),
            CategoryLayerDecision(("women",), False),
        )
        self.assertEqual(filtered.ids, ("women",))

    def test_department_roots_are_not_audience_filtered(self) -> None:
        roots = load_category_tree()
        filtered = filter_layer_decision(
            "I want running shoes.",
            roots,
            CategoryLayerDecision(("Baby_Products",), False),
        )
        self.assertEqual(filtered.ids, ("Baby_Products",))


class CategoryTreeFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roots = load_category_tree()

    def test_depth_is_at_most_three(self) -> None:
        self.assertLessEqual(tree_depth(self.roots), 3)
        payload = json.loads(TREE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("max_depth"), 3)

    def test_high_frequency_types_have_catalog_tags(self) -> None:
        tags = _all_tree_tags(self.roots)
        for needle in ("shoe", "sandal", "dress"):
            self.assertIn(needle, tags)

    def test_amazon_roots_include_unknown(self) -> None:
        ids = {node.id for node in self.roots}
        self.assertIn("Clothing_Shoes_and_Jewelry", ids)
        self.assertIn("Unknown", ids)

    def test_child_fold_differs_from_parent(self) -> None:
        from catalog_preprocess.text import fold_category

        def walk(node: CategoryNode, parent_fold: str | None) -> None:
            folded = fold_category(node.label)
            if parent_fold and folded and folded == parent_fold:
                self.fail(f"redundant child {node.id!r} under fold {parent_fold!r}")
            for child in node.children:
                walk(child, folded)

        for root in self.roots:
            walk(root, None)

    def test_every_catalog_category_is_in_the_tree(self) -> None:
        catalog = ROOT / "data" / "catalog.jsonl"
        if not catalog.is_file():
            self.skipTest("data/catalog.jsonl is not present")
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from catalog_preprocess.text import categories_list, fold_category

        catalog_tags: set[str] = set()
        with catalog.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                for label in categories_list(row):
                    folded = fold_category(label)
                    if folded:
                        catalog_tags.add(folded)
        from build_category_tree import merchandising_catalog_folds

        missing = catalog_tags - _all_tree_tags(self.roots) - merchandising_catalog_folds()
        self.assertFalse(
            missing,
            f"{len(missing)} catalog categories missing, e.g. {sorted(missing)[:12]}",
        )

    def test_csj_children_are_product_types_not_promo(self) -> None:
        csj = next(
            node for node in self.roots if node.id == "Clothing_Shoes_and_Jewelry"
        )
        child_ids = {child.id for child in csj.children}
        child_labels = {child.label for child in csj.children}
        self.assertIn("women", child_ids)
        self.assertNotIn("c_20_off_prime_members_exclusive_men", child_ids)
        self.assertNotIn("amazon_fashion_sales_deals", child_ids)
        self.assertNotIn("20% Off Prime Members Exclusive | Men", child_labels)
        self.assertNotIn("Amazon Fashion Sales & Deals", child_labels)
        for child in csj.children:
            self.assertFalse(
                is_merchandising_label(child.label),
                child.label,
            )


class CategoryParentsFileTest(unittest.TestCase):
    def setUp(self) -> None:
        if not PARENTS_PATH.is_file():
            self.skipTest("category_parents.json is not present")
        from catalog_preprocess.category_parents import load_category_parents

        self.index = load_category_parents(PARENTS_PATH)

    def test_unique_child_maps_to_parent(self) -> None:
        from catalog_preprocess.category_parents import parent_of

        self.assertEqual(parent_of("flip flops", self.index), "shoe")
        self.assertEqual(parent_of("necklaces", self.index), "jewelry")
        self.assertIsNone(parent_of("shoes", self.index))
        self.assertIsNone(parent_of("sandals", self.index))
        self.assertGreaterEqual(len(self.index["homes"].get("shoe") or []), 2)
        self.assertGreaterEqual(len(self.index["homes"].get("sandal") or []), 2)

    def test_path_picks_department_home(self) -> None:
        from catalog_preprocess.category_parents import layers_for_path

        self.assertEqual(
            layers_for_path(
                ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Sandals"],
                self.index,
            ),
            ("clothing shoe jewelry", "woman", "shoe"),
        )
        self.assertEqual(
            layers_for_path(
                ["Clothing, Shoes & Jewelry", "Boys", "School Uniforms", "Shoes"],
                self.index,
            ),
            ("clothing shoe jewelry", "boys", "school uniform"),
        )

    def test_catalog_nodes_are_in_parent_or_homes(self) -> None:
        catalog = ROOT / "data" / "catalog.jsonl"
        if not catalog.is_file():
            self.skipTest("data/catalog.jsonl is not present")
        from catalog_preprocess.text import categories_list, fold_category

        keys = set(self.index.get("parent") or {}) | set(self.index.get("homes") or {})
        missing: set[str] = set()
        with catalog.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                for label in categories_list(row):
                    folded = fold_category(label)
                    if folded and folded not in keys:
                        missing.add(folded)
        from build_category_tree import merchandising_catalog_folds

        missing -= merchandising_catalog_folds()
        self.assertFalse(
            missing,
            f"{len(missing)} catalog categories missing from parent map, "
            f"e.g. {sorted(missing)[:12]}",
        )


class CategoryWalkTest(unittest.TestCase):
    def test_running_shoes_records_three_path_layers(self) -> None:
        picks = walk_category_tree("running shoes", classify=_classify_running_shoes)
        self.assertEqual(
            tuple(node.id for node in picks),
            ("Clothing_Shoes_and_Jewelry", "women", "shoes"),
        )
        self.assertLessEqual(len(picks), 3)
        tags = {tag for node in picks for tag in node.catalog_tags}
        self.assertIn("clothing shoe jewelry", tags)
        self.assertIn("woman", tags)
        self.assertTrue(tags & {"shoe", "running", "athletic", "sandal"})

    def test_fanout_caps_ids_per_layer(self) -> None:
        def classify(
            message: str,
            parent: CategoryNode | None,
            children: tuple[CategoryNode, ...],
        ) -> CategoryLayerDecision:
            del message, parent
            return CategoryLayerDecision(tuple(node.id for node in children[:5]), False)

        picks = walk_category_tree("x", classify=classify, max_fanout=3, max_depth=1)
        self.assertLessEqual(len(picks), 3)

    def test_layer_failure_returns_empty_on_l1(self) -> None:
        picks = walk_category_tree("running shoes", classify=lambda *_args: None)
        self.assertEqual(picks, ())

    def test_committed_tree_is_fold_pruned_and_shoes_is_a_leaf(self) -> None:
        from catalog_preprocess.text import fold_category

        roots = load_category_tree()
        csj = next(node for node in roots if node.id == "Clothing_Shoes_and_Jewelry")
        women = next(node for node in csj.children if node.id == "women")
        shoes = next(node for node in women.children if node.id == "shoes")
        self.assertFalse(shoes.has_children)
        self.assertNotEqual(fold_category(women.label), fold_category(shoes.label))
        for child in women.children:
            self.assertNotEqual(fold_category(child.label), fold_category(women.label))

    def test_leaf_does_not_start_another_classify_round(self) -> None:
        leaf_l2 = CategoryNode("promo", "Promo", ("promo",))
        leaf_l3 = CategoryNode("shoes", "Shoes", ("shoe",))
        women = CategoryNode("women", "Women", ("woman",), (leaf_l3,))
        root = CategoryNode("csj", "CSJ", ("clothing shoe jewelry",), (leaf_l2, women))
        calls: list[str] = []

        def classify(
            message: str,
            parent: CategoryNode | None,
            children: tuple[CategoryNode, ...],
        ) -> CategoryLayerDecision:
            del message
            calls.append(parent.id if parent else "L1")
            ids = {node.id for node in children}
            if "csj" in ids:
                return CategoryLayerDecision(("csj",), False)
            if "promo" in ids:
                return CategoryLayerDecision(("promo",), False)
            if "women" in ids:
                return CategoryLayerDecision(("women",), False)
            if "shoes" in ids:
                return CategoryLayerDecision(("shoes",), False)
            return CategoryLayerDecision((), True)

        walk_category_tree("x", classify=classify, roots=(root,), max_depth=3)
        self.assertEqual(len(calls), 2)

        calls.clear()

        def classify_to_shoes(
            message: str,
            parent: CategoryNode | None,
            children: tuple[CategoryNode, ...],
        ) -> CategoryLayerDecision:
            del message
            calls.append(parent.id if parent else "L1")
            ids = {node.id for node in children}
            if "csj" in ids:
                return CategoryLayerDecision(("csj",), False)
            if "women" in ids:
                return CategoryLayerDecision(("women",), False)
            if "shoes" in ids:
                return CategoryLayerDecision(("shoes",), False)
            return CategoryLayerDecision((), True)

        picks = walk_category_tree(
            "x", classify=classify_to_shoes, roots=(root,), max_depth=3
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(tuple(node.id for node in picks), ("csj", "women", "shoes"))

    def test_layer_concatenates_children_of_all_selected_parents(self) -> None:
        seen: list[tuple[str, ...]] = []

        def classify(
            message: str,
            parent: CategoryNode | None,
            children: tuple[CategoryNode, ...],
        ) -> CategoryLayerDecision:
            del message, parent
            seen.append(tuple(node.id for node in children))
            ids = {node.id for node in children}
            if "dept_a" in ids:
                return CategoryLayerDecision(("dept_a", "dept_b"), False)
            return CategoryLayerDecision(tuple(node.id for node in children), True)

        roots = (
            CategoryNode(
                "dept_a",
                "A",
                children=(CategoryNode("child_a", "Child A"),),
            ),
            CategoryNode(
                "dept_b",
                "B",
                children=(CategoryNode("child_b", "Child B"),),
            ),
        )
        picks = walk_category_tree("x", classify=classify, roots=roots, max_depth=2)
        self.assertEqual(seen[0], ("dept_a", "dept_b"))
        self.assertEqual(set(seen[1]), {"child_a", "child_b"})
        self.assertEqual(
            {node.id for node in picks},
            {"dept_a", "dept_b", "child_a", "child_b"},
        )


class AliasRewriteTest(unittest.TestCase):
    def test_orpiment_orange_becomes_orange(self) -> None:
        rewritten = rewrite_for_nlu("Need orpiment orange sandals.")
        self.assertIn("orange", rewritten)
        self.assertNotIn("orpiment", rewritten)

    def test_navy_becomes_blue(self) -> None:
        rewritten = rewrite_for_nlu("A navy dress.")
        self.assertIn("blue", rewritten)
        self.assertNotIn("navy", rewritten)

    def test_lycra_becomes_spandex(self) -> None:
        rewritten = rewrite_for_nlu("lycra leggings")
        self.assertIn("spandex", rewritten)
        self.assertNotIn("lycra", rewritten)

    def test_gold_necklace_is_not_rewritten_to_yellow(self) -> None:
        rewritten = rewrite_for_nlu("gold necklace")
        self.assertIn("gold", rewritten)
        self.assertNotIn("yellow", rewritten)
        self.assertIn("necklace", rewritten)

    def test_same_span_concatenates_color_then_material(self) -> None:
        merged = merge_alias_hits(
            (AliasHit(0, 1, "cordovan", "brown"),),
            (AliasHit(0, 1, "cordovan", "leather"),),
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].replacement, "brown leather")

    def test_rewrite_concatenates_when_both_maps_keep(self) -> None:
        with (
            patch(
                "agent.understand.observation.rewrite._load_color_mapping",
                return_value=({"cordovan": "brown"}, 1),
            ),
            patch(
                "agent.understand.observation.rewrite._load_material_mapping",
                return_value=({"cordovan": "leather"}, 1),
            ),
        ):
            rewritten = rewrite_for_nlu("cordovan shoes")
        self.assertEqual(rewritten, "brown leather shoes")

    def test_material_drop_keeps_color_only(self) -> None:
        with (
            patch(
                "agent.understand.observation.rewrite._load_color_mapping",
                return_value=({"cordovan": "brown"}, 1),
            ),
            patch(
                "agent.understand.observation.rewrite._load_material_mapping",
                return_value=({"cordovan": "leather"}, 1),
            ),
        ):
            rewritten = rewrite_for_nlu(
                "cordovan shoes",
                verify_color=list,
                verify_material=lambda _hits: (),
            )
        self.assertEqual(rewritten, "brown shoes")

    def test_color_gate_drops_source_that_is_not_a_color_word(self) -> None:
        with (
            patch(
                "agent.understand.observation.rewrite._load_color_mapping",
                return_value=({"off": "white", "orpiment": "orange"}, 1),
            ),
            patch(
                "agent.understand.observation.rewrite._load_material_mapping",
                return_value=({}, 1),
            ),
        ):
            rewritten = rewrite_for_nlu(
                "off orpiment jacket",
                verify_color=lambda hits: [hit for hit in hits if hit.phrase != "off"],
            )
        self.assertIn("off", rewritten)
        self.assertNotIn("white", rewritten)
        self.assertIn("orange", rewritten)
        self.assertNotIn("orpiment", rewritten)


class SplitNluTest(unittest.TestCase):
    def test_category_surface_cites_shopper_span(self) -> None:
        extract = parse_observation_payload(
            {
                "category": [
                    {
                        "surface": "Athletic shoes",
                        "canonical": ["shoes", "running"],
                        "is_hard": True,
                    }
                ],
                "constraints": [],
                "empty": False,
            },
            "I want running shoes.",
        )
        categories = [slot for slot in extract.slots if slot.attribute == "category"]
        self.assertEqual(len(categories), 2)
        self.assertTrue(all("run" in slot.surface or "shoe" in slot.surface for slot in categories))
        tags = {slot.canonical[0] for slot in categories if slot.canonical}
        self.assertEqual(tags, {"shoes", "running"})

    def test_uncited_category_row_is_dropped(self) -> None:
        extract = parse_observation_payload(
            {
                "category": [
                    {
                        "surface": "Boys Sneakers (no fs)",
                        "canonical": ["boys sneaker no fs"],
                        "is_hard": True,
                    }
                ],
                "empty": False,
            },
            "I want running shoes.",
        )
        self.assertTrue(extract.empty)
        self.assertFalse(any(slot.attribute == "category" for slot in extract.slots))

    def test_empty_tag_leaf_without_cite_is_dropped(self) -> None:
        extract = parse_observation_payload(
            {
                "category": [{"surface": "Power banks", "canonical": [], "is_hard": True}],
                "empty": False,
            },
            "I need a charger for travel.",
        )
        self.assertTrue(extract.empty)
        self.assertIsNone(extract.category)

    def test_inspect_walks_layers_then_attributes(self) -> None:
        client = OllamaNluClient()
        layers = [
            {
                "ids": ["Clothing_Shoes_and_Jewelry", "Sports_and_Outdoors"],
                "stop": False,
            },
            {"ids": ["running", "kids_shoes"], "stop": False},
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "blue",
                        "canonical": ["blue"],
                    }
                ],
                "empty": False,
            },
        ]
        with patch.object(client, "_complete", side_effect=layers) as mocked:
            raw, extract = client.inspect("I want blue running shoes.")
        self.assertEqual(mocked.call_count, 3)
        first_prompt = mocked.call_args_list[0].args[0]
        self.assertIn("Clothing_Shoes_and_Jewelry", first_prompt)
        self.assertNotIn("Westlake", first_prompt)
        self.assertNotIn("Prime Members Exclusive", first_prompt)
        self.assertNotIn("Fashion Sales", first_prompt)
        second_prompt = mocked.call_args_list[1].args[0]
        self.assertIn("women", second_prompt)
        self.assertIn("running", second_prompt)
        self.assertNotIn("All_Beauty", second_prompt)
        attr_system = mocked.call_args_list[2].kwargs.get("system") or ""
        self.assertIn("Do not emit category", attr_system)
        assert extract is not None
        assert raw is not None
        category_slots = [slot for slot in extract.slots if slot.attribute == "category"]
        self.assertGreaterEqual(len(category_slots), 2)
        tags: set[str] = set()
        for slot in category_slots:
            if slot.canonical:
                tags.update(slot.canonical)
        self.assertIn("clothing shoe jewelry", tags)
        self.assertNotIn("woman", tags)
        self.assertNotIn("kids shoe", tags)
        self.assertTrue(tags & {"shoe", "running", "athletic"})
        for slot in category_slots:
            self.assertTrue(
                slot.surface.casefold() in "i want blue running shoes.",
                slot.surface,
            )
        self.assertTrue(extract.category)
        colors = [slot for slot in extract.slots if slot.attribute == "color"]
        self.assertEqual(colors[0].canonical, ("blue",))

    def test_observe_writes_three_layers_into_turn_delta(self) -> None:
        configure_understand(MODE_NLU)
        self.addCleanup(lambda: configure_understand(MODE_REGEX))
        client = OllamaNluClient()
        layers = [
            {
                "ids": ["Clothing_Shoes_and_Jewelry", "Sports_and_Outdoors"],
                "stop": False,
            },
            {"ids": ["running", "kids_shoes"], "stop": False},
            {
                "constraints": [
                    {
                        "attribute": "color",
                        "surface": "blue",
                        "canonical": ["blue"],
                    }
                ],
                "empty": False,
            },
        ]
        state = SessionState("observe-layers", {})
        with (
            patch(
                "agent.understand.observation.llm_nlu.get_nlu_client",
                return_value=client,
            ),
            patch.object(client, "_complete", side_effect=layers),
        ):
            observe(state, "I want blue running shoes.")
        delta = state.turn_delta
        assert delta is not None
        tags: set[str] = set()
        for slot in delta.slots:
            if slot.attribute == "category" and slot.canonical:
                tags.update(slot.canonical)
        self.assertIn("clothing shoe jewelry", tags)
        self.assertNotIn("woman", tags)
        self.assertTrue(tags & {"shoe", "running", "athletic"})
        apply_delta(state)
        committed: set[str] = set()
        for slot in state.typed_constraints:
            if slot.attribute == "category" and slot.canonical:
                committed.update(slot.canonical)
        self.assertNotIn("woman", committed)
        self.assertTrue(committed & {"shoe", "running", "athletic"})
        self.assertTrue(state.category)

    def test_category_canonical_enables_sidecar_aliases(self) -> None:
        state = SessionState("nlu", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="category",
                surface="running shoes",
                canonical=("shoe",),
            )
        ]
        self.assertTrue(uses_search_aliases(state))


if __name__ == "__main__":
    unittest.main()
