"""Purpose: extract category and locked constraints from one message.

Input: stripped message; extract_constraints also reads SessionState for semicolon restore.
Output: CategoryHit | constraint strings; None/empty when the sentence has none.
Role: regex extractors only. Does not classify override. hybrid.hybrid_extract decides when to call them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain import canonical
from ..attributes.lookup import resolve_matters_pieces
from ..attributes.parsers import MATTERS_RE
from .patterns import (
    EXPLORING_RE,
    GENERIC_CATEGORY_RE,
    INITIAL_OTHER_RE,
    KEY_REQUIREMENT_RE,
    OVERRIDE_RE,
    OVERRIDE_VALUE_RE,
)

if TYPE_CHECKING:
    from ..state.session import SessionState

# Colon-fallback must not treat official empty replies as constraints.
_SKIP_COLON_MARKERS = (
    "not quite right",
    "use your judgment",
    "no preference",
    "additional preference",
)


@dataclass(frozen=True)
class CategoryHit:
    category: str
    provisional_hint: str | None = None


@dataclass(frozen=True)
class OverrideHit:
    new_value: str | None


def extract_category(message: str) -> CategoryHit | None:
    match = KEY_REQUIREMENT_RE.match(message)
    if match:
        return CategoryHit(match.group(1).strip())
    match = EXPLORING_RE.match(message)
    if match:
        return CategoryHit(match.group(1).strip())
    match = INITIAL_OTHER_RE.match(message)
    if match:
        hint = match.group(2).strip(" .")
        return CategoryHit(match.group(1).strip(), hint or None)
    match = GENERIC_CATEGORY_RE.search(message)
    if match:
        return CategoryHit(match.group(1).strip())
    return None


def extract_constraints(state: SessionState, message: str) -> list[str]:
    match = KEY_REQUIREMENT_RE.match(message)
    if match:
        return [match.group(2).strip(" \t\n.;")]

    matters = MATTERS_RE.search(message)
    if matters:
        payload = matters.group(1).strip(" .")
        return resolve_matters_pieces(state, payload)

    if any(word in message.casefold() for word in ("requirement", "must have", "must-have")):
        tail = message.rsplit(":", 1)[-1].strip(" .")
        if tail and tail != message:
            return [tail]

    need = extract_new_need(message)
    if need:
        return [need]
    return []


def extract_new_need(message: str) -> str | None:
    """New-need span from kit phrasing. Not an override routing bit."""

    match = OVERRIDE_RE.search(message)
    if match:
        cleaned = match.group(1).strip(" \t\n.;")
        return cleaned or None
    match = OVERRIDE_VALUE_RE.search(message)
    if match:
        cleaned = match.group(1).strip(" \t\n.;")
        return cleaned or None
    return None


def parse_override(message: str, *, gate_closed: bool) -> OverrideHit | None:
    """Unused by observe. Kept for import compatibility. Does not route."""

    del gate_closed
    need = extract_new_need(message)
    if need is None:
        return None
    return OverrideHit(need)


def colon_fallback(state: SessionState, message: str) -> list[str]:
    lowered = message.casefold()
    if not state.last_ask or any(marker in lowered for marker in _SKIP_COLON_MARKERS):
        return []
    tail = message.rsplit(":", 1)[-1]
    pieces = [item.strip() for item in tail.split(";") if len(canonical(item)) >= 3]
    if not (0 < len(pieces) <= 2):
        return []
    return pieces
