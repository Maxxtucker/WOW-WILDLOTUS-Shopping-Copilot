"""Purpose: SQLite schema, fingerprint check, and FTS + signature tables from JSONL.

Input: CatalogRetriever connection, catalog_path.
Output: written products / product_fts / signature_values / index_meta.
Role: offline index for the 50k catalog; rebuild only when the fingerprint changes.
"""

from __future__ import annotations

import json
import math
import sqlite3
import zlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .protocol_copy import INDEX_VERSION, text
from .signatures import build_response_signature, value_aliases
from .types import ResponseSignature

if TYPE_CHECKING:
    from .retriever import CatalogRetriever


class IndexMixin:
    """Schema and build helpers mixed into :class:`CatalogRetriever`."""

    def _configure_connection(self: CatalogRetriever) -> None:
        with self.connection:
            self.connection.execute("PRAGMA temp_store=MEMORY")
            self.connection.execute("PRAGMA cache_size=-65536")
            if self.index_path is None:
                self.connection.execute("PRAGMA journal_mode=MEMORY")
                self.connection.execute("PRAGMA synchronous=OFF")
            else:
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=NORMAL")

    def _catalog_fingerprint(self: CatalogRetriever) -> str:
        stat = self.catalog_path.stat()
        return f"{self.catalog_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"

    def _index_is_current(self: CatalogRetriever) -> bool:
        try:
            rows = dict(self.connection.execute("SELECT key, value FROM index_meta"))
            required_tables = {
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            return (
                rows.get("version") == INDEX_VERSION
                and rows.get("catalog_fingerprint") == self._catalog_fingerprint()
                and {"products", "product_fts", "signature_values"}.issubset(required_tables)
            )
        except sqlite3.Error:
            return False

    def _drop_schema(self: CatalogRetriever) -> None:
        self.connection.executescript(
            """
            DROP TABLE IF EXISTS product_fts;
            DROP TABLE IF EXISTS signature_values;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS index_meta;
            """
        )

    def _create_schema(self: CatalogRetriever) -> None:
        try:
            self.connection.executescript(
                """
                CREATE TABLE index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID;

                CREATE TABLE products (
                    doc_id INTEGER PRIMARY KEY,
                    parent_asin TEXT NOT NULL UNIQUE,
                    price REAL,
                    average_rating REAL,
                    rating_number INTEGER NOT NULL DEFAULT 0,
                    categories_json TEXT NOT NULL,
                    store TEXT NOT NULL,
                    raw_json BLOB NOT NULL,
                    signature_json BLOB NOT NULL
                );

                CREATE VIRTUAL TABLE product_fts USING fts5(
                    parent_asin UNINDEXED,
                    title,
                    categories,
                    features,
                    details,
                    store,
                    description,
                    tokenize='porter unicode61 remove_diacritics 2'
                );

                CREATE TABLE signature_values (
                    attribute TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value_norm TEXT NOT NULL,
                    parent_asin TEXT NOT NULL,
                    PRIMARY KEY (attribute, kind, value_norm, parent_asin)
                ) WITHOUT ROWID;

                """
            )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).casefold():
                raise RuntimeError(
                    "This Python SQLite build does not include FTS5; the official "
                    "starter requires the same SQLite feature."
                ) from exc
            raise

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _signature_rows(
        self: CatalogRetriever,
        parent_asin: str,
        signature: ResponseSignature,
    ) -> list[tuple[str, str, str, str]]:
        rows: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        response_aliases: set[tuple[str, str]] = set()
        for kind, mapping in (
            ("response", signature.response_values),
            ("search", signature.search_values),
        ):
            for attribute, raw_values in mapping.items():
                for raw_value in raw_values:
                    for alias in value_aliases(attribute, raw_value):
                        logical_value = (attribute, alias)
                        # search_values is a superset of response_values.  The
                        # default lookup queries both kinds, so storing the
                        # duplicate a second time only bloats the 50k index.
                        if kind == "search" and logical_value in response_aliases:
                            continue
                        if kind == "response":
                            response_aliases.add(logical_value)
                        row = (attribute, kind, alias, parent_asin)
                        if alias and row not in seen:
                            seen.add(row)
                            rows.append(row)
        return rows

    def _build_index(self: CatalogRetriever) -> None:
        with self._lock:
            self._drop_schema()
            self._create_schema()
            product_rows: list[tuple[object, ...]] = []
            fts_rows: list[tuple[str, ...]] = []
            signature_rows: list[tuple[str, str, str, str]] = []
            seen_asins: set[str] = set()

            def flush() -> None:
                if not product_rows:
                    return
                self.connection.executemany(
                    "INSERT INTO products(parent_asin, price, average_rating, "
                    "rating_number, categories_json, store, raw_json, signature_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    product_rows,
                )
                self.connection.executemany(
                    "INSERT INTO product_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    fts_rows,
                )
                self.connection.executemany(
                    "INSERT OR IGNORE INTO signature_values VALUES (?, ?, ?, ?)",
                    signature_rows,
                )
                product_rows.clear()
                fts_rows.clear()
                signature_rows.clear()

            self.connection.execute("BEGIN")
            try:
                with self.catalog_path.open(encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if not line.strip():
                            continue
                        try:
                            product = json.loads(line)
                            parent_asin = str(product["parent_asin"]).strip()
                        except (json.JSONDecodeError, KeyError, TypeError) as exc:
                            raise ValueError(
                                f"Invalid catalog row at line {line_number}"
                            ) from exc
                        if not parent_asin:
                            raise ValueError(f"Empty parent_asin at line {line_number}")
                        if parent_asin in seen_asins:
                            raise ValueError(f"Duplicate parent_asin: {parent_asin}")
                        seen_asins.add(parent_asin)

                        signature = build_response_signature(product)
                        categories = product.get("categories") or []
                        if not isinstance(categories, Sequence) or isinstance(
                            categories, (str, bytes)
                        ):
                            categories = [categories]
                        raw_json = json.dumps(
                            product, ensure_ascii=False, separators=(",", ":")
                        )
                        signature_json = json.dumps(
                            signature.to_dict(), ensure_ascii=False, separators=(",", ":")
                        )
                        product_rows.append(
                            (
                                parent_asin,
                                self._safe_float(product.get("price")),
                                self._safe_float(product.get("average_rating")),
                                self._safe_int(product.get("rating_number")),
                                json.dumps(categories, ensure_ascii=False),
                                str(product.get("store") or ""),
                                sqlite3.Binary(zlib.compress(raw_json.encode("utf-8"), 6)),
                                sqlite3.Binary(zlib.compress(signature_json.encode("utf-8"), 6)),
                            )
                        )
                        fts_rows.append(
                            (
                                parent_asin,
                                text(product.get("title")),
                                text(product.get("categories")),
                                text(product.get("features")),
                                text(product.get("details")),
                                text(product.get("store")),
                                text(product.get("description")),
                            )
                        )
                        signature_rows.extend(
                            self._signature_rows(parent_asin, signature)
                        )
                        if len(product_rows) >= 750:
                            flush()
                flush()
                self.connection.executemany(
                    "INSERT INTO index_meta(key, value) VALUES (?, ?)",
                    (
                        ("version", INDEX_VERSION),
                        ("catalog_fingerprint", self._catalog_fingerprint()),
                        ("product_count", str(len(seen_asins))),
                    ),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            if not seen_asins:
                raise ValueError(f"Catalog is empty: {self.catalog_path}")

    def _load_stats(self: CatalogRetriever) -> None:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(rating_number), 0) AS max_count "
            "FROM products"
        ).fetchone()
        self.product_count = int(row["count"])
        self._max_rating_count = max(1, int(row["max_count"]))
