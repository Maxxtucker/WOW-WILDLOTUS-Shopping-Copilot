"""Purpose: open the conversion gate after an override writeback.

Input: SessionState plus an optional new constraint string.
Output: updates gate_open, intent_version, leftover hints, exclusions.
Role: used by the intention router. Does not classify override.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import add_constraint

if TYPE_CHECKING:
    from .session import SessionState


def open_conversion_gate(state: SessionState) -> None:
    """Enable conversion and drop leftover / miss evidence from the old intent."""

    state.intent_version += 1
    state.override_seen = True
    state.gate_open = True
    state.legacy_hints.clear()
    state.excluded_asins.clear()
    state.shown_asins.clear()


def apply_override(state: SessionState, new_value: str | None) -> None:
    open_conversion_gate(state)
    if new_value:
        add_constraint(state, new_value)
