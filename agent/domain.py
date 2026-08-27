"""Purpose: evaluator protocol mirror (intent_card, classify_constraint, canonical, …).

Input: product dict or constraint/category strings.
Output: card / attribute name / normalized text aligned with evaluator.local_evaluator.
Role: state machine and planner use this copy; index build uses the independent catalog.protocol_copy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


ALLOWED_ATTRIBUTES = (
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
)

# ``category`` and ``brand`` are valid API values, but the released simulator's
# constraint classifier never emits them.  They remain available to callers,
# while this ordering favours attributes with useful answer coverage.
QUESTION_ATTRIBUTES = (
    "other",
    "feature",
    "material",
    "color",
    "style",
    "size",
    "use_case",
    "budget",
)

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
SEARCH_FIELDS = ("title", "features", "details", "description", "categories", "store")
MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b",
    re.IGNORECASE,
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
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


def text(value: object) -> str:
    """Flatten a catalog value to readable text without losing dict keys."""

    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def terms(value: str | Iterable[str]) -> list[str]:
    """Return stable, de-duplicated search terms."""

    source = value if isinstance(value, str) else " ".join(value)
    result: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(source.casefold()):
        if len(token) <= 1 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def canonical(value: object) -> str:
    """Normalize messages and constraints for robust equality checks."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^a-z0-9$]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def searchable_text(product: dict) -> str:
    parts: list[str] = []
    for field in SEARCH_FIELDS:
        value = product.get(field)
        if isinstance(value, dict):
            parts.extend(f"{key} {item}" for key, item in value.items())
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).strip()


def flatten_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def clean_constraint(value: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\n")[:limit].rstrip()


def intent_card(product: dict, limit: int = 180) -> dict[str, object]:
    """Reproduce the participant-visible deterministic intent-card generator."""

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


def card_constraints(card: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        str(item)
        for key in ("hard_constraints", "soft_preferences")
        for item in (card.get(key) or [])
    )


def coarse_category(values: Iterable[str]) -> str:
    """Reproduce the evaluator's target-derived initial category string."""

    excluded = {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
    cleaned: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part and part.casefold() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def classify_constraint(value: str) -> str:
    lowered = value.casefold()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if any(material in lowered for material in MATERIALS):
        return "material"
    if any(word in lowered for word in ("color", "black", "white", "blue", "red", "pink", "green")):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work")):
        return "use_case"
    return "feature"


def safe_price(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
