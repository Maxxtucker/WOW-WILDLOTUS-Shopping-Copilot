"""Purpose: write a locked shopping constraint into SessionState.

Input: SessionState, constraint string.
Output: active_constraints and disclosed updated in place.
Role: retrieve reads ranking_constraints; observation.classify finds the strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import canonical

if TYPE_CHECKING:
    from ..state.session import SessionState


def add_constraint(state: SessionState, value: str, *, disclosed: bool = True) -> None:
    cleaned = value.strip(" \t\n.;")
    key = canonical(cleaned)
    if not key:
        return
    if key not in {canonical(item) for item in state.active_constraints}:
        state.active_constraints.append(cleaned)
    if disclosed:
        state.disclosed.add(key)
