"""Purpose: write shopping constraints from the message into SessionState.

Input: SessionState, message text.
Output: active_constraints, disclosed, no_preference, boundary_seen, and related fields.
Role: hard/soft filters for retrieve; which attributes clarification should stop asking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import canonical
from .lookup import resolve_matters_pieces
from .parsers import MATTERS_RE, NO_ADDITIONAL_RE, NO_PREFERENCE_RE

if TYPE_CHECKING:
    from ..state.session import SessionState


class AttributeCapture:
    """Stage 3: turn free-text evidence into typed constraints."""

    def apply(self, state: SessionState, message: str) -> SessionState:
        capture_reply_attributes(state, message.strip())
        return state


def add_constraint(state: SessionState, value: str, *, disclosed: bool = True) -> None:
    cleaned = value.strip(" \t\n.;")
    key = canonical(cleaned)
    if not key:
        return
    if key not in {canonical(item) for item in state.active_constraints}:
        state.active_constraints.append(cleaned)
    if disclosed:
        state.disclosed.add(key)


def capture_no_additional(state: SessionState, value: str) -> bool:
    no_additional = NO_ADDITIONAL_RE.search(value)
    if not no_additional:
        return False
    attribute = no_additional.group(1).casefold()
    state.no_preference.add(attribute)
    state.last_reply_no_additional = True
    return True


def capture_no_preference(state: SessionState, value: str) -> bool:
    no_preference = NO_PREFERENCE_RE.search(value)
    if not no_preference:
        return False
    attribute = no_preference.group(1).casefold()
    state.boundary_seen = True
    state.scenario_hint = "boundary"
    # Boundary's first answer is deliberately uninformative.  Do not
    # permanently ban ``other`` because asking it again reveals data.
    if attribute != "other":
        state.no_preference.add(attribute)
    return True


def capture_matters(state: SessionState, value: str) -> bool:
    matters = MATTERS_RE.search(value)
    if not matters:
        return False
    payload = matters.group(1).strip(" .")
    pieces = resolve_matters_pieces(state, payload)
    for piece in pieces:
        add_constraint(state, piece)
    if pieces:
        state.informative_replies += 1
        state.last_reply_informative = True
    return True


def capture_colon_paraphrase(state: SessionState, value: str) -> bool:
    if not state.last_ask or any(
        marker in value.casefold()
        for marker in ("not quite right", "use your judgment", "no preference")
    ):
        return False
    tail = value.rsplit(":", 1)[-1]
    pieces = [item.strip() for item in tail.split(";") if len(canonical(item)) >= 3]
    if not (0 < len(pieces) <= 2):
        return False
    for piece in pieces:
        add_constraint(state, piece)
    state.informative_replies += 1
    state.last_reply_informative = True
    return True


def capture_turn1_generic_fallback(state: SessionState, value: str) -> None:
    """Recover a coarse shopping phrase when no official turn-1 template matched."""

    from ..intention.parsers import GENERIC_CATEGORY_RE

    generic_category = GENERIC_CATEGORY_RE.search(value)
    if generic_category:
        state.category = generic_category.group(1).strip()
    if any(word in value.casefold() for word in ("requirement", "must have", "must-have")):
        tail = value.rsplit(":", 1)[-1].strip(" .")
        if tail and tail != value:
            add_constraint(state, tail)


def capture_reply_attributes(state: SessionState, value: str) -> bool:
    """Parse simulator answers. Returns True when the message is fully consumed."""

    if capture_no_additional(state, value):
        return True
    if capture_no_preference(state, value):
        return True
    if capture_matters(state, value):
        return True
    return False
