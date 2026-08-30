"""Production adapter from ranked catalog candidates to Dynamic Slating.

The adapter is read-only: it predicts no-hit/answer branches from catalog
answer signatures without mutating the live SessionState or running NLU.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from ...domain import QUESTION_ATTRIBUTES
from ..ranking.normalize import RankedCandidate
from .dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateBranch,
    DynamicSlateState,
)
from .types import NO_ADDITIONAL
from .utility import hit_utility


# Intent-card coverage measured over the released 50,000-product catalog.
ATTRIBUTE_COVERAGE = {
    "other": 1.0000,
    "feature": 0.9580,
    "material": 0.5730,
    "color": 0.4270,
    "style": 0.1620,
    "size": 0.0757,
    "use_case": 0.0163,
    "budget": 0.0053,
}

# Conservative initial probability that a non-empty answer survives the live
# parser with the intended attribute/value. These are configuration priors,
# not claims of measured private-set accuracy.
PARSER_RELIABILITY = {
    "other": 0.65,
    "feature": 0.80,
    "material": 0.90,
    "color": 0.95,
    "style": 0.85,
    "size": 0.90,
    "use_case": 0.75,
    "budget": 0.95,
}


class CatalogSignatureTransitionModel:
    """Approximate answer transitions using catalog-native reply signatures."""

    def __init__(
        self,
        answer_signature: Callable[[str, str], tuple[str, ...]],
        *,
        max_candidates: int = 80,
        max_typed_branches: int = 12,
        max_other_branches: int = 4,
        tail_floor: float = 0.20,
        tail_retrieval_success: float = 0.55,
        min_effective_coverage: float = 0.10,
    ) -> None:
        self.answer_signature = answer_signature
        self.max_candidates = max(1, int(max_candidates))
        self.max_typed_branches = max(2, int(max_typed_branches))
        self.max_other_branches = max(2, int(max_other_branches))
        self.tail_floor = max(0.0, min(float(tail_floor), 0.95))
        self.tail_retrieval_success = max(
            0.0, min(float(tail_retrieval_success), 1.0)
        )
        self.min_effective_coverage = max(
            0.0, min(float(min_effective_coverage), 1.0)
        )
        self._serial = 0

    def root_state(
        self,
        *,
        turn: int,
        candidates: Sequence[RankedCandidate],
        questions: Sequence[str | None],
        gate_open: bool,
    ) -> DynamicSlateState:
        raw_head = tuple(candidates[: self.max_candidates])
        raw_mass = sum(item.probability for item in raw_head)
        natural_tail = max(0.0, 1.0 - raw_mass)
        tail = max(natural_tail, self.tail_floor if candidates else 1.0)
        head_budget = max(0.0, 1.0 - tail)
        scale = 0.0 if raw_mass <= 0.0 else head_budget / raw_mass
        head = tuple(
            RankedCandidate(item.parent_asin, item.score, item.probability * scale)
            for item in raw_head
        )
        # Filter questions by viability; before turn 10, ensure no None-only fallback
        filtered_questions = tuple(
            question for question in questions
            if self._question_is_viable(question)
        )
        if turn < 10 and not filtered_questions:
            # Ensure a concrete attribute is available even if all were filtered.
            # Use the first viable concrete attribute from QUESTION_ATTRIBUTES.
            for attr in ("feature", "material", "color", "other"):
                if self._question_is_viable(attr):
                    filtered_questions = (attr,)
                    break
        final_questions = filtered_questions or (None,)
        return DynamicSlateState(
            turn=turn,
            candidates=head,
            questions=final_questions,
            gate_probability=1.0 if gate_open else 0.0,
            tail_probability=tail,
            cache_key=self._next_key("root"),
        )

    def branches(
        self,
        state: DynamicSlateState,
        action: DynamicSlateAction,
    ) -> tuple[DynamicSlateBranch, ...]:
        weighted = self._no_hit_candidates(state, action.slate_size)
        if state.turn >= 10:
            return ()

        groups: dict[tuple[str, ...], list[tuple[RankedCandidate, float]]] = (
            defaultdict(list)
        )
        if action.ask_attribute is None:
            groups[("__no_information__",)] = weighted
        else:
            coverage = ATTRIBUTE_COVERAGE.get(action.ask_attribute, 0.0)
            parser_reliability = PARSER_RELIABILITY.get(
                action.ask_attribute, 0.50
            )
            useful_probability = coverage * parser_reliability
            for item, mass in weighted:
                signature = self.answer_signature(
                    item.parent_asin, action.ask_attribute
                )
                if signature == NO_ADDITIONAL:
                    groups[NO_ADDITIONAL].append((item, mass))
                    continue
                useful_mass = mass * useful_probability
                no_information_mass = mass - useful_mass
                if useful_mass > 0.0:
                    groups[signature].append((item, useful_mass))
                if no_information_mass > 0.0:
                    groups[("__no_information__",)].append(
                        (item, no_information_mass)
                    )

        limit = (
            self.max_other_branches
            if action.ask_attribute == "other"
            else self.max_typed_branches
        )
        compact = self._compact_groups(groups, limit)
        branches: list[DynamicSlateBranch] = []
        for observation, members in compact:
            branch_mass = sum(mass for _item, mass in members)
            if branch_mass <= 0.0:
                continue
            posterior = tuple(
                RankedCandidate(item.parent_asin, item.score, mass / branch_mass)
                for item, mass in members
            )
            next_questions = self._next_questions(
                state.questions,
                action.ask_attribute,
                posterior,
            )
            # A closed override gate becomes increasingly likely to open over
            # the two-step horizon without claiming knowledge of its exact turn.
            next_gate = min(1.0, state.gate_probability + 0.5)
            next_state = DynamicSlateState(
                turn=min(10, state.turn + 1),
                candidates=posterior,
                questions=next_questions,
                gate_probability=next_gate,
                cache_key=self._next_key("branch"),
            )
            branches.append(
                DynamicSlateBranch(
                    observation=" | ".join(observation),
                    probability=branch_mass,
                    next_state=next_state,
                )
            )
        branches.extend(self._tail_branches(state, action))
        return tuple(branches)

    def _tail_branches(
        self,
        state: DynamicSlateState,
        action: DynamicSlateAction,
    ) -> tuple[DynamicSlateBranch, ...]:
        """Approximate products outside the planning head as recovery branches."""

        tail = state.tail_probability
        if tail <= 0.0:
            return ()
        if action.ask_attribute is None:
            useful_probability = 0.0
        else:
            useful_probability = ATTRIBUTE_COVERAGE.get(
                action.ask_attribute, 0.0
            ) * PARSER_RELIABILITY.get(action.ask_attribute, 0.50)
        useful_mass = tail * useful_probability
        no_information_mass = tail - useful_mass
        next_turn = min(10, state.turn + 1)
        next_gate = min(1.0, state.gate_probability + 0.5)
        result: list[DynamicSlateBranch] = []
        if useful_mass > 0.0:
            result.append(
                DynamicSlateBranch(
                    observation="__tail_retrieval__",
                    probability=useful_mass,
                    next_state=DynamicSlateState(
                        turn=next_turn,
                        candidates=(),
                        questions=(None,),
                        gate_probability=next_gate,
                        tail_probability=1.0,
                        tail_value=(
                            self.tail_retrieval_success
                            * hit_utility(next_turn, 1)
                        ),
                        cache_key=self._next_key("tail-recovered"),
                    ),
                )
            )
        if no_information_mass > 0.0:
            result.append(
                DynamicSlateBranch(
                    observation="__tail_no_information__",
                    probability=no_information_mass,
                    next_state=DynamicSlateState(
                        turn=next_turn,
                        candidates=(),
                        questions=(None,),
                        gate_probability=next_gate,
                        tail_probability=1.0,
                        tail_value=0.0,
                        cache_key=self._next_key("tail-missed"),
                    ),
                )
            )
        return tuple(result)

    def _no_hit_candidates(
        self,
        state: DynamicSlateState,
        slate_size: int,
    ) -> list[tuple[RankedCandidate, float]]:
        weighted: list[tuple[RankedCandidate, float]] = []
        for index, item in enumerate(state.candidates):
            survives = 1.0
            if index < slate_size:
                survives -= state.gate_probability
            mass = item.probability * survives
            if mass > 0.0:
                weighted.append((item, mass))
        return weighted

    def _next_questions(
        self,
        questions: tuple[str | None, ...],
        asked: str | None,
        candidates: tuple[RankedCandidate, ...],
    ) -> tuple[str | None, ...]:
        if not candidates:
            return (None,)
        result: list[str | None] = [None]
        for attribute in questions:
            if attribute is None or attribute == asked:
                continue
            if not self._question_is_viable(attribute):
                continue
            signatures = {
                self.answer_signature(item.parent_asin, attribute)
                for item in candidates
            }
            if len(signatures) > 1 or (
                signatures and next(iter(signatures)) != NO_ADDITIONAL
            ):
                result.append(attribute)
        return tuple(result)

    def _question_is_viable(self, attribute: str | None) -> bool:
        if attribute is None:
            return True
        effective_coverage = ATTRIBUTE_COVERAGE.get(
            attribute, 0.0
        ) * PARSER_RELIABILITY.get(attribute, 0.50)
        return effective_coverage >= self.min_effective_coverage

    @staticmethod
    def _compact_groups(
        groups: dict[tuple[str, ...], list[tuple[RankedCandidate, float]]],
        limit: int,
    ) -> list[tuple[tuple[str, ...], list[tuple[RankedCandidate, float]]]]:
        ordered = sorted(
            groups.items(),
            key=lambda row: -sum(mass for _item, mass in row[1]),
        )
        if len(ordered) <= limit:
            return ordered
        kept = ordered[: limit - 1]
        overflow: list[tuple[RankedCandidate, float]] = []
        for _observation, members in ordered[limit - 1 :]:
            overflow.extend(members)
        overflow.sort(key=lambda row: -row[1])
        kept.append((("__other_answers__",), overflow))
        return kept

    def _next_key(self, prefix: str) -> str:
        self._serial += 1
        return f"{prefix}:{self._serial}"
