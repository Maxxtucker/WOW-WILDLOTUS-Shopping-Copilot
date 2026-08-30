"""Purpose: swappable stage Protocols so a later LLM implementation can replace a stage without changing pipeline.

Input / Output: each Protocol.apply signature is that stage's I/O.
Role: structural contract; there is no second implementation yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .retrieve.catalog.retriever import CatalogRetriever
from .retrieve.catalog.types import SearchHit
from .decide.clarification.types import Plan
from .decide.ranking.normalize import RankedCandidate
from .understand.state.session import SessionState


class StateDetectStage(Protocol):
    def apply(self, state: SessionState, message: str, turn: int) -> SessionState:
        ...


class IntentRouterStage(Protocol):
    def apply(
        self, state: SessionState, retriever: CatalogRetriever
    ) -> set[str] | None:
        ...


class CandidateStage(Protocol):
    def apply(
        self, state: SessionState, exact: set[str] | None = None
    ) -> list[SearchHit]:
        ...


class RankingStage(Protocol):
    def apply(
        self,
        hits: list[SearchHit],
        state: SessionState | None = None,
    ) -> list[RankedCandidate]:
        ...


class ClarificationStage(Protocol):
    def apply(
        self,
        state: SessionState,
        ranked: list[RankedCandidate],
        top_k: int,
    ) -> tuple[Plan, list[str]]:
        ...


class ResponseStage(Protocol):
    def apply(
        self,
        state: SessionState,
        retriever: CatalogRetriever,
        candidate_asins: Sequence[str],
        plan: Plan,
        slate: list[str],
    ) -> dict:
        ...
