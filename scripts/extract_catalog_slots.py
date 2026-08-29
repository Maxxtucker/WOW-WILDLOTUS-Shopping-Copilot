#!/usr/bin/env python3
"""Scan catalog.jsonl once and write the product_slots sidecar SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent.retrieve.catalog.slots_sidecar import (
    DEFAULT_SLOTS_RELATIVE,
    SIDECAR_VERSION,
    catalog_fingerprint,
)
from catalog_preprocess.aliases import load_color_aliases, load_material_aliases
from catalog_preprocess.category_parents import load_category_parents
from catalog_preprocess.product import extract_product

SCHEMA = """
DROP TABLE IF EXISTS product_slots;
DROP TABLE IF EXISTS meta;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE product_slots (
    parent_asin TEXT NOT NULL,
    attribute TEXT NOT NULL,
    canonical TEXT NOT NULL,
    surface TEXT NOT NULL,
    source TEXT NOT NULL,
    extras_json TEXT,
    PRIMARY KEY (parent_asin, attribute, canonical, surface, source)
) WITHOUT ROWID;

CREATE INDEX product_slots_lookup
    ON product_slots (attribute, canonical);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / DEFAULT_SLOTS_RELATIVE)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")

    color_aliases = load_color_aliases()
    material_aliases = load_material_aliases()
    category_parents = load_category_parents()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()

    connection = sqlite3.connect(str(args.output))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(SCHEMA)

    fingerprint = catalog_fingerprint(args.catalog)
    batch: list[tuple[str, str, str, str, str, str | None]] = []
    products = 0
    slots = 0

    def flush() -> None:
        if not batch:
            return
        connection.executemany(
            "INSERT OR IGNORE INTO product_slots("
            "parent_asin, attribute, canonical, surface, source, extras_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )
        batch.clear()

    with args.catalog.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            product = json.loads(line)
            parent_asin = str(product.get("parent_asin") or "").strip()
            if not parent_asin:
                continue
            products += 1
            for row in extract_product(
                product,
                color_aliases=color_aliases,
                material_aliases=material_aliases,
                category_parents=category_parents,
            ):
                extras = None
                if row.extras:
                    extras = json.dumps(row.extras, ensure_ascii=False, separators=(",", ":"))
                batch.append(
                    (
                        parent_asin,
                        row.attribute,
                        row.canonical,
                        row.surface,
                        row.source,
                        extras,
                    )
                )
                slots += 1
            if len(batch) >= 2000:
                flush()
            if args.limit and products >= args.limit:
                break
    flush()
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        (
            ("version", SIDECAR_VERSION),
            ("catalog_fingerprint", fingerprint),
            ("product_count", str(products)),
            ("slot_count", str(slots)),
        ),
    )
    connection.commit()
    connection.close()
    print(f"Wrote {slots} slots for {products} products to {args.output}")


if __name__ == "__main__":
    main()
