"""Purpose: run turn-1 templates → reply attributes → override in a fixed order.

Input: SessionState, this turn's message.
Output: SessionState updated in place.
Role: catalog copy may contain instead/forget; parse what matters is before intent override.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.capture import (
    capture_colon_paraphrase,
    capture_reply_attributes,
    capture_turn1_generic_fallback,
)
from ..intention.detector import apply_override_message, apply_turn1_template

if TYPE_CHECKING:
    from ..state.session import SessionState


class ObservationCoordinator:
    """Compose intention and attribute capture without changing parse order.

    Catalog features can legally contain words such as ``instead`` or
    ``forget``. Structured ``what matters is`` payloads must be consumed
    before override detection.
    """

    def apply(self, state: SessionState, message: str) -> SessionState:
        observe(state, message)
        return state


def observe(state: SessionState, message: str) -> None:
    value = message.strip()
    if state.turn == 1:
        if apply_turn1_template(state, value):
            return
        # Paraphrase-safe fallback: retain the raw message for BM25 and
        # recover a coarse shopping phrase when possible. The gate stays
        # open unless the explicit override template above was recognized.
        capture_turn1_generic_fallback(state, value)

    # Parse the simulator's structured answers before looking for intent
    # changes.  Catalog values are free text and can legitimately contain
    # words such as "instead", "rather", or "forget"; those words inside
    # a ``what matters is`` payload must remain product constraints.
    if capture_reply_attributes(state, value):
        return
    if apply_override_message(state, value):
        return
    capture_colon_paraphrase(state, value)
