"""Purpose: shared surface, number, and operator helpers for slot grounding.

Input: raw strings, amounts, and the user message.
Output: cleaned spans, parsed numbers, and grounded surfaces.
Role: attribute handlers do not reimplement span or digit checks.
"""

from __future__ import annotations

import re

from ..schema import span_grounded
from ....domain import canonical
from .types import ConstraintOp

_AMOUNT_RE = re.compile(r"(?:\$|usd\s*)?(\d+(?:\.\d+)?)", re.IGNORECASE)
_UNDER_RE = re.compile(r"\b(under|below|less|max|at most|no more)\b", re.IGNORECASE)
_OVER_RE = re.compile(r"\b(over|above|more|min|at least|no less)\b", re.IGNORECASE)


def clean_surface(value: object) -> str:
    return str(value or "").strip(" \t\n.;")


def fold_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().strip())


def format_amount(amount: float) -> str:
    if amount == int(amount):
        return str(int(amount))
    return str(amount)


def amount_in_message(amount: float, message: str) -> bool:
    """True when the numeric token appears in the message (not as a longer number)."""

    token = re.escape(format_amount(amount))
    pattern = re.compile(rf"(?<![\d.]){token}(?![\d.])")
    return bool(pattern.search(message) or pattern.search(canonical(message)))


def parse_amount(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    match = _AMOUNT_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def infer_op(surface: str, tagged_op: str | None = None) -> ConstraintOp:
    if tagged_op in {"<", "<="}:
        return "lte"
    if tagged_op in {">", ">="}:
        return "gte"
    if _UNDER_RE.search(surface):
        return "lte"
    if _OVER_RE.search(surface):
        return "gte"
    return "eq"


def grounded_number(value: object, message: str) -> float | None:
    amount = parse_amount(value)
    if amount is not None and amount_in_message(amount, message):
        return amount
    return None


def ground_surface(
    surface: str,
    message: str,
    *,
    amount: float | None = None,
    extras: tuple[str, ...] = (),
) -> str | None:
    for candidate in (surface, *extras):
        cleaned = clean_surface(candidate)
        if cleaned and span_grounded(cleaned, message):
            return cleaned
    if amount is not None and amount_in_message(amount, message):
        return format_amount(amount)
    return None


def number_spans(text: str, amount: float | None) -> list[tuple[int, int]]:
    text = text or ""
    spans: list[tuple[int, int]] = []
    if amount is not None:
        token = re.escape(format_amount(amount))
        pattern = re.compile(rf"(?<![\d.]){token}(?![\d.])")
        spans = [match.span() for match in pattern.finditer(text)]
    if not spans:
        spans = [match.span(1) for match in _AMOUNT_RE.finditer(text)]
    return spans
