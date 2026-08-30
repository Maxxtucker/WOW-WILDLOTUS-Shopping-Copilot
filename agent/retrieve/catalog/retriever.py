"""Purpose: CatalogRetriever facade: open index, exact lookup, predict simulator replies, BM25 search.

Input: catalog.jsonl path, optional index_path; queries are query/constraints/ASIN.
Output: SearchHit lists, signatures, parent_asin sets, predicted reply tuples.
Role: the only SQLite entry in retrieve. Session code must not run SQL directly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

from .index import IndexMixin
from .protocol_copy import DEFAULT_FIELD_WEIGHTS, SEARCH_FIELDS, normalise_attribute, normalize_text
from .scoring import ScoringMixin
from .search import SearchMixin
from .signatures import value_aliases
from .slots_sidecar import attach_product_slots
from .types import ResponseSignature


class CatalogRetriever(IndexMixin, ScoringMixin, SearchMixin):
    """Fielded BM25 and response-signature index for the frozen catalog.

    Parameters
    ----------
    catalog_path:
        Path to the official JSONL catalog.
    index_path:
        Optional persistent SQLite file.  A catalog size/mtime fingerprint is
        checked before reuse.  ``None`` builds a process-local in-memory index.
    rebuild:
        Force rebuilding a persistent index.
    field_weights:
        Optional per-field BM25 weights; unspecified fields keep the defaults.
    slots_path:
        Optional preprocess sidecar from ``scripts/extract_catalog_slots.py``.
        ``None`` uses ``AGENT_SLOTS_PATH`` / the default cache path. The
        retriever only ATTACH-es that file; it never extracts catalog slots.
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        index_path: str | Path | None = None,
        rebuild: bool = False,
        field_weights: Mapping[str, float] | None = None,
        slots_path: str | Path | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.is_file():
            raise FileNotFoundError(f"Catalog not found: {self.catalog_path}")
        self.index_path = None if index_path is None else Path(index_path)
        if self.index_path is not None:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.field_weights = dict(DEFAULT_FIELD_WEIGHTS)
        if field_weights:
            unknown = set(field_weights) - set(SEARCH_FIELDS)
            if unknown:
                raise ValueError(f"Unknown BM25 fields: {sorted(unknown)}")
            self.field_weights.update(
                {key: float(value) for key, value in field_weights.items()}
            )

        database = ":memory:" if self.index_path is None else str(self.index_path)
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._closed = False
        self._slots_attached = False
        self._slots_path = None
        self._all_parent_asins: frozenset[str] | None = None
        self._configure_connection()
        if rebuild or not self._index_is_current():
            self._build_index()
        self._load_stats()
        self._slots_path = attach_product_slots(
            self.connection,
            self.catalog_path,
            slots_path=slots_path,
        )
        self._slots_attached = self._slots_path is not None

    def __len__(self) -> int:
        return self.product_count

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.connection.close()
                self._closed = True

    def __enter__(self) -> "CatalogRetriever":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_product(self, parent_asin: str) -> dict[str, object] | None:
        """Return a catalog row, or ``None`` when the ID is unknown."""

        with self._lock:
            row = self.connection.execute(
                "SELECT raw_json FROM products WHERE parent_asin = ?",
                (str(parent_asin),),
            ).fetchone()
        if row is None:
            return None
        return json.loads(zlib.decompress(bytes(row["raw_json"])).decode("utf-8"))

    @lru_cache(maxsize=20_000)
    def get_signature(self, parent_asin: str) -> ResponseSignature | None:
        """Return the deterministic response signature for one product."""

        with self._lock:
            row = self.connection.execute(
                "SELECT signature_json FROM products WHERE parent_asin = ?",
                (str(parent_asin),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(
            zlib.decompress(bytes(row["signature_json"])).decode("utf-8")
        )
        return ResponseSignature.from_dict(payload)

    def signature_candidates(
        self,
        attribute: str,
        value: object,
        *,
        response_only: bool = False,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        """Find products with a normalized exact signature value.

        ``response_only=True`` restricts matches to values the simulator can
        actually disclose.  The default searches broader catalog aliases and,
        when a matching preprocess sidecar is ATTACH-ed, ``slots.product_slots``.
        """

        attr = normalise_attribute(attribute)
        # Protocol-response matching must preserve the complete normalized
        # constraint.  Searching all aliases here would make distinct values
        # such as "Leather sole" and "100% Leather" collapse to the generic
        # alias "leather", destroying the response fingerprint.  Broader
        # aliases remain appropriate for the robust catalog-search path.
        aliases = (
            (normalize_text(value),)
            if response_only
            else value_aliases(attr, value)
        )
        if not aliases:
            return ()
        placeholders = ",".join("?" for _ in aliases)
        if response_only:
            parameters: list[object] = [attr, "response", *aliases]
            kind_clause = "kind = ?"
        else:
            parameters = [attr, *aliases]
            kind_clause = "kind IN ('response', 'search')"
        sql = (
            "SELECT DISTINCT parent_asin FROM signature_values "
            f"WHERE attribute = ? AND {kind_clause} AND value_norm IN ({placeholders}) "
            "ORDER BY parent_asin"
        )
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        with self._lock:
            rows = self.connection.execute(sql, parameters).fetchall()
            found = [str(row["parent_asin"]) for row in rows]
            if not response_only and getattr(self, "_slots_attached", False):
                slot_sql = (
                    "SELECT DISTINCT parent_asin FROM slots.product_slots "
                    f"WHERE attribute = ? AND canonical IN ({placeholders}) "
                    "ORDER BY parent_asin"
                )
                slot_parameters: list[object] = [attr, *aliases]
                if limit is not None:
                    slot_sql += " LIMIT ?"
                    slot_parameters.append(max(0, int(limit)))
                slot_rows = self.connection.execute(
                    slot_sql, slot_parameters
                ).fetchall()
                seen = set(found)
                for row in slot_rows:
                    parent_asin = str(row["parent_asin"])
                    if parent_asin not in seen:
                        seen.add(parent_asin)
                        found.append(parent_asin)
        if limit is not None:
            found = found[: max(0, int(limit))]
        return tuple(found)

    def all_parent_asins(self) -> frozenset[str]:
        """Every catalog ASIN. Cached for lenient unknown-attribute sets."""

        cached = self._all_parent_asins
        if cached is not None:
            return cached
        with self._lock:
            rows = self.connection.execute(
                "SELECT parent_asin FROM products"
            ).fetchall()
        result = frozenset(str(row["parent_asin"]) for row in rows)
        self._all_parent_asins = result
        return result

    def asins_with_attribute(
        self,
        attribute: str,
        *,
        response_only: bool = False,
    ) -> set[str]:
        """ASINs that have any indexed value for ``attribute``.

        Uses the same lookup surface as ``signature_candidates``: response
        signatures only when ``response_only``, otherwise response+search and
        (when attached) ``slots.product_slots``.
        """

        attr = normalise_attribute(attribute)
        if response_only:
            sql = (
                "SELECT DISTINCT parent_asin FROM signature_values "
                "WHERE attribute = ? AND kind = 'response'"
            )
            parameters: list[object] = [attr]
        else:
            sql = (
                "SELECT DISTINCT parent_asin FROM signature_values "
                "WHERE attribute = ? AND kind IN ('response', 'search')"
            )
            parameters = [attr]
        with self._lock:
            rows = self.connection.execute(sql, parameters).fetchall()
            found = {str(row["parent_asin"]) for row in rows}
            if not response_only and getattr(self, "_slots_attached", False):
                slot_rows = self.connection.execute(
                    "SELECT DISTINCT parent_asin FROM slots.product_slots "
                    "WHERE attribute = ?",
                    (attr,),
                ).fetchall()
                found.update(str(row["parent_asin"]) for row in slot_rows)
        return found

    def predict_reply(
        self,
        parent_asin: str,
        attribute: str,
        disclosed: Iterable[str] = (),
    ) -> tuple[str, ...]:
        signature = self.get_signature(parent_asin)
        if signature is None:
            return ()
        return signature.expected_reply(attribute, disclosed)

    def partition_by_response(
        self,
        parent_asins: Iterable[str],
        attribute: str,
        disclosed: Iterable[str] = (),
    ) -> dict[tuple[str, ...], tuple[str, ...]]:
        """Group candidate IDs by their predicted reply to ``attribute``."""

        groups: dict[tuple[str, ...], list[str]] = {}
        for parent_asin in parent_asins:
            key = self.predict_reply(str(parent_asin), attribute, disclosed)
            groups.setdefault(key, []).append(str(parent_asin))
        return {key: tuple(values) for key, values in groups.items()}


# Short alias for teams that prefer ``Retriever`` at the integration point.
Retriever = CatalogRetriever
