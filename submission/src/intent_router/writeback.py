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
    from .llm import OverrideDecision


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


def delta_attribute_names(delta: ObservationExtract | None) -> set[str]:
    """Attribute names present on this turn's extract."""

    if delta is None or delta.empty:
        return set()
    names: set[str] = set()
    for slot in delta.slots:
        name = str(getattr(slot, "attribute", "") or "").strip()
        if name:
            names.add(name)
    if (delta.category or "").strip():
        names.add("category")
    for piece in delta.constraints:
        names.add(classify_constraint(piece))
    return names


def delta_has_category(delta: ObservationExtract | None) -> bool:
    """True when this turn's extract names a category."""

    return "category" in delta_attribute_names(delta)


def incoming_category(delta: ObservationExtract | None) -> str:
    """Category surface from this turn's extract, if any."""

    if delta is None or delta.empty:
        return ""
    raw = (delta.category or "").strip()
    if raw:
        return raw
    for slot in delta.slots:
        name = str(getattr(slot, "attribute", "") or "").strip()
        surface = str(getattr(slot, "surface", "") or "").strip()
        if name == "category" and surface:
            return surface
    return ""


def clear_typed(state: SessionState) -> None:
    """Drop every committed typed constraint and leftover hint."""

    state.active_constraints.clear()
    state.typed_constraints.clear()
    state.legacy_hints.clear()
    state.category = None


def drop_typed(state: SessionState, names: set[str]) -> None:
    """Remove committed slots and strings for the given attribute names."""

    if not names:
        return
    state.typed_constraints = [
        slot for slot in state.typed_constraints if slot.attribute not in names
    ]
    state.active_constraints = [
        piece
        for piece in state.active_constraints
        if classify_constraint(piece) not in names
    ]
    if "category" in names:
        state.category = None
        _sync_primary_category(state)


def finish_override_gate(state: SessionState) -> None:
    """Open the conversion gate and drop the leftover ranking list."""

    open_conversion_gate(state)
    state.last_ranked.clear()
    # Raw-text retrieval must not replay language from the superseded intent.
    state.current_intent_messages = [state.latest_message] if state.latest_message else []


def apply_override_decision(state: SessionState, decision: OverrideDecision) -> None:
    """L1 clears all then apply_delta; L2 drops delta fields then apply_delta."""

    if decision.level == 1:
        # A shopper can fully replace the stated preferences without changing
        # the product family (the official override utterance commonly does
        # exactly this).  Do not throw away the only retrieval anchor unless
        # the new turn actually names a replacement category.
        keeps_category = not delta_has_category(state.turn_delta)
        category_slots = (
            [slot for slot in state.typed_constraints if slot.attribute == "category"]
            if keeps_category
            else []
        )
        category = state.category if keeps_category else None
        clear_typed(state)
        if category_slots:
            state.typed_constraints.extend(category_slots)
            _sync_primary_category(state, fallback=category)
        elif category:
            state.category = category
        apply_delta(state)
        finish_override_gate(state)
        return
    if decision.level == 2:
        drop_typed(state, delta_attribute_names(state.turn_delta))
        apply_delta(state)
        finish_override_gate(state)


def replace_with_delta(state: SessionState) -> None:
    """L1 path: clear all typed memory, apply this turn's delta, open the gate."""

    clear_typed(state)
    apply_delta(state)
    finish_override_gate(state)


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
