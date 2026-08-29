"""Purpose: optional semantic reranking, then RankedCandidate posterior.

Input: SearchHit list plus current SessionState and catalog access.
Output: RankedCandidate list.
Role: pipeline stage 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...progress import emit, skip_nodes
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
            emit("retrieve", "qwen_rerank", "running")
            semantic = self.semantic.belief(state, hits, self.retriever)
            if semantic is not None:
                emit(
                    "retrieve",
                    "qwen_rerank",
                    "completed",
                    {
                        "input": {"hits": len(hits)},
                        "output": {"reranked": len(semantic)},
                    },
                )
                skip_nodes(
                    "retrieve",
                    "belief_hits",
                    why="Qwen reranker available",
                )
                ranked = normalize_probabilities(semantic)
                emit(
                    "retrieve",
                    "normalize",
                    "completed",
                    {
                        "input": {"path": "qwen"},
                        "output": {"count": len(ranked)},
                        "count": len(ranked),
                    },
                )
                return ranked
            emit(
                "retrieve",
                "qwen_rerank",
                "skipped",
                {"why": "reranker unavailable or off"},
            )
        else:
            skip_nodes(
                "retrieve",
                "qwen_rerank",
                why="no session or catalog for semantic head",
            )
        emit("retrieve", "belief_hits", "running")
        weights = belief_from_hits(hits)
        emit(
            "retrieve",
            "belief_hits",
            "completed",
            {
                "input": {"hits": len(hits)},
                "output": {"weighted": len(weights)},
            },
        )
        ranked = normalize_probabilities(weights)
        emit(
            "retrieve",
            "normalize",
            "completed",
            {
                "input": {"path": "belief"},
                "output": {"count": len(ranked)},
                "count": len(ranked),
            },
        )
        return ranked


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
