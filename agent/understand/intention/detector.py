"""Purpose: recognize Buying / Browsing / Override / Boundary and apply override.

Input: SessionState plus a stripped message.
Output: updates scenario_hint, gate_open, intent_version, legacy_hints; turn-1 buying also writes the first constraint.
Role: decides the conversion gate and which intent version retrieval should use. A turn-1 template match ends observation for this turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import add_constraint
from .parsers import (
    EXPLORING_RE,
    INITIAL_OTHER_RE,
    KEY_REQUIREMENT_RE,
    OVERRIDE_RE,
    OVERRIDE_SIGNAL_RE,
    OVERRIDE_VALUE_RE,
)

if TYPE_CHECKING:
    from ..state.session import SessionState


class IntentionDetector:
    """Stage 2: classify the active shopping scenario.

    Turn-1 templates also write category and the first constraint; later
    override detection only runs after attribute capture so catalog prose
    containing words such as ``instead`` is not treated as an intent reset.
    """

    def apply_turn1(self, state: SessionState, value: str) -> bool:
        return apply_turn1_template(state, value)

    def apply_override(self, state: SessionState, value: str) -> bool:
        return apply_override_message(state, value)


def apply_override(state: SessionState, new_value: str | None) -> None:
    state.intent_version += 1
    state.override_seen = True
    state.scenario_hint = "intent_override"
    state.gate_open = True
    state.legacy_hints.clear()
    state.excluded_asins.clear()
    state.shown_asins.clear()
    if new_value:
        add_constraint(state, new_value)


def apply_turn1_template(state: SessionState, value: str) -> bool:
    """Route the official first message. True means the observation is complete."""

    match = KEY_REQUIREMENT_RE.match(value)
    if match:
        state.category = match.group(1).strip()
        state.scenario_hint = "buying"
        state.gate_open = True
        add_constraint(state, match.group(2))
        return True
    match = EXPLORING_RE.match(value)
    if match:
        state.category = match.group(1).strip()
        state.scenario_hint = "exploring"
        state.gate_open = True
        return True
    match = INITIAL_OTHER_RE.match(value)
    if match:
        state.category = match.group(1).strip()
        state.scenario_hint = "override_pending"
        state.gate_open = False
        hint = match.group(2).strip(" .")
        if hint:
            state.legacy_hints.append(hint)
        return True
    return False


def apply_override_message(state: SessionState, value: str) -> bool:
    """Exact override syntax is always accepted; looser evidence is gated."""

    override = OVERRIDE_RE.search(value)
    override_signal = OVERRIDE_SIGNAL_RE.search(value)
    generic_value = OVERRIDE_VALUE_RE.search(value)
    explicit_earlier_preference = "ignore my earlier preference" in value.casefold()
    should_override = bool(
        override
        or explicit_earlier_preference
        or (
            override_signal
            and (
                state.scenario_hint == "override_pending"
                or generic_value is not None
            )
        )
    )
    if not should_override:
        return False
    extracted = override.group(1) if override else None
    if extracted is None and generic_value:
        extracted = generic_value.group(1)
    apply_override(state, extracted)
    return True
