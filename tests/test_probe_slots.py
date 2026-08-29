"""Probe exact-pool against product_slots (tiny fixture + optional live sidecar).

Does not read public_set.jsonl. Live tests skip when catalog or sidecar is missing.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.intent_router.probe import probe_exact_pool
from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.protocol_copy import normalize_text
from agent.retrieve.catalog.slots_sidecar import (
    SIDECAR_VERSION,
    catalog_fingerprint,
    sidecar_is_current,
)
from agent.retrieve.from_slots import exact_pool_groups
from agent.understand.observation.slots import ConstraintSlot
from agent.understand.state import SessionState
from evaluator.local_evaluator import COLOR_RE, MATERIAL_RE, searchable_text

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalog.jsonl"
LIVE_SIDECARS = (
    ROOT / ".cache" / "catalog_preprocess" / "product_slots_new.sqlite3",
    ROOT / ".cache" / "catalog_preprocess" / "product_slots.sqlite3",
)


def _state(*slots: ConstraintSlot) -> SessionState:
    state = SessionState("probe", {})
    state.typed_constraints = list(slots)
    return state


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


def _shoe(parent_asin: str, title: str, store: str) -> dict:
    return {
        "parent_asin": parent_asin,
        "title": title,
        "features": ["walking shoe"],
        "description": ["Comfortable"],
        "price": 49.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes"],
        "details": {},
        "average_rating": 4.0,
        "rating_number": 10,
        "store": store,
    }


class FixtureProbeSlotsTest(unittest.TestCase):
    """In-process catalog + sidecar. Always runs in CI."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.catalog_path = root / "catalog.jsonl"
        products = [
            _shoe("A", "Blue leather trainer", "Nike"),
            _shoe("B", "Pink leather trainer", "Adidas"),
            _shoe("C", "Blue cotton trainer", "Puma"),
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in products),
            encoding="utf-8",
        )
        self.slots_path = root / "product_slots.sqlite3"
        _write_sidecar(
            self.slots_path,
            self.catalog_path,
            [
                ("A", "color", "blue", "blue", "title", None),
                ("A", "material", "leather", "leather", "title", None),
                ("A", "brand", "nike", "Nike", "store", None),
                ("A", "category", "shoes", "Shoes", "categories", None),
                ("B", "color", "pink", "pink", "title", None),
                ("B", "material", "leather", "leather", "title", None),
                ("B", "brand", "adidas", "Adidas", "store", None),
                ("B", "category", "shoes", "Shoes", "categories", None),
                ("C", "color", "blue", "blue", "title", None),
                ("C", "material", "cotton", "cotton", "title", None),
                ("C", "brand", "puma", "Puma", "store", None),
                ("C", "category", "shoes", "Shoes", "categories", None),
            ],
        )
        self.retriever = CatalogRetriever(
            self.catalog_path, slots_path=self.slots_path
        )
        self.addCleanup(self.retriever.close)
        self.assertTrue(self.retriever._slots_attached)

    def test_color_filters_to_sidecar_members(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("color", "blue", canonical="blue")),
        )
        self.assertIsNotNone(pool)
        self.assertIn("A", pool)
        self.assertIn("C", pool)
        self.assertNotIn("B", pool)

    def test_color_or_unions_alternatives(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("color", "blue", canonical="blue"),
                ConstraintSlot("color", "pink", canonical="pink"),
            ),
        )
        self.assertEqual(pool, {"A", "B", "C"})

    def test_color_and_material_intersects(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("color", "blue", canonical="blue"),
                ConstraintSlot("material", "leather", canonical="leather"),
            ),
        )
        self.assertEqual(pool, {"A"})

    def test_brand_matches_folded_store(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("brand", "Nike", canonical="Nike")),
        )
        self.assertIsNotNone(pool)
        self.assertIn("A", pool)
        self.assertNotIn("B", pool)

    def test_soft_color_is_not_probed(self) -> None:
        state = _state(
            ConstraintSlot("color", "blue", canonical="blue", is_hard=True),
            ConstraintSlot("color", "pink", canonical="pink", is_hard=False),
        )
        self.assertEqual(dict(exact_pool_groups(state))["color"], ("blue",))
        pool = probe_exact_pool(self.retriever, state)
        self.assertEqual(pool, {"A", "C"})

    def test_budget_amount_is_not_an_exact_group(self) -> None:
        state = _state(
            ConstraintSlot(
                "budget",
                "under $40",
                amount=40.0,
                op="lte",
            ),
            ConstraintSlot("color", "blue", canonical="blue"),
        )
        self.assertNotIn("budget", dict(exact_pool_groups(state)))
        pool = probe_exact_pool(self.retriever, state)
        self.assertEqual(pool, {"A", "C"})

    def test_unknown_category_does_not_drop_other_hard_groups(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("category", "xyzzy not a catalog node"),
                ConstraintSlot("color", "blue", canonical="blue"),
            ),
        )
        self.assertEqual(pool, {"A", "C"})

    def test_unknown_category_alone_is_none(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("category", "xyzzy not a catalog node")),
        )
        self.assertIsNone(pool)

    def test_category_canonical_hits_sidecar(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot(
                    "category",
                    "running shoes",
                    canonical=("shoes", "running"),
                )
            ),
        )
        self.assertEqual(pool, {"A", "B", "C"})

    def test_category_canonical_and_color_intersect(self) -> None:
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("category", "shoes", canonical=("shoes",)),
                ConstraintSlot("color", "blue", canonical="blue"),
            ),
        )
        self.assertEqual(pool, {"A", "C"})


