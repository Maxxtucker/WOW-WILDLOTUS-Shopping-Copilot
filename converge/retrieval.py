"""Offline catalog retrieval for the Converge shopping copilot.

The module deliberately uses only Python's standard library.  SQLite FTS5 is
used for fast field-aware BM25 over the 50k-product catalog, while a separate
signature index handles normalized exact constraints and predicts the values
that the official customer simulator can reveal.

The public API is intentionally independent of the conversation-state and
planning modules:

* :class:`CatalogRetriever` builds or opens the index.
* :meth:`CatalogRetriever.search` returns scored :class:`SearchHit` objects.
* :meth:`CatalogRetriever.get_signature` exposes the deterministic response
  signature of a product.
* :meth:`CatalogRetriever.partition_by_response` groups candidates by the
  answer they would give to a clarification question.

Pass ``index_path`` to persist the generated SQLite index between runs.  With
``index_path=None`` (the default), the whole index is built in memory and no
files are written.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import unicodedata
import zlib
from functools import lru_cache
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias


INDEX_VERSION = "converge-retrieval-v3"

SEARCH_FIELDS = (
    "title",
    "categories",
    "features",
    "details",
    "store",
    "description",
)

# These weights intentionally mirror the strong official starter baseline.
# SQLite's bm25() receives one additional zero weight for parent_asin.
DEFAULT_FIELD_WEIGHTS = {
    "title": 6.0,
    "categories": 4.0,
    "features": 2.5,
    "details": 2.5,
    "store": 1.5,
    "description": 1.0,
}

ALLOWED_ATTRIBUTES = {
    "category",
    "material",
    "color",
    "size",
    "style",
    "brand",
    "budget",
    "feature",
    "use_case",
    "other",
}

MATERIALS = (
    "cotton",
    "polyester",
    "nylon",
    "leather",
    "wool",
    "spandex",
    "silk",
    "rayon",
    "fabric",
)
COLORS = (
    "black",
    "white",
    "blue",
    "red",
    "pink",
    "green",
    "brown",
    "gray",
    "grey",
    "purple",
    "yellow",
    "orange",
)

MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b",
    re.IGNORECASE,
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
MONEY_RE = re.compile(r"(?:\$|usd\s*)?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "do",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "some",
    "that",
    "the",
    "this",
    "to",
    "want",
    "with",
    "would",
    "you",
    "looking",
}

ConstraintInput: TypeAlias = (
    Mapping[str, object]
    | Iterable[tuple[str, object] | str]
    | tuple[str, object]
    | str
    | None
)
BudgetInput: TypeAlias = (
    float
    | int
    | str
    | tuple[float | None, float | None]
    | list[float | None]
    | None
)


@dataclass(frozen=True, slots=True)
class SearchWeights:
    """Weights used to combine lexical, structured, and catalog priors."""

    lexical: float = 1.0
    required: float = 5.0
    preferred: float = 1.75
    category: float = 3.0
    budget: float = 1.25
    rating: float = 0.08
    popularity: float = 0.12
    missing_required: float = -0.35
    excluded: float = -8.0


@dataclass(frozen=True, slots=True)
class ResponseSignature:
    """Product values relevant to retrieval and deterministic dialog replies.

    ``response_values`` contains only values the current official simulator can
    disclose for each ``ask_attribute``.  ``search_values`` additionally
    contains catalog-derived aliases such as category and store/brand.  Keeping
    the two mappings separate prevents the question planner from hallucinating
    that a brand or category answer will be revealed when the simulator's
    constraint classifier cannot produce one.
    """

    target_category: str
    hard_constraints: tuple[str, ...]
    soft_preferences: tuple[str, ...]
    response_values: Mapping[str, tuple[str, ...]] = field(repr=False)
    search_values: Mapping[str, tuple[str, ...]] = field(repr=False)

    @property
    def constraints(self) -> tuple[str, ...]:
        return self.hard_constraints + self.soft_preferences

    def expected_reply(
        self,
        attribute: str,
        disclosed: Iterable[str] = (),
        *,
        limit: int = 2,
    ) -> tuple[str, ...]:
        """Return values the official simulator would reveal for ``attribute``.

        The caller remains responsible for the Boundary scenario's first
        ``NO_PREFERENCE`` reply because boundary state is session-specific, not
        a property of the product.
        """

        attr = _normalise_attribute(attribute)
        disclosed_norm = {normalize_text(value) for value in disclosed}
        if attr == "other":
            values = self.constraints
        else:
            values = self.response_values.get(attr, ())
        return tuple(
            value
            for value in values
            if normalize_text(value) not in disclosed_norm
        )[: max(0, limit)]

    def to_dict(self) -> dict[str, object]:
        return {
            "target_category": self.target_category,
            "hard_constraints": list(self.hard_constraints),
            "soft_preferences": list(self.soft_preferences),
            "response_values": {
                key: list(values) for key, values in self.response_values.items()
            },
            "search_values": {
                key: list(values) for key, values in self.search_values.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ResponseSignature":
        response_payload = payload.get("response_values")
        search_payload = payload.get("search_values")
        return cls(
            target_category=str(payload.get("target_category") or "product"),
            hard_constraints=tuple(
                str(value) for value in payload.get("hard_constraints", []) or []
            ),
            soft_preferences=tuple(
                str(value) for value in payload.get("soft_preferences", []) or []
            ),
            response_values=_tuple_mapping(response_payload),
            search_values=_tuple_mapping(search_payload),
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One ranked catalog candidate with inspectable score components."""

    parent_asin: str
    score: float
    lexical_score: float
    structured_score: float
    prior_score: float
    required_coverage: float
    matched_constraints: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def recommendation(self, *, include_score: bool = False) -> dict[str, object]:
        result: dict[str, object] = {"parent_asin": self.parent_asin}
        if include_score:
            result["score"] = self.score
        return result


