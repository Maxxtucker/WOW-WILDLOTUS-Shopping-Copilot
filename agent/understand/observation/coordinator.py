"""Purpose: apply category, constraints, then override in a fixed order every turn.

Input: SessionState, this turn's message.
Output: SessionState updated in place, including Buying/Browsing track.
Role: catalog copy may contain instead/forget; locked constraints are applied before override.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import add_constraint
from ..intention.detector import apply_override
from ...domain import canonical
from .classify import CategoryHit, colon_fallback
from .hybrid import hybrid_extract
from .schema import ObservationExtract, infer_track
from .slots.merge import merge_or_slot
from .slots.types import OR_ATTRIBUTES

if TYPE_CHECKING:
    from ..state.session import SessionState


class ObservationCoordinator:
    """Compose extractors without changing parse order."""

    def apply(self, state: SessionState, message: str) -> SessionState:
        observe(state, message)
        return state


def observe(state: SessionState, message: str) -> None:
    value = message.strip()
    extract = hybrid_extract(state, value)
    _apply_extract(state, value, extract)


def _apply_extract(state: SessionState, value: str, extract: ObservationExtract) -> None:
    if extract.empty:
        return

    _remember_slots(state, extract)

    wrote_constraints = False
    if extract.constraints:
        for piece in extract.constraints:
            add_constraint(state, piece)
        state.informative_replies += 1
        state.last_reply_informative = True
        if extract.category:
            state.category = extract.category
        wrote_constraints = True
        # Regex path: catalog features may contain instead/forget. Stop before override.
        if extract.source != "llm" or not extract.override:
            _set_track(state, extract, locked=True)
            return

    if extract.category and not wrote_constraints:
        _apply_category(
            state,
            CategoryHit(extract.category, extract.provisional_hint),
        )

    if extract.override:
        apply_override(state, extract.override_value)
        _set_track(state, extract, locked=True)
        return

    if extract.source != "llm" and not wrote_constraints:
        pieces = colon_fallback(state, value)
        if pieces:
            for piece in pieces:
                add_constraint(state, piece)
            state.informative_replies += 1
            state.last_reply_informative = True
            _set_track(state, extract, locked=True)
            return

    _set_track(state, extract, locked=wrote_constraints)


def _remember_slots(state: SessionState, extract: ObservationExtract) -> None:
    if not extract.slots:
        return
    for slot in extract.slots:
        if slot.attribute in OR_ATTRIBUTES:
            index = next(
                (
                    position
                    for position, existing in enumerate(state.typed_constraints)
                    if existing.attribute == slot.attribute
                ),
                None,
            )
            if index is None:
                state.typed_constraints.append(slot)
            else:
                state.typed_constraints[index] = merge_or_slot(
                    state.typed_constraints[index], slot
                )
            continue
        key = (slot.attribute, canonical(slot.surface))
        if any(
            existing.attribute == slot.attribute
            and canonical(existing.surface) == key[1]
            for existing in state.typed_constraints
        ):
            continue
        state.typed_constraints.append(slot)


def _apply_category(state: SessionState, hit: CategoryHit) -> None:
    state.category = hit.category
    if not hit.provisional_hint:
        return
    state.gate_open = False
    if hit.provisional_hint not in state.legacy_hints:
        state.legacy_hints.append(hit.provisional_hint)


def _set_track(
    state: SessionState,
    extract: ObservationExtract,
    *,
    locked: bool,
) -> None:
    track = infer_track(extract, locked=locked)
    if track:
        state.track = track
