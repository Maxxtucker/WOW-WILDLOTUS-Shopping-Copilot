from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent.intent_router.exact_pool import exact_pool_for_state
from agent.retrieve.candidates.retrieve import retrieve_candidates
from agent.retrieve.candidates.routing import routing_for
from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.protocol_copy import normalize_text
from agent.retrieve.catalog.slots_sidecar import SIDECAR_VERSION, catalog_fingerprint
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState
from catalog_preprocess.category_parents import (
    build_parent_index,
    layer_identity_tags,
    layers_for_path,
    parent_of,
)
from catalog_preprocess.product import extract_product

MINI_CATEGORY_TREE = {
    "version": 1,
    "roots": [
        {
            "id": "Clothing_Shoes_and_Jewelry",
            "label": "Clothing, Shoes and Jewelry",
            "catalog_tags": ["clothing shoe jewelry"],
            "children": [
                {
                    "id": "women",
                    "label": "Women",
                    "catalog_tags": ["woman"],
                    "children": [
                        {
                            "id": "shoes",
                            "label": "Shoes",
                            "catalog_tags": ["shoe", "sandal"],
                        }
                    ],
                },
                {
                    "id": "men",
                    "label": "Men",
                    "catalog_tags": ["man"],
                    "children": [
                        {
                            "id": "shoes",
                            "label": "Shoes",
                            "catalog_tags": ["shoe", "sandal"],
                        }
                    ],
                },
            ],
        }
    ],
}

COLOR_ALIASES = {
    "navy": {"base": "indigo", "eval": "blue"},
    "blue": {"base": "blue", "eval": "blue"},
    "pink": {"base": "pink", "eval": "pink"},
    "black": {"base": "black", "eval": "black"},
    "purple": {"base": "purple", "eval": "purple"},
    "yellow": {"base": "yellow", "eval": "yellow"},
    "gold": {"base": "gold", "eval": "yellow"},
    "white": {"base": "white", "eval": "white"},
}
MATERIAL_ALIASES = {
    "lycra": {"fiber": "elastane", "eval": "spandex"},
    "spandx": {"fiber": "elastane", "eval": "spandex"},
    "spandex": {"fiber": "spandex", "eval": "spandex"},
    "polyester": {"fiber": "polyester", "eval": "polyester"},
    "cotton": {"fiber": "cotton", "eval": "cotton"},
    "leather": {"fiber": "leather", "eval": "leather"},
    "satin": {"fiber": "satin", "eval": "fabric"},
    "fabric": {"fiber": "fabric", "eval": "fabric"},
}


def _extract(product: dict) -> list:
    return extract_product(
        product, color_aliases=COLOR_ALIASES, material_aliases=MATERIAL_ALIASES
    )


def _canons(rows, attribute: str) -> set[str]:
    return {row.canonical for row in rows if row.attribute == attribute}


def _write_sidecar(
    path: Path,
    catalog_path: Path,
    rows: list[tuple],
    *,
    texts: list[tuple] | None = None,
    stats: list[tuple] | None = None,
    max_idf: float = 1.0,
) -> None:
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
    connection.executemany(
        "INSERT INTO product_slots VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    if texts:
        connection.executemany(
            "INSERT INTO product_text VALUES (?, ?, ?, ?)",
            texts,
        )
    if stats:
        connection.executemany(
            "INSERT INTO slot_stats VALUES (?, ?, ?, ?)",
            stats,
        )
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        (
            ("version", SIDECAR_VERSION),
            ("catalog_fingerprint", catalog_fingerprint(catalog_path)),
            ("max_idf", str(max_idf)),
        ),
    )
    connection.commit()
    connection.close()