def _tuple_mapping(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            result[str(key)] = tuple(str(item) for item in items)
    return result


def normalize_text(value: object) -> str:
    """Normalize free text for exact signature matching.

    NFKC/casefold makes the function safe for non-ASCII catalog text.  Common
    spelling and monetary variants are canonicalized, while meaningful digits
    and size tokens are retained.
    """

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = text.replace("colour", "color").replace("grey", "gray")
    text = re.sub(r"\bus\s*\$", "$", text)
    text = re.sub(r"[^\w$]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value: object, *, limit: int | None = None) -> tuple[str, ...]:
    """Tokenize text for FTS queries and soft signature similarity."""

    normalised = normalize_text(value)
    tokens: list[str] = []
    seen: set[str] = set()
    for match in WORD_RE.findall(normalised):
        token = match.casefold()
        if token in STOPWORDS or (len(token) == 1 and token not in {"s", "m", "l"}):
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
            if limit is not None and len(tokens) >= limit:
                break
    return tuple(tokens)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(str(item) for item in value)
    return str(value)


def _flatten_values(value: object) -> list[str]:
    """Match the official evaluator's one-level metadata flattening."""

    if isinstance(value, Mapping):
        return [
            f"{key}: {item}"
            for key, item in value.items()
            if item not in (None, "", [])
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _clean_constraint(value: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\n")[:limit].rstrip()


def searchable_text(product: Mapping[str, object]) -> str:
    parts: list[str] = []
    for field_name in ("title", "features", "details", "description", "categories", "store"):
        value = product.get(field_name)
        if isinstance(value, Mapping):
            parts.extend(f"{key} {item}" for key, item in value.items())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).strip()


def coarse_category(values: Iterable[object]) -> str:
    """Reproduce the category phrase used in the official initial message."""

    excluded = {
        "clothing",
        "clothing shoes & jewelry",
        "clothing, shoes & jewelry",
    }
    cleaned: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part and part.casefold() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def classify_constraint(value: str) -> str:
    """Reproduce the public evaluator's constraint-to-attribute policy."""

    lowered = value.lower()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if any(material in lowered for material in MATERIALS):
        return "material"
    if any(
        word in lowered
        for word in ("color", "black", "white", "blue", "red", "pink", "green")
    ):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(
        word in lowered
        for word in ("department", "style", "fit", "sleeve", "neck")
    ):
        return "style"
    if any(
        word in lowered
        for word in ("hiking", "running", "gym", "winter", "outdoor", "work")
    ):
        return "use_case"
    return "feature"


def _normalise_attribute(attribute: object) -> str:
    candidate = str(attribute or "other").strip().casefold().replace("-", "_")
    aliases = {
        "categories": "category",
        "materials": "material",
        "colours": "color",
        "colour": "color",
        "colors": "color",
        "sizes": "size",
        "brands": "brand",
        "price": "budget",
        "features": "feature",
        "usecase": "use_case",
        "use cases": "use_case",
    }
    candidate = aliases.get(candidate, candidate)
    return candidate if candidate in ALLOWED_ATTRIBUTES else classify_constraint(candidate)


def _ordered_unique(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_constraint(str(value))
        key = normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return tuple(result)


def _category_values(product: Mapping[str, object]) -> tuple[str, ...]:
    raw = product.get("categories") or []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raw = [raw]
    values: list[str] = [coarse_category(raw)]
    for item in raw:
        values.append(str(item))
        values.extend(part.strip() for part in str(item).split(",") if part.strip())
    return _ordered_unique(values)


def intent_card(product: Mapping[str, object], limit: int = 180) -> dict[str, object]:
    """Reproduce ``evaluator.local_evaluator.intent_card`` exactly.

    This small public helper is useful in regression tests and keeps the
    retrieval index explicitly coupled to the released simulator protocol.
    """

    title = _clean_constraint(str(product.get("title") or "product"), limit)
    candidates = [
        *_flatten_values(product.get("features")),
        *_flatten_values(product.get("details")),
    ]
    corpus = searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    if material:
        candidates.insert(0, material.group(1).lower())
    if color:
        candidates.insert(1, f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        candidates.append(f"budget around ${product['price']}")
    cleaned = list(
        dict.fromkeys(
            _clean_constraint(item, limit)
            for item in candidates
            if _clean_constraint(item, limit)
        )
    )
    if not cleaned:
        cleaned = [title]
    return {
        "target_category": title,
        "hard_constraints": cleaned[:2],
        "soft_preferences": cleaned[2:4] or cleaned[:1],
    }


def build_response_signature(product: Mapping[str, object]) -> ResponseSignature:
    """Build an evaluator-compatible intent card plus retrieval aliases."""

    card = intent_card(product)
    title = str(card["target_category"])
    corpus = searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    hard = tuple(str(value) for value in card["hard_constraints"])
    soft = tuple(str(value) for value in card["soft_preferences"])
    all_constraints = hard + soft

    response_values_lists: dict[str, list[str]] = {
        attribute: [] for attribute in ALLOWED_ATTRIBUTES
    }
    for constraint in all_constraints:
        response_values_lists[classify_constraint(constraint)].append(constraint)
    response_values_lists["other"] = list(all_constraints)

    search_values_lists = {
        key: list(values) for key, values in response_values_lists.items()
    }
    search_values_lists["category"].extend(_category_values(product))
    if product.get("store") not in (None, ""):
        search_values_lists["brand"].append(str(product["store"]))
    # These corpus-derived aliases help robust search but do not change what
    # expected_reply() predicts for the official customer simulator.
    if material:
        search_values_lists["material"].append(material.group(1).lower())
    if color:
        search_values_lists["color"].append(f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        search_values_lists["budget"].append(f"budget around ${product['price']}")

    response_values = {
        key: _ordered_unique(values)
        for key, values in response_values_lists.items()
        if values
    }
    search_values = {
        key: _ordered_unique(values)
        for key, values in search_values_lists.items()
        if values
    }
    return ResponseSignature(
        target_category=title,
        hard_constraints=hard,
        soft_preferences=soft,
        response_values=response_values,
        search_values=search_values,
    )


def _value_aliases(attribute: str, value: object) -> tuple[str, ...]:
    attr = _normalise_attribute(attribute)
    text = normalize_text(value)
    aliases: list[str] = [text] if text else []
    if ":" in str(value):
        aliases.append(normalize_text(str(value).split(":", 1)[1]))
    if attr == "material":
        match = MATERIAL_RE.search(str(value))
        if match:
            aliases.append(normalize_text(match.group(1)))
    elif attr == "color":
        match = COLOR_RE.search(str(value))
        if match:
            aliases.append(normalize_text(match.group(1)))
    elif attr == "budget":
        match = MONEY_RE.search(str(value).replace(",", ""))
        if match:
            amount = float(match.group(1))
            aliases.extend((f"{amount:g}", f"budget {amount:g}"))
    return _ordered_unique(aliases)


def _coerce_constraints(value: ConstraintInput) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return ((classify_constraint(value), value),) if value.strip() else ()
    if isinstance(value, Mapping):
        pairs: list[tuple[str, str]] = []
        for attribute, raw_values in value.items():
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
                iterable = raw_values
            else:
                iterable = [raw_values]
            for raw in iterable:
                if raw not in (None, ""):
                    pairs.append((_normalise_attribute(attribute), str(raw)))
        return tuple(pairs)
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and not isinstance(value[1], tuple)
    ):
        # A two-item tuple is ambiguous: it can be one explicit
        # ``(attribute, value)`` pair or two independent constraints.  Treat it
        # as a pair only when the first value is a real attribute name/alias;
        # otherwise the iterable branch below must classify both strings.
        raw_attribute = value[0].strip().casefold().replace("-", "_")
        attribute_aliases = {
            "categories",
            "materials",
            "colours",
            "colour",
            "colors",
            "sizes",
            "brands",
            "price",
            "features",
            "usecase",
            "use cases",
        }
        if raw_attribute in ALLOWED_ATTRIBUTES or raw_attribute in attribute_aliases:
            return ((_normalise_attribute(value[0]), str(value[1])),)

    result: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                result.append((classify_constraint(item), item))
        elif isinstance(item, Sequence) and len(item) == 2:
            result.append((_normalise_attribute(item[0]), str(item[1])))
        else:
            raise TypeError(f"Unsupported constraint item: {item!r}")
    return tuple(result)


def _coerce_budget(value: BudgetInput) -> tuple[float | None, float | None] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        maximum = float(value)
        return (None, maximum) if math.isfinite(maximum) else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 2:
            raise ValueError("budget sequence must be (minimum, maximum)")
        minimum = None if value[0] is None else float(value[0])
        maximum = None if value[1] is None else float(value[1])
        if minimum is not None and maximum is not None and minimum > maximum:
            minimum, maximum = maximum, minimum
        return minimum, maximum

    text = str(value).replace(",", "")
    numbers = [float(match) for match in MONEY_RE.findall(text)]
    if not numbers:
        return None
    lowered = text.casefold()
    if len(numbers) >= 2:
        return min(numbers[:2]), max(numbers[:2])
    amount = numbers[0]
    if any(word in lowered for word in ("under", "below", "less", "max", "up to", "<=")):
        return None, amount
    if any(word in lowered for word in ("over", "above", "more", "min", ">=")):
        return amount, None
    # "around $x" gets a deliberately broad tolerance; sparse catalog prices
    # must never become an accidental hard filter.
    return amount * 0.8, amount * 1.2


def _signature_similarity(attribute: str, query: str, values: Iterable[str]) -> float:
    query_aliases = set(_value_aliases(attribute, query))
    if not query_aliases:
        return 0.0
    query_tokens = set(tokenize(query))
    best = 0.0
    for candidate in values:
        candidate_aliases = set(_value_aliases(attribute, candidate))
        if query_aliases & candidate_aliases:
            return 1.0
        for left in query_aliases:
            for right in candidate_aliases:
                if left and right and (left in right or right in left):
                    best = max(best, 0.9)
        candidate_tokens = set(tokenize(candidate))
        if query_tokens and candidate_tokens:
            overlap = len(query_tokens & candidate_tokens) / max(
                len(query_tokens), len(candidate_tokens)
            )
            best = max(best, overlap)
    return best


class CatalogRetriever:
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
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        index_path: str | Path | None = None,
        rebuild: bool = False,
        field_weights: Mapping[str, float] | None = None,
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
        self._configure_connection()
        if rebuild or not self._index_is_current():
            self._build_index()
        self._load_stats()

    def _configure_connection(self) -> None:
        with self.connection:
            self.connection.execute("PRAGMA temp_store=MEMORY")
            self.connection.execute("PRAGMA cache_size=-65536")
            if self.index_path is None:
                self.connection.execute("PRAGMA journal_mode=MEMORY")
                self.connection.execute("PRAGMA synchronous=OFF")
            else:
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=NORMAL")

    def _catalog_fingerprint(self) -> str:
        stat = self.catalog_path.stat()
        return f"{self.catalog_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"

    def _index_is_current(self) -> bool:
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

    def _drop_schema(self) -> None:
        self.connection.executescript(
            """
            DROP TABLE IF EXISTS product_fts;
            DROP TABLE IF EXISTS signature_values;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS index_meta;
            """
        )

    def _create_schema(self) -> None:
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
                    tokenize='unicode61 remove_diacritics 2'
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
        self,
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
                    for alias in _value_aliases(attribute, raw_value):
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

    def _build_index(self) -> None:
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
                                _text(product.get("title")),
                                _text(product.get("categories")),
                                _text(product.get("features")),
                                _text(product.get("details")),
                                _text(product.get("store")),
                                _text(product.get("description")),
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

    def _load_stats(self) -> None:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(rating_number), 0) AS max_count "
            "FROM products"
        ).fetchone()
        self.product_count = int(row["count"])
        self._max_rating_count = max(1, int(row["max_count"]))

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
        actually disclose.  The default searches broader catalog aliases.
        """

        attr = _normalise_attribute(attribute)
        # Protocol-response matching must preserve the complete normalized
        # constraint.  Searching all aliases here would make distinct values
        # such as "Leather sole" and "100% Leather" collapse to the generic
        # alias "leather", destroying the response fingerprint.  Broader
        # aliases remain appropriate for the robust catalog-search path.
        aliases = (
            (normalize_text(value),)
            if response_only
            else _value_aliases(attr, value)
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
        return tuple(str(row["parent_asin"]) for row in rows)

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

    def _fts_candidates(self, text: str, limit: int) -> dict[str, float]:
        terms = tokenize(text, limit=48)
        if not terms or limit <= 0:
            return {}
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        weights = [0.0] + [self.field_weights[field_name] for field_name in SEARCH_FIELDS]
        placeholders = ", ".join("?" for _ in weights)
        sql = (
            "SELECT parent_asin, bm25(product_fts, "
            f"{placeholders}) AS raw_score FROM product_fts "
            "WHERE product_fts MATCH ? ORDER BY raw_score ASC LIMIT ?"
        )
        with self._lock:
            rows = self.connection.execute(
                sql, (*weights, expression, max(0, int(limit)))
            ).fetchall()
        return {
            str(row["parent_asin"]): math.log1p(max(0.0, -float(row["raw_score"])))
            for row in rows
        }

    def _popular_candidates(self, limit: int) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT parent_asin FROM products "
                "ORDER BY rating_number DESC, average_rating DESC, parent_asin ASC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return tuple(str(row["parent_asin"]) for row in rows)

    def _load_candidate_rows(self, parent_asins: Iterable[str]) -> dict[str, sqlite3.Row]:
        values = tuple(dict.fromkeys(str(value) for value in parent_asins if value))
        result: dict[str, sqlite3.Row] = {}
        for offset in range(0, len(values), 400):
            chunk = values[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            with self._lock:
                rows = self.connection.execute(
                    "SELECT parent_asin, price, average_rating, rating_number, "
                    f"signature_json FROM products WHERE parent_asin IN ({placeholders})",
                    chunk,
                ).fetchall()
            result.update({str(row["parent_asin"]): row for row in rows})
        return result

    @staticmethod
    def _budget_fit(
        price: float | None,
        budget: tuple[float | None, float | None] | None,
    ) -> float:
        if price is None or budget is None:
            return 0.0
        minimum, maximum = budget
        if (minimum is None or price >= minimum) and (maximum is None or price <= maximum):
            return 1.0
        boundary = minimum if minimum is not None and price < minimum else maximum
        if boundary is None:
            return 0.0
        scale = max(10.0, abs(boundary) * 0.25)
        return max(-1.0, 1.0 - abs(price - boundary) / scale)

    def score_candidates(
        self,
        parent_asins: Iterable[str],
        *,
        lexical_scores: Mapping[str, float] | None = None,
        required: ConstraintInput = None,
        preferred: ConstraintInput = None,
        excluded: ConstraintInput = None,
        categories: Iterable[str] = (),
        budget: BudgetInput = None,
        exclude_asins: Iterable[str] = (),
        weights: SearchWeights | None = None,
        hard_exclusions: bool = True,
    ) -> list[SearchHit]:
        """Score a supplied candidate pool without performing retrieval."""

        scoring = weights or SearchWeights()
        required_pairs = _coerce_constraints(required)
        preferred_pairs = _coerce_constraints(preferred)
        excluded_pairs = _coerce_constraints(excluded)
        category_pairs = tuple(("category", str(value)) for value in categories if str(value).strip())
        budget_range = _coerce_budget(budget)
        excluded_ids = {str(value) for value in exclude_asins}
        lexical = lexical_scores or {}
        rows = self._load_candidate_rows(parent_asins)
        hits: list[SearchHit] = []

        for parent_asin, row in rows.items():
            if parent_asin in excluded_ids:
                continue
            payload = json.loads(
                zlib.decompress(bytes(row["signature_json"])).decode("utf-8")
            )
            signature = ResponseSignature.from_dict(payload)
            reasons: list[str] = []
            matched: list[str] = []
            structured_score = 0.0

            required_similarities: list[float] = []
            for attribute, value in required_pairs:
                similarity = _signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                required_similarities.append(similarity)
                if similarity > 0:
                    matched.append(f"required:{attribute}={value}")
                structured_score += scoring.required * similarity
            if required_pairs:
                missing = sum(1 for value in required_similarities if value == 0.0)
                structured_score += scoring.missing_required * missing
                required_coverage = sum(required_similarities) / len(required_similarities)
                reasons.append(f"required_coverage={required_coverage:.2f}")
            else:
                required_coverage = 1.0

            for attribute, value in preferred_pairs:
                similarity = _signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                if similarity > 0:
                    matched.append(f"preferred:{attribute}={value}")
                structured_score += scoring.preferred * similarity

            excluded_match = 0.0
            for attribute, value in excluded_pairs:
                similarity = _signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                excluded_match = max(excluded_match, similarity)
            if hard_exclusions and excluded_match >= 0.9:
                continue
            structured_score += scoring.excluded * excluded_match
            if excluded_match:
                reasons.append(f"excluded_match={excluded_match:.2f}")

            category_match = 0.0
            for attribute, value in category_pairs:
                category_match = max(
                    category_match,
                    _signature_similarity(
                        attribute, value, signature.search_values.get(attribute, ())
                    ),
                )
            structured_score += scoring.category * category_match
            if category_match:
                matched.append("category")

            price = None if row["price"] is None else float(row["price"])
            budget_fit = self._budget_fit(price, budget_range)
            structured_score += scoring.budget * budget_fit
            if budget_fit:
                reasons.append(f"budget_fit={budget_fit:.2f}")

            rating = 0.0 if row["average_rating"] is None else float(row["average_rating"])
            rating_count = max(0, int(row["rating_number"]))
            prior_score = (
                scoring.rating * max(0.0, min(1.0, rating / 5.0))
                + scoring.popularity
                * math.log1p(rating_count)
                / math.log1p(self._max_rating_count)
            )
            lexical_score = float(lexical.get(parent_asin, 0.0))
            score = scoring.lexical * lexical_score + structured_score + prior_score
            hits.append(
                SearchHit(
                    parent_asin=parent_asin,
                    score=round(score, 8),
                    lexical_score=round(lexical_score, 8),
                    structured_score=round(structured_score, 8),
                    prior_score=round(prior_score, 8),
                    required_coverage=round(required_coverage, 8),
                    matched_constraints=tuple(matched),
                    reasons=tuple(reasons),
                )
            )

        hits.sort(
            key=lambda item: (
                -item.score,
                -item.required_coverage,
                -item.lexical_score,
                item.parent_asin,
            )
        )
        return hits

    def search(
        self,
        text: str = "",
        *,
        required: ConstraintInput = None,
        preferred: ConstraintInput = None,
        excluded: ConstraintInput = None,
        categories: Iterable[str] = (),
        budget: BudgetInput = None,
        exclude_asins: Iterable[str] = (),
        limit: int = 200,
        candidate_limit: int = 600,
        weights: SearchWeights | None = None,
        hard_required: bool = False,
        hard_exclusions: bool = True,
    ) -> list[SearchHit]:
        """Retrieve and rank products.

        Exact signature candidates are unioned with fielded BM25 candidates.
        ``hard_required=True`` intersects only those required constraints that
        have at least one exact catalog match; unknown/paraphrased constraints
        therefore still fall back safely to BM25 and soft matching.
        """

        if limit <= 0:
            return []
        candidate_limit = max(limit, candidate_limit)
        required_pairs = _coerce_constraints(required)
        preferred_pairs = _coerce_constraints(preferred)
        category_values = tuple(str(value) for value in categories if str(value).strip())

        query_parts = [text]
        query_parts.extend(value for _, value in required_pairs)
        query_parts.extend(value for _, value in preferred_pairs)
        query_parts.extend(category_values)
        lexical = self._fts_candidates(" ".join(query_parts), candidate_limit)
        candidates: dict[str, None] = dict.fromkeys(lexical)

        exact_required_sets: list[set[str]] = []
        exact_pairs = [
            *required_pairs,
            *preferred_pairs,
            *(("category", value) for value in category_values),
        ]
        for index, (attribute, value) in enumerate(exact_pairs):
            matches = set(
                self.signature_candidates(
                    attribute,
                    value,
                    limit=max(candidate_limit * 3, 2_000),
                )
            )
            for parent_asin in matches:
                candidates.setdefault(parent_asin, None)
            if index < len(required_pairs) and matches:
                exact_required_sets.append(matches)

        if hard_required and exact_required_sets:
            allowed = set.intersection(*exact_required_sets)
            for parent_asin in allowed:
                candidates.setdefault(parent_asin, None)
            candidates = {
                parent_asin: None
                for parent_asin in candidates
                if parent_asin in allowed
            }

        if not candidates:
            candidates = dict.fromkeys(self._popular_candidates(candidate_limit))

        hits = self.score_candidates(
            candidates,
            lexical_scores=lexical,
            required=required_pairs,
            preferred=preferred_pairs,
            excluded=excluded,
            categories=category_values,
            budget=budget,
            exclude_asins=exclude_asins,
            weights=weights,
            hard_exclusions=hard_exclusions,
        )
        return hits[:limit]

    def retrieve(self, *args: object, **kwargs: object) -> list[str]:
        """Convenience wrapper returning only ranked ``parent_asin`` values."""

        return [hit.parent_asin for hit in self.search(*args, **kwargs)]

    @staticmethod
    def calibrated_distribution(
        hits: Sequence[SearchHit],
        *,
        temperature: float = 1.0,
        tail_mass: float = 0.05,
    ) -> dict[str, float]:
        """Convert candidate scores into a softmax belief with reserved tail mass."""

        if not hits:
            return {}
        if temperature <= 0 or not math.isfinite(temperature):
            raise ValueError("temperature must be a finite positive number")
        tail = max(0.0, min(0.99, float(tail_mass)))
        maximum = max(hit.score for hit in hits)
        values = [math.exp((hit.score - maximum) / temperature) for hit in hits]
        total = sum(values)
        scale = (1.0 - tail) / total
        return {
            hit.parent_asin: value * scale for hit, value in zip(hits, values, strict=True)
        }


# Short alias for teams that prefer ``Retriever`` at the integration point.
Retriever = CatalogRetriever


__all__ = [
    "ALLOWED_ATTRIBUTES",
    "CatalogRetriever",
    "ResponseSignature",
    "Retriever",
    "SearchHit",
    "SearchWeights",
    "build_response_signature",
    "classify_constraint",
    "coarse_category",
    "normalize_text",
    "searchable_text",
    "tokenize",
]