def _resolve_live_sidecar() -> Path | None:
    if not CATALOG.is_file():
        return None
    fingerprint = catalog_fingerprint(CATALOG)
    for path in LIVE_SIDECARS:
        if sidecar_is_current(path, fingerprint):
            return path
    return None


@unittest.skipUnless(CATALOG.is_file(), "data/catalog.jsonl is not present")
class LiveProbeSlotsTest(unittest.TestCase):
    """Full catalog + cache sidecar. Skips when the sidecar is missing or stale."""

    retriever: CatalogRetriever | None = None
    slots_db: sqlite3.Connection | None = None
    slots_path: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        path = _resolve_live_sidecar()
        if path is None:
            raise unittest.SkipTest(
                "no current product_slots sidecar "
                "(try product_slots_new.sqlite3 after extract_catalog_slots.py)"
            )
        cls.slots_path = path
        cls.slots_db = sqlite3.connect(str(path))
        cls.retriever = CatalogRetriever(CATALOG, slots_path=path)
        if not cls.retriever._slots_attached:
            cls.retriever.close()
            cls.retriever = None
            cls.slots_db.close()
            cls.slots_db = None
            raise unittest.SkipTest(f"sidecar did not ATTACH: {path}")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.retriever is not None:
            cls.retriever.close()
            cls.retriever = None
        if cls.slots_db is not None:
            cls.slots_db.close()
            cls.slots_db = None

    def _slot_asins(self, attribute: str, canonical: str) -> set[str]:
        assert self.slots_db is not None
        rows = self.slots_db.execute(
            "SELECT DISTINCT parent_asin FROM product_slots "
            "WHERE attribute = ? AND canonical = ?",
            (attribute, canonical),
        )
        return {str(row[0]) for row in rows}

    def _one_asin(self, sql: str, parameters: tuple = ()) -> str | None:
        assert self.slots_db is not None
        row = self.slots_db.execute(sql, parameters).fetchone()
        return None if row is None else str(row[0])

    def test_sidecar_attached(self) -> None:
        assert self.retriever is not None
        self.assertTrue(self.retriever._slots_attached)

    def test_color_blue_keeps_a_sidecar_member(self) -> None:
        assert self.retriever is not None
        target = self._one_asin(
            "SELECT parent_asin FROM product_slots "
            "WHERE attribute = 'color' AND canonical = 'blue' LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no color=blue")
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("color", "blue", canonical="blue")),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)

    def test_color_or_pink_still_keeps_blue_product(self) -> None:
        assert self.retriever is not None
        target = self._one_asin(
            "SELECT parent_asin FROM product_slots "
            "WHERE attribute = 'color' AND canonical = 'blue' LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no color=blue")
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("color", "blue", canonical="blue"),
                ConstraintSlot("color", "pink", canonical="pink"),
            ),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)

    def test_color_and_material_keeps_joint_member(self) -> None:
        assert self.retriever is not None
        target = self._one_asin(
            "SELECT a.parent_asin FROM product_slots AS a "
            "INNER JOIN product_slots AS b ON a.parent_asin = b.parent_asin "
            "WHERE a.attribute = 'color' AND a.canonical = 'blue' "
            "AND b.attribute = 'material' AND b.canonical = 'leather' "
            "LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no color=blue AND material=leather")
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("color", "blue", canonical="blue"),
                ConstraintSlot("material", "leather", canonical="leather"),
            ),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)

    def test_brand_keeps_sidecar_member(self) -> None:
        assert self.retriever is not None
        row = None if self.slots_db is None else self.slots_db.execute(
            "SELECT parent_asin, canonical FROM product_slots "
            "WHERE attribute = 'brand' AND canonical != '' LIMIT 1"
        ).fetchone()
        if row is None:
            self.skipTest("sidecar has no brand")
        parent_asin, canonical = str(row[0]), str(row[1])
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("brand", canonical, canonical=canonical)),
        )
        self.assertIsNotNone(pool)
        self.assertIn(parent_asin, pool)

    def test_evaluator_regex_slots_from_product_still_hit(self) -> None:
        """Same closed color/material tokens the evaluator regex would pick."""

        assert self.retriever is not None
        target = self._one_asin(
            "SELECT a.parent_asin FROM product_slots AS a "
            "INNER JOIN product_slots AS b ON a.parent_asin = b.parent_asin "
            "WHERE a.attribute = 'color' AND a.canonical = 'blue' "
            "AND b.attribute = 'material' AND b.canonical = 'leather' "
            "LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no color=blue AND material=leather")
        product = self.retriever.get_product(target)
        if product is None:
            self.skipTest("catalog row missing for sidecar ASIN")
        corpus = searchable_text(product)
        color = COLOR_RE.search(corpus)
        material = MATERIAL_RE.search(corpus)
        if color is None or material is None:
            self.skipTest("evaluator regex did not see color and material on this row")
        color_value = normalize_text(color.group(1))
        material_value = normalize_text(material.group(1))
        if color_value == "grey":
            color_value = "gray"
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("color", color.group(1), canonical=color_value),
                ConstraintSlot("material", material.group(1), canonical=material_value),
            ),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)

    def test_unknown_category_phrase_does_not_drop_color_filter(self) -> None:
        assert self.retriever is not None
        target = self._one_asin(
            "SELECT parent_asin FROM product_slots "
            "WHERE attribute = 'color' AND canonical = 'blue' LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no color=blue")
        pool = probe_exact_pool(
            self.retriever,
            _state(
                ConstraintSlot("category", "xyzzy not a catalog node"),
                ConstraintSlot("color", "blue", canonical="blue"),
            ),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)

    def test_category_shoes_canonical_hits_sidecar(self) -> None:
        assert self.retriever is not None
        target = self._one_asin(
            "SELECT parent_asin FROM product_slots "
            "WHERE attribute = 'category' AND canonical = 'shoe' LIMIT 1"
        )
        if target is None:
            self.skipTest("sidecar has no category=shoe")
        pool = probe_exact_pool(
            self.retriever,
            _state(ConstraintSlot("category", "running shoes", canonical=("shoe",))),
        )
        self.assertIsNotNone(pool)
        self.assertIn(target, pool)


if __name__ == "__main__":
    unittest.main()
