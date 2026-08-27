"""Purpose: mutable memory for one session (constraints, misses, conversion gate).

Input: session_id / user_profile at reset; later stages mutate fields in place.
Output: ranking_constraints, excluded_asins, gate_open, and related fields for retrieve/decide.
Role: all dialogue state for one session lives here; sessions do not share it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..attributes.lookup import build_reply_lookup


@dataclass
class SessionState:
    session_id: str
    user_profile: dict
    category: str | None = None
    intent_version: int = 0
    gate_open: bool = True
    override_seen: bool = False
    active_constraints: list[str] = field(default_factory=list)
    legacy_hints: list[str] = field(default_factory=list)
    disclosed: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)
    last_ask: str | None = None
    last_slate: list[str] = field(default_factory=list)
    last_gate_open: bool = True
    excluded_asins: set[str] = field(default_factory=set)
    shown_asins: set[str] = field(default_factory=set)
    informative_replies: int = 0
    last_reply_informative: bool = False
    reply_value_lookup: dict[str, tuple[str, ...] | None] = field(default_factory=dict)
    latest_message: str = ""
    message_history: list[str] = field(default_factory=list)
    turn: int = 0

    @property
    def ranking_constraints(self) -> tuple[str, ...]:
        values = [*self.active_constraints]
        if not self.override_seen:
            values.extend(self.legacy_hints)
        return tuple(dict.fromkeys(values))

    def begin_turn(self, message: str, turn: int) -> None:
        """Apply guaranteed previous-miss feedback, then parse this observation."""

        from .lifecycle import begin_turn as _begin_turn

        _begin_turn(self, message, turn)

    def _add_constraint(self, value: str, *, disclosed: bool = True) -> None:
        from ..attributes.capture import add_constraint

        add_constraint(self, value, disclosed=disclosed)

    def _apply_override(self, new_value: str | None) -> None:
        from ..intention.detector import apply_override

        apply_override(self, new_value)

    def observe(self, message: str) -> None:
        from ..observation.coordinator import observe

        observe(self, message)

    def record_action(self, slate: list[str], ask_attribute: str | None) -> None:
        from ...decide.response.writeback import record_action

        record_action(self, slate, ask_attribute)

    def set_reply_options(self, options: list[tuple[str, ...]]) -> None:
        self.reply_value_lookup = build_reply_lookup(options)
