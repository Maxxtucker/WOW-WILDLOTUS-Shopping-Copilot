"""Purpose: coerce a raw constraint item into a typed ParsedItem.

Input: one LLM constraint object or tagged/plain string.
Output: ParsedItem with a slot attribute name, or None.
Role: attribute handlers never parse JSON shape; they only ground a parsed item.
"""

from __future__ import annotations

import re
from typing import Any

from ....domain import ALLOWED_ATTRIBUTES, classify_constraint
from .text import clean_surface, format_amount, infer_op, parse_amount
from .types import ConstraintOp, ParsedItem

SLOT_ATTRIBUTES = frozenset(ALLOWED_ATTRIBUTES)
ATTRIBUTE_ALIASES = {
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
    "use": "use_case",
    "use cases": "use_case",
}
_TAGGED_RE = re.compile(
    r"^(?P<attr>category|material|color|colour|size|style|brand|budget|"
    r"feature|use_case|use|other)\s*"
    r"(?P<op><=|>=|=|:|<|>)\s*"
    r"(?P<value>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_string_list(value: object) -> tuple[str, ...]:
    """Accept a string or a JSON list of strings. Empty pieces are dropped."""

    if value is None or value == "":
        return ()
    if isinstance(value, str):
        cleaned = clean_surface(value)
        return (cleaned,) if cleaned else ()
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for piece in value:
            cleaned = clean_surface(piece)
            if cleaned:
                items.append(cleaned)
        return tuple(items)
    cleaned = clean_surface(value)
    return (cleaned,) if cleaned else ()


def normalise_slot_attribute(attribute: object) -> str:
    candidate = str(attribute or "").strip().casefold().replace("-", "_")
    candidate = ATTRIBUTE_ALIASES.get(candidate, candidate)
    if candidate in SLOT_ATTRIBUTES:
        return candidate
    if candidate:
        mapped = classify_constraint(candidate)
        if mapped in SLOT_ATTRIBUTES:
            return mapped
    return "other"


def coerce_is_hard(value: object, *, default: bool = True) -> bool:
    """True unless the payload clearly marks a soft preference."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "1", "hard", "yes"}:
        return True
    if text in {"false", "0", "soft", "no"}:
        return False
    return default


def parse_constraint_item(item: Any) -> ParsedItem | None:
    """Return a parsed constraint, or None when there is no surface."""

    if isinstance(item, dict):
        attribute = normalise_slot_attribute(item.get("attribute") or item.get("name"))
        surface = clean_surface(
            item.get("surface") or item.get("value") or item.get("text") or ""
        )
        canonical_hints = parse_string_list(item.get("canonical"))
        alt_surfaces = parse_string_list(item.get("surfaces"))
        amount = parse_amount(item.get("amount") if "amount" in item else surface)
        raw_op = item.get("op")
        op: ConstraintOp | None = None
        if raw_op in {"lte", "gte", "eq"}:
            op = raw_op
        elif attribute in {"budget", "size"}:
            op = infer_op(surface)
        if not surface and amount is not None:
            surface = format_amount(amount)
        if not surface and not alt_surfaces:
            return None
        extras = tuple(
            extra
            for extra in (
                clean_surface(item.get("value")),
                format_amount(amount) if amount is not None else "",
                *alt_surfaces,
            )
            if extra and extra != surface
        )
        return ParsedItem(
            attribute,
            surface,
            canonical_hints,
            amount,
            op,
            extras,
            item,
            alt_surfaces,
            coerce_is_hard(item.get("is_hard")),
        )

    if item is None:
        return None
    text = str(item).strip()
    if not text:
        return None
    tagged = _TAGGED_RE.match(text)
    if tagged:
        attribute = normalise_slot_attribute(tagged.group("attr"))
        tagged_op = tagged.group("op")
        rhs = clean_surface(tagged.group("value"))
        amount = parse_amount(rhs) if attribute in {"budget", "size"} else None
        op = infer_op(text, tagged_op) if attribute in {"budget", "size"} else None
        surface = rhs or text
        extras = (text,) if text != surface else ()
        return ParsedItem(attribute, surface, (), amount, op, extras, item)
    attribute = classify_constraint(text)
    if attribute not in SLOT_ATTRIBUTES:
        attribute = "other"
    amount = parse_amount(text) if attribute in {"budget", "size"} else None
    op = infer_op(text) if attribute in {"budget", "size"} and amount is not None else None
    return ParsedItem(attribute, text, (), amount, op, (), item)
