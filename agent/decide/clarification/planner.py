"""Purpose: one-step joint search over “which attribute to ask” × “how many products to expose”.

Input: SessionState, RankedCandidate, top_k, answer_signature.
Output: Plan (slate + ask_attribute + expected_value).
Role: dumping an uncertain Top-10 too early loses score; turn 10 and empty disclosure are a full slate with no question.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import math
from typing import TYPE_CHECKING

from .distinguish import future_value, terminal_value
from .questions import eligible_questions
from .types import Plan
from .utility import hit_utility

if TYPE_CHECKING:
    from ..ranking.normalize import RankedCandidate
    from ...understand.state.session import SessionState


class ScoreAwarePlanner:
    """One-step finite-horizon planner over question and slate-size actions.

    The look-ahead is intentionally small: it is deterministic, fast on CPU,
    and captures the main competition-specific trade-off—an uncertain rank-10
    hit now can be worse than a rank-1 hit after one informative answer.
    """

    def __init__(self, max_planning_candidates: int = 500) -> None:
        self.max_planning_candidates = max_planning_candidates

    def _terminal_value(self, candidates: Sequence[RankedCandidate], turn: int) -> float:
        return terminal_value(candidates, turn)

    def _future_value(
        self,
        residual: Sequence[RankedCandidate],
        attribute: str | None,
        next_turn: int,
        answer_signature: Callable[[str, str], tuple[str, ...]],
    ) -> float:
        return future_value(
            residual,
            attribute,
            next_turn,
            answer_signature,
            self.max_planning_candidates,
        )

    def _eligible_questions(
        self,
        state: SessionState,
        candidates: Sequence[RankedCandidate],
        answer_signature: Callable[[str, str], tuple[str, ...]],
    ) -> list[str | None]:
        return eligible_questions(
            state, candidates, answer_signature, self.max_planning_candidates
        )

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

        if state.empty_disclosure_reveal:
            slate = tuple(item.parent_asin for item in candidates[:top_k])
            return Plan(
                slate,
                None,
                self._terminal_value(candidates, state.turn),
                "empty disclosure",
            )

        questions = self._eligible_questions(state, candidates, answer_signature)

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
