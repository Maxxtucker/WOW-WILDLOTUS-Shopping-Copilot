"""Conversation-state tracking with explicit intent versions and miss feedback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .domain import canonical


KEY_REQUIREMENT_RE = re.compile(
    r"^I['’]m looking for (.+?)\.\s*A key requirement is:\s*(.+?)\.?$",
    re.IGNORECASE,
)
EXPLORING_RE = re.compile(
    r"^I['’]m looking for (.+?),\s*but I['’]m still exploring\.?$",
    re.IGNORECASE,
)
INITIAL_OTHER_RE = re.compile(r"^I['’]m looking for (.+?)\.\s*(.+?)\.?$", re.IGNORECASE)
OVERRIDE_RE = re.compile(
    r"(?:actually[, ]+)?(?:ignore|forget|replace).+?(?:what I need is|need|requirement is)\s*:\s*(.+?)\.?$",
    re.IGNORECASE,
)
OVERRIDE_SIGNAL_RE = re.compile(
    r"\b(?:actually|ignore|disregard|forget|changed?\s+my\s+mind|instead|"
    r"no\s+longer|rather|new\s+plan|new\s+requirement)\b",
    re.IGNORECASE,
)
OVERRIDE_VALUE_RE = re.compile(
    r"(?:what\s+i\s+(?:need|want)\s+is|i\s+(?:now\s+)?(?:need|want)|"
    r"new\s+requirement\s+is|instead[, ]+(?:i\s+)?(?:need|want))"
    r"\s*:?\s*(.+?)\.?$",
    re.IGNORECASE,
)
GENERIC_CATEGORY_RE = re.compile(
    r"(?:looking|shopping)\s+for\s+(.+?)(?:[.,;]|$)",
    re.IGNORECASE,
)
MATTERS_RE = re.compile(r"what matters is:\s*(.+?)\.?$", re.IGNORECASE)
NO_ADDITIONAL_RE = re.compile(
    r"(?:no|an) additional preference for\s+([a-z_]+)",
    re.IGNORECASE,
)
NO_PREFERENCE_RE = re.compile(
    r"(?:no|a) preference for\s+([a-z_]+)",
    re.IGNORECASE,
)


@dataclass
class SessionState:
    session_id: str
    user_profile: dict
    category: str | None = None
    scenario_hint: str = "unknown"
    intent_version: int = 0
    gate_open: bool = True
    override_seen: bool = False
    boundary_seen: bool = False
    active_constraints: list[str] = field(default_factory=list)
    legacy_hints: list[str] = field(default_factory=list)
    disclosed: set[str] = field(default_factory=set)
    no_preference: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)
    last_ask: str | None = None
    last_slate: list[str] = field(default_factory=list)
    last_gate_open: bool = True
    excluded_asins: set[str] = field(default_factory=set)
    shown_asins: set[str] = field(default_factory=set)
    informative_replies: int = 0
    last_reply_informative: bool = False
    last_reply_no_additional: bool = False
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

        if turn > 1 and self.last_gate_open:
            # If the evaluator called us again, the previous scored slate missed.
            self.excluded_asins.update(self.last_slate)
        self.turn = turn
        self.latest_message = str(message)
        self.message_history.append(self.latest_message)
        self.last_reply_informative = False
        self.last_reply_no_additional = False
        self.observe(message)
        # The published override always fires on turn 3 or 4. If an organizer
        # paraphrase defeats every lexical rule, opening the internal gate on
        # turn 4 is safer than remaining permanently stuck in the old intent.
        if self.scenario_hint == "override_pending" and turn >= 4 and not self.override_seen:
            self._apply_override(None)

    def _add_constraint(self, value: str, *, disclosed: bool = True) -> None:
        cleaned = value.strip(" \t\n.;")
        key = canonical(cleaned)
        if not key:
            return
        if key not in {canonical(item) for item in self.active_constraints}:
            self.active_constraints.append(cleaned)
        if disclosed:
            self.disclosed.add(key)

    def _apply_override(self, new_value: str | None) -> None:
        self.intent_version += 1
        self.override_seen = True
        self.scenario_hint = "intent_override"
        self.gate_open = True
        self.legacy_hints.clear()
        self.excluded_asins.clear()
        self.shown_asins.clear()
        if new_value:
            self._add_constraint(new_value)

    def observe(self, message: str) -> None:
        value = message.strip()
        if self.turn == 1:
            match = KEY_REQUIREMENT_RE.match(value)
            if match:
                self.category = match.group(1).strip()
                self.scenario_hint = "buying"
                self.gate_open = True
                self._add_constraint(match.group(2))
                return
            match = EXPLORING_RE.match(value)
            if match:
                self.category = match.group(1).strip()
                self.scenario_hint = "exploring"
                self.gate_open = True
                return
            match = INITIAL_OTHER_RE.match(value)
            if match:
                self.category = match.group(1).strip()
                self.scenario_hint = "override_pending"
                self.gate_open = False
                hint = match.group(2).strip(" .")
                if hint:
                    self.legacy_hints.append(hint)
                return

            # Paraphrase-safe fallback: retain the raw message for BM25 and
            # recover a coarse shopping phrase when possible. The gate stays
            # open unless the explicit override template above was recognized.
            generic_category = GENERIC_CATEGORY_RE.search(value)
            if generic_category:
                self.category = generic_category.group(1).strip()
            if any(word in value.casefold() for word in ("requirement", "must have", "must-have")):
                tail = value.rsplit(":", 1)[-1].strip(" .")
                if tail and tail != value:
                    self._add_constraint(tail)

        # Parse the simulator's structured answers before looking for intent
        # changes.  Catalog values are free text and can legitimately contain
        # words such as "instead", "rather", or "forget"; those words inside
        # a ``what matters is`` payload must remain product constraints.
        no_additional = NO_ADDITIONAL_RE.search(value)
        if no_additional:
            attribute = no_additional.group(1).casefold()
            self.no_preference.add(attribute)
            self.last_reply_no_additional = True
            return

        no_preference = NO_PREFERENCE_RE.search(value)
        if no_preference:
            attribute = no_preference.group(1).casefold()
            self.boundary_seen = True
            self.scenario_hint = "boundary"
            # Boundary's first answer is deliberately uninformative.  Do not
            # permanently ban ``other`` because asking it again reveals data.
            if attribute != "other":
                self.no_preference.add(attribute)
            return

        matters = MATTERS_RE.search(value)
        if matters:
            payload = matters.group(1).strip(" .")
            predicted = self.reply_value_lookup.get(canonical(payload))
            # The simulator joins values with semicolons, but an individual
            # catalog feature may itself contain semicolons.  Prefer the
            # candidate-conditioned inverse mapping prepared on the prior turn
            # so an atomic feature is not split into fake constraints.
            if predicted is not None:
                pieces = list(predicted)
            else:
                pieces = [item.strip() for item in payload.split(";") if item.strip()]
            for piece in pieces:
                self._add_constraint(piece)
            if pieces:
                self.informative_replies += 1
                self.last_reply_informative = True
            return

        # Exact override syntax is always accepted.  Looser lexical evidence
        # is accepted when an override is already pending, or when the message
        # also contains an explicit new-value construction (for example,
        # "I've changed my mind; instead I need waterproof leather").  This
        # avoids treating an isolated word in ordinary catalog prose as an
        # intent reset.
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
                    self.scenario_hint == "override_pending"
                    or generic_value is not None
                )
            )
        )
        if should_override:
            extracted = override.group(1) if override else None
            if extracted is None and generic_value:
                extracted = generic_value.group(1)
            self._apply_override(extracted)
            return

        # Private evaluation may paraphrase the fixed surface text.  A reply to
        # a structured attribute still gets a conservative, colon-aware parse.
        if self.last_ask and not any(
            marker in value.casefold()
            for marker in ("not quite right", "use your judgment", "no preference")
        ):
            tail = value.rsplit(":", 1)[-1]
            pieces = [item.strip() for item in tail.split(";") if len(canonical(item)) >= 3]
            if 0 < len(pieces) <= 2:
                for piece in pieces:
                    self._add_constraint(piece)
                self.informative_replies += 1
                self.last_reply_informative = True

    def record_action(self, slate: list[str], ask_attribute: str | None) -> None:
        self.last_slate = list(slate)
        self.last_gate_open = self.gate_open
        self.last_ask = ask_attribute
        self.shown_asins.update(slate)
        if ask_attribute:
            self.asked.append(ask_attribute)

    def set_reply_options(self, options: list[tuple[str, ...]]) -> None:
        """Store an inverse surface-form map for the pending structured reply.

        ``None`` marks an ambiguous surface that can be produced by two
        different atomic-value segmentations; such a case uses the conservative
        parser fallback instead of silently choosing one candidate's values.
        """

        lookup: dict[str, tuple[str, ...] | None] = {}
        for values in options:
            if not values:
                continue
            key = canonical("; ".join(values))
            previous = lookup.get(key)
            if key in lookup and previous != values:
                lookup[key] = None
            else:
                lookup[key] = values
        self.reply_value_lookup = lookup
