#!/usr/bin/env python3
"""Scan catalog.jsonl once and write the product-slots sidecar SQLite database.

From this directory (contest zip or kit package):

    python extract_slots.py
    python extract_slots.py --catalog /path/to/catalog.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parent
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from src.paths import DATA_DIR
from src.retrieve.catalog.slots_sidecar import (
    DEFAULT_SLOTS_RELATIVE,
    SIDECAR_VERSION,
    catalog_fingerprint,
)
from preprocess.aliases import load_color_aliases, load_material_aliases
from preprocess.category_parents import load_category_parents
from preprocess.document import extract_documents
from preprocess.product import extract_product

SCHEMA = """
DROP TABLE IF EXISTS product_slots;
DROP TABLE IF EXISTS product_text;
DROP TABLE IF EXISTS slot_stats;
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

CREATE INDEX product_slots_lookup
    ON product_slots (attribute, canonical);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Frozen catalog JSONL (default: data/catalog.jsonl under the project root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Sidecar SQLite path (default: .cache/catalog_preprocess/product_slots.sqlite3 under cwd)",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.catalog is None:
        args.catalog = DATA_DIR / "catalog.jsonl"
    if args.output is None:
        args.output = Path.cwd() / DEFAULT_SLOTS_RELATIVE
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")

    color_aliases = load_color_aliases()
    material_aliases = load_material_aliases()
    category_parents = load_category_parents()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = args.output.with_name(args.output.name + ".tmp")
    if staging.exists():
        staging.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(staging) + suffix)
        if extra.exists():
            extra.unlink()

    connection = sqlite3.connect(str(staging))
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(SCHEMA)

    fingerprint = catalog_fingerprint(args.catalog)
    batch: list[tuple[str, str, str, str, str, str | None]] = []
    text_batch: list[tuple[str, str, str, str]] = []
    products = 0
    slots = 0
    texts = 0

    def flush() -> None:
        if batch:
            connection.executemany(
                "INSERT OR IGNORE INTO product_slots("
                "parent_asin, attribute, canonical, surface, source, extras_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch,
            )
            batch.clear()
        if text_batch:
            connection.executemany(
                "INSERT OR IGNORE INTO product_text("
                "parent_asin, field, surface, canonical) VALUES (?, ?, ?, ?)",
                text_batch,
            )
            text_batch.clear()

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
            for field, surface, canonical in extract_documents(product):
                text_batch.append((parent_asin, field, surface, canonical))
                texts += 1
            if len(batch) >= 2000 or len(text_batch) >= 2000:
                flush()
            if args.limit and products >= args.limit:
                break
    flush()
    df_map: dict[tuple[str, str], set[str]] = {}
    for attribute, canonical, parent_asin in connection.execute(
        "SELECT attribute, canonical, parent_asin FROM product_slots"
    ):
        tokens = str(canonical).split()
        if not tokens or len(tokens) > 4 or len(str(canonical)) > 40:
            continue
        df_map.setdefault((str(attribute), str(canonical)), set()).add(str(parent_asin))
    n_docs = max(products, 1)
    stats_rows: list[tuple[str, str, int, float]] = []
    max_idf = 0.0
    for (attribute, canonical), members in df_map.items():
        df = len(members)
        idf = math.log((n_docs + 1) / (df + 1))
        max_idf = max(max_idf, idf)
        stats_rows.append((attribute, canonical, df, idf))
    if stats_rows:
        connection.executemany(
            "INSERT OR IGNORE INTO slot_stats(attribute, canonical, df, idf) "
            "VALUES (?, ?, ?, ?)",
            stats_rows,
        )
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        (
            ("version", SIDECAR_VERSION),
            ("catalog_fingerprint", fingerprint),
            ("product_count", str(products)),
            ("slot_count", str(slots)),
            ("text_count", str(texts)),
            ("stat_count", str(len(stats_rows))),
            ("max_idf", str(max_idf)),
        ),
    )
    connection.commit()
    connection.close()
    try:
        staging.replace(args.output)
        for suffix in ("-wal", "-shm"):
            extra = Path(str(args.output) + suffix)
            if extra.exists():
                extra.unlink()
    except OSError:
        fallback = args.output.with_name(args.output.name + ".new")
        if fallback.exists():
            fallback.unlink()
        staging.replace(fallback)
        raise SystemExit(
            f"Wrote {slots} slots and {texts} text rows for {products} products "
            f"to {fallback} (could not replace locked {args.output})"
        )
    print(
        f"Wrote {slots} slots and {texts} text rows "
        f"for {products} products to {args.output}"
    )


if __name__ == "__main__":
    main()