class ExtractorTest(unittest.TestCase):
    def test_blend_emits_all_fibers(self) -> None:
        rows = _extract(
            {
                "parent_asin": "B1",
                "title": "Columbia Men's Crew",
                "features": ["67% Polyester, 33% Cotton"],
                "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts"],
                "details": {"Department": "mens"},
                "price": 27.99,
                "store": "Columbia",
            }
        )
        self.assertEqual(_canons(rows, "material"), {"polyester", "cotton"})
        self.assertIn("columbia", _canons(rows, "brand"))
        self.assertIn("mens", _canons(rows, "style"))
        budget = next(row for row in rows if row.attribute == "budget")
        self.assertEqual(budget.canonical, "27.99")
        self.assertEqual(budget.extras["amount"], 27.99)

    def test_budget_keeps_decimal_point(self) -> None:
        rows = _extract(
            {
                "parent_asin": "P199",
                "title": "Example",
                "features": [],
                "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
                "details": {},
                "price": 1.99,
                "store": "X",
            }
        )
        self.assertEqual(_canons(rows, "budget"), {"1.99"})
        self.assertNotIn("1 99", _canons(rows, "budget"))

    def test_title_color_and_lycra_to_spandex(self) -> None:
        rows = _extract(
            {
                "parent_asin": "B2",
                "title": "Navy running socks",
                "features": ["100% Lycra"],
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Women",
                    "Clothing",
                    "Active",
                    "Athletic Socks",
                ],
                "details": {},
                "store": "Hylaea",
            }
        )
        self.assertIn("blue", _canons(rows, "color"))
        self.assertIn("spandex", _canons(rows, "material"))
        self.assertIn("running", _canons(rows, "use_case"))

    def test_spandx_typo_and_split_colors(self) -> None:
        rows = _extract(
            {
                "parent_asin": "B3",
                "title": "Gloves- Black - Men & Women",
                "features": ["12% Spandx"],
                "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing"],
                "details": {"Color": "Black/Purple"},
                "store": "X",
            }
        )
        self.assertIn("spandex", _canons(rows, "material"))
        self.assertTrue({"black", "purple"} <= _canons(rows, "color"))

    def test_jewelry_gold_is_not_yellow(self) -> None:
        rows = _extract(
            {
                "parent_asin": "B4",
                "title": "14k Gold Necklace",
                "features": [],
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Women",
                    "Jewelry",
                    "Necklaces",
                ],
                "details": {},
                "store": "Nupuyai",
            }
        )
        self.assertNotIn("yellow", _canons(rows, "color"))
        self.assertIn("jewelry", _canons(rows, "category"))

    def test_pink_satin_and_dimension_size(self) -> None:
        rows = _extract(
            {
                "parent_asin": "B5",
                "title": "1950s Pink Satin Jacket",
                "features": [],
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Costumes & Accessories",
                    "Women",
                    "Costumes & Cosplay Apparel",
                ],
                "details": {
                    "Product Dimensions": "1.97 x 1.97 x 0.08 inches; 0.5 Ounces",
                    "Size": "M",
                },
                "store": "CISSTEC",
            }
        )
        self.assertIn("pink", _canons(rows, "color"))
        self.assertIn("fabric", _canons(rows, "material"))
        size_rows = [row for row in rows if row.attribute == "size"]
        kinds = {row.extras.get("kind") for row in size_rows if row.extras}
        self.assertIn("dimension", kinds)
        self.assertIn("m", _canons(rows, "size"))
        self.assertIn("costume", _canons(rows, "category"))
        dim = next(
            row
            for row in size_rows
            if row.extras and row.extras.get("kind") == "dimension"
        )
        self.assertEqual(dim.extras["unit"], "in")
        self.assertAlmostEqual(dim.extras["length"], 1.97)
        self.assertEqual(dim.extras["source_key"], "product dimensions")

    def test_dimension_string_keeps_pounds_and_item_weight(self) -> None:
        rows = _extract(
            {
                "parent_asin": "W1",
                "title": "Case",
                "features": [],
                "categories": ["Home"],
                "details": {
                    "Product Dimensions": "16.26 x 13.74 x 2.68 inches; 1.52 Pounds",
                    "Item Weight": "8 Ounces",
                },
                "store": "X",
            }
        )
        dims = [
            row
            for row in rows
            if row.attribute == "size" and row.extras and row.extras.get("kind") == "dimension"
        ]
        boxed = next(
            row for row in dims if row.extras.get("source_key") == "product dimensions"
        )
        self.assertAlmostEqual(boxed.extras["length"], 16.26)
        self.assertAlmostEqual(boxed.extras["weight"], 1.52)
        item = next(row for row in dims if row.extras.get("source_key") == "item weight")
        self.assertAlmostEqual(item.extras["weight"], 0.5)
        self.assertIsNone(item.extras.get("length"))

    def test_any_dimension_key_parses_and_converts_cm_to_inches(self) -> None:
        rows = _extract(
            {
                "parent_asin": "D1",
                "title": "Box",
                "features": [],
                "categories": ["Home"],
                "details": {
                    "Dimensions": "10 x 5 x 2 cm",
                    "Package Dimensions": "20 x 10 x 4 inches",
                },
                "store": "X",
            }
        )
        dims = [
            row
            for row in rows
            if row.attribute == "size"
            and row.extras
            and row.extras.get("kind") == "dimension"
        ]
        self.assertEqual(len(dims), 2)
        productish = next(row for row in dims if row.extras["source_key"] == "dimensions")
        packaged = next(
            row for row in dims if "package" in str(row.extras["source_key"])
        )
        self.assertAlmostEqual(productish.extras["length"], 10 / 2.54, places=5)
        self.assertEqual(productish.extras["unit"], "in")
        self.assertAlmostEqual(packaged.extras["length"], 20.0)

    def test_brand_key_substring_folds_canonical(self) -> None:
        rows = _extract(
            {
                "parent_asin": "BR1",
                "title": "Tee",
                "features": [],
                "categories": ["Clothing"],
                "details": {"Product Brand": "Nike", "Brand Name": "NIKE"},
                "store": "Outlet",
            }
        )
        brands = [row for row in rows if row.attribute == "brand"]
        canons = {row.canonical for row in brands}
        self.assertIn("nike", canons)
        self.assertIn("outlet", canons)
        surfaces = {row.surface for row in brands}
        self.assertIn("Nike", surfaces)

    def test_style_key_keeps_original_surface(self) -> None:
        rows = _extract(
            {
                "parent_asin": "ST1",
                "title": "Tee",
                "features": [],
                "categories": ["Clothing"],
                "details": {
                    "Collar Style": "V-Neck",
                    "Neck Style": "Crew",
                    "Lifestyle": "Outdoor",
                },
                "store": "X",
            }
        )
        styles = [row for row in rows if row.attribute == "style"]
        surfaces = {row.surface for row in styles}
        self.assertIn("V-Neck", surfaces)
        self.assertIn("Crew", surfaces)
        self.assertNotIn("Outdoor", surfaces)

    def test_feature_line_is_verbatim_and_skips_composition(self) -> None:
        rows = _extract(
            {
                "parent_asin": "F1",
                "title": "Jacket",
                "features": ["Waterproof shell", "67% Polyester, 33% Cotton"],
                "categories": ["Clothing"],
                "details": {},
                "store": "X",
            }
        )
        features = [row for row in rows if row.attribute == "feature"]
        surfaces = {row.surface for row in features}
        self.assertIn("Waterproof shell", surfaces)
        self.assertTrue(any(row.canonical == "waterproof" for row in features))
        self.assertFalse(any("%" in row.surface for row in features))

    def test_document_folds_title_without_stopwords(self) -> None:
        from catalog_preprocess.document import extract_documents

        rows = extract_documents(
            {
                "title": "The Boots and the Bag",
                "details": {"Color": "Brown", "Fit Type": "Slim"},
                "description": ["A sturdy pair."],
            }
        )
        by_field = {field: (surface, canonical) for field, surface, canonical in rows}
        self.assertIn("title", by_field)
        self.assertEqual(by_field["title"][0], "The Boots and the Bag")
        self.assertNotIn("the", by_field["title"][1].split())
        self.assertNotIn("and", by_field["title"][1].split())
        self.assertIn("boots", by_field["title"][1])
        self.assertIn("details", by_field)
        self.assertIn("Brown", by_field["details"][0])
        self.assertNotIn("Color", by_field["details"][0])
        self.assertIn("description", by_field)

    def test_fold_category_unifies_spelling_and_plurals(self) -> None:
        from catalog_preprocess.text import fold_category

        self.assertEqual(
            fold_category("Clothing, Shoes & Jewelry"),
            "clothing shoe jewelry",
        )
        self.assertEqual(
            fold_category("Clothing, Shoes and Jewelry"),
            "clothing shoe jewelry",
        )
        self.assertEqual(fold_category("Shoes"), "shoe")
        self.assertEqual(fold_category("Women"), "woman")
        self.assertEqual(fold_category("Sandals"), "sandal")

    def test_same_fold_child_is_pruned(self) -> None:
        from build_category_tree import _collapse_fold_redundant, _tags, node

        parent = node(
            "shoes",
            "Shoes",
            _tags("Shoes"),
            [node("shoe", "Shoe", _tags("Shoe", "Sandals"))],
        )
        out = _collapse_fold_redundant(parent)
        self.assertFalse(out.get("children"))
        tags = set(out["catalog_tags"])
        self.assertIn("shoe", tags)
        self.assertIn("sandal", tags)

    def test_same_fold_siblings_merge(self) -> None:
        from build_category_tree import _collapse_fold_redundant, _tags, node

        parent = node(
            "women",
            "Women",
            _tags("Women"),
            [
                node("shoes", "Shoes", _tags("Shoes", "Sandals")),
                node("shoe", "Shoe", _tags("Shoe", "Boots")),
            ],
        )
        out = _collapse_fold_redundant(parent)
        children = out.get("children") or []
        self.assertEqual(len(children), 1)
        tags = set(children[0]["catalog_tags"])
        self.assertTrue({"shoe", "sandal", "boot"} <= tags)

    def test_tree_layers_align_with_understand_path(self) -> None:
        index = build_parent_index(MINI_CATEGORY_TREE)
        self.assertEqual(parent_of("sandals", index), "shoe")
        self.assertIsNone(parent_of("shoes", index))
        self.assertGreaterEqual(len(index["homes"]["shoe"]), 2)
        self.assertEqual(
            layers_for_path(
                ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Sandals"],
                index,
            ),
            ("clothing shoe jewelry", "woman", "shoe"),
        )
        self.assertEqual(
            layers_for_path(
                ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Sandals"],
                index,
            ),
            ("clothing shoe jewelry", "man", "shoe"),
        )
        rows = extract_product(
            {
                "parent_asin": "S1",
                "title": "Leather sandals",
                "features": [],
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Women",
                    "Shoes",
                    "Sandals",
                ],
                "details": {},
                "store": "X",
            },
            color_aliases=COLOR_ALIASES,
            material_aliases=MATERIAL_ALIASES,
            category_parents=index,
        )
        canons = _canons(rows, "category")
        self.assertIn("clothing shoe jewelry", canons)
        self.assertNotIn("clothing shoes and jewelry", canons)
        self.assertNotIn("shoes", canons)
        self.assertIn("woman", canons)
        self.assertIn("shoe", canons)
        self.assertIn("sandal", canons)
        shoe_rows = [row for row in rows if row.attribute == "category" and row.canonical == "shoe"]
        self.assertEqual(len(shoe_rows), 1)
        self.assertEqual(shoe_rows[0].source, "categories:tree")
        tree_canons = {
            row.canonical for row in rows if row.source == "categories:tree"
        }
        self.assertEqual(
            tree_canons,
            set(layer_identity_tags(("clothing shoe jewelry", "woman", "shoe"), index)),
        )
        self.assertNotIn("sandal", tree_canons)


class SlotsAttachTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog_path = self.root / "catalog.jsonl"
        product = {
            "parent_asin": "NAVY1",
            "title": "Mystery item",
            "features": ["Made in USA"],
            "description": [],
            "price": 10,
            "categories": ["Clothing, Shoes & Jewelry", "Women", "Clothing"],
            "details": {"Department": "womens"},
            "average_rating": 4.0,
            "rating_number": 10,
            "store": "Acme",
        }
        self.catalog_path.write_text(json.dumps(product) + "\n", encoding="utf-8")
        self.slots_path = self.root / "product_slots.sqlite3"
        _write_sidecar(
            self.slots_path,
            self.catalog_path,
            [
                (
                    "NAVY1",
                    "color",
                    normalize_text("blue"),
                    "navy",
                    "title",
                    None,
                )
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_search_aliases_union_slots_but_response_only_does_not(self) -> None:
        with CatalogRetriever(
            self.catalog_path, slots_path=self.slots_path
        ) as retriever:
            self.assertTrue(retriever._slots_attached)
            search_hits = retriever.signature_candidates(
                "color", "blue", response_only=False
            )
            self.assertIn("NAVY1", search_hits)
            response_hits = retriever.signature_candidates(
                "color", "blue", response_only=True
            )
            self.assertNotIn("NAVY1", response_hits)

    def test_missing_sidecar_does_not_extract(self) -> None:
        missing = self.root / "missing.sqlite3"
        with self.assertWarns(RuntimeWarning):
            retriever = CatalogRetriever(self.catalog_path, slots_path=missing)
        try:
            self.assertFalse(retriever._slots_attached)
            hits = retriever.signature_candidates("color", "blue", response_only=False)
            self.assertNotIn("NAVY1", hits)
        finally:
            retriever.close()


class BudgetDimensionRetrieveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog_path = self.root / "catalog.jsonl"
        products = [
            {
                "parent_asin": "CHEAP",
                "title": "Cheap patch",
                "features": [],
                "description": [],
                "price": 20,
                "categories": ["Clothing, Shoes & Jewelry"],
                "details": {},
                "average_rating": 4.0,
                "rating_number": 10,
                "store": "X",
            },
            {
                "parent_asin": "DEAR",
                "title": "Dear patch",
                "features": [],
                "description": [],
                "price": 80,
                "categories": ["Clothing, Shoes & Jewelry"],
                "details": {},
                "average_rating": 4.0,
                "rating_number": 10,
                "store": "X",
            },
            {
                "parent_asin": "FREE",
                "title": "Unpriced patch",
                "features": [],
                "description": [],
                "price": None,
                "categories": ["Clothing, Shoes & Jewelry"],
                "details": {},
                "average_rating": 4.0,
                "rating_number": 10,
                "store": "X",
            },
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in products),
            encoding="utf-8",
        )
        self.slots_path = self.root / "product_slots.sqlite3"
        extras_ok = json.dumps(
            {
                "kind": "dimension",
                "unit": "in",
                "length": 3.0,
                "width": 3.0,
                "height": 0.1,
                "source_key": "product dimensions",
            }
        )
        extras_pkg = json.dumps(
            {
                "kind": "dimension",
                "unit": "in",
                "length": 12.0,
                "width": 10.0,
                "height": 4.0,
                "source_key": "package dimensions",
            }
        )
        _write_sidecar(
            self.slots_path,
            self.catalog_path,
            [
                (
                    "CHEAP",
                    "size",
                    "dimension",
                    "3 x 3 x 0.1 inches",
                    "details:product dimensions",
                    extras_ok,
                ),
                (
                    "DEAR",
                    "size",
                    "dimension",
                    "12 x 10 x 4 inches",
                    "details:package dimensions",
                    extras_pkg,
                ),
                ("CHEAP", "color", "blue", "blue", "details:color", None),
                ("DEAR", "color", "blue", "blue", "details:color", None),
                ("FREE", "color", "blue", "blue", "details:color", None),
            ],
        )
        self.retriever = CatalogRetriever(
            self.catalog_path, slots_path=self.slots_path
        )

    def tearDown(self) -> None:
        self.retriever.close()
        self.temporary.cleanup()

    def test_hard_budget_drops_missing_and_over_price(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="budget",
                surface="under $40",
                amount=40,
                op="lte",
                is_hard=True,
            )
        ]
        hits = retrieve_candidates(
            self.retriever, state, {"CHEAP", "DEAR", "FREE"}
        )
        self.assertEqual([hit.parent_asin for hit in hits], ["CHEAP"])

    def test_soft_budget_keeps_missing_and_over_with_zero_bonus(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="budget",
                surface="under $40",
                amount=40,
                op="lte",
                is_hard=False,
            )
        ]
        hits = retrieve_candidates(
            self.retriever, state, {"CHEAP", "DEAR", "FREE"}
        )
        asins = {hit.parent_asin for hit in hits}
        self.assertEqual(asins, {"CHEAP", "DEAR", "FREE"})
        by_id = {hit.parent_asin: hit for hit in hits}
        self.assertIn("budget_fit=1.00", by_id["CHEAP"].reasons)
        self.assertNotIn("budget_fit=1.00", by_id["DEAR"].reasons)
        self.assertNotIn("budget_fit=1.00", by_id["FREE"].reasons)

    def test_hard_dimension_prefers_product_and_drops_missing(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="size",
                surface="3 x 3 inches",
                kind="dimension",
                unit="in",
                length=3.0,
                width=3.0,
                is_hard=True,
            )
        ]
        hits = retrieve_candidates(
            self.retriever, state, {"CHEAP", "DEAR", "FREE"}
        )
        self.assertEqual([hit.parent_asin for hit in hits], ["CHEAP"])
        self.assertIn("size", hits[0].matched_constraints)

    def test_hybrid_fill_keeps_numeric_mismatches_as_ranked_candidates(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="budget",
                surface="under $40",
                amount=40,
                op="lte",
                is_hard=True,
            ),
            ConstraintSlot(
                attribute="size",
                surface="3 x 3 inches",
                kind="dimension",
                unit="in",
                length=3.0,
                width=3.0,
                is_hard=True,
            ),
        ]

        hits = retrieve_candidates(self.retriever, state, {"CHEAP"})

        by_id = {hit.parent_asin: hit for hit in hits}
        self.assertEqual(set(by_id), {"CHEAP", "DEAR", "FREE"})
        self.assertIn("budget_fit=1.00", by_id["CHEAP"].reasons)
        self.assertIn("dimension_fit=1.00", by_id["CHEAP"].reasons)
        self.assertNotIn("budget_fit=1.00", by_id["DEAR"].reasons)
        self.assertNotIn("dimension_fit=1.00", by_id["DEAR"].reasons)
        self.assertNotIn("budget_fit=1.00", by_id["FREE"].reasons)
        self.assertNotIn("dimension_fit=1.00", by_id["FREE"].reasons)
        self.assertGreater(by_id["CHEAP"].score, by_id["DEAR"].score)

    def test_probe_hard_budget_filters_after_string_intersect(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(attribute="color", surface="blue", canonical=("blue",)),
            ConstraintSlot(
                attribute="budget",
                surface="under $40",
                amount=40,
                op="lte",
                is_hard=True,
            ),
        ]
        pool = exact_pool_for_state(self.retriever, state)
        self.assertEqual(pool, {"CHEAP"})

    def test_probe_hard_dimension_filters_after_string_intersect(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(attribute="color", surface="blue", canonical=("blue",)),
            ConstraintSlot(
                attribute="size",
                surface="3 x 3 inches",
                kind="dimension",
                unit="in",
                length=3.0,
                width=3.0,
                is_hard=True,
            ),
        ]
        pool = exact_pool_for_state(self.retriever, state)
        self.assertEqual(pool, {"CHEAP"})

    def test_hard_weight_drops_missing(self) -> None:
        extras_light = json.dumps(
            {
                "kind": "dimension",
                "unit": "in",
                "weight": 0.5,
                "source_key": "item weight",
            }
        )
        connection = sqlite3.connect(str(self.slots_path))
        connection.execute(
            "INSERT OR REPLACE INTO product_slots VALUES (?, ?, ?, ?, ?, ?)",
            (
                "CHEAP",
                "size",
                "dimension",
                "8 ounces",
                "details:item weight",
                extras_light,
            ),
        )
        connection.commit()
        connection.close()
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="size",
                surface="under 1 pound",
                kind="dimension",
                weight=1.0,
                op="lte",
                is_hard=True,
            )
        ]
        hits = retrieve_candidates(
            self.retriever, state, {"CHEAP", "DEAR", "FREE"}
        )
        self.assertEqual([hit.parent_asin for hit in hits], ["CHEAP"])
        probe_state = SessionState("s", {})
        probe_state.typed_constraints = [
            ConstraintSlot(attribute="color", surface="blue", canonical=("blue",)),
            ConstraintSlot(
                attribute="size",
                surface="under 1 pound",
                kind="dimension",
                weight=1.0,
                op="lte",
                is_hard=True,
            ),
        ]
        self.assertEqual(exact_pool_for_state(self.retriever, probe_state), {"CHEAP"})


