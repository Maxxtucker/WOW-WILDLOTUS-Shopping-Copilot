"""Purpose: independent index-side copy of intent_card / classify_constraint.

Input: catalog product dict or constraint string.
Output: card / attribute name / normalized text aligned with the official evaluator.
Role: index build does not import agent.domain, so check_parity can compare both sides.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence


INDEX_VERSION = "agent-retrieval-v4"

SEARCH_FIELDS = (
    "title",
    "categories",
    "features",
    "details",
    "store",
    "description",
)

# These weights favor concise identity and category fields over verbose copy.
# SQLite's bm25() receives one additional zero weight for parent_asin.
DEFAULT_FIELD_WEIGHTS = {
    "title": 6.0,
    "categories": 5.0,
    "features": 3.0,
    "details": 1.0,
    "store": 2.0,
    "description": 0.8,
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


def text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(str(item) for item in value)
    return str(value)


def flatten_values(value: object) -> list[str]:
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


def clean_constraint(value: str, limit: int = 180) -> str:
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


def normalise_attribute(attribute: object) -> str:
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


def ordered_unique(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_constraint(str(value))
        key = normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return tuple(result)


def category_values(product: Mapping[str, object]) -> tuple[str, ...]:
    raw = product.get("categories") or []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raw = [raw]
    values: list[str] = [coarse_category(raw)]
    for item in raw:
        values.append(str(item))
        values.extend(part.strip() for part in str(item).split(",") if part.strip())
    return ordered_unique(values)


def intent_card(product: Mapping[str, object], limit: int = 180) -> dict[str, object]:
    """Reproduce ``evaluator.local_evaluator.intent_card`` exactly.

    This small public helper is useful in regression tests and keeps the
    retrieval index explicitly coupled to the released simulator protocol.
    """

    title = clean_constraint(str(product.get("title") or "product"), limit)
    candidates = [
        *flatten_values(product.get("features")),
        *flatten_values(product.get("details")),
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
            clean_constraint(item, limit)
            for item in candidates
            if clean_constraint(item, limit)
        )
    )
    if not cleaned:
        cleaned = [title]
    return {
        "target_category": title,
        "hard_constraints": cleaned[:2],
        "soft_preferences": cleaned[2:4] or cleaned[:1],
    }


# Private aliases kept so moved call sites can stay close to the original names.
_text = text
_flatten_values = flatten_values
_clean_constraint = clean_constraint
_normalise_attribute = normalise_attribute
_ordered_unique = ordered_unique
_category_values = category_values
