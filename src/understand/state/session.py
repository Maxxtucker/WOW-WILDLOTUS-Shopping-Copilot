"""Purpose: mutable memory for one session (constraints, misses, conversion gate, intention).

Input: session_id / user_profile at reset; later stages mutate fields in place.
Output: typed_constraints (NLU), ranking_constraints (regex/kit), preference_tags, excluded_asins, gate_open, intention, recommendation scoring weights, and related fields.
Role: all dialogue state for one session lives here; sessions do not share it.
Retrieve builds search pairs from typed_constraints; they are not stored here.
The intention router writes ``exact_strict`` / ``exact_lenient`` for retrieve.
preference_tags is a reset-time copy of the aggregate profile; semantic ranking
uses it only as weak evidence.
Observe writes only turn_delta; the intention router commits constraints.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..attributes.lookup import build_reply_lookup

if TYPE_CHECKING:
    from ...decide.clarification.utility import RecommendationScoreWeights
    from ..observation.schema import ObservationExtract


def _default_scoring_weights() -> RecommendationScoreWeights:
    from ...decide.clarification.utility import (
        DEFAULT_RECOMMENDATION_SCORE_WEIGHTS,
    )

    return DEFAULT_RECOMMENDATION_SCORE_WEIGHTS


def preference_tags_from_profile(profile: Mapping[str, object] | None) -> tuple[str, ...]:
    """Snapshot preference_tags from the evaluator aggregate profile.

    Missing, null, or non-list values yield an empty tuple. Blank entries are
    dropped. Duplicates are removed case-insensitively, keeping first-seen form.
    """

    raw = None if profile is None else profile.get("preference_tags")
    if not isinstance(raw, list):
        return ()
    seen: set[str] = set()
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(cleaned)
    return tuple(tags)


@dataclass
class SessionState:
    session_id: str
    user_profile: dict
    category: str | None = None
    intention: str | None = None
    intent_version: int = 0
    gate_open: bool = True
    override_seen: bool = False
    active_constraints: list[str] = field(default_factory=list)
    legacy_hints: list[str] = field(default_factory=list)
    disclosed: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)
    last_ask: str | None = None
    last_slate: list[str] = field(default_factory=list)
    last_ranked: list[str] = field(default_factory=list)
    last_gate_open: bool = True
    excluded_asins: set[str] = field(default_factory=set)
    shown_asins: set[str] = field(default_factory=set)
    disclosure_empty: bool | None = None
    informative_replies: int = 0
    last_reply_informative: bool = False
    reply_value_lookup: dict[str, tuple[str, ...] | None] = field(default_factory=dict)
    latest_message: str = ""
    message_history: list[str] = field(default_factory=list)
    # Non-empty disclosure messages for raw-text retrieval within the active intent.
    current_intent_messages: list[str] = field(default_factory=list)
    turn: int = 0
    typed_constraints: list = field(default_factory=list)
    preference_tags: tuple[str, ...] = field(init=False)
    turn_delta: ObservationExtract | None = None
    candidate_count: int | None = None
    previous_candidate_count: int | None = None
    candidate_count_before_delta: int | None = None
    exact_strict: set[str] | None = None
    exact_lenient: set[str] | None = None
    router_prompt_tokens: int = 0
    router_completion_tokens: int = 0
    scoring_weights: RecommendationScoreWeights = field(
        default_factory=_default_scoring_weights
    )
    recommendation_preference_position: float = 34.375
    recommendation_preference_locked: bool = False

    def __post_init__(self) -> None:
        self.preference_tags = preference_tags_from_profile(self.user_profile)

    @property
    def ranking_constraints(self) -> tuple[str, ...]:
        """Cited-string union for the regex / kit path only.

        NLU retrieve and the NLU console use ``typed_constraints``.
        """

        values = [*self.active_constraints]
        if not self.override_seen:
            values.extend(self.legacy_hints)
        return tuple(dict.fromkeys(values))

    def locked_constraint_strings(self) -> tuple[str, ...]:
        """Surfaces the attribute LLM should treat as already locked.

        NLU uses typed slot surfaces. Regex and ``/constraints`` seed still
        use ``active_constraints``.
        """

        if self.typed_constraints:
            return tuple(
                slot.surface.strip()
                for slot in self.typed_constraints
                if str(slot.surface).strip()
            )
        return tuple(self.active_constraints)

    @property
    def empty_disclosure_reveal(self) -> bool:
        """Decide should show a full Top-K slate: shopper added nothing this turn."""

        return self.disclosure_empty is True

    @property
    def current_intent_text(self) -> str:
        """Natural-language evidence for the active intent only."""

        return " ".join(
            message.strip()
            for message in self.current_intent_messages[-4:]
            if message.strip()
        )

    def begin_turn(self, message: str, turn: int) -> None:
        """Apply guaranteed previous-miss feedback, then parse this observation."""

        from .lifecycle import begin_turn as _begin_turn

        _begin_turn(self, message, turn)

    def _add_constraint(self, value: str, *, disclosed: bool = True) -> None:
        from ..attributes.capture import add_constraint

        add_constraint(self, value, disclosed=disclosed)

    def _apply_override(self, new_value: str | None) -> None:
        from .gate import apply_override

        apply_override(self, new_value)

    def observe(self, message: str) -> None:
        from ..observation.coordinator import observe

        observe(self, message)

    def record_action(self, slate: list[str], ask_attribute: str | None) -> None:
        from ...decide.response.writeback import record_action

        record_action(self, slate, ask_attribute)

    def set_reply_options(self, options: list[tuple[str, ...]]) -> None:
        self.reply_value_lookup = build_reply_lookup(options)
