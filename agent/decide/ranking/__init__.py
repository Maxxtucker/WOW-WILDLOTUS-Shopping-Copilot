"""Purpose: optional semantic reranking, then RankedCandidate posterior.

Input: SearchHit list plus current SessionState and catalog access.
Output: RankedCandidate list.
Role: pipeline stage 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .belief import BELIEF_TEMPERATURE, belief_from_hits
from .normalize import RankedCandidate, normalize_probabilities
from .semantic import (
    DEFAULT_MODEL,
    QwenSemanticReranker,
    RerankerConfig,
    build_product_document,
    build_shopping_query,
    semantic_belief,
)

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...retrieve.catalog.types import SearchHit
    from ...understand.state.session import SessionState


class Ranker:
    """Stage 6: Qwen head reranking with deterministic score fallback."""

    def __init__(
        self,
        retriever: CatalogRetriever | None = None,
        semantic: QwenSemanticReranker | None = None,
    ) -> None:
        self.retriever = retriever
        self.semantic = semantic or QwenSemanticReranker()

    def apply(
        self,
        hits: list[SearchHit],
        state: SessionState | None = None,
    ) -> list[RankedCandidate]:
        if state is not None and self.retriever is not None:
            semantic = self.semantic.belief(state, hits, self.retriever)
            if semantic is not None:
                return normalize_probabilities(semantic)
        return normalize_probabilities(belief_from_hits(hits))


__all__ = [
    "BELIEF_TEMPERATURE",
    "DEFAULT_MODEL",
    "QwenSemanticReranker",
    "RankedCandidate",
    "Ranker",
    "RerankerConfig",
    "belief_from_hits",
    "build_product_document",
    "build_shopping_query",
    "normalize_probabilities",
    "semantic_belief",
]
