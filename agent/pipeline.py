"""Purpose: one-turn orchestration: understand → retrieve → decide.

Input: SessionState, user_message, turn, top_k.
Output: official respond dict.
Role: StateDetector.apply runs observe (category / constraints / override) in fixed order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .decide.clarification.planner import ScoreAwarePlanner
from .decide.clarification.stage import Clarifier
from .decide.ranking import Ranker
from .decide.response.builder import ResponseBuilder
from .retrieve.candidates.retrieve import CandidateOrganizer
from .retrieve.filtering.exact_pool import ProductFilter
from .understand.state.lifecycle import StateDetector

if TYPE_CHECKING:
    from .retrieve.catalog.retriever import CatalogRetriever
    from .understand.state.session import SessionState


class TurnPipeline:
    """Run one evaluator turn: observe, retrieve, rank, plan, respond."""

    def __init__(
        self,
        retriever: CatalogRetriever,
        planner: ScoreAwarePlanner | None = None,
    ) -> None:
        self.retriever = retriever
        self.state_detector = StateDetector()
        self.filter = ProductFilter(retriever)
        self.organizer = CandidateOrganizer(retriever)
        self.ranker = Ranker()
        self.clarifier = Clarifier(retriever, planner)
        self.responder = ResponseBuilder()

    def run(
        self,
        state: SessionState,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        self.state_detector.apply(state, user_message, turn)
        exact = self.filter.apply(state)
        hits = self.organizer.apply(state, exact)
        ranked = self.ranker.apply(hits)
        plan, slate = self.clarifier.apply(state, ranked, top_k)
        return self.responder.apply(state, self.retriever, hits, plan, slate)