class SlotStatsExtractTest(unittest.TestCase):
    def test_extract_writes_short_stats_and_skips_long_feature(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        catalog = root / "catalog.jsonl"
        long_line = " ".join(f"token{index}" for index in range(20))
        catalog.write_text(
            json.dumps(
                {
                    "parent_asin": "Z1",
                    "title": "Black case",
                    "features": [long_line],
                    "description": [],
                    "price": 10,
                    "categories": ["Home"],
                    "details": {"Color": "Black", "Item Weight": "8 Ounces"},
                    "average_rating": 4.0,
                    "rating_number": 5,
                    "store": "X",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        output = root / "product_slots.sqlite3"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "extract_catalog_slots.py"),
                "--catalog",
                str(catalog),
                "--output",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("1 products", completed.stdout)
        connection = sqlite3.connect(str(output))
        version = connection.execute(
            "SELECT value FROM meta WHERE key = 'version'"
        ).fetchone()[0]
        self.assertEqual(version, SIDECAR_VERSION)
        feature_canons = [
            row[0]
            for row in connection.execute(
                "SELECT canonical FROM slot_stats WHERE attribute = 'feature'"
            )
        ]
        self.assertFalse(any(len(item.split()) > 4 for item in feature_canons))
        self.assertFalse(any(len(item) > 40 for item in feature_canons))
        colors = {
            row[0]
            for row in connection.execute(
                "SELECT canonical FROM slot_stats WHERE attribute = 'color'"
            )
        }
        self.assertTrue(colors)
        extras = connection.execute(
            "SELECT extras_json FROM product_slots WHERE attribute = 'size'"
        ).fetchall()
        self.assertTrue(
            any(json.loads(row[0] or "{}").get("weight") is not None for row in extras)
        )
        connection.close()


class ScoringLayersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog_path = self.root / "catalog.jsonl"
        products = [
            {
                "parent_asin": "A",
                "title": "Black cushioned shoe",
                "features": ["UPF", "cushioned"],
                "description": [],
                "price": 30,
                "categories": ["Shoes"],
                "details": {"Color": "Black"},
                "average_rating": 4.0,
                "rating_number": 10,
                "store": "X",
            },
            {
                "parent_asin": "B",
                "title": "Black leather shoe",
                "features": ["Waterproof", "leather"],
                "description": [],
                "price": 30,
                "categories": ["Shoes"],
                "details": {"Color": "Black"},
                "average_rating": 4.0,
                "rating_number": 10,
                "store": "X",
            },
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in products),
            encoding="utf-8",
        )
        self.slots_path = self.root / "product_slots.sqlite3"
        _write_sidecar(
            self.slots_path,
            self.catalog_path,
            [
                ("A", "color", "black", "Black", "details:color", None),
                ("B", "color", "black", "Black", "details:color", None),
                ("A", "feature", "upf", "UPF", "features", None),
                ("B", "feature", "waterproof", "Waterproof", "features", None),
            ],
            texts=[
                ("A", "title", "Black cushioned shoe", "black cushioned shoe"),
                ("B", "title", "Black leather shoe", "black leather shoe"),
            ],
            stats=[
                ("color", "black", 10000, 0.1),
                ("feature", "upf", 5, 8.0),
                ("feature", "waterproof", 200, 2.0),
            ],
            max_idf=8.0,
        )
        self.retriever = CatalogRetriever(
            self.catalog_path, slots_path=self.slots_path
        )

    def tearDown(self) -> None:
        self.retriever.close()
        self.temporary.cleanup()

    def test_exact_pool_does_not_rarity_weight_hard_color(self) -> None:
        hits_exact = self.retriever.score_candidates(
            ["A", "B"],
            required_groups=(("color", ("black",)),),
            in_exact_pool=True,
        )
        hits_hybrid = self.retriever.score_candidates(
            ["A", "B"],
            required_groups=(("color", ("black",)),),
            in_exact_pool=False,
        )
        exact_scores = {hit.parent_asin: hit.structured_score for hit in hits_exact}
        self.assertAlmostEqual(exact_scores["A"], exact_scores["B"])
        self.assertGreater(
            hits_exact[0].structured_score, hits_hybrid[0].structured_score
        )

    def test_hybrid_missing_rare_hurts_more_than_missing_common(self) -> None:
        hits = self.retriever.score_candidates(
            ["A", "B"],
            required_groups=(
                ("color", ("black",)),
                ("feature", ("upf",)),
            ),
            in_exact_pool=False,
        )
        self.assertEqual(hits[0].parent_asin, "A")

    def test_soft_preferred_uses_rarity(self) -> None:
        hits = self.retriever.score_candidates(
            ["A", "B"],
            preferred_groups=(("feature", ("upf", "waterproof")),),
            in_exact_pool=True,
        )
        self.assertEqual(hits[0].parent_asin, "A")
        self.assertGreater(hits[0].structured_score, hits[1].structured_score)

    def test_soft_text_overlap_ranks_title_hit(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="color", surface="black", canonical=("black",), is_hard=True
            ),
            ConstraintSlot(
                attribute="feature",
                surface="cushioned",
                canonical=("cushioned",),
                is_hard=False,
            ),
        ]
        hits = retrieve_candidates(self.retriever, state, {"A", "B"})
        self.assertEqual(hits[0].parent_asin, "A")
        self.assertTrue(any(reason.startswith("text_fit=") for reason in hits[0].reasons))

    def test_no_soft_slots_text_fit_is_zero(self) -> None:
        state = SessionState("s", {})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="color", surface="black", canonical=("black",), is_hard=True
            )
        ]
        hits = retrieve_candidates(self.retriever, state, {"A", "B"})
        for hit in hits:
            self.assertFalse(
                any(reason.startswith("text_fit=") for reason in hit.reasons)
            )

    @patch(
        "agent.retrieve.catalog.scoring.profile_fits",
        return_value={"A": 0.9, "B": 0.1},
    )
    def test_profile_cosine_breaks_ties(self, _mocked) -> None:
        state = SessionState("s", {"preference_tags": ["comfort"]})
        state.typed_constraints = [
            ConstraintSlot(
                attribute="color", surface="black", canonical=("black",), is_hard=True
            )
        ]
        hits = retrieve_candidates(self.retriever, state, {"A", "B"})
        self.assertEqual(hits[0].parent_asin, "A")
        self.assertTrue(
            any(reason.startswith("profile_fit=") for reason in hits[0].reasons)
        )

    def test_buying_text_weight_is_half(self) -> None:
        self.assertEqual(routing_for("buying").weights.text, 0.5)


if __name__ == "__main__":
    unittest.main()
