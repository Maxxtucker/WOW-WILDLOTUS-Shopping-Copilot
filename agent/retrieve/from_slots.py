"""Purpose: build retrieve signals from SessionState.typed_constraints.

Input: SessionState (typed slots, or active_constraints when slots are empty).
Output: (attribute, values) groups, BM25 terms, optional budget interval, preferred soft pairs.
Role: retrieve's view of needs. Hard groups feed the router probe and required scoring; soft pairs only preferred-score. Not stored on SessionState.
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


def uses_search_aliases(state: SessionState) -> bool:
    """Regex-like slots have no closed canonicals; keep response_only signatures."""

    return any(
        slot.canonical
        for slot in state.typed_constraints
        if slot.attribute not in {"category", "budget"}
    )


def _groups_from_slots(
    slots: list[ConstraintSlot] | tuple[ConstraintSlot, ...],
    *,
    skip_budget_interval: bool = False,
) -> tuple[ConstraintGroup, ...]:
    """OR values of the same attribute; AND across attributes."""

    by_attr: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for slot in slots:
        if skip_budget_interval and slot.attribute == "budget" and slot.amount is not None:
            continue
        values = slot_search_values(slot)
        if not values:
            continue
        bucket = by_attr.setdefault(slot.attribute, [])
        used = seen.setdefault(slot.attribute, set())
        for value in values:
            key = value.casefold()
            if not value or key in used:
                continue
            used.add(key)
            bucket.append(value)
    return tuple((attribute, tuple(values)) for attribute, values in by_attr.items() if values)


def hard_slots(state: SessionState) -> list[ConstraintSlot]:
    return [slot for slot in state.typed_constraints if slot.is_hard]


def soft_slots(state: SessionState) -> list[ConstraintSlot]:
    return [slot for slot in state.typed_constraints if not slot.is_hard]


def constraint_groups(state: SessionState) -> tuple[ConstraintGroup, ...]:
    """Hard typed slots win. Empty slots fall back to active_constraints (not leftover).

    When typed rows exist, a soft-only table is not a string-path fallback.
    """

    if uses_typed_slots(state):
        return _groups_from_slots(hard_slots(state))
    return tuple(
        (classify_constraint(item), (item,))
        for item in state.active_constraints
        if str(item).strip()
    )


def preferred_groups(state: SessionState) -> tuple[ConstraintGroup, ...]:
    """Soft slots. Same-attribute values are OR for scoring, never an exact prune."""

    return _groups_from_slots(soft_slots(state))


def preferred_pairs(state: SessionState) -> tuple[tuple[str, str], ...]:
    return tuple(
        (attribute, value)
        for attribute, values in preferred_groups(state)
        for value in values
    )


def constraint_pairs(state: SessionState) -> tuple[tuple[str, str], ...]:
    """Flattened (attribute, value) view of ``constraint_groups``."""

    return tuple(
        (attribute, value)
        for attribute, values in constraint_groups(state)
        for value in values
    )


def query_terms(state: SessionState) -> tuple[str, ...]:
    """BM25 terms: hard and soft search values, else active constraint strings."""

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
    return tuple(state.active_constraints)


def session_budget(
    state: SessionState, *, hard_only: bool = True
) -> tuple[float | None, float | None] | None:
    """Budget interval from typed amount/op slots. None means use string required."""

    if not state.typed_constraints:
        return None
    lo: float | None = None
    hi: float | None = None
    found = False
    for slot in state.typed_constraints:
        if slot.attribute != "budget" or slot.amount is None:
            continue
        if hard_only and not slot.is_hard:
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
    """Hard groups plus structured hard budget. Budget slots are not double-counted."""

    groups = constraint_groups(state)
    budget = session_budget(state, hard_only=True)
    if budget is not None:
        groups = tuple(group for group in groups if group[0] != "budget")
    groups = tuple(group for group in groups if group[0] != "category")
    return groups, budget


def exact_pool_groups(state: SessionState) -> tuple[ConstraintGroup, ...]:
    """Hard signals to intersect, including hard category values (OR).

    Leftover / ``ranking_constraints`` strings are not used here.
    """

    if uses_typed_slots(state):
        return _groups_from_slots(hard_slots(state), skip_budget_interval=True)
    groups = tuple(
        (classify_constraint(item), (item,))
        for item in state.active_constraints
        if str(item).strip()
    )
    if state.category:
        return (("category", (state.category,)), *groups)
    return groups
