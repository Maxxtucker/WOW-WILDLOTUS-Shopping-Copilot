"""Purpose: apply an override: open the conversion gate and replace legacy hints.

Input: SessionState plus an optional new constraint string.
Output: updates gate_open, intent_version, legacy_hints, exclusions.
Role: conversion-gate writeback. Parse order lives in observation.classify / coordinator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import add_constraint

if TYPE_CHECKING:
    from ..state.session import SessionState


def apply_override(state: SessionState, new_value: str | None) -> None:
    state.intent_version += 1
    state.override_seen = True
    state.gate_open = True
    state.legacy_hints.clear()
    state.excluded_asins.clear()
    state.shown_asins.clear()
    if new_value:
        add_constraint(state, new_value)
