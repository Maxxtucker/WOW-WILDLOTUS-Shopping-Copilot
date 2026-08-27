"""Purpose: extract category, locked constraints, and override from one message.

Input: stripped message; extract_constraints also reads SessionState for semicolon restore.
Output: CategoryHit | constraint strings | OverrideHit; None/empty when the sentence has none.
Role: protocol-regex toy. Does not write SessionState. Empty simulator replies are simply misses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain import canonical
from ..attributes.lookup import resolve_matters_pieces
from ..attributes.parsers import MATTERS_RE
from ..intention.parsers import (
    EXPLORING_RE,
    GENERIC_CATEGORY_RE,
    INITIAL_OTHER_RE,
    KEY_REQUIREMENT_RE,
    OVERRIDE_RE,
    OVERRIDE_SIGNAL_RE,
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

    return []


def parse_override(message: str, *, gate_closed: bool) -> OverrideHit | None:
    override = OVERRIDE_RE.search(message)
    override_signal = OVERRIDE_SIGNAL_RE.search(message)
    generic_value = OVERRIDE_VALUE_RE.search(message)
    explicit_earlier_preference = "ignore my earlier preference" in message.casefold()
    should_override = bool(
        override
        or explicit_earlier_preference
        or (override_signal and (gate_closed or generic_value is not None))
    )
    if not should_override:
        return None
    extracted = override.group(1) if override else None
    if extracted is None and generic_value:
        extracted = generic_value.group(1)
    return OverrideHit(extracted)


def colon_fallback(state: SessionState, message: str) -> list[str]:
    lowered = message.casefold()
    if not state.last_ask or any(marker in lowered for marker in _SKIP_COLON_MARKERS):
        return []
    tail = message.rsplit(":", 1)[-1]
    pieces = [item.strip() for item in tail.split(";") if len(canonical(item)) >= 3]
    if not (0 < len(pieces) <= 2):
        return []
    return pieces
