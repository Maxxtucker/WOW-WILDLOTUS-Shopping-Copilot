from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.protocol_copy import normalize_text
from agent.retrieve.catalog.slots_sidecar import SIDECAR_VERSION, catalog_fingerprint
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
    connection.executemany(
        "INSERT INTO product_slots VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        (
            ("version", SIDECAR_VERSION),
            ("catalog_fingerprint", catalog_fingerprint(catalog_path)),
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


if __name__ == "__main__":
    unittest.main()
