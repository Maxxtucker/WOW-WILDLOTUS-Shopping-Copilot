"""Score-aware joint recommendation-slate and clarification planning."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import math

from .domain import QUESTION_ATTRIBUTES
from .state import SessionState


NO_ADDITIONAL = ("__no_additional__",)


@dataclass(frozen=True)
class RankedCandidate:
    parent_asin: str
    score: float
    probability: float


@dataclass(frozen=True)
class Plan:
    recommendations: tuple[str, ...]
    ask_attribute: str | None
    expected_value: float
    reason: str


def hit_utility(turn: int, rank: int) -> float:
    """Exact per-session contribution to the official technical composite."""

    return 0.50 + 0.30 / rank + 0.02 * (11 - turn)


def normalize_probabilities(items: Sequence[tuple[str, float]]) -> list[RankedCandidate]:
    if not items:
        return []
    finite = [(asin, max(float(weight), 1e-12)) for asin, weight in items]
    total = sum(weight for _, weight in finite)
    return [
        RankedCandidate(asin, weight, weight / total)
        for asin, weight in sorted(finite, key=lambda item: (-item[1], item[0]))
    ]


class ScoreAwarePlanner:
    """One-step finite-horizon planner over question and slate-size actions.

    The look-ahead is intentionally small: it is deterministic, fast on CPU,
    and captures the main competition-specific trade-off—an uncertain rank-10
    hit now can be worse than a rank-1 hit after one informative answer.
    """

    def __init__(
        self,
        max_planning_candidates: int = 500,
        *,
        question_priority: Sequence[str] | None = None,
        question_policy: str = "dynamic",
    ) -> None:
        self.max_planning_candidates = max_planning_candidates
        priority = tuple(question_priority or QUESTION_ATTRIBUTES)
        if set(priority) != set(QUESTION_ATTRIBUTES) or len(priority) != len(QUESTION_ATTRIBUTES):
            raise ValueError("question_priority must contain every supported question exactly once")
        if question_policy not in {"dynamic", "static"}:
            raise ValueError("question_policy must be 'dynamic' or 'static'")
        self.question_priority = priority
        self.question_policy = question_policy

    @staticmethod
    def _terminal_value(candidates: Sequence[RankedCandidate], turn: int) -> float:
        return sum(
            item.probability * hit_utility(turn, rank)
            for rank, item in enumerate(candidates[:10], start=1)
        )

    def _future_value(
        self,
        residual: Sequence[RankedCandidate],
        attribute: str | None,
        next_turn: int,
        answer_signature: Callable[[str, str], tuple[str, ...]],
    ) -> float:
        if not residual or next_turn > 10:
            return 0.0
        if attribute is None:
            return self._terminal_value(residual, next_turn)

        groups: dict[tuple[str, ...], list[RankedCandidate]] = defaultdict(list)
        for item in residual[: self.max_planning_candidates]:
            groups[answer_signature(item.parent_asin, attribute)].append(item)

        # Probabilities remain unconditional here.  Summing each branch's
        # top-10 terminal reward therefore already integrates branch mass.
        return sum(self._terminal_value(group, next_turn) for group in groups.values())

    def _eligible_questions(
        self,
        state: SessionState,
        candidates: Sequence[RankedCandidate],
        answer_signature: Callable[[str, str], tuple[str, ...]],
    ) -> list[str | None]:
        if state.turn >= 10:
            return [None]
        result: list[str | None] = [None]
        for attribute in self.question_priority:
            if attribute in state.no_preference:
                continue
            signatures = {
                answer_signature(item.parent_asin, attribute)
                for item in candidates[: self.max_planning_candidates]
            }
            informative = {value for value in signatures if value != NO_ADDITIONAL}
            if not informative:
                continue
            # Repeated ``other`` is useful because it reveals the next pair of
            # undisclosed constraints. Typed attributes are not repeated.
            if attribute != "other" and attribute in state.asked:
                continue
            result.append(attribute)
            # A static policy is defined as the first eligible, informative
            # attribute in its configured order. Later attributes cannot alter
            # its action, so their counterfactual signatures are unnecessary.
            if self.question_policy == "static":
                break
        return result

    def plan(
        self,
        state: SessionState,
        ranked: Sequence[RankedCandidate],
        top_k: int,
        answer_signature: Callable[[str, str], tuple[str, ...]],
    ) -> Plan:
        candidates = list(ranked[: self.max_planning_candidates])
        if not candidates:
            ask = None if state.turn >= 10 else "other"
            return Plan((), ask, 0.0, "empty candidate pool")

        if state.turn >= 10:
            slate = tuple(item.parent_asin for item in candidates[:top_k])
            return Plan(slate, None, self._terminal_value(candidates, state.turn), "final turn")

        questions = self._eligible_questions(state, candidates, answer_signature)
        if self.question_policy == "static":
            first_typed = next((value for value in questions if value is not None), None)
            questions = [first_typed] if first_typed is not None else [None]

        # Before an intent override, hits are disabled.  Showing one provisional
        # candidate is useful to a human demo but does not censor the belief.
        if not state.gate_open:
            best_question = max(
                questions,
                key=lambda attribute: self._future_value(
                    candidates, attribute, state.turn + 1, answer_signature
                ),
            )
            return Plan(
                (candidates[0].parent_asin,),
                best_question,
                self._future_value(candidates, best_question, state.turn + 1, answer_signature),
                "waiting for intent override gate",
            )

        best: Plan | None = None
        max_k = min(top_k, len(candidates))
        for attribute in questions:
            # A null question cannot improve the next observation.  It is still
            # evaluated as the robustness baseline.
            for size in range(0, max_k + 1):
                slate = candidates[:size]
                immediate = sum(
                    item.probability * hit_utility(state.turn, rank)
                    for rank, item in enumerate(slate, start=1)
                )
                residual = candidates[size:]
                future = self._future_value(
                    residual,
                    attribute,
                    state.turn + 1,
                    answer_signature,
                )
                value = immediate + future

                # Exact ties prefer an informative question, then a smaller
                # slate.  This prevents needless low-rank terminal hits.
                tie_break = (attribute is not None, -size)
                current_break = (
                    best is not None and best.ask_attribute is not None,
                    -(len(best.recommendations) if best else 0),
                )
                if best is None or value > best.expected_value + 1e-12 or (
                    math.isclose(value, best.expected_value, abs_tol=1e-12)
                    and tie_break > current_break
                ):
                    best = Plan(
                        tuple(item.parent_asin for item in slate),
                        attribute,
                        value,
                        f"joint one-step utility, slate={size}",
                    )
        assert best is not None
        return best


def explain_question(attribute: str | None) -> str:
    templates = {
        "material": "Do you have a preferred material?",
        "color": "Which color would you prefer?",
        "size": "Do you have a size or fit requirement?",
        "style": "What style or fit should I prioritize?",
        "budget": "What budget range should I use?",
        "feature": "Which product feature matters most to you?",
        "use_case": "What will you mainly use the product for?",
        "other": "What other requirements matter most to you?",
        "category": "Which product category should I focus on?",
        "brand": "Do you have a preferred brand?",
    }
    return templates.get(attribute, "I have enough information to refine the shortlist.")
