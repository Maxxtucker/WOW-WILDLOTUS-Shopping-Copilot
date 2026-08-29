"""Purpose: commit turn_delta onto SessionState (accumulate or replace).

Input: SessionState whose turn_delta was set by observe.
Output: category, constraints, slots, leftover gate updates.
Role: used after the override LLM decision. Does not classify intention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain import classify_constraint
from ..understand.attributes.capture import add_constraint
from ..understand.observation.classify import CategoryHit
from ..understand.observation.slots.merge import merge_or_attribute_slots
from ..understand.observation.slots.types import ConstraintSlot
from ..understand.state.gate import open_conversion_gate

if TYPE_CHECKING:
    from ..understand.observation.schema import ObservationExtract
    from ..understand.state.session import SessionState


def apply_delta(state: SessionState) -> None:
    """Accumulate this turn's delta onto existing session memory."""

    delta = state.turn_delta
    if delta is None or delta.empty:
        return
    _remember_slots(state, delta)
    wrote_constraints = False
    if delta.constraints:
        for piece in delta.constraints:
            add_constraint(state, piece)
        state.informative_replies += 1
        state.last_reply_informative = True
        wrote_constraints = True
        if delta.category:
            _sync_primary_category(state, fallback=delta.category)
        return
    if delta.category:
        _apply_category(state, CategoryHit(delta.category, delta.provisional_hint))
        _sync_primary_category(state, fallback=delta.category)
        if not wrote_constraints and delta.provisional_hint:
            return


def replace_with_delta(state: SessionState) -> None:
    """Treat delta as the full new intent and open the conversion gate."""

    delta = state.turn_delta
    if delta is None or delta.empty:
        state.active_constraints.clear()
        state.typed_constraints.clear()
        state.legacy_hints.clear()
        state.category = None
        open_conversion_gate(state)
        return
    state.active_constraints.clear()
    state.typed_constraints.clear()
    state.legacy_hints.clear()
    if delta.category:
        state.category = delta.category
    _remember_slots(state, delta)
    if delta.constraints:
        for piece in delta.constraints:
            add_constraint(state, piece)
        state.informative_replies += 1
        state.last_reply_informative = True
    _sync_primary_category(state, fallback=delta.category)
    open_conversion_gate(state)


def _remember_slots(state: SessionState, extract: ObservationExtract) -> None:
    incoming = list(extract.slots)
    if extract.category and not any(slot.attribute == "category" for slot in incoming):
        incoming.append(
            ConstraintSlot(
                attribute="category",
                surface=extract.category,
                is_hard=True,
            )
        )
    if extract.provisional_hint and not any(
        not slot.is_hard
        and slot.surface.strip().casefold() == extract.provisional_hint.strip().casefold()
        for slot in incoming
    ):
        incoming.append(
            ConstraintSlot(
                attribute=classify_constraint(extract.provisional_hint),
                surface=extract.provisional_hint,
                is_hard=False,
            )
        )
    if not incoming:
        return
    merged = merge_or_attribute_slots([*state.typed_constraints, *incoming])
    state.typed_constraints = list(merged)
    _sync_primary_category(state, fallback=extract.category)


def _sync_primary_category(state: SessionState, *, fallback: str | None = None) -> None:
    hard = [
        slot.surface
        for slot in state.typed_constraints
        if slot.attribute == "category" and slot.is_hard and slot.surface.strip()
    ]
    any_cat = [
        slot.surface
        for slot in state.typed_constraints
        if slot.attribute == "category" and slot.surface.strip()
    ]
    if hard:
        # Last hard row is the most specific tree layer (L1 then L2 then L3).
        state.category = hard[-1]
        return
    if any_cat:
        state.category = any_cat[0]
        return
    if fallback:
        state.category = fallback


def _apply_category(state: SessionState, hit: CategoryHit) -> None:
    state.category = hit.category
    if not hit.provisional_hint:
        return
    state.gate_open = False
    if hit.provisional_hint not in state.legacy_hints:
        state.legacy_hints.append(hit.provisional_hint)
