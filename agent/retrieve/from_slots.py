"""Purpose: build retrieve signals from SessionState.typed_constraints.

Input: SessionState (typed slots, or ranking_constraints when slots are empty).
Output: (attribute, values) groups, BM25 terms, optional budget interval.
Role: retrieve's view of locked needs. Not stored on SessionState.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain import classify_constraint
from ..understand.observation.slots.text import format_amount
from ..understand.observation.slots.types import ConstraintSlot

if TYPE_CHECKING:
    from ..understand.state.session import SessionState

ConstraintGroup = tuple[str, tuple[str, ...]]


def slot_search_values(slot: ConstraintSlot) -> tuple[str, ...]:
    """Values retrieve should match. Canonical alternatives beat the cited paraphrase."""

    if slot.attribute == "budget":
        if slot.amount is not None:
            return (format_amount(slot.amount),)
        cleaned = slot.surface.strip()
        return (cleaned,) if cleaned else ()
    if slot.attribute == "size":
        if slot.kind == "dimension":
            cleaned = slot.surface.strip()
            return (cleaned,) if cleaned else ()
        if slot.canonical:
            return slot.canonical
        parts: list[str] = []
        if slot.system:
            parts.append(slot.system.upper())
        if slot.amount is not None:
            parts.append(format_amount(slot.amount))
        if parts:
            return (" ".join(parts),)
        cleaned = slot.surface.strip()
        return (cleaned,) if cleaned else ()
    if slot.canonical:
        return slot.canonical
    cleaned = slot.surface.strip()
    return (cleaned,) if cleaned else ()


def slot_search_value(slot: ConstraintSlot) -> str:
    """First search value; kept for single-value callers."""

    values = slot_search_values(slot)
    return values[0] if values else ""


def uses_typed_slots(state: SessionState) -> bool:
    return bool(state.typed_constraints)


def constraint_groups(state: SessionState) -> tuple[ConstraintGroup, ...]:
    """Typed slots win. Empty slots fall back to one AND group per ranking string."""

    if state.typed_constraints:
        groups: list[ConstraintGroup] = []
        for slot in state.typed_constraints:
            values = slot_search_values(slot)
            if values:
                groups.append((slot.attribute, values))
        return tuple(groups)
    return tuple(
        (classify_constraint(item), (item,))
        for item in state.ranking_constraints
        if str(item).strip()
    )


def constraint_pairs(state: SessionState) -> tuple[tuple[str, str], ...]:
    """Flattened (attribute, value) view of ``constraint_groups``."""

    return tuple(
        (attribute, value)
        for attribute, values in constraint_groups(state)
        for value in values
    )


def query_terms(state: SessionState) -> tuple[str, ...]:
    """BM25 terms: every alternative search value, else the locked constraint strings."""

    if state.typed_constraints:
        terms: list[str] = []
        seen: set[str] = set()
        for slot in state.typed_constraints:
            for value in slot_search_values(slot):
                key = value.casefold()
                if value and key not in seen:
                    seen.add(key)
                    terms.append(value)
        return tuple(terms)
    return state.ranking_constraints


def session_budget(state: SessionState) -> tuple[float | None, float | None] | None:
    """Budget interval from typed amount/op slots. None means use string required."""

    if not state.typed_constraints:
        return None
    lo: float | None = None
    hi: float | None = None
    found = False
    for slot in state.typed_constraints:
        if slot.attribute != "budget" or slot.amount is None:
            continue
        found = True
        amount = slot.amount
        if slot.op == "gte":
            lo = amount if lo is None else max(lo, amount)
        elif slot.op == "lte":
            hi = amount if hi is None else min(hi, amount)
        else:
            band_lo, band_hi = amount * 0.8, amount * 1.2
            lo = band_lo if lo is None else min(lo, band_lo)
            hi = band_hi if hi is None else max(hi, band_hi)
    if not found:
        return None
    return (lo, hi)


def required_and_budget(
    state: SessionState,
) -> tuple[tuple[ConstraintGroup, ...], tuple[float | None, float | None] | None]:
    """Required groups plus structured budget. Budget slots are not double-counted."""

    groups = constraint_groups(state)
    budget = session_budget(state)
    if budget is not None:
        groups = tuple(group for group in groups if group[0] != "budget")
    return groups, budget


def exact_pool_groups(state: SessionState) -> tuple[ConstraintGroup, ...]:
    """Signals to intersect. Typed budget is scored as an interval, not an exact key."""

    groups, _budget = required_and_budget(state)
    return groups
